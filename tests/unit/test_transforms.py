"""Test delle trasformazioni configurabili del Parser Personalizzato (CP-05)."""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_parser_engine as eng
from xtrader_bridge import transforms as tr


@pytest.mark.parametrize("score, atteso", [
    ("6-0", "Over 6,5"),
    ("6:0", "Over 6,5"),
    ("2-3", "Over 5,5"),
    ("0-0", "Over 0,5"),
    (" 1 - 2 ", "Over 3,5"),
    ("1x2", "Over 3,5"),
    ("1X2", "Over 3,5"),
])
def test_score_to_over(score, atteso):
    assert tr.apply(score, "score_to_over") == atteso


@pytest.mark.parametrize("bad", ["", "abc", "6", "6-", "-0", "6-0-0", "x-y"])
def test_score_to_over_input_non_valido_vuoto(bad):
    assert tr.apply(bad, "score_to_over") == ""


def test_trasformazione_sconosciuta_vuota():
    assert tr.apply("6-0", "non_esiste") == ""


def test_available_e_has():
    assert "score_to_over" in tr.available_transforms()
    assert tr.has_transform("score_to_over")
    assert not tr.has_transform("xxx")


# ── integrazione col modello e col motore ──────────────────────────────────

def test_field_rule_round_trip_con_transform():
    r = cp.FieldRule(target="SelectionName", start_after="Risultato:", transform="score_to_over")
    again = cp.FieldRule.from_dict(r.to_dict())
    assert again.transform == "score_to_over"


def test_validate_transform_sconosciuta():
    d = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="SelectionName", fixed_value="x", transform="boh"),
    ])
    assert any("trasformazione sconosciuta" in e for e in cp.validate_parser_def(d))


def test_validate_transform_nota_ok():
    d = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="SelectionName", start_after="R:", transform="score_to_over"),
    ])
    assert cp.validate_parser_def(d) == []


def test_apply_parser_usa_la_trasformazione():
    # Estrae il punteggio dal messaggio e lo trasforma in linea Over.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="SelectionName", start_after="Risultato:", end_before="\n",
                     transform="score_to_over", required=True),
    ])
    res = eng.apply_parser(defn, "Risultato: 6-0\naltro")
    assert res.values["SelectionName"] == "Over 6,5"


def test_apply_parser_ordine_transform_poi_value_map():
    # Blinda l'ordine estrazione → trasformazione → value-map: la value-map deve
    # ricevere il risultato della trasformazione ("Over 6,5"), non il grezzo.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="SelectionName", start_after="Risultato:", end_before="\n",
                     transform="score_to_over", value_map="over_map", required=True),
    ])
    # Registry nel formato reale: nome → {alias_normalizzato: valore}. La chiave è
    # normalizzata come fa value_maps.resolve ("Over 6,5" → "over 6.5").
    reg = {"over_map": {"over 6.5": "Over 6,5 gol"}}
    res = eng.apply_parser(defn, "Risultato: 6-0\n", value_maps_registry=reg)
    assert res.values["SelectionName"] == "Over 6,5 gol"


def test_apply_parser_transform_input_non_valido_non_pronto():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="SelectionName", start_after="Risultato:", end_before="\n",
                     transform="score_to_over", required=True),
    ])
    res = eng.apply_parser(defn, "Risultato: ndefinito\n")
    assert res.values["SelectionName"] == ""
    assert res.ready is False
    assert res.missing_required == ["SelectionName"]


@pytest.mark.parametrize("score", ["999-999", "31-0", "0-31", "100-2", "50:50"])
def test_score_to_over_punteggio_implausibile_vuoto(score):
    # A5: un punteggio assurdo (un lato oltre 30 gol) NON deve generare una linea Over
    # inventata; fail-closed → "".
    assert tr.apply(score, "score_to_over") == ""


@pytest.mark.parametrize("score", ["30-30", "20-20", "16-15", "25-10"])
def test_score_to_over_somma_implausibile_vuoto(score):
    # Codex: anche se ogni lato è ≤30, una SOMMA oltre 30 dà un totale assurdo
    # ("30-30" → "Over 60,5"); deve fallire chiuso → "".
    assert tr.apply(score, "score_to_over") == ""


def test_score_to_over_cap_al_limite():
    # A5: 30 gol per lato è ancora ammesso; 31 è oltre il cap. La somma 30 è al limite.
    assert tr.apply("30-0", "score_to_over") == "Over 30,5"
    assert tr.apply("0-30", "score_to_over") == "Over 30,5"
    assert tr.apply("15-15", "score_to_over") == "Over 30,5"
    assert tr.apply("31-0", "score_to_over") == ""
