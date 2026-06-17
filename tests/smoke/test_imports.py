"""Smoke test: tutti i moduli del package si importano headless.

Intercetta rotture di import/packaging senza avviare la GUI né Telegram.
La lista dei moduli "puri" è scoperta dinamicamente (pkgutil), così resta in
sync da sola quando si aggiungono nuovi moduli. `app` è escluso perché importa
customtkinter (GUI) ed è gestito a parte con importorskip.
"""

import importlib
import pkgutil

import pytest

import xtrader_bridge

# Moduli con side-effect all'import (GUI/servizi): testati separatamente.
_IMPURE = {"xtrader_bridge.app", "xtrader_bridge.custom_parser_gui"}

# Moduli core che DEVONO sempre essere presenti (guardia contro discovery rotta).
_CORE = {
    "xtrader_bridge.parser",
    "xtrader_bridge.csv_writer",
    "xtrader_bridge.config_store",
    "xtrader_bridge.recognition",
    "xtrader_bridge.dizionario",
    "xtrader_bridge.signal_gate",
}


def _discover_pure_modules() -> list:
    found = ["xtrader_bridge"]
    # iter_modules elenca i nomi senza importarli: sicuro anche per i moduli impuri.
    for info in pkgutil.iter_modules(xtrader_bridge.__path__, xtrader_bridge.__name__ + "."):
        if info.name not in _IMPURE:
            found.append(info.name)
    return sorted(found)


PURE_MODULES = _discover_pure_modules()


def test_discovery_include_i_moduli_core():
    # Se la discovery si rompe (lista vuota/incompleta) il test deve fallire,
    # non passare in silenzio.
    assert _CORE.issubset(set(PURE_MODULES))


@pytest.mark.parametrize("mod", PURE_MODULES)
def test_import_modulo_puro(mod):
    assert importlib.import_module(mod) is not None


def test_app_import_opzionale():
    # app dipende da customtkinter: se assente nell'ambiente, lo skippiamo.
    pytest.importorskip("customtkinter")
    assert importlib.import_module("xtrader_bridge.app") is not None


def test_custom_parser_gui_import_opzionale():
    # La GUI del costruttore dipende da customtkinter: skip se assente.
    pytest.importorskip("customtkinter")
    assert importlib.import_module("xtrader_bridge.custom_parser_gui") is not None
