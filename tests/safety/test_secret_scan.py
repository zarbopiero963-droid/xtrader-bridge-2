"""Test hard dello scanner segreti condiviso (`tools/secret_scan.sh`) — audit #105 / #153 H3.

Esercita lo script reale via subprocess: deve uscire 1 sui segreti noti (token Telegram,
chiave privata PEM, AWS key id) stampando SOLO il path (mai il valore), e 0 su file puliti.

I segreti fittizi sono costruiti per **concatenazione** così il sorgente di questo test NON
contiene il pattern in chiaro (altrimenti il gate `forbidden-files` lo segnalerebbe).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "tools" / "secret_scan.sh"

# Segreti fittizi spezzati: a runtime sono validi per il pattern, in sorgente no.
FAKE_TELEGRAM = "123456789" + ":" + ("A" * 35)
FAKE_PEM = "-----BEGIN " + "RSA PRIVATE " + "KEY-----"
FAKE_AWS = "AKI" + "A" + ("0" * 16)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or not SCANNER.exists(),
    reason="bash o tools/secret_scan.sh non disponibili",
)


def _run(*paths):
    """Esegue lo scanner sui path dati e cattura stdout/stderr/returncode."""
    return subprocess.run(
        ["bash", str(SCANNER), *map(str, paths)],
        capture_output=True, text=True,
    )


def test_file_pulito_esce_zero(tmp_path):
    """Un file senza segreti → exit 0 e messaggio OK."""
    f = tmp_path / "clean.txt"
    f.write_text("nessun segreto qui\nsolo testo\n")
    r = _run(f)
    assert r.returncode == 0
    assert "OK" in r.stdout


@pytest.mark.parametrize("secret", [FAKE_TELEGRAM, FAKE_PEM, FAKE_AWS])
def test_segreto_noto_esce_uno_e_non_stampa_il_valore(tmp_path, secret):
    """Ogni segreto noto → exit 1 col solo path; il valore non compare mai nell'output."""
    f = tmp_path / "leak.txt"
    f.write_text(f"config = {secret}\n")
    r = _run(f)
    assert r.returncode == 1, f"atteso fallimento per {secret!r}"
    # Il path è segnalato...
    assert "leak.txt" in (r.stdout + r.stderr)
    # ...ma il VALORE del segreto non deve mai comparire nell'output.
    assert secret not in (r.stdout + r.stderr)


def test_misto_pulito_e_segreto_fallisce(tmp_path):
    """Con un file pulito e uno con segreto → exit 1, solo il path del file incriminato."""
    clean = tmp_path / "ok.txt"
    clean.write_text("tutto bene\n")
    leak = tmp_path / "bad.txt"
    leak.write_text(f"token={FAKE_TELEGRAM}\n")
    r = _run(clean, leak)
    assert r.returncode == 1
    assert "bad.txt" in (r.stdout + r.stderr)
    assert FAKE_TELEGRAM not in (r.stdout + r.stderr)


def test_nessun_argomento_su_repo_pulito_esce_zero():
    """Senza argomenti scansiona i file tracciati: il repo non contiene segreti noti → exit 0."""
    # Senza argomenti scansiona i file tracciati: il repo non contiene segreti noti.
    r = subprocess.run(
        ["bash", str(SCANNER)], cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_errore_grep_fa_fail_closed(tmp_path):
    """Un errore di scan (file inesistente → grep rc>=2) NON passa per pulito: fail-closed."""
    r = _run(tmp_path / "non_esiste.txt")
    assert r.returncode == 1, "un errore di grep deve fallire chiuso, non aprire"
    assert "scan non affidabile" in (r.stdout + r.stderr)


HOOK = REPO_ROOT / ".githooks" / "pre-commit"


@pytest.mark.skipif(
    shutil.which("git") is None or not HOOK.exists(),
    reason="git o .githooks/pre-commit non disponibili",
)
def test_pre_commit_hook_scansiona_il_blob_in_staging(tmp_path):
    """L'hook blocca un segreto presente nel BLOB in staging anche se rimosso dal working tree
    (staging parziale / file modificato dopo l'add); con blob pulito invece passa."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    shutil.copy(SCANNER, repo / "tools" / "secret_scan.sh")
    shutil.copy(HOOK, repo / ".githooks" / "pre-commit")

    def git(*args):
        return subprocess.run(["git", *args], cwd=str(repo),
                              capture_output=True, text=True)

    git("init", "-q")

    def run_hook():
        return subprocess.run(["bash", str(repo / ".githooks" / "pre-commit")],
                              cwd=str(repo), capture_output=True, text=True)

    # Caso 1: segreto nel blob in staging, working tree ripulito DOPO l'add → deve bloccare.
    secret_file = repo / "leak.txt"
    secret_file.write_text(f"token={FAKE_TELEGRAM}\n")
    git("add", "leak.txt")
    secret_file.write_text("ora sono pulito\n")     # working tree pulito, index ancora sporco
    r = run_hook()
    assert r.returncode == 1, "il segreto nel blob in staging deve essere intercettato"
    assert FAKE_TELEGRAM not in (r.stdout + r.stderr)   # valore mai stampato

    # Caso 2: blob in staging pulito → l'hook non blocca.
    clean_file = repo / "ok.txt"
    clean_file.write_text("nessun segreto\n")
    git("add", "ok.txt")
    # rimuovo dallo staging il file sporco così resta solo quello pulito
    git("reset", "-q", "leak.txt")
    r2 = run_hook()
    assert r2.returncode == 0, r2.stdout + r2.stderr
