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


def test_should_run_hour_non_numerico_non_crasha():
    # Ora non numerica/bool → normalize_hour ripiega su 23 e DEVE essere riusata anche
    # per run_key: non deve crashare (int("x")) né produrre una dedupe-key sbagliata
    # (CodeRabbit). Con now alle 23 e hour="x" (→23) deve scattare.
    assert should_run(_NOW_23, enabled=True, hour="x",
                      last_run_key=None, sync_in_progress=False) is True
    assert should_run(_NOW_23, enabled=True, hour=True,
                      last_run_key=None, sync_in_progress=False) is True
    # E la dedupe-key è quella normalizzata (23): seconda valutazione non riscatta.
    key = run_key(_NOW_23, normalize_hour("x"))
    assert should_run(_NOW_23, enabled=True, hour="x",
                      last_run_key=key, sync_in_progress=False) is False
    # Fuori orario con hour invalido non scatta (now 22 != 23 normalizzato).
    assert should_run(_NOW_22, enabled=True, hour="x",
                      last_run_key=None, sync_in_progress=False) is False


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


def _cfg(enabled=True, hour=23, sports=("Calcio",)):
    """Config LEGGERA dello scheduler: (enabled, hour, sports). Le credenziali NON
    stanno più qui (si leggono lazy in `_cycle` via `get_credentials`)."""
    return lambda: (enabled, hour, list(sports))


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


def test_sessione_manuale_idle_non_viene_sloggata():
    # Se la sessione condivisa è GIÀ loggata (login manuale dalla tab, idle), l'auto-sync
    # NON deve fare login/logout: riusa la sessione e la lascia intatta (Codex).
    class _Session:
        is_logged_in = True

    class _AuthWithSession(_Auth):
        def __init__(self):
            super().__init__()
            self.session = _Session()

    auth, eng = _AuthWithSession(), _Engine(SyncResult(status=OK))
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                              get_credentials=lambda: "CREDS")
    res = sched.maybe_run(_NOW_23)
    assert res.status == OK
    assert eng.ran is True                # la sync gira sulla sessione esistente
    assert auth.calls == []               # NESSUN login/logout: sessione manuale preservata


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
                              get_config=lambda: (True, 23, ["Calcio"]),
                              get_credentials=lambda: _Creds())
    sched.maybe_run(_NOW_23)
    assert eng.app_key_set == "KeyCorrente"


def test_credenziali_lette_solo_quando_la_run_e_dovuta():
    # Il keyring (get_credentials) NON deve essere toccato a ogni tick: solo quando la
    # run è davvero dovuta, dentro `_cycle`, dopo il gate (CodeRabbit).
    calls = {"creds": 0}

    def _creds():
        calls["creds"] += 1
        return "CREDS"

    auth, eng = _Auth(), _Engine()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(hour=23),
                              get_credentials=_creds)
    # Tick fuori orario: decisione pura, NESSUNA lettura credenziali.
    assert sched.maybe_run(_NOW_22) is None
    assert calls["creds"] == 0
    # Tick nell'orario: la run parte e le credenziali vengono lette UNA volta.
    assert sched.maybe_run(_NOW_23) is not None
    assert calls["creds"] == 1
    # Secondo tick stessa ora (già fatta): niente nuova lettura del keyring.
    assert sched.maybe_run(datetime(2026, 7, 1, 23, 30, 0)) is None
    assert calls["creds"] == 1


def test_reserve_fallita_non_logga_e_ritorna_busy():
    # Se il motore è già prenotato (sync manuale in corso), l'auto-sync NON deve
    # fare login/logout sulla sessione condivisa (Codex): ritorna BUSY.
    class _EngineReserve(_Engine):
        def reserve(self, blocking=False):
            return False     # manuale in corso

        def release(self):
            pass

    auth, eng = _Auth(), _EngineReserve()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    res = sched.maybe_run(_NOW_23)
    assert res.status == "BUSY"
    assert auth.calls == []          # niente login/logout sulla sessione condivisa
    assert eng.ran is False


def test_reserve_ok_login_sync_logout_e_release():
    class _EngineReserve(_Engine):
        def __init__(self):
            super().__init__()
            self.events = []

        def reserve(self, blocking=False):
            self.events.append("reserve")
            return True

        def release(self):
            self.events.append("release")

        def run(self, sports, *, locked=False):
            self.events.append(f"run(locked={locked})")
            return super().run(sports)

    auth, eng = _Auth(), _EngineReserve()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    res = sched.maybe_run(_NOW_23)
    assert res.status == OK
    assert auth.calls == ["login", "logout"]
    assert eng.events == ["reserve", "run(locked=True)", "release"]


def test_maybe_run_hour_non_numerico_persiste_chiave_normalizzata():
    # Con hour non numerico ("x" → 23), una sync riuscita NON deve crashare al momento
    # di marcare la run: maybe_run deve persistere la run_key NORMALIZZATA (CodeRabbit).
    store = {"key": None}
    auth, eng = _Auth(), _Engine(SyncResult(status=OK))
    sched = AutoSyncScheduler(auth=auth, engine=eng,
                              get_config=lambda: (True, "x", ["Calcio"]),
                              load_state=lambda: store["key"],
                              save_state=lambda k: store.__setitem__("key", k))
    res = sched.maybe_run(_NOW_23)                       # ora 23 == normalize_hour("x")
    assert res is not None and res.status == OK          # nessun crash int("x")
    assert sched.last_run_key == run_key(_NOW_23, 23)    # chiave normalizzata
    assert store["key"] == run_key(_NOW_23, 23)          # persistita
    # Secondo tick stessa ora con lo stesso hour invalido: non riparte.
    assert sched.maybe_run(datetime(2026, 7, 1, 23, 45, 0)) is None


def test_on_summary_che_solleva_non_perde_la_run_riuscita():
    # Se on_summary solleva (es. Tk `after` su finestra in chiusura) dopo una sync OK,
    # la run DEVE comunque essere registrata/persistita: altrimenti la stessa ora
    # rieseguirebbe al tick successivo (Codex). Il riepilogo è best-effort.
    store = {"key": None}

    def _boom(_res):
        raise RuntimeError("Tk after su root distrutta")

    auth, eng = _Auth(), _Engine(SyncResult(status=OK))
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                              on_summary=_boom,
                              load_state=lambda: store["key"],
                              save_state=lambda k: store.__setitem__("key", k))
    res = sched.maybe_run(_NOW_23)
    assert res is not None and res.status == OK     # _cycle NON propaga l'errore di summary
    assert auth.calls == ["login", "logout"]
    assert store["key"] == run_key(_NOW_23, 23)     # run riuscita registrata/persistita
    # Secondo tick stessa ora: non riparte (la finestra è stata consumata).
    assert sched.maybe_run(datetime(2026, 7, 1, 23, 40, 0)) is None


def test_on_state_error_invocato_se_save_fallisce():
    errors = []

    def _bad_save(_k):
        raise OSError("disco pieno")

    auth, eng = _Auth(), _Engine()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                              save_state=_bad_save,
                              on_state_error=lambda ex: errors.append(type(ex).__name__))
    res = sched.maybe_run(_NOW_23)
    assert res.status == OK                  # la run è ok…
    assert errors == ["OSError"]             # …ma il fallimento di save è segnalato


def test_login_fallito_non_chiama_logout_preserva_sessione():
    # Se l'auto-login FALLISCE non ha stabilito/sostituito alcun token: un logout
    # incondizionato sloggherebbe una eventuale sessione manuale condivisa (Codex).
    # Quindi logout NON deve essere chiamato quando login solleva.
    class _BadAuth(_Auth):
        def login(self, creds):
            self.calls.append("login")
            raise RuntimeError("login ko")

    auth, eng = _BadAuth(), _Engine()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    res = sched.maybe_run(_NOW_23)
    assert res.status == FAILED
    assert auth.calls == ["login"]                # NESSUN logout: sessione preservata
    assert eng.ran is False                       # sync non raggiunta


# ── #184 LOW: release() in finally best-effort (no lock bloccato / risultato mascherato) ──

def test_release_che_solleva_non_propaga_e_non_maschera_il_risultato():
    # Se engine.release() solleva nel finally di _cycle, l'eccezione NON deve propagare
    # fino al worker del tick: mascherebbe il SyncResult già calcolato e lascerebbe la run
    # riuscita NON registrata (la stessa ora rieseguirebbe). Logout deve comunque avvenire.
    class _EngineReleaseBoom(_Engine):
        def __init__(self):
            super().__init__(SyncResult(status=OK, new_events=2))
            self.events = []

        def reserve(self, blocking=False):
            self.events.append("reserve")
            return True

        def release(self):
            self.events.append("release")
            raise RuntimeError("release unlocked lock (simulato)")

        def run(self, sports, *, locked=False):
            self.events.append(f"run(locked={locked})")
            return super().run(sports)

    store = {"key": None}
    auth, eng = _Auth(), _EngineReleaseBoom()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg(),
                              save_state=lambda k: store.__setitem__("key", k))
    res = sched.maybe_run(_NOW_23)                      # NON deve sollevare nonostante release()
    assert res is not None and res.status == OK and res.new_events == 2
    assert "release" in eng.events                     # il release è stato tentato
    assert auth.calls == ["login", "logout"]           # logout comunque eseguito
    assert sched.last_run_key == run_key(_NOW_23, 23)  # run marcata (non mascherata)
    assert store["key"] == run_key(_NOW_23, 23)        # e persistita


def test_logout_che_solleva_non_impedisce_il_release():
    # Logout e release sono indipendenti: un logout che solleva (già best-effort) non deve
    # impedire il release del lock del motore. Regressione: il lock va sempre rilasciato.
    class _AuthLogoutBoom(_Auth):
        def logout(self):
            self.calls.append("logout")
            raise RuntimeError("logout fallito (simulato)")

    class _EngineRel(_Engine):
        def __init__(self):
            super().__init__(SyncResult(status=OK))
            self.events = []

        def reserve(self, blocking=False):
            return True

        def release(self):
            self.events.append("release")

        def run(self, sports, *, locked=False):
            return super().run(sports)

    auth, eng = _AuthLogoutBoom(), _EngineRel()
    sched = AutoSyncScheduler(auth=auth, engine=eng, get_config=_cfg())
    res = sched.maybe_run(_NOW_23)
    assert res is not None and res.status == OK
    assert "logout" in auth.calls
    assert eng.events == ["release"]                    # release eseguito nonostante logout boom
