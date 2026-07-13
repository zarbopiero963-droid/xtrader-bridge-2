"""Test hard #343 slice 4r: localizzazione dei log MODE-TRANSITION ANNULLATA.

Copre i log emessi in `_gate_dangerous_transitions` quando l'utente ANNULLA la conferma di una
transizione di modalità pericolosa (attivazione REALE, attivazione COLLAUDO, coda multi-segnale).
Puro e headless (`app.py` importa customtkinter → si legge il sorgente via AST e si esercita il
catalogo i18n reale). Verifica:
- wrapping in `i18n.tr(...)` nel sorgente (via AST, incluse le chiavi multilinea concatenate);
- che i log DINAMICI «… torno a {old_mode}.» chiamino davvero `.format(old_mode=…)` — mutation-guard;
- copertura piena EN/ES **con traduzione != IT**; conservazione segnaposto; round-trip; marker;
- ESCLUSIONE: il log di AUDIT «⚠️ » + `real_mode.enabled_message()` (bolla di dominio da layer puro)
  resta NON wrappato in `i18n.tr` (solo il messaggio di dominio, concatenato fuori).
"""

import ast
import os
import re
import string

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


def _log_tr_format_calls():
    """(template, {kwargs}) per ogni `self._log(i18n.tr("…").format(**kwargs))` in app.py (AST)."""
    out = []
    for node in ast.walk(_APP_AST):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_log" and node.args):
            continue
        msg = node.args[0]
        if not (isinstance(msg, ast.Call) and isinstance(msg.func, ast.Attribute)
                and msg.func.attr == "format"):
            continue
        tr = msg.func.value
        if not (isinstance(tr, ast.Call) and isinstance(tr.func, ast.Attribute)
                and tr.func.attr == "tr" and tr.args
                and isinstance(tr.args[0], ast.Constant) and isinstance(tr.args[0].value, str)):
            continue
        out.append((tr.args[0].value, {kw.arg for kw in msg.keywords if kw.arg}))
    return out


# Gruppo MODE-TRANSITION ANNULLATA localizzato in questa slice.
_MODE_KEYS = (
    "↩️ Attivazione modalità REALE ANNULLATA: torno a {old_mode}.",
    "↩️ Attivazione modalità COLLAUDO ANNULLATA: torno a {old_mode}.",
    "↩️ Modalità coda multi-segnale ANNULLATA: resto a un solo segnale attivo (OVERWRITE_LAST).",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_mode_logs_wrappati_in_app():
    """Ogni chiave del gruppo è una costante di `i18n.tr(...)` in app.py (anche le multilinea)."""
    for key in _MODE_KEYS:
        assert key in _APP_TR, f"chiave mode-transition non wrappata in i18n.tr: {key!r}"
    # le vecchie f-string/stringhe non wrappate non devono sopravvivere
    for old in ('self._log("↩️ Attivazione modalità REALE ANNULLATA: torno a "',
                'self._log("↩️ Attivazione modalità COLLAUDO ANNULLATA: torno a "',
                'self._log("↩️ Modalità coda multi-segnale ANNULLATA: resto a un solo segnale "'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_mode_logs_chiamano_format():
    """Mutation-guard AST: i due log «… torno a {old_mode}.» devono essere formattati con kwargs che
    coprono TUTTI i segnaposto (togliere `.format`/il kwarg `old_mode` → fallisce)."""
    calls = _log_tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    for key in _MODE_KEYS:
        if _placeholders(key):
            assert key in dinamici, f"template dinamico non formattato via _log: {key!r}"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_mode_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _MODE_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Segnaposto identici in EN/ES (niente KeyError a runtime)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _MODE_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_mode():
    """Flusso reale tr(template).format(...) e marker conservato in ogni lingua."""
    i18n.set_language("EN")
    assert i18n.tr("↩️ Attivazione modalità REALE ANNULLATA: torno a {old_mode}.").format(
        old_mode="SIMULAZIONE") == "↩️ REAL mode activation CANCELLED: reverting to SIMULAZIONE."
    assert i18n.tr(
        "↩️ Modalità coda multi-segnale ANNULLATA: resto a un solo segnale attivo (OVERWRITE_LAST)."
    ) == "↩️ Multi-signal queue mode CANCELLED: staying with a single active signal (OVERWRITE_LAST)."
    i18n.set_language("ES")
    assert i18n.tr("↩️ Attivazione modalità COLLAUDO ANNULLATA: torno a {old_mode}.").format(
        old_mode="REALE") == "↩️ Activación del modo PRUEBA CANCELADA: vuelvo a REALE."
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("↩️ Attivazione modalità REALE ANNULLATA: torno a {old_mode}.").format(
        old_mode="COLLAUDO") == "↩️ Attivazione modalità REALE ANNULLATA: torno a COLLAUDO."
    # marker iniziale conservato in EN/ES per tutte le chiavi
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        for key in _MODE_KEYS:
            assert i18n.tr(key)[0] == key[0], (lang, key)


def test_esclusione_audit_enabled_message():
    """Il log di AUDIT dell'attivazione REALE confermata resta un messaggio di DOMINIO: solo il
    prefisso «⚠️ » è concatenato con `real_mode.enabled_message()`, che NON passa da `i18n.tr`."""
    assert re.search(r'self\._log\("⚠️ "\s*\+\s*real_mode\.enabled_message\(\)\)', _APP_SRC), (
        "il log AUDIT enabled_message deve restare concatenazione di dominio fuori da i18n.tr")
    assert "i18n.tr(real_mode.enabled_message())" not in _APP_SRC
