"""Test hard #343 slice 4i: localizzazione della finestra Mapping (Dizionario nomi + mercati).

Puri e headless (non si costruisce la GUI: `name_mapping_gui` importa customtkinter). Si
verifica il catalogo i18n e il wrapping nel sorgente, con attenzione:
- alle etichette colonna (tuple `_HEADER_COLUMNS`/`_MARKET_HEADER_COLUMNS`, rese via
  `i18n.tr(text)`): sono chiavi del catalogo tanto quanto le stringhe wrappate direttamente;
- ai molti messaggi TEMPLATE ({name}/{old}/{new}/{count}/{names}/{exc}/{kind}/{added}/
  {skipped}/{n}): la traduzione deve conservare gli stessi segnaposto, altrimenti `.format(...)`
  esploderebbe a runtime;
- alle ESCLUSIONI value-as-key che NON devono essere wrappate (restano IT perché usate in
  confronti di uguaglianza / chiavi di config): le sentinelle delle tendine
  (`_SPORT_ALL`/`_ENTITY_ALL`/`_LANGUAGE_ALL`/`_NO_PROFILE`) e i tab del container.
"""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "name_mapping_gui.py"), encoding="utf-8") as _fh:
    _MAP_SRC = _fh.read()
_MAP_TREE = ast.parse(_MAP_SRC)

# Chiavi wrappate come costante di `i18n.tr(...)` (AST unisce le concatenazioni multi-linea).
_MAP_TR = set()
for _n in ast.walk(_MAP_TREE):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _MAP_TR.add(_n.args[0].value)

# Etichette colonna: literal delle tuple `_HEADER_COLUMNS`/`_MARKET_HEADER_COLUMNS`
# (rese via `i18n.tr(text)` sull'elemento indicizzato) + la costante `_CHANNEL_ALIAS_COLUMN`.
_MAP_HEADERS = set()
for _n in ast.walk(_MAP_TREE):
    if isinstance(_n, ast.Assign):
        _tid = {getattr(t, "id", None) for t in _n.targets}
        if _tid & {"_HEADER_COLUMNS", "_MARKET_HEADER_COLUMNS"}:
            for _el in _n.value.elts:
                _lab = _el.elts[0]
                if isinstance(_lab, ast.Constant) and isinstance(_lab.value, str):
                    _MAP_HEADERS.add(_lab.value)
        if "_CHANNEL_ALIAS_COLUMN" in _tid and isinstance(_n.value, ast.Constant):
            _MAP_HEADERS.add(_n.value.value)

_MAP_KEYS = _MAP_TR | _MAP_HEADERS


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_mapping_ha_stringhe_wrappate():
    """Sanity: il sorgente wrappa titoli/colonne/pulsanti/status (non è rimasto tutto IT)."""
    assert len(_MAP_TR) >= 40, len(_MAP_TR)
    assert len(_MAP_HEADERS) >= 10, _MAP_HEADERS
    for probe in ('i18n.tr("🗺️  Dizionario nomi squadra")', 'i18n.tr("🎯  Dizionario mercati")',
                  'i18n.tr("💾 Salva profilo")', 'text=i18n.tr(text)',
                  'self.title(i18n.tr("Dizionario nomi squadra"))'):
        assert probe in _MAP_SRC, f"wrap atteso mancante: {probe}"
    # titoli/label NON devono restare hardcoded fuori da i18n.tr
    for probe in ('text="🗺️  Dizionario nomi squadra"', 'text="💾 Salva profilo"',
                  'self.title("Dizionario mercati")'):
        assert probe not in _MAP_SRC, f"stringa non wrappata: {probe}"


def test_ogni_stringa_mapping_e_nel_catalogo_en_ed_es():
    """Copertura piena EN/ES: nessuna stringa chrome del Mapping resta in italiano (niente UI
    mista). Include le etichette colonna oltre alle stringhe wrappate direttamente."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _MAP_KEYS:
            assert key in table, f"{lang}: manca la traduzione Mapping per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Ogni template ({name}/{old}/{new}/{count}/{names}/{exc}/{kind}/{added}/{skipped}/{n})
    deve avere gli stessi segnaposto in EN/ES, altrimenti `.format(...)` darebbe KeyError."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _MAP_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_status_mapping():
    """Flusso reale dei messaggi di stato: tr(template).format(...) → testo tradotto e
    interpolato, senza graffe residue."""
    i18n.set_language("EN")
    msg = i18n.tr("💾 Profilo «{name}» salvato ({n} righe valide).").format(name="Prematch", n=3)
    assert msg == "💾 Profile «Prematch» saved (3 valid rows)." and "{" not in msg
    msg = i18n.tr("🗑 Profilo «{name}» eliminato.").format(name="Prematch")
    assert msg == "🗑 Profile «Prematch» deleted."
    i18n.set_language("ES")
    msg = i18n.tr("✏️ Profilo rinominato «{old}» → «{new}».").format(old="A", new="B")
    assert msg == "✏️ Perfil renombrado «A» → «B»."
    # fallback IT: template invariato, interpolazione corretta
    i18n.set_language("IT")
    msg = i18n.tr("🆕 Profilo «{name}» creato.").format(name="X")
    assert msg == "🆕 Profilo «X» creato."


def test_esclusioni_value_as_key_non_wrappate():
    """Le sentinelle delle tendine e i tab del container sono value-as-key (usati in confronti
    di uguaglianza / chiavi di matching): DEVONO restare IT, mai wrappati né a catalogo (un
    wrap qui romperebbe `_label_to_sport`/`_label_to_language`/il ritrovamento del tab)."""
    for sentinel in ('_SPORT_ALL = "(tutti gli sport)"', '_ENTITY_ALL = "(qualsiasi tipo)"',
                     '_LANGUAGE_ALL = "(tutte le lingue)"', '_NO_PROFILE = "(nessun profilo)"'):
        assert sentinel in _MAP_SRC, f"sentinella cambiata: {sentinel}"
    # mai wrappate in i18n.tr
    for bad in ('i18n.tr(_SPORT_ALL', 'i18n.tr(_LANGUAGE_ALL', 'i18n.tr(_NO_PROFILE',
                'i18n.tr("(tutti gli sport)")', 'i18n.tr("(tutte le lingue)")'):
        assert bad not in _MAP_SRC, f"sentinella wrappata per errore: {bad}"
    # i tab del container restano IT (chiavi di matching + pannello guidato non localizzato)
    for tab in ('self._tabs.add("⚽ Calcio")', 'self._tabs.add("🎯 Mercati")',
                'self._tabs.add("🌳 Mapping guidato")'):
        assert tab in _MAP_SRC, f"tab container modificato (dovrebbe restare IT): {tab}"
    # le sentinelle non sono chiavi di catalogo (non tradotte)
    for lang in ("EN", "ES"):
        for sent in ("(tutti gli sport)", "(qualsiasi tipo)", "(tutte le lingue)", "(nessun profilo)"):
            assert sent not in i18n._CATALOG[lang], f"{lang}: sentinella a catalogo per errore: {sent!r}"
