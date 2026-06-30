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

# Codici di errore APING dell'Exchange che indicano un sessionToken SCADUTO o INVALIDO
# (issue #184 LOW). Quando l'Exchange ne restituisce uno, il token in RAM è ormai inutile:
# la sessione va pulita così `is_logged_in` torna `False` e la GUI invita a riloggarsi,
# invece di restare in uno stato "fantasma" (connesso a vista, ma ogni sync fallisce).
SESSION_EXPIRED_ERROR_CODES = frozenset({
    "INVALID_SESSION_INFORMATION",
    "INVALID_SESSION_TOKEN",
    "NO_SESSION",
    "SESSION_EXPIRED",
})


def is_session_expired_error(error_code) -> bool:
    """``True`` se `error_code` (codice APING Betfair) indica una sessione scaduta/invalida.

    Tollerante: confronto case-insensitive senza spazi; ``None``/vuoto/non-stringa → ``False``
    (un errore generico — es. ``TOO_MUCH_DATA`` — NON deve sloggare l'utente)."""
    if not error_code:
        return False
    return str(error_code).strip().upper() in SESSION_EXPIRED_ERROR_CODES


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

        De-registra **prima** il token PRECEDENTE (#166, Codex): in un re-login il vecchio token
        resterebbe altrimenti in `_secret_literals` per sempre (il `clear` futuro de-registrerebbe
        solo il NUOVO), facendo crescere il registro dei segreti con valori ormai morti.

        Un token vuoto/``None`` equivale a non loggati (come `clear`)."""
        if not token:
            self.clear()
            return
        new = str(token)
        prev = self._token
        if prev is not None and prev != new:
            log_safety.unregister_secret(prev)   # il vecchio token non serve più: de-registralo
        self._token = new
        log_safety.register_secret(new)

    def clear(self) -> None:
        """Cancella il sessionToken (logout): lo de-registra dai log e azzera la RAM.
        Idempotente: chiamarlo senza sessione attiva non fa nulla di dannoso."""
        if self._token:
            log_safety.unregister_secret(self._token)
        self._token = None

    def clear_if_expired(self, error_code) -> bool:
        """Se `error_code` indica una sessione scaduta/invalida (vedi
        `SESSION_EXPIRED_ERROR_CODES`), esegue il `clear()` (logout) e ritorna ``True``;
        altrimenti non tocca nulla e ritorna ``False``. Idempotente.

        Lo chiama il codice che osserva un errore dell'Exchange (es. la sync del
        palinsesto) per non restare loggati con un token morto: dopo il `clear`,
        `is_logged_in` è ``False`` e la GUI torna 'disconnesso' (#184 LOW)."""
        if is_session_expired_error(error_code):
            self.clear()
            return True
        return False

    def __repr__(self) -> str:
        return f"<BetfairSession logged_in={self.is_logged_in}>"

    __str__ = __repr__
