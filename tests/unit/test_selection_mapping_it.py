"""Test del mapping alias → selezione XTrader italiana (PR-08).

Asserzioni fedeli ai valori reali di data/dizionario_xtrader.csv.
"""

import pytest

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

@pytest.mark.parametrize("shorthand, market_type, selection", [
    ("OVER 0.5",  "OVER_UNDER_05", "Over 0,5 goal"),
    ("UNDER 0.5", "OVER_UNDER_05", "Under 0,5 goal"),
    ("OVER 1.5",  "OVER_UNDER_15", "Over 1,5 goal"),
    ("UNDER 1.5", "OVER_UNDER_15", "Under 1,5 goal"),
    ("OVER 2.5",  "OVER_UNDER_25", "Over 2,5 goal"),
    ("UNDER 2.5", "OVER_UNDER_25", "Under 2,5 goal"),
    ("OVER 3.5",  "OVER_UNDER_35", "Over 3,5 goal"),
    ("UNDER 3.5", "OVER_UNDER_35", "Under 3,5 goal"),
])
def test_shorthand_over_under_tutte_le_linee(shorthand, market_type, selection):
    r = mapping.resolve_shorthand(shorthand, home="Inter", away="Milan")
    assert r["MarketType"] == market_type
    assert r["SelectionName"] == selection


def test_shorthand_over_25_virgola():
    # "Over 2,5" (virgola) deve normalizzarsi a "over 2.5".
    r = mapping.resolve_shorthand("Over 2,5")
    assert r["MarketType"] == "OVER_UNDER_25"
    assert r["SelectionName"] == "Over 2,5 goal"


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
    # Selezione statica (no placeholder) per testare il BetType senza squadre.
    assert mapping.resolve("esito_finale", "x")["BetType"] == "PUNTA"


def test_shorthand_suffisso_ft_ignorato():
    # "OVER 2.5 FT" deve mappare come "OVER 2.5" (FT è il default).
    r = mapping.resolve_shorthand("OVER 2.5 FT")
    assert r["MarketType"] == "OVER_UNDER_25"
    assert r["SelectionName"] == "Over 2,5 goal"


def test_shorthand_over_45_coperto():
    r = mapping.resolve_shorthand("OVER 4.5")
    assert r["MarketType"] == "OVER_UNDER_45"
    assert r["SelectionName"] == "Over 4,5 goal"


def test_shorthand_ht_primo_tempo():
    r = mapping.resolve_shorthand("OVER 0.5 HT")
    assert r["MarketType"] == "FIRST_HALF_GOALS_05"
    assert r["SelectionName"] == "Over 0,5 goal"


def test_resolve_placeholder_non_risolto_torna_none():
    # away shorthand senza nome squadra ospite -> placeholder non risolto -> None.
    assert mapping.resolve("esito_finale", "2", home="Inter") is None


def test_is_known_shorthand():
    assert mapping.is_known_shorthand("OVER 2.5") is True
    assert mapping.is_known_shorthand("2") is True
    assert mapping.is_known_shorthand("scommessa strana") is False
