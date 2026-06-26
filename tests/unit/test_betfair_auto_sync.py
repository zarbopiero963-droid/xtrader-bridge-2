"""Test hard dell'auto-sync Betfair (issue #86 PR-P8).

Copre la decisione pura `should_run` e il ciclo `AutoSyncScheduler.maybe_run`
(auto login → sync → auto logout) con dipendenze finte: OFF non parte, ON parte
all'orario, già-in-corso bloccata, niente doppio scatto stesso giorno/orario,
bridge chiuso non parte, e **logout sempre chiamato anche se la sync fallisce**.
"""

from datetime import datetime

import pytest

from xtrader_bridge.betfair import auto_sync
from xtrader_bridge.betfair.auto_sync import AutoSyncScheduler, normalize_hour, run_key, should_run
from xtrader_bridge.betfair.sync_engine import OK, FAILED, SyncResult


_NOW_23 = datetime(2026, 7, 1, 23, 5, 0)     # ora 23
_NOW_22 = datetime(2026, 7, 1, 22, 5, 0)     # ora 22


# ── normalize_hour ────────────────────────────────────────────────────────────

def test_normalize_hour():
    assert normalize_hour(23) == 23
    assert normalize_hour("9") == 9
    assert normalize_hour(0) == 0
    assert normalize_hour(24) == 23          # fuori range → default
    assert normalize_hour(-1) == 23
    assert normalize_hour("x") == 23
    assert normalize_hour(True) == 23        # bool non valido


# ── should_run (decisione pura) ───────────────────────────────────────────────

def test_should_run_off_non_parte():
    assert should_run(_NOW_23, enabled=False, hour=23,
                      last_run_key=None, sync_in_progress=False) is False


def test_should_run_on_all_orario():
    assert should_run(_NOW_23, enabled=True, hour=23,
                      last_run_key=None, sync_in_progress=False) is True


def test_should_run_fuori_orario():
    assert should_run(_NOW_22, enabled=True, hour=23,
                      last_run_key=None, sync_in_progress=False) is False


def test_should_run_gia_eseguita_oggi():
    key = run_key(_NOW_23, 23)
    assert should_run(_NOW_23, enabled=True, hour=23,
                      last_run_key=key, sync_in_progress=False) is False


def test_should_run_sync_in_corso():
    assert should_run(_NOW_23, enabled=True, hour=23,
                      last_run_key=None, sync_in_progress=True) is False


def test_should_run_giorno_diverso_riscatta():
    ieri = run_key(datetime(2026, 6, 30, 23, 0, 0), 23)
    assert should_run(_NOW_23, enabled=True, hour=23,
                      last_run_key=ieri, sync_in_progress=False) is True


# ── ciclo auto login → sync → logout ──────────────────────────────────────────

class _Auth:
    def __init__(self):
        self.calls = []

    def login(self, creds):
        self.calls.append("login")

    def logout(self):
        self.calls.append("logout")


class _Engine:
    def __init__(self, result=None, raise_on_run=False):
        self._result = result or SyncResult(status=OK)
        self._raise = raise_on_run
        self.is_syncing = False
        self.ran = False

    def run(self, sports):
        self.ran = True
        if self._raise:
            raise RuntimeError("rete giù")
        return self._result


def _cfg(enabled=True, hour=23, sports=("Calcio",), creds="CREDS"):
    return lambda: (enabled, hour, list(sports), creds)


def test_maybe_run_esegue_login_sync_logout():
    auth, eng = _Auth(), _Engine(SyncResult(status=OK, new_events=3))
    summaries = []
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                              on_summary=summaries.append)
    res = sched.maybe_run(_NOW_23)
    assert res.status == OK
    assert auth.calls == ["login", "logout"]   # login poi logout
    assert eng.ran is True
    assert summaries and summaries[0].new_events == 3


def test_maybe_run_off_non_parte():
    auth, eng = _Auth(), _Engine()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(enabled=False))
    assert sched.maybe_run(_NOW_23) is None
    assert auth.calls == []                     # nessun login/logout
    assert eng.ran is False


def test_maybe_run_bridge_chiuso_non_parte():
    auth, eng = _Auth(), _Engine()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                              is_bridge_open=lambda: False)
    assert sched.maybe_run(_NOW_23) is None
    assert auth.calls == []


def test_maybe_run_sync_gia_in_corso_bloccata():
    auth, eng = _Auth(), _Engine()
    eng.is_syncing = True
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    assert sched.maybe_run(_NOW_23) is None
    assert auth.calls == []


def test_maybe_run_non_due_volte_stesso_giorno():
    auth, eng = _Auth(), _Engine()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    assert sched.maybe_run(_NOW_23) is not None       # prima volta: parte
    auth.calls.clear()
    # secondo tick nella stessa ora/giorno: non riparte
    assert sched.maybe_run(datetime(2026, 7, 1, 23, 40, 0)) is None
    assert auth.calls == []


def test_logout_chiamato_anche_se_sync_fallisce():
    auth, eng = _Auth(), _Engine(raise_on_run=True)
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    res = sched.maybe_run(_NOW_23)
    assert res.status == FAILED
    assert "logout" in auth.calls                # logout in finally nonostante l'errore
    assert auth.calls == ["login", "logout"]


def test_last_run_persistito_evita_doppio_dopo_riavvio():
    # Stato condiviso che simula il file su disco.
    store = {"key": None}
    auth, eng = _Auth(), _Engine()
    s1 = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                           load_state=lambda: store["key"],
                           save_state=lambda k: store.__setitem__("key", k))
    assert s1.maybe_run(_NOW_23) is not None        # prima volta: parte e persiste
    assert store["key"] == run_key(_NOW_23, 23)

    # "riavvio": nuovo scheduler che ricarica lo stato persistito
    auth2, eng2 = _Auth(), _Engine()
    s2 = AutoSyncScheduler(auth=auth2, engine=eng2, get_config=_cfg(),
                           load_state=lambda: store["key"],
                           save_state=lambda k: store.__setitem__("key", k))
    assert s2.maybe_run(datetime(2026, 7, 1, 23, 50, 0)) is None   # stessa ora/giorno → non riparte
    assert auth2.calls == []


def test_run_fallita_non_consuma_la_finestra_ritenta():
    # Un tentativo fallito NON deve marcare la run come fatta: il tick successivo
    # nella stessa ora ritenta (Codex).
    store = {"key": None}
    auth = _Auth()
    eng = _Engine(raise_on_run=True)            # la sync fallisce
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                              load_state=lambda: store["key"],
                              save_state=lambda k: store.__setitem__("key", k))
    res1 = sched.maybe_run(_NOW_23)
    assert res1.status == FAILED
    assert store["key"] is None                 # NON persistito (può ritentare)
    assert sched.last_run_key is None
    # ora "il problema è risolto": un nuovo tentativo nella stessa ora parte e riesce
    sched.engine = _Engine()                    # engine che riesce
    res2 = sched.maybe_run(datetime(2026, 7, 1, 23, 9, 0))
    assert res2.status == OK
    assert store["key"] == run_key(_NOW_23, 23)  # ora marcato


def test_cycle_aggiorna_app_key_engine():
    # Dopo il login, l'engine riceve la App Key delle credenziali correnti (Codex).
    class _Creds:
        app_key = "KeyCorrente"

    class _EngineKey(_Engine):
        def __init__(self):
            super().__init__()
            self.app_key_set = None

        def set_app_key(self, k):
            self.app_key_set = k

    auth, eng = _Auth(), _EngineKey()
    sched = AutoSyncScheduler(auth=auth, engine=eng,
                              get_config=lambda: (True, 23, ["Calcio"], _Creds()))
    sched.maybe_run(_NOW_23)
    assert eng.app_key_set == "KeyCorrente"


def test_logout_chiamato_anche_se_login_fallisce():
    class _BadAuth(_Auth):
        def login(self, creds):
            self.calls.append("login")
            raise RuntimeError("login ko")

    auth, eng = _BadAuth(), _Engine()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    res = sched.maybe_run(_NOW_23)
    assert res.status == FAILED
    assert auth.calls == ["login", "logout"]     # logout sempre eseguito
    assert eng.ran is False                       # sync non raggiunta
