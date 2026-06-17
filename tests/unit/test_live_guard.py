"""Test del guardrail del percorso di scrittura live (PR-21): decisione pura."""

from xtrader_bridge import live_guard as lg
from xtrader_bridge import safety_guard, signal_dedupe


def _tracker(**kw):
    return signal_dedupe.SignalTracker(**kw)


def _real_cfg():
    return {"dry_run": False, "max_per_day": 200}


# ── esiti base ───────────────────────────────────────────────────────────────

def test_write_quando_reale_e_nuovo():
    d = safety_guard.DailyLimiter(max_per_day=10)
    assert lg.evaluate(_real_cfg(), _tracker(), d, "Inter v Milan", now=1000) == lg.WRITE


def test_dry_run_sopprime_la_scrittura():
    d = safety_guard.DailyLimiter(max_per_day=10)
    # dry_run attivo (anche di default se il campo manca) → DRY_RUN, non WRITE
    assert lg.evaluate({"dry_run": True}, _tracker(), d, "X", now=1000) == lg.DRY_RUN
    assert lg.evaluate({}, _tracker(), d, "X", now=1000) == lg.DRY_RUN


def test_duplicato_non_scrive():
    t = _tracker()
    d = safety_guard.DailyLimiter(max_per_day=10)
    assert lg.evaluate(_real_cfg(), t, d, "stesso", now=1000) == lg.WRITE
    # stesso messaggio nella finestra → DUPLICATE (nessuna doppia scommessa)
    assert lg.evaluate(_real_cfg(), t, d, "stesso", now=1001) == lg.DUPLICATE


def test_rate_limited_al_minuto():
    t = _tracker(max_per_minute=2)
    d = safety_guard.DailyLimiter(max_per_day=100)
    assert lg.evaluate(_real_cfg(), t, d, "a", now=1000) == lg.WRITE
    assert lg.evaluate(_real_cfg(), t, d, "b", now=1000) == lg.WRITE
    assert lg.evaluate(_real_cfg(), t, d, "c", now=1000) == lg.RATE_LIMITED


def test_limite_giornaliero():
    t = _tracker()
    d = safety_guard.DailyLimiter(max_per_day=1)
    assert lg.evaluate(_real_cfg(), t, d, "a", now=1000) == lg.WRITE
    assert lg.evaluate(_real_cfg(), t, d, "b", now=1001) == lg.DAILY_LIMITED


# ── precedenze / robustezza ──────────────────────────────────────────────────

def test_duplicato_ha_precedenza_su_dry_run():
    t = _tracker()
    d = safety_guard.DailyLimiter(max_per_day=10)
    lg.evaluate({"dry_run": True}, t, d, "m", now=1000)        # primo: DRY_RUN (registrato)
    assert lg.evaluate({"dry_run": True}, t, d, "m", now=1001) == lg.DUPLICATE


def test_daily_none_nessun_limite_giorno():
    t = _tracker()
    # daily=None → nessun limite giornaliero; resta WRITE
    assert lg.evaluate(_real_cfg(), t, None, "x", now=1000) == lg.WRITE


def test_rollback_dopo_write_fallita_consente_il_retry():
    # Semantica usata da app._process: si fa lo snapshot PRIMA di evaluate; se la
    # scrittura CSV fallisce si ripristina, così lo stesso segnale non resta
    # soppresso come DUPLICATE e il tetto giornaliero non viene consumato.
    t = _tracker()
    d = safety_guard.DailyLimiter(max_per_day=1)
    snap_t, snap_d = t.state(), d.state()
    assert lg.evaluate(_real_cfg(), t, d, "sig", now=1000) == lg.WRITE   # consuma
    # simula write fallita → rollback
    t.restore_state(snap_t)
    d.restore_state(snap_d)
    # retry dello stesso segnale: di nuovo WRITE (non DUPLICATE) e tetto disponibile
    assert lg.evaluate(_real_cfg(), t, d, "sig", now=1001) == lg.WRITE
    assert d.remaining(now=1001) == 0


def test_duplicato_non_consuma_la_slot_giornaliera():
    t = _tracker()
    d = safety_guard.DailyLimiter(max_per_day=1)
    assert lg.evaluate(_real_cfg(), t, d, "a", now=1000) == lg.WRITE       # consuma 1/1
    # un duplicato successivo è respinto PRIMA del daily: non aggiunge consumo
    assert lg.evaluate(_real_cfg(), t, d, "a", now=1001) == lg.DUPLICATE
    # un messaggio NUOVO ora trova il tetto giornaliero pieno
    assert lg.evaluate(_real_cfg(), t, d, "b", now=1002) == lg.DAILY_LIMITED
