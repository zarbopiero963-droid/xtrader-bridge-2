"""Presìdi anti-segreto: fonte unica e buchi misurati — PR-D del piano #194.

Chiude **B3** (il backup col seed Ed25519 passava tutte e tre le difese), **B14** (i file con
PII dei clienti non erano in `.gitignore`), **B30** (un byte NUL faceva saltare l'intero file
allo scanner) e **B31** (nessun pattern riconosceva un seed Ed25519 a 64 hex).

Il difetto **strutturale** che li univa: le tre difese — `.gitignore`,
`.github/workflows/forbidden-files.yml` e `tools/secret_scan.py` — mantenevano **tre liste
separate**, e un file nuovo doveva essere aggiunto a mano a tutte e tre. Non lo era a nessuna.
La prova che la separazione era già costata copertura è nel test
`test_il_workflow_non_riscrive_i_pattern`: le due copie del pattern del token Telegram avevano
**già divergiuto** (`{8,10}` nel workflow contro `{8,12}` nello scanner), cioè il workflow non
intercettava i bot-id lunghi che lo scanner intercettava.

I seed usati qui sono **generati a runtime** (throwaway, mai su disco fuori da `tmp_path`) o
costruiti per concatenazione, così il sorgente di questo file non contiene mai un segreto in
chiaro — altrimenti sarebbe il gate stesso a segnalarlo.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "tools" / "secret_scan.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "forbidden-files.yml"

# Segreto fittizio spezzato: valido per il pattern a runtime, invisibile nel sorgente.
FAKE_GH_TOKEN = "ghp" + "_" + ("B" * 36)

richiede_git = pytest.mark.skipif(shutil.which("git") is None, reason="git non disponibile")


def _scan(*args):
    """Esegue lo scanner REALE (Python corrente, mai `bash`) sugli argomenti dati."""
    return subprocess.run([sys.executable, str(SCANNER), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8")


# ─────────────────────────── B3 + B31 · il seed Ed25519 ────────────────────────────

def _cartella_manager(tmp_path):
    """Una cartella License Manager REALE con una keypair throwaway, via il codice di produzione."""
    from license_manager import core
    seed_hex, public_hex = core.generate_keypair()
    core.save_signing_key(str(tmp_path / core.SIGNING_KEY_FILE), seed_hex, public_hex, now=1)
    return seed_hex


def test_il_file_chiave_col_seed_viene_bloccato(tmp_path):
    """B31: `signing_key.json` contiene il seed in chiaro (`"seed": "<64 hex>"`).

    Prima della patch lo scanner non aveva alcun pattern per un seed Ed25519 e usciva **0**:
    la chiave privata che firma TUTTE le licenze poteva essere committata indisturbata.
    """
    _cartella_manager(tmp_path)
    from license_manager import core
    r = _scan(tmp_path / core.SIGNING_KEY_FILE)
    assert r.returncode == 1, "il file-chiave col seed deve BLOCCARE: " + r.stdout + r.stderr
    assert "::error::" in r.stdout


def test_il_backup_completo_col_seed_viene_bloccato(tmp_path):
    """B3, il bug 🔴: il backup prodotto dal codice di produzione contiene il seed e passava
    **tutte e tre** le difese.

    Non è un JSON costruito a mano: si usano `build_backup`/`save_backup` reali, perché la
    forma che conta è proprio quella che genera il License Manager — dentro il backup il
    contenuto del file-chiave è annidato come stringa JSON, quindi il seed appare **con le
    virgolette escapate** (`\\"seed\\": \\"…\\"`). Un pattern scritto sulla sola forma in
    chiaro mancherebbe esattamente il file di questo bug.
    """
    from license_manager import backup
    _cartella_manager(tmp_path)
    contenuto = backup.build_backup(str(tmp_path), now=1)
    dest = tmp_path / "xtrader_license_backup_2026-07-31.json"
    backup.save_backup(str(dest), contenuto)

    testo = dest.read_text(encoding="utf-8")
    assert '\\"seed\\"' in testo, "forma attesa del backup cambiata: il test non prova più B3"

    r = _scan(dest)
    assert r.returncode == 1, "il backup col seed deve BLOCCARE: " + r.stdout + r.stderr


def test_il_seed_non_produce_falsi_positivi_sugli_hash(tmp_path):
    """La controprova indispensabile: 64 caratteri esadecimali di fila sono anche un **hash
    SHA-256**, e i lockfile del repo ne contengono centinaia (misurati: 291 righe fra
    `requirements-build.lock` e `requirements-build-linux.lock`). Un pattern `[0-9a-f]{64}`
    nudo avrebbe fatto fallire il gate sull'intero repository.

    Il pattern deve quindi essere **contestuale** (la parola `seed` accanto al valore) e questi
    tre casi devono restare puliti.
    """
    innocuo = tmp_path / "requirements-finto.lock"
    innocuo.write_text(
        "pacchetto==1.0 \\\n    --hash=sha256:" + "ab" * 32 + "\n"
        '  "public": "' + "cd" * 32 + '",\n'
        + "ef" * 32 + "\n",
        encoding="utf-8")
    r = _scan(innocuo)
    assert r.returncode == 0, "hash e chiavi PUBBLICHE non sono segreti: " + r.stdout + r.stderr


@richiede_git
def test_il_repository_reale_resta_pulito():
    """Il falso positivo si misura sul repo VERO, non su una fixture: lo scan completo dei file
    tracciati (lockfile con gli hash pip, chiave pubblica embedded, asset binari) deve restare
    a zero segnalazioni. È questo test che impedisce a un pattern troppo largo di entrare."""
    r = subprocess.run([sys.executable, str(SCANNER)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr


# ──────────────────────────────── B30 · il bypass del NUL ────────────────────────────────

def test_un_nul_non_fa_piu_saltare_il_file(tmp_path):
    """B30: bastava **un** byte NUL in testa perché lo scanner non guardasse più nulla del file.

    Prima della patch questo `.py` usciva **0** con un `::notice::` non bloccante: il token
    GitHub sottostante non veniva mai esaminato. Un `::notice::` non ferma un commit.
    """
    sospetto = tmp_path / "innocuo.py"
    sospetto.write_bytes(b"\x00# nota\ntok = \"" + FAKE_GH_TOKEN.encode() + b"\"\n")
    r = _scan(sospetto)
    assert r.returncode == 1, "il NUL non deve più fare da scudo: " + r.stdout + r.stderr
    assert "innocuo.py" in r.stdout
    assert FAKE_GH_TOKEN not in (r.stdout + r.stderr), "il valore del segreto non si stampa MAI"


def test_un_asset_binario_non_e_piu_una_scorciatoia(tmp_path):
    """L'estensione non è una credenziale: rinominare `backup.json` in `logo.png` non deve
    bastare a farlo passare. Prima della patch l'esenzione per gli asset noti era proprio
    questo — una scorciatoia a costo zero per chi volesse aggirare il gate."""
    finto_asset = tmp_path / "logo.png"
    finto_asset.write_bytes(b"\x89PNG\x00\x1a\n" + b'"seed": "' + b"ab" * 32 + b'"\n')
    r = _scan(finto_asset)
    assert r.returncode == 1, "l'estensione non deve esentare: " + r.stdout + r.stderr


def test_un_binario_davvero_innocuo_resta_pulito(tmp_path):
    """La controprova del test precedente: togliere l'esenzione non deve trasformare ogni
    binario in un falso positivo. Un blob di byte senza segreti resta a exit 0 — il notice
    che segnala il binario INATTESO resta (è informativo), ma non blocca."""
    blob = tmp_path / "dati.bin"
    blob.write_bytes(bytes(range(256)) * 40)
    r = _scan(blob)
    assert r.returncode == 0, r.stdout + r.stderr


@richiede_git
def test_il_bypass_del_nul_e_chiuso_anche_in_staging(tmp_path):
    """Regola 2 — la classe, non il sito: il salto sul NUL era scritto **due volte**, in
    `_scan_path` e in `_scan_staged`. Correggerne uno solo avrebbe lasciato l'hook pre-commit
    (che usa `--staged`) scoperto: il segreto sarebbe stato bloccato in CI ma non al commit.
    """
    for args in (["init", "-q"], ["config", "user.email", "t@e.st"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(tmp_path), check=True, capture_output=True)
    f = tmp_path / "nascosto.py"
    f.write_bytes(b"\x00tok = \"" + FAKE_GH_TOKEN.encode() + b"\"\n")
    subprocess.run(["git", "add", "nascosto.py"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    r = subprocess.run([sys.executable, str(SCANNER), "--staged"], capture_output=True,
                       text=True, encoding="utf-8", cwd=str(tmp_path))
    assert r.returncode == 1, "anche lo scan in staging deve bloccare: " + r.stdout + r.stderr


# ─────────────────────── B14 · i file del License Manager e la PII ───────────────────────

def _policy():
    """Il modulo policy, importato come lo importano gli strumenti in `tools/`."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    try:
        import secret_policy
        return secret_policy
    finally:
        sys.path.pop(0)


@richiede_git
@pytest.mark.parametrize("nome", _policy().GITIGNORE_DEVE_COPRIRE)
def test_il_gitignore_rispecchia_la_policy(nome):
    """Il mirror verificato che tiene onesta la terza difesa.

    `.gitignore` è un file di git: non può importare `tools/secret_policy.py`, quindi resterebbe
    per forza una copia — ed è **esattamente così che è nato B14**, con i file del License
    Manager presenti nella testa di chi li ha scritti ma in nessuna delle tre liste. Qui l'elenco
    non è riscritto a mano (sarebbe una quarta copia): è letto dalla policy e verificato con
    `git check-ignore`. Aggiungere una voce alla policy senza toccare `.gitignore` rende questo
    test rosso — che è la promessa scritta nel docstring del modulo policy.
    """
    r = subprocess.run(["git", "check-ignore", "-q", nome], cwd=str(REPO_ROOT))
    assert r.returncode == 0, f"{nome} è nella policy ma .gitignore non lo ignora"


@richiede_git
@pytest.mark.parametrize("nome", _policy().GITIGNORE_NON_DEVE_COPRIRE)
def test_il_gitignore_non_e_diventato_troppo_largo(nome):
    """L'altra metà del mirror. Una regola troppo larga è pericolosa quanto una mancante: se
    `*backup*.json` o `*.jsonl` ingoiassero un file che il repo deve spedire, il gate
    `forbidden-files` inizierebbe a segnalare un file legittimo e verrebbe allargato a mano —
    cioè disattivato pezzo per pezzo."""
    r = subprocess.run(["git", "check-ignore", "-q", nome], cwd=str(REPO_ROOT))
    assert r.returncode == 1, f"{nome} NON deve essere ignorato: .gitignore è troppo largo"


@richiede_git
@pytest.mark.parametrize("nome", [
    "licenses.jsonl", "revoked.jsonl", "auto_backup.json", "publish_state.json",
    "publish_config.json", "restore_in_progress.json",
])
def test_gli_stati_del_license_manager_sono_ignorati(nome):
    """B14: `licenses.jsonl` e `revoked.jsonl` contengono i dati dei CLIENTI (nome, contatto,
    hardware id). Non erano in `.gitignore`, non erano bloccati dal workflow e non contengono
    un pattern di segreto: un `git add -A` dentro la cartella del tool li avrebbe committati
    senza che nulla protestasse."""
    r = subprocess.run(["git", "check-ignore", "-q", nome], cwd=str(REPO_ROOT))
    assert r.returncode == 0, f"{nome} deve essere ignorato da .gitignore"


@richiede_git
def test_il_backup_col_seed_e_ignorato_per_nome():
    """B3, seconda difesa: il file di backup va ignorato **per nome**, non solo intercettato per
    contenuto. Le due difese sono complementari — il contenuto protegge anche da un nome
    inatteso, il nome protegge anche da un formato che dovesse cambiare."""
    for nome in ("xtrader_license_backup_2026-07-31.json", "backup_licenze.json",
                 "auto_backup.json"):
        r = subprocess.run(["git", "check-ignore", "-q", nome], cwd=str(REPO_ROOT))
        assert r.returncode == 0, f"{nome} deve essere ignorato da .gitignore"


@richiede_git
def test_il_dizionario_ufficiale_resta_committabile():
    """Controprova: le nuove regole non devono ingoiare il file dati versionato. Se questo
    diventasse rosso, il `.gitignore` sarebbe diventato troppo largo."""
    r = subprocess.run(["git", "check-ignore", "-q", "data/dizionario_xtrader.csv"],
                       cwd=str(REPO_ROOT))
    assert r.returncode == 1, "data/dizionario_xtrader.csv NON deve essere ignorato"


# ────────────────────────────── la fonte unica (Regola 3) ──────────────────────────────

def test_la_policy_e_la_fonte_unica_dei_pattern():
    """`tools/secret_scan.py` non deve più tenere una propria lista: deve leggerla dalla policy.
    Se qualcuno ricreasse una lista locale, questa uguaglianza di identità cadrebbe."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    try:
        import secret_policy
        import secret_scan
    finally:
        sys.path.pop(0)
    assert secret_scan.PATTERNS is secret_policy.SECRET_PATTERNS


def test_il_workflow_non_riscrive_i_pattern():
    """Regola 3 dimostrata sul file che ha causato il difetto.

    Il workflow teneva una **copia** del pattern del token Telegram, e le due copie erano già
    divergiute: `[0-9]{8,10}` nel workflow contro `[0-9]{8,12}` nello scanner — cioè il gate CI
    non intercettava i bot-id lunghi che l'hook pre-commit intercettava. Dopo la patch il
    workflow non contiene più nessun pattern di segreto: delega alla policy.

    Il controllo guarda ciò che il workflow **esegue**, non ciò che spiega: le righe di commento
    (YAML o bash) sono escluse, altrimenti sarebbe il commento che documenta la divergenza
    storica a far fallire il test — e per non farlo fallire si sarebbe tentati di cancellare
    proprio la spiegazione che serve a non ripetere l'errore.
    """
    eseguibili = "\n".join(r for r in WORKFLOW.read_text(encoding="utf-8").splitlines()
                           if not r.lstrip().startswith("#"))
    for frammento in ("[0-9]{8,", "AKIA", "BEGIN ", "sk-[", "github_pat_"):
        assert frammento not in eseguibili, (
            f"il workflow ha di nuovo una copia locale del pattern ({frammento!r}): "
            "i pattern vivono solo in tools/secret_policy.py")


@richiede_git
def test_il_gate_dei_path_blocca_i_file_vietati(tmp_path):
    """Il controllo dei path del workflow, ora in Python, esercitato davvero: un `config.json`
    tracciato (o una sua variante Windows `Config.JSON`) deve far fallire il gate."""
    checker = REPO_ROOT / "tools" / "forbidden_paths.py"
    for args in (["init", "-q"], ["config", "user.email", "t@e.st"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "Config.JSON").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "Config.JSON"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    r = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(tmp_path))
    assert r.returncode == 1, "un config.json tracciato deve bloccare: " + r.stdout + r.stderr
    assert "Config.JSON" in r.stdout


@richiede_git
def test_il_gate_dei_path_e_pulito_sul_repository_reale():
    """Controprova sul repo vero: il gate riscritto non deve segnalare nulla di ciò che è
    legittimamente tracciato oggi."""
    checker = REPO_ROOT / "tools" / "forbidden_paths.py"
    r = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
