"""Test hard #343 slice 4s (Issue #45): localizzazione dei NOMI MODALITÀ di trading nei log.

I due log di annullo transizione (slice 4r) interpolano `{old_mode}` con un valore di dominio
(SIMULAZIONE/COLLAUDO/REALE). Questa slice rende quel nome nella lingua UI **solo in
presentazione**, tramite l'helper `App._mode_display_name`, senza mai toccare il valore usato dai
gate di sicurezza. Puro e headless (`app.py` importa customtkinter → si legge il sorgente via AST e
si esercita il catalogo i18n reale). Verifica:
- l'helper `_mode_display_name` esiste e mappa i 3 modi via `i18n.tr("<literal>")` (AST);
- le tre chiavi nome-modalità sono costanti `i18n.tr(...)` in app.py (→ anti-drift le trova);
- i due call-site di annullo usano `self._mode_display_name(old_mode)` nel `.format(...)`;
- copertura piena EN/ES **con traduzione != IT**; round-trip reale sul catalogo;
- ESCLUSIONE: la modalità coda «🧮 Modalità coda: {mode}» (OVERWRITE_LAST/FIFO, termine tecnico)
  NON è tradotta come nome-modalità e il suo valore resta passato raw.
"""

import ast
import os

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "app.py"), encoding="utf-8") as _fh:
    _APP_SRC = _fh.read()
_APP_AST = ast.parse(_APP_SRC)

_APP_TR = set()
for _n in ast.walk(_APP_AST):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _APP_TR.add(_n.args[0].value)

# Nomi modalità di trading localizzati in questa slice (valori di bridge_mode.VALID_MODES).
_MODE_NAME_KEYS = ("SIMULAZIONE", "COLLAUDO", "REALE")


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _find_func(name):
    for node in ast.walk(_APP_AST):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_helper_mode_display_name_esiste_e_usa_tr():
    """`_mode_display_name` è definito e traduce i 3 modi via `i18n.tr("<literal>")` (non tr(var),
    così l'anti-drift trova le chiavi come costanti)."""
    fn = _find_func("_mode_display_name")
    assert fn is not None, "helper _mode_display_name mancante in app.py"
    tr_literals = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tr" and node.args
                and isinstance(node.args[0], ast.Constant)):
            tr_literals.add(node.args[0].value)
    for key in _MODE_NAME_KEYS:
        assert key in tr_literals, f"il modo {key!r} non è tradotto via i18n.tr nel'helper"


def test_mode_name_keys_sono_tr_constants_in_app():
    """Le 3 chiavi nome-modalità sono costanti `i18n.tr(...)` in app.py → coperte dall'anti-drift."""
    for key in _MODE_NAME_KEYS:
        assert key in _APP_TR, f"nome modalità non presente come costante i18n.tr: {key!r}"


def test_call_sites_usano_display_name():
    """Entrambi i log di annullo passano il nome tradotto (`_mode_display_name`), non il raw."""
    assert _APP_SRC.count("self._mode_display_name(old_mode)") == 2, (
        "i due call-site di annullo devono usare _mode_display_name(old_mode)")
    # il vecchio passaggio raw non deve sopravvivere
    assert ".format(old_mode=old_mode))" not in _APP_SRC, (
        "un call-site passa ancora old_mode raw invece del nome localizzato")


def test_mode_names_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _MODE_NAME_KEYS:
            assert key in table, f"{lang}: manca la traduzione per il modo {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: nome modalità IDENTICO all'italiano per {key!r}"


def test_round_trip_nomi_modalita():
    """Il flusso reale di traduzione usato dall'helper (`i18n.tr(mode)`) rende i nomi attesi."""
    i18n.set_language("EN")
    assert i18n.tr("SIMULAZIONE") == "SIMULATION"
    assert i18n.tr("COLLAUDO") == "TEST"
    assert i18n.tr("REALE") == "REAL"
    i18n.set_language("ES")
    assert i18n.tr("SIMULAZIONE") == "SIMULACIÓN"
    assert i18n.tr("COLLAUDO") == "PRUEBA"
    assert i18n.tr("REALE") == "REAL"
    # fallback IT: identità (nessuna traduzione → valore di dominio invariato)
    i18n.set_language("IT")
    for key in _MODE_NAME_KEYS:
        assert i18n.tr(key) == key


def test_esclusione_modalita_coda_non_e_nome_modalita():
    """La modalità CODA («🧮 Modalità coda: {mode}») resta col valore raw (OVERWRITE_LAST/FIFO,
    tecnico): NON deve passare da `_mode_display_name` né essere tra le chiavi nome-modalità."""
    assert "🧮 Modalità coda: {mode}\").format(mode=guards.mode)" in _APP_SRC, (
        "il log modalità coda deve continuare a passare guards.mode raw")
    assert "_mode_display_name(guards.mode)" not in _APP_SRC
    for tech in ("OVERWRITE_LAST", "FIFO"):
        assert tech not in _MODE_NAME_KEYS
