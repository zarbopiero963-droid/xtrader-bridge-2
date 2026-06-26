"""Test del risolutore ID dal dizionario Betfair locale (issue #86 PR-P12).

`DictionaryResolver` (sola lettura) trova EventId/MarketId/SelectionId per una riga a
nomi, ristretti allo sport. È **all-or-nothing e conservativo**: ritorna gli ID solo se
l'intera catena evento→mercato→selezione è univoca; altrimenti `{}` (fallback nomi).
"""

import pytest

from xtrader_bridge.betfair.dictionary_resolver import DictionaryResolver
from xtrader_bridge.betfair.local_db import BetfairLocalDB


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


def _seed(d):
    m = d.new_sync_marker()
    # Calcio (etid 1): Inter v Milan, Match Odds, selezione "Inter".
    d.upsert_event("ev_im", "1", "c1", "Inter v Milan",
                   participant_1="Inter", participant_2="Milan", seen_at=m)
    d.upsert_market("mk_im", "ev_im", "1", "Match Odds", "MATCH_ODDS", seen_at=m)
    d.upsert_selection("mk_im", "sel_inter", "Inter", seen_at=m)
    d.upsert_selection("mk_im", "sel_milan", "Milan", seen_at=m)
    # Tennis (etid 2): un evento con lo STESSO nome evento per testare lo scoping sport.
    d.upsert_event("ev_t", "2", "c2", "Inter v Milan",
                   participant_1="Inter", participant_2="Milan", seen_at=m)
    d.upsert_market("mk_t", "ev_t", "2", "Match Odds", "MATCH_ODDS", seen_at=m)
    d.upsert_selection("mk_t", "sel_t", "Inter", seen_at=m)
    return m


def test_catena_completa_risolve_gli_id(db):
    _seed(db)
    r = DictionaryResolver(db)
    ids = r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                        market_type="MATCH_ODDS", selection_name="Inter")
    assert ids == {"EventId": "ev_im", "MarketId": "mk_im", "SelectionId": "sel_inter"}


def test_match_evento_per_partecipanti_ordine_indifferente(db):
    _seed(db)
    r = DictionaryResolver(db)
    # EventName canonico con squadre invertite: combacia comunque per set di partecipanti.
    ids = r.resolve_ids(sport="Calcio", event_name="Milan - Inter",
                        market_type="MATCH_ODDS", selection_name="Milan")
    assert ids["EventId"] == "ev_im" and ids["SelectionId"] == "sel_milan"


def test_scoping_sport_evita_match_di_altro_sport(db):
    _seed(db)
    r = DictionaryResolver(db)
    # Stesso nome evento esiste in Calcio e Tennis: lo sport del parser disambigua.
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="MATCH_ODDS", selection_name="Inter")["EventId"] == "ev_im"
    assert r.resolve_ids(sport="Tennis", event_name="Inter - Milan",
                         market_type="MATCH_ODDS", selection_name="Inter")["EventId"] == "ev_t"


def test_evento_non_trovato_ritorna_vuoto(db):
    _seed(db)
    r = DictionaryResolver(db)
    assert r.resolve_ids(sport="Calcio", event_name="Roma - Lazio",
                         market_type="MATCH_ODDS", selection_name="Roma") == {}


def test_mercato_non_trovato_ritorna_vuoto(db):
    _seed(db)
    r = DictionaryResolver(db)
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="OVER_UNDER_25", selection_name="Inter") == {}


def test_selezione_non_trovata_ritorna_vuoto(db):
    _seed(db)
    r = DictionaryResolver(db)
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="MATCH_ODDS", selection_name="Pareggio") == {}


def test_sport_assente_o_ignoto_ritorna_vuoto(db):
    _seed(db)
    r = DictionaryResolver(db)
    assert r.resolve_ids(sport="", event_name="Inter - Milan",
                         market_type="MATCH_ODDS", selection_name="Inter") == {}
    assert r.resolve_ids(sport="Cricket", event_name="Inter - Milan",
                         market_type="MATCH_ODDS", selection_name="Inter") == {}


def test_evento_ambiguo_ritorna_vuoto(db):
    # Due eventi attivi dello stesso sport con lo STESSO nome → ambiguo → nessun ID.
    m = db.new_sync_marker()
    db.upsert_event("e1", "1", "c", "Inter v Milan",
                    participant_1="Inter", participant_2="Milan", seen_at=m)
    db.upsert_event("e2", "1", "c", "Inter v Milan",
                    participant_1="Inter", participant_2="Milan", seen_at=m)
    db.upsert_market("m1", "e1", "1", "Match Odds", "MATCH_ODDS", seen_at=m)
    db.upsert_selection("m1", "s1", "Inter", seen_at=m)
    r = DictionaryResolver(db)
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="MATCH_ODDS", selection_name="Inter") == {}


def test_record_inattivi_ignorati(db):
    _seed(db)
    # disattiva l'evento calcio: non deve più risolvere.
    marker = db.new_sync_marker()
    db.deactivate_unseen("betfair_events", seen_at=marker)
    r = DictionaryResolver(db)
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="MATCH_ODDS", selection_name="Inter") == {}


def test_selezione_disambiguata_da_handicap(db):
    m = db.new_sync_marker()
    db.upsert_event("e", "1", "c", "Inter v Milan",
                    participant_1="Inter", participant_2="Milan", seen_at=m)
    db.upsert_market("mk", "e", "1", "Asian Handicap", "ASIAN_HANDICAP", seen_at=m)
    # due selezioni con lo STESSO runner_name ma handicap diverso.
    db.upsert_selection("mk", "s_05", "Inter", handicap=0.5, seen_at=m)
    db.upsert_selection("mk", "s_15", "Inter", handicap=1.5, seen_at=m)
    r = DictionaryResolver(db)
    # senza handicap: ambiguo → nessun ID.
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="ASIAN_HANDICAP", selection_name="Inter") == {}
    # con handicap: disambigua sulla selezione giusta.
    ids = r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                        market_type="ASIAN_HANDICAP", selection_name="Inter", handicap="1.5")
    assert ids.get("SelectionId") == "s_15"


def test_match_mercato_per_nome_se_manca_il_tipo(db):
    _seed(db)
    r = DictionaryResolver(db)
    ids = r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                        market_type="", market_name="Match Odds", selection_name="Inter")
    assert ids.get("MarketId") == "mk_im"


def test_handicap_con_virgola_disambigua(db):
    m = db.new_sync_marker()
    db.upsert_event("e", "1", "c", "Inter v Milan",
                    participant_1="Inter", participant_2="Milan", seen_at=m)
    db.upsert_market("mk", "e", "1", "Asian Handicap", "ASIAN_HANDICAP", seen_at=m)
    db.upsert_selection("mk", "s_05", "Inter", handicap=0.5, seen_at=m)
    db.upsert_selection("mk", "s_15", "Inter", handicap=1.5, seen_at=m)
    r = DictionaryResolver(db)
    # handicap del parser con la VIRGOLA ("1,5") deve combaciare col REAL 1.5 del DB (Codex).
    ids = r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                        market_type="ASIAN_HANDICAP", selection_name="Inter", handicap="1,5")
    assert ids.get("SelectionId") == "s_15"


def test_singola_selezione_richiede_accordo_handicap(db):
    # UNA sola selezione col nome richiesto, ma a handicap 1.5: una riga con Handicap 0
    # (default) NON deve essere arricchita con quella SelectionId (punterebbe a una linea
    # diversa). Serve accordo sull'handicap anche nel caso a runner singolo (Codex P1).
    m = db.new_sync_marker()
    db.upsert_event("e", "1", "c", "Inter v Milan",
                    participant_1="Inter", participant_2="Milan", seen_at=m)
    db.upsert_market("mk", "e", "1", "Asian Handicap", "ASIAN_HANDICAP", seen_at=m)
    db.upsert_selection("mk", "s_15", "Inter", handicap=1.5, seen_at=m)   # UNICA "Inter"
    r = DictionaryResolver(db)
    # handicap di riga 0 (default contratto) ≠ 1.5 → nessun ID (fallback nomi).
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="ASIAN_HANDICAP", selection_name="Inter",
                         handicap="0") == {}
    # handicap assente → trattato come 0 → comunque nessun match con 1.5.
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="ASIAN_HANDICAP", selection_name="Inter") == {}
    # handicap di riga 1.5 → combacia → ID risolto.
    assert r.resolve_ids(sport="Calcio", event_name="Inter - Milan",
                         market_type="ASIAN_HANDICAP", selection_name="Inter",
                         handicap="1.5")["SelectionId"] == "s_15"
