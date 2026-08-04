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

import ast
import pathlib

from xtrader_bridge import ui_cards

import license_manager as _license_manager_pkg

PKG = pathlib.Path(ui_cards.__file__).parent
# Anche l'app License Manager (separata) ha GUI scrollabili: la guardia copre
# entrambe (segnalazione proprietario 2026-08-04: «controlla anche le altre
# parti dove ho lo scroll» — l'audit runtime ha trovato il suo pannello nudo).
# I path vengono dai moduli IMPORTATI, non da posizioni relative (Sourcery #242).
PACKAGES = (PKG, pathlib.Path(_license_manager_pkg.__file__).parent)


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


def test_la_scansione_copre_anche_i_sottopackage():
    """Rilievo CodeRabbit #241: `glob` vedeva solo i figli diretti — una scrollable
    aggiunta in un sottopackage (es. `betfair/`) avrebbe bypassato la guardia.
    Il contratto è ricorsivo: la scansione deve includere i moduli annidati."""
    annidati = [p for p in PKG.rglob("*.py") if p.parent != PKG]
    assert annidati, "il package ha sottomoduli: se spariscono, rivedere la guardia"
    assert set(PKG.rglob("*.py")) >= set(annidati)


def _nome_target(nodo) -> str | None:
    """Rappresentazione testuale del bersaglio: `x` o `self._x` (altro → None)."""
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        return f"{nodo.value.id}.{nodo.attr}"
    return None


def _scrollable_non_accordate(src: str) -> list[str]:
    """Analisi STRUTTURALE (rilievo CodeRabbit #242: il conteggio testuale poteva
    essere ingannato da un commento o da una chiamata doppia): ogni variabile a cui
    è assegnata una `ctk.CTkScrollableFrame(...)` deve comparire come argomento di
    una `ui_cards.tune_scrolling(...)` nello stesso modulo."""
    tree = ast.parse(src)
    costruite: list[str] = []
    accordate: set[str] = set()
    for nodo in ast.walk(tree):
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call):
            f = nodo.value.func
            if isinstance(f, ast.Attribute) and f.attr == "CTkScrollableFrame":
                for t in nodo.targets:
                    nome = _nome_target(t)
                    if nome:
                        costruite.append(nome)
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "tune_scrolling" and nodo.args):
            nome = _nome_target(nodo.args[0])
            if nome:
                accordate.add(nome)
    return [n for n in costruite if n not in accordate]


def test_ogni_scrollable_di_entrambi_i_package_viene_accordata():
    """La classe, non il sito — su ENTRAMBI i package (bridge + License Manager):
    ogni `CTkScrollableFrame` costruita deve essere passata a `tune_scrolling`,
    con associazione per-variabile (non per conteggio)."""
    rotti = []
    for pkg in PACKAGES:
        for path in sorted(pkg.rglob("*.py")):
            if path.name == "ui_cards.py":
                continue
            for nome in _scrollable_non_accordate(path.read_text(encoding="utf-8")):
                rotti.append(f"{path.name}: `{nome}` costruita ma mai accordata")
    assert rotti == [], "\n".join(rotti)


def test_guardia_strutturale_non_si_fa_ingannare():
    """Le fixture del rilievo: un commento non conta come accordatura, una chiamata
    doppia su un'altra variabile non copre quella nuda."""
    assert _scrollable_non_accordate(
        "a = ctk.CTkScrollableFrame(x)\n# ui_cards.tune_scrolling(a)\n") == ["a"]
    assert _scrollable_non_accordate(
        "a = ctk.CTkScrollableFrame(x)\nb = ctk.CTkScrollableFrame(x)\n"
        "ui_cards.tune_scrolling(a)\nui_cards.tune_scrolling(a)\n") == ["b"]
    assert _scrollable_non_accordate(
        "self._lista = ctk.CTkScrollableFrame(x)\n"
        "ui_cards.tune_scrolling(self._lista)\n") == []
