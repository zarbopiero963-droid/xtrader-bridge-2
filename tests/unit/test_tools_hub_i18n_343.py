"""Test hard #343 slice 4x: localizzazione dell'hub «🧰 Strumenti» (`tools_gui`).

Il modulo è codice widget (importa `customtkinter` → non importabile headless senza stub): qui si
legge il sorgente via AST e si esercita il catalogo i18n reale. La slice localizza:
- il TITOLO della finestra (`ToolsWindow.__init__`, default `title="🧰 Strumenti"`);
- i TITOLI-SCHEDA (etichetta base in `TOOL_TITLES`, resa in `build_tool_panels`; il prefisso di
  gruppo ①..④ resta invariato);
- la LABEL D'ERRORE per-scheda (`i18n.tr("⚠️ Impossibile aprire questo strumento:\n{exc}")`).

Invarianti verificate:
- la resa è a BUILD-TIME, non a livello di modulo (un `i18n.tr` all'import congelerebbe la lingua IT);
- `TOOL_TITLES` resta IT canonico (sono chiavi di catalogo, non traduzioni);
- la label d'errore passa da `i18n.tr(...).format(exc=...)` (segnaposto {exc} coperto);
- copertura EN/ES != IT su tutte le 11 chiavi nuove; «Provider»/«Parser» = termini prodotto invariati;
- round-trip reale tr()/tr().format().
"""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "tools_gui.py"), encoding="utf-8") as _fh:
    _TG_SRC = _fh.read()
_TG_AST = ast.parse(_TG_SRC)

_TG_TR = set()
for _n in ast.walk(_TG_AST):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _TG_TR.add(_n.args[0].value)

# Etichette base delle schede (valori di TOOL_TITLES) + titolo finestra + label d'errore.
_TAB_TITLES = (
    "📡 Chat sorgenti",
    "📇 Provider",
    "🧩 Parser",
    "🗺️ Mapping",
    "📖 Dizionario",
    "📒 Diario",
    "🧹 Nomi squadra",
    "📁 Profili",
    "📋 Riepilogo",
)
_WINDOW_TITLE = "🧰 Strumenti"
_ERROR_LABEL = "⚠️ Impossibile aprire questo strumento:\n{exc}"
_ALL_KEYS = _TAB_TITLES + (_WINDOW_TITLE, _ERROR_LABEL)


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def test_tool_titles_restano_it_canonici():
    """`TOOL_TITLES` NON deve essere localizzato a livello di modulo: i valori sono chiavi di
    catalogo IT canoniche (la traduzione avviene a build-time). Un `i18n.tr(...)` dentro il literal
    del dict congelerebbe la lingua all'import → regressione."""
    # AST: il dict `TOOL_TITLES` ha SOLO valori Constant (nessuna Call i18n.tr al suo interno).
    dict_node = None
    for node in ast.walk(_TG_AST):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "TOOL_TITLES" for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            dict_node = node.value
    assert dict_node is not None, "TOOL_TITLES non trovato come dict-literal"
    for v in dict_node.values:
        assert isinstance(v, ast.Constant) and isinstance(v.value, str), (
            "un valore di TOOL_TITLES non è un literal IT: localizzazione a import-time vietata")
    # tutti i titoli-scheda attesi sono presenti verbatim
    valori = {v.value for v in dict_node.values}
    for t in _TAB_TITLES:
        assert t in valori, f"titolo-scheda mancante da TOOL_TITLES: {t!r}"


def test_localizzazione_a_build_time():
    """La resa localizzata avviene a build-time: `build_tool_panels` wrappa il titolo-scheda e
    `__init__` wrappa il titolo finestra. Anti-regressione sul wiring reale (via sorgente)."""
    assert "f\"{prefix} {i18n.tr(TOOL_TITLES[key])}\"" in _TG_SRC, (
        "build_tool_panels non localizza il titolo-scheda via i18n.tr a build-time")
    assert "self.title(i18n.tr(title))" in _TG_SRC, (
        "ToolsWindow.__init__ non localizza il titolo finestra via i18n.tr")
    # il vecchio titolo NON wrappato non deve sopravvivere
    assert "self.title(title)" not in _TG_SRC
    assert 'f"{prefix} {TOOL_TITLES[key]}"' not in _TG_SRC


def test_error_label_wrappata_e_formattata():
    """La label d'errore per-scheda è una costante `i18n.tr(...)` formattata con `{exc}` (AST):
    togliere il wrap o il `.format` è una regressione (in EN/ES resterebbe IT / crasherebbe)."""
    assert _ERROR_LABEL in _TG_TR, "label d'errore non wrappata in i18n.tr"
    # la vecchia f-string non wrappata non deve sopravvivere
    assert 'text=f"⚠️ Impossibile aprire questo strumento:\\n{exc}"' not in _TG_SRC
    # cerca il .format(exc=...) sull'esatta tr-constant
    trovato = False
    for node in ast.walk(_TG_AST):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"):
            tr = node.func.value
            if (isinstance(tr, ast.Call) and isinstance(tr.func, ast.Attribute)
                    and tr.func.attr == "tr" and tr.args
                    and isinstance(tr.args[0], ast.Constant)
                    and tr.args[0].value == _ERROR_LABEL):
                kwargs = {kw.arg for kw in node.keywords if kw.arg}
                assert _placeholders(_ERROR_LABEL) <= kwargs, (
                    f".format non copre {_placeholders(_ERROR_LABEL)} per la label d'errore")
                trovato = True
    assert trovato, "label d'errore non passata da .format(exc=...)"


# Coppie (lingua, chiave) in cui la traduzione è LEGITTIMAMENTE identica all'IT: termine prodotto
# invariato («Parser» in EN e ES, «Provider» in EN → in ES «Proveedor»), parola inglese che
# coincide con l'italiano («Mapping» in EN → in ES «Mapeo»), o parola condivisa IT/ES («Diario»
# in ES → in EN «Journal»).
_IDENTICO_OK = {("EN", "🧩 Parser"), ("ES", "🧩 Parser"),
                ("EN", "📇 Provider"), ("EN", "🗺️ Mapping"), ("ES", "📒 Diario")}


def test_tutte_le_chiavi_nel_catalogo_en_es():
    """Le 11 chiavi nuove (9 titoli-scheda + titolo finestra + label d'errore) sono a catalogo
    EN/ES con segnaposto conservati e traduzione != IT (salvo i termini prodotto invariati)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _ALL_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            if (lang, key) not in _IDENTICO_OK:
                assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"
            assert _placeholders(table[key]) == _placeholders(key), (
                f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_termini_prodotto_invariati():
    """«Provider» e «Parser» sono termini prodotto: invariati in EN/ES (solo l'icona resta)."""
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        assert i18n.tr("🧩 Parser") == "🧩 Parser", lang
    assert i18n._CATALOG["EN"]["📇 Provider"] == "📇 Provider"
    assert i18n._CATALOG["ES"]["📇 Provider"] == "📇 Proveedor"   # ES traduce «Provider»


def test_round_trip_en_es():
    """Flusso reale di traduzione dei titoli e della label d'errore in EN/ES + fallback IT."""
    i18n.set_language("EN")
    assert i18n.tr("🧰 Strumenti") == "🧰 Tools"
    assert i18n.tr("📖 Dizionario") == "📖 Dictionary"
    assert i18n.tr("📒 Diario") == "📒 Journal"
    assert i18n.tr("⚠️ Impossibile aprire questo strumento:\n{exc}").format(exc="boom") == (
        "⚠️ Unable to open this tool:\nboom")
    i18n.set_language("ES")
    assert i18n.tr("🧰 Strumenti") == "🧰 Herramientas"
    assert i18n.tr("🗺️ Mapping") == "🗺️ Mapeo"
    assert i18n.tr("🧹 Nomi squadra") == "🧹 Nombres de equipo"
    assert i18n.tr("⚠️ Impossibile aprire questo strumento:\n{exc}").format(exc="boom") == (
        "⚠️ No se puede abrir esta herramienta:\nboom")
    # fallback IT: identità (nessuna regressione per gli utenti italiani)
    i18n.set_language("IT")
    assert i18n.tr("🧰 Strumenti") == "🧰 Strumenti"
    assert i18n.tr("📋 Riepilogo") == "📋 Riepilogo"
