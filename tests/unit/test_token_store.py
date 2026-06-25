"""Test del modulo `xtrader_bridge.token_store` (storage sicuro del bot token).

Esercitano la logica reale con un backend keyring **fake** iniettato (deterministico,
offline): non serve `keyring` installato né un keyring di sistema reale. Coprono il
round-trip, il caso "backend assente" e il caso "backend che solleva" → fallback.
"""

from xtrader_bridge import token_store as ts


class FakeKeyring:
    """Keyring in memoria che imita l'API `set/get/delete_password` di `keyring`."""

    def __init__(self, raise_on=None):
        self.store = {}
        self.raise_on = set(raise_on or ())

    def set_password(self, service, account, password):
        if "set" in self.raise_on:
            raise RuntimeError("backend non disponibile (simulato)")
        self.store[(service, account)] = password

    def get_password(self, service, account):
        if "get" in self.raise_on:
            raise RuntimeError("backend non disponibile (simulato)")
        return self.store.get((service, account))

    def delete_password(self, service, account):
        if "delete" in self.raise_on:
            raise RuntimeError("backend non disponibile (simulato)")
        if (service, account) not in self.store:
            raise KeyError("voce inesistente")
        del self.store[(service, account)]


def _use(monkeypatch, fake):
    monkeypatch.setattr(ts, "_keyring", lambda: fake)


def test_round_trip_save_load_delete(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    assert ts.save_token("123:SEGRETO") is True
    assert fake.store[(ts.SERVICE, ts.ACCOUNT)] == "123:SEGRETO"   # davvero nel keyring
    assert ts.load_token() == "123:SEGRETO"
    assert ts.delete_token() is True
    assert ts.load_token() is None                                 # rimosso


def test_available_true_con_backend(monkeypatch):
    _use(monkeypatch, FakeKeyring())
    assert ts.available() is True


def test_available_false_senza_libreria(monkeypatch):
    monkeypatch.setattr(ts, "_keyring", lambda: None)
    assert ts.available() is False
    assert ts.load_token() is None
    assert ts.save_token("x") is False
    assert ts.delete_token() is False


def test_available_false_se_backend_solleva(monkeypatch):
    _use(monkeypatch, FakeKeyring(raise_on={"get"}))
    assert ts.available() is False     # probe get_password solleva → non disponibile


def test_save_token_vuoto_non_salva(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    assert ts.save_token("") is False
    assert fake.store == {}            # niente voce vuota nel keyring


def test_save_token_fallisce_su_errore_backend(monkeypatch):
    _use(monkeypatch, FakeKeyring(raise_on={"set"}))
    assert ts.save_token("123:SEGRETO") is False   # errore backend → fallback al chiamante


def test_load_token_none_su_errore_backend(monkeypatch):
    _use(monkeypatch, FakeKeyring(raise_on={"get"}))
    assert ts.load_token() is None


def test_delete_token_false_se_voce_inesistente(monkeypatch):
    _use(monkeypatch, FakeKeyring())   # store vuoto → delete solleva KeyError → False
    assert ts.delete_token() is False
