"""License Manager — **registro delle licenze emesse** (issue #140, opzione A).

Oggi l'emissione di una licenza è **stateless**: il tool produce un token e non registra nulla.
Questo modulo aggiunge un **registro locale** sul PC del proprietario — `licenses.jsonl`
nella cartella del License Manager (`%APPDATA%\\XTraderLicenseManager`, la stessa del seed privato,
mai nel repo/EXE) — così il proprietario può **ritrovare** chi ha ricevuto cosa, con che scadenza, e
(in una fase successiva) **rinnovare/revocare** da un elenco.

Logica **pura e fail-safe**, senza GUI:

- il **serial** di una licenza è **deterministico** dal token firmato (`license_serial`): sia il tool
  (che ha appena emesso il token) sia — in futuro — il bridge (che ha il token attivato) calcolano lo
  **stesso** identificatore, senza aggiungere campi al formato token (nessuna migrazione);
- il record si costruisce **dal payload del token** (`record_from_token`), così il registro combacia
  sempre con la licenza realmente firmata (nome/hardware/scadenza autoritativi);
- la scrittura e' **append-only** con UNA sola eccezione dichiarata: `remove_record`, che elimina
  una riga riscrivendo il file in modo atomico. Non tocca `revoked.jsonl`, quindi **non riattiva**
  un revocato; ma ne fa sparire la riga dalla vista — vedi il suo docstring;
- append-only robusto (stesso idiom di `xtrader_bridge.event_journal`: guardia sulla riga troncata +
  `flush`/`fsync`, lettura tollerante che salta le righe malformate);
- **nessun segreto**: il registro contiene il **token di attivazione** (che il proprietario dà
  comunque all'utente, legato a un singolo hardware) e i suoi metadati — **mai** il seed privato.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading

# Serial deterministico condiviso: vive in `xtrader_bridge.licensing.license` (pacchetto condiviso) così
# il **bridge** (revoca online R3c) lo calcola IDENTICO senza importare `license_manager`. Ri-esportato
# qui come `registry.license_serial` per compatibilità con i chiamanti/test esistenti.
from xtrader_bridge.licensing.license import license_serial

from . import log_safe
from .core import _fsync_dir, manager_dir

_log = log_safe.get_logger(__name__)

REGISTRY_FILE = "licenses.jsonl"

# Store delle **revoche** (issue #140 R3b): stesso idiom append-only fail-safe del registro licenze,
# file separato nella cartella del License Manager. Contiene SOLO serial/hardware/nome + timestamp —
# **mai** il seed privato. La lista firmata che il bridge scarica si produce da qui (R3b) verificandola
# con `xtrader_bridge.licensing.revocation` (R3a).
REVOKED_FILE = "revoked.jsonl"

_SECONDS_PER_DAY = 86_400

# Stati mostrati nella vista (calcolati, mai persistiti: dipendono da "adesso").
STATUS_ACTIVE = "ATTIVA"
STATUS_EXPIRED = "SCADUTA"
# Stato di VISTA, non del record: la revoca vive in `revoked.jsonl`, non dentro la licenza. Prima
# esistevano solo i due stati sopra, e una licenza revocata continuava a comparire «ATTIVA» — la
# revoca veniva registrata e pubblicata correttamente, ma il proprietario non aveva modo di
# **vederla**, e poteva credere che non avesse funzionato o rinnovare per sbaglio un revocato.
STATUS_REVOKED = "REVOCATA"


def normalize_serial(value) -> str:
    """Serial normalizzato per il CONFRONTO: spazi ai bordi via, maiuscole.

    Fonte unica della regola (rilievo CodeRabbit): la stessa normalizzazione serviva in quattro
    punti — ricerca per serial, marcatura dei revocati, stato della riga, lettura dello store nella
    GUI. Quattro copie oggi sono quattro regole divergenti domani, ed è esattamente la classe di
    difetto che il repository ha già pagato altrove."""
    return str(value or "").strip().upper()

# Serializza gli append tra thread del processo (coerente con event_journal).
_WRITE_LOCK = threading.Lock()

# Alias **pubblico** dello stesso lock. Serve a chi deve fare un read-modify-write su questi store
# senza perdere un append concorrente — oggi `backup.restore_backup`, che fonde i registri
# append-only (#184). Dev'essere lo **stesso** oggetto, non un lock nuovo: un lock diverso non
# serializzerebbe nulla. Esposto invece di far raggiungere il privato da fuori.
WRITE_LOCK = _WRITE_LOCK


def registry_path(directory: "str | None" = None) -> str:
    """Percorso del registro (`licenses.jsonl`) nella cartella data o in `manager_dir()`."""
    return os.path.join(directory or manager_dir(), REGISTRY_FILE)


def _b64u_decode(segment: str) -> bytes:
    """Decodifica base64url **senza padding** (come le scrive `license._b64u_encode`)."""
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def decode_token_payload(token: str) -> dict:
    """Payload (dict) di un token licenza `<b64u(payload)>.<b64u(sig)>`, **senza** verificarne la
    firma (la firma la verifica il bridge; qui serve solo a leggere i metadati che ABBIAMO appena
    firmato). Solleva `ValueError` se il token non è nel formato atteso."""
    parts = str(token).split(".")
    if len(parts) != 2 or not parts[0]:
        raise ValueError("token licenza malformato (atteso <payload>.<firma>)")
    try:
        payload = json.loads(_b64u_decode(parts[0]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"payload del token non decodificabile: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload del token non è un oggetto JSON")
    return payload


def record_from_token(token: str, *, now: int) -> dict:
    """Costruisce il **record di registro** da un token appena emesso, leggendone il payload
    (nome/hardware/emissione/scadenza autoritativi). `now` = istante di registrazione (unix).

    Il record contiene: `serial` (deterministico), `name`, `hardware_id`, `issued`, `expiry`,
    `days` (derivati dal payload), il `token` (per ri-invio/rinnovo futuri) e `recorded_at`.
    Solleva `ValueError` su token malformato o payload incompleto (fail-closed: non si registra una
    licenza che non sappiamo interpretare)."""
    payload = decode_token_payload(token)
    try:
        name = str(payload["name"])
        hardware_id = str(payload["hw"])
        issued = int(payload["iss"])
        expiry = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"payload del token incompleto/non valido: {type(exc).__name__}") from exc
    days = max(1, round((expiry - issued) / _SECONDS_PER_DAY))
    return {
        "serial": license_serial(token),
        "name": name,
        "hardware_id": hardware_id,
        "issued": issued,
        "expiry": expiry,
        "days": days,
        "token": str(token),
        "recorded_at": int(now),
    }


def _ends_without_newline(path: str) -> bool:
    """`True` se il file esiste, è non vuoto e NON termina con `\\n` (ultima riga troncata da un
    crash a metà append). Stesso guard di `event_journal`."""
    try:
        if os.path.getsize(path) == 0:
            return False
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"
    except OSError:
        return False


def append_record(record: dict, *, directory: "str | None" = None) -> dict:
    """Appende UN record al registro (creando la cartella se serve), con `flush`+`fsync` e la guardia
    anti riga-troncata (separatore+riga+`\\n` in **una sola** write). Ritorna il record scritto.

    Gli errori di I/O **propagano**: il chiamante (GUI) li tratta best-effort — un fallimento di
    registrazione **non** deve bloccare l'emissione della licenza."""
    path = registry_path(directory)
    line = json.dumps(record, ensure_ascii=False)
    with _WRITE_LOCK:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        prefix = "\n" if _ends_without_newline(path) else ""
        with open(path, "a", encoding="utf-8") as f:
            f.write(prefix + line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return record


def remove_record(serial, *, directory: "str | None" = None) -> int:
    """**Elimina** dal registro tutti i record con quel `serial`. Ritorna quanti ne ha rimossi.

    È l'**unica** operazione non-append di questo modulo, e va letta sapendo cosa NON fa.

    **Non revoca e non de-revoca.** La revoca vive in `revoked.jsonl`, uno store separato: questa
    funzione non lo tocca. Eliminare la riga di un revocato **non lo riattiva** — la lista firmata
    che i bridge scaricano si costruisce da `revoked.jsonl` (`revocation_entries`), non da qui.
    È la trappola che ha già rischiato di far tornare attivi tutti i revocati nella PR-C (#194),
    e per questo è verificata da un test dedicato invece che lasciata al ragionamento.

    **Ma fa sparire quel serial dalla VISTA.** `view_rows` costruisce l'elenco dai record del
    registro e vi *sovrappone* i serial revocati: senza record non c'è riga, quindi una revoca
    ancora attiva diventa **invisibile** nel Registro. Chi chiama deve dirlo all'utente prima di
    procedere — la GUI lo fa con una conferma esplicita.

    **Riscrittura atomica**: si scrive un temporaneo nella stessa cartella e si fa `os.replace`,
    quindi un crash a metà lascia il registro **precedente intatto** invece di un file mezzo
    riscritto. È la stessa forma usata per il file-chiave in `core.save_signing_key`, ed è
    obbligatoria qui: a differenza di un append, questa operazione riscrive TUTTO il file.

    Serial vuoto/non trovato → `0`, nessuna scrittura (non si riscrive un file per nulla).
    Gli errori di I/O **propagano**, come in `append_record`."""
    voluto = normalize_serial(serial)
    if not voluto:
        return 0
    path = registry_path(directory)
    with _WRITE_LOCK:
        # Si filtrano le RIGHE GREZZE, non i record ri-serializzati (rilievo di Fable 5 e
        # CodeRabbit, indipendenti). Ri-costruire il file da `read_records` avrebbe scartato per
        # sempre le righe che quella funzione salta — vuote, troncate, non-dict — comprese quelle
        # di **altri** serial, che l'utente non ha chiesto di toccare. Su questo registro sarebbe
        # distruzione silenziosa: contiene l'unica copia del token di ogni licenza, e una riga
        # troncata da un crash è ancora recuperabile a mano finché resta sul disco.
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                righe = f.readlines()
        except OSError:
            return 0
        tenute, rimossi = [], 0
        for grezza in righe:
            testo = grezza.strip()
            if not testo:
                continue
            try:
                obj = json.loads(testo)
            except (json.JSONDecodeError, ValueError):
                obj = None
            if isinstance(obj, dict) and normalize_serial(obj.get("serial")) == voluto:
                rimossi += 1
                continue
            tenute.append(testo)      # illeggibile o di un altro serial → si TIENE
        if not rimossi:
            return 0
        payload = "".join(r + "\n" for r in tenute)
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".registry_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        # `fsync` della DIRECTORY dopo il rename (rilievo Fugu Ultra): l'fsync del file rende
        # durabile il CONTENUTO, non la voce di directory — un power-loss subito dopo `os.replace`
        # poteva lasciare il registro al contenuto vecchio. Riusa l'helper di `core`, che e' gia'
        # best-effort e non solleva (su Windows e' un no-op: la' il rename e' gia' atomico).
        _fsync_dir(parent)
    return rimossi


def read_records(*, directory: "str | None" = None, path: "str | None" = None) -> list:
    """Legge il registro come lista di record (dict), nell'ordine d'inserimento. Fail-safe: file
    assente → `[]`; righe vuote/malformate (es. l'ultima troncata) **saltate** senza crashare.
    `errors="replace"` come in `event_journal` (una coda UTF-8 rotta non fa fallire il replay)."""
    target = path or registry_path(directory)
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except OSError:
        return []
    out = []
    for raw in raw_lines:
        text = raw.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def revoked_registry_path(directory: "str | None" = None) -> str:
    """Percorso dello store revoche (`revoked.jsonl`) nella cartella data o in `manager_dir()`."""
    return os.path.join(directory or manager_dir(), REVOKED_FILE)


def revocation_record(record: dict, *, now: int) -> dict:
    """Costruisce il **record di revoca** da un record di licenza del registro (opzione B/R3b).

    Tiene `serial` (autoritativo per la revoca) più `name`/`hardware_id` come **metadati per la vista**
    del proprietario e `revoked_at` (unix). Solleva `ValueError` se il record non ha un `serial`
    (fail-closed: non si revoca «nulla»)."""
    serial = normalize_serial(record.get("serial"))
    if not serial:
        raise ValueError("record senza serial: impossibile revocare")
    return {
        "serial": serial,
        "name": str(record.get("name", "")),
        "hardware_id": str(record.get("hardware_id", "")),
        "revoked_at": int(now),
    }


def append_revocation(record: dict, *, directory: "str | None" = None) -> dict:
    """Appende UN record di revoca allo store (`revoked.jsonl`), con lo **stesso** append atomico
    (`flush`+`fsync` + guardia anti riga-troncata) del registro licenze. Gli errori di I/O propagano
    (il chiamante GUI li tratta best-effort). Ritorna il record scritto."""
    path = revoked_registry_path(directory)
    line = json.dumps(record, ensure_ascii=False)
    with _WRITE_LOCK:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        prefix = "\n" if _ends_without_newline(path) else ""
        with open(path, "a", encoding="utf-8") as f:
            f.write(prefix + line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return record


def read_revocations(*, directory: "str | None" = None, path: "str | None" = None) -> list:
    """Legge lo store revoche come lista di record (dict), nell'ordine d'inserimento. Fail-safe: file
    assente → `[]`; righe vuote/malformate saltate (stesso guard di `read_records`)."""
    target = path or revoked_registry_path(directory)
    return read_records(path=target)


def is_serial_revoked(revocations: list, serial: str) -> bool:
    """`True` se `serial` (normalizzato spazi/maiuscole) compare tra i record di revoca. Serve alla GUI
    per non registrare due volte la stessa revoca e per annotare lo stato nella vista."""
    key = normalize_serial(serial)
    if not key:
        return False
    # Anche qui l'helper, non la regola riscritta a mano (rilievo Fugu): era l'ultima copia
    # rimasta, e una copia sopravvissuta è esattamente il punto da cui riparte la divergenza.
    return any(normalize_serial(r.get("serial")) == key for r in revocations)


def revocation_entries(revocations: list) -> list:
    """Converte i record di revoca nelle **entry** per `revocation.build_revocation_list`:
    `[{"serial": ..}, ...]` deduplicate per serial.

    Revoca **per serial** (la specifica emissione), che è sufficiente a tagliare fuori un utente — solo
    il proprietario emette token, quindi non può auto-generarsi un serial nuovo — ed è **reversibile**
    (una nuova licenza = serial nuovo, non revocato). L'`hardware_id` è conservato nello store come
    metadato ma **non** viene emesso nella lista (un blacklist di macchina è un'azione più forte, non il
    default di R3b). Le entry senza serial valido sono ignorate (fail-safe).

    **Blacklist della macchina, opzionale** (PR-C del piano #194, decisione del proprietario). Un
    record che porta `blacklist_hw` vero emette **anche** `{"hw": …}`. Serve contro un caso preciso:
    su un bridge **non aggiornato** il token malleato di B2 è ancora accettato, e lì l'unica difesa
    che regge è l'Hardware ID — che il padding non cambia.

    Resta **opzionale e spento di default**, e il motivo è misurato: emetterlo in ogni revoca la
    renderebbe **irreversibile**. Un cliente revocato che poi RICOMPRA ha un serial nuovo ma la stessa
    macchina, quindi resterebbe bloccato per sempre:

        entry                    vecchio revocato   NUOVO acquistato
        solo serial (default)    bloccato           NON bloccato      ← può ricomprare
        serial + hw              bloccato           bloccato          ← macchina in blacklist

    I record già su disco non hanno il campo, quindi dopo l'aggiornamento **nessuna macchina finisce
    in blacklist a sorpresa**: nessuna migrazione, nessun cambio di comportamento retroattivo.
    """
    per_serial, out = {}, []
    for r in revocations:
        serial = normalize_serial(r.get("serial"))
        if not serial:
            continue
        entry = per_serial.get(serial)
        if entry is None:
            entry = {"serial": serial}
            per_serial[serial] = entry
            out.append(entry)
        # `hw` solo se richiesto ESPLICITAMENTE e se c'è davvero un hardware id: una entry con `hw`
        # vuoto non revocherebbe nulla e verrebbe scartata da `normalize_entries` — meglio non
        # generarla affatto.
        #
        # Il flag si valuta su OGNI record dello stesso serial, non solo sul primo (rilievo Fable 5
        # sulla PR-C): col dedup precedente, se lo stesso serial compariva prima **senza** e poi
        # **con** `blacklist_hw`, il secondo record veniva scartato e la blacklist richiesta
        # esplicitamente spariva **in silenzio**. Chiesta una volta = emessa.
        #
        # `is True` e non un `if` generico (rilievo GPT-5.5): la blacklist è **irreversibile** — la
        # macchina resta fuori uso per sempre — e con la verifica lasca la **stringa** `"false"`,
        # che in Python è vera, l'avrebbe attivata. Una svista di serializzazione non deve poter
        # decidere una cosa del genere; il valore che il codice scrive è il booleano vero.
        if r.get("blacklist_hw") is True and "hw" not in entry:
            hw = str(r.get("hardware_id", "")).strip()
            if hw:
                entry["hw"] = hw
    return out


def find_by_serial(records: list, serial: str) -> "dict | None":
    """Primo record col `serial` dato (confronto esatto, spazi/maiuscole normalizzati), o `None`.
    Serve al rinnovo/ri-emissione (opzione B): dato un serial dell'elenco si ritrova la licenza per
    riusarne nome + hardware ID (rinnovo) o ri-mostrarne il token (ri-invio)."""
    key = normalize_serial(serial)
    if not key:
        return None
    for rec in records:
        if normalize_serial(rec.get("serial")) == key:
            return rec
    return None


def record_status(record: dict, *, now: int) -> str:
    """`ATTIVA` se `now < expiry`, altrimenti `SCADUTA`. Un `expiry` mancante/non numerico è trattato
    come **scaduto** (fail-safe: nel dubbio non risulta attiva)."""
    try:
        expiry = int(record.get("expiry"))
    except (TypeError, ValueError):
        return STATUS_EXPIRED
    return STATUS_ACTIVE if int(now) < expiry else STATUS_EXPIRED


def days_left(record: dict, *, now: int) -> int:
    """Giorni interi rimasti alla scadenza (arrotondati per eccesso), **0** se già scaduta o
    `expiry` non valido."""
    try:
        expiry = int(record.get("expiry"))
    except (TypeError, ValueError):
        return 0
    remaining = expiry - int(now)
    if remaining <= 0:
        return 0
    return (remaining + _SECONDS_PER_DAY - 1) // _SECONDS_PER_DAY


def view_rows(records: list, *, query: str = "", now: int, revoked_serials=()) -> list:
    """Righe pronte per la tabella, **filtrate** (ricerca) e annotate con stato/giorni.

    Filtro **case-insensitive per sottostringa** su `serial`, `name`, `hardware_id` (spazi ai bordi
    ignorati); `query` vuota = tutte. Ogni riga espone SOLO campi non sensibili
    (`serial`/`name`/`hardware_id`/`issued`/`expiry`/`days`/`status`/`days_left`): **il token NON è
    incluso** (non va mostrato nella vista d'elenco). Le righe più recenti (per `expiry`) prima.

    `revoked_serials` = i serial presenti in `revoked.jsonl` (li legge il chiamante). Una licenza in
    quell'insieme esce `REVOCATA`, **anche se scaduta**: è l'informazione che spiega perché non
    riattivarla con un rinnovo distratto, e rispetto al fatto che la licenza è stata tolta la
    scadenza è secondaria. Parametro **opzionale**: i chiamanti che non lo passano si comportano
    esattamente come prima (nessuna migrazione, nessun cambio di esito)."""
    q = str(query or "").strip().casefold()
    # Normalizzati come ovunque nel registro (spazi + maiuscole): un record scritto a mano non deve
    # sfuggire alla marcatura — nel dubbio si mostra revocato, non attivo.
    revocati = {normalize_serial(s) for s in (revoked_serials or ())}
    rows = []
    for rec in records:
        serial = str(rec.get("serial", ""))
        name = str(rec.get("name", ""))
        hardware_id = str(rec.get("hardware_id", ""))
        if q and q not in serial.casefold() and q not in name.casefold() \
                and q not in hardware_id.casefold():
            continue
        rows.append({
            "serial": serial,
            "name": name,
            "hardware_id": hardware_id,
            "issued": rec.get("issued"),
            "expiry": rec.get("expiry"),
            "days": rec.get("days"),
            # La revoca vince su tutto: è uno stato della LICENZA nel mondo, non del suo calendario.
            "status": (STATUS_REVOKED if normalize_serial(serial) in revocati
                       else record_status(rec, now=now)),
            "days_left": days_left(rec, now=now),
        })

    def _sort_key(row):
        # A prova di TypeError (review Sourcery #152): un `expiry` NON numerico (riga editata a
        # mano/formato futuro) non deve far crashare la sort mischiando int e str. I record con
        # `expiry` valido vanno in testa ordinati per scadenza DECRESCENTE (`-int`); quelli con
        # `expiry` None/non numerico finiscono in fondo (gruppo 1), stabili tra loro.
        try:
            return (0, -int(row["expiry"]))
        except (TypeError, ValueError):
            return (1, 0)

    rows.sort(key=_sort_key)
    return rows
