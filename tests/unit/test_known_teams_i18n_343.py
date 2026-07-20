"""Test hard #343 slice 4t: localizzazione del pannello «🧹 Nomi squadra noti» (known_teams_gui).

Il pannello è codice widget (customtkinter → non importabile headless in CI): si legge il sorgente
via AST e si esercita il catalogo i18n reale. Verifica:
- wrapping in `i18n.tr(...)` nel sorgente di tutte le label/status (via AST tr-constant);
- copertura piena EN/ES **con traduzione != IT** (eccetto «Sport», parola identica in EN);
- conservazione segnaposto ({exc}/{count}) in EN/ES; round-trip reale; marker iniziale;
- ESCLUSIONE value-as-key: il SENTINEL «(tutti gli sport)» (`_SPORT_ALL`, confronto `s == _SPORT_ALL`
  in `_selected_sport`) resta IT e NON è a catalogo — localizzarlo romperebbe il confronto;
- ESCLUSIONE dominio: i nomi sport (`sports.SPORTS`) e i nomi squadra NON sono wrappati.
"""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "known_teams_gui.py"), encoding="utf-8") as _fh:
    _KT_SRC = _fh.read()
_KT_AST = ast.parse(_KT_SRC)

_KT_TR = set()
for _n in ast.walk(_KT_AST):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _KT_TR.add(_n.args[0].value)

# Tutte le stringhe UI del pannello localizzate in questa slice.
_KT_KEYS = (
    "🧹  Nomi squadra noti (permanenti) — ripulitura",
    "Nomi squadra del dizionario locale, conservati per sempre. Elimina qui quelli obsoleti/errati (es. squadre retrocesse).",
    "Sport",
    "🔄 Aggiorna",
    "Nomi noti",
    "⛔ Provider del dizionario locale non disponibile.",
    "⏳ Dizionario occupato: riprova tra poco.",
    "⚠️ Errore lettura nomi: {exc}",
    "{count} nomi noti.",
    "🗑 Elimina",
    "⛔ Eliminazione non disponibile.",
    "⚠️ Eliminazione fallita: {exc}",
    "⚠️ Eliminazione non riuscita: dizionario locale non disponibile.",
)

# «Sport» è identica in EN (parola uguale in italiano/inglese): unica chiave EN == IT ammessa.
_EN_IDENTICAL = {"Sport"}


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_tutte_le_label_wrappate_in_tr():
    """Ogni stringa UI del pannello è una costante di `i18n.tr(...)` (via AST)."""
    for key in _KT_KEYS:
        assert key in _KT_TR, f"label del pannello non wrappata in i18n.tr: {key!r}"
    # le vecchie stringhe hardcoded non devono sopravvivere
    for old in ('text="🔄 Aggiorna"', 'text="🗑 Elimina"',
                'f"{len(teams)} nomi noti."', 'f"⚠️ Errore lettura nomi: {type(exc).__name__}"'):
        assert old not in _KT_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_sentinel_value_as_key_resta_it_e_non_a_catalogo():
    """«(tutti gli sport)» è un value-as-key: resta `_SPORT_ALL` IT, MAI wrappato né a catalogo
    (localizzarlo romperebbe il confronto `s == _SPORT_ALL` in _selected_sport)."""
    assert '_SPORT_ALL = "(tutti gli sport)"' in _KT_SRC
    assert "return None if s == _SPORT_ALL else s" in _KT_SRC
    assert "values=[_SPORT_ALL, *sports.SPORTS]" in _KT_SRC
    assert 'i18n.tr("(tutti gli sport)")' not in _KT_SRC
    assert 'i18n.tr(_SPORT_ALL' not in _KT_SRC
    for lang in ("EN", "ES"):
        assert "(tutti gli sport)" not in i18n._CATALOG[lang], (
            f"{lang}: sentinel value-as-key finito a catalogo per errore")


def test_import_i18n():
    assert "from . import gui_utils, i18n, sports" in _KT_SRC


def test_dynamic_labels_chiamano_format():
    """I due status dinamici usano `.format(...)` che copre i segnaposto ({exc}/{count})."""
    for node in ast.walk(_KT_AST):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"):
            continue
        tr = node.func.value
        if not (isinstance(tr, ast.Call) and isinstance(tr.func, ast.Attribute)
                and tr.func.attr == "tr" and tr.args
                and isinstance(tr.args[0], ast.Constant)):
            continue
        attesi = _placeholders(tr.args[0].value)
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        assert attesi <= kwargs, (
            f".format non copre i segnaposto di {tr.args[0].value!r}: mancano {attesi - kwargs}")
    # entrambi i template dinamici passano da .format
    assert 'i18n.tr("⚠️ Errore lettura nomi: {exc}").format(exc=type(exc).__name__)' in _KT_SRC
    assert 'i18n.tr("{count} nomi noti.").format(count=len(teams))' in _KT_SRC


def test_catalogo_en_es_completo_e_diverso():
    """Copertura piena EN/ES; traduzione != IT (eccetto «Sport», identica in EN)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _KT_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            if lang == "EN" and key in _EN_IDENTICAL:
                continue
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_placeholder_e_marker_conservati():
    """Segnaposto identici in EN/ES e marker iniziale (emoji/simbolo) conservato."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _KT_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")
            if not key[0].isalnum():   # marker emoji/simbolo/paren/brace preservato
                assert table[key][0] == key[0], (lang, key)


def test_round_trip_reale():
    i18n.set_language("EN")
    assert i18n.tr("🗑 Elimina") == "🗑 Delete"
    # sentinel value-as-key: NON tradotto → identità anche in EN
    assert i18n.tr("(tutti gli sport)") == "(tutti gli sport)"
    assert i18n.tr("{count} nomi noti.").format(count=3) == "3 known names."
    assert i18n.tr("⚠️ Errore lettura nomi: {exc}").format(exc="KeyError") == (
        "⚠️ Error reading names: KeyError")
    i18n.set_language("ES")
    assert i18n.tr("Sport") == "Deporte"
    assert i18n.tr("🔄 Aggiorna") == "🔄 Actualizar"
    # fallback IT: identità
    i18n.set_language("IT")
    assert i18n.tr("🧹  Nomi squadra noti (permanenti) — ripulitura") == (
        "🧹  Nomi squadra noti (permanenti) — ripulitura")
