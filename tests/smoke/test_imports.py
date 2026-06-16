"""Smoke test: tutti i moduli del package si importano headless.

Intercetta rotture di import/packaging senza avviare la GUI né Telegram.
(`app` importa customtkinter: se non installato in CI, l'import può fallire ed
è atteso; per questo è gestito a parte e marcato skip.)
"""

import importlib

import pytest

PURE_MODULES = [
    "xtrader_bridge",
    "xtrader_bridge.parser",
    "xtrader_bridge.csv_writer",
    "xtrader_bridge.config_store",
    "xtrader_bridge.recognition",
    "xtrader_bridge.dizionario",
    "xtrader_bridge.signal_gate",
]


@pytest.mark.parametrize("mod", PURE_MODULES)
def test_import_modulo_puro(mod):
    assert importlib.import_module(mod) is not None


def test_app_import_opzionale():
    # app dipende da customtkinter: se assente nell'ambiente, lo skippiamo.
    pytest.importorskip("customtkinter")
    assert importlib.import_module("xtrader_bridge.app") is not None
