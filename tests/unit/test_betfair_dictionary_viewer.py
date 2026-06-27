"""Test del viewer (SOLA LETTURA) del dizionario Betfair locale (issue #86 PR-P11).

Copre il controller puro `DictionaryViewerController`: vista tabellare per livello,
scoping per sport (event_type_id per sport/competizioni/eventi/mercati; market_id per le
selezioni), filtro «solo attivi», conteggi, formattazione celle e livello non valido.
Nessuna GUI, nessuna rete: DB in memoria.
"""

import pytest

from xtrader_bridge.betfair.dictionary_viewer import (
    DictionaryViewerController,
    LEVELS,
    LEVEL_LABELS,
)
from xtrader_bridge.betfair.local_db import BetfairLocalDB


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


def _seed(d):
    """Dizionario di prova: Calcio (etid 1) e Tennis (etid 2). Ritorna il marker della
    sync usato (così i test di disattivazione possono usarne uno successivo)."""
    m = d.new_sync_marker()
    d.upsert_sport("1", "Calcio", seen_at=m)
    d.upsert_sport("2", "Tennis", seen_at=m)
    d.upsert_competition("c1", "1", "Serie A", seen_at=m)
    d.upsert_competition("c2", "2", "ATP", seen_at=m)
    d.upsert_event("e1", "1", "c1", "Inter v Milan", seen_at=m)
    d.upsert_event("e2", "2", "c2", "Sinner v Alcaraz", seen_at=m)
    d.upsert_market("m1", "e1", "1", "Match Odds", "MATCH_ODDS", seen_at=m)
    d.upsert_market("m2", "e2", "2", "Match Odds", "MATCH_ODDS", seen_at=m)
    d.upsert_selection("m1", "s1", "Inter", seen_at=m)
    d.upsert_selection("m2", "s2", "Sinner", seen_at=m)
    return m


def test_view_eventi_senza_sport_mostra_tutto(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("events")
    assert v["total"] == 2 and v["active"] == 2
    nomi = [r[1] for r in v["rows"]]          # colonna "Evento"
    assert "Inter v Milan" in nomi and "Sinner v Alcaraz" in nomi


def test_view_eventi_scoping_per_sport(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("events", sport="Calcio")
    assert v["total"] == 1
    assert v["rows"][0][1] == "Inter v Milan"
    # case-insensitive
    assert ctrl.view("events", sport="tennis")["rows"][0][1] == "Sinner v Alcaraz"


def test_view_selezioni_scoping_via_market_id(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    # le selezioni non hanno event_type_id: lo scope passa dai market_id dello sport.
    v = ctrl.view("selections", sport="Calcio")
    assert v["total"] == 1
    assert v["rows"][0][2] == "Inter"         # colonna "Selezione" (runner_name)
    assert ctrl.view("selections", sport="Tennis")["rows"][0][2] == "Sinner"


def test_view_sport_ignoto_nessun_filtro(db):
    # Sport non supportato/non specificato → nessun filtro (tutte le righe in scope).
    _seed(db)
    ctrl = DictionaryViewerController(db)
    assert ctrl.view("events", sport="Cricket")["total"] == 2
    assert ctrl.view("events", sport="")["total"] == 2
    assert ctrl.view("events", sport=None)["total"] == 2


def test_view_solo_attivi(db):
    _seed(db)
    # disattiva e2 (Tennis) simulando una sync successiva (marker maggiore) che non lo rivede.
    marker = db.new_sync_marker()
    db.upsert_event("e1", "1", "c1", "Inter v Milan", seen_at=marker)   # rivisto
    db.deactivate_unseen("betfair_events", seen_at=marker)              # e2 → inattivo
    ctrl = DictionaryViewerController(db)
    v_all = ctrl.view("events")
    assert v_all["total"] == 2 and v_all["active"] == 1                 # conteggi: 2 tot, 1 attivo
    assert len(v_all["rows"]) == 2                                      # senza filtro: entrambe
    v_active = ctrl.view("events", active_only=True)
    assert len(v_active["rows"]) == 1                                   # solo attivo
    assert v_active["rows"][0][1] == "Inter v Milan"


def test_active_column_formattata_si_no(db):
    _seed(db)
    marker = db.new_sync_marker()                                       # marker successivo
    db.upsert_event("e1", "1", "c1", "Inter v Milan", seen_at=marker)
    db.deactivate_unseen("betfair_events", seen_at=marker)              # e2 → inattivo
    ctrl = DictionaryViewerController(db)
    rows = {r[1]: r[-1] for r in ctrl.view("events")["rows"]}           # Evento → Attivo
    assert rows["Inter v Milan"] == "sì"
    assert rows["Sinner v Alcaraz"] == "no"


def test_counts_per_sport(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    c = ctrl.counts(sport="Calcio")
    assert c["sports"]["total"] == 1          # solo l'event_type 1
    assert c["events"]["total"] == 1
    assert c["markets"]["total"] == 1
    assert c["selections"]["total"] == 1
    # senza sport: tutto
    c_all = ctrl.counts()
    assert c_all["events"]["total"] == 2 and c_all["selections"]["total"] == 2


def test_columns_e_livelli(db):
    ctrl = DictionaryViewerController(db)
    assert ctrl.levels() == list(LEVELS)
    assert "Evento" in ctrl.columns("events")
    # ogni livello ha un'etichetta italiana
    for lvl in LEVELS:
        assert lvl in LEVEL_LABELS


def test_livello_non_valido_solleva(db):
    ctrl = DictionaryViewerController(db)
    with pytest.raises(ValueError):
        ctrl.view("scommesse")
    with pytest.raises(ValueError):
        ctrl.columns("xyz")


def test_db_vuoto_nessuna_riga(db):
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("events")
    assert v["total"] == 0 and v["active"] == 0 and v["rows"] == []


# ── Ricerca testuale (issue #178 §1: "Ricerca partecipante" / "Ricerca selection") ──

def test_view_ricerca_evento(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("events", search="inter")          # case-insensitive, sottostringa
    assert v["total"] == 1
    assert v["rows"][0][1] == "Inter v Milan"


def test_view_ricerca_partecipante(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    # cerca su participant_1/participant_2: "Sinner" è un partecipante dell'evento tennis.
    v = ctrl.view("events", search="alcaraz")
    assert v["total"] == 1
    assert v["rows"][0][1] == "Sinner v Alcaraz"


def test_view_ricerca_selezione(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("selections", search="sinner")     # runner_name
    assert v["total"] == 1
    assert v["rows"][0][2] == "Sinner"


def test_view_ricerca_nessun_match(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    assert ctrl.view("events", search="zzz-non-esiste")["total"] == 0


def test_view_ricerca_vuota_o_none_nessun_filtro(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    assert ctrl.view("events", search="")["total"] == 2
    assert ctrl.view("events", search=None)["total"] == 2


def test_view_ricerca_e_sport_combinati(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    # "v" è in entrambi i nomi evento ma lo sport restringe a Calcio.
    v = ctrl.view("events", sport="Calcio", search="v ")
    assert v["total"] == 1 and v["rows"][0][1] == "Inter v Milan"


# ── Filtri drill-down (issue #178 §1: "Filtro competizione / evento / mercato") ──

def test_filtro_competizione_su_eventi(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("events", filters={"competition_id": "c1"})
    assert v["total"] == 1 and v["rows"][0][1] == "Inter v Milan"


def test_filtro_evento_su_mercati(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("markets", filters={"event_id": "e2"})
    assert v["total"] == 1
    # colonna Event ID è la seconda del livello markets
    assert v["rows"][0][1] == "e2"


def test_filtro_mercato_su_selezioni(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("selections", filters={"market_id": "m1"})
    assert v["total"] == 1 and v["rows"][0][2] == "Inter"


def test_filtro_chiave_inesistente_ignorata(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    # una chiave non colonna del livello non azzera la vista (fail-open per il viewer)
    assert ctrl.view("events", filters={"non_esiste": "x"})["total"] == 2


def test_filtro_e_ricerca_combinati(db):
    _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("markets", filters={"event_id": "e1"}, search="match")
    assert v["total"] == 1 and v["rows"][0][1] == "e1"


# ── Colonna last_seen_at (issue #178 §1: "last_seen_at non mostrato") ──

def test_last_seen_at_in_colonne_di_ogni_livello(db):
    ctrl = DictionaryViewerController(db)
    for lvl in LEVELS:
        assert "Ultima sync" in ctrl.columns(lvl)
    # "Attivo" resta l'ultima colonna (i test esistenti usano r[-1] per l'attivo)
    assert ctrl.columns("events")[-1] == "Attivo"


def test_last_seen_at_valorizzato_nelle_righe(db):
    m = _seed(db)
    ctrl = DictionaryViewerController(db)
    v = ctrl.view("events")
    cols = v["columns"]
    idx = cols.index("Ultima sync")
    # il marker della sync è > 0 e viene mostrato come stringa non vuota
    assert all(r[idx] == str(m) for r in v["rows"])
