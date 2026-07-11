"""Regressione: la funzione «Betfair Sync» è stata rimossa.

Il bridge non contatta più Betfair, non fa login, non fa auto-sync e non costruisce più il
dizionario automaticamente. Sopravvivono SOLO il dizionario locale (`betfair_dictionary.db`,
popolato a mano dall'utente) e i suoi lettori (sola lettura). Questi test bloccano una
reintroduzione accidentale delle chiavi/API rimosse ed esercitano il substrato superstite.
"""

import os

import pytest

from xtrader_bridge import config_store, runtime_state


# ── config: le chiavi auto-sync NON esistono più ──────────────────────────────

@pytest.mark.parametrize("key", ["betfair_auto_sync", "betfair_auto_sync_hour",
                                 "betfair_sync_sports"])
def test_config_defaults_senza_chiavi_autosync(key):
    # Fail-first: prima erano nei DEFAULTS e re-iniettate a ogni load_config.
    assert key not in config_store.DEFAULTS


def test_load_config_non_reinietta_le_chiavi_autosync(tmp_path):
    # Una config nuova non deve materializzare le chiavi auto-sync rimosse.
    p = tmp_path / "config.json"
    cfg = config_store.load_config(str(p))
    for key in ("betfair_auto_sync", "betfair_auto_sync_hour", "betfair_sync_sports"):
        assert key not in cfg


def test_load_config_scarta_chiavi_autosync_legacy(tmp_path):
    # Un vecchio config.json con le chiavi auto-sync resta caricabile: le chiavi ignote non
    # sono validate ma NON devono far crashare il load (compatibilità retro).
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "X", "betfair_auto_sync": True,
                             "betfair_auto_sync_hour": 9,
                             "betfair_sync_sports": ["Tennis"]}), encoding="utf-8")
    cfg = config_store.load_config(str(p))          # non solleva
    assert cfg.get("provider") == "X"


# ── runtime_state: DB locale sì, stato auto-sync no ───────────────────────────

def test_runtime_state_db_path_presente():
    path = runtime_state.betfair_db_path("/tmp/cfg")
    assert path.endswith("betfair_dictionary.db")


def test_runtime_state_autosync_state_path_rimosso():
    # Fail-first: prima esisteva `betfair_autosync_state_path` per la guardia «una volta al giorno».
    assert not hasattr(runtime_state, "betfair_autosync_state_path")
    assert not hasattr(runtime_state, "BETFAIR_AUTOSYNC_STATE_FILE")


# ── subpackage betfair: solo dizionario locale, niente rete/login ─────────────

def test_betfair_package_espone_solo_il_dizionario_locale():
    import xtrader_bridge.betfair as bf
    # Presenti: il substrato dizionario e i lettori.
    for name in ("BetfairLocalDB", "DictionaryResolver", "DictionaryViewerController"):
        assert hasattr(bf, name), f"manca {name} nel subpackage dizionario"
    # Assenti: ogni API di rete/login/sync.
    for gone in ("BetfairAuthClient", "BetfairSession", "CatalogueSync", "SyncEngine",
                 "AutoSyncScheduler", "BetfairCredentials", "assert_read_only"):
        assert not hasattr(bf, gone), f"API di rete/login «{gone}» non deve riesistere"


def test_moduli_rete_login_non_importabili():
    import importlib
    for mod in ("auth_client", "catalogue_client", "credential_store", "session",
                "sync_engine", "auto_sync", "safety", "log_safety",
                "sync_tab_gui", "sync_tab_controller"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"xtrader_bridge.betfair.{mod}")


def test_resolver_costruibile_sul_dizionario_locale():
    # Il seam superstite: un resolver sul DB locale vuoto risolve «nulla» senza crash
    # (fallback nomi), pronto a essere popolato dall'utente coi suoi campi.
    from xtrader_bridge.betfair.local_db import BetfairLocalDB
    from xtrader_bridge.betfair.dictionary_resolver import DictionaryResolver
    db = BetfairLocalDB(":memory:")
    try:
        resolver = DictionaryResolver(db)
        ids = resolver.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                                   market_type="MATCH_ODDS", selection_name="Inter")
        assert ids == {} or all(not v for v in ids.values())   # dizionario vuoto → nessun ID
    finally:
        db.close()
