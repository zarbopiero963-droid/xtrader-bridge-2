"""Scorrimento fluido delle CTkScrollableFrame (segnalazione proprietario 2026-08-04).

Sintomo su Windows: nella scheda Parser Personalizzato (soprattutto sulla
«Griglia regole — 14 colonne CSV») lo scroll con la rotellina «scatta/trema».
Causa misurata: CustomTkinter su Windows imposta ``yscrollincrement=1`` e scrolla
``-delta/6`` (=20) unità per scatto → **20px a scatto** su un contenuto di
~2600px: ~130 scatti per attraversarlo, e OGNI scatto ridisegna decine di widget
con angoli arrotondati → tremolio percepito.

Rimedio (fonte unica, regola 3): ``ui_cards.tune_scrolling(sf)`` porta gli
increment del canvas a 3px → ~60px per scatto con un TERZO dei ridisegni, senza
toccare i binding di CustomTkinter. Va chiamata su OGNI CTkScrollableFrame del
package (la classe, non il sito — regola 2): il test sorgente qui sotto lo
impone contando costruzioni e chiamate per modulo.
"""
from __future__ import annotations

import pathlib
import re

from xtrader_bridge import ui_cards

PKG = pathlib.Path(ui_cards.__file__).parent


class _CanvasDoppio:
    def __init__(self):
        self.kwargs = {}

    def configure(self, **kw):
        self.kwargs.update(kw)


class _ScrollableDoppio:
    def __init__(self):
        self._parent_canvas = _CanvasDoppio()


def test_tune_scrolling_imposta_gli_increment_a_3px():
    sf = _ScrollableDoppio()
    ui_cards.tune_scrolling(sf)
    assert sf._parent_canvas.kwargs == {"xscrollincrement": 3, "yscrollincrement": 3}


def test_tune_scrolling_passo_personalizzato():
    sf = _ScrollableDoppio()
    ui_cards.tune_scrolling(sf, step_px=5)
    assert sf._parent_canvas.kwargs == {"xscrollincrement": 5, "yscrollincrement": 5}


def test_tune_scrolling_best_effort_su_doppio_senza_canvas():
    """Doppio headless senza `_parent_canvas` (o canvas che solleva): mai un crash —
    lo scroll resta quello di default, la GUI vive."""
    ui_cards.tune_scrolling(object())          # nessun _parent_canvas

    class _CanvasRotto:
        def configure(self, **kw):
            raise RuntimeError("canvas distrutto")

    class _SfRotto:
        _parent_canvas = _CanvasRotto()

    ui_cards.tune_scrolling(_SfRotto())        # configure che solleva → assorbito


def test_ogni_scrollable_del_package_viene_accordata():
    """La classe, non il sito: OGNI `ctk.CTkScrollableFrame(` costruita nel package
    deve avere la sua `ui_cards.tune_scrolling(...)` nello stesso modulo — una
    costruzione senza accordatura è una scrollable che torna a 20px/scatto."""
    rotti = []
    for path in sorted(PKG.glob("*.py")):
        if path.name == "ui_cards.py":
            continue
        src = path.read_text(encoding="utf-8")
        costruzioni = len(re.findall(r"ctk\.CTkScrollableFrame\(", src))
        accordi = src.count("ui_cards.tune_scrolling(")
        if costruzioni != accordi:
            rotti.append(f"{path.name}: {costruzioni} scrollable, {accordi} tune_scrolling")
    assert rotti == [], "\n".join(rotti)
