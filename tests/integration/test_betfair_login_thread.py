"""Test hard del login Betfair NON bloccante per la GUI (issue #184 H1).

Prima del fix la callback «Accedi» eseguiva `login()` (POST HTTPS, fino a ~20s) DIRETTAMENTE
nel main thread Tk → finestra congelata. Ora il login gira su un WORKER THREAD e l'esito è
marshalato con `after(0, ...)`, con un flag anti-rientro. Qui si esercitano i METODI REALI di
`App` (headless harness): `_betfair_login_work` (logica bloccante isolata, no Tk),
`_betfair_login_async` (offload su thread + flag) e `_betfair_login_done`.
"""

import threading
import types


class _FakeAuth:
    """Client di login finto: registra le chiamate; può sollevare un'eccezione."""

    def __init__(self, exc=None):
        self.exc = exc
        self.calls = []

    def login(self, creds):
        self.calls.append(creds)
        if self.exc is not None:
            raise self.exc


class _FakeEngine:
    def __init__(self):
        self.app_key = None

    def set_app_key(self, key):
        self.app_key = key


# ── _betfair_login_work: logica bloccante isolata (no Tk) ─────────────────────

def test_betfair_login_work_successo_porta_appkey_nell_engine(make_app):
    a = make_app(running=True)
    a._betfair_auth_obj = _FakeAuth()
    a._betfair_engine_obj = _FakeEngine()
    creds = types.SimpleNamespace(app_key="APPKEY")
    msg = a._betfair_login_work(creds)
    assert "riuscito" in msg.lower()
    assert a._betfair_auth_obj.calls == [creds]              # login realmente chiamato
    assert a._betfair_engine_obj.app_key == "APPKEY"         # app key del login → engine


def test_betfair_login_work_fallito_e_safe(make_app):
    from xtrader_bridge.betfair.auth_client import LoginError
    a = make_app(running=True)
    a._betfair_auth_obj = _FakeAuth(exc=LoginError("status 403"))
    a._betfair_engine_obj = _FakeEngine()
    creds = types.SimpleNamespace(app_key="SEGRETISSIMO")
    msg = a._betfair_login_work(creds)
    assert "fallito" in msg.lower()
    assert "SEGRETISSIMO" not in msg                          # nessun segreto nel messaggio


def test_betfair_login_work_engine_assente_non_crasha(make_app):
    # set_app_key che solleva (engine/DB non disponibile) non deve far fallire il login.
    a = make_app(running=True)
    a._betfair_auth_obj = _FakeAuth()

    class _BoomEngine:
        def set_app_key(self, key):
            raise RuntimeError("DB non apribile")

    a._betfair_engine_obj = _BoomEngine()
    msg = a._betfair_login_work(types.SimpleNamespace(app_key="K"))
    assert "riuscito" in msg.lower()                          # login ok comunque


# ── _betfair_login_async: offload su worker thread + anti-rientro ─────────────

def test_betfair_login_async_gira_su_worker_thread(make_app):
    a = make_app(running=True)
    main_tid = threading.get_ident()
    seen = {}

    def _fake_work(creds):
        seen["tid"] = threading.get_ident()
        return "🔵 ok"

    a._betfair_login_work = _fake_work
    a._betfair_login_async(types.SimpleNamespace(app_key="K"))
    a._betfair_login_thread.join(timeout=5)                   # deterministico

    assert seen["tid"] != main_tid                            # H1: login NON sul main thread
    assert a._betfair_login_busy is False                     # flag liberato a fine login
    assert a.logs[-1] == "🔵 ok"                              # esito marshalato e loggato


def test_betfair_login_async_non_rientrante(make_app):
    # Un login già in corso (busy) non ne avvia un secondo (equivale al bottone disabilitato).
    a = make_app(running=True)
    a._betfair_login_busy = True
    called = []
    a._betfair_login_work = lambda creds: called.append(1) or "x"
    a._betfair_login_async(types.SimpleNamespace(app_key="K"))
    assert called == []                                       # nessun secondo login parte


def test_betfair_login_done_libera_flag_e_logga(make_app):
    a = make_app(running=True)
    a._betfair_login_busy = True
    a._betfair_login_done("✅ esito")
    assert a._betfair_login_busy is False
    assert a.logs[-1] == "✅ esito"
