"""Test hard: `App._known_betfair_teams` NON congela la GUI durante una sync (#321).

Fix CodeRabbit: la lettura dei nomi Betfair per la precompila della mappatura nomi
(area ⚽ Calcio) gira sul thread Tk. `CatalogueSync.sync` tiene il lock del DB per l'intera
transazione (incluse le chiamate HTTP), quindi una lettura **bloccante** congelerebbe la
finestra fino a fine sync. Il metodo fa quindi **fail-fast** (`DictionaryBusy`) se il lock è
occupato, invece di attendere — mirror di `DictionaryViewerController.view_if_free` (#175).

Esercita il METODO REALE di `App` via l'harness headless (`make_app`), con un
`BetfairLocalDB` reale in memoria.
"""

import threading
import types

import pytest

from xtrader_bridge.betfair.dictionary_viewer import DictionaryBusy
from xtrader_bridge.betfair.local_db import BetfairLocalDB


def _app_with_db(make_app, db):
    a = make_app()
    a._betfair_engine_obj = types.SimpleNamespace(db=db)   # _betfair_sync_engine() lo ritorna
    return a


def test_known_teams_lock_libero_ritorna_nomi(make_app, app_mod):
    db = BetfairLocalDB(":memory:")
    db.upsert_known_team("Calcio", "Inter", seen_at=1)
    a = _app_with_db(make_app, db)
    try:
        teams = app_mod.App._known_betfair_teams(a, "Calcio")
        assert [t["display_name"] for t in teams] == ["Inter"]
    finally:
        db.close()


def test_known_teams_durante_sync_fa_fail_fast(make_app, app_mod):
    db = BetfairLocalDB(":memory:")
    a = _app_with_db(make_app, db)
    holding, release = threading.Event(), threading.Event()

    def _hold_lock_like_a_sync():
        db.acquire_read(blocking=True)   # come transaction(): tiene il lock del DB
        holding.set()
        release.wait(2)
        db.release_read()

    t = threading.Thread(target=_hold_lock_like_a_sync)
    t.start()
    try:
        assert holding.wait(2)
        # Il thread Tk NON deve bloccare: fail-fast con DictionaryBusy.
        with pytest.raises(DictionaryBusy):
            app_mod.App._known_betfair_teams(a, "Calcio")
    finally:
        release.set()
        t.join()
        db.close()


def test_known_teams_db_assente_ritorna_vuoto(make_app, app_mod):
    a = make_app()

    def _boom():
        raise RuntimeError("DB non disponibile")

    a._betfair_sync_engine = _boom     # engine non costruibile → best-effort []
    assert app_mod.App._known_betfair_teams(a) == []


def test_known_teams_engine_con_db_none_ritorna_vuoto(make_app, app_mod):
    # Engine costruibile ma `.db` None (es. sync mai fatta): NON deve sollevare
    # AttributeError fuori dalla guardia (review Fugu #321) — contratto «indisponibile → []».
    a = make_app()
    a._betfair_engine_obj = types.SimpleNamespace(db=None)
    assert app_mod.App._known_betfair_teams(a) == []


def test_known_teams_query_solleva_ritorna_vuoto_e_rilascia_il_lock(make_app, app_mod):
    # DB presente, lock ACQUISITO, ma `known_teams()` solleva un errore generico (es.
    # dizionario corrotto): il catch-all best-effort ritorna `[]` e — punto chiave — il
    # lock viene comunque RILASCIATO nel `finally`, senza sbilanciamenti (review GLM/GPT/
    # Fable #321). Prova anche che `except DictionaryBusy: raise` NON è dead code: la
    # struttura try/except è quella intesa (busy propaga, il resto → []).
    calls = {"acq": 0, "rel": 0}

    class _FakeDB:
        def acquire_read(self, *, blocking=False):
            calls["acq"] += 1
            return True                      # lock libero: entra nel ramo di lettura
        def release_read(self):
            calls["rel"] += 1
        def known_teams(self, sport=None):
            raise RuntimeError("dizionario corrotto")

    a = make_app()
    a._betfair_engine_obj = types.SimpleNamespace(db=_FakeDB())
    assert app_mod.App._known_betfair_teams(a) == []       # errore ingoiato (best-effort)
    assert calls["acq"] == 1 and calls["rel"] == 1          # acquisito E rilasciato: no leak lock


# ── _delete_betfair_team: stessa busy-guard della lettura (#282 PR 11-bis) ─────

def test_delete_team_lock_libero_elimina(make_app, app_mod):
    db = BetfairLocalDB(":memory:")
    db.upsert_known_team("Calcio", "Inter", seen_at=1)
    a = _app_with_db(make_app, db)
    try:
        assert app_mod.App._delete_betfair_team(a, "Calcio", "inter") is True
        assert db.count_known_teams("Calcio") == 0
    finally:
        db.close()


def test_delete_team_durante_sync_fa_fail_fast(make_app, app_mod):
    db = BetfairLocalDB(":memory:")
    db.upsert_known_team("Calcio", "Inter", seen_at=1)
    a = _app_with_db(make_app, db)
    holding, release = threading.Event(), threading.Event()

    def _hold_lock_like_a_sync():
        db.acquire_read(blocking=True)
        holding.set()
        release.wait(2)
        db.release_read()

    t = threading.Thread(target=_hold_lock_like_a_sync)
    t.start()
    try:
        assert holding.wait(2)
        with pytest.raises(DictionaryBusy):
            app_mod.App._delete_betfair_team(a, "Calcio", "inter")   # non blocca: fail-fast
        assert db.count_known_teams("Calcio") == 1                    # niente eliminazione
    finally:
        release.set()
        t.join()
        db.close()


def test_delete_team_db_assente_ritorna_false(make_app, app_mod):
    a = make_app()
    a._betfair_engine_obj = types.SimpleNamespace(db=None)
    assert app_mod.App._delete_betfair_team(a, "Calcio", "inter") is False


# ── _known_market_terms: stessa busy-guard della lettura (#283 PR 13) ──────────

def test_known_market_terms_lock_libero_ritorna_valori(make_app, app_mod):
    db = BetfairLocalDB(":memory:")
    db.upsert_market_term("Calcio", "MATCH_ODDS", "Esito Finale", seen_at=1)
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Over 2,5", seen_at=1)
    db.upsert_market_term("Tennis", "OVER_UNDER_205_GAMES", "Over/Under 20,5", "Over 20,5", seen_at=1)
    a = _app_with_db(make_app, db)
    try:
        terms = app_mod.App._known_market_terms(a, "Calcio")   # filtrato per sport
        assert terms["market_types"] == ["MATCH_ODDS", "OVER_UNDER_25"]
        assert terms["market_names"] == ["Esito Finale", "Over/Under 2,5"]
        assert terms["selection_names"] == ["Over 2,5"]        # niente Tennis (cross-sport)
    finally:
        db.close()


def test_known_market_terms_durante_sync_fa_fail_fast(make_app, app_mod):
    db = BetfairLocalDB(":memory:")
    a = _app_with_db(make_app, db)
    holding, release = threading.Event(), threading.Event()

    def _hold_lock_like_a_sync():
        db.acquire_read(blocking=True)   # come transaction(): tiene il lock del DB
        holding.set()
        release.wait(2)
        db.release_read()

    t = threading.Thread(target=_hold_lock_like_a_sync)
    t.start()
    try:
        assert holding.wait(2)
        with pytest.raises(DictionaryBusy):      # il thread Tk non blocca: fail-fast
            app_mod.App._known_market_terms(a, "Calcio")
    finally:
        release.set()
        t.join()
        db.close()


def test_known_market_terms_db_assente_ritorna_liste_vuote(make_app, app_mod):
    a = make_app()
    a._betfair_engine_obj = types.SimpleNamespace(db=None)
    terms = app_mod.App._known_market_terms(a)
    assert terms == {"market_types": [], "market_names": [], "selection_names": []}


def test_known_market_terms_engine_non_costruibile_ritorna_liste_vuote(make_app, app_mod):
    a = make_app()

    def _boom():
        raise RuntimeError("DB non disponibile")

    a._betfair_sync_engine = _boom     # engine non costruibile → best-effort liste vuote
    terms = app_mod.App._known_market_terms(a)
    assert terms == {"market_types": [], "market_names": [], "selection_names": []}
