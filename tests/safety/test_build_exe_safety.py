"""Gate di sicurezza della build EXE personale (issue #86 PR-P13).

La build Windows deve produrre **solo** l'EXE personale del bridge, senza includere segreti
né certificati e senza un secondo «Admin EXE». La compilazione vera (PyInstaller su Windows)
NON gira in questa CI Linux: qui si verifica in modo deterministico e offline che i
**workflow** rispettino le regole non negoziabili dell'issue.

Posizione di sicurezza: **fail-closed**. Il gate sa analizzare la forma *canonica* della
build — l'eseguibile CLI `pyinstaller … main.py` con opzioni sulla riga di comando — e su
quella applica tutti i controlli. Qualunque forma che *non* sa analizzare in modo affidabile
(uno **spec file**, `python -m PyInstaller`, l'**API Python** `PyInstaller.__main__.run`, …)
viene **rifiutata**, non ignorata: con uno spec o con l'API le opzioni CLI sono inaffidabili
(lo spec può rinominare l'EXE in «Admin» o includere certificati) e una verifica statica non
darebbe garanzie. Restando fail-closed, il proprietario deve mantenere la forma canonica che
il gate controlla davvero — che è esattamente quella usata da `build.yaml` e
`merge-simulation-hard.yml`.

Controlli (su OGNI workflow che invoca PyInstaller, oggi `build.yaml` e
`merge-simulation-hard.yml`, e automaticamente ogni nuovo build):

- forma canonica CLI `pyinstaller … main.py`, niente `.spec`/modulo/API;
- una sola build per workflow, `--onefile` come opzione reale (EXE singolo personale);
- nome EXE (`--name`/`-n`, anche `--opt=value`) esattamente quello personale (no «Admin»);
- nel bundle solo `data/dizionario_xtrader.csv` → `data`: nessun `--add-data`/`--add-binary`
  con cert/chiavi/`.env`/`config.json`/DB/token (qualsiasi quoting, anche `--opt=value`);
- `--collect-*` solo su pacchetti in allowlist (niente raccolta dati fuori dal dizionario);
- i test (TUTTI gli step `python -m pytest`) girano PRIMA della build;
- artifact/release pubblicano un solo `.exe` da dist/; nessun secondo EXE altrove;
- `data/` non contiene file/percorsi sensibili (scansione ricorsiva).

Resta *dependency-free* (nessun parser YAML esterno) così gira identico anche quando i
workflow di build eseguono i test sotto il lockfile riproducibile.
"""

import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUILD_YAML = os.path.join(_REPO_ROOT, ".github", "workflows", "build.yaml")
_WORKFLOWS_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")
_DATA_DIR = os.path.join(_REPO_ROOT, "data")

# Invarianti dell'EXE personale.
_ALLOWED_EXE_NAME = "XTrader-Signal-Bridge"
_ALLOWED_BUNDLE_SRC = "data/dizionario_xtrader.csv"
_ALLOWED_BUNDLE_DEST = "data"
_ALLOWED_SCRIPT = "main.py"
# Pacchetti per cui è ammessa la raccolta dati/sottomoduli (GUI di terze parti + il package
# del bridge stesso, che non contiene segreti committati). Tutto il resto è rifiutato.
_ALLOWED_COLLECT = {"customtkinter", "xtrader_bridge"}

# Estensioni/nomi/segmenti vietati nel bundle dell'EXE (segreti, credenziali, certificati,
# artefatti locali). Include formati certificato comuni (.cer/.der/.crt/.pem/.p12/.pfx) e un
# segmento di percorso `cert`/`certs` (Codex).
_FORBIDDEN_BUNDLE = re.compile(
    r"\.(crt|cer|der|pem|key|env|p12|pfx|db|sqlite|sqlite3|log|zip)\b"
    r"|config\.json|secret|token|\bcerts?\b",
    re.IGNORECASE)

# Rileva un'invocazione PyInstaller in QUALSIASI forma, così nessuna sfugge al gate: CLI
# (inizio comando o dopo `;`/`&&`/`||`), modulo `-m PyInstaller`, o API Python
# (`PyInstaller.__main__` / `import PyInstaller`). NON combacia con `pip install … pyinstaller`
# (lì è un argomento di pip, preceduto da una parola).
_PYINSTALLER_DETECT = re.compile(
    r"(?:^|;|&&|\|\|)\s*pyinstaller\b"
    r"|-m\s+pyinstaller\b"
    r"|pyinstaller\.__main__"
    r"|import\s+pyinstaller\b",
    re.IGNORECASE)
# Forma canonica analizzabile: il comando È l'eseguibile CLI `pyinstaller …`.
_PYINSTALLER_CLI = re.compile(r"^\s*pyinstaller\b")
# Indicatori di block scalar YAML per `run:` (folded `>` / literal `|`).
_BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d*$")


def _norm(p: str) -> str:
    return p.strip().strip('"').strip("'").replace("\\", "/")


def _workflow_files():
    return [os.path.join(_WORKFLOWS_DIR, n) for n in sorted(os.listdir(_WORKFLOWS_DIR))
            if n.endswith((".yml", ".yaml"))]


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _run_commands(text: str):
    """Estrae, **in ordine**, il testo di ogni passo `run:` (inline o block scalar
    folded/literal). I block vengono uniti con spazi così un comando spezzato su più righe
    torna un'unica stringa."""
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


def _opt_values(cmd: str, *opts):
    """Tutti i valori delle opzioni date nel comando, robusto a: quoting `"…"`/`'…'`/nudo,
    forma `--opt value` E `--opt=value`, e alias corti (`-n`). Il boundary `(?<![\\w-])` evita
    che `-n` combaci dentro `--name`."""
    out = []
    for opt in opts:
        pat = (r"(?<![\w-])" + re.escape(opt)
               + r"""(?:=|\s+)(?:"([^"]*)"|'([^']*)'|([^\s]+))""")
        for mm in re.finditer(pat, cmd):
            out.append(next(g for g in mm.groups() if g is not None))
    return out


def _has_flag(cmd: str, flag: str) -> bool:
    """Vero se `flag` compare come opzione reale (token isolato), non come sottostringa."""
    return re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", cmd) is not None


def _build_commands():
    """``(workflow_name, command)`` per OGNI passo run che invoca PyInstaller (qualsiasi
    forma)."""
    out = []
    for path in _workflow_files():
        for cmd in _run_commands(_read(path)):
            if _PYINSTALLER_DETECT.search(cmd):
                out.append((os.path.basename(path), cmd))
    return out


def test_build_yaml_esiste():
    assert os.path.isfile(_BUILD_YAML), "manca .github/workflows/build.yaml"


def test_build_commands_rilevati():
    names = {name for name, _ in _build_commands()}
    assert "build.yaml" in names, "build.yaml: invocazione pyinstaller non rilevata"
    assert "merge-simulation-hard.yml" in names, \
        "merge-simulation-hard.yml: pyinstaller non coperto dal gate"


def test_forma_build_canonica():
    # Fail-closed: ogni build deve essere la forma CLI analizzabile `pyinstaller … main.py`.
    # Spec file / `python -m PyInstaller` / API Python rendono inaffidabili le opzioni CLI
    # (lo spec può rinominare l'EXE o includere certificati) → vengono RIFIUTATE (Codex).
    builds = _build_commands()
    assert builds, "nessuna build trovata"
    for name, cmd in builds:
        assert _PYINSTALLER_CLI.match(cmd), \
            f"{name}: forma di build non analizzabile (spec/modulo/API): {cmd!r}"
        assert ".spec" not in cmd.lower(), f"{name}: build da spec file non ammessa: {cmd!r}"
        assert re.search(r"(?<!\S)" + re.escape(_ALLOWED_SCRIPT) + r"(?!\S)", cmd), \
            f"{name}: la build deve targettare {_ALLOWED_SCRIPT}, non altro: {cmd!r}"


def test_un_solo_build_e_onefile_per_workflow():
    builds = _build_commands()
    assert builds, "nessuna build trovata"
    per_wf = {}
    for name, cmd in builds:
        per_wf.setdefault(name, []).append(cmd)
    for name, cmds in per_wf.items():
        assert len(cmds) == 1, f"{name}: attesa UNA sola build, trovate {len(cmds)}"
        cmd = cmds[0]
        assert len(re.findall(r"(?<![\w-])pyinstaller\b", cmd)) == 1, \
            f"{name}: attesa UNA sola invocazione pyinstaller nel comando"
        assert _has_flag(cmd, "--onefile"), \
            f"{name}: build non --onefile (EXE singolo personale)"


def test_nome_exe_solo_quello_personale():
    # `--name`/`-n` (anche `--name=…`, anche su riga folded) devono essere esattamente l'EXE
    # personale: blocca un `--name "Admin"` o un alias `-n Admin` (Codex).
    for name, cmd in _build_commands():
        names = _opt_values(cmd, "--name", "-n")
        assert names, f"{name}: build senza --name (nome EXE ambiguo)"
        for got in names:
            assert _norm(got) == _ALLOWED_EXE_NAME, \
                f"{name}: nome EXE dev'essere {_ALLOWED_EXE_NAME!r}, non {got!r}"


def test_nessun_admin_exe():
    # Rete di sicurezza extra: nessun riferimento testuale a un EXE «Admin» in alcun workflow.
    for path in _workflow_files():
        low = _read(path).casefold()
        assert "admin exe" not in low
        assert "admin.exe" not in low
        assert not re.search(r"pyinstaller[^\n]*admin", low)


def test_adddata_solo_il_dizionario():
    # Ogni --add-data (qualsiasi quoting, anche `--add-data=…`) deve avere SORGENTE ==
    # dizionario e DESTINAZIONE == `data` (il loader cerca `_MEIPASS/data/…`).
    builds = _build_commands()
    assert builds, "nessuna build trovata"
    for name, cmd in builds:
        entries = _opt_values(cmd, "--add-data")
        assert entries, f"{name}: atteso almeno un --add-data (il dizionario)"
        for entry in entries:
            parts = entry.split(";")   # separatore Windows; NON `:` (drive letter)
            src = _norm(parts[0])
            dest = _norm(parts[1]) if len(parts) > 1 else ""
            assert not _FORBIDDEN_BUNDLE.search(src), \
                f"{name}: --add-data include un file vietato: {src!r}"
            assert src == _ALLOWED_BUNDLE_SRC, \
                f"{name}: nel bundle è ammesso SOLO {_ALLOWED_BUNDLE_SRC}, non {src!r}"
            assert dest == _ALLOWED_BUNDLE_DEST, \
                f"{name}: il dizionario va in {_ALLOWED_BUNDLE_DEST!r}, non {dest!r}"


def test_nessun_add_binary_di_certificati():
    for name, cmd in _build_commands():
        for entry in _opt_values(cmd, "--add-binary"):
            assert not _FORBIDDEN_BUNDLE.search(entry), \
                f"{name}: --add-binary include un file vietato: {entry!r}"


def test_collect_solo_pacchetti_in_allowlist():
    # `--collect-all`/`--collect-data`/`--collect-binaries`/`--collect-submodules` possono
    # impacchettare dati/binari di un pacchetto: ammessi solo quelli noti-sicuri (GUI di terze
    # parti + il package del bridge), altrimenti si bundlerebbero dati fuori dal dizionario
    # (Codex).
    collect_opts = ("--collect-all", "--collect-data", "--collect-binaries",
                    "--collect-submodules")
    for name, cmd in _build_commands():
        for pkg in _opt_values(cmd, *collect_opts):
            base = _norm(pkg).split(":", 1)[0].split("=", 1)[0]
            assert base in _ALLOWED_COLLECT, \
                f"{name}: --collect su pacchetto non in allowlist: {pkg!r}"


def test_test_eseguiti_prima_della_build():
    # In OGNI workflow che compila, TUTTI gli step `python -m pytest` devono precedere la
    # build (non basta il primo: spostare unit/integration dopo la build lascerebbe l'EXE
    # compilato prima della suite completa). Codex.
    build_names = {name for name, _ in _build_commands()}
    assert build_names, "nessun workflow di build trovato"
    for path in _workflow_files():
        name = os.path.basename(path)
        if name not in build_names:
            continue
        cmds = _run_commands(_read(path))
        pytest_idx = [k for k, c in enumerate(cmds) if "python -m pytest" in c]
        i_build = next((k for k, c in enumerate(cmds) if _PYINSTALLER_DETECT.search(c)), None)
        assert pytest_idx, f"{name}: manca uno step reale `python -m pytest`"
        assert i_build is not None, f"{name}: manca l'invocazione pyinstaller"
        assert max(pytest_idx) < i_build, \
            f"{name}: TUTTI i test devono girare PRIMA della build dell'EXE"


def test_data_dir_senza_file_sensibili():
    # `data/` (bundle-abile) non deve contenere segreti/cert/DB. Scansione RICORSIVA e pattern
    # vietato applicato al PATH RELATIVO completo (anche un segmento di cartella sensibile come
    # `data/secret/x.txt` o `data/certs/y.txt` viene intercettato). Codex.
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
    # build.yaml: l'upload artifact (`path:`) E la release (`files:`) pubblicano ESATTAMENTE
    # un .exe da dist/. Su TUTTI i workflow: nessun `dist/*.exe` estraneo (es. dist/Admin.exe).
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
        foreign = [e for e in re.findall(r"dist/(\S+\.exe)", _read(path))
                   if e != _ALLOWED_EXE_NAME + ".exe"]
        assert not foreign, f"{os.path.basename(path)}: secondo EXE inatteso: {foreign}"
