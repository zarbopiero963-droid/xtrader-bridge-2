"""Test hard del client di autenticazione Betfair.it (issue #86 PR-P4).

Esercita la logica reale con un trasporto HTTP **finto** iniettato (offline,
deterministico): login OK, login fallito, certificato mancante, logout, e in
particolare che il sessionToken resti **solo in RAM** (mai persistito) e non finisca
nei log. Nessun segreto reale, nessuna chiamata di rete, nessun XTrader.
"""

import pytest

from xtrader_bridge import token_store
from xtrader_bridge.betfair import auth_client, credential_store as cs
from xtrader_bridge.betfair import log_safety
from xtrader_bridge.betfair.auth_client import (
    BetfairAuthClient,
    CertificateError,
    LoginError,
)
from xtrader_bridge.betfair.credential_store import BetfairCredentials
from xtrader_bridge.betfair.session import BetfairSession


@pytest.fixture(autouse=True)
def _clean():
    log_safety.clear_secrets()
    yield
    log_safety.clear_secrets()


def _creds(tmp_path, complete=True):
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    cert.write_text("-----CERT-----", encoding="utf-8")
    key.write_text("-----KEY-----", encoding="utf-8")
    return BetfairCredentials(
        app_key="DelayedKey", username="utente", password="pw",
        cert_path=str(cert) if complete else "",
        key_path=str(key) if complete else "")


# ── login OK ──────────────────────────────────────────────────────────────────

def test_login_ok_mette_il_token_in_ram(tmp_path):
    seen = {}

    def _ok(creds):
        seen["creds"] = creds          # il trasporto riceve le credenziali REALI
        return {"loginStatus": "SUCCESS", "sessionToken": "tok-RAM-123"}

    sess = BetfairSession()
    client = BetfairAuthClient(session=sess, transport=_ok)
    token = client.login(_creds(tmp_path))
    assert token == "tok-RAM-123"
    assert sess.is_logged_in is True
    assert sess.token == "tok-RAM-123"
    # il trasporto ha ricevuto cert/app key reali (wiring corretto)
    assert seen["creds"].app_key == "DelayedKey"
    # token registrato per la redazione: non comparirà nei log
    assert "tok-RAM-123" not in log_safety.redact("dbg tok-RAM-123")


# ── login fallito ─────────────────────────────────────────────────────────────

def test_login_fallito_status_non_success(tmp_path):
    def _fail(creds):
        return {"loginStatus": "INVALID_USERNAME_OR_PASSWORD", "sessionToken": ""}

    client = BetfairAuthClient(session=BetfairSession(), transport=_fail)
    with pytest.raises(LoginError) as ei:
        client.login(_creds(tmp_path))
    assert "INVALID_USERNAME_OR_PASSWORD" in str(ei.value)
    assert client.is_logged_in is False


def test_login_errore_di_rete_e_safe(tmp_path):
    def _boom(creds):
        raise RuntimeError("connessione fallita verso " + creds.password)  # contiene la pw!

    client = BetfairAuthClient(session=BetfairSession(), transport=_boom)
    with pytest.raises(LoginError) as ei:
        client.login(_creds(tmp_path))
    # messaggio safe: solo il TIPO dell'errore, MAI il segreto incorporato
    assert "pw" not in str(ei.value)
    assert "RuntimeError" in str(ei.value)
    assert client.is_logged_in is False
    # #168 (Codex): la causa grezza è SOPPRESSA (`from None`) — un traceback / exc_info non
    # può ri-stampare l'eccezione originale del trasporto (che incorpora la password).
    assert ei.value.__cause__ is None
    assert ei.value.__suppress_context__ is True


def test_login_credenziali_incomplete(tmp_path):
    creds = _creds(tmp_path)
    creds.app_key = ""
    client = BetfairAuthClient(session=BetfairSession(), transport=lambda c: {})
    with pytest.raises(LoginError):
        client.login(creds)


# ── certificato mancante ──────────────────────────────────────────────────────

def test_login_cert_non_configurato(tmp_path):
    client = BetfairAuthClient(session=BetfairSession(), transport=lambda c: {})
    with pytest.raises(CertificateError):
        client.login(_creds(tmp_path, complete=False))


def test_login_file_cert_inesistente(tmp_path):
    creds = _creds(tmp_path)
    creds.cert_path = str(tmp_path / "manca.crt")
    client = BetfairAuthClient(session=BetfairSession(), transport=lambda c: {})
    with pytest.raises(CertificateError):
        client.login(creds)


# ── logout ────────────────────────────────────────────────────────────────────

def test_logout_pulisce_il_token(tmp_path):
    sess = BetfairSession()
    client = BetfairAuthClient(session=sess, transport=lambda c: {
        "loginStatus": "SUCCESS", "sessionToken": "tok"})
    client.login(_creds(tmp_path))
    assert client.is_logged_in is True
    client.logout()
    assert client.is_logged_in is False
    assert sess.token is None
    # idempotente
    client.logout()
    assert client.is_logged_in is False


# ── token mai persistito su disco (keyring) ──────────────────────────────────

def test_token_non_salvato_nel_keyring(tmp_path, monkeypatch):
    # keyring fake condiviso: dopo il login NON deve esistere alcuna voce sessione.
    class FakeKeyring:
        def __init__(self):
            self.store = {}

        def set_password(self, s, a, p):
            self.store[(s, a)] = p

        def get_password(self, s, a):
            return self.store.get((s, a))

        def delete_password(self, s, a):
            self.store.pop((s, a), None)

    fake = FakeKeyring()
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    client = BetfairAuthClient(session=BetfairSession(), transport=lambda c: {
        "loginStatus": "SUCCESS", "sessionToken": "tok-secret"})
    client.login(_creds(tmp_path))
    # nessuna chiave del keyring contiene il token o assomiglia a una "sessione"
    assert all("session" not in acct for (_svc, acct) in fake.store)
    assert "tok-secret" not in fake.store.values()


# ── login carica le credenziali dal keyring se non passate ────────────────────

def test_login_usa_credenziali_dal_keyring(tmp_path, monkeypatch):
    class FakeKeyring:
        def __init__(self):
            self.store = {}

        def set_password(self, s, a, p):
            self.store[(s, a)] = p

        def get_password(self, s, a):
            return self.store.get((s, a))

        def delete_password(self, s, a):
            self.store.pop((s, a), None)

    fake = FakeKeyring()
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    cs.save_credentials(_creds(tmp_path))     # salva nel keyring fake
    got = {}
    client = BetfairAuthClient(session=BetfairSession(),
                               transport=lambda c: got.update(app_key=c.app_key) or {
                                   "loginStatus": "SUCCESS", "sessionToken": "t"})
    client.login()                            # nessun creds passato → carica dal keyring
    assert got["app_key"] == "DelayedKey"
