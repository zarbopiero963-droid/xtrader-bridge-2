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

Hardening #296 (residui audit #242/PR#177, Codex):
- i VALORI di `--paths`/`--hidden-import` sono allowlistati (non solo il nome-opzione);
- i comandi pytest non possono essere addolciti (`|| …`, `; exit 0`/`true` dopo pytest)
  e `continue-on-error` è vietato in tutti i workflow (fail-closed sui gate di test);
- il comando di build non può contenere argomenti DINAMICI (`$VAR`, `${{ … }}`,
  `$( … )` — bash e PowerShell —, `%VAR%`, `!VAR!` delayed-expansion cmd, splatting
  `@extra`);
- le build WRAPPATE (`cmd /c pyinstaller …`, `powershell -Command "pyinstaller …"`,
  `sh -c 'pyinstaller …'`, anche con wrapper quotato o con path completo) sono
  rilevate dal detector e rifiutate come forma non canonica.

Threat-model del gate (onestà sul perimetro): questo è un controllo ANTI-DRIFT contro
modifiche accidentali/incaute dei workflow, non una difesa da un avversario con accesso
in scrittura — chi può editare i workflow può editare anche QUESTO file di gate. La
copertura dei pattern d'elusione è quindi best-effort fail-closed, non una garanzia
di completezza.
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

# Valori ammessi per le opzioni di ESPANSIONE IMPORT (#296, da audit #242/PR#177, Codex):
# `--paths` e `--hidden-import` erano allowlistate solo come NOME-opzione, coi VALORI liberi —
# un `--paths`/`--hidden-import` arbitrario può trascinare nel bundle codice non previsto.
# Come per `--add-data`/`--collect-*`, i valori sono ESATTI e fail-closed: la radice del
# progetto per `--paths` e i soli moduli runtime reali (telegram/httpx) per `--hidden-import`.
_ALLOWED_PATHS_VALUES = {"."}
_ALLOWED_HIDDEN_IMPORTS = {
    "telegram", "telegram.ext", "telegram.ext._application", "telegram.ext._updater",
    "httpx", "httpcore",
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
# Wrapper di shell che rilanciano PyInstaller (`cmd /c pyinstaller …`, `powershell/pwsh
# -Command "pyinstaller …"`, `sh/bash -c 'pyinstaller …'`): PRIMA sfuggivano DEL TUTTO al
# gate perché il detector era ancorato all'invocazione diretta (#296, audit #242/PR#177,
# Codex). Ora vengono RILEVATI — e quindi RIFIUTATI da `test_forma_build_canonica`, perché
# la forma wrappata non è la CLI canonica analizzabile (fail-closed, nessun wrapper ammesso).
# Gli switch PowerShell possono avere un VALORE senza trattino (`-ExecutionPolicy Bypass
# -Command …`, Codex P2 su #297): il gruppo ammette `-Switch [valore]` ripetuti, così il
# wrapper è rilevato anche con parametri valorizzati prima di `-Command`. Dopo il wrapper
# sono rilevate TUTTE le forme d'invocazione (Codex P2, 2° giro): l'eseguibile CLI, il
# call-operator pwsh `& pyinstaller` e la forma modulo `python -m PyInstaller` — un
# wrapper non deve mai far uscire la build dal gate.
# Il NOME del wrapper può a sua volta essere quotato o con path completo
# (`& "C:/Windows/System32/cmd.exe" /c …`, `"pwsh.exe" -Command …` — Codex P2, 3° giro):
# prefisso call-operator/quote/path opzionali anche davanti al wrapper.
_WRAPPED_PREFIX = (
    r"|(?:^|[\s;&|(])(?:&\s*)?[\"']?(?:[^\s\"']*[\\/])?"
    # `cmd` può avere switch documentati PRIMA di /c (`/d /s /c`, `/v:on /c` — Codex P2,
    # 4° giro): gruppo `/x[:val]` ripetuto prima del /c|/k finale.
    # …e anche DOPO /c, prima del comando (`cmd /c /d pyinstaller` — Codex P2, 5° giro)
    r"(?:cmd(?:\.exe)?[\"']?\s+(?:/\w+(?::\w+)?\s+)*/[ck]\s+(?:/\w+(?::\w+)?\s+)*"
    r"|(?:powershell|pwsh)(?:\.exe)?[\"']?\s+(?:-\w+(?:\s+[\w.:\\/-]+)?\s+)*"
    r"|(?:ba|z|da)?sh[\"']?\s+-c\s+)"
    r"""["']?\s*(?:&\s*)?["']?"""
    r"(?:(?:[^\s\"']*[\\/])?pyinstaller(?:\.exe)?\b"
    # anche il python della forma modulo può essere qualificato/venv
    # (`.venv\Scripts\python.exe -m PyInstaller` — Codex P2, 5° giro) o VERSIONATO
    # (`python3`/`python3.12 -m PyInstaller` — Codex P2 fantasma #298)
    r"|(?:[^\s\"']*[\\/])?python(?:3(?:\.\d+)?)?(?:\.exe)?[\"']?\s+-m\s+pyinstaller\b)")
_PYINSTALLER_DETECT = re.compile(
    _CLI_PREFIX
    # il python DIRETTO può essere qualificato/venv (stessa classe del 5° giro Codex,
    # coperta d'anticipo): `& ".venv\Scripts\python.exe" -m PyInstaller …` — e VERSIONATO
    # (`python3`/`python3.12 -m PyInstaller` — Codex P2 fantasma #298)
    + r"""|^\s*&?\s*["']?(?:[^\s"']*[\\/])?python(?:3(?:\.\d+)?)?(?:\.exe)?["']?\s+-m\s+pyinstaller\b"""
    r"|pyinstaller\.__main__"
    r"|(?:^|\s)import\s+pyinstaller\b"
    r"|from\s+pyinstaller\s+import"
    + _WRAPPED_PREFIX,
    re.IGNORECASE)
# Forma canonica analizzabile: il comando È l'eseguibile CLI `pyinstaller …` (call-operator e
# virgolette/percorso ammessi).
_PYINSTALLER_CLI = re.compile(_CLI_PREFIX, re.IGNORECASE)
# `python -m pytest …` come comando eseguibile (no echo/commenti), con `&` PowerShell opz.
_PYTEST_CMD = re.compile(r"^\s*&?\s*python\s+-m\s+pytest\b", re.IGNORECASE)
# QUALSIASI invocazione pytest (anche via venv pwsh `& ".venv\…\python.exe" -m pytest`):
# serve al gate fail-closed #296, che deve vedere anche le forme che _PYTEST_CMD non copre.
_PYTEST_ANY = re.compile(r"(?<![\w-])pytest\b", re.IGNORECASE)
# Argomento DINAMICO in un comando: variabile shell (`$VAR`/`${VAR}`), expression GitHub
# (`${{ … }}`), command/subexpression substitution `$( … )` (bash E PowerShell, stessa
# grafia — Codex P2 su #297), variabile cmd (`%VAR%`) o SPLATTING PowerShell (`@extra`,
# token che inietta parametri da una variabile — Codex P2, 2° giro). Un argomento
# dinamico sfugge a ogni allowlist statica del gate (#296, audit #242/PR#177, Codex).
# `%VAR%` copre anche le forme AVANZATE di cmd (`%VAR:~0,200%`, `%VAR:a=b%` — Codex P2,
# 5° giro): dopo il nome è ammesso un suffisso `:…` qualsiasi fino al `%` di chiusura.
# Il residuo di command substitution copre anche il BACKQUOTE bash (`` `cat flags.txt` ``)
# e l'array subexpression PowerShell `@( … )` (Codex P2 fantasmi #298).
_DYNAMIC_ARG = re.compile(
    r"\$\{\{[^}]*\}\}|\$\([^)]*\)|\$\{?\w+\}?|%\w+(?::[^%\s]*)?%|!\w+!"
    r"|`[^`]+`|(?:^|(?<=\s))@\([^)]*\)|(?:^|(?<=\s))@[\w.]+")
# Comando che RESETTA l'exit code a successo: `exit 0` in QUALSIASI posizione a/da la
# riga del pytest (anche condizionale, es. `if ($LASTEXITCODE -ne 0) { exit 0 }` — Codex
# P2, 3° giro) o `true` come comando a sé/concatenato: renderebbe verde uno step coi
# test rossi. `exit 1` e i reset PRIMA di pytest restano legittimi. Il lookbehind
# esclude `$LASTEXITCODE`/`EXITCODE` (non sono il comando `exit`).
_EXIT_OK_TOKEN = re.compile(r"(?<![\w$])exit\s+0(?!\d)", re.IGNORECASE)
_EXIT_RESET_LINE = re.compile(r"^true\s*;?\s*$", re.IGNORECASE)
_EXIT_RESET_SAMELINE = re.compile(r";\s*true\s*(?:;|$)", re.IGNORECASE)
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


def _import_expansion_offenders(cmd: str):
    """Coppie ``(opzione, valore)`` di `--paths`/`--hidden-import` con valore FUORI
    allowlist nel comando dato (#296): vuoto = tutti i valori sono quelli ammessi."""
    off = []
    for val in _opt_values(cmd, "--paths"):
        if _norm(val) not in _ALLOWED_PATHS_VALUES:
            off.append(("--paths", val))
    for val in _opt_values(cmd, "--hidden-import"):
        if _norm(val) not in _ALLOWED_HIDDEN_IMPORTS:
            off.append(("--hidden-import", val))
    return off


def _pytest_fail_open_lines(step: str):
    """Righe di uno step `run:` in cui un'invocazione pytest è ADDOLCITA con `||`
    (`pytest || true`, `|| exit 0`, …): il fallimento dei test non farebbe fallire lo
    step (fail-open). Si scandisce il TESTO GREZZO per righe LOGICHE — non i comandi già
    spezzati da `_split_shell`, che separerebbe `pytest` da `|| true` nascondendo il
    pattern (#296, audit #242/PR#177, Codex). Le CONTINUAZIONI di riga (backslash bash o
    backtick pwsh a fine riga) vengono ricongiunte prima del controllo: un pytest con
    continuazione seguito da `|| true` sulla riga fisica successiva è UN solo comando
    per la shell (Codex P2 su #297). Le righe
    COMMENTATE (`#…`, vale per bash e pwsh) sono ignorate: non vengono eseguite,
    flaggarle sarebbe un falso positivo (Sourcery su #297).

    Oltre a `||`, è flaggato anche il RESET dell'exit code a successo (Codex P2, 2°-3°
    giro): un `exit 0` in QUALSIASI posizione dalla riga del pytest in poi — anche
    condizionale, es. `if ($LASTEXITCODE -ne 0) { exit 0 }` — oppure `true` concatenato
    (`; true`) o standalone su riga successiva. In tutti i casi lo step riporterebbe
    successo coi test rossi. `exit 1` e i reset PRIMA di pytest (es. guard di install)
    restano legittimi."""
    logical = re.sub(r"[\\`][ \t]*\n[ \t]*", " ", step)
    out, seen_pytest = [], False
    for ln in logical.splitlines():
        if ln.lstrip().startswith("#"):
            continue
        has_pytest = bool(_PYTEST_ANY.search(ln))
        if has_pytest and ("||" in ln or _EXIT_OK_TOKEN.search(ln)
                           or _EXIT_RESET_SAMELINE.search(ln)):
            out.append(ln.strip())
        elif seen_pytest and (_EXIT_OK_TOKEN.search(ln)
                              or _EXIT_RESET_LINE.match(ln.strip())):
            out.append(ln.strip())
        seen_pytest = seen_pytest or has_pytest
    return out


def _dynamic_args(cmd: str):
    """Argomenti dinamici (`$VAR`, `${{ … }}`, `%VAR%`) presenti nel comando dato (#296)."""
    return _DYNAMIC_ARG.findall(cmd)


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


def test_nessun_argomento_dinamico_nella_build():
    """(#296, audit #242/PR#177, Codex) Il comando PyInstaller non può contenere argomenti
    DINAMICI (`$VAR`, `${{ … }}`, `%VAR%`): sfuggirebbero a ogni allowlist statica del
    gate (es. `pyinstaller $ARGS main.py` con `$ARGS` deciso altrove)."""
    builds = _build_commands()
    assert builds, "nessuna build trovata"
    for name, cmd in builds:
        dyn = _dynamic_args(cmd)
        assert not dyn, f"{name}: argomenti dinamici nella build: {dyn} ({cmd!r})"


def test_argomenti_dinamici_rilevati():
    """Regressione #296: PRIMA `pyinstaller $ARGS main.py` passava silenzioso (né opzione
    `--…` né script `.py`)."""
    assert _dynamic_args("pyinstaller $ARGS main.py") == ["$ARGS"]
    assert _dynamic_args("pyinstaller ${{ inputs.flags }} main.py")
    assert _dynamic_args("pyinstaller %FLAGS% main.py") == ["%FLAGS%"]
    # command/subexpression substitution `$( … )` — bash e PowerShell (Codex P2 #297)
    assert _dynamic_args("pyinstaller $(Get-Content flags.txt) --onefile main.py") == \
        ["$(Get-Content flags.txt)"]
    assert _dynamic_args("pyinstaller $(cat flags.txt) main.py")
    # SPLATTING PowerShell `@extra` (Codex P2, 2° giro): inietta parametri da variabile
    assert _dynamic_args("pyinstaller --onefile @extra main.py") == ["@extra"]
    # delayed expansion cmd `!FLAGS!` (Codex P2, 3° giro)
    assert _dynamic_args("pyinstaller --onefile !FLAGS! main.py") == ["!FLAGS!"]
    # percent expansion AVANZATA di cmd (Codex P2, 5° giro)
    assert _dynamic_args("pyinstaller %FLAGS:~0,200% main.py") == ["%FLAGS:~0,200%"]
    assert _dynamic_args("pyinstaller %PATH:str1=str2% main.py")
    assert _dynamic_args("pyinstaller --onefile --paths . main.py") == []


def test_fantasmi_298_python3_versionato_e_substitution_residue():
    """Regressione #298 (fantasmi post-merge di #297, 2 Codex P2): PRIMA (1) la forma
    modulo VERSIONATA `python3 -m PyInstaller` — diretta o wrappata — sfuggiva DEL TUTTO
    al detector (le alternative modulo accettavano solo `python`/`python.exe`), quindi
    `_build_commands()` la ometteva e i gate canonical-form/allowlist non giravano;
    (2) `_dynamic_args()` non flaggava il backquote bash (`` `cat flags.txt` ``) né
    l'array subexpression PowerShell `@(Get-Content flags.txt)`."""
    versioned = [
        "python3 -m PyInstaller --onefile main.py",
        "python3.12 -m PyInstaller --onefile main.py",
        "cmd /c python3 -m PyInstaller --onefile main.py",
        'pwsh -Command "python3 -m PyInstaller --onefile main.py"',
        '& ".venv/bin/python3" -m PyInstaller --onefile main.py',
    ]
    for cmd in versioned:
        assert _PYINSTALLER_DETECT.search(cmd), f"forma versionata non rilevata: {cmd!r}"
        assert not _PYINSTALLER_CLI.match(cmd), \
            f"forma modulo scambiata per CLI canonica (verrebbe analizzata male): {cmd!r}"
    # controcampi: pytest/pip versionati NON sono build (nessun falso positivo)
    assert not _PYINSTALLER_DETECT.search("python3 -m pytest -q")
    assert not _PYINSTALLER_DETECT.search(
        "python3 -m pip install -r requirements-dev.txt pyinstaller httpx")
    # command substitution residue: backquote bash e array subexpression PowerShell
    assert _dynamic_args("pyinstaller `cat flags.txt` main.py") == ["`cat flags.txt`"]
    assert _dynamic_args("pyinstaller @(Get-Content flags.txt) main.py") == \
        ["@(Get-Content flags.txt)"]
    # controcampo: argomenti statici restano puliti (niente falsi positivi da ` o @)
    assert _dynamic_args("pyinstaller --onefile --name bridge main.py") == []


def test_build_wrappate_rilevate_e_rifiutate():
    """Regressione #296 (audit #242/PR#177, Codex): PRIMA `cmd /c pyinstaller …` sfuggiva
    DEL TUTTO al detector (ancorato all'invocazione diretta). Ora le forme wrappate sono
    RILEVATE — quindi entrano nel gate — e NON sono la forma CLI canonica, per cui
    `test_forma_build_canonica` le rifiuta (fail-closed: nessun wrapper ammesso)."""
    wrapped = [
        "cmd /c pyinstaller --onefile main.py",
        'cmd.exe /C "pyinstaller --onefile main.py"',
        'powershell -Command "pyinstaller --onefile main.py"',
        'pwsh -NoProfile -Command "pyinstaller --onefile main.py"',
        # switch VALORIZZATI prima di -Command (Codex P2 #297)
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "pyinstaller --onefile main.py"',
        'pwsh -ExecutionPolicy RemoteSigned -Command "pyinstaller --onefile main.py"',
        # forma MODULO e call-operator dentro il wrapper (Codex P2, 2° giro)
        "cmd /c python -m PyInstaller --onefile main.py",
        'pwsh -Command "python -m PyInstaller --onefile main.py"',
        'pwsh -Command "& pyinstaller --onefile main.py"',
        'powershell -NoProfile -Command "& pyinstaller --onefile main.py"',
        # wrapper QUOTATO o con path completo (Codex P2, 3° giro)
        '& "C:/Windows/System32/cmd.exe" /c pyinstaller --onefile main.py',
        '"pwsh.exe" -Command "pyinstaller --onefile main.py"',
        # switch di cmd PRIMA di /c (Codex P2, 4° giro)
        "cmd /d /s /c pyinstaller --onefile main.py",
        "cmd /v:on /c pyinstaller --onefile main.py",
        # switch di cmd DOPO /c (Codex P2, 5° giro)
        "cmd /c /d pyinstaller --onefile main.py",
        # python QUALIFICATO/venv, wrappato e diretto (Codex P2, 5° giro)
        'pwsh -Command "& .\\.venv\\Scripts\\python.exe -m PyInstaller --onefile main.py"',
        '& ".venv\\Scripts\\python.exe" -m PyInstaller --onefile main.py',
        "sh -c 'pyinstaller --onefile main.py'",
        "bash -c 'pyinstaller --onefile main.py'",
    ]
    for cmd in wrapped:
        assert _PYINSTALLER_DETECT.search(cmd), f"wrapper non rilevato: {cmd!r}"
        assert not _PYINSTALLER_CLI.match(cmd), \
            f"wrapper scambiato per forma canonica (verrebbe analizzato male): {cmd!r}"
    # controcampo: la forma diretta resta canonica e una menzione innocua non è una build
    assert _PYINSTALLER_CLI.match("pyinstaller --onefile main.py")
    assert not _PYINSTALLER_DETECT.search(
        "python -m pip install -r requirements-dev.txt pyinstaller httpx")


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


def test_valori_paths_e_hidden_import_in_allowlist():
    """(#296, audit #242/PR#177, Codex) Anche i VALORI di `--paths` e `--hidden-import`
    devono stare nell'allowlist esatta (`.` e i soli moduli runtime reali): PRIMA era
    controllato solo il nome-opzione, quindi `--hidden-import ctypes` o `--paths C:\\evil`
    passavano il gate."""
    builds = _build_commands()
    assert builds, "nessuna build trovata"
    for name, cmd in builds:
        off = _import_expansion_offenders(cmd)
        assert not off, \
            f"{name}: valori import-expansion fuori allowlist: {off} ({cmd!r})"


def test_valori_import_expansion_maligni_rifiutati():
    """Regressione #296: i casi che PRIMA passavano ora sono flaggati; i valori reali no."""
    assert _import_expansion_offenders(
        "pyinstaller --onefile --hidden-import ctypes main.py") == \
        [("--hidden-import", "ctypes")]
    assert _import_expansion_offenders(
        r"pyinstaller --onefile --paths C:\evil main.py") == [("--paths", r"C:\evil")]
    # forma `--opt=value` e quoting coperti come per le altre opzioni
    assert _import_expansion_offenders(
        'pyinstaller --hidden-import="ctypes" main.py') == [("--hidden-import", "ctypes")]
    # i valori realmente usati dai workflow restano ammessi
    assert _import_expansion_offenders(
        "pyinstaller --paths . --hidden-import=telegram --hidden-import=httpx main.py") == []


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


def test_pytest_fail_closed_nei_workflow():
    """(#296, audit #242/PR#177, Codex) I gate di test non possono essere fail-open:
    nessuna invocazione pytest addolcita con `||` (es. `pytest || true`) e nessun
    `continue-on-error` in ALCUN workflow. Un pytest che non fa fallire lo step
    maschererebbe regressioni prima della build. I `|| true` sui grep non-pytest
    (forbidden-files) restano legittimi e non sono toccati.

    Il divieto di `continue-on-error` è deliberatamente GLOBALE e non scopato ai soli
    job di test/build (valutato su suggerimento Sourcery, #297): oggi NESSUN workflow
    lo usa (costo zero) e un'euristica "solo job di test" lascerebbe scoperto un futuro
    workflow di test non riconosciuto. Stesso stile fail-closed di `_ALLOWED_OPTS`: un
    eventuale uso legittimo futuro dovrà emendare consapevolmente questo gate."""
    for path in _workflow_files():
        name = os.path.basename(path)
        text = _read(path)
        assert "continue-on-error" not in text, \
            f"{name}: `continue-on-error` vietato (gate fail-open)"
        for step in _run_steps(text):
            bad = _pytest_fail_open_lines(step)
            assert not bad, f"{name}: comando pytest addolcito (fail-open): {bad}"


def test_pytest_addolcito_rilevato():
    """Regressione #296: PRIMA `pytest || true` non faceva fallire il gate (lo split dei
    comandi separava `pytest` da `|| true`); la scansione per riga lo becca."""
    assert _pytest_fail_open_lines("python -m pytest -q || true")
    assert _pytest_fail_open_lines('& ".venv\\Scripts\\python.exe" -m pytest -q || exit 0')
    assert not _pytest_fail_open_lines('python -m pytest -q -m "not manual"')
    # `|| true` su un comando NON-pytest (es. i grep di forbidden-files) resta ammesso
    assert not _pytest_fail_open_lines("ci=$(git ls-files | grep -iE 'x' || true)")
    # righe COMMENTATE non eseguite: niente falso positivo (Sourcery su #297)
    assert not _pytest_fail_open_lines("# python -m pytest -q || true (esempio disattivato)")
    assert not _pytest_fail_open_lines("  # nota: mai usare `pytest || true` nei gate")
    # CONTINUAZIONI di riga: `pytest \` + `|| true` è UN comando per la shell (Codex P2 #297)
    assert _pytest_fail_open_lines("python -m pytest -q \\\n  || true")
    assert _pytest_fail_open_lines("python -m pytest -q `\n  || exit 0")   # backtick pwsh
    assert not _pytest_fail_open_lines("python -m pytest -q \\\n  -m 'not manual'")
    # RESET dell'exit code dopo pytest (Codex P2, 2° giro): stessa riga o riga successiva
    assert _pytest_fail_open_lines("python -m pytest -q; exit 0")
    assert _pytest_fail_open_lines("python -m pytest -q; true")
    assert _pytest_fail_open_lines("python -m pytest -q\nexit 0")
    assert _pytest_fail_open_lines("python -m pytest -q\ntrue")
    # exit 0 CONDIZIONALE dopo pytest (Codex P2, 3° giro): stessa riga o riga successiva
    assert _pytest_fail_open_lines(
        "python -m pytest -q; if ($LASTEXITCODE -ne 0) { exit 0 }")
    assert _pytest_fail_open_lines(
        "python -m pytest -q\nif ($LASTEXITCODE -ne 0) { exit 0 }")
    # `exit 1` (fail-closed) e i reset PRIMA di pytest (guard di install) restano legittimi
    assert not _pytest_fail_open_lines(
        "if ($LASTEXITCODE -ne 0) { exit 1 }\npython -m pytest -q")
    assert not _pytest_fail_open_lines("exit 0\n# step senza pytest")
    assert not _pytest_fail_open_lines("git cat-file -e x\nexit 0")   # step non-pytest


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
