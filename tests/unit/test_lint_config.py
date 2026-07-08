"""Test di regressione della configurazione lint soft-warning (#311-3.5-c).

NON esegue ruff/mypy (non sono in `requirements-dev.txt`: stanno in `requirements-lint.txt`,
installato solo dal job CI `lint`). Verifica invece che la CONFIGURAZIONE resti presente e
coerente: se qualcuno rimuove il job lint, la config o le dipendenze, questi test falliscono.
"""

import os
import re

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_requirements_lint_elenca_ruff_e_mypy():
    txt = _read("requirements-lint.txt")
    assert "ruff" in txt and "mypy" in txt


def test_lint_tools_fuori_dal_lock_di_build():
    # I tool di lint NON devono finire nel lock di build EXE: requirements-build.in non deve
    # includere requirements-lint.txt, e requirements-dev.txt non deve elencare ruff/mypy.
    assert "requirements-lint.txt" not in _read("requirements-build.in")
    dev = _read("requirements-dev.txt")
    assert "ruff" not in dev and "mypy" not in dev


def test_pyproject_ha_config_ruff_e_mypy():
    if tomllib is None:  # pragma: no cover
        # Fallback minimale senza tomllib: verifica testuale delle sezioni.
        s = _read("pyproject.toml")
        assert "[tool.ruff]" in s and "[tool.mypy]" in s
        return
    with open(os.path.join(_ROOT, "pyproject.toml"), "rb") as f:
        data = tomllib.load(f)
    assert "ruff" in data["tool"]
    assert "mypy" in data["tool"]
    # mypy lenient sugli import mancanti (stub di terze parti non installati nel job lint).
    assert data["tool"]["mypy"].get("ignore_missing_imports") is True


def test_job_lint_e_soft_warning_non_bloccante():
    # Il job `lint` deve esistere in pr-checks.yml ed essere SOFT: gli step ruff/mypy hanno
    # continue-on-error (non bloccano il merge). Se qualcuno lo rende bloccante o lo rimuove,
    # questo test se ne accorge.
    wf = _read(".github/workflows/pr-checks.yml")
    assert "\n  lint:" in wf, "job `lint` mancante in pr-checks.yml"
    # Isola il blocco del solo job `lint` (dal suo header fino al prossimo job allo stesso
    # livello di indentazione, o a fine file): così le assert su `continue-on-error` valgono
    # DAVVERO sul job lint e non su un `continue-on-error` di un altro job qualsiasi.
    lint_block = wf.split("\n  lint:", 1)[1]
    lint_block = re.split(r"\n  [A-Za-z0-9_-]+:\n", lint_block, maxsplit=1)[0]
    assert "continue-on-error: true" in lint_block, "il job lint deve essere soft (continue-on-error)"
    assert "requirements-lint.txt" in lint_block
    assert "ruff check" in lint_block and "mypy" in lint_block
