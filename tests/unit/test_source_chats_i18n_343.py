"""Test hard #343 slice 4e: localizzazione (chrome) della finestra Chat sorgenti.

Finestra SAFETY-CRITICAL (filtro chat): si localizza SOLO il display. Questi test
verificano che (a) la chrome sia wrappata e coperta EN/ES, (b) la sentinella
`(predefinito)`, il chip «Traduzioni» e gli errori di dominio NON siano stati
toccati (restano IT, per non alterare logica/contratti di test)."""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
_SRC = open(os.path.join(_PKG, "source_chats_gui.py"), encoding="utf-8").read()

_SC_TR = set()
for _n in ast.walk(ast.parse(_SRC)):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _SC_TR.add(_n.args[0].value)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_chrome_wrappata():
    assert len(_SC_TR) >= 12
    for probe in ('text="📡  Chat sorgenti (multi-chat)"', 'text="💾  Salva"',
                  'self.title("Chat sorgenti (multi-chat)")'):
        assert probe not in _SRC, f"chrome non wrappata: {probe}"
    for probe in ('i18n.tr("📡  Chat sorgenti (multi-chat)")', 'i18n.tr("💾  Salva")',
                  'i18n.tr("Attiva")', 'i18n.tr("Traduzioni")'):
        assert probe in _SRC, f"wrap atteso mancante: {probe}"


# Intestazioni colonna GIÀ identiche tra le lingue (restano via fallback, non a
# catalogo): «Provider» differisce SOLO in ES → non è qui.
_IDENTICHE = {"Chat ID", "Provider", "Parser", ""}


def test_ogni_stringa_chrome_traducibile_e_nel_catalogo_en_ed_es():
    """Ogni chrome wrappata che DEVE tradursi è in catalogo EN/ES; le intestazioni
    già identiche (Chat ID/Parser/Provider) restano via fallback (allowlist)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _SC_TR:
            if key in _IDENTICHE and key not in table:
                continue                       # identica in questa lingua: fallback OK
            assert key in table, f"{lang}: manca la traduzione chrome per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati():
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _SC_TR:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r}")


def test_format_conteggio_sorgenti():
    i18n.set_language("EN")
    assert (i18n.tr("✅ Salvate {n} sorgenti in config.json.").format(n=3)
            == "✅ Saved 3 sources to config.json.")
    i18n.set_language("ES")
    assert (i18n.tr("✅ Salvate {n} sorgenti in config.json.").format(n=1)
            == "✅ Guardados 1 orígenes en config.json.")


def test_logica_safety_critical_NON_localizzata():
    """La sentinella e il chip-helper restano IT/invariati: sono logica/contratto,
    non chrome. Un tocco qui cambierebbe confronti di uguaglianza o test CI."""
    # sentinella intatta e NON passata da i18n.tr
    assert 'i18n.tr(_NO_PARSER_BASE)' not in _SRC
    assert '_NO_PARSER_BASE = "(predefinito)"' in _SRC
    # il chip-helper puro non è stato wrappato (vocabolario asserito verbatim altrove)
    assert 'i18n.tr("Nomi ✓")' not in _SRC and 'i18n.tr(nomi)' not in _SRC
    # e i suoi valori restano nel catalogo? NO: non devono esserci (fuori scope)
    for lang in ("EN", "ES"):
        assert "Nomi ✓" not in i18n._CATALOG[lang]
        assert "(predefinito)" not in i18n._CATALOG[lang]
