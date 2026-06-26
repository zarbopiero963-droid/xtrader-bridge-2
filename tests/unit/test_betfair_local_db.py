"""Test hard del dizionario Betfair locale (issue #86 PR-P5).

Esercita la logica reale su un DB SQLite in memoria. Copre i casi richiesti
dall'issue: upsert non duplica; stesso nome squadra in eventi diversi non scartato;
selection_id uguale in market diversi senza conflitto; record non più visti →
active=0. Tutto locale, nessun cloud/export.
"""

import pytest

from xtrader_bridge.betfair.local_db import BetfairLocalDB, _norm_handicap


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


# ── upsert non duplica ────────────────────────────────────────────────────────

def test_upsert_sport_non_duplica(db):
    db.upsert_sport("1", "Calcio", seen_at=1)
    db.upsert_sport("1", "Calcio (agg.)", seen_at=2)   # stesso event_type_id
    rows = db.fetchall("betfair_sports")
    assert len(rows) == 1
    assert rows[0]["name"] == "Calcio (agg.)"          # aggiornato, non duplicato


def test_upsert_market_non_duplica(db):
    db.upsert_market("1.23", "ev1", "1", "Match Odds", "MATCH_ODDS", seen_at=1)
    db.upsert_market("1.23", "ev1", "1", "Esito Finale", "MATCH_ODDS", seen_at=2)
    assert db.count_active("betfair_markets") == 1


# ── stesso nome squadra in eventi diversi NON viene scartato ──────────────────

def test_stesso_nome_in_eventi_diversi_non_scartato(db):
    # Due eventi diversi (event_id diverso) con lo stesso nome: entrambi presenti.
    db.upsert_event("ev1", "1", "compA", "Inter v Milan", seen_at=1)
    db.upsert_event("ev2", "1", "compB", "Inter v Milan", seen_at=1)
    events = db.get_events()
    assert len(events) == 2
    assert {e["event_id"] for e in events} == {"ev1", "ev2"}


# ── selection_id uguale in market diversi: nessun conflitto ───────────────────

def test_selection_id_uguale_in_market_diversi_nessun_conflitto(db):
    # Stesso selection_id (47972) in due market diversi → due righe distinte.
    db.upsert_selection("1.10", "47972", "Inter", seen_at=1)
    db.upsert_selection("1.20", "47972", "Inter", seen_at=1)
    assert db.count_active("betfair_selections") == 2
    assert len(db.get_selections("1.10")) == 1
    assert len(db.get_selections("1.20")) == 1


def test_selezione_chiave_include_handicap(db):
    # Stesso market+selection ma handicap diverso → due selezioni (es. linee Asian).
    db.upsert_selection("1.10", "47972", "Over", handicap=2.5, seen_at=1)
    db.upsert_selection("1.10", "47972", "Over", handicap=3.5, seen_at=1)
    assert db.count_active("betfair_selections") == 2
    # stesso handicap → upsert, non duplica
    db.upsert_selection("1.10", "47972", "Over (agg)", handicap=2.5, seen_at=2)
    assert db.count_active("betfair_selections") == 2


def test_norm_handicap():
    assert _norm_handicap(None) == 0.0
    assert _norm_handicap("") == 0.0
    assert _norm_handicap("2.5") == 2.5
    assert _norm_handicap("x") == 0.0


# ── record non più visti diventano inattivi ───────────────────────────────────

def test_deactivate_unseen_marca_inactive_i_non_visti(db):
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=10)
    db.upsert_event("ev2", "1", "c", "C v D", seen_at=10)
    # nuova sync (seen_at=20) rivede solo ev1
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=20)
    n = db.deactivate_unseen("betfair_events", seen_at=20)
    assert n == 1                                   # ev2 disattivato
    assert db.count_active("betfair_events") == 1   # solo ev1 attivo


def test_deactivate_unseen_scope_per_sport(db):
    # Sync del solo Calcio (event_type_id=1) non deve disattivare eventi del Tennis (2).
    db.upsert_event("calcio1", "1", "c", "A v B", seen_at=10)
    db.upsert_event("tennis1", "2", "c", "X v Y", seen_at=10)
    # nuova sync vede solo calcio (nuovo evento), scope sul Calcio
    db.upsert_event("calcio2", "1", "c", "C v D", seen_at=20)
    db.deactivate_unseen("betfair_events", seen_at=20, scope_value="1")
    rows = {e["event_id"]: e["active"] for e in db.get_events()}
    assert rows["calcio1"] == 0     # non rivisto nel suo sport → inattivo
    assert rows["calcio2"] == 1     # rivisto
    assert rows["tennis1"] == 1     # altro sport: intatto


def test_riattivazione_se_ricompare(db):
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=10)
    db.deactivate_unseen("betfair_events", seen_at=20)   # ev1 non rivisto → inactive
    assert db.count_active("betfair_events") == 0
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=30)  # ricompare
    assert db.count_active("betfair_events") == 1          # riattivato


def test_deactivate_unseen_tabella_non_valida(db):
    with pytest.raises(ValueError):
        db.deactivate_unseen("sqlite_master", seen_at=1)


# ── sync run + name mapping locali ────────────────────────────────────────────

def test_record_sync_run(db):
    rid = db.record_sync_run(started_at=100, finished_at=200, status="OK",
                             summary="2 eventi")
    assert isinstance(rid, int)
    runs = db.fetchall("betfair_sync_runs")
    assert len(runs) == 1 and runs[0]["status"] == "OK"


def test_name_mapping_per_sport_non_duplica(db):
    db.upsert_name_mapping("Calcio", "juve", "Juventus", "team", seen_at=1)
    db.upsert_name_mapping("Calcio", "juve", "Juventus FC", "team", seen_at=2)
    # stesso sport+nome → upsert; sport diverso → riga distinta
    db.upsert_name_mapping("Tennis", "juve", "Juve Tennis", "player", seen_at=1)
    rows = db.fetchall("betfair_local_name_mappings")
    assert len(rows) == 2
