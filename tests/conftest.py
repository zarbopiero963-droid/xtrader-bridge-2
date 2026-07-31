"""Configurazione comune dei test.

Rende importabile il package `xtrader_bridge` (root del repo). Dopo il refactor
di PR-03 i moduli testati (`parser`, `csv_writer`, `config_store`) NON importano
`customtkinter`, quindi non serve più alcuno stub GUI: la suite gira headless,
senza GUI e senza token Telegram.
"""

import os
import sys
import tempfile

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


# ── Capacità del filesystem: symlink (B7/B8 #194) ────────────────────────────────
# Fonte UNICA della sonda (rilievo Fable 5 su #203): era duplicata identica in
# `tests/safety/test_path_link_194.py` e `tests/integration/test_path_link_app_194.py`,
# cioè esattamente la divergenza che la regola 3 esiste per impedire — e in un helper
# che decide se un test SI ESEGUE, dove una copia disallineata non fallisce: SALTA, in
# silenzio.


def _sa_creare_link() -> bool:
    """Prova DAVVERO a creare un symlink, invece di dare per scontato che su Windows non
    si possa.

    Il salto incondizionato su `os.name == "nt"` lasciava Windows — l'ambiente più critico
    per il bridge — senza NESSUNA verifica su link e junction, proprio dove il contratto li
    promette. Con la sonda, un runner Windows che HA il privilegio (Developer Mode, o un
    account con SeCreateSymbolicLinkPrivilege) esegue i test invece di saltarli.

    Eseguita una sola volta a import di questo conftest: l'I/O è un file temporaneo in una
    cartella temporanea, e qualunque errore diventa `False` (si salta, mai si rompe).
    """
    if not hasattr(os, "symlink"):
        return False
    try:
        with tempfile.TemporaryDirectory() as d:
            bersaglio = os.path.join(d, "bersaglio")
            with open(bersaglio, "w", encoding="utf-8") as f:
                f.write("x")
            os.symlink(bersaglio, os.path.join(d, "link"))
            return True
    except (OSError, NotImplementedError, AttributeError):
        return False


SA_CREARE_LINK = _sa_creare_link()

richiede_link = pytest.mark.skipif(
    not SA_CREARE_LINK,
    reason="questo filesystem/utente non puo' creare symlink (su Windows serve Developer "
           "Mode o SeCreateSymbolicLinkPrivilege)")

richiede_hardlink = pytest.mark.skipif(
    not hasattr(os, "link"), reason="hard link non supportati su questo filesystem")


def crea_symlink(src: str, dst: str) -> None:
    """Crea un symlink per un test, o **salta** il test se questo filesystem non lo permette.

    La sonda gira in `%TEMP%`, i test in `tmp_path`: possono stare su volumi DIVERSI con
    politiche diverse, quindi la sonda può passare mentre la creazione reale fallisce
    (rilievo Fugu Ultra su #203). Senza questa rete il test non salterebbe — **fallirebbe**,
    per una ragione che non c'entra con ciò che verifica. Lo stesso criterio già usato dai
    test sugli hard link.
    """
    try:
        os.symlink(src, dst)
    except (OSError, NotImplementedError, AttributeError) as e:
        pytest.skip(f"symlink non creabile su questo filesystem: {e}")
