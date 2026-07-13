"""Test hard #343 slice 4n: localizzazione dei log di RESILIENZA runtime (riconnessione + recovery).

Puro e headless (`app.py` importa customtkinter → si legge il sorgente e si esercita il catalogo
i18n reale). Copre il gruppo di log di resilienza: riconnessione/backoff (riconnesso, errore non
recuperabile del listener, connessione persa con backoff) e recovery CSV (ripulito al retry
post-STOP, temporanei orfani rimossi all'avvio). Verifica:
- wrapping in `i18n.tr(...)` nel sorgente (via AST → costanti multi-riga confrontate verbatim);
- che i log DINAMICI chiamino davvero `.format(...)` sui segnaposto reali — mutation-guard AST;
- copertura piena EN/ES **con traduzione != IT**; conservazione segnaposto; round-trip; marker;
- ESCLUSIONE: i log di recovery con `{quando}` (value-as-key, confrontato `== "all'avvio"`)
  restano IT non wrappati.
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


# Gruppo RESILIENZA localizzato in questa slice.
_RESIL_KEYS = (
    "🔄 Riconnesso: i messaggi arrivati durante la disconnessione vengono recuperati (i troppo vecchi restano scartati per freschezza).",
    "❌ Errore non recuperabile del listener: {exc}. Bridge fermato.",
    "🔌 Connessione persa ({error}): riconnessione tra {delay}s (tentativo {attempt})…",
    "🧹 CSV ripulito al retry dopo lo STOP: {path}",
    "🧹 Rimossi {count} file temporanei CSV orfani all'avvio.",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_resilience_logs_wrappati_in_app():
    """Ogni chiave del gruppo è una costante di `i18n.tr(...)` in app.py (AST → multi-riga ok)."""
    for key in _RESIL_KEYS:
        assert key in _APP_TR, f"chiave resilienza non wrappata in i18n.tr: {key!r}"
    for old in ('f"❌ Errore non recuperabile del listener: {e}. Bridge fermato."',
                'f"🧹 CSV ripulito al retry dopo lo STOP: {path}"',
                'f"🧹 Rimossi {removed} file temporanei CSV orfani all\'avvio."'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_resilience_logs_chiamano_format():
    """Mutation-guard AST: ogni `self._log(i18n.tr("…{seg}…").format(**kwargs))` deve fornire
    kwargs che coprono TUTTI i segnaposto (togliere `.format`/un kwarg → fallisce)."""
    calls = _log_tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    for key in _RESIL_KEYS:
        if _placeholders(key):
            assert key in dinamici, f"template dinamico non formattato via _log: {key!r}"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_resilience_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _RESIL_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Segnaposto identici in EN/ES (niente KeyError a runtime)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _RESIL_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_resilience():
    """Flusso reale tr(template).format(...) e marker conservato in ogni lingua."""
    i18n.set_language("EN")
    msg = i18n.tr("🔌 Connessione persa ({error}): riconnessione tra {delay}s (tentativo {attempt})…").format(
        error="TimedOut", delay="8", attempt=3)
    assert msg == "🔌 Connection lost (TimedOut): reconnecting in 8s (attempt 3)…" and "{" not in msg
    assert i18n.tr("❌ Errore non recuperabile del listener: {exc}. Bridge fermato.").format(
        exc="InvalidToken") == "❌ Unrecoverable listener error: InvalidToken. Bridge stopped."
    i18n.set_language("ES")
    assert i18n.tr("🧹 Rimossi {count} file temporanei CSV orfani all'avvio.").format(count=2) == (
        "🧹 Eliminados 2 archivos temporales CSV huérfanos al inicio.")
    assert i18n.tr("🧹 CSV ripulito al retry dopo lo STOP: {path}").format(path="/x/o.csv") == (
        "🧹 CSV limpiado en el reintento tras STOP: /x/o.csv")
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("🔄 Riconnesso: i messaggi arrivati durante la disconnessione vengono recuperati (i troppo vecchi restano scartati per freschezza).").startswith("🔄 Riconnesso")
    # marker iniziale conservato in EN/ES per tutte le chiavi
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        for key in _RESIL_KEYS:
            assert i18n.tr(key)[0] == key[0], (lang, key)


def test_esclusione_quando_recovery_resta_it():
    """I log di recovery con `{quando}` (value-as-key, confrontato `== "all'avvio"` per scegliere
    l'evento journal) restano IT non wrappati: localizzarli richiede uno split display↔chiave,
    rimandato a una slice dedicata. Guardia contro una localizzazione prematura."""
    assert 'f"🧹 CSV riportato a solo header {quando}: {path}"' in _APP_SRC
    assert 'f"⚠️ Impossibile ripulire il CSV {quando} ({exc}): un segnale potrebbe "' in _APP_SRC
    for bad in ('i18n.tr("🧹 CSV riportato a solo header {quando}',
                'i18n.tr(f"🧹 CSV riportato a solo header',
                'i18n.tr(f"⚠️ Impossibile ripulire il CSV'):
        assert bad not in _APP_SRC, f"log {{quando}} wrappato prematuramente: {bad}"
