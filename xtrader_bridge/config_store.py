"""Caricamento/salvataggio configurazione (funzioni pure, nessuna GUI).

PR-04: la configurazione vive in una cartella utente persistente
(`%APPDATA%\\XTraderBridge\\config.json` su Windows), così sopravvive a
spostamenti/aggiornamenti/reinstallazioni dell'EXE. Alla prima esecuzione, se
esiste un vecchio `config.json` accanto all'eseguibile, viene migrato.
Un file corrotto viene messo da parte (`.bak`) e si riparte dai default.
"""

import copy
import json
import logging
import math
import os
import shutil
import sys

from . import atomic_io, autostart, confirmation_reader, safety_guard

APP_DIR_NAME = "XTraderBridge"
CONFIG_VERSION = 1

# Prefisso/suffisso del file temporaneo della scrittura atomica del config: fonte
# unica così i test si allineano senza duplicare la stringa (finding Sourcery).
TMP_PREFIX = ".config_"
TMP_SUFFIX = ".tmp"

# Logger di modulo: un salvataggio/migrazione config fallito NON deve restare
# silenzioso (prima era `except: pass`). Resta comunque best-effort — l'app non
# crasha e prosegue dai default — ma l'errore diventa visibile per la diagnosi.
logger = logging.getLogger(__name__)

DEFAULTS = {
    "config_version":   CONFIG_VERSION,
    "bot_token":        "",
    "chat_id":          "",
    "csv_path":         r"C:\XTrader\segnali.csv",
    "clear_delay":      90,
    "provider":         "TelegramBot",
    # Modalità di riconoscimento XTrader: ID_ONLY / NAME_ONLY / BOTH.
    # Default NAME_ONLY: oggi il bridge non ricava gli ID dal messaggio Telegram.
    "recognition_mode": "NAME_ONLY",
    # NB: la quota obbligatoria sì/no NON è più una chiave globale: la governa la
    # casella «Obblig.» sulla riga Price di ogni Parser Personalizzato (per-parser).
    # Parser Personalizzato attivo (nome; "" = usa il parser hardcoded). CP-07.
    "active_parser":    "",
    # Override per chat sorgente: {chat_id: nome_parser}. Vuoto = usa active_parser.
    "parser_by_chat":   {},
    # Chat sorgente multiple (PR-12): lista di {name, chat_id, enabled, provider,
    # mode PRE/LIVE}. Vuoto = setup mono-chat classico (chat_id + provider globali).
    "source_chats":     [],
    # Conferme XTrader (PR-17): chat SEPARATA dalle sorgenti su cui XTrader notifica
    # l'esito; timeout senza conferma; keyword (vuote = usa i default del modulo).
    "xtrader_notification_chat_id": "",
    "confirmation_timeout":         120,
    "confirmation_keywords":        [],
    "rejection_keywords":           [],
    # Guardrail di sicurezza (PR-19): in DRY_RUN (simulazione) il CSV operativo non
    # viene scritto. Default sicuro True: una config vecchia senza il campo eredita
    # la simulazione, così un aggiornamento non genera scommesse reali per sbaglio.
    "dry_run":                      True,
    # Tetto di segnali nuovi accettati in un giorno (UTC), complementare al
    # limite/minuto di signal_dedupe (PR-15).
    "max_per_day":                  200,
    # Coda dei segnali attivi (PR-22): OVERWRITE_LAST (default sicuro: un solo segnale
    # attivo alla volta) / APPEND_ACTIVE / QUEUE_UNTIL_CONFIRMED. Le ultime due
    # producono PIÙ righe attive nel CSV (più scommesse simultanee).
    "queue_mode":                   "OVERWRITE_LAST",
    # Anti-segnale-stantio (PR reconnect): un messaggio Telegram più vecchio di questi
    # secondi viene SCARTATO all'arrivo (probabile recupero dopo una disconnessione,
    # quando la connessione torna e arretrati vengono rifetchati). 0 = filtro disattivo.
    "max_signal_age":               120,
    # Avvio automatico del listener all'apertura dell'app. Default sicuro False: il
    # bridge parte solo con START manuale. Se True parte da solo SOLO se token e chat
    # sono configurati; in modalità REALE chiede comunque conferma prima di avviare.
    "auto_start_listener":          False,
}


def as_bool(value) -> bool:
    """Coercizione robusta a bool, condivisa dai vari moduli (config da JSON o stringhe
    truthy/falsey). `bool`→sé; numeri→`!= 0`; stringa→False solo se vuota o in
    ``{"0","false","no","off"}`` (case-insensitive). Unica fonte per evitare versioni
    divergenti dello stesso helper."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in ("", "0", "false", "no", "off")


def config_dir() -> str:
    """Cartella utente per i dati dell'app.

    Windows: ``%APPDATA%\\XTraderBridge``. Altrove (dev/CI/Linux/macOS):
    ``$XDG_CONFIG_HOME/XTraderBridge`` o ``~/.config/XTraderBridge``.
    """
    base = (
        os.environ.get("APPDATA")
        or os.environ.get("XDG_CONFIG_HOME")
        or os.path.join(os.path.expanduser("~"), ".config")
    )
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def legacy_config_path() -> str:
    """Vecchia posizione del config: accanto all'EXE/script.

    Nell'EXE PyInstaller (`--onefile`) `__file__` punta al bundle temporaneo,
    quindi quando l'app è "frozen" usiamo la cartella di `sys.executable` (dove
    sta davvero `XTrader-Signal-Bridge.exe`), così la migrazione trova il
    vecchio `config.json` accanto all'eseguibile.
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "config.json")


# Posizione persistente (nuova) e posizione legacy (accanto all'EXE/script).
CONFIG_FILE = config_path()
LEGACY_CONFIG_FILE = legacy_config_path()


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def migrate_legacy_config(new_path: str = CONFIG_FILE,
                          legacy_path: str = LEGACY_CONFIG_FILE) -> bool:
    """Se il config nuovo non esiste ma c'è quello vecchio, lo copia.

    Non distruttivo: il file legacy viene lasciato dov'è. Ritorna True se ha
    effettivamente migrato qualcosa.
    """
    try:
        if (not os.path.exists(new_path)
                and os.path.abspath(legacy_path) != os.path.abspath(new_path)
                and os.path.exists(legacy_path)):
            _ensure_dir(new_path)
            # Copia ATOMICA (audit L3): file temporaneo nella stessa cartella + flush/fsync +
            # `os.replace`, come `save_config`. `shutil.copyfile` non è atomico: un'interruzione
            # a metà (crash/blackout) lascerebbe un `config.json` troncato nella posizione nuova
            # alla prima esecuzione, costringendo a ripartire dai default. Copia BINARIA byte-per-byte
            # (modalità "wb"): il legacy può non essere UTF-8 valido, non va re-decodificato.
            def _copy_legacy(f):
                with open(legacy_path, "rb") as src:
                    shutil.copyfileobj(src, f)
            atomic_io.atomic_write(new_path, _copy_legacy, prefix=TMP_PREFIX, suffix=TMP_SUFFIX,
                                   mode="wb", encoding=None)
            return True
    except Exception as exc:   # noqa: BLE001 — best-effort, ma ora loggato (non silenzioso)
        # exc_info=True: l'except è ampio, il traceback aiuta a capire la causa.
        logger.warning("Migrazione config legacy fallita (%s -> %s): %s",
                       legacy_path, new_path, exc, exc_info=True)
    return False


# Chiavi-lista che accettano anche una STRINGA singola come formato valido (keyword
# conferma/rifiuto XTrader): vanno normalizzate, non azzerate (finding Codex P2).
_KEYWORD_KEYS = ("confirmation_keywords", "rejection_keywords")


def _coerce_int(value, default: int) -> int:
    """int robusto per la migrazione config (audit C5): accetta int/float e stringhe
    numeriche (`"90"`); su un valore non interpretabile torna al `default` SICURO invece
    di propagare un tipo sbagliato ai consumer. `bool` è sottoclasse di `int` ma NON è un
    numero qui (`True` da JSON non deve diventare `1` di timeout) → torna al default."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Solo float FINITI e INTERI: un `max_signal_age: 0.5` NON deve troncare a 0
        # (un valore <= 0 disattiva il filtro anti-stale → backlog vecchio passa,
        # finding Codex P2); `inf`/`nan` da un JSON editato a mano → default sicuro.
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _migrate(cfg: dict) -> dict:
    """Coercizione difensiva dei tipi noti (audit C5).

    `cfg.update(data)` sovrappone tipi arbitrari da un file vecchio o editato a mano
    (es. `"90"` stringa dove serve un intero, una stringa dove serve una lista): senza
    questo passo la sicurezza dipenderebbe dal fatto che OGNI consumer sia difensivo.
    Qui riportiamo ogni chiave NOTA (presente nei `DEFAULTS`) al tipo del suo default;
    un valore non interpretabile torna al default **sicuro** (es. `dry_run` resta `True`
    → simulazione). Le chiavi sconosciute/future NON vengono toccate (forward-compat):
    `config_version` con skew su disco viene preservato come intero.

    NB: l'ordine dei controlli mette `bool` prima di `int` perché `bool` è sottoclasse
    di `int` in Python.
    """
    for key, default in DEFAULTS.items():
        if isinstance(default, bool):
            # Le bool di SICUREZZA hanno semantica per-chiave OPPOSTA e fail-closed che
            # un coercitore generico fail-OPEN come `as_bool` falserebbe (finding Codex P1 /
            # CodeRabbit): `dry_run` (default True) deve restare in simulazione su valore
            # sporco/vuoto, `auto_start_listener` (default False) NON deve auto-avviarsi su
            # un valore non esplicitamente truthy. Deleghiamo alla funzione CANONICA di
            # ciascuna (single source of truth: stessi insiemi truthy/falsey dei consumer),
            # così il valore migrato coincide esattamente con la decisione di sicurezza.
            # Una eventuale bool futura senza semantica dedicata ricade su `as_bool`.
            if key == "dry_run":
                cfg[key] = safety_guard.is_dry_run(cfg)
            elif key == "auto_start_listener":
                cfg[key] = autostart.is_enabled(cfg)
            else:
                cfg[key] = as_bool(cfg.get(key, default))
        elif isinstance(default, int):
            cfg[key] = _coerce_int(cfg.get(key), default)
        elif isinstance(default, str):
            val = cfg.get(key, default)
            cfg[key] = val if isinstance(val, str) else (default if val is None else str(val))
        elif isinstance(default, list):
            if key in _KEYWORD_KEYS:
                # Una STRINGA singola è un formato SUPPORTATO per le keyword di conferma/
                # rifiuto (config scritta a mano: `confirmation_reader.normalize_keywords` la
                # avvolge come singola keyword, e il settings controller gestisce la CSV-string).
                # Azzerarla a `[]` farebbe ricadere `app._handle_confirmation` sui default del
                # modulo, ignorando i custom XTrader words → segnale chiuso solo a timeout
                # (finding Codex P2). La normalizziamo alla lista canonica; vuoto/tipo inatteso
                # → `[]` (= usa le keyword di default del modulo).
                cfg[key] = confirmation_reader.normalize_keywords(cfg.get(key)) or []
            elif not isinstance(cfg.get(key), list):
                cfg[key] = copy.deepcopy(default)
        elif isinstance(default, dict):
            if not isinstance(cfg.get(key), dict):
                cfg[key] = copy.deepcopy(default)
    return cfg


def load_config(path: str = CONFIG_FILE) -> dict:
    """Ritorna i default, sovrascritti dal file se presente e leggibile.

    Se il file esiste ma è corrotto (JSON non valido), ne fa un backup `.bak`
    e riparte dai default, così una config rotta non blocca l'avvio. Prima di
    restituire, `_migrate` coerce i tipi noti (audit C5) così un file vecchio/editato
    a mano non immette tipi sbagliati nei consumer.
    """
    # deepcopy: i default contengono valori mutabili nested (es. parser_by_chat
    # {}); una copia shallow li condividerebbe con DEFAULTS e una mutazione
    # in-place della config restituita corromperebbe i load successivi.
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
            else:
                _backup_corrupted(path)
        except (json.JSONDecodeError, ValueError, OSError):
            _backup_corrupted(path)
    # `config_version` è già garantito dai DEFAULTS; se il file ne porta uno
    # (futuro schema v2+) viene preservato così non perdiamo lo skew su disco.
    return _migrate(cfg)


def save_config(cfg: dict, path: str = CONFIG_FILE):
    """Salva la configurazione su file (best-effort) in modo **atomico**.

    Ritorna una tupla ``(config_salvata, ok)``:
    - ``config_salvata``: la config effettivamente serializzata (con `config_version`),
      sempre restituita così il chiamante può tenerla in memoria anche se il disco fallisce;
    - ``ok``: ``True`` se la scrittura su disco è riuscita, ``False`` altrimenti — così la
      GUI non può più segnalare "salvato" quando in realtà non lo è (finding A1).

    Scrittura **atomica** (tempfile nella stessa cartella + `flush`+`fsync` + `os.replace`,
    lo stesso schema di `csv_writer`/`signal_dedupe`/`profile_store`): un'interruzione a
    metà (crash, blackout, disco pieno) NON lascia un `config.json` troncato — o resta
    quello vecchio intatto, o c'è quello nuovo completo. Niente più reset ai default per
    una scrittura interrotta."""
    # deepcopy (audit C7): la `dict(cfg)` shallow condivideva i nested mutabili (liste/dict
    # come source_chats, parser_by_chat) tra lo snapshot restituito e il `cfg` del chiamante.
    # Il chiamante fa `self._config = saved`: con l'aliasing una mutazione successiva di uno
    # avrebbe alterato silenziosamente l'altro. Con la copia profonda i due sono indipendenti.
    to_save = copy.deepcopy(cfg)
    to_save.setdefault("config_version", CONFIG_VERSION)
    try:
        _ensure_dir(path)
        # Scrittura atomica condivisa (tmp + flush/fsync + os.replace, cleanup su errore).
        atomic_io.atomic_write_json(path, to_save, prefix=TMP_PREFIX, suffix=TMP_SUFFIX,
                                    indent=2)
    except OSError as exc:
        # Persistenza fallita (disco pieno, permessi, path non scrivibile): l'app
        # continua con la config in memoria, ma l'utente deve poterlo sapere.
        # exc_info=True: traceback completo per il post-mortem (più save point, stesso path).
        logger.error("Salvataggio config fallito (%s): %s", path, exc, exc_info=True)
        return to_save, False
    return to_save, True


def _backup_corrupted(path: str) -> None:
    """Sposta una config illeggibile in `<path>.bak` (best-effort).

    Usa os.replace così sovrascrive un eventuale `.bak` preesistente in modo
    atomico e cross-platform (su Windows shutil.move fallirebbe se esiste già).
    """
    try:
        os.replace(path, path + ".bak")
    except OSError as exc:
        # Best-effort, ma non più SILENZIOSO (audit #105 P2): se anche il backup fallisce
        # (permessi/lock), config corrotta + backup mancato = perdita di evidenza e l'utente
        # non capisce perché è tornato ai default. Si logga path + tipo errore (nessun
        # contenuto della config → niente leak). exc_info per il traceback in diagnosi.
        logger.warning("Backup della config corrotta fallito (%s → %s): %s",
                       path, path + ".bak", exc, exc_info=True)
