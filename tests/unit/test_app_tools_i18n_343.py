"""Test hard #343 slice 4o: localizzazione dei log LOG & DIAGNOSTICA (strumenti) di app.py.

Puro e headless (`app.py` importa customtkinter → si legge il sorgente e si esercita il catalogo
i18n reale). Copre i log degli strumenti Log/diagnostica: apri cartella log, export audit modalità
reale, copia diagnostica, retention log, svuota log, toggle Debug. Verifica:
- wrapping in `i18n.tr(...)` nel sorgente (via AST);
- che i log DINAMICI chiamino davvero `.format(...)` sui segnaposto reali — mutation-guard AST;
- copertura piena EN/ES **con traduzione != IT**; conservazione segnaposto; round-trip; marker;
- ESCLUSIONE: i suffissi di dominio `config_store.save_status_message` (retention/debug NON
  salvata) restano IT concatenati FUORI da `i18n.tr` (si wrappa solo il prefisso).
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


# Gruppo LOG & DIAGNOSTICA localizzato in questa slice.
_TOOLS_KEYS = (
    "📂 Cartella log: {path}",
    "❌ Impossibile aprire la cartella log: {exc}",
    "🧾 Audit modalità reale esportato ({count} eventi): {path}",
    "❌ Esportazione audit reale fallita: {exc}",
    "📋 Diagnostica copiata negli appunti.",
    "❌ Copia diagnostica fallita: {exc}",
    "❌ Retention log NON salvata. ",
    "🧹 Retention log: {days} giorni · {count} file vecchi rimossi.",
    "🧹 Retention log: conservo tutto (nessuna pulizia automatica).",
    "🧹 Log svuotati: {count} file su disco rimossi; vista azzerata.",
    "🐞 Modalità Debug log: {state}.",
    "⚠️ Impostazione Debug NON salvata. ",
    "🧹 Retention log ({days}g): {count} file vecchi rimossi.",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_tools_logs_wrappati_in_app():
    """Ogni chiave del gruppo è una costante di `i18n.tr(...)` in app.py."""
    for key in _TOOLS_KEYS:
        assert key in _APP_TR, f"chiave tools non wrappata in i18n.tr: {key!r}"
    for old in ('f"📂 Cartella log: {folder}"', 'f"🧹 Log svuotati: {len(removed)}',
                'f"🐞 Modalità Debug log: {\'ON\' if on else \'OFF\'}."',
                'self._log("📋 Diagnostica copiata negli appunti.")'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_tools_logs_chiamano_format():
    """Mutation-guard AST: ogni `self._log(i18n.tr("…{seg}…").format(**kwargs))` deve fornire
    kwargs che coprono TUTTI i segnaposto (togliere `.format`/un kwarg → fallisce)."""
    calls = _log_tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    for key in _TOOLS_KEYS:
        if _placeholders(key):
            assert key in dinamici, f"template dinamico non formattato via _log: {key!r}"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_tools_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _TOOLS_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Segnaposto identici in EN/ES (niente KeyError a runtime)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _TOOLS_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_tools():
    """Flusso reale tr(template).format(...) e marker conservato in ogni lingua."""
    i18n.set_language("EN")
    assert i18n.tr("📂 Cartella log: {path}").format(path="/var/log") == "📂 Log folder: /var/log"
    msg = i18n.tr("🧾 Audit modalità reale esportato ({count} eventi): {path}").format(count=7, path="a.txt")
    assert msg == "🧾 Real-mode audit exported (7 events): a.txt" and "{" not in msg
    assert i18n.tr("🐞 Modalità Debug log: {state}.").format(state="ON") == "🐞 Debug log mode: ON."
    i18n.set_language("ES")
    assert i18n.tr("🧹 Retention log: {days} giorni · {count} file vecchi rimossi.").format(
        days=7, count=3) == "🧹 Retención de logs: 7 días · 3 archivos antiguos eliminados."
    assert i18n.tr("📋 Diagnostica copiata negli appunti.") == "📋 Diagnóstico copiado al portapapeles."
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("🧹 Log svuotati: {count} file su disco rimossi; vista azzerata.").format(count=2) == (
        "🧹 Log svuotati: 2 file su disco rimossi; vista azzerata.")
    # marker iniziale conservato in EN/ES per tutte le chiavi
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        for key in _TOOLS_KEYS:
            assert i18n.tr(key)[0] == key[0], (lang, key)


def test_esclusione_suffissi_dominio_restano_it():
    """I prefissi retention/debug NON-salvata sono wrappati, ma il suffisso di dominio
    `config_store.save_status_message` resta concatenato FUORI da `i18n.tr` (regex robusta a
    formattazione)."""
    for prefix in ('❌ Retention log NON salvata\\. ', '⚠️ Impostazione Debug NON salvata\\. '):
        assert re.search(
            r'i18n\.tr\("' + prefix + r'"\)\s*\+\s*config_store\.save_status_message', _APP_SRC), prefix
    for bad in ('i18n.tr("❌ Retention log NON salvata. " + config_store',
                'i18n.tr(config_store.save_status_message'):
        assert bad not in _APP_SRC, f"suffisso di dominio wrappato per errore: {bad}"
