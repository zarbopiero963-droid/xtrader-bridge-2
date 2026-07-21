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
FAKE_AWS = "AKI" + "A" + ("0" * 16)          # AKIA = chiave permanente
FAKE_AWS_STS = "ASI" + "A" + ("0" * 16)      # ASIA = credenziale temporanea STS

# `tools/secret_scan.py` fa parte del repo: se manca, i test NON devono passare in silenzio
# saltando (sarebbe l'opposto del fail-closed che questi test garantiscono) → fallire (review
# CodeRabbit).
assert SCANNER.exists(), "tools/secret_scan.py non disponibile (lo scanner canonico deve esistere)"


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


@pytest.mark.parametrize("secret", [FAKE_TELEGRAM, FAKE_PEM, FAKE_AWS, FAKE_AWS_STS])
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


@pytest.mark.skipif(shutil.which("git") is None, reason="git non disponibile")
def test_staged_scan_intercetta_un_rename_con_segreto(tmp_path):
    """Un `git mv` + piccola modifica che inietta un segreto produce uno stato `R` (rename
    rilevato): il vecchio filtro `--diff-filter=ACM` lo escludeva → bypass. Con `ACMR` il file
    rinominato viene scansionato (review CodeRabbit). Via Python (sys.executable), niente bash."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shutil.copy(SCANNER, repo / "tools" / "secret_scan.py")

    def git(*args):
        return subprocess.run(["git", *args], cwd=str(repo),
                              capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    # File "grande" committato: dopo il rename + APPEND del segreto la similarità resta alta →
    # git lo rileva come rename (stato R), che è il caso che ACM escludeva.
    big = repo / "big.txt"
    big.write_text("".join(f"line {i}\n" for i in range(20)))
    git("add", "big.txt")
    git("commit", "-qm", "init")
    git("mv", "big.txt", "moved.txt")
    (repo / "moved.txt").write_text(
        "".join(f"line {i}\n" for i in range(20)) + f"tok={FAKE_TELEGRAM}\n")
    git("add", "-A")

    # Sanity: lo stato in staging è davvero un rename (R), non Add+Delete.
    status = git("diff", "--cached", "--name-status").stdout
    assert status.startswith("R"), f"atteso un rename (R), ottenuto: {status!r}"

    r = subprocess.run(
        [sys.executable, str(repo / "tools" / "secret_scan.py"), "--staged"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert r.returncode == 1, "il segreto nel file RINOMINATO in staging deve essere intercettato"
    assert "moved.txt" in (r.stdout + r.stderr)
    assert FAKE_TELEGRAM not in (r.stdout + r.stderr)


def test_hook_pre_commit_delega_allo_scanner_staged():
    """Sanity: l'hook `.githooks/pre-commit` deve delegare allo scanner Python in modo `--staged`
    (è il punto che garantisce il controllo dei blob in staging). Controllo statico del wiring,
    senza eseguire `bash` (cross-platform)."""
    hook = REPO_ROOT / ".githooks" / "pre-commit"
    if not hook.exists():
        pytest.skip(".githooks/pre-commit non presente")
    text = hook.read_text(encoding="utf-8")
    assert "secret_scan.py" in text and "--staged" in text


# ── AC-M14 audit #114: le chiavi che il repo maneggia DAVVERO ora BLOCCANO il commit ────────
# Fittizi spezzati (il sorgente non contiene il pattern contiguo → il gate non segnala questo file).
FAKE_ANTHROPIC = "sk-" + "ant-api03-" + ("A" * 40)     # Anthropic
FAKE_OPENAI = "sk-" + "proj-" + ("B" * 30)             # OpenAI
FAKE_OPENROUTER = "sk-or" + "-v1-" + ("c" * 40)        # OpenRouter
FAKE_GH_PAT = "github_" + "pat_" + ("D" * 30)          # GitHub fine-grained PAT
FAKE_GH_TOKEN = "ghp" + "_" + ("E" * 36)               # GitHub token
FAKE_TELEGRAM_12 = "123456789012" + ":" + ("F" * 35)   # bot-id a 12 cifre (AC-B37)


@pytest.mark.parametrize("secret", [FAKE_ANTHROPIC, FAKE_OPENAI, FAKE_OPENROUTER,
                                    FAKE_GH_PAT, FAKE_GH_TOKEN, FAKE_TELEGRAM_12])
def test_nuove_chiavi_bloccano_e_non_stampano_il_valore(tmp_path, secret):
    """FAIL-FIRST: prima di AC-M14 il gate NON bloccava sk-…/gh?_…/github_pat_… né i bot-id a
    11-12 cifre → questi test uscivano 0. Ora exit 1 col solo path (mai il valore)."""
    f = tmp_path / "leak.txt"
    f.write_text(f"key = {secret}\n")
    r = _run(f)
    assert r.returncode == 1, f"atteso blocco per {secret!r}"
    assert "leak.txt" in (r.stdout + r.stderr)
    assert secret not in (r.stdout + r.stderr)   # il valore non si stampa mai


def test_allowlist_marker_salta_solo_la_riga(tmp_path):
    """Una riga col marker `pragma: allowlist secret` (fixture nota) è saltata, ma il marker NON
    allowlista l'intero file: un segreto su un'altra riga non marcata resta bloccato."""
    only_marked = tmp_path / "fixtures.txt"
    only_marked.write_text(f'API = "{FAKE_ANTHROPIC}"   # pragma: allowlist secret\n')
    assert _run(only_marked).returncode == 0, "riga marcata: falso positivo noto → saltata"

    mixed = tmp_path / "mixed.txt"
    mixed.write_text(
        f'fixture = "{FAKE_ANTHROPIC}"   # pragma: allowlist secret\n'
        f'REAL_LEAK = "{FAKE_GH_TOKEN}"\n')            # riga NON marcata → deve bloccare
    r = _run(mixed)
    assert r.returncode == 1, "il marker non deve allowlistare un segreto su un'altra riga"
    assert FAKE_GH_TOKEN not in (r.stdout + r.stderr)


def test_bot_id_8_cifre_limite_inferiore_blocca(tmp_path):
    """Review GLM #131: il limite INFERIORE del bot-id (`{8,12}`) è 8 cifre → deve bloccare."""
    secret = "12345678" + ":" + ("G" * 35)          # 8 cifre (minimo)
    f = tmp_path / "leak.txt"
    f.write_text(f"tok = {secret}\n")
    r = _run(f)
    assert r.returncode == 1
    assert secret not in (r.stdout + r.stderr)


def test_allowlist_marker_salta_l_intera_riga(tmp_path):
    """Review GLM/GPT #131: il marker salta l'INTERA riga (comportamento voluto e documentato):
    un secondo segreto SULLA STESSA riga marcata NON viene intercettato. È il motivo per cui il
    marker va usato solo su righe a fixture singola — questo test blocca il comportamento così
    una regressione (marker che smette di saltare, o che allowlista troppo) verrebbe notata."""
    same_line = tmp_path / "one_line.txt"
    same_line.write_text(f'a = "{FAKE_ANTHROPIC}"; b = "{FAKE_GH_TOKEN}"  # pragma: allowlist secret\n')
    assert _run(same_line).returncode == 0, "riga marcata: l'intera riga è saltata (per design)"
    # ...ma la riga SUCCESSIVA non marcata resta protetta:
    next_line = tmp_path / "two_lines.txt"
    next_line.write_text(
        f'fixture = "{FAKE_ANTHROPIC}"  # pragma: allowlist secret\n'
        f'leak = "{FAKE_TELEGRAM_12}"\n')
    assert _run(next_line).returncode == 1, "una riga non marcata resta bloccata"


def test_binario_inatteso_emette_notice_ma_non_fallisce(tmp_path):
    """AC-B36: un file NON-asset (es. `.py`) con byte NUL è saltato ma con `::notice::` visibile
    (non sparisce in silenzio); un asset atteso (`.png`) è saltato SENZA rumore."""
    suspicious = tmp_path / "weird.py"
    suspicious.write_bytes(b"\x00" + f"tok = {FAKE_GH_TOKEN}".encode() + b"\x00")
    r = _run(suspicious)
    assert r.returncode == 0                          # binario saltato: non blocca
    assert "::notice::" in r.stderr and "INATTESO" in r.stderr and "weird.py" in r.stderr

    asset = tmp_path / "image.png"
    asset.write_bytes(b"\x00\x89PNG" + FAKE_AWS.encode() + b"\x00")
    r2 = _run(asset)
    assert r2.returncode == 0
    assert "::notice::" not in r2.stderr              # asset atteso: nessun rumore
