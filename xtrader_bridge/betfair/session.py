"""Sessione Betfair — il sessionToken vive **solo in RAM** (issue #86 PR-P2).

Regola assoluta: il `sessionToken` ottenuto al login Betfair.it **non va mai
scritto su disco** (né config, né log, né cache). Questo modulo lo custodisce in
memoria e basta: nessuna operazione di I/O su file, qui dentro.

In più, ogni token impostato viene **registrato** nel redattore globale dei log
(`log_safety.register_secret`) così, se per errore finisse in un messaggio di log,
verrebbe mascherato; al `clear()` (logout) viene de-registrato. `__repr__`/`__str__`
non espongono mai il token: mostrano solo se la sessione è attiva.
"""

from . import log_safety


class BetfairSession:
    """Custode in-RAM del sessionToken Betfair. Nessuna persistenza su disco."""

    __slots__ = ("_token",)

    def __init__(self):
        self._token = None

    @property
    def token(self):
        """Il sessionToken corrente, o ``None`` se non loggati. Da usare solo per
        comporre gli header della richiesta, mai per loggare/persistere."""
        return self._token

    @property
    def is_logged_in(self) -> bool:
        """``True`` se è presente un sessionToken (login attivo)."""
        return bool(self._token)

    def set_token(self, token) -> None:
        """Imposta il sessionToken (in RAM) e lo registra per la redazione dei log.

        Un token vuoto/``None`` equivale a non loggati (come `clear`)."""
        if not token:
            self.clear()
            return
        self._token = str(token)
        log_safety.register_secret(self._token)

    def clear(self) -> None:
        """Cancella il sessionToken (logout): lo de-registra dai log e azzera la RAM.
        Idempotente: chiamarlo senza sessione attiva non fa nulla di dannoso."""
        if self._token:
            log_safety.unregister_secret(self._token)
        self._token = None

    def __repr__(self) -> str:
        return f"<BetfairSession logged_in={self.is_logged_in}>"

    __str__ = __repr__
