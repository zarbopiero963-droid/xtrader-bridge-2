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

def _login_ok(_c):
    return {"loginStatus": "SUCCESS", "sessionToken": "tok"}


def test_logout_pulisce_il_token(tmp_path):
    sess = BetfairSession()
    seen = []
    client = BetfairAuthClient(session=sess, transport=_login_ok,
                               logout_transport=lambda t, k: seen.append((t, k)) or {
                                   "status": "SUCCESS"})
    client.login(_creds(tmp_path))
    assert client.is_logged_in is True
    client.logout()
    assert client.is_logged_in is False
    assert sess.token is None
    # idempotente: una seconda logout senza sessione NON richiama il transport server-side
    client.logout()
    assert client.is_logged_in is False
    assert len(seen) == 1


def test_logout_invalida_la_sessione_lato_server(tmp_path):
    """#168 (Codex P2): il logout deve invalidare la sessione LATO SERVER (POST col
    sessionToken in `X-Authentication` e l'App Key in `X-Application`) PRIMA del clear locale,
    così la sessione non resta valida sul server fino alla scadenza.

    Fail-first: sul vecchio `logout()` (solo `session.clear()`) il transport server-side NON
    veniva mai chiamato."""
    calls = []
    client = BetfairAuthClient(session=BetfairSession(), transport=_login_ok,
                               logout_transport=lambda token, app_key: calls.append(
                                   {"token": token, "app_key": app_key}) or {"status": "SUCCESS"})
    client.login(_creds(tmp_path))
    client.logout()
    assert len(calls) == 1                          # il logout server-side è stato chiamato
    assert calls[0]["token"] == "tok"               # col sessionToken corrente
    assert calls[0]["app_key"] == "DelayedKey"      # e l'App Key dell'ultimo login
    assert client.is_logged_in is False             # poi il clear locale


def test_logout_server_side_fallito_pulisce_comunque_il_token(tmp_path, caplog):
    """Best-effort: un logout server-side che SOLLEVA (rete/timeout) non deve impedire il
    clear locale né propagare l'eccezione (la GUI deve risultare disconnessa lo stesso). E il
    log NON deve contenere né il token né il messaggio grezzo dell'eccezione (solo il TIPO)."""
    def _boom(token, app_key):
        raise RuntimeError("connessione fallita " + token)   # incorpora il token!

    sess = BetfairSession()
    client = BetfairAuthClient(session=sess, transport=_login_ok, logout_transport=_boom)
    client.login(_creds(tmp_path))
    with caplog.at_level("WARNING"):
        client.logout()                             # non solleva
    assert client.is_logged_in is False
    assert sess.token is None
    assert "tok" not in caplog.text                 # il token NON finisce nel log
    assert "connessione fallita" not in caplog.text # né il messaggio grezzo dell'eccezione


def test_logout_status_non_success_non_logga_la_response(tmp_path, caplog):
    """Ramo `status != SUCCESS`: il clear locale avviene comunque e la RESPONSE (che può
    riecheggiare il token o portare un body) NON viene loggata — solo lo `status` (codice safe)."""
    def _fail(_token, _app_key):
        return {"status": "FAIL", "echo": "tok", "detail": "response body leaked"}

    sess = BetfairSession()
    client = BetfairAuthClient(session=sess, transport=_login_ok, logout_transport=_fail)
    client.login(_creds(tmp_path))
    with caplog.at_level("WARNING"):
        client.logout()
    assert client.is_logged_in is False
    assert sess.token is None
    assert "tok" not in caplog.text
    assert "response body leaked" not in caplog.text


def test_logout_risposta_non_dict_pulisce_comunque_il_token(tmp_path, caplog):
    """Resilienza (CodeRabbit): se il transport ritorna un JSON valido ma NON oggetto (lista/
    stringa, es. proxy malformato), il clear locale deve avvenire COMUNQUE (best-effort), senza
    che `.get` sollevi e salti la pulizia. E il warning del ramo non-dict NON deve loggare il
    payload grezzo (che potrebbe portare token/body sensibili) — solo lo `status` generico.

    Fail-first: col vecchio `(data or {}).get(...)` un payload truthy non-dict sollevava
    AttributeError e la sessione restava 'loggata' (token non cancellato)."""
    sess = BetfairSession()
    client = BetfairAuthClient(
        session=sess, transport=_login_ok,
        logout_transport=lambda t, k: ["tok", "response body leaked"])  # marker token/body
    client.login(_creds(tmp_path))
    with caplog.at_level("WARNING"):
        client.logout()                             # non solleva
    assert client.is_logged_in is False
    assert sess.token is None
    assert "tok" not in caplog.text                 # il payload grezzo NON finisce nel warning
    assert "response body leaked" not in caplog.text


def test_logout_senza_login_non_chiama_il_server(tmp_path):
    """Senza un login precedente (nessun token / App Key in RAM) il logout resta locale e
    non tenta alcuna chiamata server-side (niente token da invalidare)."""
    calls = []
    client = BetfairAuthClient(session=BetfairSession(),
                               logout_transport=lambda t, k: calls.append(1) or {"status": "SUCCESS"})
    client.logout()
    assert calls == []
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


def test_logout_non_cancella_un_token_piu_recente(tmp_path):
    """Race (Codex P2): se durante la POST di logout un altro path fa un re-login sulla sessione
    CONDIVISA (token cambiato), il clear locale NON deve cancellare il token NUOVO — altrimenti
    una sessione fresca verrebbe sloggata silenziosamente.

    Fail-first: col vecchio `self.session.clear()` incondizionato il token nuovo veniva cancellato."""
    sess = BetfairSession()

    def _slow_logout(token, app_key):
        # Simula un re-login concorrente avvenuto MENTRE la POST di logout era in volo.
        sess.set_token("NEW-TOKEN")
        return {"status": "SUCCESS"}

    creds = _creds(tmp_path)
    client = BetfairAuthClient(session=sess, transport=_login_ok, logout_transport=_slow_logout)
    client.login(creds)                             # token "tok"
    client.logout()
    assert sess.token == "NEW-TOKEN"                # il token PIÙ RECENTE non è stato cancellato
    assert client.is_logged_in is True
    # E nemmeno l'App Key va azzerata se il clear NON è avvenuto (token cambiato): un logout
    # successivo deve poter ancora invalidare lato server (CodeRabbit #262).
    assert client._app_key == creds.app_key.strip()


def test_default_logout_transport_usa_context_tls_esplicito(monkeypatch):
    """Sicurezza TLS (Codex P2): il transport reale di logout deve passare un `ssl.SSLContext`
    ESPLICITO a `urlopen` (come il login), non affidarsi al default globale di processo (che un
    ambiente potrebbe aver indebolito) mentre porta credenziali.

    Fail-first: senza `context=...` il kwarg catturato sarebbe None."""
    import ssl
    import urllib.request

    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"status": "SUCCESS"}'

    def _fake_urlopen(req, *a, **k):
        captured["context"] = k.get("context")
        captured["timeout"] = k.get("timeout")
        captured["url"] = req.full_url
        captured["x_auth"] = req.headers.get("X-authentication")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    data = auth_client._default_logout_transport("tok-SECRET", "DelayedKey")
    assert isinstance(captured["context"], ssl.SSLContext)   # context TLS ESPLICITO
    assert captured["timeout"] == auth_client.LOGOUT_TIMEOUT  # timeout passato a urlopen
    assert captured["url"] == auth_client.LOGOUT_URL
    assert captured["x_auth"] == "tok-SECRET"               # token nell'header, non in URL/body
    assert data == {"status": "SUCCESS"}


def test_session_clear_if_token_e_atomico_sul_match(tmp_path):
    """#262 (Codex/CodeRabbit): `BetfairSession.clear_if_token` cancella SOLO se il token corrente
    coincide; se è cambiato (login concorrente) NON tocca la sessione nuova. È il primitivo atomico
    (sotto lock) che `logout` usa per non sloggare un token più recente."""
    sess = BetfairSession()
    sess.set_token("A")
    assert sess.clear_if_token("B") is False        # token diverso → non cancella
    assert sess.token == "A"
    assert sess.clear_if_token("A") is True          # token coincide → cancella
    assert sess.token is None
    assert sess.clear_if_token(None) is True         # idempotente: None == None → no-op "riuscito"
