"""`tools/screenshots/shoot.sh` scrive nella config REALE dell'utente: le sue garanzie.

Lo script cambia `app_language` per fare le catture in una lingua, e la config che tocca è
`~/.config/XTraderBridge/config.json` — quella vera dell'app, non una copia. Una scrittura
troncata a metà lì dentro non produce uno screenshot sbagliato: produce un'app che non parte
più, con la configurazione persa.

Lo script non è eseguibile nella suite (serve Xvfb, la GUI, xdotool). Ma il pezzo che scrive
la config è Python dentro un heredoc: qui viene **estratto ed eseguito davvero** su una config
finta, e verificato per sabotaggio. Il resto sono invarianti di forma sul testo dello script,
che è ciò che si può controllare senza un display.

Rilievi CodeRabbit sulla #277: scrittura in-place, temporanei prevedibili, `eval`, PID condiviso.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "tools" / "screenshots" / "shoot.sh"


def _blocco_python() -> str:
    """Il primo heredoc `python3 - ... <<'PY' … PY` dello script: quello che scrive la config."""
    testo = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", testo, re.S)
    assert match, "non trovo più il blocco Python che scrive la config"
    return match.group(1)


def test_la_config_viene_sostituita_in_modo_atomico(tmp_path):
    """Il caso che conta: la config esistente deve restare leggibile in ogni istante.

    Si esegue il blocco reale dello script su una config finta e si verifica che il
    contenuto sia quello atteso, che il file finale sia JSON valido e che non resti
    nessun temporaneo di scarto nella cartella.
    """
    cfg = tmp_path / "config.json"
    originale = {"app_language": "it", "bot_token": "", "csv_path": "C:/x/segnali.csv"}
    cfg.write_text(json.dumps(originale), encoding="utf-8")

    res = subprocess.run([sys.executable, "-c", _blocco_python(), "es", str(cfg)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr

    scritta = json.loads(cfg.read_text(encoding="utf-8"))
    assert scritta["app_language"] == "es", "la lingua non è stata applicata"
    assert scritta["csv_path"] == originale["csv_path"], "il resto della config è stato perso"
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"], \
        "è rimasto un file temporaneo accanto alla config"


def test_una_scrittura_fallita_non_distrugge_la_config_esistente(tmp_path, monkeypatch):
    """Sabotaggio: si fa fallire il `replace` finale. La config precedente deve essere
    ancora lì, intatta e valida — non un file vuoto o mezzo scritto."""
    cfg = tmp_path / "config.json"
    originale = {"app_language": "it", "csv_path": "C:/x/segnali.csv"}
    cfg.write_text(json.dumps(originale), encoding="utf-8")

    sabotaggio = _blocco_python().replace(
        "    os.replace(tmp, p)",
        "    raise OSError('disco pieno')  # sabotaggio del test",
    )
    assert "sabotaggio del test" in sabotaggio, "la sostituzione del sabotaggio non ha attecchito"

    res = subprocess.run([sys.executable, "-c", sabotaggio, "es", str(cfg)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode != 0, "il sabotaggio doveva far fallire lo script"

    assert json.loads(cfg.read_text(encoding="utf-8")) == originale, \
        "la config è stata alterata da una scrittura fallita"
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"], \
        "il temporaneo non è stato rimosso dopo l'errore"


@pytest.mark.parametrize("invariante, motivo", [
    ("trap pulisci EXIT INT TERM",
     "senza trap, un fallimento a metà lascia l'app in esecuzione"),
    ('cp -p "$RUNDIR/config.orig.json" "$CFG"',
     "senza ripristino, la lingua dell'utente resta cambiata per sempre"),
    ('RUNDIR="$(mktemp -d)"',
     "percorsi /tmp prevedibili: pre-creabili come symlink da chiunque sulla macchina"),
    ("umask 077",
     "i file temporanei della cattura non devono essere leggibili da altri utenti"),
    ("APP_PID=$!",
     "il PID deve essere quello di QUESTA invocazione, non di un file condiviso"),
])
def test_le_garanzie_dello_script_restano_nel_testo(invariante, motivo):
    """Invarianti verificabili senza display. Se una sparisce, sparisce anche la protezione."""
    assert invariante in _SCRIPT.read_text(encoding="utf-8"), motivo


def test_nessun_eval_sull_output_di_comandi():
    """`eval $(xdotool …)` rieseguirebbe come codice di shell qualunque cosa arrivi da fuori;
    la geometria si legge e si valida numericamente."""
    testo = _SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*eval\b", testo, re.M), "lo script è tornato a usare eval"


def test_lo_script_non_cancella_il_lock_di_un_altra_istanza():
    """Il lock è la protezione contro due istanze dell'app: cancellarlo alla cieca la
    disarma. Se c'è, lo script si ferma e lo dice."""
    testo = _SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"rm\s+-f\s+.*XTraderBridge\.lock", testo), \
        "lo script cancella di nuovo il lock senza sapere di chi è"
    assert 'if [ -e "$LOCK" ]' in testo, "manca il controllo esplicito sul lock"


def _bash_utilizzabile() -> bool:
    """C'è una shell bash VERA su questa macchina?

    Su Windows `bash` sul PATH è il launcher di WSL (`C:\\Windows\\System32\\bash.exe`), che
    senza una distribuzione installata risponde «non ci sono distribuzioni installate» con
    exit code 1 — e non ha nulla a che vedere con la sintassi dello script. Il runner Windows
    della CI ha fatto esattamente questo. Quindi non basta `which bash`: la shell va provata.
    """
    if shutil.which("bash") is None:
        return False
    try:
        prova = subprocess.run(["bash", "-c", "exit 0"], capture_output=True, text=True,
                               encoding="utf-8", timeout=30)
    except OSError:
        return False
    return prova.returncode == 0


def test_lo_script_e_sintatticamente_valido():
    """`bash -n` non esegue nulla ma rifiuta uno script malformato: dopo una riscrittura è
    l'unico controllo automatico possibile senza un display.

    Si salta dove bash non c'è davvero: `shoot.sh` è uno strumento Linux (Xvfb, xdotool,
    imagemagick) e su Windows non viene mai eseguito. Il controllo resta dov'è utile — la
    CI Linux — invece di fallire su una macchina che quello script non lo usa.
    """
    if not _bash_utilizzabile():
        pytest.skip("nessuna bash reale qui (su Windows è il launcher WSL): shoot.sh è "
                    "uno strumento Linux e la sua sintassi si verifica nella CI Linux")
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
