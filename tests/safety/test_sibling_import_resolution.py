"""Ogni modulo del package che USA un modulo fratello deve anche IMPORTARLO.

Nato dal bug post-merge della #236: `name_mapping_gui._build_ui` faceva
``ui_cards.card_style(...)`` senza avere `ui_cards` nel blocco ``from . import``
→ `NameError` all'apertura di «Dizionario nomi» e «Dizionario mercati». La suite
non lo vedeva perché nessun test costruisce quei widget con CTk reale (vietato in
CI dopo l'incidente 2026-08-04): questa è la versione headless dello stesso
controllo — risoluzione statica dei nomi, nessun widget.

Il controllo è generale (tutti i moduli fratelli, non solo `ui_cards`): la regola
2 chiede la classe, non il sito.
"""
from __future__ import annotations

import ast
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[2] / "xtrader_bridge"
SIBLINGS = {p.stem for p in PKG.glob("*.py") if p.stem != "__init__"}


def _nomi_definiti(tree: ast.Module) -> set[str]:
    """Nomi resi disponibili a livello modulo: import, assegnazioni, def/class."""
    nomi: set[str] = set()
    for nodo in ast.walk(tree):
        if isinstance(nodo, ast.Import):
            for a in nodo.names:
                nomi.add(a.asname or a.name.split(".")[0])
        elif isinstance(nodo, ast.ImportFrom):
            for a in nodo.names:
                nomi.add(a.asname or a.name)
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nomi.add(nodo.name)
        elif isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name):
                    nomi.add(t.id)
        elif isinstance(nodo, (ast.arg,)):
            nomi.add(nodo.arg)
    return nomi


def _usi_da_modulo(tree: ast.Module) -> set[str]:
    """Nomi di moduli fratelli usati come ``modulo.attributo``."""
    usi: set[str] = set()
    for nodo in ast.walk(tree):
        if (isinstance(nodo, ast.Attribute)
                and isinstance(nodo.value, ast.Name)
                and nodo.value.id in SIBLINGS):
            usi.add(nodo.value.id)
    return usi


def test_ogni_uso_di_modulo_fratello_ha_il_suo_import():
    rotti: list[str] = []
    for path in sorted(PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definiti = _nomi_definiti(tree)
        for modulo in sorted(_usi_da_modulo(tree)):
            if modulo == path.stem:
                continue  # riferimento a se stesso (es. ricorsione qualificata)
            if modulo not in definiti:
                rotti.append(f"{path.name}: usa `{modulo}.` ma non lo importa")
    assert rotti == [], "\n".join(rotti)
