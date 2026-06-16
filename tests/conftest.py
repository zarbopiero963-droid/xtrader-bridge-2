"""Configurazione comune dei test.

Rende importabile `main.py` (root del repo) e fornisce uno stub minimo di
`customtkinter` quando la libreria GUI non è installata, così la suite gira
headless, senza GUI e senza token Telegram.
"""

import os
import sys
import types

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if "customtkinter" not in sys.modules:
    try:
        import customtkinter  # noqa: F401
    except Exception:
        # Contratto dello stub: simboli garantiti per importare main.py headless.
        #   - set_appearance_mode(*a, **k) / set_default_color_theme(*a, **k)
        #   - CTk  (classe base, istanziabile senza argomenti)
        #   - CTkFont(*a, **k)
        # Se il codice di produzione userà altri widget/metodi, aggiornare qui.
        # Lo stub è già esercitato dai test che importano `main` (parser/CSV/config).
        _stub = types.ModuleType("customtkinter")
        _stub.set_appearance_mode = lambda *a, **k: None
        _stub.set_default_color_theme = lambda *a, **k: None
        _stub.CTk = type("CTk", (), {})
        _stub.CTkFont = lambda *a, **k: None
        sys.modules["customtkinter"] = _stub
