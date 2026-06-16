"""Safety: nessun segreto/artefatto deve essere tracciato nel repository.

Mirror del workflow `forbidden-files` come test, così la regola gira anche nel
**commit-gate** (e in locale): vietati `.env`, `config.json`, `*.exe`, `*.zip`,
`*.log` e qualsiasi `.csv` tranne il dizionario ufficiale. Niente Telegram/EXE.
"""

import os
import subprocess

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ALLOWED_CSV = {"data/dizionario_xtrader.csv"}


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
        base = os.path.basename(f)
        if base in (".env", "config.json"):
            bad.append(f)
        elif low.endswith((".exe", ".zip", ".log")):
            bad.append(f)
        elif low.endswith(".csv") and f not in _ALLOWED_CSV:
            bad.append(f)
    assert not bad, f"File vietati tracciati nel repo: {bad}"
