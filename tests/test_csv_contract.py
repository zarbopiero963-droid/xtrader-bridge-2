"""Test hard del contratto CSV XTrader (PR-01, aggiornato PR-03).

Esercita le funzioni reali di `xtrader_bridge.csv_writer`. Il contratto a 14
colonne è basato sui CSV di esempio reali del team XTrader. `CONTRACT_HEADER` è
volutamente un letterale indipendente: è la guardia che fa fallire il test se
l'header di produzione cambia per errore.
"""

from xtrader_bridge import csv_writer

# Contratto ufficiale a 14 colonne (vedi docs/xtrader_csv_contract.md).
CONTRACT_HEADER = [
    "Provider", "EventId", "EventName", "MarketId", "MarketName",
    "MarketType", "SelectionId", "SelectionName", "Handicap", "Price",
    "MinPrice", "MaxPrice", "BetType", "Points",
]


def _row(**overrides):
    parsed = {
        "signal_type": "MATCH ODDS", "competition": "Serie A",
        "teams": "Inter v Milan", "score": "1 - 0", "time_": "67m",
        "quota": "1.85", "probability": "72.5", "bet_type": "BACK",
    }
    parsed.update(overrides)
    return csv_writer.build_csv_row(parsed, "PBet")


def test_header_matches_contract_in_order():
    assert csv_writer.CSV_HEADER == CONTRACT_HEADER


def test_header_has_14_columns():
    assert len(csv_writer.CSV_HEADER) == 14


def test_header_has_no_stake_or_timestamp():
    assert "Stake" not in csv_writer.CSV_HEADER
    assert "Timestamp" not in csv_writer.CSV_HEADER


def test_id_columns_present():
    for col in ("EventId", "MarketId", "SelectionId", "Handicap"):
        assert col in csv_writer.CSV_HEADER


def test_build_csv_row_keys_match_header_order():
    # Assert order-sensitive: cattura regressioni nell'ordine delle colonne.
    assert list(_row().keys()) == CONTRACT_HEADER


def test_bettype_back_maps_to_punta():
    assert _row(bet_type="BACK")["BetType"] == "PUNTA"


def test_bettype_lay_maps_to_banca():
    assert _row(bet_type="LAY")["BetType"] == "BANCA"


def test_bettype_lowercase_is_normalized():
    assert _row(bet_type="back")["BetType"] == "PUNTA"
    assert _row(bet_type="lay")["BetType"] == "BANCA"


def test_unsupported_bettype_is_blocked():
    raised = False
    try:
        _row(bet_type="foo")
    except ValueError:
        raised = True
    assert raised, "bet_type non valido deve sollevare ValueError"


def test_points_is_empty_by_default():
    assert _row()["Points"] == csv_writer.DEFAULT_POINTS == ""


def test_handicap_default_is_zero():
    assert _row()["Handicap"] == "0"


def test_ids_empty_when_absent_from_signal():
    row = _row()
    assert row["EventId"] == "" and row["MarketId"] == "" and row["SelectionId"] == ""
