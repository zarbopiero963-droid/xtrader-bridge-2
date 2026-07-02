"""GUI CustomTkinter + listener Telegram.

Unica parte del progetto che dipende dalla GUI. La logica pura (parser, CSV,
config) vive in moduli separati ed è testabile headless.
"""

import asyncio
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime

import customtkinter as ctk

from . import __version__
from .config_store import (
    CONFIG_FILE,
    DEFAULTS,
    as_bool,
    as_bool_optin,
    config_dir,
    load_config,
    migrate_legacy_config,
    save_config,
)
from .csv_writer import clear_stale_csv, has_active_row, init_csv, sweep_orphan_temps, write_rows
from . import (
    autostart,
    config_store,
    confirmation_reader,
    csv_lock_escalation,
    dashboard_stats,
    diagnostics,
    event_journal,
    event_log,
    gui_utils,
    live_guard,
    log_privacy,
    log_view,
    message_freshness,
    multi_signal,
    real_mode,
    reconnect_policy,
    runtime_state,
    safety_guard,
    settings_controller,
    settings_validation,
    signal_dedupe,
    signal_outcome,
    signal_queue,
    signal_router,
    source_manager,
    telegram_dispatch,
    write_path,
)

try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
    TELEGRAM_OK = True
except ImportError:
    TELEGRAM_OK = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Ritardo (s) di retry quando una riscrittura del CSV fallisce (es. file bloccato da
# XTrader oltre i retry atomici): breve, per non lasciare una riga stantia per un
# intero intervallo di timeout (PR-23, finding Codex).
_WRITE_RETRY_DELAY = 5

# Quanti eventi tenere nel ledger append-only (#230): potato allo startup per non far
# crescere `event_journal.jsonl` all'infinito (~uno-pochi eventi per segnale).
_EVENT_JOURNAL_KEEP = 5000

# Cap delle righe di log tenute in memoria per il filtro (PR-14b): una sessione
# lunga non deve far crescere il log all'infinito. Si trima con isteresi (a
# _LOG_TRIM_AT si torna a _LOG_MAX) per non rifare il render a ogni riga.
_LOG_MAX = 1000
_LOG_TRIM_AT = 1200

# Larghezza di wrap per le label di contenuto del monitoraggio (Chat ascoltate /
# Stato): unica fonte, così i pannelli a schede restano coerenti e si regola in un
# punto solo. Tarata sulla larghezza fissa della finestra (720px) meno i margini.
_CONTENT_WRAP = 660

# Campi "ultimo …" del pannello STATO (PR-14c): chiave interna → prefisso etichetta.
# Fonte UNICA: usata sia per creare le label sia da `_set_last`/diagnostica (niente
# prefissi duplicati che possono divergere). L'ordine è quello di visualizzazione.
_LAST_FIELDS = (
    ("signal", "Ultimo segnale"),
    ("message", "Ultimo messaggio"),
    ("csv", "Ultimo CSV"),
    ("error", "Ultimo errore"),
)
_LAST_PREFIX = dict(_LAST_FIELDS)

# Retention log (PR-3): etichetta a tendina → giorni (0 = "Mai", conserva tutto).
_RETENTION_LABELS = {"Mai": 0, "5 giorni": 5, "15 giorni": 15, "30 giorni": 30}
# Etichette utente delle schede Strumenti ricaricate dopo un profilo (per i log).
_TOOL_PANEL_LABELS = {"provider": "Provider", "sources": "Chat sorgenti", "mapping": "Mapping"}


def _retention_label(days: int) -> str:
    """Etichetta della tendina per i giorni di retention (default «Mai» se ignoto)."""
    for label, value in _RETENTION_LABELS.items():
        if value == days:
            return label
    return "Mai"


class App(ctk.CTk):
    # Default di CLASSE (non di istanza): garantiscono che questi attributi esistano SEMPRE
    # nel class dict, così un accesso non trova mai "attributo mancante" che — su una vera
    # `customtkinter.CTk` senza `self.tk` inizializzato (es. istanza headless nei test) —
    # cadrebbe nel `__getattr__` di tkinter e ricorrerebbe all'infinito (RecursionError, #184 H1).
    _betfair_login_busy = False     # True mentre un login Betfair è in corso (anti-rientro)
    _betfair_login_epoch = 0        # epoch del login: logout/delete lo bumpa → scarta i completamenti stantii
    _betfair_panel = None           # pannello tab Betfair, valorizzato in `_open_tools`
    _async_stop_event = None        # asyncio.Event della sessione listener: STOP la sveglia (#184 H5/Codex #191)

    def __init__(self):
        super().__init__()
        self.title(f"XTrader Signal Bridge v{__version__}")
        # Altezza contenuta + altezza RIDIMENSIONABILE (larghezza fissa: il layout è
        # tarato in larghezza). Su schermi bassi (768/800px) il pannello monitoraggio a
        # schede — unico widget che si espande — si riduce e nulla finisce fuori schermo;
        # i comandi (START/STOP, config) stanno sopra e restano sempre visibili (finding
        # Codex). minsize evita un collasso eccessivo.
        # Clamp dell'altezza allo schermo (720x760 può sforare su display da 768px) +
        # minsize; la larghezza resta fissa (resizable solo in altezza, layout tarato
        # in larghezza). Il pannello monitoraggio espandibile assorbe la riduzione.
        gui_utils.fit_to_screen(self, 720, 760, 720, 600)
        self.resizable(False, True)

        # Bot token registrati nel redattore dei log (#184 M7 + #203): un INSIEME, non un singolo
        # valore. Serve a deregistrare i token non più necessari quando il token cambia (così il
        # registro non cresce all'infinito), MA tenendo registrato il token ancora in uso da un
        # listener attivo (#203): il poller in esecuzione usa lo snapshot a START e de-registrare
        # il suo token a metà sessione lo scriverebbe in chiaro. Inizializzato PRIMA di
        # _load_config, che chiama _register_secret_token.
        self._registered_tokens = set()
        self._config = self._load_config()
        self._running = False
        self._session_real = False   # la sessione attiva è partita in modalità reale? (#136 p4 banner)
        # Esito dell'ultimo salvataggio config su disco (A1): il bottone "Salva Config"
        # conferma "salvato" solo se True. Default True finché non si salva davvero.
        self._save_ok = True
        self._bot_thread = None
        self._tg_app = None
        self._loop = None
        # Contatore dei tentativi di riconnessione (supervisor del listener): cresce
        # ad ogni caduta di rete e si azzera a connessione stabilita.
        self._reconnect_attempt = 0
        # Chiusura in corso: impedisce all'auto-start ritardato di avviare il listener
        # dopo che la finestra è stata chiusa (Codex P2).
        self._closing = False
        # Lock per la creazione lazy degli oggetti Betfair condivisi (sessione/auth/engine):
        # ora il flusso live (thread listener Telegram) può costruire l'engine mentre il main
        # thread lo crea per la tab/auto-sync. Senza lock si creerebbero due engine e la
        # guardia "una sync per volta" (lock sull'istanza) verrebbe aggirata (Codex). RLock:
        # `_betfair_sync_engine` chiama `_betfair_session_obj` mentre tiene il lock.
        self._betfair_lock = threading.RLock()
        # Id del callback ritardato di auto-start: tracciato per poterlo ANNULLARE su
        # qualsiasi azione manuale (AVVIA/STOP/chiusura), così un'azione dell'utente
        # nella finestra dei 400 ms non viene scavalcata dall'auto-start (Codex P2).
        self._autostart_after_id = None
        # Segnale di STOP per interrompere SUBITO l'attesa del backoff (senza
        # busy-poll): impostato in _stop, azzerato a ogni START.
        self._stop_event = threading.Event()
        # Epoch della sessione listener: incrementato a ogni START. Il supervisor
        # gira solo finché il SUO epoch è quello corrente, così un riavvio rapido
        # durante un backoff non lascia vivo il vecchio supervisor (Codex P1:
        # niente due poller sulla stessa chat).
        self._listener_epoch = 0
        # CSV effettivamente scritto nella sessione corrente, catturato a START: lo
        # STOP pulisce QUESTO, non un csv_path eventualmente cambiato in GUI dopo
        # l'avvio (Codex P1). None = nessuna sessione attiva.
        self._active_csv_path = None
        # Guardrail del percorso di scrittura (PR-21), creati allo START dalla config:
        # tracker = dedup + limite/minuto (PR-15); daily = limite/giorno (PR-19).
        self._tracker = None
        self._daily = None
        # Coda dei segnali attivi (PR-22): determina quali righe sono nel CSV e
        # gestisce i timeout per-segnale. Mutata sia dal thread del bot (add) sia dal
        # timer di scadenza → protetta da un lock. Sostituisce il vecchio SignalGate.
        self._queue = None
        self._queue_lock = threading.Lock()
        self._expire_timer = None
        # Replace/cancel del timer di scadenza serializzati (#184 low-timer-lock): senza, due
        # caller concorrenti di `_schedule_expiry` potrebbero avviare due `threading.Timer` mentre
        # solo uno resta referenziato in `self._expire_timer` → l'altro fira lo stesso (leak,
        # double-fire idempotente). Lock DEDICATO, mai annidato nel `_queue_lock`: i caller
        # rilasciano il queue_lock prima, e il callback del timer usa solo il queue_lock.
        self._timer_lock = threading.Lock()
        # Escalation visibile su CSV-lock persistente (#153 H2): conta i fallimenti di
        # scrittura consecutivi e, oltre la soglia, segnala «CSV bloccato» (logica pura).
        self._csv_lock = csv_lock_escalation.CsvLockEscalation()
        # Errori di validazione delle impostazioni avanzate dall'ultimo _save_config:
        # se non vuoto, _start si rifiuta di avviare (PR-13, finding Codex P1).
        self._adv_errors = []
        # Contatori di sessione per la dashboard (PR-14): azzerati a ogni START.
        self._stats = dashboard_stats.DashboardStats()
        # Righe di log formattate tenute in memoria, per il filtro per livello (PR-14b).
        self._log_entries = []
        # Ultimi eventi per la diagnostica (PR-14c), per chiave. Aggiornati sul thread Tk.
        self._last_vals = {k: "" for k, _ in _LAST_FIELDS}
        # Event journal append-only (#230): ledger strutturato di "cosa ha fatto" il bridge,
        # accanto al config (AppData), per ricostruzione/forense dopo un crash. Diagnostico e
        # BEST-EFFORT (mai bloccante). Potato allo startup per non crescere all'infinito.
        self._journal_path = runtime_state.event_journal_path(config_dir())
        event_journal.prune_events(self._journal_path, _EVENT_JOURNAL_KEEP)
        # #234: stato REALE del CSV operativo PRIMA del cleanup d'avvio. Il diario emette un
        # clear/recovery SOLO sulla transizione riga→solo-header (vedi `_journal_csv_cleared_if_had_row`),
        # così una riscrittura idempotente di un CSV già a solo header NON viene scambiata per un
        # crash-recovery (falso positivo), mentre una riga stantia reale di una sessione morta sì.
        self._csv_had_active_row = has_active_row(
            str((self._config or {}).get("csv_path", "") or "").strip())

        self._build_ui()
        self._update_real_mode_banner(self._config)   # banner REALE all'avvio se persistito (#136 p4)
        self._update_active_indicator(0)              # indicatore righe attive (#136 p5)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Anti-segnale-stantio (blackout/crash): all'avvio il listener è ancora
        # spento, quindi una riga nel CSV è per forza orfana di una sessione morta
        # → riportiamo il CSV a solo header PRIMA di un eventuale START.
        self._clear_stale_csv("all'avvio")
        # Igiene del disco (#184 LOW): rimuove i temporanei `.segnali_*.tmp` orfani
        # lasciati da un crash/blackout TRA la creazione del tmp e il rename atomico.
        # Il CSV reale era già intatto; qui si evita solo che gli orfani si accumulino
        # riavvio dopo riavvio. Best-effort, mai bloccante. Il listener è ancora spento,
        # quindi nessuna scrittura è in volo: ogni tmp che combacia è orfano.
        self._sweep_orphan_csv_temps()
        # Avvio automatico del listener (se abilitato e config minima presente): dopo
        # che la UI è pronta, così log/stato sono visibili. Default OFF.
        self._autostart_after_id = self.after(400, self._maybe_auto_start)
        # Tick auto-sync Betfair (issue #86 PR-P8): parte mentre il bridge è aperto;
        # internamente scatta solo se l'auto-sync è attiva e all'orario impostato. Il
        # PRIMO check è quasi subito (non +60s) così aprire il bridge DENTRO l'ora
        # configurata non manca la run; poi si ri-arma ogni 60s.
        self._autosync_after_id = self.after(2_000, self._betfair_autosync_tick)

    def _maybe_auto_start(self) -> None:
        """Avvia il listener all'apertura se `auto_start_listener` è attivo e la config
        minima c'è. La decisione fine (config valida, conferma in modalità REALE) è in
        `_start(auto=True)`, basata sulla STESSA config che `_start` userà (Codex P2)."""
        self._autostart_after_id = None    # callback consumato
        # Un'azione manuale (AVVIA/STOP/chiusura) ha la precedenza sull'auto-start.
        if self._running or self._closing:
            return
        # Gate grezzo sulla config caricata: l'auto-start è una proprietà dell'apertura.
        # Se non era richiesto, non tocchiamo nulla (niente _save_config inutile).
        if not autostart.is_enabled(self._config):
            return
        self._start(auto=True)

    def _cancel_pending_autostart(self) -> None:
        """Annulla un auto-start ritardato ancora pendente (Codex P2): qualunque
        azione manuale dell'utente non deve essere scavalcata dal callback."""
        if self._autostart_after_id is not None:
            try:
                self.after_cancel(self._autostart_after_id)
            except Exception:        # noqa: BLE001 — id già scaduto/invalid: ininfluente
                pass
            self._autostart_after_id = None

    def _clear_stale_csv(self, quando: str, path: str = None) -> None:
        """Riporta il CSV a solo header se è un CSV del bridge (difesa
        anti-segnale-stantio). Best-effort: un errore di I/O non deve impedire
        avvio/chiusura. Se `path` è None usa quello in config (caso avvio)."""
        if path is None:
            path = str((self._config or {}).get("csv_path", "") or "").strip()
        else:
            path = str(path or "").strip()
        try:
            # `on_mismatch`: se il file esiste ma NON è un CSV del bridge (header diverso),
            # `clear_stale_csv` non lo tocca e prima restava silenzioso in GUI (il solo
            # logging.warning non si vede in un EXE --windowed). Lo facciamo emergere nel log
            # del bridge — visibile a schermo E nel file `bridge-*.log` — così l'utente capisce
            # perché il CSV è rimasto intatto (es. `csv_path` sbagliato) (#105 P2, Codex).
            if clear_stale_csv(path, on_mismatch=lambda m: self._log(f"⚠️ {m}")):
                # Messaggio neutro: clear_stale_csv ripristina l'header per qualsiasi
                # file esistente, anche se era già a solo header (niente riga rimossa).
                self._log(f"🧹 CSV riportato a solo header {quando}: {path}")
                # Event journal (#230/#234): un clear all'avvio è un recovery anti-segnale-stantio
                # (riga orfana di una sessione morta); negli altri casi è un clear normale. Emesso
                # SOLO se c'era davvero una riga (no falso recovery su CSV già a solo header, #234 A).
                self._journal_csv_cleared_if_had_row(
                    "CRASH_RECOVERY_CSV_CLEARED" if quando == "all'avvio" else "CSV_CLEARED",
                    quando=quando, path=path)
        except OSError as exc:
            # Lo svuotamento ha esaurito il budget di retry (XTrader tiene il lock a lungo):
            # un segnale potrebbe restare ATTIVO nel CSV. Avviso esplicito sulla conseguenza
            # (audit C3), così l'utente può chiudere XTrader / ripulire a mano e l'auto-clear
            # alla scadenza (con retry) riproverà comunque.
            self._log(f"⚠️ Impossibile ripulire il CSV {quando} ({exc}): un segnale potrebbe "
                      "restare attivo nel CSV finché XTrader non rilascia il file.")

    def _journal(self, event_type: str, **data) -> None:
        """Registra un evento nel ledger append-only (#230). **Best-effort/diagnostico**:
        non solleva MAI e non altera il flusso di trading (il journal è uno strumento di
        ricostruzione, non parte del percorso CSV/coda). No-op se il path non è impostato
        (es. istanze headless di test che non chiamano `__init__`). Il payload è redatto da
        `event_journal` (mai token in chiaro)."""
        path = self.__dict__.get("_journal_path")
        if not path:
            return
        try:
            event_journal.append_event(path, event_type, data)
        except Exception:   # noqa: BLE001,S110 — il journal è diagnostico: un suo errore non deve
            pass            # mai propagare nel percorso di trading (best-effort, niente log: il
            #                 sink di log potrebbe a sua volta fallire e il diario non è critico)

    def _journal_csv_cleared_if_had_row(self, event_type: str, **data) -> None:
        """Registra un evento di CLEAR del CSV (`CSV_CLEARED`/`CRASH_RECOVERY_CSV_CLEARED`) SOLO se
        il CSV operativo aveva davvero una riga attiva — cioè sulla transizione reale
        riga→solo-header — poi azzera il flag `_csv_had_active_row` (#234).

        Evita due falsi del diario: (a) un crash-recovery/clear su una riscrittura idempotente di un
        CSV già a solo header (falso positivo), e (b) — combinato con l'impostazione del flag dopo
        ogni scrittura con righe — la perdita del clear quando è un retry/START a riportare il CSV a
        solo header. Best-effort: il flag è un mirror diagnostico dello stato disco, aggiornato fuori
        dal `_queue_lock`; un eventuale micro-disallineamento concorrente non tocca il trading."""
        if self.__dict__.get("_csv_had_active_row"):
            self._journal(event_type, **data)
        self._csv_had_active_row = False

    def _sweep_orphan_csv_temps(self) -> None:
        """Rimuove i temporanei `.segnali_*.tmp` orfani nella cartella del CSV (#184 LOW).
        Best-effort: delega a `csv_writer.sweep_orphan_temps` (non solleva mai). Logga solo
        se ne ha rimossi davvero, per non rumoreggiare a ogni avvio pulito."""
        path = str((self._config or {}).get("csv_path", "") or "").strip()
        if not path:
            return
        removed = sweep_orphan_temps(path)
        if removed:
            self._log(f"🧹 Rimossi {removed} file temporanei CSV orfani all'avvio.")

    # ── CONFIG ────────────────────────────────
    def _register_secret_token(self, cfg) -> None:
        """Registra il bot token corrente nel redattore dei log (#184 M7): così viene
        mascherato per-literal in QUALSIASI forma finisca in un log (anche non-canonica,
        che la regex di `redact_secrets` non riconoscerebbe). No-op se non c'è token.

        De-registra i token non più necessari quando il token cambia (Sourcery): così il registro
        non cresce all'infinito e un vecchio token non resta mascherato per sempre. **Eccezione
        (#203, Codex):** mentre il listener è ATTIVO (`_running`) NON si de-registra nulla — il
        poller in esecuzione usa ancora il token della sessione (snapshot a START) e
        de-registrarlo a metà sessione lo scriverebbe in chiaro se finisse in un log. Il registro
        cresce al più di un token per cambio durante una sessione attiva e si ripulisce al primo
        save/reload a listener fermo. Punto unico usato da `_load_config`/`_save_config`."""
        new_token = cfg.get("bot_token") if isinstance(cfg, dict) else None
        # Lettura via __dict__ e NON getattr: su un widget Tk un attributo ASSENTE farebbe
        # ricorrere `__getattr__` (→ RecursionError), e il default di getattr non lo intercetta.
        registered = self.__dict__.setdefault("_registered_tokens", set())
        if new_token and event_log.register_secret(new_token):
            registered.add(new_token)
        # Cleanup SOLO a listener COMPLETAMENTE fermo (#203, Codex + CodeRabbit): non basta
        # `_running=False`, perché `_stop` lo azzera PRIMA che il thread del poller sia davvero
        # uscito (può essere in backoff o a metà di un handler) e in quella finestra il vecchio
        # token è ancora in uso → de-registrarlo lo scriverebbe in chiaro. Si controlla quindi
        # anche `_bot_thread.is_alive()` (lo stesso segnale di teardown usato da `_is_current`).
        # Letture via __dict__: niente `__getattr__` recursion su widget Tk (regressione #184 M7).
        bot_thread = self.__dict__.get("_bot_thread")
        listener_alive = bool(self.__dict__.get("_running")) or (
            bot_thread is not None and bot_thread.is_alive())
        if not listener_alive:
            for tok in list(registered):
                if tok != new_token:
                    event_log.unregister_secret(tok)
                    registered.discard(tok)

    def _had_incomplete_token_load(self) -> bool:
        """True se la config viva porta il marker `_token_load_incomplete` (#140): il
        `bot_token` è vuoto perché il keyring era ILLEGGIBILE al load (outage), non perché
        l'utente l'abbia cancellato. Va letto PRIMA di un `save_config` (che CONSUMA il
        marker reidratando il token) per sapere, DOPO il save, se il campo password va
        risincronizzato col token reidratato (PR-08c). Lettura via `__dict__` per non
        innescare `__getattr__` su un widget Tk (regressione #184 M7)."""
        cfg = self.__dict__.get("_config")
        return bool(isinstance(cfg, dict)
                    and cfg.get(config_store.TOKEN_LOAD_INCOMPLETE_KEY))

    def _resync_token_field(self, had_incomplete_load=None) -> None:
        """Risincronizza il campo password del token con la credenziale REIDRATATA dal keyring
        dopo un load incompleto (#140/#256, PR-08c), così un save successivo non scambia il
        campo vuoto per un clear deliberato e non cancella il bot token dal keyring.

        Senza questo, il difetto noto è la PERDITA AL 2° SAVE: dopo un outage del keyring al
        load `save_config` reidrata `self._config["bot_token"]` e consuma il marker, ma il campo
        GUI resta vuoto; il save normale successivo ricostruisce la config dal campo vuoto, entra
        nel ramo clear REALE e cancella il token. Stessa lacuna per i save dei tab Tools, i save
        non-GUI (debug/retention/auto-sync Betfair) e START (che valida il campo vuoto prima che
        un save reidrati).

        Agisce SOLO se: esiste il campo, è VUOTO, e il load era incompleto (`had_incomplete_load`;
        se None lo deduce dal marker nella config viva). Un clear DELIBERATO (campo svuotato a mano
        a load COMPLETO → nessun marker) NON viene mai resuscitato; un token appena DIGITATO (campo
        non vuoto) non viene mai sovrascritto.

        Sorgente del token: la config viva se già reidratata (post-save), altrimenti — quando la
        config non ce l'ha ancora (es. START prima di qualsiasi save) — una lettura diretta del
        keyring. Quando reidrata: ripopola il campo, REGISTRA il token nel redattore log (così non
        finisce mai in chiaro anche fuori da `_save_config`) e CONSUMA il marker dalla config viva —
        da quel momento il campo porta il token, la protezione non serve più e un clear deliberato
        successivo resta valido anche se il save che avrebbe consumato il marker non è ancora
        avvenuto (es. START che poi fallisce la validazione prima di `_save_config`) — Codex."""
        entry = self.__dict__.get("_e_token")
        if entry is None:
            return
        try:
            if entry.get().strip():
                return   # campo già pieno: non sovrascrivere (token digitato / clear deliberato)
        except Exception:   # noqa: BLE001 — widget Tk distrutto: tratta come assente
            return
        cfg = self._config if isinstance(self._config, dict) else {}
        if had_incomplete_load is None:
            had_incomplete_load = bool(cfg.get(config_store.TOKEN_LOAD_INCOMPLETE_KEY))
        if not had_incomplete_load:
            return   # load completo: un campo vuoto è uno stato reale, niente reidratazione
        token = str(cfg.get("bot_token") or "")
        if not token:
            # Config non ancora reidratata (es. START prima del save): leggi ORA dal keyring,
            # distinguendo "assente" da "lettura fallita" così un keyring ancora giù non reidrata
            # (il marker resta per il retry).
            stored, read_ok = config_store.token_store.load_token_status()
            if read_ok and stored:
                token = stored
        if not token:
            return   # keyring ancora illeggibile/vuoto: niente da reidratare (marker preservato)
        entry.delete(0, "end")
        entry.insert(0, token)
        self._register_secret_token({"bot_token": token})
        if isinstance(self._config, dict):
            # Specchia il token reidratato nella config viva PRIMA di consumare il marker (Codex
            # #257): se un path che NON rilegge il campo gira dopo che il marker è stato consumato
            # ma prima di un `_save_config` (es. START reidrata dal keyring poi ABORTA per csv/timeout
            # invalidi, e poi scatta un save non-GUI debug/retention/auto-sync che usa `self._config`
            # direttamente), deve trovare il token in `self._config["bot_token"]`. Senza questo mirror
            # vedrebbe `bot_token=""` senza marker → ramo clear REALE → `delete_token` cancellerebbe
            # la credenziale appena reidratata nel campo.
            self._config["bot_token"] = token
            self._config.pop(config_store.TOKEN_LOAD_INCOMPLETE_KEY, None)

    def _load_config(self) -> dict:
        # Migra il vecchio config.json (accanto all'EXE) la prima volta, poi carica
        # dalla cartella utente persistente (%APPDATA%\XTraderBridge).
        migrate_legacy_config(CONFIG_FILE)
        cfg = load_config(CONFIG_FILE)
        self._register_secret_token(cfg)   # #184 M7: token noto → mascherato nei log
        return cfg

    def _gate_dangerous_transitions(self, old_cfg, cfg):
        """Applica le conferme di sicurezza alle transizioni PERICOLOSE di `cfg` rispetto a
        `old_cfg`, e ritorna `cfg` (eventualmente corretto). Due gate:

        - **modalità REALE** (#136 p4): attivare il reale (sim→reale) è la transizione più
          pericolosa → doppia conferma (`_confirm_real_mode`). Se annullata, si ripristina la
          simulazione (`dry_run=True`) sia nella cfg sia nella spunta del form.
        - **coda MULTI-segnale** (#136 p5): passare a una coda multi-riga (più scommesse
          simultanee) richiede conferma (`_confirm_multi_signal`). Se rifiutata, si torna a
          `OVERWRITE_LAST` (un solo segnale attivo) nella cfg e nel form.

        Centralizzato qui perché va applicato a OGNI punto che cambia la config in modo
        persistente: il bottone Salva **e** il CARICAMENTO PROFILO — altrimenti un profilo con
        `dry_run:false`/coda multi attiverebbe reale/multi senza conferma (#141/#142)."""
        if real_mode.requires_confirmation(old_cfg, cfg):
            if self._confirm_real_mode():
                # Evento di AUDIT nel log persistente (tracciabilità dell'attivazione).
                self._log("⚠️ " + real_mode.enabled_message())
            else:
                cfg["dry_run"] = True
                if "dry_run" in self._adv:
                    self._adv["dry_run"].set(True)   # ri-spunta "🧪 Simulazione (DRY_RUN)"
                self._log("↩️ Attivazione modalità REALE ANNULLATA: il bridge resta in simulazione.")
        if multi_signal.requires_warning(old_cfg, cfg):
            if not self._confirm_multi_signal(
                    cfg.get("max_active_signals", DEFAULTS["max_active_signals"])):
                cfg["queue_mode"] = signal_queue.OVERWRITE_LAST
                if "queue_mode" in self._adv:
                    self._adv["queue_mode"].set(signal_queue.OVERWRITE_LAST)
                self._log("↩️ Modalità coda multi-segnale ANNULLATA: resto a un solo segnale "
                          "attivo (OVERWRITE_LAST).")
        return cfg

    def _persist_loaded_profile(self, new_cfg):
        """Persiste un profilo CARICATO applicando gli STESSI gate di sicurezza del bottone
        Salva (#141/#142) e aggiornando il banner reale (#141, Codex review), poi ritorna
        `(saved, ok)`. La parte di refresh dei pannelli/form resta nel chiamante (è solo
        presentazione). Estratto per essere testabile headless (la closure `_profiles_loaded`
        non lo è)."""
        old_cfg = self._config if isinstance(self._config, dict) else {}
        cfg = self._gate_dangerous_transitions(old_cfg, dict(new_cfg))
        saved, ok = result = save_config(cfg, CONFIG_FILE)
        self._config = saved
        # PR-08c: se il save ha reidratato il token dal keyring (load era incompleto), registralo
        # nel redattore log. Il campo password lo ripopola già `_populate_form(saved)` nel chiamante
        # (`_profiles_loaded`), ma quel path NON passa da `_register_secret_token`, quindi senza
        # questo il token reidratato resterebbe fuori dal registro e un log potrebbe esporlo.
        self._register_secret_token(saved)
        self._save_ok = ok
        # Banner rosso persistente se il profilo ha attivato il REALE: senza questo il reale
        # resterebbe attivo senza warning visibile fino al successivo save/start/riavvio.
        self._update_real_mode_banner(saved)
        # Ritorna il SaveResult (si spacchetta come `(saved, ok)` per i chiamali storici, ma porta
        # anche `.status` per il messaggio specifico in `_profiles_loaded`) — contratto #255 line-647.
        return result

    def _save_config(self, persist: bool = True) -> dict:
        # `persist=False`: SNAPSHOT PURO del form SENZA effetti collaterali — non scrive
        # config.json, non muta campi GUI/`self._adv_errors`, non logga, non esegue i gate
        # di transizione pericolosa (che PROMPTano e scrivono audit `REAL_MODE_ENABLED`).
        # Serve a chi ha solo bisogno della config corrente — es. salvare un profilo — così
        # un salvataggio profilo che poi FALLISCE non ha già committato impostazioni
        # safety-critical (dry_run/csv_path/chat) nel config vivo, né registrato "reale
        # attivo" nell'audit mentre la config viva resta dry-run (Codex/CodeRabbit #60). La
        # persistenza + i gate + il logging restano tutti sul percorso `persist=True`.
        # Cattura il marker PRIMA di qualsiasi consumo (sia il refill pre-lettura qui sotto sia
        # `save_config` possono consumarlo): serve per il refill POST-save (Codex #257).
        had_incomplete = self._had_incomplete_token_load()
        # Reidratazione del campo token PRIMA di leggere il form (PR-08c): se il keyring era
        # illeggibile al load (marker `_token_load_incomplete`) il campo è vuoto pur esistendo
        # una credenziale; ripopolarlo ora evita che il `bot_token` vuoto del form venga letto
        # come clear deliberato e cancelli il token (perdita al 2° save). No-op se il campo è
        # già pieno, se non c'è marker (clear deliberato) o se il keyring è ancora giù.
        # Solo su `persist=True`: è una MUTAZIONE del campo GUI, non deve avvenire in uno
        # snapshot puro (Codex/CodeRabbit #60).
        if persist:
            self._resync_token_field()
        # Timeout robusto: un valore non numerico non deve crashare il salvataggio
        # (PR-13/#10). Se invalido, si tiene il default e si avvisa nel log (solo persist:
        # lo snapshot puro non deve loggare).
        delay, delay_err = settings_validation.parse_timeout(self._e_delay.get())
        if delay_err:
            delay = settings_validation.DEFAULT_TIMEOUT
            if persist:
                self._log(f"⚠️ {delay_err} Uso {delay}s.")
        # Si parte dalla config CARICATA e si sovrascrivono solo i campi del form:
        # così ogni impostazione senza campo GUI (recognition_mode, require_price,
        # active_parser, parser_by_chat, source_chats, le chiavi delle conferme
        # XTrader, ecc.) viene PRESERVATA e non si perde al salvataggio — niente
        # drift quando si aggiungono nuove chiavi.
        cfg = dict(self._config) if isinstance(self._config, dict) else {}
        cfg.update({
            "bot_token":   self._e_token.get().strip(),
            "chat_id":     self._e_chat.get().strip(),
            "csv_path":    self._e_csv.get().strip(),
            "clear_delay": delay,
            "provider":    self._e_provider.get().strip() or "TelegramBot",
        })
        adv_form = {key: w.get() for key, w in self._adv.items()}
        if not persist:
            # SNAPSHOT PURO (Codex/CodeRabbit #60): merge delle avanzate SENZA mutare
            # `self._adv_errors`, SENZA loggare e SENZA i gate transizione (che PROMPTano
            # e loggano audit `REAL_MODE_ENABLED`). Un salvataggio profilo non deve
            # registrare "reale attivo" nell'audit mentre il config vivo resta dry-run,
            # né far comparire prompt di conferma: profili e config sono gated a LOAD/START
            # (#141/#142) e `save_profile` rimuove comunque i segreti. Ritorna la config
            # del form senza alcun effetto collaterale su disco, stato o UI.
            cfg, _ = settings_controller.apply_advanced(cfg, adv_form)
            return cfg
        # Impostazioni avanzate (PR-13): valida e fonde tramite il controller puro.
        # Se un valore è invalido viene loggato e NON applicato: le chiavi avanzate
        # mantengono l'ultimo valore valido (così un errore di battitura non spegne
        # per sbaglio la simulazione o azzera un limite).
        cfg, self._adv_errors = settings_controller.apply_advanced(cfg, adv_form)
        for err in self._adv_errors:
            self._log(f"⚠️ Impostazioni avanzate: {err}")
        # Transizioni pericolose (attivazione REALE / coda multi-segnale): doppia conferma.
        # STESSA logica usata dal CARICAMENTO PROFILO, così un profilo con dry_run:false o
        # coda multi-riga NON bypassa i gate (#141/#142) — estratta in
        # `_gate_dangerous_transitions`.
        old_cfg = self._config if isinstance(self._config, dict) else {}
        cfg = self._gate_dangerous_transitions(old_cfg, cfg)
        saved, ok = result = save_config(cfg, CONFIG_FILE)
        self._config = saved
        # Refill POST-save (Codex #257): se il refill pre-lettura aveva MANCATO (keyring giù in quel
        # momento) ma `save_config` ha poi reidratato il token (keyring rientrato a metà chiamata)
        # consumando il marker, il campo è ancora vuoto e un save successivo lo scambierebbe per un
        # clear cancellando la credenziale. Risincronizza ora col token reidratato. No-op se il campo
        # è già pieno (refill pre-lettura riuscito) o se non c'era un load incompleto.
        self._resync_token_field(had_incomplete)
        self._register_secret_token(saved)     # #184 M7: aggiorna il token mascherato nei log
        self._update_real_mode_banner(saved)   # banner rosso persistente se in REALE (#136 p4)
        if not self._running:
            self._update_active_indicator(0)   # indicatore tetto aggiornato (#136 p5)
        # Esito reale della persistenza (A1): se il disco ha fallito lo si SEGNALA sempre
        # (a ogni save point), così l'utente non resta con l'illusione di aver salvato.
        # `_save_ok` lascia decidere al bottone se loggare il "salvato" di conferma.
        self._save_ok = ok
        if not ok:
            # Messaggio SPECIFICO della causa (#255 line-647): disco vs keyring (token rimandato)
            # vs config corrotto. Niente più "FALLITO su disco" quando il problema è il keyring.
            self._log("❌ " + config_store.save_status_message(result.status))
        # Mantiene il pannello "Chat ascoltate" allineato alla config salvata: unico
        # punto, così non va ripetuto a ogni call site (bottone Salva, AVVIA, ...).
        self._refresh_listened_chats()
        self._dbg(f"CONFIG salvata (ok={ok}): csv={cfg.get('csv_path', '')}, "
                  f"provider={cfg.get('provider', '')}, "
                  f"dry_run={safety_guard.is_dry_run(cfg)}")
        return saved

    def _on_save_clicked(self) -> None:
        """Bottone 'Salva Config': persiste il form e conferma "salvato" SOLO se la
        scrittura su disco è andata a buon fine (A1). Un eventuale fallimento è già
        segnalato da `_save_config`, quindi qui non si ripete l'errore."""
        self._save_config()
        if self._save_ok:
            self._log("💾 Configurazione salvata")

    def _profiles_snapshot(self) -> dict:
        """Config viva (con token) letta dal form SENZA persistere né effetti collaterali.
        Passata come `get_current_cfg` al pannello Profili: la base per salvare un profilo
        (i segreti vengono comunque rimossi da `save_profile`) e per preservare il token al
        caricamento. È lo snapshot puro di `_save_config(persist=False)` — nessuna scrittura
        su disco, nessun gate/prompt/audit, nessun log (Codex/CodeRabbit #60)."""
        return self._save_config(persist=False)

    # ── UI ────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=10)
        hdr.pack(fill="x", padx=15, pady=(12, 5))

        ctk.CTkLabel(hdr, text="🤖  XTrader Signal Bridge",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#4fc3f7").pack(side="left", padx=15, pady=10)

        self._status_lbl = ctk.CTkLabel(hdr, text="⬤  OFFLINE",
                                         font=ctk.CTkFont(size=13, weight="bold"),
                                         text_color="#ef5350")
        self._status_lbl.pack(side="right", padx=15)

        # Indicatore "righe attive" (#136 punto 5): quante righe/scommesse sono attive ora
        # nel CSV. Aggiornato da `_update_active_indicator` su scrittura/scadenza/clear.
        self._active_lbl = ctk.CTkLabel(hdr, text="", font=ctk.CTkFont(size=12),
                                        text_color="#ffb74d")
        self._active_lbl.pack(side="right", padx=(0, 6))

        # Banner ROSSO persistente quando il bridge è in modalità REALE (#136 punto 4).
        # Mostrato/nascosto da `_update_real_mode_banner` in base a `real_mode.banner_text`.
        self._real_banner = ctk.CTkLabel(
            self, text="", fg_color="#7f1d1d", text_color="white", corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"))

        # Config a tab (PR-13): impostazioni base + avanzate. Le avanzate erano prima
        # modificabili solo a mano in config.json; la logica vive nel controller puro
        # `settings_controller` (testato in CI), qui solo i widget.
        tabs = ctk.CTkTabview(self, height=210)
        tabs.pack(fill="x", padx=15, pady=5)
        # Riferimento per impaccare il banner REALE SOPRA i tab (vicino all'header) anche
        # quando viene mostrato la prima volta dopo i tab già impaccati (Codex P2: senza
        # `before` Tk lo metterebbe in fondo, fuori vista).
        self._tabs = tabs
        tab_gen = tabs.add("⚙️ Generale")
        tab_rec = tabs.add("🎯 Riconoscimento")
        tab_safe = tabs.add("🛡️ Sicurezza")
        tab_conf = tabs.add("✅ Conferme XTrader")

        # — Generale: i campi storici (token, chat, CSV, timeout, provider) —
        self._entries = {}
        gen_fields = [
            ("🔑 Bot Token",     "bot_token",   True),
            ("💬 Chat ID",       "chat_id",     False),
            ("📄 CSV Path",      "csv_path",    False),
            ("⏱️ Timeout (sec)", "clear_delay", False),
            ("🏷️ Provider",     "provider",    False),
        ]
        for r, (label, key, is_pwd) in enumerate(gen_fields):
            ctk.CTkLabel(tab_gen, text=label, width=140, anchor="w").grid(
                row=r, column=0, padx=(10, 5), pady=4, sticky="w")
            e = ctk.CTkEntry(tab_gen, width=470, show="●" if is_pwd else "")
            e.insert(0, str(self._config.get(key, "")))
            e.grid(row=r, column=1, padx=(0, 10), pady=4, sticky="w")
            self._entries[key] = e
        self._e_token    = self._entries["bot_token"]
        self._e_chat     = self._entries["chat_id"]
        self._e_csv      = self._entries["csv_path"]
        self._e_delay    = self._entries["clear_delay"]
        self._e_provider = self._entries["provider"]

        # — Impostazioni avanzate: valori correnti dal controller (default sicuri) —
        adv = settings_controller.current_values(self._config)
        self._adv = {}

        # Riconoscimento
        self._adv["recognition_mode"] = self._add_option(
            tab_rec, "🎯 Modalità riconoscimento",
            settings_controller.recognition_mode_options(), adv["recognition_mode"], 0)
        # La quota obbligatoria sì/no NON è più un interruttore globale: la governa la
        # casella «Obblig.» sulla riga Price di OGNI Parser Personalizzato (unico comando).

        # Sicurezza
        self._adv["dry_run"] = self._add_check(
            tab_safe, "🧪 Simulazione (DRY_RUN): NON scrive il CSV operativo",
            adv["dry_run"], 0)
        self._adv["max_per_day"] = self._add_entry(
            tab_safe, "📅 Limite segnali al giorno", str(adv["max_per_day"]), 1)
        self._adv["queue_mode"] = self._add_option(
            tab_safe, "🧮 Modalità coda segnali",
            settings_controller.queue_mode_options(), adv["queue_mode"], 2)
        self._adv["auto_start_listener"] = self._add_check(
            tab_safe, "▶️ Avvio automatico all'apertura (in modalità REALE chiede conferma)",
            adv["auto_start_listener"], 3)
        self._adv["debug_message_payload"] = self._add_check(
            tab_safe, "🕵️ Logga il testo completo dei messaggi (debug; OFF = solo hash + 1ª riga)",
            adv["debug_message_payload"], 4)
        self._adv["max_active_signals"] = self._add_entry(
            tab_safe, "🔢 Max segnali attivi (modalità coda multi-riga)",
            str(adv["max_active_signals"]), 5)

        # Conferme XTrader: chat notifiche + timeout conferma (PR-17b, attivo in
        # QUEUE_UNTIL_CONFIRMED) + parole chiave conferma/rifiuto come stringa CSV.
        self._adv["xtrader_notification_chat_id"] = self._add_entry(
            tab_conf, "💬 Chat notifiche XTrader", adv["xtrader_notification_chat_id"], 0)
        self._adv["confirmation_timeout"] = self._add_entry(
            tab_conf, "⏳ Timeout conferma (sec)", str(adv["confirmation_timeout"]), 1)
        self._adv["confirmation_keywords"] = self._add_entry(
            tab_conf, "✅ Parole conferma (separate da virgola)",
            adv["confirmation_keywords"], 2)
        self._adv["rejection_keywords"] = self._add_entry(
            tab_conf, "❌ Parole rifiuto (separate da virgola)",
            adv["rejection_keywords"], 3)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=6)

        self._btn_start = ctk.CTkButton(
            btn_frame, text="▶  AVVIA", width=160, height=42,
            fg_color="#2e7d32", hover_color="#1b5e20",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start)
        self._btn_start.pack(side="left", padx=5)

        self._btn_stop = ctk.CTkButton(
            btn_frame, text="■  STOP", width=160, height=42,
            fg_color="#c62828", hover_color="#7f0000",
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
            command=self._stop)
        self._btn_stop.pack(side="left", padx=5)

        self._btn_clear = ctk.CTkButton(
            btn_frame, text="🗑️  Svuota CSV ora", width=175, height=42,
            command=self._manual_clear)
        self._btn_clear.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="💾  Salva Config", width=140, height=42,
            fg_color="#37474f", hover_color="#263238",
            command=self._on_save_clicked,
        ).pack(side="right", padx=5)

        # Consolidazione GUI (roadmap, Tappa 3): tutti gli strumenti vivono come schede di
        # un'unica finestra "🧰 Strumenti" (Parser, Chat sorgenti, Provider, Profili,
        # Mapping). Un solo pulsante al posto dei cinque precedenti.
        tools_frame = ctk.CTkFrame(self, fg_color="transparent")
        tools_frame.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkButton(
            tools_frame, text="🧰  Strumenti", width=220, height=40,
            fg_color="#4527a0", hover_color="#311b92",
            command=self._open_tools).pack(side="left", padx=5)

        # Monitoraggio a schede (B3): Chat ascoltate / Stato / Dashboard / Log erano
        # quattro pannelli impilati che allungavano molto la finestra. Ora vivono in un
        # solo Tabview (una scheda per volta): stessi widget e stessi riferimenti, nessun
        # campo rimosso — solo meno clutter verticale. Config e pulsanti restano sopra,
        # sempre visibili. I titoli interni ridondanti sono rimossi (li porta la scheda).
        # Le etichette delle schede sono solo per la UI: nessun altro punto del codice
        # dipende dai nomi o dall'ordine (i widget si referenziano via attributi self._*),
        # quindi rinominarle/riordinarle è sicuro.
        mon = ctk.CTkTabview(self)
        mon.pack(fill="both", expand=True, padx=15, pady=(5, 12))
        tab_chats = mon.add("📡 Chat ascoltate")
        tab_stato = mon.add("📡 Stato")
        tab_dash = mon.add("📊 Dashboard")
        tab_log = mon.add("📋 Log")

        # — Chat ascoltate (B1): vista READ-ONLY delle chat che il listener processerà,
        # coi nomi leggibili (da source_chats) quando disponibili. Aggiornata a Salva
        # Config e al caricamento di un profilo. Rende visibile il modello "ascolta solo
        # queste chat, mai tutte" (allowed_chats, A2).
        self._chats_lbl = ctk.CTkLabel(
            tab_chats, text="", font=ctk.CTkFont(size=11), text_color="gray",
            wraplength=_CONTENT_WRAP, anchor="w", justify="left")
        self._chats_lbl.pack(anchor="w", padx=12, pady=8)
        self._refresh_listened_chats()

        # — Stato + diagnostica (PR-14c): ultimo segnale/messaggio/CSV/errore + pulsanti
        # "Apri cartella log" e "Copia diagnostica" (per il supporto). —
        sig_hdr = ctk.CTkFrame(tab_stato, fg_color="transparent")
        sig_hdr.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkButton(sig_hdr, text="📋 Copia diagnostica", width=160, height=28,
                      fg_color="#37474f", hover_color="#263238",
                      command=self._copy_diagnostics).pack(side="right", padx=(6, 0))
        ctk.CTkButton(sig_hdr, text="📂 Apri cartella log", width=160, height=28,
                      fg_color="#37474f", hover_color="#263238",
                      command=self._open_log_folder).pack(side="right", padx=(6, 0))
        ctk.CTkButton(sig_hdr, text="🧾 Esporta audit reale", width=170, height=28,
                      fg_color="#37474f", hover_color="#263238",
                      command=self._export_real_audit).pack(side="right", padx=(6, 0))
        _sty = dict(font=ctk.CTkFont(size=11), text_color="gray",
                    wraplength=_CONTENT_WRAP, anchor="w", justify="left")
        # Una label per campo, creata dalla fonte unica _LAST_FIELDS (niente prefissi
        # duplicati a mano). _set_last le aggiorna usando lo stesso prefisso.
        self._last_lbls = {}
        for i, (kind, prefix) in enumerate(_LAST_FIELDS):
            lbl = ctk.CTkLabel(tab_stato, text=f"{prefix}: —", **_sty)
            pady = (0, 1) if i == 0 else ((1, 8) if i == len(_LAST_FIELDS) - 1 else 1)
            lbl.pack(anchor="w", padx=12, pady=pady)
            self._last_lbls[kind] = lbl

        # — Dashboard contatori di sessione (PR-14): esiti del flusso dall'ultimo START. —
        ctk.CTkLabel(tab_dash, text="Contatori dall'avvio", font=ctk.CTkFont(size=11),
                     text_color="gray").grid(
            row=0, column=0, columnspan=len(dashboard_stats.COUNTERS),
            sticky="w", padx=12, pady=(8, 2))
        self._stat_lbls = {}
        for col, (name, label) in enumerate(dashboard_stats.COUNTERS):
            cell = ctk.CTkFrame(tab_dash, fg_color="transparent")
            cell.grid(row=1, column=col, padx=8, pady=(0, 8), sticky="w")
            ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=10),
                         text_color="gray").pack(anchor="w")
            val = ctk.CTkLabel(cell, text="0", font=ctk.CTkFont(size=16, weight="bold"))
            val.pack(anchor="w")
            self._stat_lbls[name] = val

        # — Log + filtro per livello (PR-14b) —
        log_hdr = ctk.CTkFrame(tab_log, fg_color="transparent")
        log_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(log_hdr, text="Mostra:", font=ctk.CTkFont(size=11),
                     text_color="gray").pack(side="left", padx=(0, 4))
        self._log_filter = tk.StringVar(master=self, value=log_view.ALL)
        ctk.CTkOptionMenu(log_hdr, values=list(log_view.OPTIONS), width=130,
                          variable=self._log_filter,
                          command=lambda _v: self._render_log()).pack(side="left")
        # Retention + Debug (PR-3): conserva log per N giorni (auto-pulizia), svuota
        # adesso, e modalità Debug (log dettagliato del percorso).
        self._retention_var = tk.StringVar(
            master=self, value=_retention_label(event_log.retention_days(self._config)))
        ctk.CTkLabel(log_hdr, text="Conserva:", font=ctk.CTkFont(size=11),
                     text_color="gray").pack(side="left", padx=(12, 4))
        ctk.CTkOptionMenu(log_hdr, values=list(_RETENTION_LABELS), width=110,
                          variable=self._retention_var,
                          command=self._on_retention_change).pack(side="left")
        ctk.CTkButton(log_hdr, text="🧹 Svuota log", width=110, height=28,
                      fg_color="#37474f", hover_color="#263238",
                      command=self._clear_logs_now).pack(side="left", padx=(8, 0))
        self._debug_var = tk.BooleanVar(master=self, value=as_bool(self._config.get("debug_log", False)))
        ctk.CTkCheckBox(log_hdr, text="🐞 Debug", variable=self._debug_var,
                        command=self._on_debug_toggle).pack(side="left", padx=(12, 0))
        self._log_box = ctk.CTkTextbox(
            tab_log, font=ctk.CTkFont(size=11, family="Courier"))
        self._log_box.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    # ── widget helper per le impostazioni avanzate (PR-13) ────────────────
    def _add_entry(self, parent, label, value, row):
        """Campo di testo etichettato; ritorna l'Entry (si legge con `.get()`)."""
        ctk.CTkLabel(parent, text=label, width=240, anchor="w").grid(
            row=row, column=0, padx=(10, 5), pady=5, sticky="w")
        e = ctk.CTkEntry(parent, width=360)
        e.insert(0, str(value))
        e.grid(row=row, column=1, padx=(0, 10), pady=5, sticky="w")
        return e

    def _add_option(self, parent, label, options, value, row):
        """Menu a tendina etichettato; ritorna la StringVar (`.get()`)."""
        ctk.CTkLabel(parent, text=label, width=240, anchor="w").grid(
            row=row, column=0, padx=(10, 5), pady=5, sticky="w")
        var = tk.StringVar(master=self, value=value)
        ctk.CTkOptionMenu(parent, values=options, variable=var, width=360).grid(
            row=row, column=1, padx=(0, 10), pady=5, sticky="w")
        return var

    def _add_check(self, parent, label, value, row):
        """Checkbox; ritorna la BooleanVar (`.get()`)."""
        var = tk.BooleanVar(master=self, value=bool(value))
        ctk.CTkCheckBox(parent, text=label, variable=var).grid(
            row=row, column=0, columnspan=2, padx=10, pady=8, sticky="w")
        return var

    # ── CHAT ASCOLTATE (B1) ───────────────────
    def _refresh_listened_chats(self) -> None:
        """Aggiorna il pannello 'Chat ascoltate' dalla config corrente. Mostra i nomi
        leggibili (source_chats) o l'ID, oppure un avviso se nessuna chat è configurata
        (in quel caso il bridge non parte: fail-fast d'avvio). Solo lettura: non cambia
        config né runtime. Thread Tk."""
        # Guardia: _save_config può essere chiamato (in teoria) prima che _build_ui abbia
        # creato il pannello; in quel caso non c'è nulla da aggiornare.
        if not hasattr(self, "_chats_lbl"):
            return
        cfg = self._config if isinstance(self._config, dict) else {}
        rows = signal_router.listened_chats(cfg)
        if not rows:
            self._chats_lbl.configure(
                text="⚠️ Nessuna chat configurata — il bridge non si avvierà finché non "
                     "imposti una Chat ID o una Chat sorgente.",
                text_color="#ffa726")
            return
        lines = [f"• {r['name']}  ({r['chat_id']})" if r["name"] else f"• {r['chat_id']}"
                 for r in rows]
        self._chats_lbl.configure(
            text=f"Il bridge ascolterà queste {len(rows)} chat:\n" + "\n".join(lines),
            text_color="gray")

    # ── DASHBOARD (PR-14) ─────────────────────
    def _refresh_dashboard(self) -> None:
        """Aggiorna le label dei contatori dai valori correnti. Thread Tk."""
        counts = self._stats.as_dict()
        for name, lbl in self._stat_lbls.items():
            lbl.configure(text=str(counts[name]))

    def _bump(self, name: str) -> None:
        """Incrementa un contatore della dashboard e rinfresca le label. DEVE girare
        sul thread Tk: dal thread del bot va chiamato via `self.after(0, ...)`."""
        self._stats.bump(name)
        self._refresh_dashboard()

    # ── DIAGNOSTICA (PR-14c) ──────────────────
    def _set_last(self, kind: str, value: str, color: str = "gray") -> None:
        """Aggiorna un campo "ultimo …" della diagnostica (signal/message/csv/error):
        memorizza il valore (redatto, mai token) e la label, col prefisso UNICO di
        `_LAST_PREFIX`. Thread Tk (dal bot via `self.after`)."""
        safe = event_log.redact_secrets(str(value or ""))
        self._last_vals[kind] = safe
        self._last_lbls[kind].configure(
            text=f"{_LAST_PREFIX[kind]}: {safe or '—'}", text_color=color)

    def _note_csv(self, path: str, n: int) -> None:
        """Aggiorna il campo "Ultimo CSV" con path, righe attive e ora. Va chiamato su
        OGNI riscrittura/svuotamento riuscito (scrittura, conferma, scadenza, clear
        manuale) così il pannello/diagnostica riflette lo stato reale del CSV (Codex)."""
        state = "svuotato" if n == 0 else f"{n} attiv{'o' if n == 1 else 'i'}"
        self._set_last("csv", f"{path} ({state}) @ {datetime.now():%H:%M:%S}")

    def _open_log_folder(self):
        """Apre nel file manager la cartella dei log persistenti (PR-14c)."""
        import os
        import subprocess
        import sys
        folder = event_log.log_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(folder)            # noqa: S606 — apertura cartella utente
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
            self._log(f"📂 Cartella log: {folder}")
        except Exception as ex:                 # noqa: BLE001 — esito a log, no crash
            self._log(f"❌ Impossibile aprire la cartella log: {ex}")

    def _confirm_real_mode(self) -> bool:
        """Doppia conferma per attivare la modalità REALE (#136 punto 4): oltre alla spunta,
        l'utente deve DIGITARE la frase di conferma. Ritorna True se confermato.

        GUI (verifica manuale): un input dialog mostra l'avviso e attende la frase; la
        DECISIONE (`real_mode.confirmation_ok`) è logica pura testata."""
        try:
            dlg = ctk.CTkInputDialog(
                title="Conferma MODALITÀ REALE",
                text=("ATTENZIONE: stai per attivare la MODALITÀ REALE.\n"
                      "XTrader potrà piazzare scommesse REALI.\n\n"
                      f"Per confermare digita:  {real_mode.CONFIRM_PHRASE}"))
            typed = dlg.get_input()    # None se l'utente annulla/chiude
        except Exception:              # noqa: BLE001 — su qualsiasi errore dialog → non confermare
            return False
        return real_mode.confirmation_ok(typed)

    def _confirm_multi_signal(self, max_active) -> bool:
        """Conferma per attivare una modalità coda MULTI-segnale (#136 p5): True se confermato.
        GUI (verifica manuale); il TESTO/decisione (`multi_signal`) è logica pura testata."""
        from tkinter import messagebox
        try:
            return bool(messagebox.askyesno(
                "Conferma modalità MULTI-segnale", multi_signal.warning_text(max_active)))
        except Exception:   # noqa: BLE001 — su errore dialog → non confermare
            return False

    def _update_active_indicator(self, n=None) -> None:
        """Aggiorna l'indicatore 'righe attive' (#136 p5). `n` esplicito (post-write) o
        calcolato dalla coda; il tetto dalla coda se attiva, altrimenti dalla config.
        Da chiamare sul MAIN thread (via `self.after` se invocato dal listener)."""
        lbl = getattr(self, "_active_lbl", None)
        if lbl is None:
            return
        q = self._queue
        if n is None:
            n = len(q.active_rows()) if q is not None else 0
        if q is not None:
            max_active = q.max_active
        elif isinstance(self._config, dict):
            max_active = self._config.get("max_active_signals", DEFAULTS["max_active_signals"])
        else:
            max_active = 0
        lbl.configure(text=multi_signal.active_count_text(n, max_active))

    def _update_real_mode_banner(self, cfg=None) -> None:
        """Mostra/nasconde il banner rosso persistente in base alla modalità (#136 p4).

        La DECISIONE è `real_mode.banner_active` (logica pura testata): il banner resta
        visibile non solo se la config viva è in reale, ma anche se una SESSIONE in corso è
        partita in reale (il betting reale è ancora attivo fino a STOP/START, Codex P1). Il
        banner è impaccato `before=self._tabs` così resta vicino all'header (Codex P2)."""
        banner = getattr(self, "_real_banner", None)
        if banner is None:
            return
        live = cfg if isinstance(cfg, dict) else (self._config if isinstance(self._config, dict) else {})
        active = real_mode.banner_active(
            live, session_active=self._running, session_real=getattr(self, "_session_real", False))
        if active:
            banner.configure(text=real_mode.BANNER_TEXT)
            tabs = getattr(self, "_tabs", None)
            if tabs is not None:
                banner.pack(fill="x", padx=15, pady=(0, 5), before=tabs)
            else:
                banner.pack(fill="x", padx=15, pady=(0, 5))
        else:
            banner.pack_forget()

    def _export_real_audit(self) -> None:
        """Esporta in un file scelto dall'utente le righe di AUDIT della modalità reale
        (`REAL_MODE_ENABLED`) estratte dai log giornalieri (#136 p4). L'estrazione
        (`real_mode.extract_audit_lines`) è logica pura testata; lettura file + dialog =
        verifica manuale."""
        import os
        from tkinter import filedialog, messagebox
        try:
            folder = event_log.log_dir()
            lines = []
            for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
                # Solo i log GIORNALIERI canonici `bridge-AAAA-MM-GG.log` (stesso regex di
                # `event_log`): evita artefatti tipo `bridge-backup.log` (CodeRabbit).
                if event_log._LOG_FILE_RE.match(name):
                    with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                        # Antepone la data dal nome file: un export multi-giorno resta
                        # non ambiguo (le righe di log portano solo [HH:MM:SS], Codex P2).
                        lines.extend(real_mode.audit_lines_with_date(name, f.read()))
            if not lines:
                messagebox.showinfo("Audit modalità reale",
                                    "Nessun evento di attivazione modalità reale nei log.")
                return
            dest = filedialog.asksaveasfilename(
                title="Esporta audit modalità reale", defaultextension=".txt",
                initialfile="audit_modalita_reale.txt",
                filetypes=[("Testo", "*.txt"), ("Tutti i file", "*.*")])
            if not dest:
                return
            with open(dest, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self._log(f"🧾 Audit modalità reale esportato ({len(lines)} eventi): {dest}")
        except Exception as ex:        # noqa: BLE001 — esito a log, no crash
            self._log(f"❌ Esportazione audit reale fallita: {ex}")

    def _copy_diagnostics(self):
        """Copia negli appunti un report diagnostico (stato, contatori, ultimi eventi,
        percorsi), già redatto dei segreti — utile per il supporto (PR-14c)."""
        cfg = self._config if isinstance(self._config, dict) else {}
        info = [
            ("Stato listener", "ATTIVO" if self._running else "OFFLINE"),
            ("Modalità", "DRY_RUN (simulazione)"
                if safety_guard.is_dry_run(cfg) else "REALE"),
            ("CSV path", cfg.get("csv_path", "")),
            ("Modalità coda", signal_queue.normalize_mode(cfg.get("queue_mode"))),
        ]
        info += [(label, self._stats.get(name)) for name, label in dashboard_stats.COUNTERS]
        # Ultimi eventi: il valore grezzo memorizzato (la label aggiunge il prefisso,
        # qui lo aggiunge il report → niente prefisso duplicato).
        info += [(prefix, self._last_vals.get(kind, "")) for kind, prefix in _LAST_FIELDS]
        info.append(("Cartella log", event_log.log_dir()))
        report = diagnostics.build_report(info)
        try:
            self.clipboard_clear()
            self.clipboard_append(report)
            self._log("📋 Diagnostica copiata negli appunti.")
        except Exception as ex:                 # noqa: BLE001
            self._log(f"❌ Copia diagnostica fallita: {ex}")

    def _on_retention_change(self, label: str):
        """Imposta i giorni di conservazione log, persiste e pulisce subito (PR-3)."""
        days = _RETENTION_LABELS.get(label, 0)
        self._config["log_retention_days"] = days
        had = self._had_incomplete_token_load()   # PR-08c: il save consuma il marker
        saved, ok = result = save_config(self._config, CONFIG_FILE)
        self._config = saved
        # Reidratazione del campo token (PR-08c): un save non-GUI può aver reidratato il token
        # dal keyring e consumato il marker lasciando il campo password vuoto → il save normale
        # successivo lo scambierebbe per un clear. Risincronizza il campo col token reidratato.
        self._resync_token_field(had)
        if not ok:
            # Causa SPECIFICA (#255 line-647): disco vs keyring vs config corrotto.
            self._log("❌ Retention log NON salvata. " + config_store.save_status_message(result.status))
            return
        if days:
            removed = event_log.purge_old_logs(days)
            self._log(f"🧹 Retention log: {days} giorni · {len(removed)} file vecchi rimossi.")
        else:
            self._log("🧹 Retention log: conservo tutto (nessuna pulizia automatica).")

    def _clear_logs_now(self):
        """«Svuota log adesso»: rimuove i file di log su disco E svuota la vista in
        memoria/textbox (PR-3), così cambiando il filtro non riappaiono entry "pulite"
        (Codex). La riga di conferma è il primo nuovo evento dopo la pulizia."""
        removed = event_log.clear_all_logs()
        self._log_entries.clear()
        self._log_box.delete("1.0", "end")
        self._log(f"🧹 Log svuotati: {len(removed)} file su disco rimossi; vista azzerata.")

    def _on_debug_toggle(self):
        """Attiva/disattiva la modalità Debug (log dettagliato del percorso) e persiste."""
        on = bool(self._debug_var.get())
        self._config["debug_log"] = on
        had = self._had_incomplete_token_load()   # PR-08c: il save consuma il marker
        saved, ok = result = save_config(self._config, CONFIG_FILE)
        self._config = saved
        # Reidratazione del campo token dopo un save non-GUI (PR-08c): vedi _on_retention_change.
        self._resync_token_field(had)
        self._log(f"🐞 Modalità Debug log: {'ON' if on else 'OFF'}.")
        if not ok:
            # Causa SPECIFICA (#255 line-647): disco vs keyring vs config corrotto.
            self._log("⚠️ Impostazione Debug NON salvata. " + config_store.save_status_message(result.status))

    def _dbg(self, msg: str):
        """Log di percorso dettagliato, scritto SOLO se la modalità Debug è attiva
        (PR-3): avvii/stop, salvataggi, selezioni, stadi del segnale + warning.
        `as_bool` evita che `"false"`/`"0"` da config a mano accendano il debug (Codex)."""
        if as_bool((self._config or {}).get("debug_log", False)):
            self._log(f"🐞 {msg}")

    # ── LOG ───────────────────────────────────
    def _log(self, msg: str, level: str = None):
        # Redazione unica nel sink condiviso: un token incorporato per sbaglio
        # (es. nel testo di un'eccezione del bot) non finisce mai nel log, né a
        # schermo né su file (invariante: mai token nei log).
        safe = event_log.redact_secrets(msg)
        # Livello: se non passato, derivato dal marker del messaggio (❌/⚠️/📱).
        lvl = event_log.normalize_level(level or event_log.classify(safe))
        # Riga formattata `[HH:MM:SS] [LEVEL] msg`: stessa forma dello storico, così
        # il filtro per livello (PR-14b) legge il campo header.
        entry = event_log.format_entry(safe, lvl)
        self._log_entries.append(entry)
        # Storico persistente in AppData (#11): sopravvive al riavvio. Best-effort:
        # un errore di filesystem non deve interrompere la GUI.
        event_log.append_entry(safe, lvl)
        # Cap con isteresi: oltre la soglia si trima ai più recenti e si rifà il
        # render una volta (non a ogni riga).
        if len(self._log_entries) > _LOG_TRIM_AT:
            del self._log_entries[:-_LOG_MAX]
            self._render_log()
            return
        # Inserimento incrementale: aggiungo a schermo solo se la riga passa il
        # filtro corrente (altrimenti resta in memoria, visibile cambiando filtro).
        if self._entry_visible(entry):
            self._log_box.insert("end", entry + "\n")
            self._log_box.see("end")

    def _entry_visible(self, entry: str) -> bool:
        """True se `entry` passa il filtro di livello selezionato (PR-14b).
        Check riga-per-riga economico (nessuna allocazione): `log_view.matches`."""
        return log_view.matches(entry, self._log_filter.get())

    def _render_log(self) -> None:
        """Ri-disegna il riquadro log applicando il filtro di livello corrente."""
        visible = log_view.filter_lines(self._log_entries, self._log_filter.get())
        self._log_box.delete("1.0", "end")
        if visible:
            self._log_box.insert("end", "\n".join(visible) + "\n")
        self._log_box.see("end")

    # ── GUARDRAIL (PR-21) ─────────────────────
    def _dedupe_state_path(self) -> str:
        # History anti-duplicato accanto al config (AppData): i duplicati recenti
        # restano riconosciuti dopo un riavvio. Path puro in `runtime_state`.
        return runtime_state.dedupe_state_path(config_dir())

    def _daily_state_path(self) -> str:
        # Conteggio giornaliero persistito: stop/start nello stesso giorno (UTC)
        # NON deve azzerare il tetto (altrimenti il limite/giorno è aggirabile).
        return runtime_state.daily_state_path(config_dir())

    # ── Betfair (issue #86): sessione/auth/engine condivisi (lazy) ────────────
    def _betfair_session_obj(self):
        """Sessione Betfair condivisa (sessionToken solo in RAM): UNA per processo.
        Creazione lazy sotto `_betfair_lock` (doppio controllo): il flusso live e il main
        thread possono richiederla in concorrenza (Codex)."""
        from .betfair.session import BetfairSession
        if getattr(self, "_betfair_session", None) is None:
            with self._betfair_lock:
                if getattr(self, "_betfair_session", None) is None:
                    self._betfair_session = BetfairSession()
        return self._betfair_session

    def _betfair_auth_client(self):
        """Client di login Betfair (read-only) condiviso, sulla sessione del bridge.
        Creazione lazy sotto `_betfair_lock` (doppio controllo)."""
        from .betfair.auth_client import BetfairAuthClient
        if getattr(self, "_betfair_auth_obj", None) is None:
            with self._betfair_lock:
                if getattr(self, "_betfair_auth_obj", None) is None:
                    self._betfair_auth_obj = BetfairAuthClient(session=self._betfair_session_obj())
        return self._betfair_auth_obj

    def _betfair_sync_engine(self):
        """Motore di sync Betfair condiviso (apre il DB locale in AppData). UNA
        istanza: il lock anti-doppia-sync e il marker devono persistere. Creazione lazy
        **sincronizzata** (`_betfair_lock`, doppio controllo): senza, una chiamata dal
        thread listener (flusso live PR-P12) e una dal main thread (tab/auto-sync)
        creerebbero DUE engine, aggirando la guardia 'una sync per volta' (Codex)."""
        from .betfair.local_db import BetfairLocalDB
        from .betfair.sync_engine import SyncEngine
        if getattr(self, "_betfair_engine_obj", None) is None:
            with self._betfair_lock:
                if getattr(self, "_betfair_engine_obj", None) is None:
                    db = BetfairLocalDB(runtime_state.betfair_db_path(config_dir()))
                    self._betfair_engine_obj = SyncEngine(db, self._betfair_session_obj())
        return self._betfair_engine_obj

    def _betfair_id_resolver(self):
        """Risolutore ID del dizionario Betfair locale per il flusso live (PR-P12),
        **best-effort**: ritorna un `DictionaryResolver` sul DB locale, o `None` se il
        dizionario non è disponibile (in tal caso il flusso resta a nomi: fallback nomi,
        nessun blocco). Sola lettura: non scrive nulla e non fa rete."""
        try:
            from .betfair.dictionary_resolver import DictionaryResolver
            return DictionaryResolver(self._betfair_sync_engine().db)
        except Exception:   # noqa: BLE001 — best-effort: il flusso live non deve crashare
            return None

    def _preview_id_resolver_factory(self):
        """Factory del resolver ID per l'ANTEPRIMA GUI «Prova messaggio» (#192, Codex P2).

        Come `_betfair_id_resolver`, MA **salta** (ritorna `None`) se una sync Betfair è in
        corso. Il resolver legge il DB sotto lo stesso `RLock` che la sync tiene per l'INTERA
        durata (incluse le chiamate di rete di navigazione/catalogo): invocarlo in modo sincrono
        dal thread Tk dell'anteprima bloccherebbe la finestra fino a fine sync/timeout HTTP.
        `is_syncing` è un probe **non bloccante** (acquire/release immediato). Durante una sync
        l'anteprima resta quindi conservativa (nessun arricchimento ID), mai un freeze — fail-open.

        Il flusso LIVE **non** è toccato: usa `_betfair_id_resolver` direttamente su un worker
        thread (non sul thread GUI), dove un'attesa sul lock è accettabile."""
        try:
            if self._betfair_sync_engine().is_syncing:
                return None
        except Exception:   # noqa: BLE001 — probe best-effort: mai bloccare/crashare l'anteprima
            return None
        return self._betfair_id_resolver()

    def _betfair_autosync_seed(self) -> dict:
        """Valori auto-sync (enabled/hour/sports) per **seminare** il pannello Betfair.

        Letti dalla config **LIVE in memoria** (`self._config`), non da una rilettura del
        disco: se un save precedente è fallito, il disco è stantio e seminare da lì
        mostrerebbe valori vecchi che un successivo edit (ora/sport) riscriverebbe sopra
        la config viva, ri-disabilitando o ri-schedulando l'auto-sync (Codex). Stessa
        semantica di `_betfair_autosync_change` e del tick, che già usano `self._config`."""
        cfg = self._config if isinstance(self._config, dict) else self._load_config()
        return {"enabled": config_store.as_bool_optin(cfg.get("betfair_auto_sync", False)),
                "hour": cfg.get("betfair_auto_sync_hour", 23),
                "sports": cfg.get("betfair_sync_sports")}

    def _betfair_login_work(self, creds):
        """Esegue il login Betfair (POST HTTPS **bloccante**, fino a ~20s) e ritorna il
        messaggio di log (già redatto, mai segreti). Pensato per girare su un WORKER
        THREAD (H1): NON tocca Tk. Su successo porta la App Key del login nell'engine
        (così la sync funziona anche con credenziali non ancora salvate nel keyring);
        su `LoginError` ritorna il messaggio safe del client (nessuna response grezza)."""
        from .betfair.auth_client import LoginError
        # Serializza il login manuale con l'auto-sync sulla SESSIONE CONDIVISA: prenota il
        # lock del motore PRIMA del login (come fa `auto_sync._cycle`). Senza, un click
        # «Accedi» durante il ciclo auto-sync (tra il suo check `pre_logged` e il `logout`
        # finale) verrebbe sloggato da quel `logout()`, lasciando la tab disconnessa pur
        # avendo riportato successo (Codex). Se il lock è già preso (sync manuale o
        # auto-sync in corso) il login è rimandato senza toccare la sessione condivisa.
        reserved = False
        engine = None
        try:
            engine = self._betfair_sync_engine()
            reserve = getattr(engine, "reserve", None)
            release = getattr(engine, "release", None)
            if callable(reserve) and callable(release):
                if not reserve():
                    return ("⏳ Login Betfair rimandato: una sincronizzazione è in corso. "
                            "Riprova tra qualche secondo.")
                reserved = True
        except Exception:               # noqa: BLE001 — engine/DB non disponibile: login senza riserva
            pass
        try:
            self._betfair_auth_client().login(creds)
            if engine is not None:
                try:
                    engine.set_app_key(creds.app_key)
                except Exception:       # noqa: BLE001 — l'engine può mancare se il DB fallisce
                    pass
            return "🔵 Login Betfair riuscito (sessione in memoria)."
        except LoginError as ex:        # messaggio già safe (nessun segreto)
            return f"❌ Login Betfair fallito: {ex}"
        finally:
            # Lock sicuramente preso (reserved=True): release() di un threading.Lock detenuto
            # non solleva, quindi niente try/except qui (a differenza del finally di
            # `_cycle`, dove il release può correre con altri path).
            if reserved:
                engine.release()

    def _betfair_login_async(self, creds):
        """Callback «Accedi» della tab Betfair (H1): il login (rete, fino a ~20s) gira su
        un WORKER THREAD per non bloccare la GUI Tk — come `_betfair_sync` — e l'esito è
        marshalato sul main thread con `after(0, ...)`. Un flag anti-rientro
        (`_betfair_login_busy`) evita login concorrenti finché uno è in corso (equivale a
        disabilitare il bottone). Prima del fix il login girava sincrono nella callback Tk
        e congelava la finestra (no repaint/STOP/chiusura) per tutta la durata della POST.

        Robustezza (Codex su #184 H1):
        - **teardown**: se l'app si sta chiudendo il worker NON rientra in Tk (flag
          `_closing`), così non chiama `after` su una root distrutta;
        - **completamento stantio**: ogni login prende un `gen` (epoch); se nel frattempo
          l'utente fa logout o «Cancella credenziali» (`_betfair_invalidate_login` bumpa
          l'epoch), il login in volo è stantio → si scarta il token appena settato
          (`_betfair_discard_stale_login`) e non si riporta la UI a «connesso». Il flag
          anti-rientro serializza i login, quindi un mismatch di epoch = logout/delete."""
        if self._betfair_login_busy:
            return
        self._betfair_login_busy = True
        self._betfair_login_epoch += 1
        gen = self._betfair_login_epoch

        def _worker():
            msg = self._betfair_login_work(creds)
            if gen != self._betfair_login_epoch:
                # logout/delete arrivato durante il login: disfa il token stantio.
                self._betfair_login_busy = False
                self._betfair_discard_stale_login()
                return
            if self._closing:           # app in chiusura: niente chiamate Tk dal worker
                self._betfair_login_busy = False
                return
            try:
                self.after(0, lambda: self._betfair_login_done(msg, gen))
            except Exception:           # noqa: BLE001 — race: root distrutta TRA il check
                # `_closing` e lo schedule (`destroy()` invalida l'interprete Tcl). Niente
                # eccezione non gestita sul daemon thread a teardown (Codex).
                self._betfair_login_busy = False

        t = threading.Thread(target=_worker, daemon=True, name="betfair-login")
        self._betfair_login_thread = t      # esposto per join nei test (deterministico)
        t.start()

    def _betfair_login_done(self, msg, gen):
        """Rientro nel main thread dopo il login (via `after`): libera il flag, e — solo se
        il login NON è stantio (epoch) e la root è viva (`_closing`/`winfo_exists`) — logga
        l'esito redatto e aggiorna gli stati dei bottoni della tab."""
        self._betfair_login_busy = False
        if gen != self._betfair_login_epoch:        # superato da logout/delete: ignora
            return
        if self._closing or not self.winfo_exists():
            return
        self._log(msg)
        panel = self._betfair_panel
        if panel is not None:
            try:
                panel._refresh_buttons()
            except Exception:           # noqa: BLE001 — refresh best-effort, mai crash GUI
                pass

    def _betfair_invalidate_login(self):
        """Invalida un eventuale login in volo: chiamato dal pannello su «Logout» e
        «Cancella credenziali» così il completamento di un login partito PRIMA dell'azione
        non riporti la sessione a «connesso» DOPO che l'utente ha sloggato/cancellato
        (Codex). Bumpa solo l'epoch (lettura/scrittura int semplice, thread-safe in CPython)."""
        self._betfair_login_epoch += 1

    def _betfair_discard_stale_login(self):
        """Un login STANTIO (superato da logout/delete) ha già settato il sessionToken
        dentro `auth_client.login`: lo si scarta pulendo la sessione (solo RAM), così
        l'utente resta sloggato come voleva. Best-effort, fuori dal main thread (niente Tk)."""
        try:
            self._betfair_session_obj().clear()
        except Exception:               # noqa: BLE001 — best-effort
            pass

    def _betfair_autosync_tick(self):
        """Tick periodico (mentre il bridge è APERTO) dell'auto-sync Betfair. La
        decisione e il ciclo (auto login→sync→auto logout) sono in `auto_sync`; qui
        si legge la config, si costruisce lo scheduler una volta e si esegue il
        `maybe_run` su un worker thread (la rete non deve bloccare la GUI). Best-effort:
        un errore non interrompe il loop dei tick. Si ri-arma ogni 60s."""
        try:
            # winfo_exists() qui gira sul MAIN thread (il tick è schedulato con after);
            # il worker NON deve toccare Tk (Codex). Lo scheduler usa is_bridge_open legato
            # a `_closing`, così un worker lanciato a ridosso della chiusura fallisce chiuso.
            if self.winfo_exists():
                # Config LIVE in memoria (non rilettura da disco): dopo un save fallito
                # `self._config` riflette ciò che l'utente ha impostato, mentre il disco
                # avrebbe valori stantii (CodeRabbit). Stessa semantica del resto di App.
                cfg = dict(self._config) if isinstance(self._config, dict) else self._load_config()
                if config_store.as_bool_optin(cfg.get("betfair_auto_sync", False)):
                    try:
                        sched = self._betfair_autosync_scheduler()
                    except Exception as ex:   # noqa: BLE001 — costruzione scheduler (es. DB non apribile)
                        # Non restare silenziosi: l'utente crede l'auto-sync attiva ma
                        # non partirà mai in questo ambiente. Avvisa UNA volta (Codex).
                        if not getattr(self, "_autosync_build_warned", False):
                            self._autosync_build_warned = True
                            self._log(f"⚠️ Auto-sync Betfair non avviabile ({type(ex).__name__}): "
                                      "controlla la cartella dati / il dizionario locale.")
                        sched = None
                    if sched is not None:
                        import datetime
                        now = datetime.datetime.now()
                        threading.Thread(target=lambda: sched.maybe_run(now),
                                         daemon=True, name="betfair-autosync").start()
        except Exception:               # noqa: BLE001 — il tick non deve mai crashare
            pass
        finally:
            # Ri-arma solo se il bridge non si sta chiudendo: dopo `_on_close`
            # `self.after` su una root distrutta solleverebbe (CodeRabbit).
            if not self._closing:
                self._autosync_after_id = self.after(60_000, self._betfair_autosync_tick)

    def _betfair_autosync_scheduler(self):
        """Scheduler auto-sync condiviso (lazy). `get_config` legge enabled/hour/sports
        dalla config e le credenziali locali per l'auto login; `on_summary` logga
        l'esito safe sul main thread e aggiorna le etichette della tab se aperta."""
        from . import atomic_io
        from .betfair import auto_sync, credential_store
        if getattr(self, "_betfair_autosync_obj", None) is not None:
            return self._betfair_autosync_obj

        def _get_config():
            # Config LEGGERA (no keyring): lo scheduler la legge a ogni tick (anche fuori
            # orario o a run già fatta), quindi NON deve leggere le credenziali qui — il
            # keyring si tocca solo quando la run è dovuta, in `_get_credentials` (CodeRabbit).
            # Config LIVE in memoria, non rilettura da disco: dopo un save fallito riflette
            # ciò che l'utente ha impostato, non valori stantii su disco (CodeRabbit).
            cfg = dict(self._config) if isinstance(self._config, dict) else self._load_config()
            enabled = config_store.as_bool_optin(cfg.get("betfair_auto_sync", False))
            hour = auto_sync.normalize_hour(cfg.get("betfair_auto_sync_hour", 23))
            sports = cfg.get("betfair_sync_sports") or []
            return enabled, hour, sports

        def _get_credentials():
            # Letto SOLO quando l'auto-sync è davvero dovuta (dentro `_cycle`), non a ogni tick.
            return credential_store.load_credentials()

        _state_path = runtime_state.betfair_autosync_state_path(config_dir())

        def _load_state():
            try:
                import json
                with open(_state_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:   # noqa: BLE001 — assente/corrotto → nessuna run nota
                return None

        def _save_state(key):
            atomic_io.atomic_write_json(_state_path, key)   # scrittura atomica

        def _on_state_error(_ex):
            # Invocato dal worker auto-sync: qui NIENTE chiamate Tk (winfo_exists) — solo
            # il flag `_closing` (lettura semplice, thread-safe). La winfo_exists vera la
            # fa il callback schedulato, che gira sul main thread (CodeRabbit).
            if self._closing:
                return

            def _report():
                if self._closing or not self.winfo_exists():
                    return
                self._log(
                    "⚠️ Auto-sync Betfair: impossibile salvare lo stato (la guardia "
                    "'una volta al giorno' potrebbe non valere dopo un riavvio).")
            self.after(0, _report)

        def _on_summary(res):
            # Invocato dal worker auto-sync (può finire DOPO `_on_close`): qui solo il flag
            # `_closing`, nessuna chiamata Tk dal worker; la winfo_exists la fa `_report`
            # sul main thread (CodeRabbit).
            if self._closing:
                return

            def _report():
                if self._closing or not self.winfo_exists():
                    return
                ok = getattr(res, "ok", False)
                self._log("🔄 Auto-sync Betfair OK." if ok
                          else "⚠️ Auto-sync Betfair non riuscita: "
                          + ("; ".join(res.errors) if res and res.errors else "—"))
                panel = getattr(self, "_betfair_panel", None)
                if panel is not None:
                    try:
                        panel.set_autosync_status(state=("OK" if ok else "errore"))
                    except Exception:   # noqa: BLE001
                        pass
            self.after(0, _report)

        self._betfair_autosync_obj = auto_sync.AutoSyncScheduler(
            auth=self._betfair_auth_client(), engine=self._betfair_sync_engine(),
            get_config=_get_config, get_credentials=_get_credentials,
            # Fail-closed in chiusura: se `_on_close` setta `_closing` dopo lo spawn del
            # worker ma prima che entri in maybe_run, il ciclo non parte (CodeRabbit).
            is_bridge_open=lambda: not self._closing,
            on_summary=_on_summary, load_state=_load_state, save_state=_save_state,
            on_state_error=_on_state_error)
        return self._betfair_autosync_obj

    def _init_guards(self, cfg: dict) -> None:
        """Crea i guardrail del percorso di scrittura dalla config (chiamato allo
        START). La costruzione pura (tracker/daily/coda + fallback fail-safe) è in
        `runtime_state.build_guards`; qui restano il load da disco e il logging.
        `max_per_day`/`clear_delay` invalidi → default sicuro con avviso."""
        import os
        self._dedupe_save_warned = False
        self._daily_save_warned = False
        guards = runtime_state.build_guards(cfg)
        self._tracker = guards.tracker
        # Avvisa solo se lo stato ESISTE ma non è caricabile (corrotto/illeggibile):
        # l'assenza al primo avvio è normale, non un degrado.
        dpath = self._dedupe_state_path()
        if os.path.exists(dpath) and not signal_dedupe.load_state(self._tracker, dpath):
            self._log("⚠️ Stato anti-duplicato presente ma illeggibile: "
                      "protezione dopo riavvio non garantita.")
        self._daily = guards.daily
        self._load_daily_state()
        self._queue = guards.queue
        # Fonte UNICA del timeout (validata dalla coda): usata anche dai timer di
        # scadenza, così coda e timer condividono lo stesso valore valido.
        self._queue_timeout = guards.queue_timeout
        # Avvisi di fallback fail-safe (max_per_day/clear_delay invalidi): loggati
        # qui perché `build_guards` resti puro e testabile senza GUI.
        for warning in guards.warnings:
            self._log(warning)
        self._log(f"🧮 Modalità coda: {guards.mode}")

    def _load_daily_state(self) -> None:
        """Ripristina il conteggio giornaliero (persistenza same-day tra START/STOP).
        Best-effort: file assente/illeggibile → si riparte da 0 per oggi."""
        if self._daily is None:
            return
        safety_guard.load_state(self._daily, self._daily_state_path())

    def _save_guard_state(self) -> None:
        """Persiste lo stato dei guardrail su disco DOPO una decisione/scrittura.
        Dedupe E daily: salvataggio ATOMICO+fsync (`signal_dedupe.save_state` /
        `safety_guard.save_state`), con avviso una-tantum se fallisce (non più silenzioso)."""
        if (not signal_dedupe.save_state(self._tracker, self._dedupe_state_path())
                and not self._dedupe_save_warned):
            self._dedupe_save_warned = True
            self.after(0, lambda: self._log(
                "⚠️ Impossibile salvare lo stato anti-duplicato su disco: "
                "protezione dopo riavvio degradata."))
        # Daily: salvataggio ATOMICO+fsync (audit #105 P2), allineato a signal_dedupe; un
        # fallimento è segnalato una sola volta (non più silenzioso come `except OSError: pass`).
        if (self._daily is not None
                and not safety_guard.save_state(self._daily, self._daily_state_path())
                and not self._daily_save_warned):
            self._daily_save_warned = True
            self.after(0, lambda: self._log(
                "⚠️ Impossibile salvare lo stato del limite giornaliero su disco: "
                "protezione anti-overtrading dopo riavvio degradata."))

    # ── START / STOP ──────────────────────────
    def _start(self, auto: bool = False):
        # Un AVVIA (manuale o automatico) consuma l'auto-start pendente: dopo questo
        # nessun callback ritardato deve (ri)avviare il listener (Codex P2).
        self._cancel_pending_autostart()
        if not TELEGRAM_OK:
            # Libreria python-telegram-bot assente: errore chiaro, niente crash
            # silenzioso nel thread del bot (PR-11, #11).
            self._log("❌ python-telegram-bot non disponibile: impossibile avviare il listener.")
            return
        # Reidratazione del campo token PRIMA della validazione grezza (PR-08c): se il keyring
        # era illeggibile al load (marker `_token_load_incomplete`) il campo è vuoto pur
        # esistendo una credenziale, e la validazione qui sotto bloccherebbe START con "inserisci
        # il Bot Token" anche a keyring rientrato. Il refill legge il token dal keyring e ripopola
        # il campo, così START non chiede più il token a outage risolto. No-op senza marker.
        self._resync_token_field()
        # Validazione sui valori GREZZI dei campi PRIMA del salvataggio
        # (PR-13/#10): _save_config normalizza il timeout invalido al default,
        # quindi validare la cfg dopo il save non vedrebbe più l'errore e il
        # bridge partirebbe a 90s ignorando l'input dell'utente.
        raw = {
            "bot_token":   self._e_token.get().strip(),
            "csv_path":    self._e_csv.get().strip(),
            "clear_delay": self._e_delay.get().strip(),
        }
        if not raw["bot_token"]:
            self._log("❌ Inserisci il Bot Token prima di avviare!")
            return
        errors = settings_validation.validate_settings(raw)
        if errors:
            for err in errors:
                self._log(f"❌ {err}")
            return

        cfg = self._save_config()   # aggiorna anche il pannello "Chat ascoltate"
        # Fail-fast (PR-13, finding Codex P1): se le impostazioni avanzate non sono
        # valide, apply_advanced le ha RIFIUTATE in blocco e cfg ha ancora i vecchi
        # valori. Avviare ignorerebbe una modifica safety-critical (es. riattivare
        # DRY_RUN o passare a OVERWRITE_LAST): meglio bloccare e far correggere.
        if self._adv_errors:
            self._log("❌ Impostazioni avanzate non valide (vedi avvisi sopra): "
                      "correggile prima di avviare. Avvio annullato.")
            return
        # Fail-fast (PR-25): senza NESSUNA chat configurata (chat_id, parser_by_chat
        # o sorgente source_chats anche disattivata) is_chat_allowed ammetterebbe
        # TUTTE le chat: il bridge accetterebbe segnali da chat arbitrarie. Blocco
        # l'avvio finché l'utente non configura almeno una chat/sorgente.
        if not signal_router.has_chat_filter(cfg):
            self._log("❌ Nessuna chat configurata (Chat ID, parser per-chat o sorgente): "
                      "il bridge accetterebbe segnali da QUALSIASI chat. Configura almeno "
                      "una chat/sorgente. Avvio annullato.")
            return
        # CP-09b: il parser automatico P.Bet è disattivato. Se NON è configurato alcun
        # Parser Personalizzato (globale o per-chat), il listener partirebbe ma ignorerebbe
        # ogni segnale in silenzio. Avviso NON bloccante: l'utente potrebbe attivare un
        # parser subito dopo, ma deve sapere che ora non verrà processato nulla (Codex).
        if not signal_router.has_active_parser_config(cfg):
            self._log("⚠️ Nessun Parser Personalizzato configurato (globale o per-chat): "
                      "il parser automatico è disattivato, quindi NESSUN segnale verrà "
                      "processato finché non attivi un parser.")
        # Fail-fast (PR-24): sorgenti multi-chat malformate (chat_id mancante,
        # DUPLICATO con provider ambiguo, modalità non valida) bloccano l'avvio,
        # altrimenti provider_for_chat sceglierebbe a caso la prima sorgente.
        src_errors = source_manager.validate_sources(cfg.get("source_chats"))
        if src_errors:
            for err in src_errors:
                self._log(f"❌ Sorgenti multi-chat: {err}")
            self._log("Avvio annullato: correggi le sorgenti.")
            return
        # Fail-fast (PR-23/PR-24): la chat notifiche XTrader NON deve coincidere con una
        # chat sorgente (chat_id, override parser_by_chat o sorgente multi-chat ATTIVA);
        # altrimenti i segnali di quella chat finirebbero nel percorso di conferma e
        # verrebbero ignorati silenziosamente.
        notif = str(cfg.get("xtrader_notification_chat_id", "") or "").strip()
        if notif:
            sources = {str(cfg.get("chat_id", "") or "").strip()}
            sources.update(str(k).strip() for k in (cfg.get("parser_by_chat") or {}))
            sources.update(str(s).strip() for s in source_manager.enabled_chat_ids(cfg))
            sources.discard("")
            if notif in sources:
                self._log("❌ La Chat notifiche XTrader coincide con una chat sorgente: "
                          "cambiala (i segnali verrebbero scambiati per conferme). Avvio annullato.")
                return

        # Avvio AUTOMATICO: la decisione si basa sulla config APPENA salvata (cfg),
        # cioè i valori correnti dei widget — non su quelli caricati all'apertura
        # (Codex P2). Se l'utente ha disattivato l'auto-start nel frattempo non si
        # parte; in modalità REALE si chiede conferma esplicita prima di scommettere.
        if auto:
            if not autostart.is_enabled(cfg):
                return
            if autostart.needs_real_mode_confirmation(cfg):
                from tkinter import messagebox
                if not messagebox.askyesno(
                        "Avvio automatico — MODALITÀ REALE",
                        "L'avvio automatico è attivo in MODALITÀ REALE: il bridge "
                        "inizierà a scrivere i segnali nel CSV (scommesse reali) "
                        "appena ricevuti.\n\nAvviare ora il listener?"):
                    self._log("⏸️ Avvio automatico in modalità reale annullato.")
                    return
            self._log("▶️ Avvio automatico del listener (auto_start_listener attivo).")

        # Pre-flight del csv_path (#184 low-csvpath-validate): un problema di percorso (cartella
        # mancante, es. il default C:\XTrader\, o path vuoto/è una cartella) dà un messaggio CHIARO
        # e azionabile e annulla l'avvio, invece di un generico FileNotFoundError da init_csv. Gli
        # errori di lock/permessi restano gestiti dall'except OSError sotto.
        csv_problem = config_store.csv_path_problem(cfg["csv_path"])
        if csv_problem:
            self._log(f"❌ {csv_problem} Avvio annullato.")
            return
        # Svuota il CSV operativo PRIMA di mettere la sessione in stato ATTIVO: se il path
        # non è scrivibile (lockato da XTrader, permessi, disco pieno) l'avvio va annullato
        # SENZA lasciare la UI "attiva" col listener mai partito (A9). init_csv è l'unico
        # I/O che può fallire qui prima dell'avvio del thread.
        try:
            init_csv(cfg["csv_path"])
        except OSError as exc:
            self._log(f"❌ Impossibile inizializzare il CSV ({cfg['csv_path']}): "
                      f"{type(exc).__name__}: {exc}. Avvio annullato.")
            return
        # #234 B: se una riga stantia è sopravvissuta fino a qui (cleanup avvio/STOP non riuscito
        # perché XTrader teneva il file lockato), è QUESTO init_csv a rimuoverla → registra il clear
        # prima del START, altrimenti il diario avrebbe un CSV_WRITTEN senza il clear corrispondente.
        self._journal_csv_cleared_if_had_row("CSV_CLEARED", reason="start")

        # Nuovo epoch PRIMA di marcare la sessione attiva (#53): un vecchio supervisor in backoff
        # (sessione precedente) valuta `_is_current()` = `_running and _listener_epoch == epoch`.
        # Se incrementiamo l'epoch DOPO `_running=True`, nella finestra tra i due un vecchio
        # supervisor troverebbe `_running` True ed epoch ancora vecchio → si riconnetterebbe con
        # la cfg precedente. Bumpando qui, l'epoch differisce subito → il vecchio loop non è più
        # current e non riparte.
        self._listener_epoch += 1
        self._running = True
        # Nuova sessione: azzera il contatore CSV-lock così i fallimenti di una sessione
        # precedente non "colano" in questa e non causano una falsa escalation (Codex #156).
        self._csv_lock.reset()
        # Modalità della SESSIONE (snapshot a START): l'esecuzione resta legata a questa
        # finché non si fa STOP/START. Il banner REALE deve riflettere ciò che ESEGUE, non
        # solo la config viva (Codex P1).
        self._session_real = not safety_guard.is_dry_run(cfg)
        self._stop_event.clear()      # nuova sessione: riarma l'attesa del backoff
        self._status_lbl.configure(text="⬤  ATTIVO", text_color="#66bb6a")
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._update_real_mode_banner()   # mostra il banner se la sessione è reale

        # Path attivo della sessione: lo STOP pulirà questo (Codex P1).
        self._active_csv_path = cfg["csv_path"]
        # Event journal (#230): inizio sessione (modalità + path, niente segreti).
        self._journal("START", dry_run=bool(safety_guard.is_dry_run(cfg)),
                      csv_path=cfg["csv_path"], auto=bool(auto))
        self._init_guards(cfg)
        self._stats.reset()           # contatori di sessione azzerati a ogni START (PR-14)
        self._refresh_dashboard()
        # Nuova sessione: azzera i campi "ultimo …" (stantii dalla sessione precedente)
        # e registra che lo START ha SVUOTATO il CSV (init_csv) — Codex (PR-14c).
        for kind, _ in _LAST_FIELDS:
            self._set_last(kind, "")
        self._note_csv(cfg["csv_path"], 0)
        # Retention (PR-3): all'avvio pulisce i log più vecchi del limite impostato
        # (best-effort, mai bloccante). 0 = "Mai" → nessuna pulizia.
        _ret = event_log.retention_days(cfg)
        if _ret:
            _removed = event_log.purge_old_logs(_ret)
            if _removed:
                self._log(f"🧹 Retention log ({_ret}g): {len(_removed)} file vecchi rimossi.")
        self._log("🚀 Bridge avviato!")
        self._log(f"📄 CSV: {cfg['csv_path']}")
        self._log(f"⏱️  Auto-clear dopo: {cfg['clear_delay']}s")
        self._dbg(f"START: chat ascoltate, provider={cfg.get('provider', '')}, "
                  f"modalità={'DRY_RUN' if safety_guard.is_dry_run(cfg) else 'REALE'}, "
                  f"debug ON")
        if safety_guard.is_dry_run(cfg):
            self._log("🧪 DRY_RUN attivo (simulazione): il CSV operativo NON verrà scritto.")
        else:
            self._log("⚠️ Modalità REALE: i segnali validi verranno scritti nel CSV.")
        self._log("👂 In ascolto su Telegram...")

        # Epoch di QUESTA sessione (già incrementato sopra, PRIMA di `_running=True`, #53):
        # passato al thread del listener per il gate `_is_current()`/`_epoch_current()`.
        epoch = self._listener_epoch
        self._bot_thread = threading.Thread(
            target=self._run_bot, args=(cfg, epoch), daemon=True)
        self._bot_thread.start()

    def _stop(self):
        was_running = self._running
        self._running = False
        # Event journal (#230): registra STOP SOLO se una sessione era davvero attiva. `_on_close()`
        # chiama `_stop()` anche a bridge mai avviato o già fermato: un append incondizionato
        # produrrebbe uno STOP senza START corrispondente (sequenza impossibile nel diario forense,
        # Codex P2). Lo STOP è il pendant del START loggato in `_start` (che imposta `_running=True`).
        if was_running:
            self._journal("STOP")
        self._session_real = False         # sessione finita: il banner torna a seguire la config viva
        self._csv_lock.reset()             # #153 H2: lo stato di lock non sopravvive alla sessione (Codex #156)
        self._update_real_mode_banner()
        self._update_active_indicator(0)   # nessuna riga attiva dopo lo STOP (#136 p5)
        self._cancel_pending_autostart()   # uno STOP non deve essere annullato da un auto-start pendente (Codex P2)
        # Arresto del listener: un SOLO percorso autorevole, IN-loop. Impostare
        # `_running=False` (sopra) e svegliare il backoff con `_stop_event` fa uscire il
        # supervisor dal suo `while _is_current()` e gli fa eseguire, NELLO STESSO event
        # loop, `await updater.stop(); app.stop(); app.shutdown()` prima di `loop.close()`
        # (#184 H5). NON si sottomettono qui coroutine fire-and-forget con
        # `run_coroutine_threadsafe`: non venendo mai attese, sarebbero scartate da
        # `loop.close()` ("Event loop is closed", eccezioni silenziate, doppio stop
        # dell'updater) e darebbero la falsa impressione di un arresto gestito. `_running`
        # già False impedisce ogni scrittura CSV nella finestra di ≤1s prima dello stop
        # in-loop (_process scrive solo se `_running`); `_is_current()`/epoch invalidano
        # comunque la vecchia sessione, quindi un AVVIA successivo non trova due poller.
        self._stop_event.set()        # sveglia subito un'eventuale attesa del backoff (riconnessione)
        # Sveglia SUBITO anche l'attesa in-loop di `_async_run`: l'updater viene fermato
        # promptamente (no finestra ~1s con il vecchio poller attivo, Codex #191), restando
        # un percorso atteso in-loop (#184 H5). `call_soon_threadsafe` perché siamo sul thread
        # GUI, non su quello del loop; se il loop è già chiuso si ignora (shutdown già fatto).
        loop, evt = self._loop, self._async_stop_event
        if loop is not None and evt is not None:
            try:
                loop.call_soon_threadsafe(evt.set)
            except RuntimeError:
                pass                  # loop già chiuso/non più in esecuzione: nulla da svegliare
        self._cancel_expiry_timer()
        # Anti-segnale-stantio: una chiusura/STOP normale non deve lasciare una riga
        # attiva nel CSV (il timer di auto-clear è appena stato cancellato). Si pulisce
        # il CSV della SESSIONE (catturato a START, Codex P1) sotto il queue_lock, così
        # un'ultima scrittura del bot in volo è serializzata col clear e non lascia una
        # riga dopo lo svuotamento (Codex P2): _process scrive solo se ancora _running.
        with self._queue_lock:
            # Svuota anche la coda IN MEMORIA: così un writer tardivo che riprende il
            # lock dopo lo STOP (conferma o tick di scadenza già scattato) riscrive al
            # più solo l'header, mai una riga rimasta in coda (Codex P2).
            if self._queue is not None:
                for sid in self._queue.active_ids():
                    self._queue.remove(sid)
            self._clear_stale_csv("allo stop", path=self._active_csv_path)
        self._active_csv_path = None
        self._status_lbl.configure(text="⬤  OFFLINE", text_color="#ef5350")
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._log("🛑 Bridge fermato.")
        self._dbg("STOP: listener fermato, coda/CSV gestiti dal ciclo di stop.")

    def _on_close(self):
        self._closing = True   # blocca un auto-start ritardato ancora pendente (Codex P2)
        self._stop()
        # Teardown DETERMINISTICO (audit C1): cancella il timer di scadenza e ASPETTA che il
        # thread del bot termini (join con timeout) prima di distruggere la finestra, invece
        # di indovinare con `after(500, destroy)`. Così il thread non chiama più `self.after()`
        # su una root Tk già distrutta (niente Tcl/RuntimeError) e l'event loop viene chiuso
        # (no leak di selector/fd). Il thread è daemon: se non termina entro il timeout si
        # procede comunque, senza bloccare la chiusura del processo.
        self._cancel_expiry_timer()
        # Cancella il tick auto-sync ancora pendente: dopo destroy non deve rifirare
        # né ri-armarsi su una root distrutta (CodeRabbit).
        _autosync_after = getattr(self, "_autosync_after_id", None)
        if _autosync_after is not None:
            try:
                self.after_cancel(_autosync_after)
            except Exception:   # noqa: BLE001 — id già scaduto/invalido: best-effort
                pass
            self._autosync_after_id = None
        t = self._bot_thread
        if t is not None and t.is_alive():
            t.join(timeout=5.0)
        self.destroy()

    # ── BOT TELEGRAM ──────────────────────────
    def _run_bot(self, cfg: dict, epoch: int):
        # Riferimento LOCALE al loop di QUESTA sessione: la chiusura nel finally deve
        # toccare solo questo loop, non un eventuale loop di un nuovo START che nel
        # frattempo abbia riassegnato `self._loop` (audit C1).
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        # App Telegram di QUESTA sessione tenuta in un riferimento LOCALE, non solo in
        # `self._tg_app` (condiviso e sovrascrivibile da un nuovo START). Lo shutdown in-loop
        # e quello d'errore devono fermare l'app COSTRUITA da questa sessione, mai quella di un
        # successore: in uno STOP→START rapido il vecchio loop, leggendo `self._tg_app`,
        # fermerebbe l'app NUOVA e lascerebbe il proprio updater a fare polling (Codex #191).
        session_app = None

        def _is_current():
            # Sessione ancora valida: bridge attivo E nessun nuovo START intervenuto.
            return self._running and self._listener_epoch == epoch

        async def _async_run():
            nonlocal session_app
            # Evento di stop IN-loop (#184 H5 / Codex #191): `_stop`, dal thread GUI, lo sveglia
            # con `call_soon_threadsafe` così il supervisor esce SUBITO dall'attesa e ferma
            # l'updater promptamente (niente finestra di ~1s con il vecchio poller ancora
            # attivo), restando un percorso atteso in-loop (nessuna coroutine scartata da
            # `loop.close`). LOCALE alla coroutine (l'attesa sotto ci si aggancia direttamente),
            # con `self._async_stop_event` solo come handle per `_stop`: un nuovo START che
            # riassegna l'attributo non dirotta l'attesa di QUESTA sessione.
            stop_evt = asyncio.Event()
            self._async_stop_event = stop_evt
            app = ApplicationBuilder().token(cfg["bot_token"]).build()
            session_app = app
            self._tg_app = app          # handle per lettori esterni; un START successivo lo rimpiazza

            async def _handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
                # Gate fail-closed per epoch (Codex #191 P1): finché il vecchio updater non
                # è fermato, può ancora consegnare un update a QUESTA closure anche dopo uno
                # STOP o un nuovo START (epoch cambiato). `_process` gating solo su `_running`
                # NON basta: un AVVIA rapido lo rimette True e un update del vecchio poller
                # scriverebbe con la cfg della VECCHIA sessione (CSV/DRY_RUN/limiti) →
                # segnale doppio/stantio. `_is_current()` (running E stesso epoch) blocca qui,
                # indipendentemente dal timing dell'arresto dell'updater.
                if not _is_current():
                    return
                msg = update.message or update.channel_post
                if not msg:
                    return
                # Anti-segnale-stantio (Codex P1): se la rete è caduta durante il
                # polling, PTB riconnette da solo e RECUPERA gli arretrati. Un
                # messaggio troppo vecchio (più di max_signal_age) va scartato: non è
                # un segnale "live" ma un arretrato dell'outage.
                msg_date = getattr(msg, "date", None)
                msg_epoch = msg_date.timestamp() if msg_date is not None else None
                # #53: il max_age effettivo non supera la vita della riga CSV per la modalità
                # coda attiva — `signal_queue.timeout_from_config(cfg)`, cioè `confirmation_timeout`
                # in QUEUE_UNTIL_CONFIRMED, altrimenti `clear_delay` (Codex): usare la STESSA
                # sorgente di timeout della coda evita di clampare a `clear_delay` quando la riga
                # vive in realtà più a lungo (default 120s conferma vs 90s clear). Un messaggio già
                # più vecchio della vita CSV è trattato come stantio, non scritto.
                max_age = message_freshness.effective_max_age(
                    cfg.get("max_signal_age", message_freshness.DEFAULT_MAX_AGE),
                    signal_queue.timeout_from_config(cfg))
                text = msg.text or msg.caption or ''
                runtime_chat = str(msg.chat_id)
                # Live-reload del routing (issue #82): INSTRADAMENTO e PARSING (chat ammesse,
                # parser attivo, provider, mappature, chat-notifiche, keyword) usano la config
                # VIVA (`self._config`, aggiornata a ogni salvataggio), non lo snapshot a START
                # — così rinominare un profilo o aggiungere un parser/sorgente ha effetto SUBITO.
                # Snapshot per-messaggio (lettura atomica del riferimento). L'ESECUZIONE resta
                # invece legata alla sessione (`cfg`): DRY_RUN/limiti, path CSV e token NON
                # cambiano a metà sessione, per non far scattare una bet reale o un CSV stantio.
                route = self._config if isinstance(self._config, dict) else cfg
                # Decisione di instradamento ESTRATTA e testabile in CI (#108): filtro chat
                # (fail-closed) → chat-notifiche (conferma o conflitto) → freschezza →
                # should_process. Il guard "nessun filtro" è PRIMO (Codex): se la config viva
                # azzera i filtri sorgente ma resta la notif-chat, l'instradamento conferma non
                # deve partire da uno stato prima fail-closed. La chat-notifiche resta PRIMA della
                # freschezza così una conferma ritardata non è scartata come stantia (#53). La
                # glue qui resta solo dispatch + log.
                decision = telegram_dispatch.decide(
                    route, runtime_chat, text, msg_epoch, time.time(), max_age)
                if decision == telegram_dispatch.IGNORE_STALE:
                    # Anti-segnale-stantio (Codex P1): un arretrato recuperato da PTB dopo una
                    # disconnessione non è un segnale "live".
                    self.after(0, lambda: self._log(
                        "⏳ Messaggio ignorato: troppo vecchio (probabile arretrato "
                        "dopo una disconnessione)."))
                    return
                if decision == telegram_dispatch.IGNORE_NO_FILTER:
                    # Difesa-in-profondità (CodeRabbit): con la config viva azzerata di
                    # chat_id/parser_by_chat/sorgenti, "nessun filtro" è fail-closed.
                    self.after(0, lambda: self._log(
                        "⚠️ Config live senza filtro chat: messaggio ignorato per sicurezza "
                        "(configura chat/sorgenti, poi salva)."))
                    return
                if decision == telegram_dispatch.IGNORE_CONFLICT:
                    # Codex P2: notif-chat che COINCIDE con una sorgente ammessa è AMBIGUA
                    # (segnale o esito?) → fail-closed, né scrittura né conferma.
                    self.after(0, lambda: self._log(
                        "❌ La Chat notifiche XTrader coincide con una sorgente ammessa: "
                        "config ambigua, messaggio IGNORATO (né segnale né conferma). "
                        "Correggi xtrader_notification_chat_id (dev'essere una chat separata)."))
                    return
                if decision == telegram_dispatch.CONFIRM:
                    # PR-23 + audit C8: la chat notifiche XTrader porta ESITI → percorso conferma.
                    self._process_confirmation(text, cfg, route_cfg=route, epoch=epoch)
                    return
                if decision == telegram_dispatch.IGNORE_NOT_RELEVANT:
                    # Chat non ammessa o messaggio non pertinente: non scrive.
                    return
                if decision != telegram_dispatch.PROCESS:
                    # Esito non riconosciuto (refuso / drift futuro del contratto di
                    # `decide`): FAIL-CLOSED — non instradare a `_process` (che scrive), ma
                    # ignorare con avviso (review CodeRabbit #158).
                    self.after(0, lambda d=decision: self._log(
                        f"⚠️ Esito instradamento sconosciuto ({d}): messaggio ignorato per sicurezza."))
                    return
                # decision == PROCESS
                # PR-14c: traccia l'ultimo messaggio pertinente ricevuto (diagnostica).
                clean = (text or "").strip()
                first_line = clean.splitlines()[0] if clean else ""
                self.after(0, lambda m=first_line[:120]: self._set_last("message", m))
                self._process(text, cfg, chat_id=runtime_chat, route_cfg=route, epoch=epoch)

            app.add_handler(MessageHandler(filters.ALL, _handle))
            await app.initialize()
            await app.start()
            # drop_pending_updates: scarta i messaggi accodati mentre il bridge era
            # offline, così all'avvio non si processano segnali vecchi (PR-11, #9).
            await app.updater.start_polling(
                allowed_updates=["message", "channel_post"], drop_pending_updates=True)
            # Connessione stabilita: azzera il backoff e segnala (utile dopo una
            # riconnessione). drop_pending_updates=True a OGNI (ri)connessione scarta
            # i messaggi accumulati mentre eravamo offline → niente segnali vecchi.
            self._reconnect_attempt = 0
            self.after(0, self._set_status_connected)
            # Attesa INTERROMPIBILE: si sveglia subito quando `_stop` setta `_async_stop_event`
            # (via `call_soon_threadsafe`), oppure ogni secondo per ricontrollare `_is_current()`
            # (nuovo START/STOP da altri percorsi). Così l'updater viene fermato senza la
            # finestra di ~1s che lascerebbe vivo il vecchio poller (Codex #191).
            while _is_current():
                try:
                    await asyncio.wait_for(stop_evt.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
                if stop_evt.is_set():
                    break
            # Shutdown sull'app LOCALE di questa sessione (non `self._tg_app`, che un nuovo
            # START può aver già rimpiazzato): si ferma SEMPRE il proprio updater (Codex #191).
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        # Supervisor con backoff: riprova le cadute di rete (errori transitori) finché
        # il bridge è in esecuzione; non ritenta dopo uno STOP manuale né su un errore
        # permanente (es. token invalido). La decisione è in `reconnect_policy` (pura,
        # testata in CI); qui solo I/O: shutdown pulito del vecchio updater (no doppio
        # polling) e attesa interrompibile.
        while _is_current():
            try:
                loop.run_until_complete(_async_run())
                break                      # uscita pulita: STOP richiesto
            except Exception as ex:        # noqa: BLE001 — gestito sotto
                self._safe_shutdown_tg(session_app, loop)   # chiude l'app DI QUESTA sessione prima di ritentare
                # Un nuovo START (epoch cambiato) o uno STOP invalidano QUESTA
                # sessione: esci senza ritentare (Codex P1, niente doppio poller).
                if not _is_current():
                    break
                if not reconnect_policy.should_reconnect(self._running, ex):
                    # errore non recuperabile mentre eravamo attivi (es. token invalido)
                    tb = traceback.format_exc()
                    self.after(0, lambda e=ex: self._set_last("error", f"bot: {e}"))
                    self.after(0, lambda e=ex: self._log(
                        f"❌ Errore non recuperabile del listener: {e}. Bridge fermato."))
                    # Traceback completo nel log per la diagnostica (redatto dal
                    # log handler): aiuta a capire un errore inatteso.
                    self.after(0, lambda t=tb: self._log(t))
                    self.after(0, self._stop)
                    break
                self._reconnect_attempt += 1
                # Event journal (#230): tentativo di riconnessione (tipo errore + tentativo).
                self._journal("RECONNECT", attempt=self._reconnect_attempt,
                              error=type(ex).__name__)
                # Backoff + flood-control di Telegram (Codex P2): se l'errore porta un
                # `retry_after` più lungo del backoff locale, attendi quello, così non si
                # riprova prima del tempo richiesto dal server. Decisione pura e testata
                # in `reconnect_policy.effective_delay`.
                retry_after = getattr(ex, "retry_after", None)
                delay = reconnect_policy.effective_delay(self._reconnect_attempt, retry_after)
                self.after(0, lambda e=ex: self._set_last("error", f"rete: {e}"))
                self.after(0, lambda e=ex, d=delay, n=self._reconnect_attempt: self._log(
                    f"🔌 Connessione persa ({type(e).__name__}): riconnessione tra "
                    f"{d:.0f}s (tentativo {n})…"))
                self.after(0, self._set_status_reconnecting)
                self._reconnect_wait(delay)
        # Sessione finita (STOP / nuovo START / errore non recuperabile): CHIUDI l'event
        # loop di QUESTA sessione, così selector/fd vengono rilasciati e non si accumula un
        # leak per ogni ciclo START/STOP (audit C1). Si chiude `loop` (riferimento locale),
        # non `self._loop`, che un nuovo START potrebbe aver già riassegnato; `self._loop`
        # si azzera solo se punta ancora a QUESTO loop. Il while gestisce già le sue
        # eccezioni, quindi qui siamo a loop fermo.
        try:
            loop.close()
        except Exception:                    # noqa: BLE001 — chiusura best-effort
            pass
        if self._loop is loop:
            self._loop = None

    def _safe_shutdown_tg(self, app, loop) -> None:
        """Chiude in modo best-effort l'app Telegram di QUESTA sessione (riferimento LOCALE
        `app`, sul `loop` di questa sessione) prima di un nuovo tentativo, così non restano due
        updater/polling attivi insieme. NON usa `self._tg_app`/`self._loop`: un nuovo START
        concorrente li avrebbe già rimpiazzati e si fermerebbe l'app/loop sbagliati (Codex #191)."""
        if app is None:
            return

        async def _shutdown():
            for step in (app.updater.stop, app.stop, app.shutdown):
                try:
                    await step()
                except Exception:        # noqa: BLE001 — chiusura best-effort
                    pass

        try:
            loop.run_until_complete(_shutdown())
        except Exception:                # noqa: BLE001
            pass
        # Azzera l'handle SOLO se punta ancora alla nostra app: non clobberare il `_tg_app`
        # di un nuovo START intervenuto nel frattempo (Codex #191).
        if self._tg_app is app:
            self._tg_app = None

    def _reconnect_wait(self, delay: float) -> None:
        """Attesa del backoff interrompibile, senza busy-poll: `Event.wait` dorme fino
        allo scadere del `delay` e si sblocca **subito** se arriva uno STOP (che
        imposta `_stop_event`)."""
        self._stop_event.wait(delay)

    def _set_status_reconnecting(self) -> None:
        self._status_lbl.configure(text="⬤  RICONNESSIONE…", text_color="#ffa726")

    def _set_status_connected(self) -> None:
        if self._running:
            self._status_lbl.configure(text="⬤  ATTIVO", text_color="#66bb6a")
            self._log("✅ Connesso a Telegram.")

    # ── PROCESS SIGNAL ────────────────────────
    def _epoch_current(self, epoch=None) -> bool:
        """Sessione listener ancora attiva: `_running` E (se `epoch` è fornito) stesso
        `_listener_epoch`. Da ricontrollare al PUNTO di scrittura/consumo, sotto `_queue_lock`
        (Codex #191): tra l'ingresso di un callback del vecchio updater e la scrittura, un
        STOP→START può rimettere `_running=True` con un epoch NUOVO; un gate solo su `_running`
        lascerebbe scrivere quel callback con la cfg della VECCHIA sessione (CSV/DRY_RUN/limiti)
        → segnale doppio/stantio. `epoch=None` (chiamanti legacy/test) → solo `_running`."""
        if epoch is None:
            return self._running
        return self._running and self._listener_epoch == epoch

    def _process(self, text: str, cfg: dict, chat_id: str = None, route_cfg: dict = None,
                 epoch=None):
        # `cfg` è la config di SESSIONE (snapshot a START): governa l'ESECUZIONE
        # (guardrail `live_guard`: DRY_RUN/limiti, e il path CSV), che NON deve cambiare a
        # metà sessione. `route_cfg` è la config VIVA per il ROUTING/PARSING (issue #82):
        # parser/provider/mappature nomi aggiornati applicati subito. Default a `cfg` per
        # retro-compatibilità (chiamanti senza routing live). `epoch` lega la scrittura alla
        # SESSIONE listener: un callback del vecchio updater non scrive dopo uno STOP→START.
        route = route_cfg if route_cfg is not None else cfg
        # Stop/sessione superata: non processare/consumare stato né scrivere (Codex P2/#191).
        # Il check DEFINITIVO anti-race (con il clear allo stop E con un nuovo START) è dentro
        # il queue_lock, sotto, al punto di scrittura.
        if not self._epoch_current(epoch):
            return
        # CP-09: instrada al Parser Personalizzato attivo (autoritativo) o, in
        # assenza, al parser hardcoded. Non scrive righe non piazzabili: meglio
        # scartare un segnale incompleto che generare una riga ambigua.
        self.after(0, lambda: self._bump("received"))   # PR-14: candidato instradato
        # Event journal (#230): solo la chat (niente testo), e in forma REDATTA — il diario è un
        # log DUREVOLE sotto AppData e il chat_id reale è sensibile (Telegram safety, Codex P2).
        self._journal("SIGNAL_RECEIVED", chat=log_privacy.redact_chat_id(chat_id))
        # Privacy log (audit #105 P1): di default il TESTO del messaggio NON va in chiaro
        # nei log — solo hash + lunghezza + prima riga troncata (`log_privacy.redact_message`).
        # Il payload completo solo se l'utente attiva `debug_message_payload` (opt-in).
        # Letto dalla config VIVA (`route`), non dallo snapshot di sessione (Codex P2): così
        # un OPT-OUT (l'utente disattiva il flag e salva a bridge attivo) ferma SUBITO il log
        # completo, senza dover riavviare. `as_bool_optin` è fail-closed (allowlist).
        payload_full = as_bool_optin(route.get("debug_message_payload"))
        # Debug (PR-3): traccia il messaggio in ingresso e la chat di origine. `_dbg`
        # va sul main thread (`_process` gira sul thread del listener Telegram).
        self.after(0, lambda m=log_privacy.redact_message(text, full=payload_full), c=chat_id:
                   self._dbg(f"IN (chat {c or '?'}): {m}"))
        # PR-P12: passa il risolutore ID del dizionario Betfair locale, così — dopo le
        # mappature a nomi — la riga viene arricchita con EventId/MarketId/SelectionId se
        # il dizionario trova un match univoco; altrimenti resta a nomi (fallback nomi).
        result = signal_router.resolve_row(text, route, chat_id=chat_id,
                                           id_resolver=self._betfair_id_resolver())
        # Event journal (#230): il PARSER è girato (esito + sorgente), PRIMA del ramo
        # piazzabile/scartato — così il diario distingue «parser eseguito ma segnale scartato»
        # da «mai ricevuto» anche per i non piazzabili, completando la pipeline RECEIVED→PARSED→
        # (VALIDATED|scarto) richiesta dal contratto (CodeRabbit). Niente dato del messaggio.
        self._journal("SIGNAL_PARSED", status=result.status, source=result.source,
                      placeable=result.placeable)
        if not result.placeable:
            detail = (", ".join(result.missing_required)
                      if result.missing_required else result.detail)
            self.after(0, lambda: self._bump("discarded"))
            self.after(0, lambda: self._log(
                f"⚠️ Segnale scartato ({result.source}/{result.status}): {detail}"))
            return

        # #192: il parser può produrre PIÙ righe (MultiMarket/MultiSelection). Per il single-row
        # `all_rows()` ne ritorna una sola → percorso legacy invariato. `row` è la prima riga
        # candidata, usata per la diagnostica dei rami NON-write (scarto/DRY_RUN, dove nulla è
        # scritto sul CSV operativo). La presentazione della scrittura RIUSCITA usa invece la
        # riga davvero scritta (`written_row`, vedi kyX più sotto), non `rows_to_commit[0]`.
        rows_to_commit = result.all_rows()
        row = rows_to_commit[0]
        # Provenienza MULTI (#192, Codex #239): un parser multi-riga espone `result.rows` (anche
        # con UNA sola riga piazzabile). L'instradamento del commit usa QUESTA provenienza, non il
        # numero di righe corrente: un parser multi che ora produce 1 riga deve comunque passare
        # dalla deduplica PER-RIGA (`commit_signals`), altrimenti se lo stesso messaggio in seguito
        # ne produce di più la riga già scritta (dedupata a hash-messaggio) sarebbe riscritta →
        # doppia scommessa.
        is_multi = result.rows is not None
        # Event journal (#230): segnale validato (piazzabile). Solo la sorgente del parser,
        # nessun dato del messaggio.
        self._journal("SIGNAL_VALIDATED", source=result.source)

        # Guardrail del percorso di scrittura (PR-21): dedup + limite/minuto +
        # limite/giorno + DRY_RUN. Solo WRITE autorizza la scrittura; ogni altro
        # esito la sopprime (anti-doppia-scommessa / simulazione).
        path = cfg["csv_path"]
        now = time.monotonic()   # scadenza coda = tempo trascorso, su clock monotòno (audit A3)
        # UN SOLO lock attorno a "valuta guardrail → aggiorna coda → scrivi CSV" (audit A2).
        # `SignalTracker`/`DailyLimiter` non hanno lock interno: consumarli FUORI dal
        # `_queue_lock` lascerebbe una finestra tra `evaluate` e la scrittura in cui due
        # callback interlacciati (seconda sorgente, reconnect) potrebbero passare entrambi il
        # dedup → doppia scommessa. La sequenza critica (valuta + coda + scrittura + rollback
        # fail-safe) è in `write_path.commit_signal`, esercitabile in CI; qui resta solo il
        # LOCK e l'anti-race con il clear allo stop.
        with self._queue_lock:
            # Anti-race DEFINITIVO al punto di scrittura (Codex P2/#191): se nel frattempo è
            # stato premuto STOP (clear in corso) O è intervenuto un nuovo START (epoch diverso,
            # `_running` rimesso True), NON valutare né scrivere — sarebbe la cfg di una sessione
            # superata. Ricontrollo sotto LO STESSO lock della scrittura, non solo all'ingresso.
            if not self._epoch_current(epoch):
                return
            if not is_multi:
                # Parser single-row (legacy): dedup a hash-messaggio, comportamento bit-identico.
                commit = write_path.commit_signal(
                    self._tracker, self._daily, self._queue,
                    cfg, text, row, path, now, write_rows)
            else:
                # #192: parser multi-riga → dedup PER-RIGA + scrittura atomica di TUTTE le righe
                # del messaggio (anche se ORA è una sola: provenienza multi preservata).
                commit = write_path.commit_signals(
                    self._tracker, self._daily, self._queue,
                    cfg, text, rows_to_commit, path, now, write_rows)
            # #153 H2: registra l'esito del lock CSV mentre la scrittura è ancora serializzata
            # (Codex #156). Solo il ramo WRITE scrive davvero su disco.
            csv_lock_event = self._record_csv_lock(
                commit.decision == live_guard.WRITE, commit.write_error)
        decision = commit.decision
        blocked_by_cap = commit.blocked_by_cap
        rows = commit.rows
        write_error = commit.write_error
        self._apply_csv_lock_event(csv_lock_event)   # #153 H2: GUI fuori dal lock
        # ── fuori dal lock: side-effect (persistenza guard state, GUI, log) ──
        if decision != live_guard.WRITE:
            # Esito non-WRITE (dup/rate/daily/dry-run): DUPLICATE/RATE_LIMITED non hanno consumato
            # stato; DAILY_LIMITED/DRY_RUN l'avevano consumato sotto lock ma `commit_signal` l'ha
            # già ANNULLATO (rollback, #184 low-tracker-nonwrite). Si persiste lo stato CORRENTE,
            # ormai coerente, così l'invariante «guardrail = WRITE reali» sopravvive al riavvio.
            if self._tracker is not None:
                self._save_guard_state()
            self._after_non_write(decision, row)
            return
        if write_error is not None:
            self.after(0, lambda: self._bump("errors"))
            self.after(0, lambda e=write_error: self._set_last("error", f"scrittura CSV: {e}"))
            self.after(0, lambda e=write_error: self._log(
                f"❌ Scrittura CSV fallita: {e}. Segnale non registrato (riprovabile)."))
            self._schedule_expiry(path)           # i segnali ripristinati devono comunque scadere
            return
        if blocked_by_cap:
            # Tetto di righe attive raggiunto (#136 p5): segnale NON aggiunto, guardrail già
            # ripristinati sotto lock (ritentabile). Avvisa, aggiorna l'indicatore e riprogramma
            # la scadenza così una riga si libera e il segnale potrà passare.
            if self._tracker is not None:
                self._save_guard_state()
            self.after(0, lambda: self._bump("discarded"))
            self.after(0, lambda m=multi_signal.blocked_message(self._queue.max_active):
                       self._log(m))
            self.after(0, lambda p=path, n=len(rows): self._note_csv(p, n))
            self.after(0, lambda n=len(rows): self._update_active_indicator(n))
            self._schedule_expiry(path)
            return
        # Scrittura riuscita: ora è sicuro persistere lo stato dei guardrail. Il recovery
        # del CSV-lock è già stato applicato sopra (`_apply_csv_lock_event`).
        if self._tracker is not None:
            self._save_guard_state()
        self.after(0, lambda: self._bump("written"))   # PR-14: riga scritta nel CSV
        # Event journal (#230): riga scritta nel CSV (numero righe attive + sorgente).
        self._journal("CSV_WRITTEN", rows=len(rows), source=result.source)
        # #234: il CSV operativo ora HA una riga attiva su disco → memorizzalo, così il prossimo
        # ritorno a solo header (scadenza/conferma/manuale/STOP/START) registra un clear reale.
        self._csv_had_active_row = True
        self.after(0, lambda p=path, n=len(rows): self._note_csv(p, n))
        self.after(0, lambda n=len(rows): self._update_active_indicator(n))   # #136 p5 indicatore

        # Presentazione della scrittura riuscita (pura, testata in `signal_outcome`):
        # «ultimo segnale» + log segnale (con sorgente) + log aggiornamento CSV.
        # kyX #192 (PR #239, Codex): la presentazione deve riflettere una riga REALMENTE
        # scritta su disco, non `rows_to_commit[0]`. In un commit MULTI-riga la prima riga
        # candidata può essere soppressa (duplicato scaduto/rate/daily) mentre una riga
        # successiva viene scritta: `row` (= `rows_to_commit[0]`) punterebbe a una riga NON
        # scritta → «ultimo segnale»/log segnale/«Messaggio→CSV» fuorvianti. Si prende la
        # PRIMA riga del messaggio effettivamente presente tra le righe attive scritte
        # (`rows` = `commit.rows`); fallback a `row` (single-row: la riga coincide sempre,
        # e il caso multi con TUTTE le righe scritte → written_row == row → invariato).
        written_row = next((r for r in rows_to_commit if r in rows), row)
        outcome = signal_outcome.describe_write(written_row, result.source, len(rows))
        self.after(0, lambda i=outcome.last_signal: self._set_last("signal", i, "white"))
        self.after(0, lambda m=outcome.signal_log: self._log(m))
        self.after(0, lambda m=outcome.csv_log: self._log(m))
        # Tracciabilità (PR-3): messaggio Telegram ↔ riga CSV scritta (data+ora già
        # nell'header `[HH:MM:SS]` della entry e nel nome file `bridge-AAAA-MM-GG.log`).
        # Il MESSAGGIO è redatto di default (privacy, audit #105 P1): solo hash + 1ª riga
        # troncata, payload completo solo con `debug_message_payload`. La RIGA CSV (dati
        # operativi della scommessa) resta per la tracciabilità; i token sono redatti dal sink.
        self.after(0, lambda m=log_privacy.redact_message(text, full=payload_full),
                   r=dict(written_row): self._log(
            "🧾 Messaggio→CSV  |  msg: " + m + "  |  riga: "
            + ", ".join(f"{k}={v}" for k, v in r.items() if v != "")))

        # Scadenza per-segnale: (ri)programma il tick alla scadenza più vicina (non un
        # ritardo fisso, così un segnale più vecchio non resta oltre il suo timeout).
        self._schedule_expiry(path)
        self.after(0, lambda d=self._queue_timeout: self._log(f"⏱️  Scadenza segnale tra ~{d}s"))

    def _after_non_write(self, decision: str, row: dict) -> None:
        """Gestisce gli esiti che NON scrivono il CSV (PR-21): log chiaro e, in
        DRY_RUN, aggiorna comunque l'ultimo segnale riconosciuto. La mappatura
        decisione→presentazione è pura in `signal_outcome.describe_non_write`; qui
        si applicano solo i side-effect GUI (bump/set_last/log) nello stesso ordine."""
        outcome = signal_outcome.describe_non_write(decision, row)
        if outcome is None:
            return
        self.after(0, lambda c=outcome.counter: self._bump(c))
        if outcome.last_signal is not None:
            self.after(0, lambda s=outcome.last_signal, col=outcome.last_color:
                       self._set_last("signal", s, col))
        self.after(0, lambda m=outcome.log: self._log(m))

    def _record_csv_lock(self, wrote: bool, write_error) -> str:
        """Registra l'esito di scrittura nel contatore CSV-lock (#153 H2) MENTRE si è ancora
        sotto `_queue_lock` (review Codex #156): così l'ordine dei conteggi rispecchia quello
        reale dei write su disco, anche con expiry su `Timer` e conferme concorrenti. Conta
        solo i rami che hanno **scritto** (`wrote`): dup/dry-run no. NON tocca scrittura/coda/
        rollback. Ritorna l'evento GUI da applicare fuori dal lock: `"escalate"`, `"recover"`
        o `""` (nulla)."""
        if not wrote:
            return ""
        if write_error is not None:
            return "escalate" if self._csv_lock.record_failure() else ""
        return "recover" if self._csv_lock.record_success() else ""

    def _apply_csv_lock_event(self, event: str) -> None:
        """Applica FUORI dal lock l'evento del contatore CSV-lock (#153 H2): stato «CSV
        bloccato» all'escalation, oppure recovery (log + campo «Ultimo errore» verde)."""
        if event == "escalate":
            self.after(0, lambda: self._set_last("error", "🔒 CSV bloccato da XTrader"))
            self.after(0, lambda m=self._csv_lock.text(): self._log(m))
        elif event == "recover":
            msg = self._csv_lock.recovery_text()
            self.after(0, lambda m=msg: self._log(m))
            self.after(0, lambda m=msg: self._set_last("error", m, "#66bb6a"))

    def _process_confirmation(self, text: str, cfg: dict, route_cfg: dict = None,
                              epoch=None) -> None:
        """Interpreta una notifica XTrader (PR-23) rispetto ai segnali in attesa e,
        se associata, marca l'esito rimuovendo il segnale dalla coda + CSV.

        - CONFIRMED (piazzata) o REJECTED (rifiutata/errore) → rimuove il segnale
          (scelta del proprietario: una volta che XTrader ha risposto, la riga non
          resta nel CSV);
        - UNKNOWN (associato ma esito non chiaro) / UNMATCHED (di un'altra scommessa)
          → solo log, nessuna modifica. Il TIMEOUT è già coperto dalla scadenza coda.

        Le KEYWORD di conferma/rifiuto sono lette dalla config VIVA (`route_cfg`,
        default = `cfg`): cambiarle a runtime ha effetto SUBITO, coerentemente col
        live-reload del routing (audit C8). Il `csv_path` resta invece legato allo
        snapshot di sessione (`cfg`), come gli altri parametri di ESECUZIONE
        (DRY_RUN/limiti/token), che non cambiano a metà sessione.
        """
        # Stop/sessione superata: non riscrivere il CSV dopo che lo STOP l'ha svuotato
        # (Codex P2) né con la cfg di una sessione precedente dopo un nuovo START (#191).
        if not self._epoch_current(epoch):
            return
        live = route_cfg if isinstance(route_cfg, dict) else cfg
        confirm_kw = confirmation_reader.normalize_keywords(live.get("confirmation_keywords"))
        reject_kw = confirmation_reader.normalize_keywords(live.get("rejection_keywords"))
        with self._queue_lock:
            pending = self._queue.pending() if self._queue is not None else []
        # interpret è puro: lo si chiama fuori dal lock (nessuna mutazione qui).
        result = confirmation_reader.interpret(
            text, pending, confirm_keywords=confirm_kw, reject_keywords=reject_kw)

        if result.status in (confirmation_reader.CONFIRMED, confirmation_reader.REJECTED):
            path = cfg["csv_path"]
            write_error = None
            with self._queue_lock:
                # Ricontrollo DEFINITIVO sotto il lock di scrittura (Codex #191): uno STOP→START
                # tra l'ingresso e qui non deve far riscrivere il CSV con la cfg della vecchia
                # sessione. Il segnale NON è ancora stato rimosso, quindi resta ritentabile.
                if not self._epoch_current(epoch):
                    return
                self._queue.confirm(result.signal_id)   # rimuove il segnale dalla coda
                # `now=` esclude dalle righe scritte un eventuale FRATELLO già scaduto ma non
                # ancora rimosso dal tick: una conferma non deve ri-scrivere nel CSV un segnale
                # oltre il suo timeout (#30, Codex). La sua rimozione dalla coda resta al tick.
                rows = self._queue.active_rows(now=time.monotonic())
                try:
                    write_rows(rows, path)
                except Exception as ex:   # noqa: BLE001 — esito a log, no crash
                    write_error = ex
                # #153 H2: esito lock CSV serializzato con la scrittura (Codex #156).
                csv_lock_event = self._record_csv_lock(True, write_error)
            self._apply_csv_lock_event(csv_lock_event)
            # Event journal (#230/#234 C): l'esito XTrader è GIÀ avvenuto (`queue.confirm` ha rimosso
            # il segnale dalla coda) → registralo SEMPRE, anche se la riscrittura CSV fallisce, prima
            # del return del retry. Altrimenti, su write-failure→retry, l'outcome andrebbe perso.
            self._journal(
                "XTRADER_CONFIRMED" if result.status == confirmation_reader.CONFIRMED
                else "XTRADER_REJECTED",
                signal_id=result.signal_id, remaining=len(rows))
            if write_error is not None:
                # Il segnale è già rimosso dalla coda ma il CSV (write fallita) ha
                # ancora la riga: riprova PRESTO (non a timeout pieno, che terrebbe la
                # riga stantia un intero intervallo) così la riga sparisce in fretta.
                # Il flag `_csv_had_active_row` resta com'era: il CSV su disco ha ancora la riga;
                # sarà il retry (`_expire_tick`) a riportarlo a solo header e a loggare il clear (#234 C).
                self.after(0, lambda: self._bump("errors"))
                self.after(0, lambda e=write_error: self._set_last("error", f"CSV dopo conferma: {e}"))
                self.after(0, lambda e=write_error: self._log(
                    f"❌ Aggiornamento CSV dopo conferma fallito: {e}. Riprovo a breve."))
                self._schedule_expiry(path, delay=_WRITE_RETRY_DELAY)
                return
            # Scrittura riuscita: aggiorna il flag di stato del CSV. Se era l'ULTIMO segnale attivo
            # (CSV tornato a solo header) registra il clear sulla transizione reale (#234), altrimenti
            # restano righe attive → il CSV ha ancora una riga.
            if rows:
                self._csv_had_active_row = True
            else:
                self._journal_csv_cleared_if_had_row("CSV_CLEARED", reason="confirmation")
            # Guard su None (review Sourcery): se in futuro si aggiungono status
            # terminali senza messaggio, non si logga `None`.
            removed_log = signal_outcome.confirmation_removed_log(result.status)
            if removed_log is not None:
                self.after(0, lambda m=removed_log: self._log(m))
            self.after(0, lambda p=path, n=len(rows): self._note_csv(p, n))
            self.after(0, lambda n=len(rows): self._update_active_indicator(n))   # #136 p5
            self._schedule_expiry(path)   # riprogramma per i segnali eventualmente rimasti
        else:
            # UNKNOWN o UNMATCHED: notifica che NON rimuove nulla → solo log informativo.
            # `confirmation_ignored_log` distingue i due casi; guard su None per status
            # non enumerati (difesa, review Sourcery).
            ignored_log = signal_outcome.confirmation_ignored_log(result.status)
            if ignored_log is not None:
                self.after(0, lambda m=ignored_log: self._log(m))

    def _schedule_expiry(self, path: str, delay=None) -> None:
        """(Ri)programma il tick di scadenza (PR-22). Con `delay=None` lo programma
        alla **scadenza più vicina** della coda (così un segnale più vecchio non
        resta oltre il suo timeout quando ne arrivano di nuovi); con un `delay`
        esplicito lo usa come ritardo (retry dopo un errore di scrittura)."""
        if delay is None:
            with self._queue_lock:
                nxt = self._queue.next_expiry() if self._queue is not None else None
            if nxt is None:
                return                       # niente di attivo: nessun tick da programmare
            # `nxt` è un expires_at su clock monotòno (audit A3): il ritardo va calcolato
            # con lo stesso clock, altrimenti un salto del wallclock falserebbe il tick.
            # `delay_until` clampa a 0 una scadenza già passata (no ritardo negativo).
            delay = signal_queue.delay_until(nxt, time.monotonic())
        # Replace ATOMICO sotto `_timer_lock` (#184 low-timer-lock): cancel del precedente +
        # creazione + assegnazione + start in un'unica sezione critica, così due caller concorrenti
        # non lasciano un secondo Timer avviato ma non referenziato.
        with self._timer_lock:
            if self._expire_timer is not None:
                self._expire_timer.cancel()
            timer = threading.Timer(delay, lambda: self._expire_tick(path))
            timer.daemon = True
            self._expire_timer = timer
            timer.start()

    def _cancel_expiry_timer(self) -> None:
        """Cancella il timer di scadenza (se presente) sotto `_timer_lock` e azzera il riferimento.
        Punto unico usato da STOP/chiusura/clear, così un cancel non si interlaccia con un replace
        di `_schedule_expiry` (#184 low-timer-lock)."""
        with self._timer_lock:
            if self._expire_timer is not None:
                self._expire_timer.cancel()
                self._expire_timer = None

    def _expire_tick(self, path: str) -> None:
        """Rimuove i segnali scaduti e riscrive le righe rimaste (o svuota il CSV
        se non ne resta nessuno). La scadenza è basata sul tempo della coda: non
        cancella mai un segnale ancora valido. Si riprogramma alla scadenza più
        vicina finché la coda non è vuota."""
        now = time.monotonic()   # stesso clock monotòno della coda/_process (audit A3)
        # Lock tenuto ATTRAVERSO la scrittura (monotòno con _process).
        write_error = None
        with self._queue_lock:
            if self._queue is None:
                return
            # Stop in corso: un tick già schedulato non deve riscrivere il CSV dopo
            # che lo STOP l'ha svuotato e azzerato la coda (Codex P2).
            if not self._running:
                return
            expired = self._queue.expire(now=now)
            rows = self._queue.active_rows()
            empty = self._queue.is_empty()
            try:
                write_rows(rows, path)    # rows vuota → solo header (CSV svuotato)
            except Exception as ex:       # noqa: BLE001 — esito riportato a log, no crash
                write_error = ex
            # #153 H2: esito lock CSV serializzato con la scrittura (Codex #156).
            csv_lock_event = self._record_csv_lock(True, write_error)
        self._apply_csv_lock_event(csv_lock_event)
        if write_error is not None:
            # La coda (memoria) ha già rimosso gli scaduti ma il CSV è rimasto indietro:
            # RIPROVA con un ritardo limitato (non a scadenza, che sarebbe nel passato
            # → busy-loop), così il disco converge allo stato della coda. Riprogramma
            # anche a coda vuota (un segnale scaduto non deve restare nel CSV).
            self.after(0, lambda: self._bump("errors"))
            self.after(0, lambda e=write_error: self._set_last("error", f"CSV alla scadenza: {e}"))
            self.after(0, lambda e=write_error: self._log(
                f"❌ Aggiornamento CSV alla scadenza fallito: {e}. Riprovo a breve."))
            self._schedule_expiry(path, delay=_WRITE_RETRY_DELAY)
            return
        if expired:
            self.after(0, lambda p=path, n=len(rows): self._note_csv(p, n))
            self.after(0, lambda n=len(rows): self._update_active_indicator(n))   # #136 p5
            self.after(0, lambda n=len(expired): self._log(
                f"🗑️  {n} segnale/i scaduto/i rimosso/i dal CSV"))
        # Stato del CSV dopo una scrittura RIUSCITA (#230/#234 D): se restano righe il CSV è ancora
        # attivo; se è tornato a solo header registra il clear sulla transizione reale. Gestito QUI
        # (non gated su `expired`) così anche un RETRY post-write-failure — dove `expired` è vuoto
        # perché gli scaduti erano già stati rimossi in un tick precedente, ma il CSV viene ora
        # davvero riportato a solo header — registra comunque il clear.
        if rows:
            self._csv_had_active_row = True
        else:
            self._journal_csv_cleared_if_had_row("CSV_CLEARED", reason="expiry")
        if not empty:
            self._schedule_expiry(path)

    def _manual_clear(self):
        # In esecuzione si svuota il CSV ATTIVO della sessione (catturato a START), non il
        # path del campo GUI: l'utente potrebbe averlo cambiato a runtime e svuotare il
        # file sbagliato lascerebbe una riga ORFANA nel CSV operativo reale (A2). A bridge
        # fermo non c'è sessione attiva → si usa il campo GUI.
        if self._running and self._active_csv_path:
            path = self._active_csv_path
        else:
            path = self._e_csv.get().strip()
        if not path:
            return
        # Ferma il tick di scadenza così non riscrive il CSV mentre lo svuotiamo (PR-22).
        self._cancel_expiry_timer()
        # Svuotamento ATOMICO rispetto a _process: teniamo `_queue_lock` ATTRAVERSO sia
        # la scrittura del CSV (init_csv) sia l'azzeramento della coda (come _process
        # tiene il lock attraverso write_rows). Così un segnale che arriva in
        # contemporanea resta o del tutto FUORI (CSV+coda già svuotati) o del tutto
        # DENTRO (lo rimuoviamo qui): senza questo, _process potrebbe inserire una riga
        # TRA init_csv e l'azzeramento e lasciarla sul disco senza tracciamento (P1).
        # Se l'I/O fallisce (file lockato da XTrader, path non scrivibile) NON azzeriamo
        # la coda e RIPROGRAMMIAMO la scadenza, così la riga rimasta sul disco viene
        # comunque ripulita più tardi invece di restare orfana; e non crasha la GUI.
        write_error = None
        with self._queue_lock:
            try:
                init_csv(path)
            except OSError as exc:
                write_error = exc
            else:
                if self._queue is not None:
                    for sid in self._queue.active_ids():
                        self._queue.remove(sid)
            # #153 H2 (Codex #156): anche lo svuotamento manuale è una scrittura su disco.
            # Registra l'esito sotto lock, così un clear riuscito dopo lo sblocco esce
            # dallo stato «CSV bloccato» (altrimenti, cancellando il timer, nessun
            # `_apply_csv_lock_event` successivo lo farebbe).
            csv_lock_event = self._record_csv_lock(True, write_error)
        self._apply_csv_lock_event(csv_lock_event)
        if write_error is not None:
            # Path + tipo eccezione aiutano a diagnosticare lock/permessi.
            self._log(
                f"❌ Svuotamento CSV fallito ({path}): "
                f"{type(write_error).__name__}: {write_error}"
            )
            self._schedule_expiry(path)   # fuori dal lock: _schedule_expiry lo riacquisisce
            return
        self._note_csv(path, 0)
        self._log("🗑️  CSV svuotato manualmente")
        # Event journal (#230/#234): lo svuotamento MANUALE riporta il CSV a solo header → registralo,
        # ma SOLO se c'era davvero una riga (no clear spurio se il CSV era già a solo header). Solo sul
        # percorso riuscito (write_error già ritornato sopra). Best-effort, fuori dal lock.
        self._journal_csv_cleared_if_had_row("CSV_CLEARED", reason="manual")

    def _refresh_tool_panels_after_profile(self, panel_refs, saved) -> None:
        """Ricarica dal disco le schede Strumenti già costruite dopo l'applicazione di un
        profilo (Provider, Chat sorgenti, Mapping, Betfair Sync). Senza, un loro Salva
        successivo riscriverebbe lo stato vecchio sopra il profilo — per Chat sorgenti
        significherebbe riscrivere `source_chats` vecchie e INDEBOLIRE il filtro chat
        (Codex P1).

        Best-effort: un refresh fallito NON blocca il caricamento del profilo, ma NON viene
        più ingoiato in silenzio — si LOGGA quale scheda è rimasta stantia, così l'utente sa
        che quella tab mostra ancora valori precedenti invece di credere tutto aggiornato
        mentre il load segnala successo (Codex P2 #94)."""
        for _key in ("provider", "sources", "mapping"):
            _panel = panel_refs.get(_key)
            if _panel is not None:
                try:
                    _panel.refresh()
                except Exception as ex:       # noqa: BLE001 — best-effort, ma non silenzioso
                    self._log(f"⚠️ Scheda {_TOOL_PANEL_LABELS[_key]} non aggiornata dal "
                              f"profilo (mostra ancora i valori precedenti): {ex}")
        # La tab Betfair ha controlli auto-sync (enabled/hour/sport) caricati dalla config:
        # dopo un profilo va ricaricata, altrimenti un suo Salva riscrive i valori vecchi.
        _bf_panel = getattr(self, "_betfair_panel", None)
        if _bf_panel is not None:
            try:
                _bf_panel.refresh_autosync(
                    config_store.as_bool_optin(saved.get("betfair_auto_sync", False)),
                    saved.get("betfair_auto_sync_hour", 23),
                    saved.get("betfair_sync_sports"))
            except Exception as ex:           # noqa: BLE001 — best-effort, ma non silenzioso
                self._log(f"⚠️ Scheda Betfair Sync non aggiornata dal profilo "
                          f"(mostra ancora i valori precedenti): {ex}")

    def _open_tools(self, initial=None):
        """Apre la finestra hub "🧰 Strumenti" a schede (consolidazione GUI, roadmap).
        Import lazy: le GUI degli strumenti non servono all'avvio del bridge. Qui si
        cablano le callback dei pannelli (la GUI principale ha la config viva), così
        `ProviderPanel`/`ProfilesPanel` aggiornano la config in memoria come facevano da
        finestre separate (stesso pattern anti-stale di Provider/Profili/Sorgenti).

        `initial`: titolo della scheda da mostrare all'apertura (es. dal pulsante)."""
        from .tools_gui import ToolsWindow
        from .provider_gui import ProviderPanel
        from .profiles_gui import ProfilesPanel
        from .source_chats_gui import SourceChatsPanel
        from .name_mapping_gui import MappingPanel
        from .custom_parser_gui import CustomParserPanel
        from .betfair.sync_tab_gui import BetfairSyncPanel
        from .betfair.sync_engine import OK as _SYNC_OK

        # UNA sola finestra hub: se è già aperta, si cambia scheda e la si porta in primo
        # piano invece di aprirne una seconda identica (CodeRabbit). `winfo_exists` è 0 se
        # è stata chiusa → in quel caso se ne crea una nuova.
        existing = getattr(self, "_tools_win", None)
        try:
            alive = existing is not None and existing.winfo_exists()
        except Exception:               # noqa: BLE001 — widget Tk distrutto: tratta come assente
            alive = False
        if alive:
            existing.select_tab(initial)
            existing.lift()
            existing.focus()
            return

        panel_refs = {}        # riferimenti ai pannelli vivi (per refresh cross-scheda)

        def _provider_saved(new_cfg):
            """Provider salvato: aggiorna la config in memoria (anti-stale)."""
            had = self._had_incomplete_token_load()   # marker PRIMA di sostituire self._config
            self._config = new_cfg
            # Il save del pannello può aver reidratato il token dal keyring lasciando il campo
            # password vuoto (PR-08c): risincronizzalo così il Salva principale successivo non lo
            # scambia per un clear e non cancella il token.
            self._resync_token_field(had)

        def _profiles_loaded(new_cfg):
            """Profilo caricato: persiste (con gate sicurezza + banner), aggiorna form/chat."""
            saved, ok = result = self._persist_loaded_profile(new_cfg)
            self._populate_form(saved)
            self._refresh_listened_chats()
            # Un profilo applicato cambia config.json: le schede Strumenti già costruite hanno
            # stato STANTIO in memoria e vanno ricaricate dal disco (estratto per essere
            # testabile headless — Codex #94).
            self._refresh_tool_panels_after_profile(panel_refs, saved)
            if ok:
                self._log("📁 Profilo caricato e applicato (token invariato).")
            else:
                # Causa SPECIFICA (#255 line-647): disco vs keyring vs config corrotto.
                self._log("⚠️ Profilo applicato in memoria (token invariato), ma NON persistito. "
                          + config_store.save_status_message(result.status))

        def _sources_saved(new_cfg):
            """Sorgenti salvate: aggiorna config in memoria + chat ascoltate (START usa
            subito le sorgenti modificate)."""
            had = self._had_incomplete_token_load()   # PR-08c: marker prima del replace
            self._config = new_cfg
            self._resync_token_field(had)             # reidrata il campo token se serve (PR-08c)
            self._refresh_listened_chats()
            self._log(f"📡 Sorgenti multi-chat aggiornate ({len(new_cfg.get('source_chats', []))}).")

        def _mapping_saved(new_cfg):
            """Dizionario nomi (area Calcio del Mapping) salvato: aggiorna la config in
            memoria (anti-stale, stesso pattern di Provider/Sorgenti)."""
            had = self._had_incomplete_token_load()   # PR-08c: marker prima del replace
            self._config = new_cfg
            self._resync_token_field(had)             # reidrata il campo token se serve (PR-08c)

        def _parser_saved(new_cfg):
            """Anagrafica Provider salvata dal builder: aggiorna la config in memoria,
            così un successivo Salva/Avvia non riscrive il file perdendo i provider."""
            had = self._had_incomplete_token_load()   # PR-08c: marker prima del replace
            self._config = new_cfg
            self._resync_token_field(had)             # reidrata il campo token se serve (PR-08c)

        # Parametri del builder dal config corrente: `provider` precompila la colonna
        # Provider; `recognition_mode` serve all'anteprima di un parser legacy a eredità.
        _cfg = self._load_config()
        _parser_provider = str(_cfg.get("provider", "")).strip()
        _parser_global_mode = str(_cfg.get("recognition_mode", "")).strip()

        def _make_provider(parent):
            """Crea il pannello Provider e ne tiene il riferimento per il refresh."""
            panel_refs["provider"] = ProviderPanel(parent, on_saved=_provider_saved)
            return panel_refs["provider"]

        def _make_parser(parent):
            """Crea il pannello Parser Personalizzato (scheda 🧩 Parser)."""
            # Factory best-effort del dizionario Betfair (#192, Codex): rende «Prova
            # messaggio» equivalente al runtime per i parser ID_ONLY dizionario-dipendenti
            # (l'anteprima risolve gli ID come il live). Usa `_preview_id_resolver_factory`
            # (non `_betfair_id_resolver`): salta durante una sync per non congelare il thread
            # GUI sul lock del DB (Codex P2). Fail-open: durante la sync l'anteprima è conservativa.
            return CustomParserPanel(parent, provider=_parser_provider,
                                     global_mode=_parser_global_mode, on_saved=_parser_saved,
                                     id_resolver_factory=self._preview_id_resolver_factory)

        def _make_sources(parent):
            """Crea il pannello Chat sorgenti e ne tiene il riferimento per il refresh."""
            panel_refs["sources"] = SourceChatsPanel(parent, on_saved=_sources_saved)
            return panel_refs["sources"]

        def _make_mapping(parent):
            """Crea il pannello Mapping e ne tiene il riferimento per il refresh."""
            panel_refs["mapping"] = MappingPanel(parent, on_saved=_mapping_saved)
            return panel_refs["mapping"]

        def _betfair_sync(sports):
            """Callback «Sincronizza ora»: la sync (rete) gira su un WORKER THREAD per
            non bloccare la GUI Tk; l'esito è marshalato sul main thread con
            `after(0, ...)` e loggato in forma safe (CodeRabbit/Codex)."""
            engine = self._betfair_sync_engine()

            def _report(res):
                if res.status == _SYNC_OK:
                    self._log(f"🔄 Sync Betfair OK — sport {res.sports}: "
                              f"+{res.new_events} eventi, +{res.new_markets} mercati, "
                              f"+{res.new_selections} selezioni, {res.deactivated} disattivati.")
                else:
                    self._log("⚠️ Sync Betfair non eseguita: "
                              + ("; ".join(res.errors) if res.errors else res.status))

            def _worker():
                res = engine.run(sports)
                self.after(0, lambda: _report(res))

            threading.Thread(target=_worker, daemon=True, name="betfair-sync").start()

        def _betfair_autosync_change(enabled, hour, sports):
            """Checkbox/orario/sport auto-sync cambiati nel pannello: persiste in config.
            Gli sport selezionati vengono salvati con i flag, così l'auto-sync usa
            esattamente quelli scelti (Codex). Un salvataggio fallito è segnalato come
            tale invece di dichiarare ON (Codex)."""
            # Parti dalla config LIVE in memoria (non da una rilettura del disco): se un
            # save precedente è fallito, il disco è stantio e ne riscriveremmo sopra le
            # impostazioni attive (source_chats/dry_run/…) sovrascrivendo `self._config`
            # con uno snapshot vecchio. Sovrapponi SOLO le chiavi auto-sync (Codex).
            cfg = dict(self._config) if isinstance(self._config, dict) else self._load_config()
            cfg["betfair_auto_sync"] = bool(enabled)
            cfg["betfair_auto_sync_hour"] = int(hour)
            if sports is not None:
                cfg["betfair_sync_sports"] = list(sports)
            had = self._had_incomplete_token_load()   # PR-08c: il save consuma il marker
            saved, ok = result = save_config(cfg, CONFIG_FILE)
            self._config = saved
            # Reidratazione del campo token dopo un save non-GUI (PR-08c): vedi _on_retention_change.
            self._resync_token_field(had)
            self._save_ok = ok
            if ok:
                self._log(f"🔵 Auto-sync Betfair {'ON' if enabled else 'OFF'} (orario {hour:02d}).")
                # Kick immediato: abilitando o portando l'ora a quella corrente subito dopo
                # un tick a 60s, si perderebbe la finestra a cavallo dell'ora (es. 23:59:30
                # → prossimo check dopo mezzanotte, ora 00 ≠ 23). Cancella il tick pendente
                # e rilancia subito; il tick si ri-arma da solo, così la chain resta unica
                # (niente doppio timer) — Codex.
                if not self._closing:
                    _prev = getattr(self, "_autosync_after_id", None)
                    if _prev is not None:
                        try:
                            self.after_cancel(_prev)
                        except Exception:   # noqa: BLE001 — id già scaduto/invalido
                            pass
                    self._autosync_after_id = self.after(0, self._betfair_autosync_tick)
            else:
                # Causa SPECIFICA (#255 line-647): disco vs keyring vs config corrotto.
                self._log("⚠️ Auto-sync Betfair NON persistito. "
                          + config_store.save_status_message(result.status))

        def _make_betfair(parent):
            """Crea la tab Betfair Sync (credenziali locali + stato login/sync + auto).
            Apre qui il DB/engine, così un suo errore resta isolato a questa scheda."""
            self._betfair_sync_engine()    # forza la creazione del DB nel try/except del pannello
            self._betfair_panel = BetfairSyncPanel(
                parent, session=self._betfair_session_obj(),
                on_login=self._betfair_login_async, on_sync=_betfair_sync,
                on_invalidate=self._betfair_invalidate_login,
                autosync=self._betfair_autosync_seed(),   # config LIVE, non disco stantio (Codex)
                on_autosync_change=_betfair_autosync_change)
            return self._betfair_panel

        def _make_dictionary(parent):
            """Crea la tab «Dizionario Betfair» (SOLA LETTURA): consulta sport/eventi/
            mercati/selezioni sincronizzati localmente. Riusa il DB del motore Betfair
            (stessa istanza), senza scrivere nulla."""
            from .betfair.dictionary_viewer import DictionaryViewerController
            from .betfair.dictionary_viewer_gui import DictionaryViewerPanel
            controller = DictionaryViewerController(self._betfair_sync_engine().db)
            return DictionaryViewerPanel(parent, controller=controller)

        panels = [
            ("🧩 Parser", _make_parser),
            ("📡 Chat sorgenti", _make_sources),
            ("📇 Provider", _make_provider),
            ("📁 Profili",
             lambda parent: ProfilesPanel(
                 parent, get_current_cfg=self._profiles_snapshot,
                 on_loaded=_profiles_loaded, is_running=lambda: self._running)),
            ("🗺️ Mapping", _make_mapping),
            ("🔵 Betfair Sync", _make_betfair),
            ("📖 Dizionario Betfair", _make_dictionary),
        ]
        self._tools_win = ToolsWindow(self, panels=panels, initial=initial)
        self._tools_win.focus()

    def _populate_form(self, cfg: dict) -> None:
        """Ripopola i campi del form (base + avanzati) dalla config passata: usato dopo
        il caricamento di un profilo, così i widget mostrano i valori applicati e un
        salvataggio successivo non riscrive i valori vecchi sopra il profilo. Simmetrico
        a `_build_ui` (stesse chiavi, stessa normalizzazione del controller)."""
        cfg = cfg if isinstance(cfg, dict) else {}
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(cfg.get(key, "")))
        adv = settings_controller.current_values(cfg)
        for key, widget in self._adv.items():
            if key not in adv:   # robusto se current_values evolve e omette una chiave
                continue
            value = adv[key]
            if isinstance(widget, tk.Variable):
                widget.set(value)
            else:   # CTkEntry (campi di testo avanzati)
                widget.delete(0, "end")
                widget.insert(0, str(value))
        # Tab Log (PR-3): allinea anche retention e Debug al profilo caricato, altrimenti
        # i widget mostrerebbero lo stato vecchio mentre `self._config` ne usa un altro
        # (es. profilo con debug_log: true ma checkbox spenta) (Codex).
        if hasattr(self, "_retention_var"):
            self._retention_var.set(_retention_label(event_log.retention_days(cfg)))
        if hasattr(self, "_debug_var"):
            self._debug_var.set(as_bool(cfg.get("debug_log", False)))
