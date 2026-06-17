"""Safety: nessun segreto/artefatto deve essere tracciato nel repository.

Mirror del workflow `forbidden-files` come test, così la regola gira anche nel
**commit-gate** (e in locale). Fonte di verità unica: **`.gitignore`**. Un file
tracciato che `.gitignore` direbbe di ignorare (config reali, `.env`, CSV
generati, log, EXE/ZIP, cache, venv, IDE/OS, build/dist, ...) è vietato.
L'eccezione `!data/dizionario_xtrader.csv` è onorata da git. Inoltre nessun token
Telegram in chiaro nei file tracciati. Niente Telegram/EXE/credenziali nei test.
"""

import os
import re
import subprocess

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Token bot Telegram: "<id 8-10 cifre>:<35 caratteri>".
_TELEGRAM_TOKEN = re.compile(r'[0-9]{8,10}:[A-Za-z0-9_-]{35}')


def _git(args):
    try:
        out = subprocess.run(["git", *args], cwd=_REPO_ROOT,
                             capture_output=True, text=True)
    except (OSError, FileNotFoundError):  # pragma: no cover - ambiente senza git
        pytest.skip("git non disponibile")
    if out.returncode != 0:  # pragma: no cover - non è un repo git
        pytest.skip("non è un repository git")
    return [line for line in out.stdout.splitlines() if line]


def test_nessun_file_ignorato_tracciato():
    # File tracciati che .gitignore direbbe di ignorare: vietati (eccezione dizionario).
    ignored = _git(["ls-files", "-i", "-c", "--exclude-standard"])
    assert not ignored, f"File ignorati da .gitignore ma tracciati: {ignored}"


def test_nessun_artefatto_case_variant():
    # Rete case-insensitive (su Linux .gitignore è case-sensitive): blocca le varianti
    # Windows Config.json/.ENV/secret.EXE/signals.CSV. CSV: solo l'esatto dizionario.
    bad = []
    for f in _git(["ls-files"]):
        low = f.lower()
        base = os.path.basename(f).lower()
        if base in (".env", "config.json"):
            bad.append(f)
        elif low.endswith((".exe", ".zip", ".log", ".spec", ".secret", ".bak")):
            bad.append(f)
        elif low.endswith(".csv") and f != "data/dizionario_xtrader.csv":
            bad.append(f)
    assert not bad, f"Artefatti/segreti tracciati (qualsiasi maiuscola): {bad}"


def test_nessun_token_telegram_in_chiaro():
    # Scansione contenuti: nessun token bot Telegram in chiaro nei file tracciati.
    # Il token NON viene stampato (solo il path), per non riesporlo nei log.
    offenders = []
    for f in _git(["ls-files"]):
        try:
            with open(os.path.join(_REPO_ROOT, f), "r", encoding="utf-8", errors="ignore") as fh:
                if _TELEGRAM_TOKEN.search(fh.read()):
                    offenders.append(f)
        except OSError:  # pragma: no cover - file illeggibile
            continue
    assert not offenders, f"Possibile token Telegram in chiaro in: {offenders}"
