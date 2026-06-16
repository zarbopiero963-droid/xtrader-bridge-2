"""Test del mapping alias → selezione XTrader italiana (PR-08).

Asserzioni fedeli ai valori reali di data/dizionario_xtrader.csv.
"""

from xtrader_bridge import mapping


def test_resolve_esito_1_sostituisce_home():
    r = mapping.resolve("esito_finale", "1", home="Inter", away="Milan")
    assert r["MarketType"] == "MATCH_ODDS"
    assert r["SelectionName"] == "Inter"        # {HOME_TEAM} sostituito


def test_resolve_esito_2_sostituisce_away():
    r = mapping.resolve("esito_finale", "2", home="Inter", away="Milan")
    assert r["SelectionName"] == "Milan"        # {AWAY_TEAM} sostituito


def test_resolve_esito_x_pareggio():
    r = mapping.resolve("esito_finale", "x", home="Inter", away="Milan")
    assert r["SelectionName"] == "Pareggio"


def test_resolve_alias_sconosciuto_none():
    assert mapping.resolve("non_esiste", "boh") is None


# ── forme brevi Telegram (SYNONYMS) ──

def test_shorthand_over_25():
    r = mapping.resolve_shorthand("OVER 2.5", home="Inter", away="Milan")
    assert r["MarketType"] == "OVER_UNDER_25"
    assert r["SelectionName"] == "Over 2,5 goal"


def test_shorthand_over_25_virgola():
    # "Over 2,5" (virgola) deve normalizzarsi a "over 2.5".
    r = mapping.resolve_shorthand("Over 2,5")
    assert r["MarketType"] == "OVER_UNDER_25"
    assert r["SelectionName"] == "Over 2,5 goal"


def test_shorthand_under_25():
    r = mapping.resolve_shorthand("under 2.5")
    assert r["SelectionName"] == "Under 2,5 goal"


def test_shorthand_gg():
    r = mapping.resolve_shorthand("GG")
    assert r["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert r["SelectionName"] == "Sì"


def test_shorthand_ng():
    r = mapping.resolve_shorthand("NG")
    assert r["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert r["SelectionName"] == "No"


def test_shorthand_1_x_2():
    assert mapping.resolve_shorthand("1", home="Inter", away="Milan")["SelectionName"] == "Inter"
    assert mapping.resolve_shorthand("X", home="Inter", away="Milan")["SelectionName"] == "Pareggio"
    assert mapping.resolve_shorthand("2", home="Inter", away="Milan")["SelectionName"] == "Milan"


def test_shorthand_sconosciuto_none():
    assert mapping.resolve_shorthand("scommessa strana") is None


def test_bettype_dal_dizionario_e_punta():
    assert mapping.resolve("esito_finale", "1")["BetType"] == "PUNTA"
