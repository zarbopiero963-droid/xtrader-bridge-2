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
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import secret_policy  # noqa: E402  (dopo il sys.path: il modulo vive accanto a questo file)
except ImportError as exc:   # pragma: no cover — mancata installazione, non un ramo logico
    # Fail-closed esplicito, coerente col resto del modulo: senza la policy non esistono pattern,
    # e uno scanner senza pattern direbbe "pulito" su qualsiasi cosa. Meglio un errore leggibile
    # di un traceback: chi legge un log CI deve capire subito che il gate NON ha scansionato.
    # Da qui in avanti lo scanner sono DUE file (`secret_scan.py` + `secret_policy.py`): vanno
    # copiati insieme.
    print(f"::error::tools/secret_policy.py non importabile (scan non affidabile): {exc}",
          file=sys.stderr)
    sys.exit(1)

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


def _notice_binary(path: str) -> None:
    """AC-B36 #114: rende VISIBILE che un file che dovrebbe essere testo contiene byte NUL, MA
    solo per i binari INATTESI (non asset noti) — così un `.py`/`.md`/… binario emerge, senza
    rumore sui PNG/ICO/… attesi. `::notice::` non fa fallire il gate: è un segnale, non un
    verdetto.

    ⚠️ B30 (#192 L3): fino alla #194 questo notice accompagnava un **salto** — il file non veniva
    scansionato affatto. Bastava quindi **un** byte NUL in testa a un `.py` perché un token
    GitHub sottostante non venisse mai esaminato, e un `::notice::` non ferma un commit. Ora il
    file è scansionato lo stesso e il notice resta solo come informazione."""
    if os.path.splitext(path)[1].lower() in _KNOWN_BINARY_EXT:
        return
    print(f"::notice::file binario INATTESO (byte NUL), scansionato comunque: {path}",
          file=sys.stderr)

# I pattern NON vivono più qui: la fonte unica è `tools/secret_policy.py`, condivisa con il gate
# dei percorsi (`tools/forbidden_paths.py`, invocato dal workflow) — vedi PR-D del piano #194.
# Prima erano duplicati fra questo file e il YAML del workflow, e le due copie erano già
# divergiute (`{8,10}` contro `{8,12}` sul bot-id Telegram). Il nome `PATTERNS` resta come alias
# storico: è usato dai test e citato nelle docs.
PATTERNS = secret_policy.SECRET_PATTERNS

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
    """Nomi dei pattern che matchano in `data`. Scansione per-riga; se `honor_allowlist` le righe
    con `_ALLOW_MARKER` (falso positivo noto) sono saltate — il chiamante lo passa True SOLO per i
    path di test (`_is_test_path`). Default **False = safe-by-default** (review GLM #131): un
    chiamante che dimentica il flag NON onora i marker → fail-closed, il segreto resta bloccato.

    **B30 (#192 L3) — i byte NUL non sono più uno scudo.** Fino alla #194 questa funzione usciva
    con `[]` appena trovava un `\\x00`, imitando `grep -I`. Il risultato misurato: un `.py` con un
    NUL in testa e un token GitHub sotto usciva **0**. Non serviva nemmeno malizia — bastava un
    file di testo corrotto. L'esenzione per estensione era anche peggio, perché rinominare
    `backup.json` in `logo.png` era una scorciatoia a costo zero.

    Ora si scansiona **tutto**, senza eccezioni per estensione. Il motivo per cui si poteva
    saltare era il falso positivo sui binari, e non regge alla misura: i pattern sono molto
    specifici e la probabilità che byte casuali producano `-----BEGIN … PRIVATE KEY-----`, 64 hex
    preceduti da `seed`, o `sk-` seguito da 20+ caratteri della classe è dell'ordine di 1e-13 per
    posizione. La controprova non è teorica — `test_il_repository_reale_resta_pulito` scansiona
    tutti i file tracciati, asset binari inclusi, e resta a zero segnalazioni."""
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
    # AC-B36 audit #114: un file che dovrebbe essere testo ma contiene byte NUL viene segnalato
    # con un `::notice::` visibile nel log CI. B30 (#194): il notice NON accompagna più un salto —
    # il file è scansionato comunque (vedi `scan_bytes`), perché un notice non ferma un commit.
    if b"\x00" in data:
        _notice_binary(path)
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
        # Regola 2 (#194): il salto sul NUL era scritto DUE volte, qui e in `_scan_path`.
        # Correggerne uno solo avrebbe lasciato scoperto proprio l'hook pre-commit (che usa
        # `--staged`): il segreto sarebbe stato bloccato in CI ma non al momento del commit.
        if b"\x00" in blob.stdout:   # AC-B36: notice se il binario è inatteso, ma si scansiona
            _notice_binary(path)
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
