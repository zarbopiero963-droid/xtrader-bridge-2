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
