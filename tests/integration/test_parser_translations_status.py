"""Indicatore «🔗 Traduzioni attive per questo parser» ✓/— (#293).

Il Parser aveva già le checkbox dei profili di mappatura Nomi/Mercati; #293 le raggruppa in un
riquadro «Traduzioni attive» con un indicatore di stato per tipo. Qui si verifica la logica REALE:
il testo dell'indicatore (`_translations_status_text`, puro) e l'aggiornamento
(`_update_translations_status`) dai profili selezionati. `customtkinter` è stubbato (GUI, no display).
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
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    return importlib.import_module("xtrader_bridge.custom_parser_gui")


def test_status_text_pure(gui_mod):
    t = gui_mod._translations_status_text
    assert t(0) == "— nessuna"
    assert t(-1) == "— nessuna"       # difensivo
    assert t(1) == "✓ 1 attiva"
    assert t(2) == "✓ 2 attive"
    assert t(5) == "✓ 5 attive"


class _FakeLabel:
    def __init__(self):
        self.text = None
        self.color = None

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]
        if "text_color" in kw:
            self.color = kw["text_color"]


class _Var:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v


def _panel(gui_mod, *, name_checks, market_checks, name_order=(), market_order=(),
           existing_names=None, existing_markets=None):
    p = object.__new__(gui_mod.CustomParserPanel)
    p._nm_status_lbl = _FakeLabel()
    p._mm_status_lbl = _FakeLabel()
    p._profile_checks = {k: _Var(v) for k, v in name_checks.items()}
    p._market_profile_checks = {k: _Var(v) for k, v in market_checks.items()}
    # profili RISOLTI (esistenti): default = tutti quelli con checkbox (nessun fantasma).
    p._existing_profiles = set(name_checks if existing_names is None else existing_names)
    p._existing_market_profiles = set(market_checks if existing_markets is None else existing_markets)
    p.builder = types.SimpleNamespace(
        name_mapping_profiles=list(name_order), market_mapping_profiles=list(market_order))
    return p


def test_update_status_nomi_attive_mercati_no(gui_mod):
    p = _panel(gui_mod, name_checks={"A": True, "B": False}, market_checks={"M": False},
               name_order=["A"])
    gui_mod.CustomParserPanel._update_translations_status(p)
    assert p._nm_status_lbl.text == "✓ 1 attiva"
    assert p._nm_status_lbl.color == gui_mod._TRANSLATION_ON_COLOR
    assert p._mm_status_lbl.text == "— nessuna"
    assert p._mm_status_lbl.color == gui_mod._TRANSLATION_OFF_COLOR


def test_update_status_entrambe_e_conteggio(gui_mod):
    p = _panel(gui_mod, name_checks={"A": True, "B": True}, market_checks={"M": True},
               name_order=["A", "B"], market_order=["M"])
    gui_mod.CustomParserPanel._update_translations_status(p)
    assert p._nm_status_lbl.text == "✓ 2 attive"
    assert p._mm_status_lbl.text == "✓ 1 attiva"


def test_update_status_profilo_fantasma_non_conta(gui_mod):
    # Fable #336: un profilo ⚠ SELEZIONATO ma NON risolto (non esistente) NON è una traduzione
    # attiva → non gonfia il conteggio. Solo-fantasma → «— nessuna».
    p = _panel(gui_mod, name_checks={"⚠B": True}, market_checks={},
               name_order=["⚠B"], existing_names=[])   # ⚠B selezionato ma NON esistente
    gui_mod.CustomParserPanel._update_translations_status(p)
    assert p._nm_status_lbl.text == "— nessuna"
    # misto risolto + fantasma → conta solo il risolto
    p2 = _panel(gui_mod, name_checks={"A": True, "⚠B": True}, market_checks={},
                name_order=["A", "⚠B"], existing_names=["A"])
    gui_mod.CustomParserPanel._update_translations_status(p2)
    assert p2._nm_status_lbl.text == "✓ 1 attiva"


def test_set_translation_status_none_no_crash(gui_mod):
    # GLM #336: `_set_translation_status(None, ...)` è un no-op difensivo esplicito.
    p = object.__new__(gui_mod.CustomParserPanel)
    gui_mod.CustomParserPanel._set_translation_status(p, None, 5)   # non deve sollevare


def test_update_status_difensivo_senza_label(gui_mod):
    # Ordine di costruzione: se le etichette non esistono ancora, nessun crash.
    p = object.__new__(gui_mod.CustomParserPanel)
    p._profile_checks = {"A": _Var(True)}
    p._existing_profiles = {"A"}
    p.builder = types.SimpleNamespace(name_mapping_profiles=["A"], market_mapping_profiles=[])
    # nessun _nm_status_lbl / _mm_status_lbl / _market_profile_checks
    gui_mod.CustomParserPanel._update_translations_status(p)   # non deve sollevare
