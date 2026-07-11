"""Test headless della glue GUI `DictionaryViewerPanel`: degrado con `controller=None`
(CodeRabbit/Fugu #20).

`_make_dictionary` (app.py) costruisce il pannello con `controller=self._dictionary_viewer_controller()`,
che è **None** se il DB locale non è apribile (AppData non scrivibile, disco pieno, file corrotto,
permessi). Qui verifichiamo il lato pannello dell'invariante: con `controller=None` il pannello
mostra l'avviso «Dizionario non disponibile» e **non solleva** (il crash non si sposta dalla
factory al render della scheda Strumenti).

`dictionary_viewer_gui` richiede `customtkinter` (un display) e non è importabile headless: si
stubba SOLO la libreria GUI con classi reali vuote, così il modulo si importa e si esercita il
VERO metodo `_refresh` su un `self` finto (nessun widget reale creato).
"""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def viewer_gui(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    # Il pannello importa anche `from tkinter import ttk` (Treeview nativo): stubba tkinter e
    # tkinter.ttk con classi vuote quando il display/Tk non è disponibile (CI headless).
    try:
        import tkinter  # noqa: F401
        from tkinter import ttk  # noqa: F401
    except ModuleNotFoundError:
        tk_mod = _FakeCtkModule("tkinter")
        ttk_mod = _FakeCtkModule("tkinter.ttk")
        tk_mod.ttk = ttk_mod
        monkeypatch.setitem(sys.modules, "tkinter", tk_mod)
        monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk_mod)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.betfair.dictionary_viewer_gui", raising=False)
    return importlib.import_module("xtrader_bridge.betfair.dictionary_viewer_gui")


def _fake_self():
    """Self minimale per il ramo `controller is None` di `_refresh`: servono solo
    `_clear_tree_rows` (registra le chiamate) e `_counts` (registra le `configure`). Il ramo
    esce PRIMA di qualunque accesso al controller/DB, quindi nient'altro è necessario."""
    cfg, cleared = [], []
    fake = types.SimpleNamespace(
        controller=None,
        _clear_tree_rows=lambda: cleared.append(1),
        _counts=types.SimpleNamespace(configure=lambda **k: cfg.append(k)),
    )
    return fake, cfg, cleared


def test_refresh_controller_none_mostra_avviso_senza_crash(viewer_gui):
    """Con `controller=None` il pannello NON solleva e mostra «Dizionario non disponibile»
    (il DB non apribile degrada, non crasha la scheda Strumenti — CodeRabbit/Fugu #20)."""
    fake, cfg, cleared = _fake_self()
    viewer_gui.DictionaryViewerPanel._refresh(fake)     # non deve sollevare
    assert cleared == [1]                               # ha ripulito la tabella
    assert len(cfg) == 1 and "non disponibile" in cfg[-1]["text"]   # solo l'avviso, poi return
