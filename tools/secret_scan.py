#!/usr/bin/env python3
"""Secret scan cross-platform (audit #105 / roadmap #153 — voce H3).

Difesa-in-profondità contro il commit accidentale di segreti. **Fonte UNICA dei pattern**,
usata dal gate CI (`forbidden-files`), dall'hook pre-commit (`.githooks/pre-commit`, modo
`--staged`) e dai test (`tests/safety/test_secret_scan.py`), così le regole non divergono.

Sostituisce il vecchio `tools/secret_scan.sh`: quest'ultimo invocava `bash`, che sul runner
**Windows GitHub Actions** veniva risolto come `wsl bash` (senza distro installate) e faceva
fallire i test safety. Essendo Python puro, gira identico su Linux, macOS e Windows.

Comportamento (invariato rispetto allo scanner shell):
- esce **1** se trova un token bot Telegram, una chiave privata PEM o un AWS Access Key Id;
- stampa **solo il path** del file sospetto — il valore del segreto non viene MAI stampato;
- esce **0** se il repo/i file sono puliti;
- **fail-closed**: un file non leggibile/assente, o un errore di `git`, NON passa per "pulito"
  ma stampa "scan non affidabile" ed esce 1 (un gate di sicurezza non deve aprire su errore).

I file binari (con byte NUL) vengono saltati, come faceva `grep -I`.

Uso:
  python tools/secret_scan.py [file...]   # scansiona i file indicati
  python tools/secret_scan.py             # scansiona tutti i file tracciati (git ls-files)
  python tools/secret_scan.py --staged    # scansiona i BLOB in staging (hook pre-commit)
"""

import re
import subprocess
import sys

# Pattern ad ALTO segnale, scelti per ~zero falsi positivi (verificati a 0 match sul repo).
# Su BYTES (come `grep -E`): nessun problema di encoding e niente decodifica del segreto.
# chat-id e path utente NON sono qui: come stringhe sono comuni nei doc/test (falsi positivi)
# e sono già coperti dal blocco file di `forbidden-files`.
PATTERNS = [
    ("Telegram bot token", re.compile(rb"[0-9]{8,10}:[A-Za-z0-9_-]{35}")),
    ("PEM private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # AKIA = chiave permanente; ASIA = credenziale TEMPORANEA STS (entrambe sono AWS access
    # key id valide e vanno intercettate — review CodeRabbit).
    ("AWS access key id", re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}")),
]

_UNRELIABLE = "scan non affidabile"


def _git(args):
    """Esegue `git <args>` catturando l'output in BYTES. Ritorna il CompletedProcess."""
    return subprocess.run(["git", *args], capture_output=True)


def scan_bytes(data: bytes) -> list:
    """Nomi dei pattern che matchano in `data`. File binario (byte NUL) → saltato (`[]`)."""
    if b"\x00" in data:
        return []
    return [name for name, rx in PATTERNS if rx.search(data)]


def _scan_path(path: str):
    """Legge e scansiona un file su disco. Ritorna ``(hits, error)``:
    `error=True` se il file è illeggibile/assente (fail-closed dal chiamante)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return [], True
    return scan_bytes(data), False


def _report(path: str) -> None:
    """Segnala un file sospetto: SOLO il path (il valore del segreto non si stampa mai)."""
    print(f"::error::Possibile segreto in (valore redatto): {path}")


def _scan_given_files(files: list) -> int:
    """Scansiona una lista esplicita di path. Ritorna 1 se trova un segreto O se un file è
    illeggibile/assente (fail-closed), 0 se tutti puliti. Lista vuota → 0."""
    found = error = False
    for path in files:
        hits, ferr = _scan_path(path)
        if ferr:
            error = True
            print(f"::error::file non leggibile o assente ({_UNRELIABLE}): {path}",
                  file=sys.stderr)
            continue
        if hits:
            found = True
            _report(path)
    return 1 if (found or error) else 0


def _scan_tracked() -> int:
    """Scansiona tutti i file TRACCIATI (`git ls-files`). Fail-closed se git fallisce."""
    r = _git(["ls-files"])
    if r.returncode != 0:
        print(f"::error::git ls-files fallito ({_UNRELIABLE}).", file=sys.stderr)
        return 1
    files = [p for p in r.stdout.decode("utf-8", "replace").splitlines() if p]
    return _scan_given_files(files)   # lista vuota → 0 (l'OK lo stampa main)


def _scan_staged() -> int:
    """Scansiona il CONTENUTO IN STAGING (i blob dell'index), non il working tree: con lo
    staging parziale (`git add -p`) o un file modificato dopo l'add, un segreto presente nel
    blob in staging ma assente dal disco sfuggirebbe (review CodeRabbit #155)."""
    # ACM**R**: includere anche i RINOMINATI (`git mv` + modifica). Con il rilevamento rename
    # attivo (default di `git diff`), un rename è uno stato `R` che `ACM` escluderebbe → un
    # `git mv` seguito da una piccola modifica con un segreto sfuggirebbe allo scan (review
    # CodeRabbit). `--name-only` su un rename elenca il path NUOVO, su cui `git show :path` legge
    # il blob in staging.
    r = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if r.returncode != 0:
        print(f"::error::git diff --cached fallito ({_UNRELIABLE}).", file=sys.stderr)
        return 1
    paths = [p for p in r.stdout.decode("utf-8", "replace").splitlines() if p]
    if not paths:
        return 0
    found = error = False
    for path in paths:
        blob = _git(["show", f":{path}"])
        if blob.returncode != 0:
            # Un path ACM dovrebbe sempre avere un blob: se l'estrazione fallisce è un'anomalia
            # → fail-closed (non saltare silenziosamente un possibile segreto).
            error = True
            print(f"::error::estrazione blob in staging fallita ({_UNRELIABLE}): {path}",
                  file=sys.stderr)
            continue
        if scan_bytes(blob.stdout):
            found = True
            _report(path)
    return 1 if (found or error) else 0


def main(argv) -> int:
    """Entry point: instrada su `--staged` / file espliciti / file tracciati e ritorna l'exit
    code (1 = segreto o scan non affidabile, 0 = pulito). Stampa l'OK finale solo se pulito."""
    args = argv[1:]
    if "--staged" in args:
        code = _scan_staged()
    else:
        files = [a for a in args if a != "--staged"]
        code = _scan_given_files(files) if files else _scan_tracked()
    if code == 0:
        print("OK: nessun segreto noto rilevato.")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
