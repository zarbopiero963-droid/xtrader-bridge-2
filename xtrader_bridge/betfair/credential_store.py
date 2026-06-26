"""Storage locale sicuro delle credenziali Betfair (issue #86 PR-P2).

Le credenziali Betfair (Delayed App Key, username, password, percorso del
certificato e della private key) sono **dati locali e sensibili**: non vanno tenute
in chiaro nel `config.json` né uscire dal PC. Questo modulo le custodisce nel
**keyring del sistema operativo** (Windows Credential Manager, macOS Keychain,
Secret Service su Linux), con lo stesso pattern fail-safe di `token_store`:

- se un backend keyring usabile manca (CI headless, Linux senza Secret Service),
  le funzioni segnalano l'assenza tornando `False`/valori vuoti, senza crashare;
- nessun valore segreto viene mai loggato; i valori segreti caricati/salvati sono
  registrati nel redattore globale dei log (`log_safety.register_secret`).

Il `sessionToken` **non** sta qui: vive solo in RAM (vedi `session.py`).
Certificato e private key restano file su disco scelti dall'utente: qui salviamo
solo il loro **percorso** (non il contenuto), così il bridge sa dove leggerli.
"""

from dataclasses import dataclass, fields as _dc_fields

from . import log_safety
from .. import token_store

# Spazio dei nomi keyring condiviso con il resto dell'app (vedi token_store.SERVICE).
SERVICE = token_store.SERVICE

# Campi delle credenziali e relativo "account" nel keyring (prefisso betfair_).
_ACCOUNT_PREFIX = "betfair_"

# Quali campi sono SEGRETI (da mascherare in GUI e da registrare per i log) e quali
# sono semplici percorsi file (mostrabili in chiaro per far vedere quale file è scelto).
_SECRET_FIELDS = ("app_key", "username", "password")
_PATH_FIELDS = ("cert_path", "key_path")

_MASK = "••••••"


@dataclass
class BetfairCredentials:
    """Credenziali Betfair locali. I tre campi segreti + i due percorsi file.

    `app_key` è la **Delayed** App Key (read-only). Nessun campo è obbligatorio a
    livello di storage: la validazione di completezza è del chiamante (GUI/auth)."""

    app_key: str = ""
    username: str = ""
    password: str = ""
    cert_path: str = ""
    key_path: str = ""

    def is_complete(self) -> bool:
        """``True`` se tutti i campi necessari al login con certificato sono presenti."""
        return all(getattr(self, f).strip() for f in
                   (*_SECRET_FIELDS, *_PATH_FIELDS))


FIELDS = tuple(f.name for f in _dc_fields(BetfairCredentials))


def _account(field: str) -> str:
    return _ACCOUNT_PREFIX + field


def available() -> bool:
    """``True`` se esiste un backend keyring usabile (vedi `token_store.available`)."""
    return token_store.available()


def _kr():
    return token_store._keyring()


def save_credentials(creds: BetfairCredentials) -> bool:
    """Salva le credenziali nel keyring. Campi non vuoti vengono scritti, campi
    vuoti vengono rimossi (così "svuotare un campo" lo cancella davvero).

    Ritorna `True` se il backend è disponibile e tutte le operazioni riescono,
    `False` altrimenti (il chiamante può avvisare l'utente). I valori segreti
    salvati sono registrati per la redazione dei log."""
    kr = _kr()
    if kr is None:
        return False
    ok = True
    for field in FIELDS:
        value = (getattr(creds, field) or "").strip()
        acct = _account(field)
        try:
            if value:
                kr.set_password(SERVICE, acct, value)
                if field in _SECRET_FIELDS:
                    log_safety.register_secret(value)
            else:
                try:
                    kr.delete_password(SERVICE, acct)
                except Exception:
                    pass  # voce già assente: non è un errore
        except Exception:
            ok = False
    return ok


def load_credentials() -> BetfairCredentials:
    """Carica le credenziali dal keyring (campi assenti → stringa vuota). I valori
    segreti caricati sono registrati per la redazione dei log."""
    kr = _kr()
    creds = BetfairCredentials()
    if kr is None:
        return creds
    for field in FIELDS:
        try:
            value = kr.get_password(SERVICE, _account(field))
        except Exception:
            value = None
        if value:
            setattr(creds, field, value)
            if field in _SECRET_FIELDS:
                log_safety.register_secret(value)
    return creds


def delete_credentials() -> bool:
    """Elimina tutte le credenziali Betfair dal keyring (best-effort). Ritorna
    `True` se il backend è disponibile (anche se alcune voci erano già assenti)."""
    kr = _kr()
    if kr is None:
        return False
    for field in FIELDS:
        try:
            kr.delete_password(SERVICE, _account(field))
        except Exception:
            pass
    return True


def masked(creds: BetfairCredentials) -> dict:
    """Vista per la GUI: i campi segreti presenti sono mostrati mascherati
    (``••••••``), i percorsi file in chiaro, i campi vuoti come stringa vuota.

    Così alla riapertura del programma l'utente vede che le credenziali ci sono,
    senza che il valore reale venga mai rimostrato."""
    out = {}
    for field in FIELDS:
        value = getattr(creds, field) or ""
        if field in _SECRET_FIELDS:
            out[field] = _MASK if value.strip() else ""
        else:
            out[field] = value
    return out
