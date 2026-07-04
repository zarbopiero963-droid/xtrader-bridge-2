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
