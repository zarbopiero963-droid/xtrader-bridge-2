"""Configurazione comune dei test.

Rende importabile il package `xtrader_bridge` (root del repo). Dopo il refactor
di PR-03 i moduli testati (`parser`, `csv_writer`, `config_store`) NON importano
`customtkinter`, quindi non serve più alcuno stub GUI: la suite gira headless,
senza GUI e senza token Telegram.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
