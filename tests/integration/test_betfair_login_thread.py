"""Test hard del login Betfair NON bloccante per la GUI (issue #184 H1 + review Codex).

Prima del fix la callback «Accedi» eseguiva `login()` (POST HTTPS, fino a ~20s) DIRETTAMENTE
nel main thread Tk → finestra congelata. Ora il login gira su un WORKER THREAD e l'esito è
marshalato con `after(0, ...)`, con: flag anti-rientro, guardia di chiusura (`_closing`) e un
**epoch** che scarta i completamenti stantii (logout/«Cancella credenziali» durante il login).
Si esercitano i METODI REALI di `App` (headless harness).
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
    a._closing = False
    a.winfo_exists = lambda: True
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
    a = make_app(running=True)
    a._betfair_login_busy = True
    called = []
    a._betfair_login_work = lambda creds: called.append(1) or "x"
    a._betfair_login_async(types.SimpleNamespace(app_key="K"))
    assert called == []                                       # nessun secondo login parte


def test_betfair_login_async_non_rientra_in_tk_a_chiusura(make_app):
    # Teardown (Codex): se l'app si sta chiudendo, il worker NON chiama `after` su una
    # root distrutta.
    a = make_app(running=True)
    a._closing = True
    after_calls = []
    a.after = lambda *x, **k: after_calls.append(x)
    a._betfair_login_work = lambda creds: "x"
    a._betfair_login_async(types.SimpleNamespace(app_key="K"))
    a._betfair_login_thread.join(timeout=5)
    assert after_calls == []                                  # niente Tk a chiusura
    assert a._betfair_login_busy is False


def test_betfair_login_async_completamento_stantio_scartato(make_app):
    # Stale completion (Codex): logout/«Cancella credenziali» durante un login lento →
    # il login in volo è stantio: scarta il token appena settato e NON riporta a «connesso».
    a = make_app(running=True)
    a._closing = False
    cleared = []
    a._betfair_session_obj = lambda: types.SimpleNamespace(clear=lambda: cleared.append(True))

    def _fake_work(creds):
        a._betfair_invalidate_login()                        # logout/delete durante il login
        return "🔵 connesso"

    a._betfair_login_work = _fake_work
    a._betfair_login_async(types.SimpleNamespace(app_key="K"))
    a._betfair_login_thread.join(timeout=5)

    assert cleared == [True]                                  # token stantio scartato
    assert a.logs == []                                       # nessun «connesso» dopo il logout
    assert a._betfair_login_busy is False


# ── _betfair_login_done: epoch + guardie root ────────────────────────────────

def test_betfair_login_done_logga_se_corrente(make_app):
    a = make_app(running=True)
    a._closing = False
    a.winfo_exists = lambda: True
    a._betfair_login_busy = True
    a._betfair_login_epoch = 5
    a._betfair_login_done("✅ esito", 5)                      # gen corrente
    assert a._betfair_login_busy is False
    assert a.logs[-1] == "✅ esito"


def test_betfair_login_done_ignora_completamento_stantio(make_app):
    a = make_app(running=True)
    a._closing = False
    a.winfo_exists = lambda: True
    a._betfair_login_epoch = 6                                # epoch avanzato (logout/delete)
    a._betfair_login_done("✅ vecchio", 5)                    # gen vecchio
    assert a.logs == []                                       # stantio: niente log


def test_betfair_login_done_ignora_root_in_chiusura(make_app):
    a = make_app(running=True)
    a._closing = True
    a._betfair_login_epoch = 1
    a._betfair_login_done("x", 1)
    assert a.logs == []                                       # root in chiusura: niente Tk


# ── invalidate / discard ─────────────────────────────────────────────────────

def test_betfair_invalidate_login_bumpa_epoch(make_app):
    a = make_app(running=True)
    e0 = a._betfair_login_epoch
    a._betfair_invalidate_login()
    assert a._betfair_login_epoch == e0 + 1


def test_betfair_discard_stale_login_pulisce_sessione(make_app):
    a = make_app(running=True)
    cleared = []
    a._betfair_session_obj = lambda: types.SimpleNamespace(clear=lambda: cleared.append(True))
    a._betfair_discard_stale_login()
    assert cleared == [True]


# ── panel: logout/delete invalidano un login in volo ─────────────────────────

def test_panel_logout_e_delete_invalidano_login():
    import pytest
    pytest.importorskip("customtkinter")   # il widget richiede la GUI (assente in locale)
    from xtrader_bridge.betfair.sync_tab_gui import BetfairSyncPanel

    p = object.__new__(BetfairSyncPanel)
    invalidated = []
    p._on_invalidate = lambda: invalidated.append(True)
    p.controller = types.SimpleNamespace(logout=lambda: None,
                                         delete_saved_credentials=lambda: True)
    p._action_status = types.SimpleNamespace(configure=lambda **k: None)
    p._refresh_buttons = lambda: None
    p._reload = lambda: None

    p._logout()
    p._delete()
    assert invalidated == [True, True]      # entrambi invalidano il login in volo
