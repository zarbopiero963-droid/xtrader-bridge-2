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
SECRET_FIELDS = ("app_key", "username", "password")
PATH_FIELDS = ("cert_path", "key_path")

# Sentinella di mascheramento mostrata in GUI per un segreto presente. È pubblica
# così controller/GUI possono riconoscerla come "campo non modificato" (non come
# valore reale da salvare/loggare).
MASK = "••••••"


@dataclass(repr=False)
class BetfairCredentials:
    """Credenziali Betfair locali. I tre campi segreti + i due percorsi file.

    `app_key` è la **Delayed** App Key (read-only). Nessun campo è obbligatorio a
    livello di storage: la validazione di completezza è del chiamante (GUI/auth).

    Il `__repr__` è **safe** (`repr=False` sul dataclass + override sotto): mai i valori segreti
    in chiaro, così `repr()`/`logger.debug(creds)`/un traceback non rivelano App Key/username/
    password (#166)."""

    app_key: str = ""
    username: str = ""
    password: str = ""
    cert_path: str = ""
    key_path: str = ""

    def is_complete(self) -> bool:
        """``True`` se tutti i campi necessari al login con certificato sono presenti."""
        return all(getattr(self, f).strip() for f in
                   (*SECRET_FIELDS, *PATH_FIELDS))

    def __repr__(self) -> str:
        """Repr SAFE: i campi segreti sono mostrati mascherati (``••••••`` se presenti, vuoto se
        assenti), i percorsi file in chiaro. Mai il valore reale di App Key/username/password —
        è la stessa prudenza di `masked()`, applicata a `repr()`/`str()` (#166, Codex)."""
        parts = []
        for f in FIELDS:
            val = getattr(self, f) or ""
            shown = (MASK if val.strip() else "") if f in SECRET_FIELDS else val
            parts.append(f"{f}={shown!r}")
        return f"BetfairCredentials({', '.join(parts)})"


FIELDS = tuple(f.name for f in _dc_fields(BetfairCredentials))


def _account(field: str) -> str:
    return _ACCOUNT_PREFIX + field


def _delete_one(kr, account) -> bool:
    """Cancella una voce e VERIFICA l'esito leggendola di nuovo.

    `keyring.delete_password` solleva sia quando la voce non esiste (caso benigno:
    niente da cancellare) sia su un errore reale del backend (permessi/transitorio):
    ingoiare l'eccezione e dichiarare successo è il bug segnalato da Codex. Qui, dopo
    il tentativo, si ricontrolla con `get_password`: la voce è considerata cancellata
    **solo** se non è più presente. Se è ancora lì (o non è verificabile) → `False`."""
    try:
        kr.delete_password(SERVICE, account)
    except Exception:
        pass  # potrebbe essere "voce inesistente" (ok) o un errore reale: si verifica
    try:
        return kr.get_password(SERVICE, account) in (None, "")
    except Exception:
        return False  # impossibile verificare → fail-safe: non dichiarare cancellato


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
        raw = getattr(creds, field) or ""
        acct = _account(field)
        # `.strip()` solo per DECIDERE se il campo è vuoto: il valore SCRITTO è quello ESATTO
        # (con eventuali spazi iniziali/finali intenzionali in una password). Strippare il valore
        # salvato altererebbe la credenziale e farebbe fallire il login (Codex #166).
        if raw.strip():
            try:
                kr.set_password(SERVICE, acct, raw)
                if field in SECRET_FIELDS:
                    log_safety.register_secret(raw)
            except Exception:
                ok = False
        else:
            # Svuotare un campo deve cancellarlo davvero: una cancellazione fallita
            # (vecchio segreto ancora presente) è un FALLIMENTO del save, non un
            # successo silenzioso (Codex) — altrimenti il segreto resterebbe.
            if not _delete_one(kr, acct):
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
            if field in SECRET_FIELDS:
                log_safety.register_secret(value)
    return creds


def delete_credentials() -> bool:
    """Elimina tutte le credenziali Betfair dal keyring. Ritorna `True` solo se,
    dopo l'operazione, **nessuna** voce è più presente (verifica per ri-lettura,
    vedi `_delete_one`). Se il backend manca o una voce resta memorizzata (errore
    reale), ritorna `False`: la GUI deve segnalare il fallimento e non far credere
    che i segreti siano stati rimossi (Codex)."""
    kr = _kr()
    if kr is None:
        return False
    ok = True
    for field in FIELDS:
        if not _delete_one(kr, _account(field)):
            ok = False
    return ok


def masked(creds: BetfairCredentials) -> dict:
    """Vista per la GUI: i campi segreti presenti sono mostrati mascherati
    (``••••••``), i percorsi file in chiaro, i campi vuoti come stringa vuota.

    Così alla riapertura del programma l'utente vede che le credenziali ci sono,
    senza che il valore reale venga mai rimostrato."""
    out = {}
    for field in FIELDS:
        value = getattr(creds, field) or ""
        if field in SECRET_FIELDS:
            out[field] = MASK if value.strip() else ""
        else:
            out[field] = value
    return out
