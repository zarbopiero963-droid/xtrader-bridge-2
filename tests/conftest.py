"""Configurazione comune dei test.

Rende importabile il package `xtrader_bridge` (root del repo). Dopo il refactor
di PR-03 i moduli testati (`parser`, `csv_writer`, `config_store`) NON importano
`customtkinter`, quindi non serve più alcuno stub GUI: la suite gira headless,
senza GUI e senza token Telegram.
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Categorie = cartelle sotto tests/. L'auto-marking applica il marker giusto in
# base alla cartella del test, così i selettori `-m` (es. "unit or safety") e i
# profili commit/pr/release funzionano senza decorare ogni singolo test.
_DIR_MARKERS = ("unit", "integration", "safety", "smoke", "e2e", "slow", "manual")


def pytest_collection_modifyitems(config, items):
    for item in items:
        parts = item.nodeid.replace("\\", "/").split("/")
        # Applica TUTTI i marker presenti nella path (niente break): così un test
        # in "tests/integration/manual/..." è sia integration sia manual e viene
        # escluso dai profili commit/pr (-m "not manual" / "not slow ...").
        for marker in _DIR_MARKERS:
            if marker in parts:
                item.add_marker(getattr(pytest.mark, marker))
