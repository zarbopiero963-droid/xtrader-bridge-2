"""Configurazione comune dei test.

Rende importabile il package `xtrader_bridge` (root del repo). Dopo il refactor
di PR-03 i moduli testati (`parser`, `csv_writer`, `config_store`) NON importano
`customtkinter`, quindi non serve più alcuno stub GUI: la suite gira headless,
senza GUI e senza token Telegram.
"""

import importlib.util
import os
import sys
import tempfile

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ── Guardia anti-shadowing di `tests` (rilievo GPT-5.5 su #209) ────────────────────────────────
#
# Vari moduli condividono costanti e sonde con `from tests.conftest import …`
# (`test_path_link_194.py`, `test_path_link_app_194.py`, i sei file di licenza). `tests/` non ha
# `__init__.py`, quindi è un **namespace package** — e un namespace PERDE contro un package
# **regolare** con lo stesso nome trovato più avanti in `sys.path`: la ricerca si ferma al primo
# `__init__.py`, anche se il namespace stava in posizione 0. Se un pacchetto installato portasse
# un top-level `tests/__init__.py`, quegli import risolverebbero altrove.
#
# Misurato: la collection si interrompe con `ModuleNotFoundError: No module named 'tests.conftest'`
# — un messaggio che non nomina la causa e manda a cercare il problema nel posto sbagliato. Peggio,
# se il package estraneo avesse a sua volta un `conftest`, l'import riuscirebbe **silenziosamente**
# con le costanti sbagliate.
#
# Questo file lo carica pytest **per path**, non via `import tests.conftest`: la guardia gira
# sempre, anche quando lo shadowing c'è, ed è l'unico punto in cui può girare.
def _verifica_nessuno_shadowing_di_tests(percorso_atteso=None):
    """Solleva `RuntimeError` se il nome `tests` non risolve a QUESTA cartella.

    `percorso_atteso` esiste per poter esercitare la guardia nei test senza dover installare
    davvero un package ostile; in esercizio si usa il default.
    """
    atteso = os.path.abspath(percorso_atteso or os.path.dirname(os.path.abspath(__file__)))
    try:
        spec = importlib.util.find_spec("tests")
    except (ImportError, ValueError) as exc:            # pragma: no cover — ambiente rotto
        raise RuntimeError(f"impossibile risolvere il nome 'tests': {exc!r}") from exc
    percorsi = [os.path.abspath(p) for p in (getattr(spec, "submodule_search_locations", None) or ())]
    if atteso not in percorsi:
        raise RuntimeError(
            "il nome 'tests' NON risolve alla cartella dei test di questo repository.\n"
            f"  atteso:   {atteso}\n"
            f"  risolve a: {percorsi or (spec.origin if spec else 'nulla')}\n"
            "Causa tipica: un pacchetto installato espone un top-level `tests/__init__.py`, che "
            "essendo un package REGOLARE vince sul namespace package di questo repo. Rimuovilo "
            "dall'ambiente (o installa in un virtualenv pulito): senza, "
            "`from tests.conftest import …` legge le costanti di un altro progetto.")


_verifica_nessuno_shadowing_di_tests()

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


# ── Keypair di TEST per i test di licenza (dal 2026-07-31) ─────────────────────────────────────
#
# Fino al 2026-07-31 `license.LICENSE_PUBLIC_KEY_HEX` conteneva la chiave pubblica di **TEST**,
# quindi i test potevano firmare col seed di test e verificare contro il default del modulo. Dal
# momento in cui il proprietario ha messo la propria chiave **reale** (issue #12 PARTE 0) quel
# default non combacia più: i test che esercitano la logica di licenza devono dichiarare
# esplicitamente che la chiave "deployata" nel loro contesto è quella di test, altrimenti
# verificherebbero firme che nessuno di loro può produrre.
#
# La fixture patcha **due** posti, e il secondo è facile da dimenticare: `revocation.py` fa
# `from .license import LICENSE_PUBLIC_KEY_HEX`, cioè copia il valore all'import. Patchare il solo
# `license` lascerebbe la verifica delle liste di revoca sulla chiave reale.
LICENSE_TEST_SEED_HEX = "a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00"  # pragma: allowlist secret


@pytest.fixture
def chiave_pubblica_di_test(monkeypatch):
    """Rende la chiave pubblica *deployata* quella del seed di TEST, per la durata del test.

    Ritorna l'esadecimale della pubblica, per i test che devono passarla esplicitamente."""
    from xtrader_bridge.licensing import ed25519
    from xtrader_bridge.licensing import license as _lic
    from xtrader_bridge.licensing import revocation as _rev

    pub = ed25519.public_key(bytes.fromhex(LICENSE_TEST_SEED_HEX)).hex()
    monkeypatch.setattr(_lic, "LICENSE_PUBLIC_KEY_HEX", pub)
    monkeypatch.setattr(_rev, "LICENSE_PUBLIC_KEY_HEX", pub)   # copia by-value: va patchata a parte
    return pub
