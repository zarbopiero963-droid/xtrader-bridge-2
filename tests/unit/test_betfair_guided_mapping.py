"""Test della logica PURA del «Mapping guidato» Betfair → nome canale (Fase 3 collaudo Betfair).

Esercita `xtrader_bridge.betfair.guided_mapping`:
- `competitions_for_sport`: competizioni attive per sport (scope event_type_id, dedup, ordine);
- `teams_for_competition`: unione participant_1/2 degli eventi di una competizione (dedup, vuoti
  scartati, include eventi disattivati);
- `merge_team_aliases`: fonde squadra→alias nel profilo senza toccare le altre righe (update, non
  duplica; alias vuoto rimuove);
- `existing_aliases_for_teams`: pre-compilazione dagli alias già salvati.

Niente GUI, niente rete: DB Betfair in memoria + dict di profilo puri.
"""

import pytest

from xtrader_bridge.betfair import guided_mapping as gm
from xtrader_bridge.betfair.local_db import BetfairLocalDB


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


def _seed(d):
    """Calcio (etid 1): Serie A (c1) con Inter v Milan (e1), Roma v Lazio (e2). Tennis (etid 2):
    ATP (c2) con Sinner v Alcaraz (e3). Ritorna il marker usato."""
    m = d.new_sync_marker()
    d.upsert_sport("1", "Calcio", seen_at=m)
    d.upsert_sport("2", "Tennis", seen_at=m)
    d.upsert_competition("c1", "1", "Serie A", seen_at=m)
    d.upsert_competition("c2", "2", "ATP", seen_at=m)
    d.upsert_event("e1", "1", "c1", "Inter v Milan",
                   participant_1="Inter", participant_2="Milan", seen_at=m)
    d.upsert_event("e2", "1", "c1", "Roma v Lazio",
                   participant_1="Roma", participant_2="Lazio", seen_at=m)
    d.upsert_event("e3", "2", "c2", "Sinner v Alcaraz",
                   participant_1="Sinner", participant_2="Alcaraz", seen_at=m)
    return m


# ── competitions_for_sport ────────────────────────────────────────────────────

def test_competitions_scope_per_sport(db):
    _seed(db)
    comps = gm.competitions_for_sport(db, "Calcio")
    assert comps == [{"competition_id": "c1", "name": "Serie A"}]
    # case-insensitive sullo sport
    assert gm.competitions_for_sport(db, "tennis") == [{"competition_id": "c2", "name": "ATP"}]


def test_competitions_sport_ignoto_vuoto(db):
    _seed(db)
    assert gm.competitions_for_sport(db, "Cricket") == []
    assert gm.competitions_for_sport(db, "") == []
    assert gm.competitions_for_sport(db, None) == []


def test_competitions_solo_attive_e_ordinate(db):
    m = db.new_sync_marker()
    db.upsert_sport("1", "Calcio", seen_at=m)
    db.upsert_competition("c1", "1", "Serie B", seen_at=m)
    db.upsert_competition("c2", "1", "Serie A", seen_at=m)
    db.upsert_competition("c3", "1", "Coppa Italia", seen_at=m)
    # disattiva Serie B con una sync successiva che non la rivede.
    m2 = db.new_sync_marker()
    db.upsert_competition("c2", "1", "Serie A", seen_at=m2)
    db.upsert_competition("c3", "1", "Coppa Italia", seen_at=m2)
    db.deactivate_unseen("betfair_competitions", seen_at=m2)   # c1 (Serie B) → inattiva
    comps = gm.competitions_for_sport(db, "Calcio")
    # solo le attive, ordinate per nome (case-insensitive)
    assert comps == [{"competition_id": "c3", "name": "Coppa Italia"},
                     {"competition_id": "c2", "name": "Serie A"}]


# ── competition_labels (disambiguazione tendina) ──────────────────────────────

def test_competition_labels_univoche_semplici():
    comps = [{"competition_id": "c2", "name": "Serie A"},
             {"competition_id": "c1", "name": "Coppa Italia"}]
    assert gm.competition_labels(comps) == [("Serie A", "c2"), ("Coppa Italia", "c1")]


def test_competition_labels_disambigua_nomi_omonimi():
    """Due competizioni con lo STESSO nome → label distinte con l'id, così la tendina risolve
    la competizione esatta (Fable/Fugu #389)."""
    comps = [{"competition_id": "c1", "name": "Premier League"},
             {"competition_id": "c2", "name": "Premier League"}]
    labels = gm.competition_labels(comps)
    assert labels == [("Premier League [c1]", "c1"), ("Premier League [c2]", "c2")]
    # ogni label mappa a UNA sola competizione
    assert dict(labels)["Premier League [c1]"] == "c1"
    assert dict(labels)["Premier League [c2]"] == "c2"


def test_competition_labels_fallback_su_collisione_residua():
    # id ripetuti (dato anomalo): la riserva «#n» garantisce comunque label univoche.
    comps = [{"competition_id": "x", "name": "Cup"},
             {"competition_id": "x", "name": "Cup"}]
    labels = [lbl for lbl, _ in gm.competition_labels(comps)]
    assert len(set(labels)) == 2                       # nessuna label duplicata


def test_competition_labels_nome_vuoto():
    labels = gm.competition_labels([{"competition_id": "c1", "name": ""}])
    assert labels == [("(senza nome)", "c1")]


# ── teams_for_competition ─────────────────────────────────────────────────────

def test_teams_union_participant(db):
    _seed(db)
    teams = gm.teams_for_competition(db, "c1")
    assert teams == ["Inter", "Lazio", "Milan", "Roma"]   # union, dedup, ordinati


def test_teams_scope_per_competizione(db):
    _seed(db)
    # gli eventi di c2 (Tennis) non finiscono in c1 (Calcio)
    assert gm.teams_for_competition(db, "c2") == ["Alcaraz", "Sinner"]
    assert gm.teams_for_competition(db, "c1") == ["Inter", "Lazio", "Milan", "Roma"]


def test_teams_scarta_vuoti_e_dedup(db):
    m = db.new_sync_marker()
    db.upsert_sport("1", "Calcio", seen_at=m)
    db.upsert_competition("c1", "1", "Serie A", seen_at=m)
    # evento outright: participant_2 vuoto → non deve produrre una squadra vuota
    db.upsert_event("e1", "1", "c1", "Vincente Serie A",
                    participant_1="Inter", participant_2="", seen_at=m)
    # duplicato con casing diverso: dedup (tiene la prima occorrenza)
    db.upsert_event("e2", "1", "c1", "Inter v Milan",
                    participant_1="inter", participant_2="Milan", seen_at=m)
    teams = gm.teams_for_competition(db, "c1")
    assert teams == ["Inter", "Milan"]                    # niente stringa vuota, niente doppione


def test_teams_include_eventi_disattivati(db):
    """Le squadre includono anche gli eventi passati/disattivati (roster storico mappabile)."""
    m = db.new_sync_marker()
    db.upsert_sport("1", "Calcio", seen_at=m)
    db.upsert_competition("c1", "1", "Serie A", seen_at=m)
    db.upsert_event("e1", "1", "c1", "Inter v Milan",
                    participant_1="Inter", participant_2="Milan", seen_at=m)
    # una sync successiva non rivede e1 → evento disattivato
    m2 = db.new_sync_marker()
    db.deactivate_unseen("betfair_events", seen_at=m2)
    assert not gm._is_active(db.fetchall("betfair_events")[0])   # sanity: e1 ora inattivo
    # le sue squadre restano comunque disponibili per la mappatura
    assert gm.teams_for_competition(db, "c1") == ["Inter", "Milan"]


def test_teams_competizione_vuota_o_none(db):
    _seed(db)
    assert gm.teams_for_competition(db, "non_esiste") == []
    assert gm.teams_for_competition(db, "") == []
    assert gm.teams_for_competition(db, None) == []


# ── merge_team_aliases ────────────────────────────────────────────────────────

def test_merge_aggiunge_righe_squadra():
    entries = []
    out = gm.merge_team_aliases(entries, "Calcio",
                                {"Inter": "Inter Milan", "Milan": "AC Milan"})
    assert {r["betfair"]: r["provider"] for r in out} == {"Inter": "Inter Milan", "Milan": "AC Milan"}
    for r in out:
        assert r["sport"] == "Calcio" and r["entity_type"] == "team" and r["country"] == ""


def test_merge_aggiorna_non_duplica():
    """Ri-salvare una squadra già mappata AGGIORNA l'alias invece di creare un doppione."""
    entries = [{"country": "", "betfair": "Inter", "provider": "Inter", "sport": "Calcio",
                "entity_type": "team"}]
    out = gm.merge_team_aliases(entries, "Calcio", {"Inter": "Inter Milan"})
    inter_rows = [r for r in out if gm.normalize(r["betfair"]) == gm.normalize("Inter")]
    assert len(inter_rows) == 1                            # niente duplicato
    assert inter_rows[0]["provider"] == "Inter Milan"      # alias aggiornato


def test_merge_alias_vuoto_rimuove():
    """Alias vuoto per una squadra editata rimuove la sua riga precedente (nessuna nuova riga)."""
    entries = [{"country": "", "betfair": "Inter", "provider": "Inter Milan", "sport": "Calcio",
                "entity_type": "team"}]
    out = gm.merge_team_aliases(entries, "Calcio", {"Inter": "   "})
    assert out == []


def test_merge_lascia_intatte_le_altre_righe():
    """Non deve toccare righe di altri sport, mercati o entity diverse."""
    entries = [
        {"country": "", "betfair": "Sinner", "provider": "J. Sinner", "sport": "Tennis",
         "entity_type": "team"},                          # altro sport
        {"country": "", "betfair": "Inter", "provider": "Inter FC", "sport": "Calcio",
         "entity_type": "player"},                        # stesso nome ma entity diversa
        {"country": "", "betfair": "1X2", "provider": "Match Odds", "sport": "Calcio",
         "entity_type": "market"},                        # mercato
    ]
    out = gm.merge_team_aliases(entries, "Calcio", {"Inter": "Inter Milan"})
    # le 3 righe originali restano + la nuova riga team Inter
    assert entries[0] in out and entries[1] in out and entries[2] in out
    new_rows = [r for r in out if r not in entries]
    assert new_rows == [{"country": "", "betfair": "Inter", "provider": "Inter Milan",
                         "sport": "Calcio", "entity_type": "team"}]


def test_merge_case_insensitive_su_squadra_e_sport():
    """Il match per l'update è case/space-insensitive su squadra e sport (via normalize)."""
    entries = [{"country": "", "betfair": "inter  milan", "provider": "old", "sport": "calcio",
                "entity_type": "team"}]
    out = gm.merge_team_aliases(entries, "Calcio", {"Inter Milan": "new alias"})
    rows = [r for r in out if gm.normalize(r["betfair"]) == gm.normalize("Inter Milan")]
    assert len(rows) == 1 and rows[0]["provider"] == "new alias"


# ── existing_aliases_for_teams ────────────────────────────────────────────────

def test_existing_aliases_precompila():
    entries = [
        {"country": "", "betfair": "Inter", "provider": "Inter Milan", "sport": "Calcio",
         "entity_type": "team"},
        {"country": "", "betfair": "Sinner", "provider": "J. Sinner", "sport": "Tennis",
         "entity_type": "team"},                          # altro sport: ignorato
    ]
    got = gm.existing_aliases_for_teams(entries, "Calcio", ["Inter", "Milan"])
    assert got == {"Inter": "Inter Milan"}                # Milan non ha mapping → assente


def test_existing_aliases_prima_riga_vince():
    entries = [
        {"country": "", "betfair": "Inter", "provider": "primo", "sport": "Calcio",
         "entity_type": "team"},
        {"country": "", "betfair": "Inter", "provider": "secondo", "sport": "Calcio",
         "entity_type": "team"},
    ]
    assert gm.existing_aliases_for_teams(entries, "Calcio", ["Inter"]) == {"Inter": "primo"}
