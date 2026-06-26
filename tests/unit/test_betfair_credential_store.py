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
    """Keyring in memoria che imita l'API set/get/delete_password di `keyring`."""

    def __init__(self):
        self.store = {}

    def set_password(self, service, account, password):
        self.store[(service, account)] = password

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
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


# ── fail-safe: backend keyring assente ────────────────────────────────────────

def test_backend_assente_non_crasha(monkeypatch):
    monkeypatch.setattr(token_store, "_keyring", lambda: None)
    assert cs.available() is False
    assert cs.save_credentials(_sample()) is False
    assert cs.delete_credentials() is False
    assert cs.load_credentials() == cs.BetfairCredentials()


# ── completezza ───────────────────────────────────────────────────────────────

def test_is_complete():
    assert _sample().is_complete() is True
    incompleto = _sample()
    incompleto.key_path = ""
    assert incompleto.is_complete() is False
