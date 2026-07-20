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

from xtrader_bridge import i18n


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    # Stato di modulo i18n: mai leak di EN/ES verso i test che pretendono i titoli IT.
    yield
    i18n.set_language("IT")


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


# ── Localizzazione hub (#343 slice 4x): i titoli-scheda passano da i18n.tr a BUILD-TIME. ──

def test_build_tool_panels_localizza_in_en(tools_mod):
    # In EN i titoli-scheda sono tradotti; il prefisso di gruppo ①..④ resta invariato. Verifica il
    # flusso REALE (build_tool_panels → i18n.tr), non solo il catalogo.
    i18n.set_language("EN")
    titles = [t for t, _f in tools_mod.build_tool_panels(_factories())]
    assert titles == [
        "① 📡 Source chats", "① 📇 Provider",
        "② 🧩 Parser", "② 🗺️ Mapping",
        "③ 📖 Dictionary", "③ 📒 Journal", "③ 🧹 Team names",
        "④ 📁 Profiles", "④ 📋 Summary",
    ]


def test_build_tool_panels_localizza_in_es(tools_mod):
    i18n.set_language("ES")
    titles = [t for t, _f in tools_mod.build_tool_panels(_factories())]
    assert titles == [
        "① 📡 Chats de origen", "① 📇 Proveedor",
        "② 🧩 Parser", "② 🗺️ Mapeo",
        "③ 📖 Diccionario", "③ 📒 Diario", "③ 🧹 Nombres de equipo",
        "④ 📁 Perfiles", "④ 📋 Resumen",
    ]


def test_build_tool_panels_it_invariato(tools_mod):
    # IT (default/fail-safe): i titoli restano quelli storici → nessuna regressione, e il test
    # d'ordine esistente (che pretende i titoli IT) resta coerente.
    i18n.set_language("IT")
    titles = [t for t, _f in tools_mod.build_tool_panels(_factories())]
    assert titles[0] == "① 📡 Chat sorgenti"
    assert titles[2] == "② 🧩 Parser"


def test_resolve_tab_title_coerente_coi_titoli_localizzati(tools_mod):
    # In EN le schede sono create coi titoli tradotti: il resolver (che legge self._panels) deve
    # restare self-consistente — match esatto e per titolo-base tradotto senza prefisso.
    i18n.set_language("EN")
    titles = [t for t, _f in tools_mod.build_tool_panels(_factories())]
    w = _window_with(tools_mod, titles)
    assert w._resolve_tab_title("② 🧩 Parser") == "② 🧩 Parser"
    assert w._resolve_tab_title("📖 Dictionary") == "③ 📖 Dictionary"     # base tradotto → scheda giusta
    assert w._resolve_tab_title("📡 Chat sorgenti") is None               # base IT non matcha in EN


# ── AC-M13: teardown finestra Strumenti alla chiusura con la «X» (audit #114) ──

def test_tools_window_registra_wm_delete_window(tools_mod):
    """AC-M13 audit #114: `CTkToplevel` NON registra `WM_DELETE_WINDOW`, quindi chiudere
    la finestra Strumenti con la «X» distruggerebbe i widget a livello Tcl SENZA invocare
    il `destroy()` Python dei pannelli figli (dove i debounce annullano gli `after`).
    `ToolsWindow.__init__` deve instradare la «X» su `self.destroy` così la catena Python
    (`BaseWidget.destroy` → figli) parte anche via «X». Guard a sorgente (l'apertura reale
    richiede un root Tk → smoke manuale su Windows), stesso pattern degli altri meta-test."""
    import inspect
    src = inspect.getsource(tools_mod.ToolsWindow.__init__)
    assert 'self.protocol("WM_DELETE_WINDOW", self.destroy)' in src, (
        "tools_gui: ToolsWindow.__init__ deve instradare la «X» su self.destroy (AC-M13 #114)")


def test_pannelli_debounce_annullano_after_nel_destroy():
    """AC-M13: la catena di `destroy` è utile solo se i pannelli figli con debounce
    annullano davvero il timer pendente nel loro `destroy()`. Blinda che i due pannelli
    interessati mantengano `cancel_pending()` sul debouncer nel teardown (regressione del
    fix #184 M12 che AC-M13 estende alla chiusura via «X»). I moduli GUI importano
    tkinter (non headless): si legge il sorgente da disco via il path del package."""
    import os
    import xtrader_bridge
    pkg = os.path.dirname(xtrader_bridge.__file__)
    for rel in ("betfair/dictionary_viewer_gui.py", "guided_mapping_gui.py"):
        with open(os.path.join(pkg, rel), encoding="utf-8") as f:
            src = f.read()
        body = src.split("def destroy(self)", 1)
        assert len(body) == 2, f"{rel}: manca il destroy() del pannello"
        after = body[1]
        assert "cancel_pending()" in after and "super().destroy()" in after, (
            f"{rel}: destroy() deve annullare il debounce e chiamare super().destroy()")
