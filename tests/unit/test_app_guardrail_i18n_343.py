"""Test hard #343 slice 4q: localizzazione dei log GUARDRAIL RUNTIME.

Copre i log di stato anti-duplicato / limite giornaliero e della modalità coda emessi in
`_init_guards`/`_save_guard_state`. Puro e headless (`app.py` importa customtkinter → si legge
il sorgente via AST e si esercita il catalogo i18n reale). Verifica:
- wrapping in `i18n.tr(...)` nel sorgente (via AST, così le chiavi multilinea concatenate — un
  singolo `ast.Constant` — sono trovate verbatim);
- che il log DINAMICO «🧮 Modalità coda: {mode}» chiami davvero `.format(mode=…)` — mutation-guard AST;
- copertura piena EN/ES **con traduzione != IT**; conservazione segnaposto; round-trip; marker;
- ESCLUSIONE: `self._log(warning)` (bolla di dominio dagli avvisi fail-safe di
  `runtime_state.build_guards`, layer puro) resta NON wrappato.
"""

import ast
import os
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


# Gruppo GUARDRAIL RUNTIME localizzato in questa slice.
_GUARD_KEYS = (
    "⚠️ Stato anti-duplicato presente ma illeggibile: protezione dopo riavvio non garantita.",
    "🧮 Modalità coda: {mode}",
    "⚠️ Impossibile salvare lo stato anti-duplicato su disco: protezione dopo riavvio degradata.",
    "⚠️ Impossibile salvare lo stato del limite giornaliero su disco: protezione anti-overtrading dopo riavvio degradata.",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_guard_logs_wrappati_in_app():
    """Ogni chiave del gruppo è una costante di `i18n.tr(...)` in app.py (anche le multilinea)."""
    for key in _GUARD_KEYS:
        assert key in _APP_TR, f"chiave guardrail non wrappata in i18n.tr: {key!r}"
    # le vecchie stringhe non wrappate non devono sopravvivere
    for old in ('self._log("⚠️ Stato anti-duplicato presente ma illeggibile: "',
                'self._log(f"🧮 Modalità coda: {guards.mode}")',
                'self.after(0, lambda: self._log(\n                "⚠️ Impossibile salvare lo stato anti-duplicato'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_guard_log_chiama_format():
    """Mutation-guard AST: «🧮 Modalità coda: {mode}» deve essere formattato con kwargs che
    coprono TUTTI i segnaposto (togliere `.format`/il kwarg `mode` → fallisce)."""
    calls = _log_tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    assert "🧮 Modalità coda: {mode}" in dinamici, "il log modalità coda non è formattato via _log"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_guard_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _GUARD_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Segnaposto identici in EN/ES (niente KeyError a runtime)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _GUARD_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_guard():
    """Flusso reale tr(template).format(...) e marker conservato in ogni lingua."""
    i18n.set_language("EN")
    assert i18n.tr("🧮 Modalità coda: {mode}").format(mode="OVERWRITE_LAST") == (
        "🧮 Queue mode: OVERWRITE_LAST")
    assert i18n.tr(
        "⚠️ Stato anti-duplicato presente ma illeggibile: protezione dopo riavvio non garantita."
    ) == "⚠️ Anti-duplicate state present but unreadable: protection after restart not guaranteed."
    i18n.set_language("ES")
    assert i18n.tr("🧮 Modalità coda: {mode}").format(mode="FIFO") == "🧮 Modo de cola: FIFO"
    assert i18n.tr(
        "⚠️ Impossibile salvare lo stato del limite giornaliero su disco: protezione anti-overtrading dopo riavvio degradata."
    ).startswith("⚠️ No se puede guardar el estado del límite diario")
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("🧮 Modalità coda: {mode}") == "🧮 Modalità coda: {mode}"
    # marker iniziale conservato in EN/ES per tutte le chiavi
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        for key in _GUARD_KEYS:
            assert i18n.tr(key)[0] == key[0], (lang, key)


def test_esclusione_warning_dominio():
    """`self._log(warning)` (bolla di dominio dagli avvisi fail-safe di build_guards) resta
    NON wrappato: è il testo prodotto dal layer puro, non una chiave del catalogo."""
    assert "for warning in guards.warnings:\n            self._log(warning)" in _APP_SRC
    # non deve essere stato trasformato in i18n.tr(warning)
    assert "i18n.tr(warning)" not in _APP_SRC
