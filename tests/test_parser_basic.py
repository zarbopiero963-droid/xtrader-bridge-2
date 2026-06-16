"""Test baseline del parser P.Bet. (PR-02).

Esercitano la funzione reale `main.parse_message`. Documentano il comportamento
ATTUALE del parser (dipendente da emoji): il parser robusto emoji+testo è PR-09.
"""

import main


def test_parse_message_emoji_completo():
    msg = """P.Bet. MATCH ODDS ✅
🏆 Serie A
🆚 Inter v Milan
⚽ 1 - 0
⌚ 67m
Quota 1,85
📊 72.5%"""
    p = main.parse_message(msg)
    assert p["signal_type"] == "MATCH ODDS"
    assert p["teams"] == "Inter v Milan"
    assert p["quota"] == "1.85"          # virgola normalizzata in punto
    assert p["probability"] == "72.5"
    assert p["bet_type"] == "BACK"       # default interno


def test_parse_message_quota_virgola():
    assert main.parse_message("Quota 2,40")["quota"] == "2.40"


def test_parse_message_quota_punto():
    assert main.parse_message("Quota 1.95")["quota"] == "1.95"


def test_parse_message_vuoto_non_crasha():
    p = main.parse_message("")
    assert p["signal_type"] == ""
    assert p["teams"] == ""
    assert p["quota"] == ""
    assert p["bet_type"] == "BACK"


def test_parse_message_senza_quota():
    p = main.parse_message("P.Bet. GOL SECONDO TEMPO\n🆚 A v B")
    assert p["teams"] == "A v B"
    assert p["quota"] == ""               # nessuna quota nel messaggio


def test_parse_message_restituisce_tutte_le_chiavi():
    p = main.parse_message("testo qualsiasi")
    for k in ("signal_type", "competition", "teams", "score",
              "time_", "quota", "probability", "bet_type"):
        assert k in p
