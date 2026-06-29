"""Auto Sync locale del dizionario Betfair (issue #86 PR-P8).

Se il bridge è **aperto** e l'auto-sync è **attiva**, all'orario impostato (HH,
default 23) il bridge fa **auto login → sync → auto logout** una sola volta al
giorno. Regole (dall'issue):

- se il bridge è chiuso, non parte (è il chiamante GUI a fare il tick solo mentre è
  aperto);
- se il bridge viene aperto DOPO l'orario, NON recupera la sync persa (la decisione è
  legata all'ora corrente, non a un recupero);
- non parte se una sync è già in corso (`engine.is_syncing`);
- non parte due volte lo stesso giorno allo stesso orario (`last_run_key`);
- il **logout è sempre eseguito in `finally`**, anche se login/sync falliscono.

La decisione «deve scattare ora?» è una funzione **pura** (`should_run`) testabile
senza tempo reale; il ciclo (`AutoSyncScheduler.maybe_run`) usa dipendenze iniettate
(auth client + sync engine), così è testabile offline. Nessun segreto nei log;
nessuna operazione di scommessa (ereditata dal motore read-only).
"""

import threading

from .sync_engine import FAILED, SyncResult


def normalize_hour(value, default: int = 23) -> int:
    """Normalizza l'orario auto-sync a un'ora valida [0, 23]; invalido → `default`."""
    if isinstance(value, bool):
        return default
    try:
        h = int(value)
    except (TypeError, ValueError):
        return default
    return h if 0 <= h <= 23 else default


def run_key(now, hour) -> list:
    """Chiave «giorno + ora» di una run, per non rieseguire lo stesso giorno/orario.
    È una **lista** (non tupla) così è serializzabile/round-trippabile in JSON quando
    viene persistita su disco (vedi `AutoSyncScheduler` load/save state)."""
    return [now.year, now.month, now.day, int(hour)]


def should_run(now, *, enabled, hour, last_run_key, sync_in_progress) -> bool:
    """`True` se l'auto-sync deve scattare ADESSO.

    - `enabled` deve essere vero;
    - nessuna sync già in corso;
    - l'ora corrente deve coincidere con `hour` (granularità oraria: aprire il bridge
      a un'ora diversa NON recupera la sync persa);
    - non deve essere già stata eseguita oggi a quell'ora (`last_run_key`)."""
    if not enabled or sync_in_progress:
        return False
    # Normalizza l'ora UNA volta e riusala sia per il confronto sull'orologio sia per
    # la run_key: passare l'ora grezza a run_key (che fa int(hour)) potrebbe crashare
    # su "x" o produrre una chiave sbagliata su valori non numerici (CodeRabbit).
    normalized_hour = normalize_hour(hour)
    if now.hour != normalized_hour:
        return False
    return last_run_key != run_key(now, normalized_hour)


class AutoSyncScheduler:
    """Scheduler locale dell'auto-sync. Da «ticchettare» dalla GUI mentre il bridge
    è aperto (es. ogni minuto), passando l'ora corrente.

    Dipendenze iniettate (testabili offline):
    - `auth`: client con `login(creds)` / `logout()`;
    - `engine`: `SyncEngine` (espone `is_syncing` e `run(sports)`);
    - `get_config()`: ritorna `(enabled, hour, sports)` correnti — config LEGGERA, niente
      credenziali (così non si colpisce il keyring a ogni tick, CodeRabbit);
    - `get_credentials()`: ritorna le credenziali per l'auto-login, lette **solo** quando
      la run è dovuta (dentro `_cycle`), non a ogni tick;
    - `is_bridge_open()`: `True` se la finestra è aperta (default: sempre);
    - `on_summary(result)`: callback opzionale per il riepilogo safe in GUI/log."""

    def __init__(self, *, auth, engine, get_config, get_credentials=None,
                 is_bridge_open=None, on_summary=None, load_state=None,
                 save_state=None, on_state_error=None):
        self.auth = auth
        self.engine = engine
        self.get_config = get_config
        self.get_credentials = get_credentials or (lambda: None)
        self.is_bridge_open = is_bridge_open or (lambda: True)
        self.on_summary = on_summary
        # Persistenza opzionale dell'ultima run (giorno+ora): senza, lo stato vive solo
        # in RAM e un riavvio nella stessa ora ri-eseguirebbe l'auto-sync (Codex).
        self._load_state = load_state
        self._save_state = save_state
        # Callback opzionale invocato se il salvataggio dello stato fallisce: la run è
        # andata bene ma la guardia 'una volta al giorno' NON è durabile (Codex).
        self._on_state_error = on_state_error
        self._last_run_key = None
        self._loaded = False
        # Gate in-flight: impedisce due cicli sovrapposti nella finestra di login (prima
        # che `engine.is_syncing` diventi vero). Thread-safe per i tick su worker.
        self._gate = threading.Lock()
        self._running = False

    @property
    def last_run_key(self):
        return self._last_run_key

    def _ensure_loaded(self):
        """Carica una volta l'ultima run persistita (se presente), così la guardia
        'una volta al giorno/orario' sopravvive ai riavvii del bridge."""
        if self._loaded:
            return
        self._loaded = True
        if self._load_state:
            try:
                self._last_run_key = self._load_state()
            except Exception:   # noqa: BLE001 — stato corrotto/assente → riparte da zero
                self._last_run_key = None

    def maybe_run(self, now):
        """Valuta la decisione e, se è ora, esegue il ciclo auto login→sync→logout.

        Ritorna il `SyncResult` se la sync è partita, altrimenti `None` (bridge chiuso,
        auto-sync spenta, fuori orario, già eseguita, sync in corso o ciclo già attivo).

        La run viene marcata «eseguita oggi» (e persistita) **solo se ha SUCCESSO**:
        un tentativo fallito (cert mancante, rete giù, sport vuoti) NON consuma la
        finestra, così i tick successivi della stessa ora **ritentano** (Codex)."""
        if not self.is_bridge_open():
            return None
        self._ensure_loaded()
        # SOLO config leggera qui (enabled/hour/sports): le credenziali (keyring) NON
        # vanno lette a ogni tick (anche fuori orario o a run già fatta), né prima del
        # gate _running, altrimenti un keyring lento accatasta worker thread (CodeRabbit).
        # Le credenziali si caricano dentro `_cycle`, solo quando la run è davvero dovuta.
        enabled, hour, sports = self.get_config()
        # Normalizza l'ora UNA volta e usala sia per la decisione sia per la run_key di
        # successo: altrimenti un `hour` non numerico ("x") supererebbe `should_run`
        # (che già normalizza) ma poi crasherebbe in `run_key(now, hour)` → int("x")
        # DOPO una sync riuscita, lasciando la run non marcata e rieseguibile (CodeRabbit).
        normalized_hour = normalize_hour(hour)
        # Check-and-set atomico: niente cicli sovrapposti (gate) + decisione pura.
        with self._gate:
            if self._running:
                return None
            if not should_run(now, enabled=enabled, hour=normalized_hour,
                              last_run_key=self._last_run_key,
                              sync_in_progress=self.engine.is_syncing):
                return None
            self._running = True
        try:
            result = self._cycle(sports)
            if getattr(result, "ok", False):
                # Solo su successo: marca e persiste, così non ri-scatta oggi/ora.
                self._last_run_key = run_key(now, normalized_hour)
                if self._save_state:
                    try:
                        self._save_state(self._last_run_key)
                    except Exception as ex:   # noqa: BLE001
                        # La run è ok ma lo stato NON è durabile: segnalalo (un riavvio
                        # nella stessa ora potrebbe ri-eseguire) invece di tacere (Codex).
                        if self._on_state_error:
                            try:
                                self._on_state_error(ex)
                            except Exception:   # noqa: BLE001
                                pass
            return result
        finally:
            with self._gate:
                self._running = False

    def _cycle(self, sports):
        """Auto login → sync → auto logout.

        Prenota il lock del motore PRIMA del login (se il motore lo supporta): se una
        sync manuale è in corso, NON esegue login/logout sulla sessione condivisa
        (eviterebbe di sloggare la tab manuale) e ritorna `BUSY` (Codex). Le credenziali
        si leggono SOLO ora (job dovuto, gate impostato, lock preso), non a ogni tick
        (CodeRabbit). Dopo il login aggiorna la App Key del motore con quella delle
        credenziali appena usate, così la sync non invia una App Key vecchia (Codex).

        Il logout viene eseguito **solo se è stato questo ciclo a fare login** (`logged_in`):
        - se `auth.login` fallisce (cert mancante, credenziali stantie) NON ha sostituito il
          token di un'eventuale sessione manuale;
        - se la sessione condivisa è **già loggata** (login manuale dalla tab, idle) il ciclo
          NON fa login/logout e riusa la sessione esistente per la sync, così non slogga
          l'utente nonostante nessuna sync manuale fosse in corso (Codex)."""
        reserve = getattr(self.engine, "reserve", None)
        release = getattr(self.engine, "release", None)
        reserved = False
        if reserve is not None and release is not None:
            if not reserve():     # sync manuale già in corso: non toccare la sessione
                result = SyncResult(status="BUSY",
                                    errors=["Sync manuale in corso: auto-sync rimandata."])
                self._safe_summary(result)
                return result
            reserved = True

        creds = self.get_credentials()
        # Sessione condivisa già attiva (login manuale idle)? Allora NON fare login/logout:
        # li rifaremmo sulla stessa sessione e alla fine la chiuderemmo, sloggando l'utente
        # anche senza sync manuale in corso. Riusa la sessione esistente per la sync (Codex).
        session = getattr(self.auth, "session", None)
        pre_logged = bool(getattr(session, "is_logged_in", False))
        logged_in = False
        result = None
        try:
            if not pre_logged:
                self.auth.login(creds)
                logged_in = True
                set_app_key = getattr(self.engine, "set_app_key", None)
                if set_app_key:
                    set_app_key(getattr(creds, "app_key", None))
            # Con lock già prenotato, run NON lo riacquisisce (locked=True).
            result = (self.engine.run(sports, locked=True) if reserved
                      else self.engine.run(sports))
        except Exception as ex:   # noqa: BLE001 — fallimento safe, niente crash/segreti
            result = SyncResult(status=FAILED,
                                errors=[f"Auto-sync fallita ({type(ex).__name__})."])
        finally:
            if logged_in:
                try:
                    self.auth.logout()
                except Exception:     # noqa: BLE001 — il logout best-effort non deve propagare
                    pass
            if reserved:
                # Anche il release è best-effort (#184 LOW): un'eccezione qui propagherebbe
                # dal `finally` di `_cycle` fino al worker del tick GUI, mascherando il
                # `result` già calcolato e NON registrando una run riuscita (la stessa ora
                # verrebbe rieseguita). Logout e release sono indipendenti: il fallimento
                # dell'uno non deve impedire l'altro.
                try:
                    release()
                except Exception:     # noqa: BLE001 — il release best-effort non deve propagare
                    pass
        self._safe_summary(result)
        return result

    def _safe_summary(self, result):
        """Riepilogo **best-effort**: un `on_summary` che solleva (es. l'app schedula un
        Tk `after` su una finestra in chiusura) NON deve far propagare l'eccezione da
        `_cycle` e impedire a `maybe_run` di registrare una run riuscita — la stessa ora
        verrebbe poi rieseguita al tick/riavvio successivo (Codex)."""
        if self.on_summary:
            try:
                self.on_summary(result)
            except Exception:   # noqa: BLE001 — il reporting non è critico
                pass
