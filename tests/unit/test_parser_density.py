"""#293 «densità parser»: il Parser mostra di default solo le colonne essenziali; le colonne
avanzate **Trasformazione** e **Value-map** sono dietro un toggle «Avanzate».

Si verifica la logica REALE e pura:
- `_visible_rule_columns(show_advanced)` — quali colonne compaiono nell'intestazione;
- `_add_row` (con `customtkinter` stubbato) — i `StringVar` `transform`/`value_map` sono creati
  **sempre** (dati preservati anche a colonne nascoste), così `_sync_to_builder` continua a
  conservare `rule.transform`/`rule.value_map`. Nessun impatto su parsing/CSV.
"""

import importlib
import sys
import types

import pytest

from xtrader_bridge.custom_parser import FieldRule


class _FakeStringVar:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Noop:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: _Noop()


class _FakeCtkModule(types.ModuleType):
    StringVar = _FakeStringVar

    def __getattr__(self, name):
        return _Noop


@pytest.fixture()
def gui_mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    return importlib.import_module("xtrader_bridge.custom_parser_gui")


# ── intestazione: densità di default ─────────────────────────────────────────

def test_colonne_default_nascondono_trasformazione_e_valuemap(gui_mod):
    labels = [label for label, _w in gui_mod._visible_rule_columns(False)]
    assert "Trasformazione" not in labels
    assert "Value-map" not in labels
    # le colonne essenziali restano sempre visibili
    for essential in ("Colonna", "Inizia dopo", "Finisce prima", "Valore fisso", "Obblig."):
        assert essential in labels


def test_colonne_avanzate_mostrano_tutto(gui_mod):
    labels = [label for label, _w in gui_mod._visible_rule_columns(True)]
    assert "Trasformazione" in labels and "Value-map" in labels
    # tutte le 8 colonne del contratto (incl. lo spazio azioni "")
    assert len(gui_mod._visible_rule_columns(True)) == len(gui_mod._RULE_COLUMNS)
    # nascondere esattamente 2 colonne (le due avanzate)
    assert len(gui_mod._visible_rule_columns(False)) == len(gui_mod._RULE_COLUMNS) - 2


# ── righe: i dati transform/value_map sopravvivono a colonne nascoste ─────────

def _fake_panel(gui_mod, *, show_advanced):
    fake = types.SimpleNamespace(
        _rows=[], _rows_frame=_Noop(), _providers=[],
        _transforms=["", "upper"], _value_maps=["", "map1"],
        _show_advanced=show_advanced)
    fake._add_row = types.MethodType(gui_mod.CustomParserPanel._add_row, fake)
    return fake


def test_add_row_preserva_transform_e_valuemap_con_colonne_nascoste(gui_mod):
    # Colonne avanzate NASCOSTE: i StringVar esistono comunque coi valori del rule, così
    # `_sync_to_builder` (che legge refs["transform"]/["value_map"].get()) li conserva.
    fake = _fake_panel(gui_mod, show_advanced=False)
    fake._add_row(FieldRule(target="EventName", transform="upper", value_map="map1"))
    refs = fake._rows[-1]
    assert refs["transform"].get() == "upper"
    assert refs["value_map"].get() == "map1"


def test_add_row_preserva_transform_e_valuemap_con_colonne_visibili(gui_mod):
    # In modalità «Avanzate» stesso comportamento sui dati (i menu vengono anche mostrati).
    fake = _fake_panel(gui_mod, show_advanced=True)
    fake._add_row(FieldRule(target="EventName", transform="upper", value_map="map1"))
    refs = fake._rows[-1]
    assert refs["transform"].get() == "upper"
    assert refs["value_map"].get() == "map1"


def test_on_toggle_advanced_sincronizza_prima_di_ricostruire(gui_mod):
    # GLM #339: il callback del toggle legge il var, poi sincronizza il builder PRIMA di
    # ricostruire intestazione + righe (così una modifica in corso non va persa).
    calls = []
    fake = types.SimpleNamespace(
        _show_advanced=False,
        _advanced_var=_FakeStringVar(True),
        _sync_to_builder=lambda: calls.append("sync"),
        _populate_rules_header=lambda: calls.append("header"),
        _reload_rows_from_builder=lambda: calls.append("rows"))
    fake._on_toggle_advanced = types.MethodType(
        gui_mod.CustomParserPanel._on_toggle_advanced, fake)

    fake._on_toggle_advanced()
    assert fake._show_advanced is True                 # stato preso dal checkbox
    assert calls == ["sync", "header", "rows"]         # sync PRIMA del rebuild, in ordine

    fake._advanced_var = _FakeStringVar(False)          # spegni il toggle
    calls.clear()
    fake._on_toggle_advanced()
    assert fake._show_advanced is False
    assert calls == ["sync", "header", "rows"]


def test_add_row_default_senza_show_advanced_non_crasha(gui_mod):
    # Difensivo: `_add_row` usa getattr(self, "_show_advanced", False) → un fake self senza
    # l'attributo (init parziale/test legacy) non solleva e crea comunque i StringVar.
    fake = types.SimpleNamespace(_rows=[], _rows_frame=_Noop(), _providers=[],
                                 _transforms=[], _value_maps=[])
    fake._add_row = types.MethodType(gui_mod.CustomParserPanel._add_row, fake)
    fake._add_row(FieldRule(target="EventName", transform="upper", value_map="map1"))
    assert fake._rows[-1]["transform"].get() == "upper"
