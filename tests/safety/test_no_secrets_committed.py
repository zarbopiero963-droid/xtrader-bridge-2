"""Safety: nessun segreto/artefatto deve essere tracciato nel repository.

Mirror del workflow `forbidden-files` come test, così la regola gira anche nel
**commit-gate** (e in locale): vietati `.env`, `config.json`, `*.exe`, `*.zip`,
`*.log` e qualsiasi `.csv` tranne il dizionario ufficiale. Niente Telegram/EXE.
"""

import os
import re
import subprocess

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ALLOWED_CSV = {"data/dizionario_xtrader.csv"}
# Token bot Telegram: "<id 8-10 cifre>:<35 caratteri>".
_TELEGRAM_TOKEN = re.compile(r'[0-9]{8,10}:[A-Za-z0-9_-]{35}')


def _tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=_REPO_ROOT,
                             capture_output=True, text=True)
    except (OSError, FileNotFoundError):  # pragma: no cover - ambiente senza git
        pytest.skip("git non disponibile")
    if out.returncode != 0:  # pragma: no cover - non è un repo git
        pytest.skip("non è un repository git")
    return [f for f in out.stdout.splitlines() if f]


def test_nessun_file_vietato_tracciato():
    bad = []
    for f in _tracked_files():
        low = f.lower()
        base = os.path.basename(f).lower()   # case-insensitive: .ENV, Config.json...
        dirs = [seg.lower() for seg in f.split("/")[:-1]]
        if base in (".env", "config.json"):
            bad.append(f)
        elif low.endswith((".exe", ".zip", ".log", ".spec", ".secret", ".bak")):
            bad.append(f)
        elif any(seg in ("build", "dist", "logs", "history") for seg in dirs):
            bad.append(f)   # artefatti PyInstaller, log e dati utente locali
        elif low.endswith(".csv") and f not in _ALLOWED_CSV:
            bad.append(f)
    assert not bad, f"File vietati tracciati nel repo: {bad}"


def test_nessun_token_telegram_in_chiaro():
    # Scansione contenuti: nessun token bot Telegram in chiaro nei file tracciati.
    # Il token NON viene stampato (solo il path), per non riesporlo nei log.
    offenders = []
    for f in _tracked_files():
        try:
            with open(os.path.join(_REPO_ROOT, f), "r", encoding="utf-8", errors="ignore") as fh:
                if _TELEGRAM_TOKEN.search(fh.read()):
                    offenders.append(f)
        except OSError:  # pragma: no cover - file illeggibile
            continue
    assert not offenders, f"Possibile token Telegram in chiaro in: {offenders}"
