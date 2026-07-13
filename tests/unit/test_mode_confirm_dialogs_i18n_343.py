"""Test hard #343 slice 4y: localizzazione dei dialoghi di CONFERMA MODALITÀ.

Sono i gate «frictionful» che precedono la scrittura di scommesse — REALE (frase da digitare),
COLLAUDO (sì/no), MULTI-segnale (sì/no) e i due gate autostart/START in modalità reale. Il testo è
codice GUI (app.py, non importabile headless) → si legge via AST; la logica pura (`multi_signal`,
`real_mode`, `bridge_mode`) è importabile e si esercita davvero.

Invariante SAFETY centrale: la frase da digitare per confermare la modalità reale resta
`real_mode.CONFIRM_PHRASE` = «REALE» in OGNI lingua (interpolata come valore, mai localizzata), perché
`real_mode.confirmation_ok` la confronta letteralmente. Localizzarla romperebbe il gate anti-scommessa.
"""

import ast
import os
import string

import pytest

from xtrader_bridge import bridge_mode, i18n, multi_signal, real_mode

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")


def _read(name):
    with open(os.path.join(_PKG, name), encoding="utf-8") as fh:
        return fh.read()


_APP_SRC = _read("app.py")
_MS_SRC = _read("multi_signal.py")


def _tr_constants(src) -> set:
    """Stringhe COSTANTI passate come primo arg a `i18n.tr(...)` (AST unisce i literal adiacenti)."""
    found = set()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tr" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


_APP_TR = _tr_constants(_APP_SRC)
_MS_TR = _tr_constants(_MS_SRC)

# Titoli + corpi resi come `i18n.tr("literal")` in app.py.
_APP_KEYS = (
    "Conferma MODALITÀ REALE",
    "ATTENZIONE: stai per attivare la MODALITÀ REALE.\n"
    "XTrader potrà piazzare scommesse REALI.\n\n"
    "Per confermare digita:  {phrase}",
    "Conferma MODALITÀ COLLAUDO",
    "Conferma modalità MULTI-segnale",
    "Avvio automatico — MODALITÀ REALE",
    "L'avvio automatico è attivo in MODALITÀ REALE: il bridge "
    "inizierà a scrivere i segnali nel CSV (scommesse reali) "
    "appena ricevuti.\n\nAvviare ora il listener?",
    "START — MODALITÀ REALE",
    "Sei in MODALITÀ REALE: il bridge scriverà i segnali nel CSV "
    "(scommesse reali) appena ricevuti.\n\nAvviare ora il listener?",
)
# Corpo COLLAUDO = costante pure-layer resa via i18n.tr(variabile).
_COLLAUDO_KEY = bridge_mode.COLLAUDO_CONFIRM_TEXT
# Corpo MULTI = template tr-constant dentro multi_signal.warning_text.
_MULTI_KEY = ("Stai attivando una modalità coda MULTI-segnale: nel CSV potranno esserci PIÙ "
              "righe attive contemporaneamente, quindi XTrader può piazzare PIÙ scommesse "
              "simultanee (tetto attuale: {max_active} righe attive). Confermi?")
_ALL_KEYS = _APP_KEYS + (_COLLAUDO_KEY, _MULTI_KEY)


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def test_titoli_e_corpi_app_wrappati_in_tr():
    """I 5 titoli + 3 corpi (REALE/autostart) sono costanti `i18n.tr(...)` in app.py (AST)."""
    for key in _APP_KEYS:
        assert key in _APP_TR, f"dialog di conferma non wrappato in i18n.tr in app.py: {key!r}"
    # wrap POSITIVO verbatim nel sorgente (un revert del wrap li farebbe tornare hardcoded solo-IT)
    for wrapped in ('title=i18n.tr("Conferma MODALITÀ REALE")',
                    'i18n.tr("Conferma MODALITÀ COLLAUDO"),',
                    'i18n.tr("Conferma modalità MULTI-segnale"),',
                    'i18n.tr("Avvio automatico — MODALITÀ REALE")',
                    'i18n.tr("START — MODALITÀ REALE")'):
        assert wrapped in _APP_SRC, f"wrap mancante in app.py: {wrapped}"
    # la vecchia forma kwarg NON wrappata del dialog reale non deve sopravvivere
    assert 'title="Conferma MODALITÀ REALE"' not in _APP_SRC


def test_collaudo_confirm_reso_via_tr_costante():
    """Il corpo COLLAUDO passa da `i18n.tr(bridge_mode.COLLAUDO_CONFIRM_TEXT)` (costante pure-layer)."""
    assert "i18n.tr(bridge_mode.COLLAUDO_CONFIRM_TEXT)" in _APP_SRC


def test_multi_warning_localizzato_dentro_multi_signal():
    """`multi_signal.warning_text` è localizzata: template tr-constant + `.format(max_active=...)`."""
    assert _MULTI_KEY in _MS_TR, "warning_text non wrappata in i18n.tr in multi_signal.py"
    assert ".format(max_active=max_active)" in _MS_SRC
    # nessuna vecchia f-string non wrappata
    assert 'f"simultanee (tetto attuale: {max_active}' not in _MS_SRC


def test_tutte_le_chiavi_nel_catalogo_en_es():
    """Le 10 chiavi (5 titoli + 5 corpi) sono a catalogo EN/ES, traduzione != IT, placeholder uguali."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _ALL_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"
            assert table[key] != key, f"{lang}: traduzione IDENTICA all'italiano per {key!r}"
            assert _placeholders(table[key]) == _placeholders(key), (
                f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_safety_frase_conferma_reale_resta_it_in_ogni_lingua():
    """SAFETY: la frase da digitare resta «REALE» in IT/EN/ES (value-as-key), e `confirmation_ok`
    accetta «REALE» e rifiuta le traduzioni — il gate anti-scommessa non si indebolisce localizzando."""
    assert real_mode.CONFIRM_PHRASE == "REALE"
    # La sicurezza NON dipende dall'assenza di «REALE» dal catalogo (esiste come chiave del
    # nome-modalità nei log, slice 4s → «REAL»): dipende dal fatto che il dialog interpola la
    # frase come VALORE `.format(phrase=real_mode.CONFIRM_PHRASE)`, mai passandola da `i18n.tr`.
    # Quindi la frase mostrata resta «REALE» qualunque sia la lingua.
    template = _APP_KEYS[1]
    for lang in ("IT", "EN", "ES"):
        i18n.set_language(lang)
        rendered = i18n.tr(template).format(phrase=real_mode.CONFIRM_PHRASE)
        assert "REALE" in rendered, f"{lang}: la frase da digitare «REALE» sparita dal dialog reale"
    # il gate logico è invariato: accetta REALE (anche tradotto il contorno), rifiuta le traduzioni
    assert real_mode.confirmation_ok("REALE") is True
    assert real_mode.confirmation_ok("REAL") is False
    assert real_mode.confirmation_ok("real") is False


def test_round_trip_multi_signal_funzione_reale():
    """Esercita la funzione REALE `multi_signal.warning_text` in IT/EN/ES: il tetto è interpolato e
    «MULTI» resta visibile in ogni lingua (severità preservata)."""
    i18n.set_language("IT")
    it = multi_signal.warning_text(2)
    assert "2" in it and "MULTI" in it.upper() and "Confermi?" in it
    i18n.set_language("EN")
    en = multi_signal.warning_text(3)
    assert "3" in en and "MULTI" in en.upper() and "Confirm?" in en
    assert en != it
    i18n.set_language("ES")
    es = multi_signal.warning_text(5)
    assert "5" in es and "MULTI" in es.upper() and "¿Confirmar?" in es


def test_round_trip_corpi_conferma_en_es():
    """Round-trip dei corpi COLLAUDO/autostart in EN/ES + fallback IT (identità)."""
    i18n.set_language("EN")
    assert i18n.tr(bridge_mode.COLLAUDO_CONFIRM_TEXT).startswith("You are enabling XTRADER TEST MODE")
    assert "real bets" in i18n.tr(_APP_KEYS[5])              # autostart auto body
    assert i18n.tr("START — MODALITÀ REALE") == "START — REAL MODE"
    i18n.set_language("ES")
    assert i18n.tr(bridge_mode.COLLAUDO_CONFIRM_TEXT).startswith("Estás activando el MODO DE PRUEBA")
    assert "apuestas reales" in i18n.tr(_APP_KEYS[7])        # START manual body
    assert i18n.tr("Conferma MODALITÀ REALE") == "Confirmar MODO REAL"
    # fallback IT: identità (nessuna regressione per gli utenti italiani)
    i18n.set_language("IT")
    assert i18n.tr(bridge_mode.COLLAUDO_CONFIRM_TEXT) == bridge_mode.COLLAUDO_CONFIRM_TEXT
    assert i18n.tr("Conferma MODALITÀ REALE") == "Conferma MODALITÀ REALE"
