"""Test delle value-map del Parser Personalizzato (CP-03).

Esercitano `xtrader_bridge.value_maps` (built-in `bettype`, costruzione da coppie
con gestione ambiguità, mappe derivate dal dizionario) e l'integrazione con il
motore di estrazione (`apply_parser` che traduce il valore via value-map).
"""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_parser_engine as eng
from xtrader_bridge import value_maps as vm


# ── built-in bettype (safety-critical) ─────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("BACK", "PUNTA"), ("back", "PUNTA"), (" Punta ", "PUNTA"), ("P", "PUNTA"),
    ("LAY", "BANCA"), ("Banca", "BANCA"), ("b", "BANCA"),
])
def test_bettype_traduce_sinonimi(raw, expected):
    assert vm.resolve(raw, "bettype") == expected


def test_bettype_valore_sconosciuto_vuoto():
    # Un lato non riconosciuto NON viene indovinato → vuoto (→ "Non pronto").
    assert vm.resolve("forse", "bettype") == ""


def test_resolve_valore_vuoto_o_mappa_sconosciuta_vuoto():
    assert vm.resolve("", "bettype") == ""
    assert vm.resolve("BACK", "non_esiste") == ""


# ── costruzione da coppie ──────────────────────────────────────────────────

def test_value_map_from_pairs_normalizza_e_salta_vuoti():
    m = vm.value_map_from_pairs([("  Over 2.5 ", "Over 2,5 gol"), ("", "x"), ("Y", "")])
    assert m == {"over 2.5": "Over 2,5 gol"}


def test_value_map_from_pairs_scarta_alias_ambiguo():
    # Stesso alias → valori diversi: rimosso (meglio "Non pronto" che indovinare).
    m = vm.value_map_from_pairs([("X", "A"), ("X", "B"), ("Y", "C")])
    assert m == {"y": "C"}


# ── mappe derivate dal dizionario ──────────────────────────────────────────

_FAKE_ROWS = [
    {"MarketAliasTelegram": "OVER 2.5", "SelectionAliasTelegram": "OVER",
     "MarketType_XTrader": "OVER_UNDER_25", "MarketName_XTrader": "Over/Under 2.5",
     "SelectionName_XTrader": "Over 2,5 gol"},
    {"MarketAliasTelegram": "GG", "SelectionAliasTelegram": "SI",
     "MarketType_XTrader": "BOTH_TEAMS_TO_SCORE", "MarketName_XTrader": "Goal/NoGoal",
     "SelectionName_XTrader": "Sì"},
]


def test_dizionario_value_maps_per_colonna():
    reg = vm.registry(include_dizionario=True, rows=_FAKE_ROWS)
    assert vm.resolve("over 2.5", "markettype", reg) == "OVER_UNDER_25"
    assert vm.resolve("SI", "selectionname", reg) == "Sì"
    assert vm.resolve("gg", "marketname", reg) == "Goal/NoGoal"


def test_registry_default_solo_builtin():
    reg = vm.registry()
    assert "bettype" in reg
    assert "markettype" not in reg  # dizionario non incluso di default


def test_available_value_maps_include_bettype():
    assert "bettype" in vm.available_value_maps()
    assert "selectionname" in vm.available_value_maps(include_dizionario=True, rows=_FAKE_ROWS)


def test_dizionario_value_maps_carica_il_dizionario_reale():
    # Smoke: il dizionario ufficiale produce mappe non vuote (file dati versionato).
    maps = vm.dizionario_value_maps()
    assert set(maps) == {"markettype", "marketname", "selectionname"}
    assert all(isinstance(m, dict) for m in maps.values())


# ── integrazione con apply_parser ──────────────────────────────────────────

def test_apply_parser_traduce_bettype():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
    ])
    res = eng.apply_parser(defn, "Lato: BACK")
    assert res.ready is True
    assert res.values["BetType"] == "PUNTA"


def test_apply_parser_bettype_sconosciuto_non_pronto():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
    ])
    res = eng.apply_parser(defn, "Lato: testacroce")  # lato non riconosciuto
    assert res.ready is False
    assert res.missing_required == ["BetType"]
    assert res.values["BetType"] == ""


def test_apply_parser_value_map_dizionario():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="SelectionName", start_after="Sel:", value_map="selectionname", required=True),
    ])
    reg = vm.registry(include_dizionario=True, rows=_FAKE_ROWS)
    res = eng.apply_parser(defn, "Sel: SI", value_maps_registry=reg)
    assert res.ready is True
    assert res.values["SelectionName"] == "Sì"
