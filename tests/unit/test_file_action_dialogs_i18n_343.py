"""Test hard #343 slice 4z: localizzazione dei dialoghi GUI di AZIONE FILE.

Sono i selettori file e gli avvisi/conferme del flusso «Sfoglia/Crea CSV» e «Esporta audit modalità
reale» — codice GUI in app.py (non importabile headless) → si legge via AST e si esercita il catalogo
i18n reale. Fire post `i18n.set_language`, quindi la localizzazione ha effetto (a differenza del dialog
«già in esecuzione» all'avvio, che renderizza PRIMA di set_language e resta IT: escluso e verificato).

Invarianti: nessuna operazione sul CSV o pattern `*.csv` toccati (solo testo dialog); `{path}` è il
percorso file, interpolato come valore via `.format`.
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

# Titoli + label filetype (chiavi brevi single-line).
_SHORT_KEYS = (
    "Scegli il file CSV per XTrader",
    "Crea un nuovo CSV per XTrader (solo header)",
    "Tutti i file",
    "Testo",
    "Bridge avviato",
    "Sovrascrivere il file esistente?",
    "Sovrascrivere il segnale attivo?",
    "Audit modalità reale",
    "Nessun evento di attivazione modalità reale nei log.",
    "Esporta audit modalità reale",
)
# Corpi (concatenati su più righe → l'AST li unisce). {path} nei due body di sovrascrittura.
_BODY_STARTED = "Il bridge è AVVIATO su questo CSV.\n\nFai STOP prima di ricrearlo."
_BODY_OVERWRITE_FILE = ("{path} esiste e NON è un CSV del bridge.\n\nSovrascriverlo con "
                        "un CSV vuoto (solo header)?")
_BODY_OVERWRITE_SIGNAL = ("{path} contiene un segnale attivo non ancora letto da XTrader.\n\n"
                          "Sovrascriverlo con un CSV vuoto (solo header)?")
_BODY_KEYS = (_BODY_STARTED, _BODY_OVERWRITE_FILE, _BODY_OVERWRITE_SIGNAL)
_ALL_KEYS = _SHORT_KEYS + _BODY_KEYS
_PATH_KEYS = (_BODY_OVERWRITE_FILE, _BODY_OVERWRITE_SIGNAL)


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def test_dialoghi_wrappati_in_tr():
    """Tutte le 13 stringhe sono costanti `i18n.tr(...)` in app.py (AST)."""
    for key in _ALL_KEYS:
        assert key in _APP_TR, f"dialog di azione file non wrappato in i18n.tr: {key!r}"
    # nessuna vecchia forma hardcoded / %-interpolata sopravvissuta
    for old in ('title="Scegli il file CSV per XTrader"',
                'title="Crea un nuovo CSV per XTrader (solo header)"',
                '"Bridge avviato",', 'title="Esporta audit modalità reale"',
                '"Audit modalità reale",'):
        assert old not in _APP_SRC, f"stringa dialog non wrappata sopravvissuta: {old}"
    assert '" % dest' not in _APP_SRC, "interpolazione %-style non convertita in .format"


def test_body_sovrascrittura_usano_format_path():
    """Mutation-guard AST: i due corpi con `{path}` passano da `.format(path=...)` (togliere il
    `.format` o l'arg → `{path}` resterebbe letterale nel dialog)."""
    trovati = set()
    for node in ast.walk(_APP_AST):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"):
            tr = node.func.value
            if (isinstance(tr, ast.Call) and isinstance(tr.func, ast.Attribute)
                    and tr.func.attr == "tr" and tr.args
                    and isinstance(tr.args[0], ast.Constant)
                    and tr.args[0].value in _PATH_KEYS):
                kwargs = {kw.arg for kw in node.keywords if kw.arg}
                assert "path" in kwargs, f"path non passato a .format per {tr.args[0].value!r}"
                trovati.add(tr.args[0].value)
    assert trovati == set(_PATH_KEYS), f"corpi con .format(path) mancanti: {set(_PATH_KEYS) - trovati}"


def test_tutte_le_chiavi_nel_catalogo_en_es():
    """Le 13 chiavi sono a catalogo EN/ES, traduzione != IT, placeholder {path} conservato."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _ALL_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"
            assert _placeholders(table[key]) == _placeholders(key), (
                f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_early_lock_dialog_resta_it_escluso():
    """Il dialog «già in esecuzione» all'avvio renderizza PRIMA di `set_language` (l'acquisizione
    del lock precede `i18n.set_language` in __init__) → resta IT e NON è a catalogo: localizzarlo
    non avrebbe effetto e mascherebbe la scelta di escluderlo."""
    assert "XTrader Bridge è già in esecuzione." in _APP_SRC   # ancora presente, hardcoded IT
    for lang in ("EN", "ES"):
        assert "XTrader Bridge è già in esecuzione." not in i18n._CATALOG[lang]


def test_round_trip_en_es():
    """Flusso reale di traduzione in EN/ES (incl. body con {path}) + fallback IT identità."""
    i18n.set_language("EN")
    assert i18n.tr("Bridge avviato") == "Bridge started"
    assert i18n.tr("Tutti i file") == "All files"
    assert i18n.tr(_BODY_OVERWRITE_SIGNAL).format(path="/x/a.csv") == (
        "/x/a.csv contains an active signal not yet read by XTrader.\n\n"
        "Overwrite it with an empty CSV (header only)?")
    i18n.set_language("ES")
    assert i18n.tr("Sovrascrivere il file esistente?") == "¿Sobrescribir el archivo existente?"
    assert i18n.tr("Testo") == "Texto"
    assert i18n.tr(_BODY_OVERWRITE_FILE).format(path="/x/a.csv").startswith(
        "/x/a.csv existe y NO es un CSV del bridge.")
    # fallback IT: identità (nessuna regressione per gli utenti italiani)
    i18n.set_language("IT")
    assert i18n.tr("Bridge avviato") == "Bridge avviato"
    assert i18n.tr(_BODY_STARTED) == _BODY_STARTED
