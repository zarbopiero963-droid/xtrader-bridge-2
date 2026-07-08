"""Test hard del gate `pytest-timeout` (#311-3.5).

Verifica tre cose reali, non decorative:
1. il plugin `pytest_timeout` è installato (altrimenti l'opzione ini è inerte);
2. il `pytest.ini` del repo configura un timeout per-test > 0 col metodo cross-platform
   `thread` (regressione bloccata se qualcuno rimuove/azzera la config);
3. il meccanismo funziona DAVVERO: un sub-pytest con la STESSA opzione ini (`timeout`,
   senza `--timeout` da riga di comando) uccide un test che si impianta. Questo prova che
   il default via ini — il nostro meccanismo — enforce il timeout, non solo che il flag
   esiste.
"""

import configparser
import importlib.util
import os
import subprocess
import sys
import textwrap

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PYTEST_INI = os.path.join(_REPO_ROOT, "pytest.ini")


def test_plugin_pytest_timeout_installato():
    # Se il plugin non c'è, l'opzione ini `timeout` è ignorata in silenzio: il gate sarebbe
    # inerte. Deve essere una dipendenza dev reale (requirements-dev.txt).
    assert importlib.util.find_spec("pytest_timeout") is not None, (
        "pytest-timeout non installato: aggiungilo a requirements-dev.txt")


def test_pytest_ini_configura_timeout_thread():
    cfg = configparser.ConfigParser()
    cfg.read(_PYTEST_INI)
    assert cfg.has_section("pytest")
    # timeout per-test presente e positivo (un valore assente/0 disattiverebbe il gate).
    timeout = cfg.getint("pytest", "timeout", fallback=0)
    assert timeout > 0, "pytest.ini deve impostare un `timeout` per-test positivo"
    # metodo cross-platform: `thread` funziona su Windows (target), `signal` no.
    assert cfg.get("pytest", "timeout_method", fallback="") == "thread"


def test_timeout_ini_uccide_un_test_impiccato(tmp_path):
    # Meccanismo end-to-end: un sub-pytest con `timeout=1` NELL'INI (nessun --timeout da CLI)
    # deve UCCIDERE un test che dorme 5 s. Prova che il default via ini enforce il timeout —
    # esattamente come il nostro pytest.ini fa in CI. Se il plugin/ini non funzionasse, il
    # sub-pytest passerebbe dopo 5 s (returncode 0) e questo assert fallirebbe.
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntimeout = 1\ntimeout_method = thread\n", encoding="utf-8")
    (tmp_path / "test_hang.py").write_text(textwrap.dedent("""
        import time
        def test_hang():
            time.sleep(5)
    """), encoding="utf-8")
    # Ambiente ERMETICO: pytest-timeout legge `PYTEST_TIMEOUT`, e pytest legge `PYTEST_ADDOPTS`;
    # se fossero impostate nell'ambiente (CI/dev) altererebbero il sub-pytest → falso positivo o
    # negativo. Le rimuoviamo così il test dipende SOLO dall'ini scritto in tmp_path (review Fable 5).
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, env=env)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"il test impiccato NON è stato ucciso:\n{out}"
    assert "Timeout" in out, f"nessun messaggio di Timeout dal plugin:\n{out}"
