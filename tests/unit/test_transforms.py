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


# ── Variante PRIMO TEMPO (richiesta del proprietario, 2026-08-03) ───────────────────────────────
#
# Perché serve: `score_to_over` produce "Over N,5", una stringa che NON porta con sé
# l'informazione tempo-pieno/primo-tempo. Le value-map del dizionario la risolvono sempre a
# `OVER_UNDER_*` (tempo pieno), e il primo tempo (`FIRST_HALF_GOALS_*`) resta irraggiungibile:
# nessuna riga di dizionario può disambiguare, perché lo STESSO input dovrebbe dare due mercati
# diversi — e in quel caso `value_maps` scarta l'alias ambiguo, giustamente.
#
# La variante HT emette invece la forma-alias del dizionario ("over N,5 ht"), che le tre mappe
# già esistenti risolvono al primo tempo senza toccare né dizionario né motore.
#
# ⚠️ Il SelectionName è IDENTICO fra i due tempi ("Over 0,5 goal"): solo il MarketType distingue.
# Per questo la scelta dev'essere esplicita nella regola, non dedotta.

@pytest.mark.parametrize("score, atteso", [
    ("0-0", "over 0,5 ht"),
    ("0-1", "over 1,5 ht"),
    ("1-1", "over 2,5 ht"),
    ("1:0", "over 1,5 ht"),
    (" 1 - 0 ", "over 1,5 ht"),
    ("1x0", "over 1,5 ht"),
])
def test_score_to_over_ht(score, atteso):
    assert tr.apply(score, "score_to_over_ht") == atteso


@pytest.mark.parametrize("bad", ["", "abc", "6", "6-", "-0", "6-0-0", "x-y", "٦-٠", "６-０"])
def test_score_to_over_ht_input_non_valido_vuoto(bad):
    # Stessa disciplina fail-closed della variante tempo pieno, cifre ASCII incluse
    # (#318 L2-1): un input non interpretabile non deve MAI produrre una linea inventata.
    assert tr.apply(bad, "score_to_over_ht") == ""


@pytest.mark.parametrize("score", ["999-999", "31-0", "0-31", "30-30", "16-15"])
def test_score_to_over_ht_implausibile_vuoto(score):
    assert tr.apply(score, "score_to_over_ht") == ""


def test_score_to_over_ht_e_nel_menu_e_riconosciuta():
    assert "score_to_over_ht" in tr.available_transforms()
    assert tr.has_transform("score_to_over_ht")


def test_score_to_over_resta_invariata_non_regressione():
    # Il nome storico NON cambia significato né sparisce dal menu: i parser già salvati
    # continuano a validare e la tendina continua a contenere il loro valore (se sparisse,
    # un parser caricato perderebbe la trasformazione in silenzio al primo salvataggio).
    assert tr.apply("6-0", "score_to_over") == "Over 6,5"
    assert "score_to_over" in tr.available_transforms()


def test_le_due_trasformazioni_condividono_ESATTAMENTE_i_cap():
    """Regola 3, verificata invece che dichiarata: `_somma_gol` è la fonte unica dei cap, quindi
    tempo pieno e primo tempo devono accettare e rifiutare gli STESSI punteggi — al limite
    compreso. Se un domani qualcuno duplicasse la logica e spostasse un cap di uno, lo stesso
    messaggio produrrebbe una linea con una trasformazione e nessuna con l'altra: un buco
    invisibile finché non capita in produzione.

    I limiti sono INCLUSIVI: somma 30 passa, 31 no (rilievo CodeRabbit su #213 — le docs
    dicevano il contrario)."""
    for score in ["0-0", "15-15", "30-0", "0-30",          # ammessi (somma ≤ 30, lato ≤ 30)
                  "16-15", "31-0", "0-31", "20-20", "abc", ""]:   # rifiutati
        ft = tr.apply(score, "score_to_over")
        ht = tr.apply(score, "score_to_over_ht")
        assert bool(ft) == bool(ht), (
            f"{score!r} accettato da una trasformazione e rifiutato dall'altra: "
            f"ft={ft!r} ht={ht!r} — i cap sono divergenti")

    # Il limite esatto, esplicito su entrambe: 30 passa, 31 no.
    assert tr.apply("15-15", "score_to_over") == "Over 30,5"
    assert tr.apply("15-15", "score_to_over_ht") == "over 30,5 ht"
    assert tr.apply("16-15", "score_to_over") == ""
    assert tr.apply("16-15", "score_to_over_ht") == ""
