"""Ogni modulo del package che USA un modulo fratello deve anche IMPORTARLO.

Nato dal bug post-merge della #236: `name_mapping_gui._build_ui` faceva
``ui_cards.card_style(...)`` senza avere `ui_cards` nel blocco ``from . import``
→ `NameError` all'apertura di «Dizionario nomi» e «Dizionario mercati». La suite
non lo vedeva perché nessun test costruisce quei widget con CTk reale (vietato in
CI dopo l'incidente 2026-08-04): questa è la versione headless dello stesso
controllo — risoluzione statica dei nomi, nessun widget.

La risoluzione è **scope-aware** (rilievo convergente di Fable 5, GPT-5.5 e
Sourcery sulla prima versione, che raccoglieva `ast.arg` e assegnazioni di ogni
scope come nomi di modulo): un parametro o una variabile locale chiamati come un
modulo fratello coprono SOLO gli usi dentro il loro scope — es. il pattern
legittimo ``def card(ctk, ...)`` — mentre un uso a livello di metodo senza
binding locale né import a livello modulo resta scoperto e fallisce.

Il controllo è generale (tutti i moduli fratelli, non solo `ui_cards`): la
regola 2 chiede la classe, non il sito.
"""
from __future__ import annotations

import ast
import pathlib
import textwrap

PKG = pathlib.Path(__file__).resolve().parents[2] / "xtrader_bridge"
SIBLINGS = {p.stem for p in PKG.glob("*.py") if p.stem != "__init__"}

_SCOPI = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _binding_di_scope(nodo: ast.AST) -> set[str]:
    """Nomi legati DENTRO questo scope (funzione o modulo), senza entrare negli
    scope funzione annidati; le classi non fanno scope per i metodi, quindi nei
    loro corpi si entra solo per raccogliere i binding a livello classe quando
    lo scope è la classe stessa — per il lookup dei metodi contano modulo e
    funzioni contenitrici, ed è così che le attraversiamo."""
    nomi: set[str] = set()

    if isinstance(nodo, _SCOPI):
        args = nodo.args
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            nomi.add(a.arg)
        if args.vararg:
            nomi.add(args.vararg.arg)
        if args.kwarg:
            nomi.add(args.kwarg.arg)

    def raccogli(stmts):
        for s in stmts:
            if isinstance(s, _SCOPI + (ast.ClassDef,)):
                if hasattr(s, "name"):
                    nomi.add(s.name)
                continue  # scope/namespace separato: non raccogliere i suoi binding
            if isinstance(s, ast.Import):
                for a in s.names:
                    nomi.add(a.asname or a.name.split(".")[0])
            elif isinstance(s, ast.ImportFrom):
                for a in s.names:
                    nomi.add(a.asname or a.name)
            elif isinstance(s, ast.Assign):
                for t in s.targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            nomi.add(n.id)
            elif isinstance(s, (ast.AnnAssign, ast.AugAssign)):
                if isinstance(s.target, ast.Name):
                    nomi.add(s.target.id)
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                for n in ast.walk(s.target):
                    if isinstance(n, ast.Name):
                        nomi.add(n.id)
                raccogli(s.body); raccogli(s.orelse)
                continue
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                for item in s.items:
                    if item.optional_vars is not None:
                        for n in ast.walk(item.optional_vars):
                            if isinstance(n, ast.Name):
                                nomi.add(n.id)
                raccogli(s.body)
                continue
            elif isinstance(s, ast.Try):
                for h in s.handlers:
                    if h.name:
                        nomi.add(h.name)
                    raccogli(h.body)
                raccogli(s.body); raccogli(s.orelse); raccogli(s.finalbody)
                continue
            # walrus e target di comprehension dentro le espressioni dello statement
            for n in ast.walk(s):
                if isinstance(n, _SCOPI):
                    break
                if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
                    nomi.add(n.target.id)
                if isinstance(n, ast.comprehension):
                    for t in ast.walk(n.target):
                        if isinstance(t, ast.Name):
                            nomi.add(t.id)
            # statement composti restanti: scendi nei rami
            for campo in ("body", "orelse"):
                sotto = getattr(s, campo, None)
                if isinstance(sotto, list) and sotto and isinstance(sotto[0], ast.stmt):
                    raccogli(sotto)

    corpo = nodo.body if not isinstance(nodo, ast.Lambda) else []
    raccogli(corpo if isinstance(corpo, list) else [])
    return nomi


def _usi_non_risolti(tree: ast.Module) -> set[str]:
    """Moduli fratelli usati come ``x.attr`` senza binding nella catena di scope."""
    rotti: set[str] = set()

    def visita(nodo: ast.AST, catena: tuple[frozenset[str], ...]):
        if isinstance(nodo, _SCOPI):
            catena = catena + (frozenset(_binding_di_scope(nodo)),)
        for figlio in ast.iter_child_nodes(nodo):
            if (isinstance(figlio, ast.Attribute)
                    and isinstance(figlio.value, ast.Name)
                    and figlio.value.id in SIBLINGS
                    and not any(figlio.value.id in s for s in catena)):
                rotti.add(figlio.value.id)
            visita(figlio, catena)

    visita(tree, (frozenset(_binding_di_scope(tree)),))
    return rotti


def test_ogni_uso_di_modulo_fratello_ha_il_suo_import():
    rotti: list[str] = []
    for path in sorted(PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for modulo in sorted(_usi_non_risolti(tree)):
            if modulo == path.stem:
                continue  # riferimento a se stesso
            rotti.append(f"{path.name}: usa `{modulo}.` ma non lo importa")
    assert rotti == [], "\n".join(rotti)


# ---- il test del tester: il rilevatore stesso è esercitato su sorgenti sintetici ----

def _controlla(src: str) -> set[str]:
    return _usi_non_risolti(ast.parse(textwrap.dedent(src)))


def test_rilevatore_prende_il_bug_reale_della_236():
    """Uso in un metodo, nessun import: il caso name_mapping_gui, deve scattare."""
    assert "ui_cards" in _controlla("""
        class Pannello:
            def _build_ui(self):
                stile = ui_cards.card_style()
    """)


def test_rilevatore_non_scatta_su_import_a_livello_modulo():
    assert _controlla("""
        from . import ui_cards
        class Pannello:
            def _build_ui(self):
                stile = ui_cards.card_style()
    """) == set()


def test_rilevatore_parametro_copre_solo_il_suo_scope():
    """Il rilievo dei reviewer sulla v1: un parametro omonimo NON deve più
    mascherare l'uso scoperto in un'ALTRA funzione."""
    src = """
        def helper(ui_cards):
            return ui_cards.card_style()   # legittimo: e' il parametro

        def rotta():
            return ui_cards.badge()        # scoperto: nessun import
    """
    assert _controlla(src) == {"ui_cards"}


def test_rilevatore_import_locale_alla_funzione_vale():
    assert _controlla("""
        def lazy():
            from . import ui_cards
            return ui_cards.card_style()
    """) == set()
