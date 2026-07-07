"""Test hard #343 slice 4g: localizzazione della finestra Parser Personalizzato.

Puri e headless (non si costruisce la GUI: `custom_parser_gui` importa customtkinter).
Si verifica il catalogo i18n e il wrapping nel sorgente, con attenzione:
- ai messaggi TEMPLATE (`{count}`/`{src}`): la traduzione DEVE conservare gli stessi
  segnaposto, altrimenti `.format(...)` esploderebbe a runtime;
- alle ESCLUSIONI di sicurezza: gli interruttori «MultiMarket (più mercati)» /
  «MultiSelection (più selezioni)» NON devono essere wrappati, perché le loro label
  raddoppiano da semantica di configurazione (un revert accidentale a i18n.tr le
  romperebbe come chiavi di confronto)."""

import ast
import os
import re
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
_PARSER_SRC = open(os.path.join(_PKG, "custom_parser_gui.py"), encoding="utf-8").read()

# Le chiavi del catalogo che appartengono alla finestra Parser: quelle presenti come
# costante tr() nel sorgente (estratte via AST così le concatenazioni multi-linea
# contano come UNA sola stringa, es. «⛔ Nessun messaggio…»).
_PARSER_TR = set()
for _n in ast.walk(ast.parse(_PARSER_SRC)):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _PARSER_TR.add(_n.args[0].value)

# Chiavi Parser volutamente IDENTICHE in EN (parola inglese): niente entry EN, il
# fallback di tr() le restituisce già (come «■  STOP»). In ES differiscono → entry
# presente. Documentare l'eccezione evita una futura UI mista silenziosa.
_EN_UNIVERSAL = {"Sport:", "➕ Provider"}


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_parser_ha_stringhe_wrappate():
    """Sanity: il sorgente wrappa davvero il suo chrome (non è rimasto tutto IT)."""
    assert len(_PARSER_TR) >= 30
    # nessuna label/titolo/bottone chrome con literal italiano FUORI da i18n.tr
    for probe in ('text="Nome parser:"', 'text="💾 Salva"', 'text="🗑 Rimuovi"',
                  'text="🔗 Traduzioni attive per questo parser"',
                  'self.title("Parser Personalizzato")'):
        assert probe not in _PARSER_SRC, f"stringa chrome non wrappata: {probe}"
    for probe in ('i18n.tr("Nome parser:")', 'i18n.tr("💾 Salva")',
                  'i18n.tr("🗑 Rimuovi")', 'i18n.tr("Messaggio di prova:")',
                  'self.title(i18n.tr("Parser Personalizzato"))'):
        assert probe in _PARSER_SRC, f"wrap atteso mancante: {probe}"


def test_esclusioni_multimarket_multiselection_non_wrappate():
    """GATE DI SICUREZZA: gli interruttori MultiMarket/MultiSelection restano literal
    IT bare (`text="..."`), MAI dentro i18n.tr — le loro label raddoppiano da semantica
    di configurazione. Se un giorno qualcuno le wrappa, QUESTO test fallisce."""
    for bare in ('text="MultiMarket (più mercati)"',
                 'text="MultiSelection (più selezioni)"'):
        assert bare in _PARSER_SRC, f"esclusione persa (non più bare): {bare}"
    for forbidden in ('i18n.tr("MultiMarket (più mercati)")',
                      'i18n.tr("MultiSelection (più selezioni)")'):
        assert forbidden not in _PARSER_SRC, (
            f"ESCLUSIONE VIOLATA: {forbidden} — label di config non deve essere localizzata")
    # E le chiavi NON devono nemmeno essere finite nel catalogo (né IT-source né traduzione).
    for lang in ("EN", "ES"):
        for excl in ("MultiMarket (più mercati)", "MultiSelection (più selezioni)"):
            assert excl not in i18n._CATALOG[lang], f"{lang}: esclusione {excl!r} nel catalogo"


def test_title_provider_resta_bare():
    """`title="Provider"` NON è wrappato: «Provider» è confrontato come `rule.target`
    (chiave di config), quindi non va localizzato (regola: mai wrappare stringhe
    entangled con un confronto)."""
    assert 'title="Provider"' in _PARSER_SRC
    assert 'rule.target == "Provider"' in _PARSER_SRC   # il confronto esiste ancora


def test_ogni_stringa_parser_nel_catalogo_en_ed_es():
    """Copertura EN/ES del chrome wrappato: nessuna stringa Parser resta senza
    traduzione (niente UI mista come #357). Eccezione documentata: le chiavi EN
    universali (`_EN_UNIVERSAL`) sono volutamente OMESSE dal catalogo EN (fallback)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PARSER_TR:
            if lang == "EN" and key in _EN_UNIVERSAL:
                assert key not in table, (
                    f"{key!r} è universale in EN: niente entry ridondante (fallback)")
                continue
            assert key in table, f"{lang}: manca la traduzione Parser per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """I template con {count}/{src}: la traduzione DEVE avere gli stessi segnaposto,
    altrimenti .format(...) darebbe KeyError o lascerebbe testo grezzo."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PARSER_TR:
            if lang == "EN" and key in _EN_UNIVERSAL:
                continue
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_en_ed_es():
    """Il flusso reale: tr(template).format(...) produce testo tradotto e interpolato,
    senza graffe residue. Copre l'indicatore «✓ N attive» e il prompt di duplica."""
    i18n.set_language("EN")
    assert i18n.tr("✓ {count} attive").format(count=3) == "✓ 3 active"
    msg = i18n.tr("Nuovo nome per la copia di {src!r}:").format(src="Bet365")
    assert msg == "New name for the copy of 'Bet365':" and "{" not in msg
    i18n.set_language("ES")
    assert i18n.tr("✓ {count} attive").format(count=2) == "✓ 2 activas"
    assert i18n.tr("💾 Salva") == "💾 Guardar"
    # fallback IT: template invariato, interpolazione comunque corretta
    i18n.set_language("IT")
    assert i18n.tr("✓ {count} attive").format(count=7) == "✓ 7 attive"
    assert i18n.tr("Sport:") == "Sport:"                 # universale/identità in IT


def test_status_text_helper_localizzato(monkeypatch):
    """`_translations_status_text` (helper puro, sorgente della verità dell'indicatore)
    passa da i18n.tr: in EN/ES il testo dell'indicatore è tradotto, non IT bare.

    Il modulo importa customtkinter; qui non serve la GUI, solo la funzione pura, quindi
    si stubba customtkinter come nell'integration test (monkeypatch ripristina sys.modules)."""
    import importlib
    import sys
    import types
    fake = types.ModuleType("customtkinter")
    fake.__getattr__ = lambda _n: object
    monkeypatch.setitem(sys.modules, "customtkinter", fake)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    gui = importlib.import_module("xtrader_bridge.custom_parser_gui")
    i18n.set_language("EN")
    assert gui._translations_status_text(0) == "— none"
    assert gui._translations_status_text(1) == "✓ 1 active"
    assert gui._translations_status_text(4) == "✓ 4 active"
    i18n.set_language("IT")
    assert gui._translations_status_text(0) == "— nessuna"   # identità IT
    assert gui._translations_status_text(2) == "✓ 2 attive"
