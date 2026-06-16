"""Test del parser robusto P.Bet. (PR-09): emoji + testo, fixtures reali."""

import os

from xtrader_bridge.parser import parse_message

_FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "pbet_messages")


def _fixture(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return f.read()


def test_emoji_completo():
    p = parse_message(_fixture("valid_match_odds_emoji.txt"))
    assert p["signal_type"] == "MATCH ODDS"
    assert p["teams"] == "Inter v Milan"
    assert p["quota"] == "1.85"
    assert p["probability"] == "72.5"
    assert p["bet_type"] == "BACK"


def test_testo_semplice_equivalente_a_emoji():
    p = parse_message(_fixture("valid_over25_text.txt"))
    assert p["signal_type"] == "OVER 2.5"
    assert p["teams"] == "Inter v Milan"        # "Inter vs Milan" normalizzato
    assert p["quota"] == "1.85"
    assert p["probability"] == "72.5"


def test_separatore_trattino_e_banca():
    p = parse_message(_fixture("valid_gg_text.txt"))
    assert p["signal_type"] == "GG"
    assert p["teams"] == "Arsenal v Chelsea"     # "Arsenal - Chelsea" normalizzato
    assert p["quota"] == "1.95"
    assert p["bet_type"] == "LAY"                # "Banca" -> LAY


def test_separatori_normalizzati():
    assert parse_message("P.Bet. 1\nInter vs Milan")["teams"] == "Inter v Milan"
    assert parse_message("P.Bet. 1\nInter - Milan")["teams"] == "Inter v Milan"
    assert parse_message("P.Bet. 1\nInter v Milan")["teams"] == "Inter v Milan"


def test_quota_virgola_e_punto():
    assert parse_message("Quota 2,40")["quota"] == "2.40"
    assert parse_message("Quota 1.95")["quota"] == "1.95"


def test_score_non_scambiato_per_squadre():
    # "Score: 1 - 0" non deve diventare teams.
    p = parse_message("P.Bet. OVER 2.5\nScore: 1 - 0\nInter v Milan")
    assert p["score"] == "1 - 0"
    assert p["teams"] == "Inter v Milan"


def test_live_flag():
    assert parse_message("P.Bet. OVER 2.5 LIVE\nInter v Milan")["live"] is True
    assert parse_message("P.Bet. OVER 2.5 live\nInter v Milan")["live"] is True
    assert parse_message("P.Bet. OVER 2.5 Live\nInter v Milan")["live"] is True
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan")["live"] is False
    # 'live' dentro una parola più lunga non deve attivare il flag (word-boundary).
    assert parse_message("P.Bet. OVER 2.5 delivery\nInter v Milan")["live"] is False
    assert parse_message("P.Bet. OVER 2.5\nLiverpool v Inter")["live"] is False


def test_probabilita_malformata_non_presa_intera():
    # "1.2.3%" non deve produrre "1.2.3" (numero ben formato).
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan\nProbability 1.2.3%")
    assert p["probability"] in ("1.2", "2.3")   # comunque un numero ben formato


def test_vuoto_non_crasha():
    p = parse_message("")
    assert p["signal_type"] == "" and p["teams"] == "" and p["quota"] == ""
    assert p["bet_type"] == "BACK" and p["live"] is False


def test_missing_teams_resta_vuoto():
    p = parse_message(_fixture("invalid_missing_teams.txt"))
    assert p["signal_type"] == "OVER 2.5"
    assert p["teams"] == ""                      # nessuna riga squadre


def test_missing_price_resta_vuoto():
    p = parse_message(_fixture("invalid_missing_price.txt"))
    assert p["teams"] == "Inter v Milan"
    assert p["quota"] == ""


def test_testo_casuale_non_inventa_segnale():
    p = parse_message(_fixture("invalid_random_text.txt"))
    assert p["signal_type"] == ""
    assert p["teams"] == ""
    assert p["quota"] == ""


def test_tutte_le_chiavi_presenti():
    p = parse_message("qualcosa")
    for k in ("signal_type", "competition", "teams", "score", "time_",
              "quota", "probability", "bet_type", "live"):
        assert k in p
