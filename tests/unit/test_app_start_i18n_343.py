"""Test hard #343 slice 4l: localizzazione dei log AVVIO/VALIDAZIONE START di `app.py`.

Puro e headless (`app.py` importa customtkinter → si legge il sorgente e si esercita il catalogo
i18n reale). Copre il gruppo di log safety-critical che BLOCCANO/annullano lo START (token
mancante, chat/parser non configurati, conflitto chat notifiche, modalità reale annullata, CSV
non inizializzabile), verificando:
- wrapping in `i18n.tr(...)` nel sorgente (via AST → costanti multi-riga concatenate confrontate
  verbatim col catalogo);
- che i log DINAMICI chiamino davvero `.format(...)` sui segnaposto reali (`{err}`/`{problem}`/
  `{path}`/`{exc}`) — mutation-guard AST;
- copertura piena EN/ES; conservazione segnaposto; round-trip `.format(...)`; marker conservato;
- le ESCLUSIONI: i log di puro dominio `f"❌ {err}"` / `f"⚠️ {warn}"` restano IT non wrappati.
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


# Gruppo START localizzato in questa slice (chiavi IT = chiavi del catalogo).
_START_KEYS = (
    "❌ python-telegram-bot non disponibile: impossibile avviare il listener.",
    "❌ Inserisci il Bot Token prima di avviare!",
    "❌ Impostazioni avanzate non valide (vedi avvisi sopra): correggile prima di avviare. Avvio annullato.",
    "❌ Nessuna chat configurata (Chat ID, parser per-chat o sorgente): il bridge accetterebbe segnali da QUALSIASI chat. Configura almeno una chat/sorgente. Avvio annullato.",
    "❌ Nessun Parser Personalizzato configurato (globale o per-chat): il parser automatico è disattivato e il listener ignorerebbe OGNI segnale. Configura almeno un Parser Personalizzato prima di avviare (scheda 🧩 Parser). Avvio annullato.",
    "❌ Sorgenti multi-chat: {err}",
    "Avvio annullato: correggi le sorgenti.",
    "⏸️ Avvio automatico annullato: nessuna chat sorgente ATTIVA.",
    "⚠️ Nessuna chat sorgente ATTIVA: il listener parte ma NON processerà alcun segnale finché non attivi almeno una chat.",
    "❌ La Chat notifiche XTrader coincide con una chat sorgente: cambiala (i segnali verrebbero scambiati per conferme). Avvio annullato.",
    "⏸️ Avvio automatico in modalità reale annullato.",
    "▶️ Avvio automatico del listener (auto_start_listener attivo).",
    "⏸️ Avvio in modalità reale annullato.",
    "❌ {problem} Avvio annullato.",
    "❌ Impossibile inizializzare il CSV ({path}): {exc}. Avvio annullato.",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_start_logs_wrappati_in_app():
    """Ogni chiave del gruppo è una costante di `i18n.tr(...)` in app.py (AST → multi-riga ok)."""
    for key in _START_KEYS:
        assert key in _APP_TR, f"chiave START non wrappata in i18n.tr: {key!r}"
    # i vecchi literal/f-string non devono sopravvivere
    for old in ('self._log("❌ Inserisci il Bot Token prima di avviare!")',
                'self._log(f"❌ {csv_problem} Avvio annullato.")',
                'self._log("Avvio annullato: correggi le sorgenti.")',
                'self._log(f"❌ Impossibile inizializzare il CSV'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_start_logs_chiamano_format():
    """Mutation-guard AST: ogni `self._log(i18n.tr("…{seg}…").format(**kwargs))` deve fornire
    kwargs che coprono TUTTI i segnaposto (togliere `.format`/un kwarg → fallisce)."""
    calls = _log_tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    for key in _START_KEYS:
        if _placeholders(key):
            assert key in dinamici, f"template dinamico START non formattato via _log: {key!r}"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_start_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES: nessun log START resta in italiano. Oltre a esistere e non essere
    vuota, la traduzione DEVE differire dalla chiave IT (Sourcery #35): questi log sono
    safety-critical e vanno realmente localizzati — una «traduzione» identità (== IT) lascerebbe
    l'utente EN/ES in italiano ma passerebbe un semplice check di presenza."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _START_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, (
                f"{lang}: traduzione IDENTICA all'italiano per {key!r} (log START non localizzato)")


def test_placeholder_conservati_nelle_traduzioni():
    """`{err}`/`{problem}`/`{path}`/`{exc}` identici in EN/ES (niente KeyError a runtime)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _START_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_start():
    """Flusso reale tr(template).format(...) e marker conservato in ogni lingua."""
    i18n.set_language("EN")
    assert i18n.tr("❌ Inserisci il Bot Token prima di avviare!") == "❌ Enter the Bot Token before starting!"
    msg = i18n.tr("❌ Sorgenti multi-chat: {err}").format(err="chat_id mancante")
    assert msg == "❌ Multi-chat sources: chat_id mancante" and "{" not in msg
    msg = i18n.tr("❌ Impossibile inizializzare il CSV ({path}): {exc}. Avvio annullato.").format(
        path="C:\\op.csv", exc="OSError: locked")
    assert msg == "❌ Cannot initialize the CSV (C:\\op.csv): OSError: locked. Start cancelled."
    i18n.set_language("ES")
    assert i18n.tr("⏸️ Avvio in modalità reale annullato.") == "⏸️ Inicio en modo real cancelado."
    msg = i18n.tr("❌ {problem} Avvio annullato.").format(problem="Cartella CSV inesistente.")
    assert msg == "❌ Cartella CSV inesistente. Inicio cancelado."
    # fallback IT
    i18n.set_language("IT")
    assert i18n.tr("▶️ Avvio automatico del listener (auto_start_listener attivo).") == (
        "▶️ Avvio automatico del listener (auto_start_listener attivo).")
    # marker/emoji iniziale conservato in EN/ES — solo per le chiavi che HANNO un marker di
    # severità (le chiavi che iniziano con testo, es. «Avvio annullato: …», non ne hanno).
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        for key in _START_KEYS:
            if not key[0].isalnum():
                assert i18n.tr(key)[0] == key[0], (lang, key)


def test_esclusioni_dominio_restano_it():
    """I log di PURO dominio (`f"❌ {err}"` dal validator, `f"⚠️ {warn}"` dagli store) restano
    IT non wrappati: guardia contro over-localization del contenuto di dominio."""
    assert 'self._log(f"❌ {err}")' in _APP_SRC
    assert 'self._log(f"⚠️ {warn}")' in _APP_SRC
    for bad in ('i18n.tr(f"❌ {err}")', 'i18n.tr(f"⚠️ {warn}")', 'i18n.tr(err)', 'i18n.tr(warn)'):
        assert bad not in _APP_SRC, f"dominio wrappato per errore: {bad}"
