"""Test del dizionario XTrader (PR-07).

Verifica struttura, assenza di alias duplicati e copertura dei mercati/combinazioni
richiesti, basandosi sul file reale `data/dizionario_xtrader.csv`.
"""

from xtrader_bridge import dizionario as dz


def _rows():
    return dz.load_dizionario()


def test_file_caricabile():
    rows = _rows()
    assert len(rows) == 81


def test_header_esatto():
    rows = _rows()
    assert list(rows[0].keys()) == dz.EXPECTED_COLUMNS


def test_nessun_alias_duplicato():
    assert dz.duplicate_alias_pairs(_rows()) == []


def test_ogni_riga_ha_markettype_e_selectionname():
    for row in _rows():
        assert row["MarketType_XTrader"].strip()
        assert row["SelectionName_XTrader"].strip()


def test_bettype_solo_punta_o_banca():
    for row in _rows():
        assert row["BetType_XTrader"] in ("PUNTA", "BANCA")


def test_correct_score_19_selezioni():
    rows = [r for r in _rows() if r["MarketType_XTrader"] == "CORRECT_SCORE"]
    sels = {r["SelectionName_XTrader"] for r in rows}
    # 16 risultati esatti 0-0..3-3 + 3 "Altro"
    for h in range(4):
        for a in range(4):
            assert f"{h} - {a}" in sels
    assert len(rows) == 19


def test_half_time_score_10_selezioni():
    rows = [r for r in _rows() if r["MarketType_XTrader"] == "HALF_TIME_SCORE"]
    sels = {r["SelectionName_XTrader"] for r in rows}
    for h in range(3):
        for a in range(3):
            assert f"{h} - {a}" in sels        # 0-0..2-2
    assert "Qualsiasi altro risultato" in sels
    assert len(rows) == 10


def test_over_under_da_05_a_85():
    mts = dz.market_types(_rows())
    for suffix in ("05", "15", "25", "35", "45", "55", "65", "75", "85"):
        assert f"OVER_UNDER_{suffix}" in mts


def test_first_half_goals_05_15_25():
    mts = dz.market_types(_rows())
    for mt in ("FIRST_HALF_GOALS_05", "FIRST_HALF_GOALS_15", "FIRST_HALF_GOALS_25"):
        assert mt in mts


def test_data_dir_da_meipass_se_frozen(monkeypatch, tmp_path):
    import os
    monkeypatch.setattr(dz.sys, "frozen", True, raising=False)
    monkeypatch.setattr(dz.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert dz._data_dir() == os.path.join(str(tmp_path), "data")


def test_alias_key_normalizza():
    assert dz.alias_key("  Over 0.5 HT ", "OVER 0.5 HT") == ("over 0.5 ht", "over 0.5 ht")


def test_alias_key_collassa_spazi_interni():
    assert dz.alias_key("over   0.5    ht", "Over  0.5  HT") == ("over 0.5 ht", "over 0.5 ht")


def test_duplicate_ignora_righe_con_alias_vuoti():
    rows = [
        {"MarketAliasTelegram": "", "SelectionAliasTelegram": ""},
        {"MarketAliasTelegram": "", "SelectionAliasTelegram": ""},
        {"MarketAliasTelegram": "esito_finale", "SelectionAliasTelegram": "1"},
    ]
    assert dz.duplicate_alias_pairs(rows) == []   # gli alias vuoti non sono duplicati


def test_duplicate_rileva_veri_duplicati():
    rows = [
        {"MarketAliasTelegram": "esito_finale", "SelectionAliasTelegram": "1"},
        {"MarketAliasTelegram": "Esito_Finale", "SelectionAliasTelegram": " 1 "},
    ]
    assert dz.duplicate_alias_pairs(rows) == [("esito_finale", "1")]


# ── Catalogo per le tendine (A1) ────────────────────────────────────────────

def test_market_catalog_22_mercati_senza_duplicati():
    cat = dz.market_catalog()
    assert len(cat) == 22                              # 22 MarketType distinti
    types = [m["MarketType"] for m in cat]
    assert len(types) == len(set(types))               # nessun duplicato
    assert all(m["MarketType"] and m["MarketName"] for m in cat)  # mai vuoti


def test_market_name_type_roundtrip():
    assert dz.market_name_for_type("MATCH_ODDS") == "Esito Finale"
    assert dz.market_type_for_name("Esito Finale") == "MATCH_ODDS"
    # case/space-insensitive sul nome
    assert dz.market_type_for_name("  over/under 2,5 gol ") == "OVER_UNDER_25"
    # sconosciuti → None (niente eccezioni)
    assert dz.market_name_for_type("INESISTENTE") is None
    assert dz.market_type_for_name("Mercato che non esiste") is None


def test_selections_for_market_match_odds():
    # match per MarketType e per MarketName danno lo stesso insieme.
    by_type = dz.selections_for_market("MATCH_ODDS")
    by_name = dz.selections_for_market("Esito Finale")
    assert {s["SelectionName"] for s in by_type} == {s["SelectionName"] for s in by_name}
    names = {s["SelectionName"] for s in by_type}
    assert names == {"{HOME_TEAM}", "{AWAY_TEAM}", "Pareggio"}
    # Home/Away sono dinamiche (placeholder squadra), Pareggio no.
    dyn = {s["SelectionName"]: s["dynamic"] for s in by_type}
    assert dyn["{HOME_TEAM}"] is True
    assert dyn["{AWAY_TEAM}"] is True
    assert dyn["Pareggio"] is False


def test_selections_for_market_over_under_porta_la_linea():
    ou = dz.selections_for_market("OVER_UNDER_25")
    assert {s["SelectionName"] for s in ou} == {"Over 2,5 goal", "Under 2,5 goal"}
    assert all(s["Linea"] == "2.5" and s["dynamic"] is False for s in ou)


def test_selections_for_market_correct_score_19_non_dinamiche():
    cs = dz.selections_for_market("CORRECT_SCORE")
    assert len(cs) == 19
    assert not any(s["dynamic"] for s in cs)


def test_selections_for_market_mercato_ignoto_o_vuoto():
    assert dz.selections_for_market("INESISTENTE") == []
    assert dz.selections_for_market("") == []
    assert dz.selections_for_market(None) == []


def test_has_placeholder():
    assert dz.has_placeholder("{HOME_TEAM}") is True
    assert dz.has_placeholder("{HOME_TEAM} +1") is True
    assert dz.has_placeholder("Pareggio") is False
    assert dz.has_placeholder("Over 2,5 goal") is False


def test_compose_event_name():
    assert dz.compose_event_name("Portogallo", "R.D. Congo") == "Portogallo - R.D. Congo"
    assert dz.compose_event_name("  Inter ", " Milan ") == "Inter - Milan"
    # squadra mancante → l'altra, senza separatore penzolante
    assert dz.compose_event_name("Inter", "") == "Inter"
    assert dz.compose_event_name("", "Milan") == "Milan"
    assert dz.compose_event_name("", "") == ""


def test_fill_placeholders():
    assert dz.fill_placeholders("{HOME_TEAM} +1", home="Inter") == "Inter +1"
    assert dz.fill_placeholders("{AWAY_TEAM}", away="Milan") == "Milan"
    assert dz.fill_placeholders("{EVENT_NAME}", home="Inter", away="Milan") == "Inter - Milan"
    # placeholder senza valore resta invariato (selezione non completabile)
    out = dz.fill_placeholders("{HOME_TEAM}", away="Milan")
    assert out == "{HOME_TEAM}"
    assert dz.has_placeholder(out) is True
