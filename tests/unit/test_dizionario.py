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
