"""Test hard #343 slice 4aa: log di ESITO (successo) del selettore lingua localizzato + attualizzato.

Il log di successo mostrato dopo la scelta lingua (`App._language_chosen`, ramo `ok`) era una f-string
IT non localizzata **e** conteneva una nota ormai STANTIA («le altre finestre arrivano con i prossimi
slice» — dalle slice 4x/4y/4z sono tutte localizzate). Questa slice: lo wrappa in `i18n.tr` e attualizza
la nota a «intera interfaccia». È codice GUI (app.py, non importabile headless) → AST + catalogo reale.

Il template esterno interpola `{lang}` (codice lingua) e `{extra}` (sotto-frase già localizzata);
la variante «CSV preservata» risolve `{kept}` col proprio `.format` PRIMA di essere interpolata →
nessuna graffa residua nel doppio format.
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

_MAIN = ("🌐 Lingua del bridge impostata: {lang}{extra} — riavvia il "
         "bridge per applicare la lingua all'intera interfaccia.")
_EXTRA_KEPT = " (lingua CSV personalizzata preservata: {kept})"
_EXTRA_ALIGNED = " — lingua CSV allineata"
_ALL_KEYS = (_MAIN, _EXTRA_KEPT, _EXTRA_ALIGNED)


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def test_success_log_wrappato_in_tr():
    """Le 3 stringhe del log di successo sono costanti `i18n.tr(...)` in app.py (AST)."""
    for key in _ALL_KEYS:
        assert key in _APP_TR, f"log selettore lingua non wrappato in i18n.tr: {key!r}"


def test_nota_stantia_rimossa():
    """La nota ormai falsa («solo finestra principale; le altre arrivano coi prossimi slice») NON
    deve sopravvivere: dalle slice 4x/4y/4z tutte le finestre/dialoghi sono localizzati."""
    for stale in ("le altre finestre arrivano", "con i prossimi slice",
                  "finestra principale; le altre"):
        assert stale not in _APP_SRC, f"nota stantia sopravvissuta: {stale!r}"
    # la vecchia f-string non wrappata non deve sopravvivere
    assert 'f"🌐 Lingua del bridge impostata:' not in _APP_SRC


def test_format_copre_i_segnaposto():
    """Mutation-guard AST: il template esterno passa da `.format(lang=..., extra=...)` e la variante
    «CSV preservata» da `.format(kept=...)` (togliere un arg → segnaposto letterale nel log)."""
    coppie = {}
    for node in ast.walk(_APP_AST):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"):
            tr = node.func.value
            if (isinstance(tr, ast.Call) and isinstance(tr.func, ast.Attribute)
                    and tr.func.attr == "tr" and tr.args
                    and isinstance(tr.args[0], ast.Constant)
                    and tr.args[0].value in _ALL_KEYS):
                coppie[tr.args[0].value] = {kw.arg for kw in node.keywords if kw.arg}
    assert coppie.get(_MAIN) == {"lang", "extra"}, "template esterno: .format(lang, extra) mancante"
    assert coppie.get(_EXTRA_KEPT) == {"kept"}, "variante CSV preservata: .format(kept) mancante"
    # la variante «allineata» non ha segnaposto → nessun .format richiesto
    assert not _placeholders(_EXTRA_ALIGNED)


def test_catalogo_en_es():
    """Le 3 chiavi sono a catalogo EN/ES, traduzione != IT, segnaposto conservati."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _ALL_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"
            assert _placeholders(table[key]) == _placeholders(key), (
                f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_round_trip_messaggio_completo():
    """Ricostruisce il messaggio reale (template + extra) in EN/ES per entrambe le varianti."""
    i18n.set_language("EN")
    extra_kept = i18n.tr(_EXTRA_KEPT).format(kept="fr")
    msg = i18n.tr(_MAIN).format(lang="EN", extra=extra_kept)
    assert msg == ("🌐 Bridge language set: EN (custom CSV language preserved: fr) — restart the "
                   "bridge to apply the language to the whole interface.")
    extra_aligned = i18n.tr(_EXTRA_ALIGNED)
    msg2 = i18n.tr(_MAIN).format(lang="EN", extra=extra_aligned)
    assert msg2.endswith("whole interface.") and "CSV language aligned" in msg2
    i18n.set_language("ES")
    msg3 = i18n.tr(_MAIN).format(lang="ES", extra=i18n.tr(_EXTRA_ALIGNED))
    assert msg3.startswith("🌐 Idioma del bridge configurado: ES — idioma CSV alineado")
    # fallback IT: identità
    i18n.set_language("IT")
    assert i18n.tr(_MAIN).format(lang="IT", extra="") == (
        "🌐 Lingua del bridge impostata: IT — riavvia il bridge per applicare la lingua "
        "all'intera interfaccia.")
