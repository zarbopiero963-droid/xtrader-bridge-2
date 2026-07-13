"""Test hard #343 slice 4p: localizzazione dei log WIZARD + LINGUA-SELECTOR + PROFILO/SORGENTI.

Puro e headless (`app.py` importa customtkinter → si legge il sorgente e si esercita il catalogo
i18n reale). Copre i log delle azioni GUI di wizard, selettore lingua (percorsi rimandato e
salvataggio-fallito), applicazione profilo e aggiornamento sorgenti. Verifica:
- wrapping in `i18n.tr(...)` nel sorgente (via AST);
- che i log DINAMICI chiamino davvero `.format(...)` sui segnaposto reali — mutation-guard AST;
- copertura piena EN/ES **con traduzione != IT**; conservazione segnaposto; round-trip; marker;
- ESCLUSIONI: il log SUCCESS «🌐 Lingua del bridge impostata …» (con `{extra}` computato + nota)
  resta f-string IT non wrappata (slice dedicata); il suffisso di dominio
  `config_store.save_status_message` di «Profilo … NON persistito» resta fuori da `i18n.tr`;
  il log di apertura-wizard-fallita logga SOLO `type(ex).__name__` (mai il token, review #354).
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


# Gruppo WIZARD + LINGUA-SELECTOR + PROFILO/SORGENTI localizzato in questa slice.
_WP_KEYS = (
    "❌ Apertura wizard fallita: {exc}",
    "🧙 Wizard completato: configurazione salvata.",
    "🌐 Selettore lingua rimandato: auto-start attivo (imposta app_language in config.json, o disattiva l'auto-start).",
    "⚠️ Lingua scelta ({lang}) ma salvataggio config FALLITO: nulla è cambiato (la sessione resta nella lingua precedente) e il selettore riapparirà al prossimo avvio — controlla permessi/spazio disco.",
    "⚠️ Scheda {tab} non aggiornata dal profilo (mostra ancora i valori precedenti): {exc}",
    "📁 Profilo caricato e applicato (token invariato).",
    "⚠️ Profilo applicato in memoria (token invariato), ma NON persistito. ",
    "📡 Sorgenti multi-chat aggiornate ({count}).",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_wp_logs_wrappati_in_app():
    """Ogni chiave del gruppo è una costante di `i18n.tr(...)` in app.py."""
    for key in _WP_KEYS:
        assert key in _APP_TR, f"chiave wizard/profilo non wrappata in i18n.tr: {key!r}"
    for old in ('f"❌ Apertura wizard fallita: {type(ex).__name__}"',
                'self._log("🧙 Wizard completato: configurazione salvata.")',
                'f"📡 Sorgenti multi-chat aggiornate ({len(new_cfg'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_wp_logs_chiamano_format():
    """Mutation-guard AST: ogni `self._log(i18n.tr("…{seg}…").format(**kwargs))` deve fornire
    kwargs che coprono TUTTI i segnaposto (togliere `.format`/un kwarg → fallisce)."""
    calls = _log_tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    for key in _WP_KEYS:
        if _placeholders(key):
            assert key in dinamici, f"template dinamico non formattato via _log: {key!r}"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_wp_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _WP_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Segnaposto identici in EN/ES (niente KeyError a runtime)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _WP_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_wp():
    """Flusso reale tr(template).format(...) e marker conservato in ogni lingua."""
    i18n.set_language("EN")
    assert i18n.tr("❌ Apertura wizard fallita: {exc}").format(exc="TclError") == (
        "❌ Failed to open the wizard: TclError")
    assert i18n.tr("📡 Sorgenti multi-chat aggiornate ({count}).").format(count=3) == (
        "📡 Multi-chat sources updated (3).")
    msg = i18n.tr("⚠️ Scheda {tab} non aggiornata dal profilo (mostra ancora i valori precedenti): {exc}").format(
        tab="🧩 Parser", exc="KeyError")
    assert msg == "⚠️ Tab 🧩 Parser not updated from the profile (still shows the previous values): KeyError"
    i18n.set_language("ES")
    assert i18n.tr("📁 Profilo caricato e applicato (token invariato).") == (
        "📁 Perfil cargado y aplicado (token sin cambios).")
    assert i18n.tr("⚠️ Lingua scelta ({lang}) ma salvataggio config FALLITO: nulla è cambiato (la sessione resta nella lingua precedente) e il selettore riapparirà al prossimo avvio — controlla permessi/spazio disco.").format(
        lang="EN").startswith("⚠️ Idioma elegido (EN)")
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("🧙 Wizard completato: configurazione salvata.") == "🧙 Wizard completato: configurazione salvata."
    # marker iniziale conservato in EN/ES per tutte le chiavi
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        for key in _WP_KEYS:
            assert i18n.tr(key)[0] == key[0], (lang, key)


def test_esclusioni_defer_e_dominio():
    """Il log SUCCESS lingua è ORA localizzato (slice 4aa): era rimandato dalla 4p, la 4aa lo wrappa
    in `i18n.tr` e attualizza la nota. Il suffisso di dominio `save_status_message` di «Profilo …
    NON persistito» resta fuori da `i18n.tr` (regex robusta). Il log wizard-fallito NON deve mai
    loggare il token (solo la classe dell'eccezione)."""
    # successo lingua: dalla slice 4aa è wrappato in i18n.tr (non più f-string rimandata); il test
    # dedicato è tests/unit/test_language_selector_success_i18n_343.py.
    assert 'f"🌐 Lingua del bridge impostata: {lang}{extra} — "' not in _APP_SRC
    assert 'i18n.tr("🌐 Lingua del bridge impostata: {lang}{extra} — riavvia il ' in _APP_SRC
    # suffisso dominio del profilo NON-persistito: prefisso wrappato, save_status_message fuori
    assert re.search(
        r'i18n\.tr\("⚠️ Profilo applicato in memoria \(token invariato\), ma NON persistito\. "\)\s*\+\s*config_store\.save_status_message',
        _APP_SRC), "prefisso profilo NON-persistito wrappato, suffisso dominio fuori da i18n.tr"
    # apertura wizard fallita: logga type(ex).__name__, MAI l'eccezione intera (token safety #354)
    assert 'i18n.tr("❌ Apertura wizard fallita: {exc}").format(exc=type(ex).__name__)' in _APP_SRC
    assert 'i18n.tr("❌ Apertura wizard fallita: {exc}").format(exc=ex)' not in _APP_SRC
