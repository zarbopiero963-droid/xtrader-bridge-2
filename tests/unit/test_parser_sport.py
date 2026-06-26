"""Test dello Sport del Parser Personalizzato (issue #86 PR-P9).

Copre: campo `sport` su `CustomParserDef` (default agnostico, round-trip JSON,
helper `event_type_id`), validazione (vuoto o sport supportato), e la preservazione
nel `ParserBuilder` (load+to_def, set_sport, sport_options). Lo sport NON cambia le
colonne CSV: serve a restringere (PR successive) la risoluzione ID all'event_type_id.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge.custom_parser import CustomParserDef, FieldRule
from xtrader_bridge.parser_builder import ParserBuilder


def _valid_def(**kw):
    """Parser minimo valido (una regola) con eventuali override (es. sport)."""
    return CustomParserDef(name="P", rules=[FieldRule(target="Provider", fixed_value="X")], **kw)


# ── default + helper event_type_id ──────────────────────────────────────────────

def test_sport_default_agnostico():
    d = CustomParserDef(name="P", rules=[])
    assert d.sport == ""
    assert d.event_type_id() is None        # non specificato → nessun event_type_id


def test_event_type_id_per_sport_noto():
    assert _valid_def(sport="Calcio").event_type_id() == "1"
    assert _valid_def(sport="Rugby Union").event_type_id() == "5"


# ── round-trip JSON ─────────────────────────────────────────────────────────────

def test_sport_roundtrip_to_from_dict():
    d = _valid_def(sport="Tennis")
    data = d.to_dict()
    assert data["sport"] == "Tennis"
    assert CustomParserDef.from_dict(data).sport == "Tennis"


def test_sport_roundtrip_to_from_json():
    d = _valid_def(sport="Basket")
    assert CustomParserDef.from_json(d.to_json()).sport == "Basket"


def test_sport_legacy_assente_resta_agnostico():
    # File salvato PRIMA di PR-P9 (nessuna chiave 'sport') → "" (retro-compatibile).
    legacy = {"name": "Old", "rules": [{"target": "Provider", "fixed_value": "X"}]}
    assert CustomParserDef.from_dict(legacy).sport == ""


def test_sport_from_dict_strippa_spazi():
    data = {"name": "P", "sport": "  Calcio ", "rules": [{"target": "Provider", "fixed_value": "X"}]}
    assert CustomParserDef.from_dict(data).sport == "Calcio"


# ── validazione ─────────────────────────────────────────────────────────────────

def test_validazione_sport_vuoto_ok():
    assert cp.validate_parser_def(_valid_def(sport="")) == []


def test_validazione_sport_noto_ok():
    assert cp.validate_parser_def(_valid_def(sport="Calcio")) == []


def test_validazione_sport_ignoto_errore():
    errs = cp.validate_parser_def(_valid_def(sport="Pallanuoto"))
    assert any("Sport non valido" in e for e in errs)
    assert cp.is_valid(_valid_def(sport="Pallanuoto")) is False


def test_validazione_sport_ignoto_da_file_bloccata():
    # Un 'sport' manomesso nel JSON non deve passare silenziosamente (fail-closed):
    # from_dict lo tiene com'è e la validazione lo segnala.
    data = {"name": "P", "sport": "Xyz", "rules": [{"target": "Provider", "fixed_value": "X"}]}
    d = CustomParserDef.from_dict(data)
    assert d.sport == "Xyz"
    assert not cp.is_valid(d)


# ── ParserBuilder: preservazione round-trip + setter ────────────────────────────

def test_builder_preserva_sport_load_to_def():
    d = _valid_def(sport="Tennis")
    b = ParserBuilder(d)
    assert b.sport == "Tennis"
    assert b.to_def().sport == "Tennis"      # load+save non azzera lo sport


def test_builder_nuovo_sport_agnostico():
    assert ParserBuilder().sport == ""


def test_builder_set_sport_canonicalizza():
    b = ParserBuilder()
    b.set_sport("calcio")
    assert b.sport == "Calcio"
    b.set_sport("  basket ")
    assert b.sport == "Basket"


def test_builder_set_sport_ignoto_resta_agnostico():
    b = ParserBuilder()
    b.set_sport("Curling")          # ignoto → "" (fail-safe, non sceglie uno a caso)
    assert b.sport == ""
    b.set_sport("Tennis")
    b.set_sport("")                 # esplicito vuoto → agnostico
    assert b.sport == ""


def test_builder_sport_options():
    opts = ParserBuilder().sport_options()
    assert opts == ["", "Calcio", "Tennis", "Basket", "Rugby Union"]
