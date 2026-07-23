"""Isolamento del License Manager dal bridge (issue #140 PR 3a — invariante #1).

Il License Manager custodisce e usa la chiave PRIVATA di firma. Quel codice non deve MAI finire
nell'EXE del bridge distribuito. La build dell'EXE colleziona solo `xtrader_bridge`
(`--collect-submodules xtrader_bridge`), e PyInstaller segue gli import: quindi la garanzia si
riduce a **nessun modulo di `xtrader_bridge` importa `license_manager`** (statico o dinamico). Più,
come rete secondaria, **nessun comando di build del bridge impacchetta esplicitamente
`license_manager`**.

Il rilevamento degli import usa l'**AST** (review CodeRabbit/GLM/GPT #145), non una regex: così un
`import_module` dentro una stringa/commento o un nome simile (`custom_import_module`) non è un falso
positivo, e un import dinamico letterale (`importlib.import_module("license_manager")` /
`__import__("license_manager")`) non è un falso negativo.

La direzione OPPOSTA è lecita e voluta: `license_manager` importa `xtrader_bridge` (riusa Ed25519,
`build_license`, `atomic_io`). Solo il tool del proprietario gira sul suo PC.
"""

import ast
import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "xtrader_bridge")
_WORKFLOWS_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")

_LM = "license_manager"


def _targets_lm(name) -> bool:
    """`True` se `name` è il package `license_manager` o un suo sottomodulo (`license_manager.x`)."""
    return isinstance(name, str) and (name == _LM or name.startswith(_LM + "."))


def source_imports_license_manager(source: str) -> bool:
    """`True` se il sorgente Python importa `license_manager` — via `import`/`from` **o** via
    import dinamico LETTERALE (`importlib.import_module("license_manager…")` /
    `__import__("license_manager…")`). Basato su **AST**: stringhe, commenti e nomi-funzione simili
    (`custom_import_module`) non producono falsi positivi."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_targets_lm(a.name) for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            # `from license_manager import …` (livello 0; gli import relativi hanno module None)
            if node.level == 0 and _targets_lm(node.module):
                return True
        elif isinstance(node, ast.Call):
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if fname in ("import_module", "__import__") and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and _targets_lm(arg0.value):
                    return True
    return False


def _bridge_py_files():
    for dirpath, _dirs, names in os.walk(_BRIDGE_DIR):
        if "__pycache__" in dirpath:
            continue
        for n in names:
            if n.endswith(".py"):
                yield os.path.join(dirpath, n)


def test_il_bridge_non_importa_il_license_manager():
    offenders = []
    for path in _bridge_py_files():
        with open(path, "r", encoding="utf-8") as f:
            if source_imports_license_manager(f.read()):
                offenders.append(os.path.relpath(path, _REPO_ROOT))
    assert not offenders, (
        "il package del bridge NON deve importare license_manager (finirebbe nell'EXE, "
        f"trascinando la firma/chiave privata): {offenders}")


def test_ast_detector_veritiero():
    # Import che DEVONO essere rilevati (statici + dinamici letterali).
    for src in (
        "import license_manager",
        "import license_manager.core",
        "from license_manager import core",
        "from license_manager.core import issue_license",
        'importlib.import_module("license_manager")',
        "importlib.import_module('license_manager.core')",
        '__import__("license_manager")',
    ):
        assert source_imports_license_manager(src), f"non rilevato: {src!r}"
    # Controcampi che NON devono scattare (niente falsi positivi da AST).
    for src in (
        "import license_manager_helper",                       # ALTRO package
        "from license_manager_helper import x",
        '# importlib.import_module("license_manager")',        # commento
        'doc = "usa importlib.import_module(\\"license_manager\\")"',  # stringa
        'custom_import_module("license_manager")',             # funzione con nome simile
        'importlib.import_module("license_managerX")',         # nome che inizia per… ma diverso
        "from . import license_manager as _lm",                # import RELATIVO interno (non il pkg top-level)
    ):
        assert not source_imports_license_manager(src), f"falso positivo: {src!r}"


# ── Rete secondaria: nessun comando di build del BRIDGE impacchetta license_manager ────────────
# Robusto ai comandi MULTILINEA (review GPT/GLM #145): il controllo è a livello di FILE, non riga
# per riga, così una direttiva su una riga di continuazione non sfugge. Un workflow è «build del
# bridge» se produce l'eseguibile personale o colleziona il package del bridge; il futuro workflow
# DEDICATO del License Manager (PR 3b) non lo è (builda il PROPRIO eseguibile) → resta lecito.
_BUILDS_BRIDGE = re.compile(r"XTrader-Signal-Bridge|--collect-submodules\s+xtrader_bridge",
                            re.IGNORECASE)
# license_manager passato a una direttiva di PACKAGING (collect/include/hidden-import): l'unico modo
# per trascinarlo nell'EXE. Una semplice menzione (commento) non conta.
_LM_PACKAGED = re.compile(
    r"--collect-\w+[=\s]+license_manager\b"
    r"|--include-package[=\s]+license_manager\b"
    r"|--hidden-import[=\s]+license_manager\b",
    re.IGNORECASE)


def test_i_workflow_di_build_non_impacchettano_il_license_manager():
    if not os.path.isdir(_WORKFLOWS_DIR):
        # Checkout ridotto/fork senza i workflow (review GPT #145): niente da controllare.
        return
    offenders = []
    for n in sorted(os.listdir(_WORKFLOWS_DIR)):
        if not n.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(_WORKFLOWS_DIR, n), "r", encoding="utf-8") as f:
            text = f.read()
        if _BUILDS_BRIDGE.search(text) and _LM_PACKAGED.search(text):
            offenders.append(n)
    assert not offenders, (
        "un workflow che builda l'EXE del BRIDGE impacchetta license_manager (lo trascinerebbe "
        f"nell'eseguibile del bridge): {offenders}")


def test_scoping_build_bridge_vs_license_manager():
    # Il gate colpisce un build del BRIDGE che impacchetta il LM, ma NON un build dedicato del
    # License Manager (PR 3b) che impacchetta legittimamente license_manager per il PROPRIO EXE.
    bridge_bad = ("pyinstaller --onefile --name XTrader-Signal-Bridge "
                  "--collect-submodules xtrader_bridge --collect-submodules license_manager main.py")
    assert _BUILDS_BRIDGE.search(bridge_bad) and _LM_PACKAGED.search(bridge_bad)

    # multilinea: la direttiva su riga separata resta nel testo del file → ancora intercettata
    bridge_bad_multiline = (
        "pyinstaller --onefile --name XTrader-Signal-Bridge\n"
        "  --collect-submodules xtrader_bridge\n"
        "  --collect-submodules license_manager\n"
        "  main.py")
    assert _BUILDS_BRIDGE.search(bridge_bad_multiline) and _LM_PACKAGED.search(bridge_bad_multiline)

    # build DEDICATO del License Manager (PR 3b): NON è un build del bridge → lecito
    lm_build = ("pyinstaller --onefile --name XTrader-License-Manager "
                "--collect-submodules license_manager license_manager_main.py")
    assert not _BUILDS_BRIDGE.search(lm_build)

    # build del bridge SENZA license_manager: ok
    bridge_ok = ("pyinstaller --onefile --name XTrader-Signal-Bridge "
                 "--collect-submodules xtrader_bridge main.py")
    assert _BUILDS_BRIDGE.search(bridge_ok) and not _LM_PACKAGED.search(bridge_ok)

    # una MENZIONE non-packaging (commento) in un build del bridge non deve scattare
    bridge_comment = ("pyinstaller --onefile --name XTrader-Signal-Bridge main.py  "
                      "# non collezionare license_manager qui")
    assert _BUILDS_BRIDGE.search(bridge_comment) and not _LM_PACKAGED.search(bridge_comment)


def test_direzione_lecita_lm_importa_il_bridge():
    # Sanity: il License Manager PUÒ importare il bridge (riuso crittografia/atomic_io).
    from license_manager import core
    from xtrader_bridge.licensing import ed25519
    seed_hex, public_hex = core.generate_keypair()
    assert ed25519.public_key(bytes.fromhex(seed_hex)).hex() == public_hex
