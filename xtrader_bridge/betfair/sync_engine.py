"""Motore unico della sincronizzazione manuale Betfair (issue #86 PR-P7).

Orchestratore sopra `CatalogueSync` (PR-P6) che aggiunge le garanzie del «Sincronizza
ora» della GUI:

- **verifica login attivo** prima di partire (sessionToken in RAM);
- **una sola sync per volta**: un lock non bloccante BLOCCA una seconda sync se una è
  già in corso (niente run sovrapposte sullo stesso dizionario);
- **fallimenti safe**: qualunque errore (rete/catalogue/DB) è catturato e riportato in
  un `SyncResult` senza far crashare la GUI e senza esporre segreti;
- **riepilogo safe** per la GUI (sport, eventi/mercati/selezioni, record disattivati,
  errori), e registrazione della sync run (già fatta da `CatalogueSync`).

Nessuna operazione di scommessa (read-only, ereditato dal guard di `CatalogueSync`);
nessun dato Betfair esce dal PC.
"""

import threading
from dataclasses import dataclass, field

from .catalogue_client import CatalogueSync

# Stati del risultato di una sync.
OK = "OK"
FAILED = "FAILED"
BUSY = "BUSY"
NOT_LOGGED_IN = "NOT_LOGGED_IN"


@dataclass
class SyncResult:
    """Esito di una sincronizzazione, pronto per il riepilogo GUI (tutto safe)."""

    status: str
    sports: list = field(default_factory=list)
    new_events: int = 0
    new_markets: int = 0
    new_selections: int = 0
    deactivated: int = 0
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == OK


class SyncEngine:
    """Motore della sync manuale. Possiede il lock anti-sovrapposizione.

    `catalogue_sync` è iniettabile (test); se assente ne costruisce uno da `db` +
    `session` + `app_key` (transport di rete reali di `CatalogueSync`)."""

    def __init__(self, db, session, *, app_key=None, catalogue_sync=None):
        self.db = db
        self.session = session
        self._sync = catalogue_sync or CatalogueSync(db, session=session, app_key=app_key)
        self._lock = threading.Lock()

    def set_app_key(self, app_key) -> None:
        """Imposta la Delayed App Key da usare per la sync (es. dopo un login con
        credenziali NON ancora salvate, così la sync non dipende dal keyring)."""
        self._sync.app_key = app_key

    def reserve(self, blocking: bool = False) -> bool:
        """Prenota il lock della sync PRIMA del ciclo (auto login→sync→logout), così
        un percorso che muta la sessione condivisa non parte mentre un'altra sync è in
        corso (Codex). Ritorna `True` se prenotato. Va rilasciato con `release()`; la
        `run(..., locked=True)` non riacquisisce il lock già prenotato."""
        return self._lock.acquire(blocking=blocking)

    def release(self) -> None:
        """Rilascia il lock prenotato con `reserve()`."""
        self._lock.release()

    @property
    def is_syncing(self) -> bool:
        """`True` se una sync è in corso (lock preso)."""
        if self._lock.acquire(blocking=False):
            self._lock.release()
            return False
        return True

    def run(self, sports, *, locked: bool = False) -> SyncResult:
        """Esegue una sync manuale e ritorna un `SyncResult` safe.

        - login non attivo → `NOT_LOGGED_IN` (non parte);
        - una sync già in corso → `BUSY` (non parte una seconda);
        - errore durante la sync → `FAILED` con messaggio safe (solo tipo errore);
        - altrimenti `OK` con i conteggi (variazione dei record attivi + disattivati).

        `locked=True`: il chiamante ha già prenotato il lock con `reserve()` (auto-sync),
        quindi `run` NON lo riacquisisce/rilascia."""
        if not (self.session and self.session.is_logged_in):
            return SyncResult(status=NOT_LOGGED_IN,
                              errors=["Login Betfair non attivo: accedi prima di sincronizzare."])

        acquired = False
        if not locked:
            if not self._lock.acquire(blocking=False):
                return SyncResult(status=BUSY,
                                  errors=["Sincronizzazione già in corso: attendi il termine."])
            acquired = True
        try:
            # Anche le letture dei conteggi (count_active) devono stare nel percorso
            # safe: se il DB è chiuso/locked NON deve crashare la GUI (CodeRabbit/Codex).
            try:
                before = self._active_counts()
                summary = self._sync.sync(sports)
                after = self._active_counts()
            except Exception as ex:   # noqa: BLE001 — fallimento safe, niente crash/segreti
                return SyncResult(status=FAILED,
                                  errors=[f"Sync fallita ({type(ex).__name__})."])
            # Tutti i "nuovi" sono variazioni dei record ATTIVI (before→after), così
            # una seconda sync identica riporta +0 ovunque (coerenza, CodeRabbit):
            # `summary["selections"]` è il totale upsertato nella run, non i nuovi.
            return SyncResult(
                status=OK,
                sports=list(summary.get("sports", [])),
                new_events=max(0, after["events"] - before["events"]),
                new_markets=max(0, after["markets"] - before["markets"]),
                new_selections=max(0, after["selections"] - before["selections"]),
                deactivated=int(summary.get("deactivated", 0)),
            )
        finally:
            if acquired:
                self._lock.release()

    def _active_counts(self) -> dict:
        return {
            "events": self.db.count_active("betfair_events"),
            "markets": self.db.count_active("betfair_markets"),
            "selections": self.db.count_active("betfair_selections"),
        }
