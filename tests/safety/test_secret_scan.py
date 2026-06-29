"""Test hard dello scanner segreti condiviso (`tools/secret_scan.py`) — audit #105 / #153 H3.

Esercita lo scanner REALE via subprocess: deve uscire 1 sui segreti noti (token Telegram,
chiave privata PEM, AWS key id) stampando SOLO il path (mai il valore), e 0 su file puliti.

Lo scanner è invocato con `sys.executable` (Python corrente), NON con `bash`: sul runner
**Windows GitHub Actions** `bash` veniva risolto come `wsl bash` (senza distro) e faceva fallire
i test safety. Lo scanner Python gira identico su Linux/macOS/Windows.

I segreti fittizi sono costruiti per **concatenazione** così il sorgente di questo test NON
contiene il pattern in chiaro (altrimenti il gate `forbidden-files` lo segnalerebbe).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "tools" / "secret_scan.py"

# Segreti fittizi spezzati: a runtime sono validi per il pattern, in sorgente no.
FAKE_TELEGRAM = "123456789" + ":" + ("A" * 35)
FAKE_PEM = "-----BEGIN " + "RSA PRIVATE " + "KEY-----"
FAKE_AWS = "AKI" + "A" + ("0" * 16)

# Niente più dipendenza da `bash`: si salta solo se manca lo scanner stesso.
pytestmark = pytest.mark.skipif(
    not SCANNER.exists(), reason="tools/secret_scan.py non disponibile",
)


def _run(*args, cwd=None):
    """Esegue lo scanner Python (sys.executable) sugli argomenti dati."""
    return subprocess.run(
        [sys.executable, str(SCANNER), *map(str, args)],
        capture_output=True, text=True, cwd=cwd,
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


def test_file_binario_viene_saltato(tmp_path):
    """Un file binario (byte NUL) che contiene la sequenza di un pattern viene SALTATO
    (come `grep -I`): niente falso positivo sui binari."""
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01" + FAKE_AWS.encode() + b"\x00")
    r = _run(f)
    assert r.returncode == 0, r.stdout + r.stderr


def test_nessun_argomento_su_repo_pulito_esce_zero():
    """Senza argomenti scansiona i file tracciati: il repo non contiene segreti noti → exit 0."""
    r = _run(cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr


def test_file_inesistente_fa_fail_closed(tmp_path):
    """Un errore di scan (file inesistente/illeggibile) NON passa per pulito: fail-closed."""
    r = _run(tmp_path / "non_esiste.txt")
    assert r.returncode == 1, "un file non leggibile deve fallire chiuso, non aprire"
    assert "scan non affidabile" in (r.stdout + r.stderr)


@pytest.mark.skipif(shutil.which("git") is None, reason="git non disponibile")
def test_staged_scan_intercetta_il_blob_in_staging(tmp_path):
    """Modo `--staged` (usato da `.githooks/pre-commit`): blocca un segreto presente nel BLOB
    in staging anche se rimosso dal working tree (staging parziale / file modificato dopo l'add);
    con blob pulito invece passa. Eseguito via Python (sys.executable), niente `bash`."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shutil.copy(SCANNER, repo / "tools" / "secret_scan.py")

    def git(*args):
        return subprocess.run(["git", *args], cwd=str(repo),
                              capture_output=True, text=True)

    git("init", "-q")

    def run_staged():
        return subprocess.run(
            [sys.executable, str(repo / "tools" / "secret_scan.py"), "--staged"],
            cwd=str(repo), capture_output=True, text=True,
        )

    # Caso 1: segreto nel blob in staging, working tree ripulito DOPO l'add → deve bloccare.
    secret_file = repo / "leak.txt"
    secret_file.write_text(f"token={FAKE_TELEGRAM}\n")
    git("add", "leak.txt")
    secret_file.write_text("ora sono pulito\n")     # working tree pulito, index ancora sporco
    r = run_staged()
    assert r.returncode == 1, "il segreto nel blob in staging deve essere intercettato"
    assert "leak.txt" in (r.stdout + r.stderr)
    assert FAKE_TELEGRAM not in (r.stdout + r.stderr)   # valore mai stampato

    # Caso 2: blob in staging pulito → non blocca.
    clean_file = repo / "ok.txt"
    clean_file.write_text("nessun segreto\n")
    git("add", "ok.txt")
    git("reset", "-q", "leak.txt")   # tolgo dallo staging il file sporco
    r2 = run_staged()
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_hook_pre_commit_delega_allo_scanner_staged():
    """Sanity: l'hook `.githooks/pre-commit` deve delegare allo scanner Python in modo `--staged`
    (è il punto che garantisce il controllo dei blob in staging). Controllo statico del wiring,
    senza eseguire `bash` (cross-platform)."""
    hook = REPO_ROOT / ".githooks" / "pre-commit"
    if not hook.exists():
        pytest.skip(".githooks/pre-commit non presente")
    text = hook.read_text(encoding="utf-8")
    assert "secret_scan.py" in text and "--staged" in text
