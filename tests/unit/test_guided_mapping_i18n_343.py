"""Test hard #343 slice 4v: localizzazione della CHROME del pannello «🌳 Mapping guidato».

Il pannello (`guided_mapping_gui`) è codice widget (customtkinter → non importabile headless): si
legge il sorgente via AST e si esercita il catalogo i18n reale. Questa slice localizza SOLO la chrome
statica (titolo/descrizione, label di riga, filtro, intestazioni colonne, bottoni, placeholder,
dialog «Nuovo profilo»); i MESSAGGI DI STATO dinamici sono rimandati alla slice 4w. Verifica:
- ogni stringa chrome è una costante `i18n.tr(...)` nel sorgente (AST);
- copertura EN/ES **!= IT** per le chiavi NUOVE della slice;
- ESCLUSIONE value-as-key: i segnaposto «(nessun profilo)»/«(scegli lo sport)» restano IT, non
  wrappati, non a catalogo;
- SCOPING: i messaggi di stato dinamici restano f-string IT NON wrappate (arrivano con 4w).
"""

import ast
import os

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "guided_mapping_gui.py"), encoding="utf-8") as _fh:
    _GM_SRC = _fh.read()
_GM_AST = ast.parse(_GM_SRC)

_GM_TR = set()
for _n in ast.walk(_GM_AST):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _GM_TR.add(_n.args[0].value)

# Tutta la chrome statica wrappata in questa slice (17 stringhe).
_CHROME_KEYS = (
    "🌳  Mapping guidato (Betfair → nome canale)",
    "Scegli Sport → Competizione: compaiono le squadre dai dati Betfair presenti nel dizionario. Accanto a ogni squadra scrivi «come la chiama il canale» e salva nel profilo. Serve un dizionario locale popolato.",
    "Profilo:",
    "🆕 Nuovo",
    "Sport:",
    "Competizione:",
    "Filtra squadre:",
    "parte del nome squadra…",
    "Pulisci",
    "Squadra Betfair",
    "Come la chiama il canale",
    "Squadre",
    "💾 Salva nel profilo",
    "Scegli Sport e Competizione per vedere le squadre.",
    "come la chiama il canale…",
    "Nome del nuovo profilo:",
    "Nuovo profilo",
)

# Chiavi NUOVE a catalogo in questa slice (le altre — Profilo:/🆕 Nuovo/Sport:/Nome del nuovo
# profilo:/Nuovo profilo — sono già a catalogo da pannelli precedenti; «Sport:» è ES-only, EN identità).
_NEW_KEYS = (
    "🌳  Mapping guidato (Betfair → nome canale)",
    "Scegli Sport → Competizione: compaiono le squadre dai dati Betfair presenti nel dizionario. Accanto a ogni squadra scrivi «come la chiama il canale» e salva nel profilo. Serve un dizionario locale popolato.",
    "Competizione:",
    "Filtra squadre:",
    "parte del nome squadra…",
    "Pulisci",
    "Squadra Betfair",
    "Come la chiama il canale",
    "Squadre",
    "💾 Salva nel profilo",
    "Scegli Sport e Competizione per vedere le squadre.",
    "come la chiama il canale…",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def test_chrome_wrappata_in_tr():
    """Ogni stringa chrome è una costante `i18n.tr(...)` nel sorgente (AST)."""
    for key in _CHROME_KEYS:
        assert key in _GM_TR, f"chrome del Mapping guidato non wrappata in i18n.tr: {key!r}"
    for old in ('text="🌳  Mapping guidato', 'text="Profilo:"', 'text="🆕 Nuovo"',
                'text="💾 Salva nel profilo"', 'placeholder_text="come la chiama il canale…"',
                'title="Nuovo profilo"'):
        assert old not in _GM_SRC, f"stringa chrome non wrappata sopravvissuta: {old}"


def test_new_keys_nel_catalogo_en_es():
    """Le chiavi NUOVE della slice sono a catalogo EN/ES con traduzione != IT."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _NEW_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"


def test_sentinel_value_as_key_restano_it():
    """«(nessun profilo)» e «(scegli lo sport)» sono value-as-key: restano IT, non wrappati, non a
    catalogo (localizzarli romperebbe confronto/segnaposto)."""
    assert '_NO_PROFILE = "(nessun profilo)"' in _GM_SRC
    assert '_NO_COMP = "(scegli lo sport)"' in _GM_SRC
    for bad in ('i18n.tr(_NO_PROFILE', 'i18n.tr("(nessun profilo)")',
                'i18n.tr(_NO_COMP', 'i18n.tr("(scegli lo sport)")'):
        assert bad not in _GM_SRC, f"sentinel value-as-key wrappato per errore: {bad}"
    for lang in ("EN", "ES"):
        assert "(nessun profilo)" not in i18n._CATALOG[lang]
        assert "(scegli lo sport)" not in i18n._CATALOG[lang]


def test_status_messages_rimandati_a_4w():
    """SCOPING: i messaggi di stato dinamici restano f-string IT NON wrappate in questa slice."""
    for status in ('text=f"❌ Config illeggibile: {exc}"',
                   'text=f"🆕 Profilo «{name}» creato."',
                   'text=f"{len(teams)} squadre. Scrivi'):
        assert status in _GM_SRC, f"status message atteso ancora f-string in 4v: {status}"
    # non devono essere già passati da i18n.tr (quello è lavoro della 4w)
    assert 'i18n.tr("❌ Config illeggibile' not in _GM_SRC
    assert 'i18n.tr("⛔ Nessun profilo selezionato' not in _GM_SRC


def test_round_trip_chrome():
    """Flusso reale di traduzione della chrome in EN/ES; «Betfair» resta invariato."""
    i18n.set_language("EN")
    assert i18n.tr("💾 Salva nel profilo") == "💾 Save to profile"
    assert i18n.tr("Squadra Betfair") == "Betfair team"
    assert i18n.tr("Pulisci") == "Clear"
    i18n.set_language("ES")
    assert i18n.tr("Competizione:") == "Competición:"
    assert i18n.tr("Squadre") == "Equipos"
    assert i18n.tr("🌳  Mapping guidato (Betfair → nome canale)") == (
        "🌳  Mapeo guiado (Betfair → nombre del canal)")
    # fallback IT: identità
    i18n.set_language("IT")
    assert i18n.tr("Pulisci") == "Pulisci"
    # marker/prodotto: «Betfair» presente in tutte le lingue della chiave header
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        assert "Betfair" in i18n.tr("Squadra Betfair")
