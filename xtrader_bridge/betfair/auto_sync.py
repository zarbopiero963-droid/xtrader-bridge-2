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
    if now.hour != normalize_hour(hour):
        return False
    return last_run_key != run_key(now, hour)


class AutoSyncScheduler:
    """Scheduler locale dell'auto-sync. Da «ticchettare» dalla GUI mentre il bridge
    è aperto (es. ogni minuto), passando l'ora corrente.

    Dipendenze iniettate (testabili offline):
    - `auth`: client con `login(creds)` / `logout()`;
    - `engine`: `SyncEngine` (espone `is_syncing` e `run(sports)`);
    - `get_config()`: ritorna `(enabled, hour, sports, creds)` correnti;
    - `is_bridge_open()`: `True` se la finestra è aperta (default: sempre);
    - `on_summary(result)`: callback opzionale per il riepilogo safe in GUI/log."""

    def __init__(self, *, auth, engine, get_config, is_bridge_open=None,
                 on_summary=None, load_state=None, save_state=None):
        self.auth = auth
        self.engine = engine
        self.get_config = get_config
        self.is_bridge_open = is_bridge_open or (lambda: True)
        self.on_summary = on_summary
        # Persistenza opzionale dell'ultima run (giorno+ora): senza, lo stato vive solo
        # in RAM e un riavvio nella stessa ora ri-eseguirebbe l'auto-sync (Codex).
        self._load_state = load_state
        self._save_state = save_state
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
        enabled, hour, sports, creds = self.get_config()
        # Check-and-set atomico: niente cicli sovrapposti (gate) + decisione pura.
        with self._gate:
            if self._running:
                return None
            if not should_run(now, enabled=enabled, hour=hour,
                              last_run_key=self._last_run_key,
                              sync_in_progress=self.engine.is_syncing):
                return None
            self._running = True
        try:
            result = self._cycle(sports, creds)
            if getattr(result, "ok", False):
                # Solo su successo: marca e persiste, così non ri-scatta oggi/ora.
                self._last_run_key = run_key(now, hour)
                if self._save_state:
                    try:
                        self._save_state(self._last_run_key)
                    except Exception:   # noqa: BLE001 — persistenza best-effort
                        pass
            return result
        finally:
            with self._gate:
                self._running = False

    def _cycle(self, sports, creds):
        """Auto login → sync → auto logout. Il logout è SEMPRE in `finally`.

        Dopo il login aggiorna la App Key del motore con quella delle credenziali
        appena usate (`set_app_key`), così la sync non invia una App Key vecchia in
        cache da un login manuale precedente (Codex)."""
        result = None
        try:
            self.auth.login(creds)
            set_app_key = getattr(self.engine, "set_app_key", None)
            if set_app_key:
                set_app_key(getattr(creds, "app_key", None))
            result = self.engine.run(sports)
        except Exception as ex:   # noqa: BLE001 — fallimento safe, niente crash/segreti
            result = SyncResult(status=FAILED,
                                errors=[f"Auto-sync fallita ({type(ex).__name__})."])
        finally:
            try:
                self.auth.logout()
            except Exception:     # noqa: BLE001 — il logout best-effort non deve propagare
                pass
        if self.on_summary:
            self.on_summary(result)
        return result
