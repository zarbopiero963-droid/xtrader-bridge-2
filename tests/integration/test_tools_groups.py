"""Information architecture dell'hub Strumenti in 4 gruppi per flusso (#293 slice 4).

Le schede restano un `CTkTabview` piatto ma sono RIORDINATE per gruppo e prefissate ①..④.
Qui si verifica la logica REALE e pura (`build_tool_panels`/`TOOL_GROUPS`/`TOOL_TITLES`): ordine
delle schede, prefissi corretti, nessuno strumento perso/duplicato, fail-fast su factory
mancante. `customtkinter` è stubbato (modulo GUI, no display).
"""

import importlib
import sys
import types

import pytest


@pytest.fixture
def tools_mod(monkeypatch):
    fake = types.ModuleType("customtkinter")
    fake.__getattr__ = lambda _n: object
    monkeypatch.setitem(sys.modules, "customtkinter", fake)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.tools_gui", raising=False)
    return importlib.import_module("xtrader_bridge.tools_gui")


_ALL_KEYS = ("sources", "provider", "parser", "mapping", "dictionary",
             "journal", "known_teams", "profiles", "summary")


def _factories():
    # Ogni factory ritorna la propria chiave, così si verifica che sia instradata alla scheda giusta.
    return {k: (lambda parent, _k=k: _k) for k in _ALL_KEYS}


def test_ordine_e_prefissi_delle_schede(tools_mod):
    panels = tools_mod.build_tool_panels(_factories())
    titles = [t for t, _f in panels]
    assert titles == [
        "① 📡 Chat sorgenti", "① 📇 Provider",
        "② 🧩 Parser", "② 🗺️ Mapping",
        "③ 📖 Dizionario", "③ 📒 Diario", "③ 🧹 Nomi squadra",
        "④ 📁 Profili", "④ 📋 Riepilogo",
    ]


def test_tutte_le_factory_sono_instradate(tools_mod):
    # Nessuno strumento perso o duplicato dal riordino: 9 schede, ogni factory alla sua scheda.
    panels = tools_mod.build_tool_panels(_factories())
    assert len(panels) == 9
    routed = [f(None) for _t, f in panels]
    assert routed == ["sources", "provider", "parser", "mapping",
                      "dictionary", "journal", "known_teams", "profiles", "summary"]


def test_ogni_prefisso_e_coerente_col_gruppo(tools_mod):
    # Ogni titolo di scheda porta il prefisso del gruppo a cui lo strumento appartiene.
    key_to_prefix = {k: prefix for prefix, _n, keys in tools_mod.TOOL_GROUPS for k in keys}
    for prefix, _name, keys in tools_mod.TOOL_GROUPS:
        for key in keys:
            title = f"{prefix} {tools_mod.TOOL_TITLES[key]}"
            assert title.startswith(prefix + " ")
            assert key_to_prefix[key] == prefix


def test_gruppi_e_titoli_coerenti(tools_mod):
    # I 4 gruppi hanno i prefissi attesi e coprono ESATTAMENTE tutti gli strumenti, una volta sola.
    prefixes = [g[0] for g in tools_mod.TOOL_GROUPS]
    assert prefixes == ["①", "②", "③", "④"]
    grouped = [k for _p, _n, keys in tools_mod.TOOL_GROUPS for k in keys]
    assert len(grouped) == len(set(grouped))                    # nessuno strumento in due gruppi
    assert sorted(grouped) == sorted(tools_mod.TOOL_TITLES)     # copertura completa, nessun orfano


def test_fail_fast_se_manca_una_factory(tools_mod):
    # Un riordino che dimentica uno strumento non deve perdere una scheda in silenzio: KeyError.
    incomplete = {"sources": lambda parent: "sources"}
    with pytest.raises(KeyError):
        tools_mod.build_tool_panels(incomplete)


def _window_with(tools_mod, titles):
    """Istanza NUDA di ToolsWindow (senza Tk) con solo `_panels` popolato, per testare il
    resolver puro `_resolve_tab_title` senza costruire widget."""
    w = object.__new__(tools_mod.ToolsWindow)
    w._panels = {t: object() for t in titles}
    return w


def test_resolve_tab_title_accetta_titolo_base_e_completo(tools_mod):
    # Robustezza `initial` (review #338, GPT/GLM/Fable/Fugu): i titoli hanno un prefisso ①..④,
    # ma un chiamante che passa il titolo BASE senza prefisso deve trovare comunque la scheda.
    w = _window_with(tools_mod, ["① 📡 Chat sorgenti", "② 🧩 Parser", "④ 📋 Riepilogo"])
    assert w._resolve_tab_title("② 🧩 Parser") == "② 🧩 Parser"     # match esatto (completo)
    assert w._resolve_tab_title("🧩 Parser") == "② 🧩 Parser"        # titolo base senza prefisso
    assert w._resolve_tab_title("📋 Riepilogo") == "④ 📋 Riepilogo"
    assert w._resolve_tab_title("📡 Chat sorgenti") == "① 📡 Chat sorgenti"


def test_resolve_tab_title_nessun_match(tools_mod):
    w = _window_with(tools_mod, ["② 🧩 Parser"])
    assert w._resolve_tab_title("🔵 Betfair Sync") is None    # non presente
    assert w._resolve_tab_title("") is None                    # vuoto
    assert w._resolve_tab_title(None) is None
    # Non deve fare match parziale ambiguo: "Parser" da solo non è un suffisso « + titolo».
    assert w._resolve_tab_title("Parser") is None
