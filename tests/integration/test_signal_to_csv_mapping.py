"""Integrazione: segnale parsato → build_csv_row → riga CSV italiana (PR-08).

Verifica che, quando l'alias è riconosciuto, la riga CSV usi i valori italiani
del dizionario e resti valida per il riconoscimento NAME_ONLY.
"""

from xtrader_bridge import recognition
from xtrader_bridge.csv_writer import CSV_HEADER, build_csv_row


def _parsed(signal_type, teams="Inter v Milan", quota="1.85", bet_type="BACK"):
    return {"signal_type": signal_type, "teams": teams, "quota": quota, "bet_type": bet_type}


def test_over25_diventa_riga_italiana():
    row = build_csv_row(_parsed("OVER 2.5"), "PBet")
    assert row["MarketType"] == "OVER_UNDER_25"
    assert row["MarketName"] == "Over/Under 2,5 gol"
    assert row["SelectionName"] == "Over 2,5 goal"
    assert row["BetType"] == "PUNTA"
    assert row["Handicap"] == "0"      # dal dizionario (over/under: Handicap 0, non la linea)
    assert row["Points"] == ""
    assert list(row.keys()) == CSV_HEADER
    assert recognition.is_valid(row, "NAME_ONLY") is True


def test_gg_diventa_btts_si():
    row = build_csv_row(_parsed("GG"), "PBet")
    assert row["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert row["SelectionName"] == "Sì"


def test_esito_1_usa_nome_squadra_casa():
    row = build_csv_row(_parsed("1", teams="Inter v Milan"), "PBet")
    assert row["MarketType"] == "MATCH_ODDS"
    assert row["EventName"] == "Inter v Milan"
    assert row["SelectionName"] == "Inter"


def test_lay_resta_banca_anche_con_mapping():
    # Il lato (PUNTA/BANCA) viene dal segnale, non dal dizionario.
    row = build_csv_row(_parsed("OVER 2.5", bet_type="LAY"), "PBet")
    assert row["BetType"] == "BANCA"


def test_away_shorthand_senza_squadra_ospite_e_scartabile():
    # teams senza " v " -> away vuoto. "2" (ospite) non risolvibile:
    # SelectionName vuoto -> NON valido (verrà scartato dal bridge), niente placeholder.
    row = build_csv_row(_parsed("2", teams="Inter - Milan"), "PBet")
    assert row["SelectionName"] == ""
    assert "{" not in row["SelectionName"]
    assert recognition.is_valid(row, "NAME_ONLY") is False


def test_over25_live_mappa_selezione_corretta():
    # Con LIVE nel testo, la selezione deve restare "Over 2,5 goal", non quella legacy.
    from xtrader_bridge.parser import parse_message
    row = build_csv_row(parse_message("P.Bet. OVER 2.5 LIVE\nInter v Milan\nQuota 1,85"), "PBet")
    assert row["MarketType"] == "OVER_UNDER_25"
    assert row["SelectionName"] == "Over 2,5 goal"


def test_segnale_non_supportato_e_scartabile():
    # Nessun mapping (né dizionario né legacy): non fabbricare MATCH_ODDS/home.
    row = build_csv_row(_parsed("MERCATO INESISTENTE", teams="Inter v Milan"), "PBet")
    assert row["MarketType"] == ""
    assert row["SelectionName"] == ""
    assert recognition.is_valid(row, "NAME_ONLY") is False


def test_segnale_non_mappato_usa_fallback():
    # "MATCH ODDS" non è una forma breve mappata: fallback legacy, selezione = casa.
    row = build_csv_row(_parsed("MATCH ODDS", teams="Inter v Milan"), "PBet")
    assert row["MarketType"] == "MATCH_ODDS"
    assert row["SelectionName"] == "Inter"
    assert row["MarketName"] == "MATCH ODDS"
