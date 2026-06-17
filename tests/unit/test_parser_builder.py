"""Test del controller del costruttore di Parser Personalizzati (CP-06).

Esercitano `xtrader_bridge.parser_builder.ParserBuilder`: opzioni dei menu,
gestione regole, validazione, save/load e test-live. Nessun widget GUI qui.
"""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_builder as pb
from xtrader_bridge import validator
from xtrader_bridge.csv_writer import CSV_HEADER


# ── opzioni per i menu a tendina ───────────────────────────────────────────

def test_target_options_sono_le_14_colonne():
    b = pb.ParserBuilder()
    assert b.target_options() == list(CSV_HEADER)


def test_transform_options_includono_vuoto_e_score():
    opts = pb.ParserBuilder().transform_options()
    assert opts[0] == ""                      # nessuna trasformazione
    assert "score_to_over" in opts


def test_value_map_options_builtin_e_dizionario():
    b = pb.ParserBuilder()
    builtin = b.value_map_options(include_dizionario=False)
    assert builtin[0] == "" and "bettype" in builtin
    full = b.value_map_options(include_dizionario=True)
    assert "markettype" in full and "selectionname" in full


def test_mode_options():
    assert set(pb.ParserBuilder().mode_options()) == {"ID_ONLY", "NAME_ONLY", "BOTH"}


# ── gestione regole ────────────────────────────────────────────────────────

def test_add_update_remove_rule():
    b = pb.ParserBuilder()
    b.add_rule("EventName", start_after="Match:", required=True)
    assert len(b.rules) == 1 and b.rules[0].target == "EventName"
    b.update_rule(0, end_before="\n")
    assert b.rules[0].end_before == "\n"
    b.remove_rule(0)
    assert b.rules == []


def test_update_rule_campo_sconosciuto_errore():
    b = pb.ParserBuilder()
    b.add_rule("Price")
    with pytest.raises(AttributeError):
        b.update_rule(0, non_esiste="x")


def test_move_rule():
    b = pb.ParserBuilder()
    b.add_rule("EventName")
    b.add_rule("Price")
    b.add_rule("BetType")
    assert b.move_rule(2, -1) == 1          # BetType su di uno
    assert [r.target for r in b.rules] == ["EventName", "BetType", "Price"]
    assert b.move_rule(0, -5) == 0          # clamp al bordo
    assert b.move_rule(0, +99) == 2         # clamp all'altro bordo


# ── validazione ────────────────────────────────────────────────────────────

def test_errors_e_is_valid():
    b = pb.ParserBuilder()
    assert not b.is_valid()                 # nome vuoto + nessuna regola
    b.name = "Mio parser"
    b.add_rule("Price", required=True)
    assert b.is_valid()
    assert b.errors() == []


def test_validazione_trasformazione_sconosciuta():
    b = pb.ParserBuilder()
    b.name = "X"
    b.add_rule("SelectionName", fixed_value="x", transform="boh")
    assert any("trasformazione sconosciuta" in e for e in b.errors())


# ── persistenza ─────────────────────────────────────────────────────────────

def test_save_e_load_round_trip(tmp_path):
    b = pb.ParserBuilder()
    b.name = "Yangon"
    b.add_rule("Provider", fixed_value="TG_CUSTOM")
    b.add_rule("Price", start_after="Quota:", required=True)
    path = b.save(str(tmp_path))
    loaded = pb.ParserBuilder.load(path)
    assert loaded.name == "Yangon"
    assert [r.target for r in loaded.rules] == ["Provider", "Price"]
    assert pb.ParserBuilder.list_saved(str(tmp_path)) == [path]


def test_save_parser_invalido_solleva(tmp_path):
    b = pb.ParserBuilder()  # nome vuoto, nessuna regola
    with pytest.raises(ValueError):
        b.save(str(tmp_path))


# ── test-live ────────────────────────────────────────────────────────────────

def test_test_message_riga_piazzabile():
    b = pb.ParserBuilder()
    b.name = "Yangon"
    b.add_rule("Provider", fixed_value="TG_CUSTOM")
    b.add_rule("EventName", start_after="Match:", end_before="\n", required=True)
    b.add_rule("MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True)
    b.add_rule("SelectionName", start_after="Sel:", end_before="\n", required=True)
    b.add_rule("Price", start_after="Quota:", end_before="\n", required=True)
    b.add_rule("BetType", start_after="Lato:", value_map="bettype", required=True)
    res = b.test_message("Match: Inter v Milan\nSel: Sì\nQuota: 1,85\nLato: BACK")
    assert res.status == validator.VALID
    assert res.placeable is True
    assert res.row["BetType"] == "PUNTA"
    assert res.row["Price"] == "1.85"


def test_test_message_non_pronto():
    b = pb.ParserBuilder()
    b.name = "X"
    b.add_rule("Price", start_after="Quota:", required=True)
    res = b.test_message("nessuna quota")
    assert res.placeable is False


def test_init_da_definizione_copia_le_regole():
    base = cp.skeleton("Base")
    b = pb.ParserBuilder(base)
    assert b.name == "Base"
    b.update_rule(0, fixed_value="ALTRO")     # modifica la copia
    assert base.rules[0].fixed_value != "ALTRO"  # l'originale non cambia
