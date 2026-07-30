"""License Manager — **backup completo e ripristino** dello stato (#183).

Perché esiste. Il backup preesistente (`core.export_signing_key`) copia **solo il seed**, ed è
corretto per quello che fa: mettere al sicuro la chiave. Non basta però a **migrare** il tool su
un'altra macchina, e usarlo per quello causa un guasto **silenzioso e grave**.

Il License Manager tiene tre stati distinti in `manager_dir()`:

- `signing_key.json` — il **seed**: generato una volta, non cambia mai;
- `licenses.jsonl` — registro delle licenze **emesse**: cresce a ogni emissione;
- `revoked.jsonl` — chi è stato **revocato**: cresce a ogni revoca.

Migrando col solo seed, sul nuovo PC `revoked.jsonl` è vuoto. Al primo «🚀 Pubblica ora» si
pubblica una lista firmata che dice **«nessuno è revocato»** — valida, firmata, e con `iss` più
recente della precedente. L'anti-replay monotòno del bridge rifiuta solo le liste *più vecchie*,
quindi la accetta: **tutti i revocati tornano attivi**, senza un errore, senza un avviso. E si
perde `licenses.jsonl`, quindi «Rinnova»/«ri-mostra token» smettono di funzionare per le licenze
già emesse.

Questo modulo produce un backup che contiene **tutto lo stato necessario a ripartire identici**, e
un ripristino che rifiuta di fare danni.

⚠️ **Il file di backup contiene il seed.** È l'oggetto più prezioso del sistema, in forma portabile:
chi lo ottiene può emettere licenze valide indistinguibili da quelle del proprietario, e non è
revocabile in modo efficace. Va trattato di conseguenza — supporto offline, mai cartelle
sincronizzate o condivise. Per la stessa ragione il **backup automatico** (`auto_backup`) esclude
deliberatamente il seed: ogni copia in più è un posto in più da cui può uscire, e il seed va salvato
**una volta**, consapevolmente.

**Il token GitHub non entra mai qui**: vive nel keyring del sistema operativo (`publish_store`),
che è il posto giusto — cifrato, legato all'utente, non copiabile per sbaglio insieme a un file. Sul
nuovo PC si re-incolla, ed è un segreto **sostituibile** (si rigenera in un minuto), a differenza del
seed.
"""

from __future__ import annotations

import json
import os

from xtrader_bridge import atomic_io

from . import core, publish_store, registry

# Versione del formato di backup: un ripristino da una versione sconosciuta viene rifiutato invece
# di essere interpretato a indovinare.
BACKUP_FORMAT_VERSION = 1

# I file dello stato, in ordine di importanza. `signing_key.json` è l'unico **obbligatorio**: senza
# seed il backup non serve a migrare. Gli altri possono legittimamente non esistere ancora (nessuna
# licenza emessa, nessuna revoca, pubblicazione mai configurata).
KEY_FILE = core.SIGNING_KEY_FILE
STATE_FILES = (registry.REGISTRY_FILE, registry.REVOKED_FILE,
               publish_store.PUBLISH_CONFIG_FILE, publish_store.PUBLISH_STATE_FILE)
ALL_FILES = (KEY_FILE,) + STATE_FILES

# File del backup automatico, dentro la cartella del tool. Contiene SOLO gli stati che cambiano —
# mai il seed (vedi il docstring del modulo).
AUTO_BACKUP_FILE = "auto_backup.json"

# Marcatore di «ripristino in corso». Scritto PRIMA della prima scrittura e rimosso solo a
# ripristino completo: se resta su disco, il ripristino non è finito (bloccante Fugu Ultra #184).
#
# Perché serve, misurato. Il ripristino non è una transazione unica: un guasto di I/O dopo il seed e
# prima delle revoche lascia una cartella con una **chiave valida** e uno store revoche **vuoto**. In
# quello stato il tool firma e pubblica volentieri una lista che dice «nessuno è revocato» — valida,
# firmata, più recente della precedente, quindi accettata da tutti i bridge. È il guasto della #183
# per una strada nuova, e senza il marcatore non lo segnalerebbe nulla.
RESTORE_MARKER_FILE = "restore_in_progress.json"


class BackupError(Exception):
    """Backup illeggibile, di formato sconosciuto, o incoerente. Sollevata **prima** di scrivere
    qualsiasi cosa: un backup rotto non deve lasciare lo stato a metà."""


class BackupExistsError(BackupError):
    """C'è già un file in quel percorso e `overwrite` non è stato chiesto.

    Sottoclasse **dedicata** e non un `BackupError` generico perché la GUI deve poter distinguere
    «non si può fare» da «si può fare, ma serve una conferma consapevole»: senza distinguerle,
    l'unica uscita sarebbe scegliere un altro nome — o, peggio, un `overwrite=True` di default che
    cancella in silenzio il backup di un'altra keypair."""


class BackupKeyMismatchError(BackupError):
    """Nella cartella di destinazione c'è già una keypair **diversa** da quella del backup.

    Distinta per la stessa ragione di `BackupExistsError`: è il caso reale di chi, sul PC nuovo, ha
    premuto «Genera keypair» prima di ripristinare. È recuperabile, ma solo con una conferma
    esplicita che dica cosa si sta per perdere."""


def backup_path(directory: "str | None" = None) -> str:
    """Percorso del backup automatico nella cartella data o in `manager_dir()`."""
    return os.path.join(directory or core.manager_dir(), AUTO_BACKUP_FILE)


def restore_marker_path(directory: "str | None" = None) -> str:
    """Percorso del marcatore «ripristino in corso»."""
    return os.path.join(directory or core.manager_dir(), RESTORE_MARKER_FILE)


def restore_in_progress(directory: "str | None" = None) -> bool:
    """`True` se in quella cartella c'è un ripristino **iniziato e non concluso**.

    Chi firma la lista di revoche deve consultarlo e **rifiutarsi** di pubblicare: uno stato a metà è
    indistinguibile, per il codice che firma, da uno stato legittimo — ma può contenere zero revoche
    e ri-attivare tutti. Fail-closed anche sull'errore di lettura: se non riusciamo a stabilire che il
    ripristino è finito, ci comportiamo come se non lo fosse."""
    try:
        return os.path.exists(restore_marker_path(directory))
    except OSError:
        return True


def _leggi(path: str) -> "str | None":
    """Contenuto testuale di un file, o `None` se assente. Un errore di I/O diverso da «non esiste»
    **propaga**: non va confuso con «il file non c'era» (stessa scelta di `core.load_signing_key`)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def build_backup(directory: "str | None" = None, *, now: int, include_key: bool = True) -> dict:
    """Costruisce il contenuto del backup leggendo lo stato da `directory`.

    `include_key=False` produce un backup di **solo stato mutevole** (registro + revoche +
    impostazioni), quello usato dall'automatismo: non contiene il seed e non è sufficiente a migrare.

    Il campo `public` in testa serve a riconoscere **quale keypair** contiene un backup senza doverne
    leggere il seed: il ripristino lo usa per accorgersi che si stanno mescolando due identità
    diverse. Solleva `BackupError` se il seed è richiesto ma assente o corrotto — un backup che non
    consente di ripartire è peggio di nessun backup, perché dà una falsa sicurezza."""
    base = directory or core.manager_dir()
    files, public = {}, None

    if include_key:
        chiave = core.load_signing_key(os.path.join(base, KEY_FILE))   # corrotto → solleva
        if chiave is None:
            raise BackupError("nessuna keypair da salvare: genera prima la chiave.")
        public = chiave["public"]
        files[KEY_FILE] = _leggi(os.path.join(base, KEY_FILE))

    for nome in STATE_FILES:
        contenuto = _leggi(os.path.join(base, nome))
        if contenuto is not None:
            files[nome] = contenuto

    return {"v": BACKUP_FORMAT_VERSION, "created": int(now), "public": public, "files": files}


def save_backup(dest_path: str, contenuto: dict, *, overwrite: bool = False) -> None:
    """Scrive il backup in modo **atomico**, con permessi `0o600` fin dalla prima syscall.

    `overwrite=False` (default) **non sovrascrive** un file esistente: potrebbe essere il backup di
    un'ALTRA keypair, e perderla significherebbe non poter più rinnovare quelle licenze — la stessa
    cautela di `core.export_signing_key`.

    Il no-overwrite passa da `core._persist_key_file`, cioè dallo **stesso** primitivo che custodisce
    il seed: `O_CREAT|O_EXCL` invece di «controlla se esiste, poi scrivi». Il controllo separato
    lasciava una finestra TOCTOU (rilievo CodeRabbit #184) in cui un altro processo poteva creare il
    file **dopo** il controllo e vederselo sostituire dal rename. Con `O_EXCL` la creazione fallisce
    atomicamente. Riusare quel primitivo — invece di riscriverne uno qui — porta con sé anche i
    permessi espliciti sul temporaneo e l'`fsync` di file **e** directory, requisiti che valgono
    identici per un file che contiene il seed."""
    try:
        core._persist_key_file(dest_path, json.dumps(contenuto, indent=2, ensure_ascii=False),
                               overwrite=overwrite)
    except core.KeyExistsError as exc:
        raise BackupExistsError(f"esiste già un file in quel percorso: {dest_path}") from exc


def load_backup(path: str) -> dict:
    """Legge e **valida** un backup. Solleva `BackupError` su qualunque anomalia.

    La validazione è deliberatamente severa e avviene **tutta prima** di qualsiasi scrittura: un
    backup troncato, di versione sconosciuta o con un seed incoerente non deve mai arrivare a
    toccare lo stato reale."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as exc:
        raise BackupError(f"backup non trovato: {path}") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise BackupError(f"backup non è un JSON valido: {path}") from exc

    if not isinstance(raw, dict):
        raise BackupError("backup con struttura inattesa.")
    if raw.get("v") != BACKUP_FORMAT_VERSION:
        raise BackupError(f"versione di backup non supportata: {raw.get('v')!r} "
                          f"(attesa {BACKUP_FORMAT_VERSION}).")
    files = raw.get("files")
    if not isinstance(files, dict) or not files:
        raise BackupError("backup senza contenuti.")
    for nome, contenuto in files.items():
        if nome not in ALL_FILES:
            raise BackupError(f"backup con file non riconosciuto: {nome!r}.")
        if not isinstance(contenuto, str):
            raise BackupError(f"contenuto non testuale per {nome!r}.")
        _valida_contenuto(nome, contenuto)
    return raw


def _valida_contenuto(nome: str, testo: str) -> None:
    """Controlla che il contenuto di uno stato sia **interpretabile**, non solo che sia una stringa.

    Perché serve (rilievo CodeRabbit #184). I file di stato sono letti in modo **fail-safe**: una riga
    JSONL illeggibile viene saltata in silenzio. Un `revoked.jsonl` corrotto dentro il backup
    sopravvivrebbe quindi alla validazione, sostituirebbe uno store valido, e alla prima pubblicazione
    produrrebbe una lista firmata **senza quelle revoche** — cioè esattamente il guasto che questo
    modulo esiste per impedire, con la differenza che qui non ci sarebbe nemmeno un errore a
    segnalarlo. Meglio rifiutare il ripristino: un backup illeggibile è un problema **visibile**, uno
    stato mezzo perso non lo è.

    Il controllo è sulla **forma**, non sul merito: righe JSONL che siano oggetti, JSON di primo
    livello che sia un oggetto. Non entra nei campi — quello resta compito dei rispettivi store, che
    hanno già i propri default sicuri."""
    if nome == KEY_FILE:
        return          # coerenza seed↔pubblica: la verifica vera è in `backup_public`
    if nome.endswith(".jsonl"):
        for numero, riga in enumerate(testo.splitlines(), start=1):
            if not riga.strip():
                continue        # righe vuote: già tollerate dagli store
            try:
                voce = json.loads(riga)
            except ValueError as exc:
                raise BackupError(f"{nome}: riga {numero} illeggibile nel backup.") from exc
            if not isinstance(voce, dict):
                raise BackupError(f"{nome}: riga {numero} non è un record.")
        return
    try:
        dati = json.loads(testo)
    except ValueError as exc:
        raise BackupError(f"{nome}: contenuto non è un JSON valido nel backup.") from exc
    if not isinstance(dati, dict):
        raise BackupError(f"{nome}: contenuto con struttura inattesa nel backup.")


def backup_public(contenuto: dict) -> "str | None":
    """La chiave **pubblica** contenuta nel backup, o `None` se è un backup di solo stato.

    Ricavata dal file-chiave vero e non dal campo `public` in testa: quel campo è comodo ma
    **dichiarativo**, e un backup manomesso potrebbe averlo incoerente col seed. Solleva
    `BackupError` se il file-chiave c'è ma non è valido."""
    grezzo = contenuto.get("files", {}).get(KEY_FILE)
    if grezzo is None:
        return None
    try:
        dati = json.loads(grezzo)
        seed = dati["seed"]
        pubblica = core._public_for_seed(seed)
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupError("il file-chiave dentro il backup non è leggibile.") from exc
    if pubblica != str(dati.get("public", "")).strip().lower():
        raise BackupError("seed e chiave pubblica del backup non sono coerenti.")
    return pubblica


def restore_backup(contenuto: dict, directory: "str | None" = None, *,
                   overwrite_key: bool = False) -> dict:
    """Ripristina lo stato da un backup **già validato** con `load_backup`.

    Ritorna ``{"scritti": [...], "public": …}``: dice **quali file** ha toccato, invece di un
    generico «ok» — dopo un ripristino serve sapere cosa è entrato.

    Protezione centrale: se in `directory` esiste già una keypair **diversa** da quella del backup,
    il ripristino è **rifiutato** salvo `overwrite_key=True` esplicito. Sovrascriverla in silenzio
    significherebbe perdere la capacità di rinnovare le licenze emesse con quella chiave — un danno
    irreversibile. Se la keypair è la **stessa**, non c'è nulla da decidere e si procede.

    **Gli store append-only si UNISCONO, non si sovrascrivono** (bloccante Fugu Ultra #184, e una mia
    affermazione sbagliata: avevo scritto «la destinazione può avere più revoche del backup, mai
    meno»). Misurato, era falso: con un `revoked.jsonl` **presente** nel backup, ripristinare uno
    snapshot più vecchio *sostituiva* lo store e faceva sparire le revoche fatte dopo — R1+R2 sulla
    destinazione, R1 nel backup, R1 dopo il ripristino. Alla prima pubblicazione R2 sarebbe tornato
    attivo: esattamente il guasto che questo modulo esiste per impedire, raggiunto da un'altra
    strada. Ora `licenses.jsonl` e `revoked.jsonl` vengono **fusi** (destinazione + voci del backup
    non già presenti, per `serial`): è la semantica giusta per due registri **append-only**, in cui
    una revoca non si annulla e una licenza emessa non si dimentica.

    `publish_config.json` e `publish_state.json` sono invece **impostazioni**, non registri: lì
    sovrascrivere è corretto — è il senso di ripristinare una configurazione.

    I file che il backup **non contiene** restano intatti (rilievo GPT-5.5/CodeRabbit #184: su una
    destinazione già usata lo stato risulta «misto»). Trattarli come cancellazioni produrrebbe la
    stessa de-revoca silenziosa dal lato opposto.

    **Un ripristino interrotto blocca la pubblicazione.** Prima della prima scrittura viene posato il
    marcatore `restore_in_progress.json`, rimosso solo a ripristino completo. Finché è lì,
    `restore_in_progress()` è `True` e chi firma la lista di revoche si rifiuta di procedere
    (bloccante Fugu Ultra #184). Misurato: senza il marcatore, un guasto di I/O dopo il seed e prima
    delle revoche lasciava una cartella con chiave valida e store revoche **vuoto**, dalla quale il
    tool pubblicava volentieri «nessuno è revocato». Il marcatore che sopravvive è **voluto**: uno
    stato a metà deve restare visibile e bloccante finché il ripristino non viene rifatto.

    Onestà sui limiti:

    - la scrittura dei singoli file **non è una transazione unica**: un guasto a metà lascia alcuni
      file ripristinati e altri no. Ogni file è però scritto in modo atomico (nessuno troncato) e il
      marcatore impedisce che quello stato venga pubblicato;
    - la fusione è un read-modify-write. **Dentro** il processo la finestra è chiusa dal lock degli
      append. **Fra** processi (due License Manager aperti insieme) resta un residuo: il controllo
      appena prima della riscrittura la riduce a pochi microsecondi e trasforma la perdita silenziosa
      in un errore esplicito e ripetibile, ma non la elimina. Il tool non ha un instance-lock, e
      quello è un cambiamento a sé."""
    base = directory or core.manager_dir()
    files = contenuto.get("files", {})
    pubblica_backup = backup_public(contenuto)

    if KEY_FILE in files:
        esistente = core.load_signing_key(os.path.join(base, KEY_FILE))   # corrotta → solleva
        if esistente is not None and esistente["public"] != pubblica_backup and not overwrite_key:
            raise BackupKeyMismatchError(
                "in questa cartella esiste già una keypair DIVERSA da quella del backup. "
                "Sovrascriverla renderebbe impossibile rinnovare le licenze emesse con la chiave "
                "attuale: conferma esplicitamente se è ciò che vuoi.")

    os.makedirs(base, exist_ok=True)
    atomic_io.atomic_write_json(restore_marker_path(base),
                                {"started": int(contenuto.get("created") or 0),
                                 "files": sorted(files)}, indent=2)
    scritti = []
    for nome in ALL_FILES:                      # ordine stabile, non quello del dict
        if nome not in files:
            continue
        percorso = os.path.join(base, nome)
        if nome == KEY_FILE:
            # Stesso primitivo di `save_backup`: permessi espliciti e `fsync` di file **e** directory
            # (rilievo Fugu #184). Misurato, `atomic_write_text` dava già `0o600` via `mkstemp`, ma
            # qui la garanzia diventa esplicita invece che incidentale — e il seed sopravvive a un
            # crash subito dopo il ripristino.
            core._persist_key_file(percorso, files[nome], overwrite=True)
        elif nome.endswith(".jsonl"):
            # Lettura e riscrittura sotto lo **stesso** lock che serializza gli append del registro
            # (rilievo GPT-5.5 #184): senza, una revoca registrata fra il `_leggi` e il `replace`
            # verrebbe persa — proprio la de-revoca silenziosa che l'unione esiste per evitare.
            with registry.WRITE_LOCK:
                prima = _leggi(percorso)
                fuso = _fondi_append_only(percorso, files[nome])
                # Controllo appena prima di sostituire: se un ALTRO PROCESSO ha appeso nel frattempo
                # (il lock è solo intra-processo), il file è cambiato e la nostra fusione è già
                # vecchia. Meglio un errore ripetibile che una revoca persa in silenzio.
                if _leggi(percorso) != prima:
                    raise BackupError(
                        f"{nome} è cambiato durante il ripristino: un'altra istanza del License "
                        "Manager sta scrivendo. Chiudila e rifai il ripristino.")
                atomic_io.atomic_write_text(percorso, fuso)
            core._restrict_perms(percorso)
        else:
            atomic_io.atomic_write_text(percorso, files[nome])
            core._restrict_perms(percorso)
        scritti.append(nome)
    try:
        os.remove(restore_marker_path(base))
    except OSError as exc:
        # Il marcatore non si toglie → la pubblicazione resta bloccata. È il verso giusto in cui
        # sbagliare, ma va detto: un «tutto a posto» silenzioso qui sarebbe una bugia.
        raise BackupError("ripristino completato, ma non è stato possibile rimuovere il marcatore "
                          f"«{RESTORE_MARKER_FILE}»: la pubblicazione resterà bloccata finché non "
                          "viene cancellato a mano.") from exc
    return {"scritti": scritti, "public": pubblica_backup}


def _chiave_voce(riga: str) -> str:
    """Chiave di deduplica di una riga JSONL: il `serial` se c'è, altrimenti la riga stessa.

    Il fallback sulla riga integrale è deliberato: senza `serial` non esiste un'identità di dominio,
    e **inventarne** una rischierebbe di scartare un record diverso. Meglio un duplicato in più — gli
    store lo tollerano — che una revoca in meno."""
    try:
        voce = json.loads(riga)
    except ValueError:
        return riga
    if isinstance(voce, dict) and str(voce.get("serial") or "").strip():
        return f"serial:{str(voce['serial']).strip()}"
    return riga


def _fondi_append_only(percorso: str, dal_backup: str) -> str:
    """Unione di due store append-only: **tutte** le righe della destinazione, più quelle del backup
    non già presenti (per `serial`). L'ordine della destinazione è preservato.

    Unione e non sostituzione perché `licenses.jsonl` e `revoked.jsonl` sono registri **monotòni**:
    una revoca non si annulla, una licenza emessa non si dimentica. Sostituirli con uno snapshot più
    vecchio farebbe sparire quello che è successo dopo il backup."""
    esistente = _leggi(percorso) or ""
    viste = {_chiave_voce(r) for r in esistente.splitlines() if r.strip()}
    righe = [r for r in esistente.splitlines() if r.strip()]
    for riga in dal_backup.splitlines():
        if not riga.strip():
            continue
        chiave = _chiave_voce(riga)
        if chiave in viste:
            continue
        viste.add(chiave)
        righe.append(riga)
    return "".join(r + "\n" for r in righe)


def auto_backup(directory: "str | None" = None, *, now: int) -> bool:
    """Backup automatico dello **stato che cambia** — registro licenze e revoche — dentro la cartella
    del tool. `True` se scritto, `False` se non c'era nulla da salvare.

    Agganciato all'**emissione** e alla **revoca**, non alla pubblicazione della lista: pubblicare
    ri-firma e carica, ma **non cambia nulla su disco** — un backup lì riscriverebbe gli stessi byte
    a ogni ciclo, senza proteggere niente.

    **Best-effort**: un errore di I/O non propaga. È una rete di sicurezza, e una rete che rompe
    l'operazione che dovrebbe proteggere è peggio che non averla — emettere una licenza non deve
    fallire perché il backup non si scrive."""
    base = directory or core.manager_dir()
    try:
        contenuto = build_backup(base, now=now, include_key=False)
        if not contenuto["files"]:
            return False
        atomic_io.atomic_write_json(backup_path(base), contenuto, indent=2, ensure_ascii=False)
        return True
    except (OSError, ValueError, TypeError, BackupError):
        return False
