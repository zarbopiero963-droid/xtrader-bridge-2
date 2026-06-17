"""Test import/export dei Parser Personalizzati e del parser d'esempio (CP-08)."""

import json

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_io as pio
from xtrader_bridge import validator
from xtrader_bridge.custom_pipeline import build_validated_row


def _valid_defn(name="Mio"):
    return cp.CustomParserDef(name=name, rules=[cp.FieldRule(target="Price", required=True)])


# ── export ──────────────────────────────────────────────────────────────────

def test_export_scrive_file_caricabile(tmp_path):
    dest = str(tmp_path / "out.json")
    pio.export_parser(_valid_defn("Yangon"), dest)
    again = cp.load_parser(dest)
    assert again.name == "Yangon"


def test_export_rifiuta_parser_invalido(tmp_path):
    invalido = cp.CustomParserDef(name="", rules=[])
    with pytest.raises(ValueError):
        pio.export_parser(invalido, str(tmp_path / "out.json"))
    assert not (tmp_path / "out.json").exists()


# ── import ──────────────────────────────────────────────────────────────────

def test_import_valido_salva_in_cartella(tmp_path):
    src = tmp_path / "src.json"
    src.write_text(_valid_defn("Importato").to_json(), encoding="utf-8")
    parsers_dir = tmp_path / "parsers"
    defn = pio.import_parser(str(src), str(parsers_dir))
    assert defn.name == "Importato"
    # salvato nella cartella dei parser e ricaricabile
    saved = cp.parser_path("Importato", str(parsers_dir))
    assert cp.load_parser(saved).name == "Importato"


def test_import_file_corrotto_solleva(tmp_path):
    src = tmp_path / "bad.json"
    src.write_text("{non json", encoding="utf-8")
    with pytest.raises(ValueError):
        pio.import_parser(str(src), str(tmp_path / "parsers"))


def test_import_parser_invalido_solleva_e_non_salva(tmp_path):
    src = tmp_path / "src.json"
    src.write_text(json.dumps({"name": "X", "rules": []}), encoding="utf-8")  # nessuna regola
    parsers_dir = tmp_path / "parsers"
    with pytest.raises(ValueError):
        pio.import_parser(str(src), str(parsers_dir))
    assert cp.list_parser_files(str(parsers_dir)) == []


def test_export_import_round_trip(tmp_path):
    dest = str(tmp_path / "shared.json")
    pio.export_parser(_valid_defn("Giro"), dest)
    defn = pio.import_parser(dest, str(tmp_path / "parsers"))
    assert defn.name == "Giro"


# ── parser d'esempio (fixture end-to-end) ───────────────────────────────────

def test_example_parser_e_valido():
    assert cp.validate_parser_def(pio.example_parser()) == []


def test_example_parser_produce_riga_piazzabile():
    defn = pio.example_parser()
    assert defn.description.strip() != ""          # esempio documentato
    res = build_validated_row(defn, pio.fixture_message())
    assert res.status == validator.VALID
    assert res.placeable is True
    assert res.row["EventName"] == "Inter v Milan"
    assert res.row["SelectionName"] == "Sì"       # "GG" via value-map dizionario
    assert res.row["BetType"] == "PUNTA"          # "BACK" via value-map bettype
    assert res.row["Price"] == "1.85"             # virgola → punto
    assert res.row["Provider"] == "TG_CUSTOM"      # fixed value
    assert res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"  # fixed value
    assert res.row["Handicap"] == "0"              # default contratto
