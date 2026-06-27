"""Gate di sicurezza della build EXE personale (issue #86 PR-P13).

La build Windows deve produrre **solo** l'EXE personale del bridge, senza includere segreti
né certificati e senza un secondo «Admin EXE». La compilazione vera (PyInstaller su Windows)
NON gira in questa CI Linux: qui si verifica in modo deterministico e offline che i
**workflow** rispettino le regole non negoziabili dell'issue:

- una sola compilazione PyInstaller per workflow (nessun Admin/secondo EXE), con nome EXE
  esattamente quello personale;
- nessun `--add-data`/`--add-binary` che includa certificati, chiavi, `.env`, `config.json`,
  DB locale o token: nel bundle è ammesso **solo** `data/dizionario_xtrader.csv`, con
  sorgente esatta e destinazione `data` (il loader runtime cerca `_MEIPASS/data/...`);
- i test girano PRIMA di compilare l'EXE (una build non parte su codice rotto);
- `data/` non contiene file sensibili che `--collect-all`/`--add-data` potrebbero includere.

Per non dipendere da come è scritto il YAML, i comandi di build vengono **estratti** dai
passi `run:` di ogni workflow — sia in forma *folded* (`run: >` / `run: |` su più righe) sia
*inline* (`- run: pyinstaller ...`) — e poi tokenizzati ignorando lo stile di quoting
(`"..."`, `'...'`, nudo). I controlli si applicano a **ogni** workflow che invoca
`pyinstaller`, non solo `build.yaml`, e automaticamente a qualunque nuovo build futuro
(findings Codex). Restiamo *dependency-free*: nessun parser YAML esterno, così il gate gira
identico anche quando i workflow di build eseguono i test sotto il lockfile riproducibile.
"""

import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUILD_YAML = os.path.join(_REPO_ROOT, ".github", "workflows", "build.yaml")
_WORKFLOWS_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")
_DATA_DIR = os.path.join(_REPO_ROOT, "data")

# Nome EXE / sorgente-bundle ammessi: gli UNICI consentiti dall'invariante personale.
_ALLOWED_EXE_NAME = "XTrader-Signal-Bridge"
_ALLOWED_BUNDLE_SRC = "data/dizionario_xtrader.csv"
_ALLOWED_BUNDLE_DEST = "data"

# Estensioni/nomi vietati nel bundle dell'EXE (segreti, credenziali, artefatti locali).
_FORBIDDEN_BUNDLE = re.compile(
    r"\.(crt|pem|key|env|p12|pfx|db|sqlite|sqlite3|log|zip)\b|config\.json|secret|token",
    re.IGNORECASE)

# Indicatori di block scalar YAML per `run:` (folded `>` / literal `|`, con chomping/indent).
_BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d*$")
# `pyinstaller` INVOCATO come programma: a inizio comando o dopo un separatore di shell
# (`;`/`&&`/`||`). NON deve combaciare con `pip install ... pyinstaller httpx`, dove
# pyinstaller è un argomento di pip (preceduto da una parola, non da un separatore).
_PYINSTALLER_CMD = re.compile(r"(?:^|;|&&|\|\|)\s*pyinstaller\b")


def _norm(p: str) -> str:
    return p.strip().strip('"').strip("'").replace("\\", "/")


def _workflow_files():
    return [os.path.join(_WORKFLOWS_DIR, n) for n in sorted(os.listdir(_WORKFLOWS_DIR))
            if n.endswith((".yml", ".yaml"))]


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _run_commands(text: str):
    """Estrae, **in ordine**, il testo di ogni passo `run:` di un workflow, gestendo sia la
    forma inline (`run: cmd`) sia i block scalar folded/literal (`run: >` / `run: |` seguiti
    da righe più indentate). I block vengono uniti con spazi così un comando PyInstaller
    spezzato su più righe (`--name` su una riga successiva) torna un'unica stringa."""
    lines = text.splitlines()
    cmds = []
    i, n = 0, len(lines)
    while i < n:
        m = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        if _BLOCK_SCALAR.match(rest):
            block, j = [], i + 1
            while j < n:
                if lines[j].strip() == "":
                    j += 1
                    continue
                cur = len(lines[j]) - len(lines[j].lstrip())
                if cur <= indent:
                    break
                block.append(lines[j].strip())
                j += 1
            cmds.append(" ".join(block))
            i = j
        else:
            cmds.append(rest.strip().strip('"').strip("'"))
            i += 1
    return cmds


def _opt_values(cmd: str, opt: str):
    """Tutti i valori dell'opzione `opt` (es. ``--add-data``) nel comando, qualunque sia lo
    stile di quoting: ``"..."``, ``'...'`` o nudo."""
    out = []
    for mm in re.finditer(re.escape(opt) + r"""\s+(?:"([^"]*)"|'([^']*)'|(\S+))""", cmd):
        out.append(next(g for g in mm.groups() if g is not None))
    return out


def _build_commands():
    """``(workflow_name, command)`` per OGNI passo run che invoca ``pyinstaller``."""
    out = []
    for path in _workflow_files():
        for cmd in _run_commands(_read(path)):
            if _PYINSTALLER_CMD.search(cmd):
                out.append((os.path.basename(path), cmd))
    return out


def test_build_yaml_esiste():
    assert os.path.isfile(_BUILD_YAML), "manca .github/workflows/build.yaml"


def test_build_commands_rilevati():
    # La scoperta automatica deve trovare (almeno) i due build noti, così un nuovo workflow
    # di build — folded o inline — non sfugge ai controlli sotto.
    names = {name for name, _ in _build_commands()}
    assert "build.yaml" in names, "build.yaml: comando pyinstaller non rilevato"
    assert "merge-simulation-hard.yml" in names, \
        "merge-simulation-hard.yml: pyinstaller non coperto dal gate"


def test_un_solo_build_e_onefile_per_workflow():
    # Per OGNI workflow che compila: un solo comando di build, una sola invocazione
    # PyInstaller in esso, e `--onefile` (EXE singolo personale; niente secondo EXE).
    builds = _build_commands()
    assert builds, "nessun comando di build trovato"
    per_wf = {}
    for name, cmd in builds:
        per_wf.setdefault(name, []).append(cmd)
    for name, cmds in per_wf.items():
        assert len(cmds) == 1, f"{name}: atteso UN solo comando di build, trovati {len(cmds)}"
        cmd = cmds[0]
        assert len(re.findall(r"\bpyinstaller\b", cmd)) == 1, \
            f"{name}: attesa UNA sola invocazione pyinstaller nel comando"
        assert "--onefile" in cmd, f"{name}: build non --onefile"


def test_nome_exe_solo_quello_personale():
    # Il `--name` (anche se su una riga successiva del comando folded) deve essere ESATTAMENTE
    # l'EXE personale: blocca un `--name "Admin"` che costruirebbe un Admin EXE pur senza
    # pubblicare dist/Admin.exe (Codex).
    for name, cmd in _build_commands():
        names = _opt_values(cmd, "--name")
        assert names, f"{name}: build senza --name (nome EXE ambiguo)"
        for got in names:
            assert _norm(got) == _ALLOWED_EXE_NAME, \
                f"{name}: --name dev'essere {_ALLOWED_EXE_NAME!r}, non {got!r}"


def test_nessun_admin_exe():
    # Nessun riferimento a una build/EXE «Admin» in alcun workflow (rete di sicurezza extra).
    for path in _workflow_files():
        low = _read(path).casefold()
        assert "admin exe" not in low
        assert "admin.exe" not in low
        assert not re.search(r"pyinstaller[^\n]*admin", low)


def test_adddata_solo_il_dizionario():
    # In OGNI comando di build, ogni --add-data deve avere SORGENTE == dizionario ufficiale e
    # DESTINAZIONE == `data`. Tokenizzazione quote-agnostica (`"..."`/`'...'`/nudo) così un
    # secondo `--add-data` con quote diverse non sfugge; il check del dest evita che il CSV
    # finisca alla radice del bundle (il loader cerca `_MEIPASS/data/...`). Findings Codex.
    builds = _build_commands()
    assert builds, "nessun comando di build trovato"
    for name, cmd in builds:
        entries = _opt_values(cmd, "--add-data")
        assert entries, f"{name}: atteso almeno un --add-data (il dizionario)"
        for entry in entries:
            # Separatore PyInstaller su Windows = `;` (NON splittare su `:`, troncherebbe un
            # path con drive letter `C:\...`).
            parts = entry.split(";")
            src = _norm(parts[0])
            dest = _norm(parts[1]) if len(parts) > 1 else ""
            assert not _FORBIDDEN_BUNDLE.search(src), \
                f"{name}: --add-data include un file vietato: {src!r}"
            assert src == _ALLOWED_BUNDLE_SRC, \
                f"{name}: nel bundle è ammesso SOLO {_ALLOWED_BUNDLE_SRC}, non {src!r}"
            assert dest == _ALLOWED_BUNDLE_DEST, \
                f"{name}: il dizionario va in {_ALLOWED_BUNDLE_DEST!r}, non {dest!r}"


def test_nessun_add_binary_di_certificati():
    # In OGNI comando di build: nessun --add-binary (qualsiasi quoting) con cert/chiavi.
    for name, cmd in _build_commands():
        for entry in _opt_values(cmd, "--add-binary"):
            assert not _FORBIDDEN_BUNDLE.search(entry), \
                f"{name}: --add-binary include un file vietato: {entry!r}"


def test_test_eseguiti_prima_della_build():
    # In OGNI workflow che compila, uno step `python -m pytest` deve precedere il comando di
    # build (una build non parte su codice non testato). Si confrontano gli step REALI in
    # ordine, non un substring che un commento potrebbe soddisfare.
    build_names = {name for name, _ in _build_commands()}
    assert build_names, "nessun workflow di build trovato"
    for path in _workflow_files():
        name = os.path.basename(path)
        if name not in build_names:
            continue
        cmds = _run_commands(_read(path))
        i_pytest = next((k for k, c in enumerate(cmds) if "python -m pytest" in c), None)
        i_build = next((k for k, c in enumerate(cmds) if _PYINSTALLER_CMD.search(c)), None)
        assert i_pytest is not None, f"{name}: manca lo step reale `python -m pytest`"
        assert i_build is not None, f"{name}: manca il comando pyinstaller"
        assert i_pytest < i_build, f"{name}: i test devono girare PRIMA della build dell'EXE"


def test_data_dir_senza_file_sensibili():
    # `data/` (bundle-abile) non deve contenere segreti/cert/DB. Scansione RICORSIVA e il
    # pattern vietato è applicato al PATH RELATIVO completo (non solo al basename), così anche
    # un segmento di cartella sensibile — es. `data/secret/x.txt` o `data/token/c.txt` — viene
    # intercettato se `data/` venisse bundlata come cartella (Codex).
    assert os.path.isdir(_DATA_DIR)
    found_dizionario = False
    for root, _dirs, files in os.walk(_DATA_DIR):
        for n in files:
            if n == "dizionario_xtrader.csv":
                found_dizionario = True
            rel = os.path.relpath(os.path.join(root, n), _DATA_DIR).replace("\\", "/")
            assert not _FORBIDDEN_BUNDLE.search(rel), f"file/percorso sensibile in data/: {rel!r}"
    assert found_dizionario, "manca data/dizionario_xtrader.csv"


def test_artifact_e_release_solo_un_exe():
    # L'upload artifact (`path:`) E la release (`files:`) di build.yaml pubblicano ESATTAMENTE
    # un singolo .exe da dist/. In più, su TUTTI i workflow di build, nessun `dist/*.exe`
    # estraneo (es. dist/Admin.exe) referenziato da nessuna parte.
    text = _read(_BUILD_YAML)
    artifact_exes = [p for p in re.findall(r"(?m)^\s*path:\s*(\S+)", text)
                     if p.lower().endswith(".exe")]
    release_exes = [p for p in re.findall(r"(?m)^\s*files:\s*(\S+)", text)
                    if p.lower().endswith(".exe")]
    assert len(artifact_exes) == 1, \
        f"atteso ESATTAMENTE un EXE nell'upload artifact, trovati {artifact_exes}"
    assert len(release_exes) == 1, \
        f"atteso ESATTAMENTE un EXE nella release, trovati {release_exes}"
    for p in artifact_exes + release_exes:
        assert p.startswith("dist/"), f"path EXE inatteso: {p!r}"
    for path in _workflow_files():
        wf_text = _read(path)
        foreign = [e for e in re.findall(r"dist/(\S+\.exe)", wf_text)
                   if e != _ALLOWED_EXE_NAME + ".exe"]
        assert not foreign, f"{os.path.basename(path)}: secondo EXE inatteso: {foreign}"
