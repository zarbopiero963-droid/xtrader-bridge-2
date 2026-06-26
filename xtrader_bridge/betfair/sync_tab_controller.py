"""Controller della tab «Betfair Sync» (logica pura, testabile in CI) — issue #86 PR-P3.

Niente widget customtkinter qui: solo lo stato e le regole della tab, così il
comportamento (quali pulsanti sono attivi, salva/cancella credenziali, logout che
NON cancella le credenziali) è coperto da test reali. La parte di widget vive in
`sync_tab_gui.py` (verifica manuale su Windows).

Regole della tab (dall'issue):
- credenziali Betfair **globali locali**, non per profilo (stanno nel keyring di
  sistema via `credential_store`, non nel profilo attivo);
- «Sincronizza» è abilitato **solo dopo il login**;
- «Logout» cancella **solo la sessione**, non le credenziali salvate;
- nessuna chiamata betting (il sottosistema resta read-only, vedi `safety.py`).

Login e sync veri arrivano nelle PR successive (PR-P4 auth, PR-P6/P7 sync): qui il
controller modella lo stato e la persistenza, e la GUI ci aggancia i callback.
"""

from . import credential_store
from .credential_store import BetfairCredentials
from .session import BetfairSession

# Sport supportati dal blocco personale (ordine di visualizzazione in GUI). Fonte
# UNICA in `xtrader_bridge.sports` (riusata da parser personalizzato e catalogue
# client, PR-P9): ri-esportata qui per non spezzare l'API di questo controller.
from ..sports import SPORTS, normalize_sport

# Giorni avanti di default per lo scarico del palinsesto (campo «Giorni avanti»).
DEFAULT_DAYS_AHEAD = 3
_MAX_DAYS_AHEAD = 30


def normalize_days_ahead(value, default: int = DEFAULT_DAYS_AHEAD) -> int:
    """Normalizza il campo «Giorni avanti» a un intero in [1, 30].

    Valori non interi/negativi/zero → `default`; valori troppo grandi sono limitati
    a 30 (evita scarichi sproporzionati). `bool` non è un intero valido qui."""
    if isinstance(value, bool):
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return default
    return min(n, _MAX_DAYS_AHEAD)


class BetfairSyncController:
    """Stato e regole della tab Betfair Sync. La GUI possiede una `BetfairSession`
    (token in RAM) e delega qui persistenza e abilitazione dei pulsanti."""

    def __init__(self, session: BetfairSession = None):
        # La sessione (sessionToken in RAM) è condivisa con il resto del bridge.
        self.session = session if session is not None else BetfairSession()

    # ── credenziali (globali, locali, cifrate nel keyring) ───────────────────

    def load_masked(self) -> dict:
        """Vista mascherata delle credenziali salvate, per popolare la tab alla
        riapertura senza rimostrare i segreti."""
        return credential_store.masked(credential_store.load_credentials())

    def has_saved_credentials(self) -> bool:
        """``True`` se esiste almeno una credenziale segreta salvata."""
        creds = credential_store.load_credentials()
        return bool(creds.app_key or creds.username or creds.password)

    def resolve_credentials(self, form_creds: BetfairCredentials) -> BetfairCredentials:
        """Risolve i valori del form in credenziali REALI da salvare/usare al login.

        Un campo segreto lasciato com'era mostra la sentinella di mascheramento
        (`credential_store.MASK`): NON è il valore reale. Qui, per ogni campo segreto
        ancora uguale alla maschera, si sostituisce il valore reale salvato nel
        keyring (campo non modificato dall'utente); i campi digitati o svuotati e i
        percorsi file restano come nel form.

        Così «Accedi»/«Salva» non inviano mai la maschera al posto del segreto e un
        Salva senza ridigitare non sovrascrive il keyring con `••••••`."""
        stored = credential_store.load_credentials()
        resolved = BetfairCredentials()
        for field in credential_store.FIELDS:
            value = getattr(form_creds, field)
            if field in credential_store.SECRET_FIELDS and value == credential_store.MASK:
                value = getattr(stored, field)   # campo non modificato → valore reale
            setattr(resolved, field, value)
        return resolved

    def save_credentials(self, creds: BetfairCredentials) -> bool:
        """Salva le credenziali (delego a `credential_store`). ``True`` se riuscito.

        Il chiamante GUI passa già le credenziali risolte (vedi `resolve_credentials`)
        così un campo mascherato non sovrascrive il segreto reale."""
        return credential_store.save_credentials(creds)

    def delete_saved_credentials(self) -> bool:
        """Cancella le credenziali salvate **e** fa logout della sessione corrente
        (cancellare le credenziali implica non poter restare loggati)."""
        self.session.clear()
        return credential_store.delete_credentials()

    # ── sessione ─────────────────────────────────────────────────────────────

    def logout(self) -> None:
        """Logout: cancella **solo** la sessione (sessionToken in RAM). Le
        credenziali salvate restano intatte (regola dell'issue)."""
        self.session.clear()

    @property
    def is_logged_in(self) -> bool:
        return self.session.is_logged_in

    # ── abilitazione pulsanti ────────────────────────────────────────────────

    def button_states(self, *, credentials_complete=None,
                       sync_in_progress: bool = False) -> dict:
        """Stato di abilitazione dei pulsanti della tab.

        - `credentials_complete`: se ``None`` deriva dalla completezza delle
          credenziali **salvate**; la GUI può passare lo stato del form corrente.
        - `sync_in_progress`: se una sync è in corso, «Sincronizza» è disabilitato.

        Regole: login solo con credenziali complete e non già loggati; «Sincronizza»
        solo dopo login e con nessuna sync in corso; logout solo se loggati;
        «Cancella credenziali» solo se ci sono credenziali salvate."""
        if credentials_complete is None:
            credentials_complete = credential_store.load_credentials().is_complete()
        logged = self.is_logged_in
        return {
            "save_credentials": True,
            "login": bool(credentials_complete) and not logged,
            "sync_now": logged and not sync_in_progress,
            "logout": logged,
            "delete_credentials": self.has_saved_credentials(),
        }
