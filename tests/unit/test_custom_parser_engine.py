"""Test del motore di estrazione del Parser Personalizzato (CP-02).

Esercitano le funzioni reali di `xtrader_bridge.custom_parser_engine`:
estrazione per singola regola (fixed/start_after/end_before/emoji/multiriga) e
applicazione completa con gate "Non pronto" sugli obbligatori vuoti.
"""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_parser_engine as eng
from xtrader_bridge.csv_writer import CSV_HEADER


# ── extract_value: singola regola ──────────────────────────────────────────

def test_fixed_value_ignora_il_testo():
    r = cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM")
    assert eng.extract_value("qualsiasi cosa", r) == "TG_CUSTOM"
    assert eng.extract_value("", r) == "TG_CUSTOM"


def test_start_after_e_end_before_estrae_in_mezzo():
    r = cp.FieldRule(target="EventName", start_after="Match:", end_before="\n")
    assert eng.extract_value("Match: Inter v Milan\nAltro", r) == "Inter v Milan"


def test_start_after_assente_ritorna_vuoto():
    r = cp.FieldRule(target="Price", start_after="Quota:")
    assert eng.extract_value("nessuna quota qui", r) == ""


def test_end_before_vuoto_si_ferma_a_fine_riga():
    r = cp.FieldRule(target="Price", start_after="Quota:")
    assert eng.extract_value("Quota: 1,85\nLato: BACK", r) == "1,85"


def test_end_before_vuoto_senza_a_capo_prende_fino_a_fine():
    r = cp.FieldRule(target="Price", start_after="Quota:")
    assert eng.extract_value("Quota: 1,85", r) == "1,85"


def test_end_before_assente_prende_fino_a_fine():
    r = cp.FieldRule(target="EventName", start_after="Match:", end_before="@@@")
    assert eng.extract_value("Match: Inter v Milan", r) == "Inter v Milan"


def test_start_after_vuoto_parte_da_inizio():
    r = cp.FieldRule(target="EventName", end_before="|")
    assert eng.extract_value("Inter v Milan|resto", r) == "Inter v Milan"


def test_delimitatori_emoji():
    r = cp.FieldRule(target="Price", start_after="📊", end_before="%")
    assert eng.extract_value("📊72% Quota", r) == "72"


def test_valore_viene_rifilato():
    r = cp.FieldRule(target="EventName", start_after=":", end_before="\n")
    assert eng.extract_value(":   Inter v Milan   \n", r) == "Inter v Milan"


def test_value_map_non_applicata_in_cp02():
    # CP-02 estrae il valore grezzo; la value-map è CP-03.
    r = cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype")
    assert eng.extract_value("Lato: BACK", r) == "BACK"


# ── apply_parser: gate "Non pronto" ────────────────────────────────────────

def _parser():
    return cp.CustomParserDef(name="Yangon", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
        cp.FieldRule(target="BetType", start_after="Lato:", required=True),
        cp.FieldRule(target="MarketName", start_after="Mercato:", end_before="\n"),  # opzionale
    ])


_MSG_OK = "Match: Inter v Milan\nQuota: 1,85\nLato: BACK"


def test_apply_parser_ready_quando_obbligatori_presenti():
    res = eng.apply_parser(_parser(), _MSG_OK)
    assert res.ready is True
    assert res.missing_required == []
    assert res.values["EventName"] == "Inter v Milan"
    assert res.values["Price"] == "1,85"
    assert res.values["BetType"] == "BACK"
    assert res.values["Provider"] == "TG_CUSTOM"
    assert res.values["MarketName"] == ""  # opzionale assente → vuoto, non blocca


def test_apply_parser_non_pronto_se_obbligatorio_vuoto():
    msg = "Match: Inter v Milan\nLato: BACK"  # manca Quota
    res = eng.apply_parser(_parser(), msg)
    assert res.ready is False
    assert res.missing_required == ["Price"]


def test_apply_parser_opzionale_vuoto_non_blocca():
    res = eng.apply_parser(_parser(), _MSG_OK)
    assert res.ready is True
    assert "MarketName" not in res.missing_required


def test_as_csv_row_ha_le_14_colonne():
    res = eng.apply_parser(_parser(), _MSG_OK)
    row = res.as_csv_row()
    assert list(row.keys()) == CSV_HEADER
    assert len(row) == 14
    assert row["EventName"] == "Inter v Milan"
    assert row["MarketId"] == ""  # colonna senza regola → vuota


def test_apply_parser_testo_vuoto_non_pronto():
    res = eng.apply_parser(_parser(), "")
    assert res.ready is False
    # tutti gli obbligatori non-fixed risultano mancanti
    assert set(res.missing_required) == {"EventName", "Price", "BetType"}
