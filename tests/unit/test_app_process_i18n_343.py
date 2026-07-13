"""Test hard #343 slice 4m: localizzazione dei log di ESITO elaborazione messaggio/segnale.

Puro e headless (`app.py` importa customtkinter → si legge il sorgente e si esercita il catalogo
i18n reale). Copre il gruppo di log runtime che spiegano l'esito di un messaggio/segnale — dispatch
ignore (troppo vecchio / config senza filtro / conflitto notif-chat / instradamento sconosciuto),
scrittura CSV (scartato / write fallita / tracciabilità Messaggio→CSV) e conferma/scadenza
(aggiornamento CSV post-conferma/scadenza fallito, scaduti rimossi). Verifica:
- wrapping in `i18n.tr(...)` nel sorgente (via AST → costanti multi-riga confrontate verbatim);
- che i log DINAMICI chiamino davvero `.format(...)` sui segnaposto reali — mutation-guard AST;
- copertura piena EN/ES **con traduzione != IT**; conservazione segnaposto; round-trip; marker;
- ESCLUSIONI: gli esiti di DOMINIO (outcome.*_log, confirmation_removed/ignored_log,
  multi_signal.blocked_message, traceback) restano IT non wrappati.
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


# Gruppo ESITO elaborazione messaggio/segnale localizzato in questa slice.
_PROC_KEYS = (
    "⏳ Messaggio ignorato: troppo vecchio (probabile arretrato dopo una disconnessione).",
    "⚠️ Config live senza filtro chat: messaggio ignorato per sicurezza (configura chat/sorgenti, poi salva).",
    "❌ La Chat notifiche XTrader coincide con una sorgente ammessa: config ambigua, messaggio IGNORATO (né segnale né conferma). Correggi xtrader_notification_chat_id (dev'essere una chat separata).",
    "⚠️ Esito instradamento sconosciuto ({decision}): messaggio ignorato per sicurezza.",
    "⚠️ Segnale scartato ({source}/{status}): {detail}",
    "❌ Scrittura CSV fallita: {exc}. Segnale non registrato (riprovabile).",
    "🧾 Messaggio→CSV  |  msg: {msg}  |  riga: {row}",
    "❌ Aggiornamento CSV dopo conferma fallito: {exc}. Riprovo a breve.",
    "❌ Aggiornamento CSV alla scadenza fallito: {exc}. Riprovo a breve.",
    "🗑️  {n} segnale/i scaduto/i rimosso/i dal CSV",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_process_logs_wrappati_in_app():
    """Ogni chiave del gruppo è una costante di `i18n.tr(...)` in app.py (AST → multi-riga ok)."""
    for key in _PROC_KEYS:
        assert key in _APP_TR, f"chiave elaborazione non wrappata in i18n.tr: {key!r}"
    # i vecchi f-string non devono sopravvivere
    for old in ('f"⚠️ Segnale scartato ({result.source}/{result.status}): {detail}"',
                'f"❌ Scrittura CSV fallita: {e}. Segnale non registrato (riprovabile)."',
                '"🧾 Messaggio→CSV  |  msg: " + m + "  |  riga: "',
                'f"🗑️  {n} segnale/i scaduto/i rimosso/i dal CSV"'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_process_logs_chiamano_format():
    """Mutation-guard AST: ogni `self._log(i18n.tr("…{seg}…").format(**kwargs))` deve fornire
    kwargs che coprono TUTTI i segnaposto (togliere `.format`/un kwarg → fallisce)."""
    calls = _log_tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    for key in _PROC_KEYS:
        if _placeholders(key):
            assert key in dinamici, f"template dinamico non formattato via _log: {key!r}"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_process_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT: questi log runtime vanno realmente localizzati."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PROC_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Segnaposto identici in EN/ES (niente KeyError a runtime)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PROC_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_process():
    """Flusso reale tr(template).format(...) e marker conservato in ogni lingua."""
    i18n.set_language("EN")
    msg = i18n.tr("⚠️ Segnale scartato ({source}/{status}): {detail}").format(
        source="P.Bet", status="NOT_READY", detail="quota mancante")
    assert msg == "⚠️ Signal discarded (P.Bet/NOT_READY): quota mancante" and "{" not in msg
    msg = i18n.tr("❌ Scrittura CSV fallita: {exc}. Segnale non registrato (riprovabile).").format(
        exc="OSError: locked")
    assert msg == "❌ CSV write failed: OSError: locked. Signal not recorded (retryable)."
    assert i18n.tr("🗑️  {n} segnale/i scaduto/i rimosso/i dal CSV").format(n=2) == (
        "🗑️  2 expired signal(s) removed from the CSV")
    i18n.set_language("ES")
    msg = i18n.tr("🧾 Messaggio→CSV  |  msg: {msg}  |  riga: {row}").format(msg="h#1", row="Price=1,85")
    assert msg == "🧾 Mensaje→CSV  |  msg: h#1  |  fila: Price=1,85"
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("⚠️ Esito instradamento sconosciuto ({decision}): messaggio ignorato per sicurezza.").format(
        decision="X") == "⚠️ Esito instradamento sconosciuto (X): messaggio ignorato per sicurezza."
    # marker iniziale conservato in EN/ES per tutte le chiavi
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        for key in _PROC_KEYS:
            assert i18n.tr(key)[0] == key[0], (lang, key)


def test_esclusioni_dominio_restano_it():
    """Gli esiti di DOMINIO (outcome.*_log, confirmation_removed/ignored_log, blocked_message,
    traceback) restano IT non wrappati: guardia contro over-localization."""
    for dom in ('self._log(m))', 'outcome.signal_log', 'outcome.csv_log', 'outcome.log',
                'multi_signal.blocked_message', 'signal_outcome.confirmation_removed_log',
                'signal_outcome.confirmation_ignored_log'):
        assert dom in _APP_SRC, f"percorso di dominio sparito: {dom}"
    for bad in ('i18n.tr(outcome.', 'i18n.tr(m)', 'i18n.tr(removed_log',
                'i18n.tr(ignored_log', 'i18n.tr(multi_signal.blocked_message'):
        assert bad not in _APP_SRC, f"dominio wrappato per errore: {bad}"
