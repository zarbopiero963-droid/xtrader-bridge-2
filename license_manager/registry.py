"""License Manager — **registro delle licenze emesse** (issue #140, opzione A).

Oggi l'emissione di una licenza è **stateless**: il tool produce un token e non registra nulla.
Questo modulo aggiunge un **registro locale** append-only sul PC del proprietario — `licenses.jsonl`
nella cartella del License Manager (`%APPDATA%\\XTraderLicenseManager`, la stessa del seed privato,
mai nel repo/EXE) — così il proprietario può **ritrovare** chi ha ricevuto cosa, con che scadenza, e
(in una fase successiva) **rinnovare/revocare** da un elenco.

Logica **pura e fail-safe**, senza GUI:

- il **serial** di una licenza è **deterministico** dal token firmato (`license_serial`): sia il tool
  (che ha appena emesso il token) sia — in futuro — il bridge (che ha il token attivato) calcolano lo
  **stesso** identificatore, senza aggiungere campi al formato token (nessuna migrazione);
- il record si costruisce **dal payload del token** (`record_from_token`), così il registro combacia
  sempre con la licenza realmente firmata (nome/hardware/scadenza autoritativi);
- append-only robusto (stesso idiom di `xtrader_bridge.event_journal`: guardia sulla riga troncata +
  `flush`/`fsync`, lettura tollerante che salta le righe malformate);
- **nessun segreto**: il registro contiene il **token di attivazione** (che il proprietario dà
  comunque all'utente, legato a un singolo hardware) e i suoi metadati — **mai** il seed privato.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading

# Serial deterministico condiviso: vive in `xtrader_bridge.licensing.license` (pacchetto condiviso) così
# il **bridge** (revoca online R3c) lo calcola IDENTICO senza importare `license_manager`. Ri-esportato
# qui come `registry.license_serial` per compatibilità con i chiamanti/test esistenti.
from xtrader_bridge.licensing.license import license_serial

from .core import manager_dir

_log = logging.getLogger(__name__)

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
    serial = str(record.get("serial", "")).strip().upper()
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
    key = str(serial or "").strip().upper()
    if not key:
        return False
    return any(str(r.get("serial", "")).strip().upper() == key for r in revocations)


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
        serial = str(r.get("serial", "")).strip().upper()
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
    key = str(serial or "").strip().upper()
    if not key:
        return None
    for rec in records:
        if str(rec.get("serial", "")).strip().upper() == key:
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
    revocati = {str(s).strip().upper() for s in (revoked_serials or ())}
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
            "status": (STATUS_REVOKED if serial.strip().upper() in revocati
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
