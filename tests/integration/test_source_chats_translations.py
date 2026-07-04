"""#293 slice 6: chip «Traduzioni» (Nomi ✓ / Mercati —) per canale nel pannello Chat sorgenti.

Verifica l'helper puro di presentazione `_translations_chip_text` (il rendering reale del chip
è smoke manuale su Windows). `customtkinter` è stubbato (modulo GUI, no display).
"""

import importlib
import sys
import types

import pytest


@pytest.fixture
def gui_mod(monkeypatch):
    fake = types.ModuleType("customtkinter")
    fake.__getattr__ = lambda _n: object
    monkeypatch.setitem(sys.modules, "customtkinter", fake)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.source_chats_gui", raising=False)
    return importlib.import_module("xtrader_bridge.source_chats_gui")


def test_chip_text_combinazioni(gui_mod):
    t = gui_mod._translations_chip_text
    assert t(True, False) == "Nomi ✓ · Mercati —"
    assert t(False, True) == "Nomi — · Mercati ✓"
    assert t(True, True) == "Nomi ✓ · Mercati ✓"
    assert t(False, False) == "Nomi — · Mercati —"


def test_effective_parser_name(gui_mod):
    # CodeRabbit #340: risoluzione override-vs-globale estratta in helper puro, testata diretta.
    f = gui_mod._effective_parser_name
    assert f("P1", "(predefinito)", "GLOB") == "P1"                # override esplicito
    assert f("(predefinito)", "(predefinito)", "GLOB") == "GLOB"   # sentinella → globale
    assert f("(predefinito)", "(predefinito)", "") == ""           # nessun globale → nessuno
    assert f("(predefinito)", "(predefinito)", "  G  ") == "G"     # globale rifilato
    assert f("P1", "(predefinito)", "") == "P1"                    # override vince anche senza globale


class _Var:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v


class _Label:
    def __init__(self):
        self.text = None
        self.color = None

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]
        if "text_color" in kw:
            self.color = kw["text_color"]


def test_update_row_chip_override_vs_predefinito(gui_mod, tmp_path, monkeypatch):
    # GPT/GLM #340: il chip usa il parser dell'OVERRIDE di riga, o — se «(predefinito)» — il
    # parser GLOBALE dallo snapshot self._cfg. Prova che la risoluzione è guidata da self._cfg
    # (rebuttal al falso «self._cfg stantio»: refresh/__init__/refresh_options lo aggiornano).
    from xtrader_bridge import custom_parser as cp
    from xtrader_bridge import name_mapping_store
    cp.save_parser(cp.CustomParserDef(
        name="P1", rules=[cp.FieldRule(target="Price", required=True)],
        name_mapping_profiles=["Nomi1"]), str(tmp_path))
    monkeypatch.setattr(cp, "default_parsers_dir", lambda: str(tmp_path))
    cfg = name_mapping_store.set_entries(
        {"active_parser": "P1"}, "Nomi1",
        [{"betfair": "Milan", "provider": "AC Milan", "sport": "Calcio"}])

    panel = object.__new__(gui_mod.SourceChatsPanel)
    panel._cfg = cfg
    panel._no_parser = "(predefinito)"
    Panel = gui_mod.SourceChatsPanel

    # override esplicito «P1» → mappatura nomi risolta → verde
    refs = {"parser": _Var("P1"), "trad_chip": _Label()}
    Panel._update_row_chip(panel, refs)
    assert refs["trad_chip"].text == "Nomi ✓ · Mercati —"
    assert refs["trad_chip"].color == gui_mod._CHIP_ON_COLOR

    # «(predefinito)» → usa active_parser globale «P1» → stesso esito (guidato da self._cfg)
    refs2 = {"parser": _Var("(predefinito)"), "trad_chip": _Label()}
    Panel._update_row_chip(panel, refs2)
    assert refs2["trad_chip"].text == "Nomi ✓ · Mercati —"

    # «(predefinito)» ma senza parser globale nello snapshot → nessuna traduzione (grigio)
    panel._cfg = dict(cfg)
    panel._cfg["active_parser"] = ""
    refs3 = {"parser": _Var("(predefinito)"), "trad_chip": _Label()}
    Panel._update_row_chip(panel, refs3)
    assert refs3["trad_chip"].text == "Nomi — · Mercati —"
    assert refs3["trad_chip"].color == gui_mod._CHIP_OFF_COLOR
