"""Gate di sicurezza della build EXE personale (issue #86 PR-P13).

La build Windows deve produrre **solo** l'EXE personale del bridge, senza includere segreti
né certificati e senza un secondo «Admin EXE». La compilazione vera (PyInstaller su Windows)
NON gira in questa CI Linux: qui si verifica in modo deterministico e offline che i
**workflow** rispettino le regole non negoziabili dell'issue.

Posizione di sicurezza: **fail-closed**. Il gate sa analizzare la forma *canonica* della
build — l'eseguibile CLI `pyinstaller … main.py` con opzioni sulla riga di comando (anche con
il call-operator PowerShell `& pyinstaller`) — e su quella applica tutti i controlli.
Qualunque forma che *non* sa analizzare in modo affidabile (uno **spec file**,
`python -m PyInstaller`, l'**API Python** `PyInstaller.__main__.run`) viene **rifiutata**, non
ignorata.

Parsing dei workflow (dependency-free, nessun parser YAML esterno):

- i workflow vengono segmentati in **job** (`_jobs`): l'ordine dei passi conta solo
  *dentro* un job, perché i job girano in parallelo salvo `needs`;
- ogni passo `run:` (inline o block scalar folded `>` / literal `|`) viene spezzato nei
  singoli **comandi di shell** (`_shell_commands`) su `\n`/`;`/`&&`/`||`, scartando commenti
  ed echo, così `cd release` seguito da `pyinstaller …` resta un comando distinto e un
  `echo "python -m pytest"` non viene scambiato per un'esecuzione di test;
- le opzioni sono tokenizzate ignorando il quoting (`"…"`/`'…'`/nudo) e la forma
  `--opt=value`, inclusi gli alias corti (`-n`).

Controlli (su OGNI workflow che invoca PyInstaller, oggi `build.yaml` e
`merge-simulation-hard.yml`, e automaticamente ogni nuovo build):

- forma canonica CLI `pyinstaller … main.py`, niente `.spec`/modulo/API; `main.py` unico
  script (niente `admin.py main.py`);
- una sola build per workflow, `--onefile` come opzione reale (EXE singolo personale);
- nome EXE (`--name`/`-n`, anche `--opt=value`) esattamente quello personale (no «Admin»);
- nel bundle solo `data/dizionario_xtrader.csv` → `data`; nessun `--add-binary` (nessun
  payload binario extra) e `--collect-*` solo nelle coppie (opzione, pacchetto) ammesse;
- nello stesso job, TUTTI i `python -m pytest` girano PRIMA della build;
- artifact/release pubblicano esattamente il path `dist/XTrader-Signal-Bridge.exe`;
- `data/` non contiene file/percorsi sensibili (scansione ricorsiva).
"""

import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUILD_YAML = os.path.join(_REPO_ROOT, ".github", "workflows", "build.yaml")
_WORKFLOWS_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")
_DATA_DIR = os.path.join(_REPO_ROOT, "data")

# Invarianti dell'EXE personale.
_ALLOWED_EXE_NAME = "XTrader-Signal-Bridge"
_ALLOWED_EXE_PATH = "dist/" + _ALLOWED_EXE_NAME + ".exe"
_ALLOWED_BUNDLE_SRC = "data/dizionario_xtrader.csv"
_ALLOWED_BUNDLE_DEST = "data"
_ALLOWED_SCRIPT = "main.py"
# Allowlist delle OPZIONI PyInstaller ammesse nel comando di build: SOLO quelle usate dai
# workflow reali. Tutto il resto è rifiutato fail-closed, così non serve inseguire ogni
# singolo flag pericoloso (`--resource`, `--runtime-hook`, `--additional-hooks-dir`,
# `--uac-admin`, `--collect-datas`, …): qualunque opzione non elencata fa fallire il gate
# (Codex). `--name`/`-n` sono ammessi come opzione, ma il loro VALORE è verificato a parte.
_ALLOWED_OPTS = {
    "--onefile", "--windowed", "--name", "-n", "--paths",
    "--collect-submodules", "--collect-all", "--add-data", "--hidden-import",
}

# Coppie (opzione, pacchetto) di raccolta ammesse: ESATTE, non solo il nome del pacchetto.
# Così `--collect-all xtrader_bridge` (che raccoglierebbe i DATI del package) resta vietato,
# mentre `--collect-submodules xtrader_bridge` (solo codice) è ammesso (CodeRabbit).
_ALLOWED_COLLECT = {
    ("--collect-all", "customtkinter"),
    ("--collect-submodules", "xtrader_bridge"),
}

# Estensioni/nomi/segmenti vietati nel bundle dell'EXE (segreti, credenziali, certificati,
# artefatti locali), inclusi i formati certificato comuni e il segmento `cert`/`certs`.
_FORBIDDEN_BUNDLE = re.compile(
    r"\.(crt|cer|der|pem|key|env|p12|pfx|db|sqlite|sqlite3|log|zip)\b"
    r"|config\.json|secret|token|\bcerts?\b",
    re.IGNORECASE)

# Invocazione PyInstaller in QUALSIASI forma su un SINGOLO comando di shell: CLI (anche con
# call-operator PowerShell `& pyinstaller`, `& "pyinstaller"` o `& "C:\…\pyinstaller.exe"`),
# `python -m PyInstaller`, o API Python. Il prefisso `["']?(?:[^\s"']*[\\/])?` ammette
# l'eventuale virgoletta del call-operator e un path completo (Codex).
_CLI_PREFIX = r"""^\s*&?\s*["']?(?:[^\s"']*[\\/])?pyinstaller(?:\.exe)?\b"""
_PYINSTALLER_DETECT = re.compile(
    _CLI_PREFIX
    + r"""|^\s*&?\s*["']?python(?:\.exe)?["']?\s+-m\s+pyinstaller\b"""
    r"|pyinstaller\.__main__"
    r"|(?:^|\s)import\s+pyinstaller\b"
    r"|from\s+pyinstaller\s+import",
    re.IGNORECASE)
# Forma canonica analizzabile: il comando È l'eseguibile CLI `pyinstaller …` (call-operator e
# virgolette/percorso ammessi).
_PYINSTALLER_CLI = re.compile(_CLI_PREFIX, re.IGNORECASE)
# `python -m pytest …` come comando eseguibile (no echo/commenti), con `&` PowerShell opz.
_PYTEST_CMD = re.compile(r"^\s*&?\s*python\s+-m\s+pytest\b", re.IGNORECASE)
# Indicatori di block scalar YAML per `run:` (folded `>` / literal `|`).
_BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d*$")


def _norm(p: str) -> str:
    """Normalizza un valore-path: rimuove spazi e quoting e usa separatori `/`."""
    return p.strip().strip('"').strip("'").replace("\\", "/")


def _workflow_files():
    """Percorsi di tutti i file workflow (`.yml`/`.yaml`) in `.github/workflows/`."""
    return [os.path.join(_WORKFLOWS_DIR, n) for n in sorted(os.listdir(_WORKFLOWS_DIR))
            if n.endswith((".yml", ".yaml"))]


def _read(path: str) -> str:
    """Contenuto testuale (UTF-8) del file indicato."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _jobs(text: str):
    """`(job_name, job_body)` per ogni job sotto `jobs:` (indentazione standard a 2 spazi,
    come in questo repo). L'ordine dei passi è significativo solo dentro un singolo job,
    perché i job girano in parallelo salvo `needs`."""
    lines = text.splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if re.match(r"^jobs:\s*$", ln)), None)
    if start is None:
        return []
    jobs, cur_name, cur_body = [], None, []
    for ln in lines[start:]:
        if re.match(r"^\S", ln):   # tornati a colonna 0: fine sezione jobs
            break
        m = re.match(r"^  ([\w-]+):\s*(?:#.*)?$", ln)   # header job a 2 spazi (commento opz.)
        if m:
            if cur_name is not None:
                jobs.append((cur_name, "\n".join(cur_body)))
            cur_name, cur_body = m.group(1), []
        elif cur_name is not None:
            cur_body.append(ln)
    if cur_name is not None:
        jobs.append((cur_name, "\n".join(cur_body)))
    return jobs


def _run_steps(text: str):
    """Testo grezzo di ogni passo `run:`, in ordine. I block folded (`>`) sono uniti con
    spazi (continuazione logica: un comando spezzato su più righe resta uno); i block literal
    (`|`) sono uniti con newline (righe = comandi distinti)."""
    lines = text.splitlines()
    steps = []
    i, n = 0, len(lines)
    while i < n:
        m = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        if _BLOCK_SCALAR.match(rest):
            folded = rest[0] == ">"
            block, j = [], i + 1
            while j < n:
                if lines[j].strip() == "":
                    block.append("")
                    j += 1
                    continue
                cur = len(lines[j]) - len(lines[j].lstrip())
                if cur <= indent:
                    break
                block.append(lines[j].strip())
                j += 1
            steps.append((" " if folded else "\n").join(block))
            i = j
        else:
            steps.append(rest.strip().strip('"').strip("'"))
            i += 1
    return steps


def _split_shell(step: str):
    """Spezza un passo nei comandi di shell su `\\n`/`;`/`&&`/`||`, ma SOLO fuori dalle
    virgolette: un `;` dentro `"…;…"` (es. il separatore PyInstaller `SORG;DEST`) non è un
    separatore di comando."""
    cmds, buf, quote, i = [], [], None, 0
    while i < len(step):
        ch = step[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
            i += 1
        elif ch in "\n;":
            cmds.append("".join(buf))
            buf = []
            i += 1
        elif step[i:i + 2] in ("&&", "||"):
            cmds.append("".join(buf))
            buf = []
            i += 2
        elif ch in "&|":   # `&` (background/sequenza PowerShell) e `|` (pipe) singoli
            cmds.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    cmds.append("".join(buf))
    return cmds


def _shell_commands(text: str):
    """Comandi di shell individuali estratti dai passi `run:`, in ordine; commenti (`#…`) e
    righe vuote sono scartati."""
    out = []
    for step in _run_steps(text):
        for part in _split_shell(step):
            c = part.strip()
            if c and not c.startswith("#"):
                out.append(c)
    return out


def _opt_values(cmd: str, *opts):
    """Valori delle opzioni date, robusto a quoting `"…"`/`'…'`/nudo, forma `--opt value` e
    `--opt=value`, e alias corti (`-n`). Il boundary `(?<![\\w-])` evita falsi match (`-n`
    dentro `--name`)."""
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


def _py_scripts(cmd: str):
    """Token-script `*.py` (target positional) presenti nel comando, in ordine."""
    return re.findall(r"(?<!\S)([^\s\"']+\.py)(?!\S)", cmd)


def _name_values(cmd: str):
    """Valori del nome EXE da `--name`/`-n`, robusto anche alla forma corta CONCATENATA
    (`-nAdmin`) oltre a `--name X`/`--name=X`/`-n X`/`-n=X` (Codex)."""
    vals = _opt_values(cmd, "--name")
    for mm in re.finditer(r"""(?<![\w-])-n(?:=|\s*)(?:"([^"]*)"|'([^']*)'|([^\s]+))""", cmd):
        vals.append(next(g for g in mm.groups() if g is not None))
    return vals


def _option_tokens(cmd: str):
    """Nomi-opzione normalizzati nel comando: per `--opt`/`--opt=val` → `--opt`; per la forma
    corta `-xVAL`/`-x` → `-x` (la singola lettera). I valori e gli script (non inizianti con
    `-`) non sono opzioni."""
    opts = []
    for tok in re.findall(r"(?<!\S)--?[A-Za-z][^\s=]*", cmd):
        opts.append(tok.split("=")[0] if tok.startswith("--") else tok[:2])
    return opts


def _build_commands():
    """`(workflow_name, command)` per OGNI comando di shell che invoca PyInstaller (qualsiasi
    forma)."""
    out = []
    for path in _workflow_files():
        for cmd in _shell_commands(_read(path)):
            if _PYINSTALLER_DETECT.search(cmd):
                out.append((os.path.basename(path), cmd))
    return out


def test_build_yaml_esiste():
    """Il workflow di build personale `build.yaml` deve esistere."""
    assert os.path.isfile(_BUILD_YAML), "manca .github/workflows/build.yaml"


def test_build_commands_rilevati():
    """La scoperta automatica copre (almeno) i due build noti."""
    names = {name for name, _ in _build_commands()}
    assert "build.yaml" in names, "build.yaml: invocazione pyinstaller non rilevata"
    assert "merge-simulation-hard.yml" in names, \
        "merge-simulation-hard.yml: pyinstaller non coperto dal gate"


def test_forma_build_canonica():
    """Ogni build dev'essere la forma CLI `pyinstaller … main.py` (fail-closed): no
    spec/modulo/API, e `main.py` come UNICO script (niente `admin.py main.py`)."""
    builds = _build_commands()
    assert builds, "nessuna build trovata"
    for name, cmd in builds:
        assert _PYINSTALLER_CLI.match(cmd), \
            f"{name}: forma di build non analizzabile (spec/modulo/API): {cmd!r}"
        assert ".spec" not in cmd.lower(), f"{name}: build da spec file non ammessa: {cmd!r}"
        scripts = _py_scripts(cmd)
        assert scripts == [_ALLOWED_SCRIPT], \
            f"{name}: lo script di build dev'essere solo {_ALLOWED_SCRIPT}, trovati {scripts}"


def test_build_e_comando_isolato_nel_suo_step():
    """Il comando di build dev'essere l'UNICO comando del suo passo `run:`: nessun
    concatenamento nello stesso step (`pytest && pyinstaller`, `pytest || pyinstaller`,
    `pytest & pyinstaller`, `cd x; pyinstaller`). Così la build non può essere resa
    condizionale al fallimento dei test (`||`) né accodata ad altri comandi (Codex)."""
    found = False
    for path in _workflow_files():
        for step in _run_steps(_read(path)):
            cmds = [c.strip() for c in _split_shell(step)
                    if c.strip() and not c.strip().startswith("#")]
            if any(_PYINSTALLER_DETECT.search(c) for c in cmds):
                found = True
                assert len(cmds) == 1, \
                    f"{os.path.basename(path)}: la build dev'essere isolata nel suo step: {cmds}"
    assert found, "nessun passo di build trovato"


def test_un_solo_build_e_onefile_per_workflow():
    """Per ogni workflow che compila: un solo comando di build con `--onefile` (EXE singolo,
    nessun secondo EXE)."""
    builds = _build_commands()
    assert builds, "nessuna build trovata"
    per_wf = {}
    for name, cmd in builds:
        per_wf.setdefault(name, []).append(cmd)
    for name, cmds in per_wf.items():
        assert len(cmds) == 1, f"{name}: attesa UNA sola build, trovate {len(cmds)}"
        assert _has_flag(cmds[0], "--onefile"), \
            f"{name}: build non --onefile (EXE singolo personale)"


def test_solo_opzioni_note():
    """Allowlist delle opzioni PyInstaller: il comando di build può usare SOLO le opzioni
    note e sicure dei workflow reali. Qualunque altra opzione — `--resource`/`-r`,
    `--runtime-hook`, `--additional-hooks-dir`, `--uac-admin`, `--collect-datas`, … — è
    rifiutata fail-closed (Codex)."""
    for name, cmd in _build_commands():
        for opt in _option_tokens(cmd):
            assert opt in _ALLOWED_OPTS, \
                f"{name}: opzione PyInstaller non in allowlist: {opt!r} ({cmd!r})"


def test_nome_exe_solo_quello_personale():
    """Il nome EXE (`--name`/`-n`, anche `--opt=value` o forma corta concatenata `-nX`)
    dev'essere esattamente quello personale: blocca «Admin» o altri nomi."""
    for name, cmd in _build_commands():
        names = _name_values(cmd)
        assert names, f"{name}: build senza --name (nome EXE ambiguo)"
        for got in names:
            assert _norm(got) == _ALLOWED_EXE_NAME, \
                f"{name}: nome EXE dev'essere {_ALLOWED_EXE_NAME!r}, non {got!r}"


def test_nessun_admin_exe():
    """Rete di sicurezza extra: nessun riferimento testuale a un EXE «Admin» in alcun
    workflow."""
    for path in _workflow_files():
        low = _read(path).casefold()
        assert "admin exe" not in low
        assert "admin.exe" not in low
        assert not re.search(r"pyinstaller[^\n]*admin", low)


def test_adddata_solo_il_dizionario():
    """Ogni `--add-data` deve avere sorgente == dizionario e destinazione == `data` (nessun
    cert/segreto bundlato; qualsiasi quoting/forma `--opt=value`)."""
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


def test_nessun_add_binary():
    """Nessun `--add-binary`: nel bundle è ammesso solo il dizionario (dato), nessun payload
    binario extra (DLL/cert/altro). CodeRabbit/Codex."""
    for name, cmd in _build_commands():
        entries = _opt_values(cmd, "--add-binary")
        assert not entries, \
            f"{name}: --add-binary non ammesso (solo il dizionario nel bundle): {entries}"


def test_collect_solo_coppie_in_allowlist():
    """Ogni `--collect-*` deve combaciare ESATTAMENTE con una coppia (opzione, pacchetto)
    ammessa: così `--collect-all xtrader_bridge`/`--collect-data xtrader_bridge` (dati del
    package oltre il dizionario) sono respinti, pur ammettendo `--collect-submodules
    xtrader_bridge` (solo codice) e `--collect-all customtkinter` (risorse GUI). CodeRabbit."""
    collect_opts = ("--collect-all", "--collect-data", "--collect-binaries",
                    "--collect-submodules")
    for name, cmd in _build_commands():
        for opt in collect_opts:
            for pkg in _opt_values(cmd, opt):
                base = _norm(pkg).split(":", 1)[0].split("=", 1)[0]
                assert (opt, base) in _ALLOWED_COLLECT, \
                    f"{name}: combinazione {opt} {pkg!r} non ammessa"


def test_test_eseguiti_prima_della_build():
    """Nello STESSO job che compila, TUTTI gli step `python -m pytest` (comandi reali, non
    echo/commenti) devono precedere la build. L'ordinamento conta solo dentro un job, perché
    job diversi girano in parallelo salvo `needs` (Codex)."""
    build_names = {name for name, _ in _build_commands()}
    assert build_names, "nessun workflow di build trovato"
    seen_build_job = False
    for path in _workflow_files():
        name = os.path.basename(path)
        if name not in build_names:
            continue
        for jobname, body in _jobs(_read(path)):
            cmds = _shell_commands(body)
            b_idx = [k for k, c in enumerate(cmds) if _PYINSTALLER_DETECT.search(c)]
            if not b_idx:
                continue
            seen_build_job = True
            p_idx = [k for k, c in enumerate(cmds) if _PYTEST_CMD.match(c)]
            assert p_idx, f"{name}/{jobname}: build senza `python -m pytest` nello stesso job"
            assert max(p_idx) < min(b_idx), \
                f"{name}/{jobname}: TUTTI i test devono girare PRIMA della build dell'EXE"
    assert seen_build_job, "nessun job con build individuato"


def test_data_dir_senza_file_sensibili():
    """`data/` (bundle-abile) non deve contenere segreti/cert/DB: scansione ricorsiva sul
    path relativo completo."""
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
    """build.yaml pubblica ESATTAMENTE il path `dist/XTrader-Signal-Bridge.exe` via artifact
    (`path:`) e release (`files:`) — niente wildcard `dist/*.exe` né secondo EXE; nessun
    `dist/*.exe` estraneo in alcun workflow (Codex)."""
    text = _read(_BUILD_YAML)
    artifact_exes = [p for p in re.findall(r"(?m)^\s*path:\s*(\S+)", text)
                     if p.lower().endswith(".exe")]
    release_exes = [p for p in re.findall(r"(?m)^\s*files:\s*(\S+)", text)
                    if p.lower().endswith(".exe")]
    assert artifact_exes == [_ALLOWED_EXE_PATH], \
        f"l'artifact deve pubblicare esattamente {_ALLOWED_EXE_PATH!r}, non {artifact_exes}"
    assert release_exes == [_ALLOWED_EXE_PATH], \
        f"la release deve pubblicare esattamente {_ALLOWED_EXE_PATH!r}, non {release_exes}"
    for path in _workflow_files():
        foreign = [e for e in re.findall(r"dist/(\S+\.exe)", _read(path))
                   if e != _ALLOWED_EXE_NAME + ".exe"]
        assert not foreign, f"{os.path.basename(path)}: EXE inatteso (anche wildcard): {foreign}"
