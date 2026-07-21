#!/usr/bin/env python3
"""Secret scan cross-platform (audit #105 / roadmap #153 — voce H3).

Difesa-in-profondità contro il commit accidentale di segreti. **Fonte UNICA dei pattern**,
usata dal gate CI (`forbidden-files`), dall'hook pre-commit (`.githooks/pre-commit`, modo
`--staged`) e dai test (`tests/safety/test_secret_scan.py`), così le regole non divergono.

Sostituisce il vecchio `tools/secret_scan.sh`: quest'ultimo invocava `bash`, che sul runner
**Windows GitHub Actions** veniva risolto come `wsl bash` (senza distro installate) e faceva
fallire i test safety. Essendo Python puro, gira identico su Linux, macOS e Windows.

Comportamento:
- esce **1** se trova un token bot Telegram, una chiave privata PEM, un AWS Access Key Id,
  una API key `sk-…` (OpenAI/Anthropic/OpenRouter) o un GitHub token/PAT (`gh?_…`/`github_pat_…`)
  — le stesse classi che i workflow di review redigono nei diff (AC-M14/AC-B37 audit #114);
- stampa **solo il path** del file sospetto — il valore del segreto non viene MAI stampato;
- esce **0** se il repo/i file sono puliti;
- **fail-closed**: un file non leggibile/assente, o un errore di `git`, NON passa per "pulito"
  ma stampa "scan non affidabile" ed esce 1 (un gate di sicurezza non deve aprire su errore).

I file binari (con byte NUL) vengono saltati, come faceva `grep -I`; se il file NON è un asset
binario atteso (immagine/archivio/font/…) il salto è segnalato con un `::notice::` non-bloccante
(AC-B36 audit #114: un `.py`/`.md`/… con byte NUL è sospetto e non deve sparire in silenzio).
Una riga con il marker `pragma: allowlist secret` è un falso positivo NOTO (fixture di test) e
viene saltata per-riga (non allowlista l'intero file).

Uso:
  python tools/secret_scan.py [file...]   # scansiona i file indicati
  python tools/secret_scan.py             # scansiona tutti i file tracciati (git ls-files)
  python tools/secret_scan.py --staged    # scansiona i BLOB in staging (hook pre-commit)
"""

import os
import re
import subprocess
import sys

# Estensioni di ASSET binari ATTESI: un file con questa estensione + byte NUL è normale (immagini,
# archivi, font, eseguibili) → nessun notice. Un file NON-asset con byte NUL (es. un `.py`/`.md`/
# `.json`/`.csv` che dovrebbe essere testo) è SOSPETTO e va segnalato (AC-B36): potrebbe nascondere
# un segreto dietro un NUL. Solo i binari inattesi ricevono il `::notice::`.
_KNOWN_BINARY_EXT = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svgz", ".pdf",
    ".zip", ".gz", ".tar", ".tgz", ".7z", ".xz", ".bz2",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat", ".class", ".jar", ".whl", ".pyc",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov",
    ".db", ".sqlite", ".sqlite3",
})


def _notice_binary_skip(path: str) -> None:
    """AC-B36 #114: rende VISIBILE (non in silenzio) che un file binario non è stato scansionato,
    MA solo per i binari INATTESI (non asset noti) — così un `.py`/`.md`/… con byte NUL emerge,
    senza rumore sui PNG/ICO/… attesi. `::notice::` non fa fallire il gate."""
    if os.path.splitext(path)[1].lower() in _KNOWN_BINARY_EXT:
        return
    print(f"::notice::file binario INATTESO non scansionato per segreti (byte NUL): {path}",
          file=sys.stderr)

# Pattern ad ALTO segnale, scelti per ~zero falsi positivi (verificati a 0 match sul repo).
# Su BYTES (come `grep -E`): nessun problema di encoding e niente decodifica del segreto.
# chat-id e path utente NON sono qui: come stringhe sono comuni nei doc/test (falsi positivi)
# e sono già coperti dal blocco file di `forbidden-files`.
PATTERNS = [
    # AC-B37 audit #114: allargato il bot-id a `{8,12}` (prima `{8,10}`) per intercettare i
    # bot-id più lunghi dei bot Telegram recenti. La parte auth resta `{35}` (formato REALE del
    # token): NON allargata a `{30,}` come il redactor dei workflow (volutamente lasco per la
    # sola redazione), così il GATE non blocca falsi positivi — le fixture di test usano 32-34
    # char, sotto i 35 reali. NESSUN `\b`, né iniziale né finale (review Fable/GLM #131),
    # INTENZIONALMENTE come il pattern STORICO (`[0-9]{8,10}:…{35}`, che non ne aveva): il match
    # su substring intercetta anche un token EMBEDDED in una stringa più lunga (il `\b` finale su
    # `{35}` lo mancherebbe; quello iniziale mancherebbe un token preceduto da altre cifre). Per
    # un GATE la copertura più ampia è preferibile; la forma resta molto specifica
    # (`<8-12 cifre>:<35 char>`) → nessun falso positivo su sequenze numeriche nude (repo: 0 FP).
    ("Telegram bot token", re.compile(rb"[0-9]{8,12}:[A-Za-z0-9_-]{35}")),
    ("PEM private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # AKIA = chiave permanente; ASIA = credenziale TEMPORANEA STS (entrambe sono AWS access
    # key id valide e vanno intercettate — review CodeRabbit).
    ("AWS access key id", re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    # AC-M14 audit #114: le chiavi che il repo maneggia DAVVERO (Anthropic/OpenAI/OpenRouter,
    # GitHub token/PAT) erano redatte nei diff di review ma NON bloccate al commit dal gate.
    # `sk-…` copre OpenAI (`sk-`/`sk-proj-`), Anthropic (`sk-ant-…`) e OpenRouter (`sk-or-v1-…`).
    # `\b` INIZIALE mantenuto (evita match dentro parole tipo `disk-`/`task-`/`mask-`+20char =
    # falsi positivi); `\b` FINALE RIMOSSO (review Fugu #131): una chiave reale che TERMINA con
    # `-` (la classe include `-`) seguita da `"`/newline NON produrrebbe word-boundary → falso
    # NEGATIVO (chiave non bloccata). Senza `\b` finale il match su prefisso resta valido.
    ("OpenAI/Anthropic/OpenRouter API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}")),
    ("GitHub fine-grained PAT", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{30,}")),
]

_UNRELIABLE = "scan non affidabile"


def _git(args):
    """Esegue `git <args>` catturando l'output in BYTES. Ritorna il CompletedProcess."""
    return subprocess.run(["git", *args], capture_output=True)


# Marker di allowlist per-riga (convenzione detect-secrets): una riga che lo contiene è un
# falso positivo NOTO e VOLUTO (es. una fixture di test che verifica proprio la redazione di un
# finto segreto). Marcatura per-RIGA, esplicita e auditabile: NON allowlista un intero file, così
# un segreto REALE su una riga non marcata dello stesso file resta bloccato.
# ⚠️ DISCIPLINA (review GLM/GPT #131): il marker salta l'INTERA riga — non va MAI messo su una
# riga che contiene anche un segreto reale (lo maschererebbe). Usarlo solo su fixture a segreto
# singolo/finto; in review una riga marcata è un punto di attenzione esplicito. Inoltre il marker
# è onorato SOLO nei file sotto `tests/` (review Fugu #131): un file di PRODUZIONE non può
# auto-bypassarsi aggiungendo il marker a un segreto reale.
_ALLOW_MARKER = b"pragma: allowlist secret"


def _is_test_path(path: str) -> bool:
    """True se `path` ha un componente `tests` (il marker allowlist è onorato solo lì)."""
    return "tests" in path.replace("\\", "/").split("/")


def scan_bytes(data: bytes, *, honor_allowlist: bool = False) -> list:
    """Nomi dei pattern che matchano in `data`. File binario (byte NUL) → saltato (`[]`).
    Scansione per-riga; se `honor_allowlist` le righe con `_ALLOW_MARKER` (falso positivo noto)
    sono saltate — il chiamante lo passa True SOLO per i path di test (`_is_test_path`).
    Default **False = safe-by-default** (review GLM #131): un chiamante che dimentica il flag NON
    onora i marker → fail-closed, il segreto resta bloccato."""
    if b"\x00" in data:
        return []
    hits = []
    for line in data.splitlines():
        if honor_allowlist and _ALLOW_MARKER in line:
            continue
        for name, rx in PATTERNS:
            if name not in hits and rx.search(line):
                hits.append(name)
    return hits


def _scan_path(path: str):
    """Legge e scansiona un file su disco. Ritorna ``(hits, error)``:
    `error=True` se il file è illeggibile/assente (fail-closed dal chiamante)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return [], True
    # AC-B36 audit #114: un file binario (byte NUL) è saltato come `grep -I`, ma NON più in
    # SILENZIO: un `::notice::` rende visibile nel log CI che quel file non è stato scansionato
    # (un segreto nascosto in un binario non passa "invisibile"). Notice = non fa fallire il gate.
    if b"\x00" in data:
        _notice_binary_skip(path)
        return [], False
    return scan_bytes(data, honor_allowlist=_is_test_path(path)), False


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
        if b"\x00" in blob.stdout:   # AC-B36: binario in staging saltato, notice se inatteso
            _notice_binary_skip(path)
            continue
        if scan_bytes(blob.stdout, honor_allowlist=_is_test_path(path)):
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
