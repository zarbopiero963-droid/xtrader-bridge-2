"""Collaudo #12 (2026-08-01): la finestra del bridge deve essere RIDIMENSIONABILE.

Trovato dal proprietario al primo collaudo reale: la finestra non si allargava né in larghezza
né — contrariamente all'intento di `resizable(False, True)` — in altezza percepita, lasciando una
schermata piccola e bloccata. Decisione del proprietario: ridimensionabile in ENTRAMBI gli assi.

La sicurezza del layout resta garantita dal MINIMO, non dal blocco: `fit_to_screen` imposta
`minsize(_WINDOW_WIDTH, 600)`, quindi la finestra può solo CRESCERE oltre il layout tarato —
il budget della riga CSV Path (`test_gen_layout_budget.py`) vale alla larghezza minima e resta
il pavimento. Meta-test a sorgente (pattern del repo per il cablaggio Tk, non esercitabile
headless senza display).
"""

import os
import re

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge", "app.py")
with open(_APP, encoding="utf-8") as _fh:
    _SRC = _fh.read()


def test_la_finestra_principale_e_ridimensionabile_in_entrambi_gli_assi():
    assert re.search(r"self\.resizable\(\s*True\s*,\s*True\s*\)", _SRC), (
        "la finestra principale non è resizable(True, True)")
    assert not re.search(r"self\.resizable\(\s*False", _SRC), (
        "c'è ancora un resizable(False, …) sulla finestra principale")


def test_il_minimo_resta_il_layout_tarato():
    """La larghezza minima deve restare `_WINDOW_WIDTH`: sotto quella il layout della riga
    CSV Path taglierebbe i pulsanti (è il caso che il budget-test protegge)."""
    assert re.search(r"fit_to_screen\(\s*self,\s*_WINDOW_WIDTH,\s*\d+,\s*_WINDOW_WIDTH,\s*\d+\)",
                     _SRC), "fit_to_screen non usa più _WINDOW_WIDTH come minimo"
