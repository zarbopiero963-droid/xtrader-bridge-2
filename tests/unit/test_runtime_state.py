"""Test di `xtrader_bridge.runtime_state` — path di stato + costruzione guardrail.

Pura, headless: esercita le funzioni reali estratte da `App._init_guards`,
verificando i fallback fail-safe (max_per_day/clear_delay invalidi) e i default.
"""

import os

from xtrader_bridge import runtime_state as rs
from xtrader_bridge import safety_guard, signal_queue
from xtrader_bridge.config_store import DEFAULTS


def test_state_paths_uniscono_il_config_dir():
    assert rs.dedupe_state_path("/cfg") == os.path.join("/cfg", "dedupe_state.json")
    assert rs.daily_state_path("/cfg") == os.path.join("/cfg", "daily_state.json")
    # nomi file = fonte unica
    assert rs.DEDUPE_STATE_FILE == "dedupe_state.json"
    assert rs.DAILY_STATE_FILE == "daily_state.json"


def test_build_guards_config_valida_nessun_avviso():
    cfg = {"max_per_day": 5, "queue_mode": "APPEND_ACTIVE",
           "clear_delay": 30, "max_active_signals": 3}
    g = rs.build_guards(cfg)
    assert g.warnings == []
    assert g.mode == "APPEND_ACTIVE"
    assert g.tracker is not None
    assert g.daily.max_per_day == 5
    # il tetto righe attive arriva alla coda
    assert g.queue.max_active == 3
    # il timeout della coda è la fonte unica (validata dalla coda)
    assert g.queue_timeout == g.queue.default_timeout


def test_build_guards_max_per_day_invalido_fallback_con_avviso():
    # max_per_day non valido (float NaN-like / negativo) → DailyLimiter di default + avviso
    cfg = {"max_per_day": -1, "queue_mode": "OVERWRITE_LAST"}
    g = rs.build_guards(cfg)
    assert g.daily.max_per_day == safety_guard.DEFAULT_MAX_PER_DAY
    assert any("max_per_day" in w for w in g.warnings)


def test_build_guards_clear_delay_invalido_failsafe_timeout():
    # clear_delay malformato → `timeout_from_config` ricade su DEFAULT_TIMEOUT
    # PRIMA della coda, quindi la coda riceve sempre un timeout valido (un segnale
    # deve scadere comunque, mai immortale). Il ramo `except ValueError` della coda
    # resta difensivo/non raggiungibile da questo path (fedele a _init_guards).
    cfg = {"queue_mode": "OVERWRITE_LAST", "clear_delay": "nan"}
    g = rs.build_guards(cfg)
    assert isinstance(g.queue, signal_queue.SignalQueue)
    assert g.queue_timeout == signal_queue.DEFAULT_TIMEOUT
    assert g.queue_timeout > 0


def test_build_guards_default_quando_chiavi_assenti():
    # config minima: usa i default sicuri (incl. max_active_signals dei DEFAULTS)
    g = rs.build_guards({})
    assert g.warnings == []
    assert g.mode == signal_queue.normalize_mode(None)
    assert g.queue.max_active == DEFAULTS["max_active_signals"]
    assert g.daily.max_per_day == safety_guard.DEFAULT_MAX_PER_DAY
