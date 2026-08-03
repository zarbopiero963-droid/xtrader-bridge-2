"""Nascondimento degli strumenti orfani di una sorgente dati — #182 PR N.

**Perché esistono.** Tre pezzi di GUI leggono il **DB Betfair locale**, che senza il «Betfair
Sync» (rimosso) resta **vuoto e non popolabile dall'app**: `upsert_sport`/`upsert_competition`/
`upsert_event` esistono ma non hanno alcun chiamante nel codice di prodotto. All'utente
apparivano *rotti*, e il messaggio «Popola il dizionario locale, poi riprova» chiedeva una cosa
impossibile. Sono stati **nascosti**:

- la scheda **«🧹 Nomi squadra»** dell'hub Strumenti;
- la sotto-scheda **«🌳 Mapping guidato»** del pannello Mapping;
- il pulsante **«📥 Precompila da Betfair»** del pannello «⚽ Calcio».

**Nascondere non è rimuovere.** Etichette, pannelli, factory, metodi, DB e resolver restano
tutti: la riattivazione deve costare poche righe quando tornerà una sorgente dati. Perciò ogni
test qui ha **due metà**: la scheda/il pulsante non si vede più **E** il codice sottostante c'è
ancora. Una metà sola lascerebbe passare la cancellazione per errore.

La ritenzione è **verificata** (file su disco, sorgente ispezionata, metodo risolto), non
asserita a parole: un test che dicesse solo «è ritenuto» non si accorgerebbe di nulla.
"""

import importlib
import inspect
import os
import sys
import types

import pytest

import xtrader_bridge


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota.

    Stesso pattern di `tests/unit/test_name_mapping_gui_prefill.py`: i moduli GUI importano
    tkinter e non sono importabili headless, ma la logica sotto test è quella vera."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def name_mapping_mod(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    return importlib.import_module("xtrader_bridge.name_mapping_gui")


@pytest.fixture()
def tools_mod(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.tools_gui", raising=False)
    return importlib.import_module("xtrader_bridge.tools_gui")


def _pkg_path(*parti):
    return os.path.join(os.path.dirname(xtrader_bridge.__file__), *parti)


# ── 🧹 Nomi squadra ──────────────────────────────────────────────────────────────────

def test_known_teams_fuori_dalle_schede_ma_RITENUTA(tools_mod):
    """Fail-first: prima della patch «known_teams» era nel gruppo ③ e la scheda si vedeva."""
    grouped = [k for _p, _n, keys in tools_mod.TOOL_GROUPS for k in keys]
    assert "known_teams" not in grouped, (
        "la scheda «🧹 Nomi squadra» è tornata visibile: legge il DB Betfair, che è vuoto")

    # RITENUTA — le tre prove che la riattivazione è ancora possibile:
    assert tools_mod.TOOL_TITLES.get("known_teams") == "🧹 Nomi squadra"   # etichetta e traduzioni
    assert os.path.exists(_pkg_path("known_teams_gui.py"))                 # pannello su disco
    from xtrader_bridge import app as app_mod  # factory cablata
    src = inspect.getsource(app_mod.App._open_tools)
    assert '"known_teams":' in src, (
        "la factory di known_teams è sparita da app.py: la scheda non è più riattivabile "
        "con una riga in TOOL_GROUPS")


# ── 🌳 Mapping guidato ───────────────────────────────────────────────────────────────

def test_mapping_ha_esattamente_due_sottoschede(name_mapping_mod):
    """Le sotto-schede del Mapping sono ⚽ Calcio e 🎯 Mercati, e nient'altro.

    Fail-first: prima della patch ce n'erano tre. Guardia sul **sorgente** perché costruire il
    `CTkTabview` richiede widget veri."""
    src = inspect.getsource(name_mapping_mod.MappingPanel.__init__)
    aggiunte = [riga for riga in src.splitlines()
                if "_tabs.add(" in riga and not riga.strip().startswith("#")]
    assert len(aggiunte) == 2, f"sotto-schede attive attese 2, trovate {len(aggiunte)}: {aggiunte}"
    assert any("⚽ Calcio" in r for r in aggiunte)
    assert any("🎯 Mercati" in r for r in aggiunte)
    assert not any("Mapping guidato" in r for r in aggiunte), (
        "la sotto-scheda «🌳 Mapping guidato» è tornata attiva: legge il DB Betfair vuoto")


def test_guided_mapping_RITENUTO():
    """Il pannello guidato non è stato cancellato: file, classe e provider restano."""
    assert os.path.exists(_pkg_path("guided_mapping_gui.py"))
    assert os.path.exists(_pkg_path("betfair", "guided_mapping.py"))

    from xtrader_bridge import app as app_mod
    src = inspect.getsource(app_mod.App._open_tools)
    # I provider restano cablati: riattivare la sotto-scheda non deve richiedere di ricablare app.py.
    assert "competitions_provider=" in src and "teams_provider=" in src, (
        "i provider Betfair sono spariti da app.py: riattivare il Mapping guidato non sarebbe "
        "più una modifica locale a name_mapping_gui")


def test_mapping_refresh_non_esplode_senza_la_sottoscheda_guidata(name_mapping_mod):
    """**Il consumatore, non il sito** (regola 2-bis).

    `MappingPanel.refresh` inoltrava a tutte e tre le aree, `self._guidato` inclusa. Nascondere
    la sotto-scheda senza toccare `refresh` lascia `self._guidato = None` e fa sollevare
    `AttributeError` a OGNI refresh del Mapping — un pannello rotto, non una scheda in meno.

    Fail-first: sul codice pre-patch questa chiamata sollevava
    `AttributeError: 'NoneType' object has no attribute 'refresh'`."""
    visti = []
    finto = types.SimpleNamespace(
        _calcio=types.SimpleNamespace(refresh=lambda cfg: visti.append(("calcio", cfg))),
        _mercati=types.SimpleNamespace(refresh=lambda cfg: visti.append(("mercati", cfg))),
        _guidato=None,
    )

    name_mapping_mod.MappingPanel.refresh(finto, {"name_mappings": {"p": []}})

    assert [nome for nome, _ in visti] == ["calcio", "mercati"], (
        "il refresh deve raggiungere le due aree ancora visibili")


# ── 📥 Precompila da Betfair ─────────────────────────────────────────────────────────

def test_pulsante_precompila_nascosto_ma_metodo_RITENUTO(name_mapping_mod):
    """Fail-first: prima della patch il pulsante era costruito in `NameMappingPanel._build_ui`.

    ⚠️ Il primo giro di questo test ispezionava `__init__`, dove il pulsante **non è mai stato**:
    passava sul codice pre-patch, cioè non provava niente. La funzione giusta è `_build_ui`, ed
    è per questo che il fail-first va **eseguito** e non dato per scontato."""
    src = inspect.getsource(name_mapping_mod.NameMappingPanel._build_ui)
    attive = [riga for riga in src.splitlines() if not riga.strip().startswith("#")]
    assert not any("Precompila da Betfair" in r for r in attive), (
        "il pulsante «📥 Precompila da Betfair» è tornato attivo: precompila dal DB Betfair, "
        "che è vuoto e non popolabile dall'app")

    # RITENUTO: il metodo è ancora risolvibile e chiamabile — non un commento, un attributo vero.
    assert callable(getattr(name_mapping_mod.NameMappingPanel, "_prefill_betfair_names", None)), (
        "`_prefill_betfair_names` è stato cancellato: il pulsante non sarebbe più riattivabile")


def test_le_etichette_i18n_delle_parti_nascoste_restano():
    """Le traduzioni non vanno potate insieme alla visibilità: servono alla riattivazione, e
    toglierle renderebbe la scheda riattivata monolingue."""
    from xtrader_bridge import i18n

    i18n.set_language("EN")
    assert i18n.tr("🧹 Nomi squadra") != "🧹 Nomi squadra"          # tradotta, non identità
    assert i18n.tr("📥 Precompila da Betfair") != "📥 Precompila da Betfair"
    i18n.set_language("IT")
