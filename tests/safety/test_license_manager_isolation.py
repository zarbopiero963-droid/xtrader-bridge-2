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

# Un import di `license_manager` in qualsiasi forma (`import license_manager`,
# `from license_manager import …`, `import license_manager.core`).
_LM_IMPORT = re.compile(r"^\s*(?:from\s+license_manager\b|import\s+license_manager\b)", re.MULTILINE)


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


def test_i_workflow_di_build_non_collezionano_il_license_manager():
    # Nessun --collect-*/--include-package license_manager, e in generale nessuna menzione di
    # license_manager nei comandi di build dell'EXE del bridge.
    offenders = []
    for n in sorted(os.listdir(_WORKFLOWS_DIR)):
        if not n.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(_WORKFLOWS_DIR, n), "r", encoding="utf-8") as f:
            text = f.read()
        if re.search(r"--collect-\w+\s+license_manager|--include-package[=\s]+license_manager"
                     r"|\blicense_manager\b", text):
            offenders.append(n)
    assert not offenders, (
        "i workflow di build del bridge non devono referenziare license_manager: "
        f"{offenders}")


def test_direzione_lecita_lm_importa_il_bridge():
    # Sanity: il License Manager PUÒ importare il bridge (riuso crittografia/atomic_io).
    from license_manager import core
    from xtrader_bridge.licensing import ed25519
    seed_hex, public_hex = core.generate_keypair()
    assert ed25519.public_key(bytes.fromhex(seed_hex)).hex() == public_hex
