"""Test hard del motore di sync manuale Betfair (issue #86 PR-P7).

Copre i casi richiesti dall'issue: sync OK, sync fallita (safe), sync già in corso
bloccata, sync due volte non duplica, login non attivo. Usa il DB locale reale e un
CatalogueSync con transport finti (offline).
"""

import threading

import pytest

from xtrader_bridge.betfair import sync_engine as se
from xtrader_bridge.betfair.catalogue_client import CatalogueSync
from xtrader_bridge.betfair.local_db import BetfairLocalDB
from xtrader_bridge.betfair.session import BetfairSession
from xtrader_bridge.betfair.sync_engine import SyncEngine


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


def _logged_session():
    s = BetfairSession()
    s.set_token("tok-ram")
    return s


def _menu():
    return {"type": "GROUP", "children": [
        {"type": "EVENT_TYPE", "id": "1", "name": "Soccer", "children": [
            {"type": "EVENT", "id": "e1", "name": "Inter v Milan", "children": [
                {"type": "MARKET", "id": "1.101", "name": "Match Odds",
                 "marketType": "MATCH_ODDS"}]}]}]}


def _catalogue():
    return [{"marketId": "1.101", "marketName": "Match Odds",
             "description": {"marketType": "MATCH_ODDS"},
             "event": {"id": "e1", "name": "Inter v Milan"},
             "runners": [{"selectionId": 1, "runnerName": "Inter", "handicap": 0},
                         {"selectionId": 2, "runnerName": "Milan", "handicap": 0}]}]


def _engine(db, catalogue_sync=None, session=None):
    cs = catalogue_sync or CatalogueSync(
        db, navigation_transport=lambda: _menu(),
        catalogue_transport=lambda mids: _catalogue())
    return SyncEngine(db, session or _logged_session(), catalogue_sync=cs)


# ── sync OK ───────────────────────────────────────────────────────────────────

def test_run_ok(db):
    res = _engine(db).run(["Calcio"])
    assert res.status == se.OK and res.ok
    assert res.new_events == 1
    assert res.new_markets == 1
    assert res.new_selections == 2
    assert res.errors == []
    assert db.count_active("betfair_selections") == 2


# ── login non attivo ──────────────────────────────────────────────────────────

def test_run_login_non_attivo(db):
    eng = _engine(db, session=BetfairSession())   # nessun token
    res = eng.run(["Calcio"])
    assert res.status == se.NOT_LOGGED_IN
    assert res.errors                                # messaggio safe
    # non ha sincronizzato nulla
    assert db.count_active("betfair_events") == 0


# ── sync fallita (safe) ───────────────────────────────────────────────────────

class _BoomSync:
    def sync(self, sports):
        raise RuntimeError("rete giù con segreto tok-ram")   # contiene un "segreto"


def test_run_fallita_e_safe(db):
    eng = SyncEngine(db, _logged_session(), catalogue_sync=_BoomSync())
    res = eng.run(["Calcio"])
    assert res.status == se.FAILED
    assert res.errors and "RuntimeError" in res.errors[0]
    assert "tok-ram" not in res.errors[0]            # nessun segreto nel messaggio


# ── sync già in corso bloccata ────────────────────────────────────────────────

class _BlockingSync:
    def __init__(self, started, release):
        self._started = started
        self._release = release

    def sync(self, sports):
        self._started.set()        # segnala che la sync è "in corso"
        self._release.wait(2)      # resta dentro finché il test lo permette
        return {"sports": ["1"], "selections": 0, "deactivated": 0}


def test_seconda_sync_bloccata_se_una_in_corso(db):
    started, release = threading.Event(), threading.Event()
    eng = SyncEngine(db, _logged_session(), catalogue_sync=_BlockingSync(started, release))

    out = {}

    def _first():
        out["first"] = eng.run(["Calcio"])

    t = threading.Thread(target=_first)
    t.start()
    assert started.wait(2)         # la prima sync è entrata (lock preso)
    assert eng.is_syncing is True
    # mentre la prima è in corso, la seconda deve risultare BUSY
    res2 = eng.run(["Calcio"])
    assert res2.status == se.BUSY
    release.set()                  # lascia terminare la prima
    t.join(2)
    assert out["first"].status == se.OK
    assert eng.is_syncing is False


# ── sync due volte non duplica ────────────────────────────────────────────────

def test_due_volte_non_duplica(db):
    eng = _engine(db)
    eng.run(["Calcio"])
    res2 = eng.run(["Calcio"])
    assert res2.status == se.OK
    assert db.count_active("betfair_events") == 1
    assert db.count_active("betfair_markets") == 1
    assert db.count_active("betfair_selections") == 2
    # alla seconda run niente di nuovo (delta 0), selezioni incluse (CodeRabbit)
    assert res2.new_events == 0 and res2.new_markets == 0
    assert res2.new_selections == 0


# ── sport vuoti propagati come FAILED safe ────────────────────────────────────

def test_run_sport_vuoti_e_failed(db):
    res = _engine(db).run([])      # CatalogueSync alza ValueError → FAILED safe
    assert res.status == se.FAILED
    assert res.errors and "ValueError" in res.errors[0]


# ── errore di lettura conteggi DB → FAILED safe (Codex) ───────────────────────

def test_errore_count_active_e_failed():
    class _FakeDB:
        def count_active(self, table):
            raise RuntimeError("db locked")

    class _OkSync:
        def sync(self, sports):
            return {"sports": ["1"], "selections": 0, "deactivated": 0}

    eng = SyncEngine(_FakeDB(), _logged_session(), catalogue_sync=_OkSync())
    res = eng.run(["Calcio"])
    assert res.status == se.FAILED      # niente crash: count_active dentro il path safe
    assert res.errors and "RuntimeError" in res.errors[0]


# ── set_app_key (login non salvato) ───────────────────────────────────────────

def test_set_app_key(db):
    eng = SyncEngine(db, _logged_session())   # CatalogueSync di default
    eng.set_app_key("DelayedKeyDalLogin")
    assert eng._sync.app_key == "DelayedKeyDalLogin"
