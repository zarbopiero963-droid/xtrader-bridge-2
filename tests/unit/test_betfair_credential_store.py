"""Test hard dello storage sicuro delle credenziali Betfair (issue #86 PR-P2).

Esercita la logica reale con un backend keyring **fake** iniettato (offline,
deterministico): salvataggio, ricarica con campi mascherati, cancellazione, e il
caso "backend assente" → fail-safe senza crash. Nessun segreto reale nei test.
"""

import pytest

from xtrader_bridge import token_store
from xtrader_bridge.betfair import credential_store as cs
from xtrader_bridge.betfair import log_safety


class FakeKeyring:
    """Keyring in memoria che imita l'API set/get/delete_password di `keyring`.

    `fail_delete`: insieme di account il cui `delete_password` solleva e **lascia la
    voce** (simula un errore reale del backend: la cancellazione non avviene)."""

    def __init__(self, fail_delete=None):
        self.store = {}
        self.fail_delete = set(fail_delete or ())

    def set_password(self, service, account, password):
        self.store[(service, account)] = password

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
        if account in self.fail_delete:
            raise RuntimeError("delete fallita (backend, simulato)")  # voce resta
        if (service, account) not in self.store:
            raise KeyError("voce inesistente")
        del self.store[(service, account)]


@pytest.fixture(autouse=True)
def _clean_registry():
    log_safety.clear_secrets()
    yield
    log_safety.clear_secrets()


def _use(monkeypatch, fake):
    # credential_store legge il keyring tramite token_store._keyring.
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)


def _sample():
    return cs.BetfairCredentials(
        app_key="DelayedAppKey123", username="utenteBetfair",
        password="PasswordSegreta!", cert_path="/c/cert.crt", key_path="/c/cert.key")


# ── round-trip salvataggio/caricamento ────────────────────────────────────────

def test_save_e_load_round_trip(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    assert cs.save_credentials(_sample()) is True
    loaded = cs.load_credentials()
    assert loaded == _sample()
    # i segreti sono davvero nel keyring sotto account prefissati
    assert fake.store[(cs.SERVICE, "betfair_app_key")] == "DelayedAppKey123"
    assert fake.store[(cs.SERVICE, "betfair_password")] == "PasswordSegreta!"


def test_secret_salvati_registrati_per_redazione(monkeypatch):
    _use(monkeypatch, FakeKeyring())
    cs.save_credentials(_sample())
    # App key e password non devono comparire in chiaro nei log
    assert "DelayedAppKey123" not in log_safety.redact("dbg DelayedAppKey123")
    assert "PasswordSegreta!" not in log_safety.redact("dbg PasswordSegreta!")


# ── riapertura con campi mascherati ───────────────────────────────────────────

def test_masked_nasconde_i_segreti_mostra_i_path(monkeypatch):
    _use(monkeypatch, FakeKeyring())
    cs.save_credentials(_sample())
    view = cs.masked(cs.load_credentials())
    assert view["app_key"] == "••••••"
    assert view["username"] == "••••••"
    assert view["password"] == "••••••"
    # i percorsi file sono mostrati in chiaro (per far vedere quale file è scelto)
    assert view["cert_path"] == "/c/cert.crt"
    assert view["key_path"] == "/c/cert.key"


def test_masked_campo_assente_e_vuoto(monkeypatch):
    _use(monkeypatch, FakeKeyring())
    view = cs.masked(cs.BetfairCredentials())
    assert view["app_key"] == ""        # niente maschera se non c'è nulla
    assert view["cert_path"] == ""


# ── cancellazione e svuotamento campo ─────────────────────────────────────────

def test_delete_rimuove_tutte_le_voci(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    cs.save_credentials(_sample())
    assert cs.delete_credentials() is True
    assert cs.load_credentials() == cs.BetfairCredentials()
    assert fake.store == {}


def test_campo_svuotato_viene_cancellato_dal_keyring(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    cs.save_credentials(_sample())
    # nuovo save con password vuota → la voce password deve sparire
    creds = _sample()
    creds.password = ""
    assert cs.save_credentials(creds) is True
    assert (cs.SERVICE, "betfair_password") not in fake.store
    assert (cs.SERVICE, "betfair_app_key") in fake.store     # gli altri restano


# ── cancellazione fallita NON deve sembrare riuscita (Codex P2) ───────────────

def test_delete_fallita_ritorna_false_e_lascia_la_voce(monkeypatch):
    # Il backend fallisce la delete dell'app_key e la voce resta memorizzata.
    fake = FakeKeyring(fail_delete={"betfair_app_key"})
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    cs.save_credentials(_sample())
    assert cs.delete_credentials() is False               # non dichiara successo
    # il segreto è ancora lì: la GUI deve segnalare il fallimento
    assert fake.store.get((cs.SERVICE, "betfair_app_key")) == "DelayedAppKey123"


def test_save_con_clear_fallito_ritorna_false(monkeypatch):
    # L'utente svuota la password ma la delete del backend fallisce: il vecchio
    # segreto resta → il save deve risultare FALLITO, non riuscito.
    fake = FakeKeyring(fail_delete={"betfair_password"})
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    cs.save_credentials(_sample())
    creds = _sample()
    creds.password = ""                                   # clear del campo password
    assert cs.save_credentials(creds) is False
    # la vecchia password è ancora memorizzata (clear non avvenuto)
    assert fake.store.get((cs.SERVICE, "betfair_password")) == "PasswordSegreta!"


def test_delete_di_voce_assente_e_successo(monkeypatch):
    # Cancellare quando non c'è nulla NON è un errore: ritorna True (niente da fare).
    fake = FakeKeyring()
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    assert cs.delete_credentials() is True


# ── fail-safe: backend keyring assente ────────────────────────────────────────

def test_backend_assente_non_crasha(monkeypatch):
    monkeypatch.setattr(token_store, "_keyring", lambda: None)
    assert cs.available() is False
    assert cs.save_credentials(_sample()) is False
    assert cs.delete_credentials() is False
    assert cs.load_credentials() == cs.BetfairCredentials()


# ── #166: repr SAFE (mai segreti in chiaro) ───────────────────────────────────

def test_repr_non_espone_i_segreti():
    """#166 (Codex): `repr(BetfairCredentials(...))` non deve rivelare App Key/username/password.
    Fail-first: con il repr generato dal dataclass i valori segreti comparivano in chiaro."""
    creds = _sample()
    r = repr(creds)
    assert "DelayedAppKey123" not in r
    assert "utenteBetfair" not in r
    assert "PasswordSegreta!" not in r
    # i segreti presenti sono mostrati mascherati, i percorsi file in chiaro.
    assert cs.MASK in r
    assert "/c/cert.crt" in r and "/c/cert.key" in r
    # str() (che ricade su __repr__ per un dataclass) è altrettanto safe.
    assert "PasswordSegreta!" not in str(creds)


def test_repr_campi_segreti_vuoti_non_mascherati():
    # Un segreto ASSENTE non mostra la maschera (niente falso "presente").
    creds = cs.BetfairCredentials(cert_path="/c/x.crt")
    r = repr(creds)
    assert "app_key=''" in r and cs.MASK not in r
    assert "/c/x.crt" in r


# ── #166: il valore salvato è ESATTO (niente strip che altera la password) ─────

def test_save_preserva_il_valore_esatto_con_spazi(monkeypatch):
    """#166 (Codex): una password con spazi iniziali/finali intenzionali deve essere salvata
    INALTERATA. Fail-first: `save_credentials` applicava `.strip()` al valore scritto."""
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    creds = _sample()
    creds.password = "  pw con spazi  "                     # spazi intenzionali
    assert cs.save_credentials(creds) is True
    # il keyring contiene il valore ESATTO, non strippato
    assert fake.store[(cs.SERVICE, "betfair_password")] == "  pw con spazi  "
    # ricaricata, la password è identica (round-trip senza alterazioni)
    assert cs.load_credentials().password == "  pw con spazi  "
    # il valore esatto (con spazi) è registrato per la redazione log
    assert "  pw con spazi  " not in log_safety.redact("dbg   pw con spazi  ")


def test_save_campo_di_soli_spazi_e_trattato_come_vuoto(monkeypatch):
    # Un campo di SOLI spazi non è una credenziale: è trattato come vuoto (voce cancellata),
    # coerente con `is_complete`/`masked` che usano `.strip()` per decidere la presenza.
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    cs.save_credentials(_sample())
    creds = _sample()
    creds.password = "   "                                  # solo spazi → vuoto
    assert cs.save_credentials(creds) is True
    assert (cs.SERVICE, "betfair_password") not in fake.store


# ── completezza ───────────────────────────────────────────────────────────────

def test_is_complete():
    assert _sample().is_complete() is True
    incompleto = _sample()
    incompleto.key_path = ""
    assert incompleto.is_complete() is False
