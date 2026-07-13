"""Test hard #343 slice 4v+4w: localizzazione del pannello «🌳 Mapping guidato».

Il pannello (`guided_mapping_gui`) è codice widget (customtkinter → non importabile headless): si
legge il sorgente via AST e si esercita il catalogo i18n reale. La 4v ha localizzato la CHROME statica
(titolo/label/filtro/intestazioni/bottoni/placeholder/dialog); la **4w** localizza i **MESSAGGI DI
STATO dinamici** (esiti profilo/competizioni/squadre/salvataggio, con `{exc}`/`{name}`/`{sport}`/
conteggi). Verifica:
- ogni stringa (chrome + status) è una costante `i18n.tr(...)` nel sorgente (AST);
- i log dinamici chiamano `.format(...)` coprendo TUTTI i segnaposto (mutation-guard AST);
- copertura EN/ES **!= IT**; conservazione segnaposto; round-trip reale;
- ESCLUSIONE value-as-key: i segnaposto «(nessun profilo)»/«(scegli lo sport)» restano IT, non
  wrappati, non a catalogo.
"""

import ast
import os
import string

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


# Messaggi di STATO dinamici localizzati nella slice 4w (esclusa «⏳ Dizionario occupato: riprova
# tra poco.» — già a catalogo dalla slice 4t, qui solo wrappata).
_STATUS_KEYS = (
    "❌ Config illeggibile: {exc}",
    "⛔ Profilo non creato (nome vuoto).",
    "ℹ️ Il profilo «{name}» esiste già.",
    "🆕 Profilo «{name}» creato.",
    "❌ Salvataggio FALLITO: «{name}» non creato.",
    "ℹ️ Nessuna competizione per «{sport}». Popola il dizionario locale, poi riprova.",
    "ℹ️ Nessuna squadra per questa competizione (nessun evento nel dizionario). Popola il dizionario locale, poi riprova.",
    "{count} squadre. Scrivi l'alias del canale e premi «Salva nel profilo».",
    "… mostrate {shown} di {total} squadre: usa «Filtra» per restringere (gli alias già scritti restano salvati anche se non visibili).",
    "⛔ Nessun profilo selezionato: crea o scegli un profilo di destinazione.",
    "⛔ Nessuna squadra caricata da salvare.",
    "💾 Salvato nel profilo «{profile}»: {written} squadre mappate in questa competizione ({total} righe totali nel profilo).",
    "❌ Salvataggio FALLITO: «{profile}» non salvato (andrebbe perso al riavvio). Controlla permessi/spazio del file config.",
)


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _tr_format_calls():
    """(template, {kwargs}) per ogni `i18n.tr("…").format(**kwargs)` nel sorgente (AST)."""
    out = []
    for node in ast.walk(_GM_AST):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"):
            continue
        tr = node.func.value
        if not (isinstance(tr, ast.Call) and isinstance(tr.func, ast.Attribute)
                and tr.func.attr == "tr" and tr.args
                and isinstance(tr.args[0], ast.Constant) and isinstance(tr.args[0].value, str)):
            continue
        out.append((tr.args[0].value, {kw.arg for kw in node.keywords if kw.arg}))
    return out


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


def test_status_messages_wrappati():
    """Slice 4w: ogni messaggio di stato è una costante `i18n.tr(...)` e nessuno resta f-string.
    «⏳ Dizionario occupato: riprova tra poco.» (già a catalogo, 4t) è comunque wrappato qui."""
    for key in _STATUS_KEYS:
        assert key in _GM_TR, f"messaggio di stato non wrappato in i18n.tr: {key!r}"
    assert "⏳ Dizionario occupato: riprova tra poco." in _GM_TR
    # nessun vecchio status f-string sopravvissuto
    for old in ('text=f"❌ Config illeggibile: {exc}"', 'text=f"🆕 Profilo «{name}» creato."',
                'text=f"{len(teams)} squadre. Scrivi',
                'text=f"💾 Salvato nel profilo'):
        assert old not in _GM_SRC, f"status f-string non wrappato sopravvissuto: {old}"


def test_status_dinamici_chiamano_format():
    """Mutation-guard AST: i template con segnaposto passano da `.format(...)` coprendo TUTTI i
    segnaposto (togliere `.format`/un kwarg → fallisce)."""
    calls = _tr_format_calls()
    dinamici = {t for t, _ in calls if _placeholders(t)}
    for key in _STATUS_KEYS:
        if _placeholders(key):
            assert key in dinamici, f"template di stato non formattato: {key!r}"
    for template, kwargs in calls:
        attesi = _placeholders(template)
        if attesi:
            assert attesi <= kwargs, (
                f".format non copre i segnaposto di {template!r}: mancano {attesi - kwargs}")


def test_status_nel_catalogo_en_es():
    """Copertura piena EN/ES con traduzione != IT + segnaposto conservati."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _STATUS_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"
            assert _placeholders(table[key]) == _placeholders(key), (
                f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_round_trip_status():
    """Flusso reale tr(template).format(...) sui messaggi di stato in EN/ES."""
    i18n.set_language("EN")
    assert i18n.tr("🆕 Profilo «{name}» creato.").format(name="Serie A") == (
        "🆕 Profile «Serie A» created.")
    assert i18n.tr("{count} squadre. Scrivi l'alias del canale e premi «Salva nel profilo».").format(
        count=5) == "5 teams. Type the channel alias and press «Save to profile»."
    i18n.set_language("ES")
    assert i18n.tr("⛔ Nessuna squadra caricata da salvare.") == (
        "⛔ Ningún equipo cargado para guardar.")
    assert i18n.tr("💾 Salvato nel profilo «{profile}»: {written} squadre mappate in questa competizione ({total} righe totali nel profilo).").format(
        profile="P1", written=3, total=10).startswith("💾 Guardado en el perfil «P1»: 3 equipos")
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("⛔ Nessuna squadra caricata da salvare.") == "⛔ Nessuna squadra caricata da salvare."


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
