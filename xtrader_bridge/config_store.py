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
import os
import shutil
import sys
import tempfile

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
    # Se True (default sicuro) un segnale senza quota valida (> 1.0) viene scartato.
    "require_price":     True,
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
            shutil.copyfile(legacy_path, new_path)
            return True
    except Exception as exc:   # noqa: BLE001 — best-effort, ma ora loggato (non silenzioso)
        # exc_info=True: l'except è ampio, il traceback aiuta a capire la causa.
        logger.warning("Migrazione config legacy fallita (%s -> %s): %s",
                       legacy_path, new_path, exc, exc_info=True)
    return False


def load_config(path: str = CONFIG_FILE) -> dict:
    """Ritorna i default, sovrascritti dal file se presente e leggibile.

    Se il file esiste ma è corrotto (JSON non valido), ne fa un backup `.bak`
    e riparte dai default, così una config rotta non blocca l'avvio.
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
    return cfg


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
    to_save = dict(cfg)
    to_save.setdefault("config_version", CONFIG_VERSION)
    try:
        _ensure_dir(path)
        d = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(dir=d, prefix=TMP_PREFIX, suffix=TMP_SUFFIX)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(to_save, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            # Scrittura/rename falliti: rimuovi il temporaneo, non lasciare residui.
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
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
    except OSError:
        pass
