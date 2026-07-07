"""Test hard #343 slice 4a: catalogo i18n della finestra principale.

Puri e headless. Il test anti-drift lega il catalogo al sorgente REALE di
`app.py`: una label cambiata nel codice fa fallire la suite finché il catalogo
non viene aggiornato (mai traduzioni orfane)."""

import ast
import os

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")


def _read(name):
    with open(os.path.join(_PKG, name), encoding="utf-8") as fh:
        return fh.read()


_APP_SRC = _read("app.py")
# Le chiavi dei contatori Dashboard vivono in dashboard_stats.COUNTERS (la resa in
# app.py li wrappa via i18n.tr(label)): l'anti-drift le cerca in ENTRAMBI i sorgenti.
_DASH_SRC = _read("dashboard_stats.py")


def _tr_constants(*module_names) -> set:
    """Estrae via AST tutte le stringhe COSTANTI passate come primo argomento a
    `i18n.tr(...)` nei moduli indicati. L'AST unisce i literal adiacenti (le
    stringhe multi-linea concatenate del sorgente diventano UNA costante), così le
    chiavi lunghe delle finestre secondarie sono confrontabili verbatim col catalogo
    (#343 slice 4c: le chiavi Provider sono concatenazioni su più righe)."""
    found = set()
    for name in module_names:
        tree = ast.parse(_read(name))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


# Costanti tr() delle finestre secondarie localizzate (#343 slice 4c/4d/4e).
_SECONDARY_TR = _tr_constants("provider_gui.py", "profiles_gui.py", "source_chats_gui.py")


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")     # stato di modulo: mai leak verso altri test


def test_default_italiano_e_tr_identita():
    assert i18n.get_language() == "IT"
    assert i18n.tr("▶  AVVIA") == "▶  AVVIA"          # IT: il catalogo non serve
    assert i18n.tr("qualunque cosa") == "qualunque cosa"


def test_set_language_fail_safe():
    assert i18n.set_language("en") == "EN"
    assert i18n.get_language() == "EN"
    assert i18n.set_language("XX") == "IT"             # non supportata → IT
    assert i18n.set_language(None) == "IT"
    assert i18n.set_language("") == "IT"               # mai scelta → comportamento storico


def test_tr_traduce_en_ed_es():
    i18n.set_language("EN")
    assert i18n.tr("▶  AVVIA") == "▶  START"
    assert i18n.tr("🧰  Strumenti") == "🧰  Tools"
    assert i18n.tr("■  STOP") == "■  STOP"             # identica in EN: fallback
    i18n.set_language("ES")
    assert i18n.tr("▶  AVVIA") == "▶  INICIAR"
    assert i18n.tr("■  STOP") == "■  DETENER"
    assert i18n.tr("🧰  Strumenti") == "🧰  Herramientas"


def test_tr_fail_safe_su_chiave_mancante():
    i18n.set_language("EN")
    assert i18n.tr("stringa mai catalogata") == "stringa mai catalogata"
    assert i18n.tr("") == ""                            # mai crash, mai None


def test_catalogo_anti_drift_chiavi_verbatim_nel_sorgente():
    """Ogni chiave del catalogo esiste VERBATIM in app.py: una label rinominata
    nel codice senza aggiornare il catalogo fa fallire QUESTO test (mai
    traduzioni orfane che l'utente EN/ES non vedrebbe più)."""
    for lang, table in i18n._CATALOG.items():
        for key in table:
            assert key in _APP_SRC or key in _DASH_SRC or key in _SECONDARY_TR, (
                f"{lang}: chiave stantia, non in app.py/dashboard_stats.py né nelle "
                f"finestre secondarie localizzate: {key!r}")


def test_catalogo_valori_sensati():
    for lang, table in i18n._CATALOG.items():
        assert table, f"catalogo {lang} vuoto"
        for key, val in table.items():
            assert isinstance(val, str) and val.strip(), f"{lang}:{key!r} vuota"


def test_nomi_tab_solo_dentro_tr():
    """Fable #357: un accesso ai tab PER NOME con la stringa italiana hardcoded
    (`tabs.set("…")`, `tabview.tab("…")`, `insert(..., before="…")`) crasherebbe
    in EN/ES, perché il tab è stato AGGIUNTO col nome tradotto. Guardia: ogni
    occorrenza dei nomi-tab in app.py deve stare dentro `i18n.tr(...)` — un
    futuro accesso per nome non wrappato fa fallire QUESTO test."""
    import re
    tabs = ["⚙️ Generale", "🎯 Riconoscimento", "🛡️ Sicurezza",
            "✅ Conferme XTrader", "📡 Chat ascoltate", "🚦 Salute",
            "📡 Stato", "📊 Dashboard", "📋 Log"]
    for t in tabs:
        occorrenze = list(re.finditer(re.escape(f'"{t}"'), _APP_SRC))
        assert occorrenze, f"nome tab sparito da app.py: {t!r}"
        for m in occorrenze:
            assert _APP_SRC[:m.start()].endswith("i18n.tr("), (
                f"accesso al tab {t!r} con literal NON wrappato in i18n.tr "
                "(in EN/ES CTkTabview non troverebbe il tab)")


def test_sorgente_usa_tr_sulle_label_catalogate():
    """Anti-regressione wiring: le label tradotte devono passare da i18n.tr nel
    sorgente (un revert del wrap le farebbe tornare hardcoded solo-IT)."""
    for probe in ('i18n.tr("▶  AVVIA")', 'i18n.tr("🧰  Strumenti")',
                  'i18n.tr("⚙️ Generale")', 'i18n.tr(label)',
                  # CodeRabbit #357: anche i CONTENUTI dei tab tradotti (impostazioni
                  # avanzate) e i contatori Dashboard devono passare da tr()
                  'i18n.tr("🚦 Modalità bridge")',
                  'i18n.tr("💬 Chat notifiche XTrader")'):
        assert probe in _APP_SRC, f"wrap mancante in app.py: {probe}"
    assert _APP_SRC.count("i18n.tr(label)") >= 2, (
        "wrap mancante su gen_fields o sui contatori Dashboard (entrambi i loop "
        "devono passare da i18n.tr(label))")
