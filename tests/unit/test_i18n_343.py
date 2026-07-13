"""Test hard #343 slice 4a: catalogo i18n della finestra principale.

Puri e headless. Il test anti-drift lega il catalogo al sorgente REALE di
`app.py`: una label cambiata nel codice fa fallire la suite finché il catalogo
non viene aggiornato (mai traduzioni orfane)."""

import ast
import os

import pytest

from xtrader_bridge import bridge_mode, i18n, real_mode

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")


def _read(name):
    with open(os.path.join(_PKG, name), encoding="utf-8") as fh:
        return fh.read()


_APP_SRC = _read("app.py")
# Le chiavi dei contatori Dashboard vivono in dashboard_stats.COUNTERS (la resa in
# app.py li wrappa via i18n.tr(label)): l'anti-drift le cerca in ENTRAMBI i sorgenti.
_DASH_SRC = _read("dashboard_stats.py")
# Wizard (#343 slice 4h): i 5 titoli step vivono nella tupla `_TITLES` e sono resi via
# `i18n.tr(self._TITLES[step])` (indiretto → non estraibili come tr-constant): l'anti-drift li
# cerca come literal VERBATIM nel sorgente (sono single-line, non concatenati).
_WIZARD_SRC = _read("wizard_gui.py")
# Mapping (#343 slice 4i): le etichette colonna vivono nelle tuple `_HEADER_COLUMNS`/
# `_MARKET_HEADER_COLUMNS` e sono rese via `i18n.tr(text)` (indiretto): come per il Wizard,
# l'anti-drift le cerca come literal VERBATIM nel sorgente (single-line nelle tuple).
_NAMEMAP_SRC = _read("name_mapping_gui.py")
# Hub «🧰 Strumenti» (#343 slice 4x): i titoli-scheda vivono in `TOOL_TITLES` e il titolo finestra
# nel default `title="🧰 Strumenti"`; sono resi via `i18n.tr(variable)` a build-time (indiretto →
# non estraibili come tr-constant). Come Wizard/Mapping, l'anti-drift li cerca come literal VERBATIM
# nel sorgente (single-line, nessun escape). La label d'errore per-scheda è invece un
# `i18n.tr("literal")` (contiene «\n») → coperta da `_SECONDARY_TR` che ne decodifica l'escape.
_TOOLS_SRC = _read("tools_gui.py")


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


# Costanti tr() delle finestre secondarie localizzate (#343 slice 4c/4d/4e/4f).
_SECONDARY_TR = _tr_constants("provider_gui.py", "profiles_gui.py",
                              "source_chats_gui.py", "journal_view_gui.py",
                              "custom_parser_gui.py", "wizard_gui.py", "name_mapping_gui.py",
                              # Pannello «🧹 Nomi squadra noti» (#343 slice 4t): chiavi tutte
                              # `i18n.tr("literal")` (descrizione multi-riga concatenata inclusa →
                              # AST le unisce). Il sentinel «(tutti gli sport)» resta value-as-key IT.
                              "known_teams_gui.py",
                              # Pannello «📋 Riepilogo configurazione» (#343 slice 4u): helper puri
                              # di presentazione, tutte le chiavi sono `i18n.tr("literal")`.
                              "config_summary_gui.py",
                              # Pannello «🌳 Mapping guidato» (#343 slice 4v — CHROME): chiavi tutte
                              # `i18n.tr("literal")` (descrizione multi-riga inclusa). I segnaposto
                              # value-as-key «(nessun profilo)»/«(scegli lo sport)» restano IT.
                              "guided_mapping_gui.py",
                              # Hub «🧰 Strumenti» (#343 slice 4x): la sola tr-constant è la label
                              # d'errore per-scheda `i18n.tr("⚠️ Impossibile aprire…\n{exc}")` (l'AST
                              # decodifica il «\n» che la ricerca raw non troverebbe). I titoli-scheda
                              # e il titolo finestra sono `i18n.tr(variable)` → coperti da `_TOOLS_SRC`.
                              "tools_gui.py")

# Costanti tr() di app.py (#343 slice 4j/4k — log localizzati): alcune chiavi dei log sono
# COSTANTI multi-riga concatenate (`i18n.tr("… " "…")`) che la ricerca raw in `_APP_SRC` non
# trova. L'AST le unisce in UNA costante confrontabile verbatim col catalogo, come per le
# finestre secondarie.
_APP_TR = _tr_constants("app.py")

# Banner di MODALITÀ (#343 slice 4 — residuo banner della #3): i testi vivono come COSTANTI
# multi-riga concatenate in `real_mode`/`bridge_mode` e sono resi in app.py via
# `i18n.tr(real_mode.BANNER_TEXT)` / `i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT)`. L'anti-drift
# li lega ai VALORI REALI delle costanti (non al testo sorgente, che è spezzato dalla
# concatenazione): se una costante cambia, la chiave del catalogo non combacia più → FAIL.
_BANNER_TEXTS = {real_mode.BANNER_TEXT, bridge_mode.COLLAUDO_BANNER_TEXT}


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
            assert (key in _APP_SRC or key in _APP_TR or key in _DASH_SRC or key in _SECONDARY_TR
                    or key in _BANNER_TEXTS or key in _WIZARD_SRC or key in _NAMEMAP_SRC
                    or key in _TOOLS_SRC), (
                f"{lang}: chiave stantia, non in app.py/dashboard_stats.py, nelle finestre "
                f"secondarie localizzate, nei banner, nel wizard, nel Mapping né nell'hub "
                f"Strumenti: {key!r}")


def _catalog_lang_dicts(tree):
    """I dict-literal per-lingua DENTRO l'assegnazione `_CATALOG = {"EN": {...}, "ES": {...}}` di
    i18n.py (CodeRabbit #50: la guardia va limitata al catalogo, non a ogni ast.Dict del file)."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_CATALOG" for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            for lang_key, lang_val in zip(node.value.keys, node.value.values):
                if isinstance(lang_val, ast.Dict):
                    lang = lang_key.value if isinstance(lang_key, ast.Constant) else "?"
                    yield lang, lang_val


def test_catalogo_nessuna_chiave_duplicata_con_valore_diverso():
    """Nessuna mappa-lingua di `_CATALOG` ha la STESSA chiave mappata a DUE valori DIVERSI
    (CodeRabbit #50): è la classe di bug reale — l'ultima entry vince silenziosamente, cambiando la
    traduzione per i chiamanti dell'entry precedente (es. profiles_gui). Guardia AST scoping-ata al
    solo `_CATALOG` (non a ogni dict di i18n.py): parse del sorgente, per ogni mappa-lingua si vieta
    ogni chiave stringa ripetuta con valore diverso. (I duplicati con valore IDENTICO sono ridondanti
    ma innocui e non falliscono qui.)"""
    tree = ast.parse(_read("i18n.py"))
    lang_dicts = list(_catalog_lang_dicts(tree))
    # il test non deve diventare un no-op se `_CATALOG` viene ristrutturato: pretende le lingue reali.
    lingue = {lang for lang, _ in lang_dicts}
    assert set(i18n._CATALOG) <= lingue, (
        f"guardia non ha trovato tutte le mappe-lingua di _CATALOG come dict-literal: {lingue}")
    conflitti = []
    for lang, d in lang_dicts:
        viste = {}
        for k, v in zip(d.keys, d.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)
                    and isinstance(v, ast.Constant)):
                continue
            if k.value in viste and viste[k.value] != v.value:
                conflitti.append((lang, k.value, viste[k.value], v.value, k.lineno))
            viste[k.value] = v.value
    assert not conflitti, "chiavi di catalogo duplicate con valore DIVERSO (override silenzioso):\n" + \
        "\n".join(f"  [{lg}] {key!r} @L{ln}: {prev!r} → {cur!r}"
                  for lg, key, prev, cur, ln in conflitti)


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


def test_banner_modalita_default_italiano():
    # IT (default/fail-safe): i banner restano nel testo italiano storico — il catalogo non
    # tocca la lingua di riferimento, nessuna regressione per gli utenti italiani.
    assert i18n.get_language() == "IT"
    assert i18n.tr(real_mode.BANNER_TEXT) == real_mode.BANNER_TEXT
    assert i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT) == bridge_mode.COLLAUDO_BANNER_TEXT


def test_banner_modalita_tradotti_en_es():
    # SAFETY: il banner ROSSO «MODALITÀ REALE» e quello COLLAUDO devono localizzarsi in EN/ES
    # (prima restavano hardcoded in IT). Traduzione verbatim → blocca la regressione e verifica
    # che la severità sia preservata (REAL/REALES, TEST/PRUEBA, warning emoji conservata).
    i18n.set_language("EN")
    assert i18n.tr(real_mode.BANNER_TEXT) == (
        "⚠️ REAL MODE ACTIVE — valid signals are written to the operational CSV "
        "and XTrader can place REAL bets.")
    assert i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT) == (
        "🔬 XTRADER TEST MODE — the operational CSV IS written: "
        "XTrader must be in Simulation Mode (no real bets).")
    i18n.set_language("ES")
    assert i18n.tr(real_mode.BANNER_TEXT) == (
        "⚠️ MODO REAL ACTIVO — las señales válidas se escriben en el CSV "
        "operativo y XTrader puede realizar apuestas REALES.")
    assert i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT) == (
        "🔬 MODO DE PRUEBA XTRADER — el CSV operativo SE escribe: "
        "XTrader debe estar en Modo Simulación (sin apuestas reales).")
    # la warning-emoji e il rischio «real» restano visibili in entrambe le lingue
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        assert i18n.tr(real_mode.BANNER_TEXT).startswith("⚠️"), lang
        assert i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT).startswith("🔬"), lang


def test_banner_wiring_in_app():
    # Anti-regressione wiring: app.py deve rendere i banner via i18n.tr sulle costanti (un
    # revert li farebbe tornare hardcoded solo-IT anche in EN/ES).
    assert "i18n.tr(real_mode.BANNER_TEXT)" in _APP_SRC
    assert "i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT)" in _APP_SRC
