"""Test del modello dati del Parser Personalizzato (CP-01).

Esercitano le funzioni reali di `xtrader_bridge.custom_parser`: round-trip
dict/JSON, validazione strutturale (errori e casi validi), skeleton, e
salvataggio/caricamento su disco (tmp_path, nessun file committato).
"""

import json
import os

import pytest

from xtrader_bridge import config_store
from xtrader_bridge import custom_parser as cp
from xtrader_bridge.csv_writer import CSV_HEADER


def _valid_def():
    return cp.CustomParserDef(
        name="Yangon City",
        description="modello di esempio",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="Price", start_after="Quota", required=True),
            cp.FieldRule(target="BetType", value_map="bettype", required=True),
        ],
    )


# ── target ancorati al contratto CSV ───────────────────────────────────────

def test_valid_targets_sono_le_14_colonne_del_contratto():
    assert cp.VALID_TARGETS == tuple(CSV_HEADER)
    assert len(cp.VALID_TARGETS) == 14


# ── round-trip ─────────────────────────────────────────────────────────────

def test_round_trip_dict_preserva_i_dati():
    d = _valid_def()
    again = cp.CustomParserDef.from_dict(d.to_dict())
    assert again.to_dict() == d.to_dict()


def test_round_trip_json_preserva_i_dati_e_unicode():
    d = _valid_def()
    text = d.to_json()
    # ensure_ascii=False: l'unicode resta leggibile nel file.
    assert "\\u" not in text
    again = cp.CustomParserDef.from_json(text)
    assert again.to_dict() == d.to_dict()


def test_from_dict_tollera_chiavi_mancanti_ed_extra():
    rule = cp.FieldRule.from_dict({"target": "Price", "sconosciuta": "x"})
    assert rule.target == "Price"
    assert rule.start_after == "" and rule.required is False
    # version mancante → default schema
    d = cp.CustomParserDef.from_dict({"name": "X", "rules": [{"target": "Price"}]})
    assert d.version == cp.SCHEMA_VERSION


def test_from_dict_required_normalizzato_a_bool():
    assert cp.FieldRule.from_dict({"target": "Price", "required": 1}).required is True
    assert cp.FieldRule.from_dict({"target": "Price", "required": 0}).required is False
    assert cp.FieldRule.from_dict({"target": "Price", "required": True}).required is True


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("True", True), ("1", True), ("yes", True), ("si", True), ("on", True),
    ("false", False), ("False", False), ("0", False), ("no", False), ("off", False), ("", False),
])
def test_from_dict_required_stringhe_truthy_falsy(value, expected):
    # Niente trappola bool("false")==True: le stringhe note sono normalizzate.
    assert cp.FieldRule.from_dict({"target": "Price", "required": value}).required is expected


def test_from_dict_required_valore_ambiguo_errore():
    # Un valore booleano non riconosciuto NON viene indovinato (safety-critical).
    with pytest.raises(ValueError):
        cp.FieldRule.from_dict({"target": "Price", "required": "forse"})


def test_from_dict_rule_senza_target_errore():
    with pytest.raises(ValueError):
        cp.FieldRule.from_dict({"start_after": "x"})


# ── validazione strutturale ────────────────────────────────────────────────

def test_def_valido_nessun_errore():
    assert cp.validate_parser_def(_valid_def()) == []
    assert cp.is_valid(_valid_def())


def test_nome_vuoto_invalido():
    d = _valid_def()
    d.name = "   "
    assert any("nome" in e.lower() for e in cp.validate_parser_def(d))


def test_nessuna_regola_invalido():
    d = cp.CustomParserDef(name="X", rules=[])
    assert any("almeno una regola" in e for e in cp.validate_parser_def(d))


def test_target_sconosciuto_invalido():
    d = cp.CustomParserDef(name="X", rules=[cp.FieldRule(target="NonEsiste")])
    errs = cp.validate_parser_def(d)
    assert any("non valida" in e for e in errs)
    assert not cp.is_valid(d)


def test_target_duplicato_invalido():
    d = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Price", required=True),
        cp.FieldRule(target="Price", fixed_value="1"),
    ])
    assert any("duplicata" in e for e in cp.validate_parser_def(d))


def test_fixed_value_piu_estrazione_invalido():
    d = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Price", fixed_value="2.0", start_after="Quota"),
    ])
    assert any("fixed_value" in e for e in cp.validate_parser_def(d))


def test_versione_non_valida_invalido():
    d = _valid_def()
    d.version = 0
    assert any("Versione" in e for e in cp.validate_parser_def(d))


@pytest.mark.parametrize("raw, expected", [("2", 2), ("abc", 1), (None, 1), (3, 3)])
def test_from_dict_version_coercion(raw, expected):
    # from_dict coerce le versioni non intere; "abc"/None ripiegano sullo schema.
    d_dict = _valid_def().to_dict()
    d_dict["version"] = raw
    parsed = cp.CustomParserDef.from_dict(d_dict)
    assert parsed.version == expected
    # con versione >= 1 e regole valide, la definizione resta valida
    assert cp.validate_parser_def(parsed) == []


def test_required_targets():
    d = _valid_def()
    assert d.required_targets() == ["EventName", "Price", "BetType"]


# ── skeleton ───────────────────────────────────────────────────────────────

def test_skeleton_e_valido_e_targets_nel_contratto():
    sk = cp.skeleton("Mio parser")
    assert sk.name == "Mio parser"
    assert cp.validate_parser_def(sk) == []
    for r in sk.rules:
        assert r.target in CSV_HEADER


# ── persistenza su disco (tmp_path) ────────────────────────────────────────

def test_save_e_load_round_trip(tmp_path):
    d = _valid_def()
    path = cp.save_parser(d, str(tmp_path))
    assert path.endswith(".json")
    loaded = cp.load_parser(path)
    assert loaded.to_dict() == d.to_dict()
    # file JSON valido e leggibile
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["name"] == "Yangon City"


def test_save_rifiuta_parser_non_valido(tmp_path):
    d = cp.CustomParserDef(name="", rules=[])
    with pytest.raises(ValueError):
        cp.save_parser(d, str(tmp_path))
    assert cp.list_parser_files(str(tmp_path)) == []


def test_filename_sicuro_contro_path_traversal(tmp_path):
    d = _valid_def()
    d.name = "../../etc/passwd"
    path = cp.save_parser(d, str(tmp_path))
    # il file resta DENTRO tmp_path (niente traversal)
    assert path.startswith(str(tmp_path))
    assert ".." not in path[len(str(tmp_path)):]


def test_list_parser_files_vuoto_se_cartella_assente(tmp_path):
    assert cp.list_parser_files(str(tmp_path / "non_esiste")) == []


def test_default_parsers_dir_e_persistente_non_meipass():
    # I parser utente vanno in una cartella persistente (config_store.config_dir),
    # NON nella cartella temporanea dell'EXE (sys._MEIPASS).
    d = cp.default_parsers_dir()
    assert d == os.path.join(config_store.config_dir(), "parsers")
    assert d.endswith(os.path.join("XTraderBridge", "parsers"))


def test_save_rifiuta_collisione_nomi(tmp_path):
    # "A/B" e "AB" si sanitizzano allo stesso file: il secondo NON deve
    # sovrascrivere in silenzio il primo (perdita di regole).
    first = _valid_def()
    first.name = "A/B"
    p1 = cp.save_parser(first, str(tmp_path))
    second = _valid_def()
    second.name = "AB"
    assert cp.parser_path("AB", str(tmp_path)) == p1  # stesso file
    with pytest.raises(ValueError):
        cp.save_parser(second, str(tmp_path))
    # il primo parser è rimasto intatto
    assert cp.load_parser(p1).name == "A/B"


def test_save_stesso_nome_aggiorna(tmp_path):
    d = _valid_def()
    cp.save_parser(d, str(tmp_path))
    d.description = "aggiornata"
    path = cp.save_parser(d, str(tmp_path))  # stesso nome → update, nessun errore
    assert cp.load_parser(path).description == "aggiornata"


def test_save_atomico_non_lascia_tmp_residui(tmp_path):
    cp.save_parser(_valid_def(), str(tmp_path))
    leftovers = [f for f in os.listdir(str(tmp_path)) if f.startswith(".parser_")]
    assert leftovers == []


def test_list_parser_files_ignora_tmp_atomici(tmp_path):
    # Un temp atomico residuo (crash a metà save) NON deve apparire come parser.
    p = cp.save_parser(_valid_def(), str(tmp_path))
    (tmp_path / ".parser_orfano.json").write_text("{}", encoding="utf-8")
    files = cp.list_parser_files(str(tmp_path))
    assert files == [p]
    assert all(not os.path.basename(f).startswith(".") for f in files)
