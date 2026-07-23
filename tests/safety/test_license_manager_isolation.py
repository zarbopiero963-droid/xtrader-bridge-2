"""Isolamento del License Manager dal bridge (issue #140 PR 3a — invariante #1).

Il License Manager custodisce e usa la chiave PRIVATA di firma. Quel codice non deve MAI finire
nell'EXE del bridge distribuito. La build dell'EXE colleziona solo `xtrader_bridge`
(`--collect-submodules xtrader_bridge`), quindi la garanzia si riduce a: **nessun modulo di
`xtrader_bridge` importa `license_manager`**. Questo test lo verifica staticamente sul sorgente e
sui workflow di build; se un domani un import accidentale trascinasse il tool del proprietario nel
package del bridge, fallisce.

La direzione OPPOSTA è lecita e voluta: `license_manager` importa `xtrader_bridge` (riusa Ed25519,
`build_license`, `atomic_io`). Solo il tool del proprietario gira sul suo PC.
"""

import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "xtrader_bridge")
_WORKFLOWS_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")

# Un import di `license_manager` in qualsiasi forma:
# - statico:  `import license_manager`, `from license_manager import …`, `import license_manager.core`;
# - DINAMICO: `importlib.import_module("license_manager…")`, `__import__("license_manager…")`
#   (review GLM #145: un import dinamico sfuggirebbe a un match solo sullo statico).
_LM_IMPORT = re.compile(
    r"^\s*(?:from\s+license_manager\b|import\s+license_manager\b)"          # statico
    r"|(?:import_module|__import__)\s*\(\s*[\"']license_manager\b",         # dinamico
    re.MULTILINE)


def _py_files(root):
    for dirpath, _dirs, names in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for n in names:
            if n.endswith(".py"):
                yield os.path.join(dirpath, n)


def test_il_bridge_non_importa_il_license_manager():
    offenders = []
    for path in _py_files(_BRIDGE_DIR):
        with open(path, "r", encoding="utf-8") as f:
            if _LM_IMPORT.search(f.read()):
                offenders.append(os.path.relpath(path, _REPO_ROOT))
    assert not offenders, (
        "il package del bridge NON deve importare license_manager (finirebbe nell'EXE, "
        f"trascinando la firma/chiave privata): {offenders}")


# Riga di comando che compila l'EXE del BRIDGE (PyInstaller/Nuitka su `main.py`, oppure che
# colleziona `xtrader_bridge`, oppure che produce l'eseguibile personale `XTrader-Signal-Bridge`).
# Solo queste righe non devono mai referenziare license_manager: un futuro workflow DEDICATO al
# License Manager (PR 3b) userà legittimamente `license_manager` per il PROPRIO EXE (review
# CodeRabbit #145), quindi NON si può vietare la parola in ogni workflow.
_BRIDGE_BUILD_CMD = re.compile(
    r"(?:pyinstaller|nuitka)\b.*(?:\bmain\.py\b|xtrader_bridge|XTrader-Signal-Bridge)"
    r"|--collect-\w+\s+xtrader_bridge",
    re.IGNORECASE)
# Un riferimento a license_manager come PACCHETTO da impacchettare (collect/include/hidden-import).
_LM_PACKAGED = re.compile(
    r"--collect-\w+[=\s]+license_manager\b|--include-package[=\s]+license_manager\b"
    r"|--hidden-import[=\s]+license_manager\b",
    re.IGNORECASE)


def test_i_workflow_di_build_non_collezionano_il_license_manager():
    # Solo i comandi che compilano l'EXE del BRIDGE non devono impacchettare license_manager.
    # (NON si vieta la parola in ogni workflow: PR 3b avrà un build dedicato al License Manager.)
    if not os.path.isdir(_WORKFLOWS_DIR):
        # Checkout ridotto/fork senza i workflow (review GPT #145): nessun workflow = niente da
        # collezionare. Non è un fallimento del gate.
        return
    offenders = []
    for n in sorted(os.listdir(_WORKFLOWS_DIR)):
        if not n.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(_WORKFLOWS_DIR, n), "r", encoding="utf-8") as f:
            text = f.read()
        for line in text.splitlines():
            if _BRIDGE_BUILD_CMD.search(line) and (
                    _LM_PACKAGED.search(line) or re.search(r"\blicense_manager\b", line)):
                offenders.append(f"{n}: {line.strip()}")
    assert not offenders, (
        "un comando di build dell'EXE del BRIDGE referenzia license_manager (lo trascinerebbe "
        f"nell'eseguibile del bridge): {offenders}")


def test_rileva_anche_gli_import_dinamici():
    # Regressione (review GLM #145): il detector deve intercettare ANCHE gli import dinamici, non
    # solo `import`/`from` statici — così un accidentale caricamento del tool nel bridge non sfugge.
    assert _LM_IMPORT.search('importlib.import_module("license_manager")')
    assert _LM_IMPORT.search("importlib.import_module('license_manager.core')")
    assert _LM_IMPORT.search('__import__("license_manager")')
    assert _LM_IMPORT.search("import license_manager")
    assert _LM_IMPORT.search("from license_manager import core")
    # controcampo: un nome che INIZIA per license_manager… ma è un altro package non è un match
    assert not _LM_IMPORT.search("import license_manager_helper")
    assert not _LM_IMPORT.search('importlib.import_module("license_managerX")')
    # controcampo: una menzione in un commento/stringa non-import non deve scattare
    assert not _LM_IMPORT.search("# vedi license_manager per i dettagli")


def test_scoping_build_bridge_vs_license_manager():
    # CR #145: il gate colpisce SOLO i comandi che compilano l'EXE del bridge, non ogni menzione
    # di license_manager. Un futuro build DEDICATO del License Manager (PR 3b) è lecito.
    bridge_bad = ("pyinstaller --onefile --name XTrader-Signal-Bridge "
                  "--collect-submodules xtrader_bridge --collect-submodules license_manager main.py")
    assert _BRIDGE_BUILD_CMD.search(bridge_bad)          # è un build del bridge…
    assert re.search(r"\blicense_manager\b", bridge_bad)  # …che referenzia il LM → verrebbe flaggato

    # build DEDICATO del License Manager (PR 3b): NON è un build del bridge → lecito
    lm_build = ("pyinstaller --onefile --name XTrader-License-Manager "
                "--collect-submodules license_manager license_manager_main.py")
    assert not _BRIDGE_BUILD_CMD.search(lm_build)

    # build del bridge SENZA license_manager: ok
    bridge_ok = ("pyinstaller --onefile --name XTrader-Signal-Bridge "
                 "--collect-submodules xtrader_bridge main.py")
    assert _BRIDGE_BUILD_CMD.search(bridge_ok)
    assert not re.search(r"\blicense_manager\b", bridge_ok)


def test_direzione_lecita_lm_importa_il_bridge():
    # Sanity: il License Manager PUÒ importare il bridge (riuso crittografia/atomic_io).
    from license_manager import core
    from xtrader_bridge.licensing import ed25519
    seed_hex, public_hex = core.generate_keypair()
    assert ed25519.public_key(bytes.fromhex(seed_hex)).hex() == public_hex
