"""P3-7 audit #76 — le schede Strumenti devono riflettere la config VIVA, non il disco.

Bug: dopo l'applicazione di un profilo, `_refresh_tool_panels_after_profile` chiamava
`_panel.refresh()` senza argomenti e ogni pannello rileggeva `config.json` DAL DISCO.
Ma `_persist_loaded_profile` applica il profilo in memoria (`self._config = saved`)
ANCHE quando il persist su disco FALLISCE («Profilo applicato in memoria … ma NON
persistito»): in quel caso il disco contiene ancora la config PRE-profilo e i pannelli
tornavano a mostrare — e a un Salva successivo a riscrivere, su disco e nella config
viva via `on_saved` — lo stato vecchio, incluse le `source_chats` (filtro chat
riportato silenziosamente al pre-profilo).

Fix testato: `refresh(cfg=None)` su tutti i pannelli — la config VIVA passata vince sul
disco; `None` conserva il comportamento storico (ricarica da disco) per gli altri
chiamanti; `app.py` inoltra `copy.deepcopy(saved)` per pannello (i pannelli non devono
condividere dict annidati con la config viva).

Pattern: `__new__` + ctk finto (come test_guided_mapping_autosave_76): niente widget, ma
store/editor REALI (`provider_store`, `SourceEditor`, `name_mapping_store`,
`market_mapping_store`, `config_store`) su un CONFIG_FILE temporaneo — il contrasto
disco ≠ viva è vero, non simulato."""

import importlib
import re
import sys
import types
from pathlib import Path

import pytest

from xtrader_bridge import (config_store, market_mapping_store, name_mapping_store,
                            provider_store)

_APP = Path(__file__).resolve().parents[2] / "xtrader_bridge" / "app.py"


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


class _Var:
    def __init__(self, value="", **_k):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _Menu:
    """Cattura `configure(values=...)` della tendina profili."""
    values = None

    def configure(self, **k):
        self.values = k.get("values", self.values)


def _mod(monkeypatch, name):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, f"xtrader_bridge.{name}", raising=False)
    return importlib.import_module(f"xtrader_bridge.{name}")


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """CONFIG_FILE temporaneo: il DISCO è la config pre-profilo (divergente dalla viva)."""
    path = str(tmp_path / "config.json")
    monkeypatch.setattr(config_store, "CONFIG_FILE", path)
    return path


# ── Provider: la lista viene dalla config viva, non dal disco ────────────────────────

def test_provider_load_names_usa_la_config_viva(cfg_file, monkeypatch):
    mod = _mod(monkeypatch, "provider_gui")
    _saved, ok = config_store.save_config(provider_store.add_provider({}, "DiscoProv"),
                                          cfg_file)
    assert ok
    panel = mod.ProviderPanel.__new__(mod.ProviderPanel)
    live = provider_store.add_provider({}, "LiveProv")
    assert panel._load_names(live) == ["LiveProv"]      # cfg viva passata: il disco NON conta
    assert panel._load_names() == ["DiscoProv"]         # senza cfg: comportamento storico


# ── Chat sorgenti: refresh(cfg) ricostruisce le righe dalla config viva ──────────────

def test_sources_refresh_usa_la_config_viva(cfg_file, monkeypatch):
    mod = _mod(monkeypatch, "source_chats_gui")
    disk = {"source_chats": [{"name": "Vecchia", "chat_id": "-100111", "enabled": True}]}
    _saved, ok = config_store.save_config(disk, cfg_file)
    assert ok
    live = {"source_chats": [{"name": "Profilo", "chat_id": "-100222", "enabled": True}]}

    panel = mod.SourceChatsPanel.__new__(mod.SourceChatsPanel)
    panel._rows = []
    added = []
    panel._add_row = lambda src: added.append(src["chat_id"])   # niente widget: cattura

    panel.refresh(live)
    assert added == ["-100222"], "refresh(cfg) deve usare le sorgenti della config VIVA"
    # Review Fable #92: unico pannello che TRATTIENE la config (chip «Traduzioni») →
    # deepcopy DIFENSIVA interna: snapshot UGUALE alla viva ma indipendente (nessun dict
    # annidato condiviso, anche se il chiamante non passasse già una copia).
    assert panel._cfg == live and panel._cfg is not live
    assert panel._cfg["source_chats"] is not live["source_chats"]

    added.clear()
    panel.refresh()                                              # storico: dal disco
    assert added == ["-100111"]


# ── Mapping (⚽ nomi / 🎯 mercati): profili dalla config viva, propagata alle righe ───

def test_name_mapping_reload_profiles_usa_la_config_viva(cfg_file, monkeypatch):
    mod = _mod(monkeypatch, "name_mapping_gui")
    _saved, ok = config_store.save_config(name_mapping_store.add_profile({}, "DISK"),
                                          cfg_file)
    assert ok
    live = name_mapping_store.add_profile({}, "LIVE")

    panel = mod.NameMappingPanel.__new__(mod.NameMappingPanel)
    panel._profile_menu, panel._profile_var, panel._current = _Menu(), _Var(), None
    seen = []
    panel._reload_rows = lambda cfg=None: seen.append(cfg)

    panel._reload_profiles(select_first=True, cfg=live)
    assert panel._profile_menu.values == ["LIVE"]
    assert panel._current == "LIVE"
    assert seen == [live], "la config viva deve arrivare anche alle RIGHE, non solo ai profili"

    panel._current = None
    panel._reload_profiles(select_first=True)                    # storico: dal disco
    assert panel._profile_menu.values == ["DISK"]


def test_market_mapping_reload_profiles_usa_la_config_viva(cfg_file, monkeypatch):
    mod = _mod(monkeypatch, "name_mapping_gui")
    _saved, ok = config_store.save_config(market_mapping_store.add_profile({}, "DISK"),
                                          cfg_file)
    assert ok
    live = market_mapping_store.add_profile({}, "LIVE")

    panel = mod.MarketMappingPanel.__new__(mod.MarketMappingPanel)
    panel._profile_menu, panel._profile_var, panel._current = _Menu(), _Var(), None
    seen = []
    panel._reload_rows = lambda cfg=None: seen.append(cfg)

    panel._reload_profiles(select_first=True, cfg=live)
    assert panel._profile_menu.values == ["LIVE"]
    assert seen == [live]


def test_guided_refresh_usa_la_config_viva(cfg_file, monkeypatch):
    mod = _mod(monkeypatch, "guided_mapping_gui")
    _saved, ok = config_store.save_config(name_mapping_store.add_profile({}, "DISK"),
                                          cfg_file)
    assert ok
    live = name_mapping_store.add_profile({}, "LIVE")

    panel = mod.GuidedMappingPanel.__new__(mod.GuidedMappingPanel)
    panel._profile_menu, panel._profile_var, panel._current = _Menu(), _Var(), None

    panel.refresh(live)
    assert panel._profile_menu.values == ["LIVE"]
    panel.refresh()                                              # storico: dal disco
    assert panel._profile_menu.values == ["DISK"]


# ── Hub Mapping: refresh(cfg) inoltra la STESSA config viva a tutte e tre le aree ────

def test_mapping_panel_inoltra_la_config_viva_alle_aree(monkeypatch):
    mod = _mod(monkeypatch, "name_mapping_gui")
    hub = mod.MappingPanel.__new__(mod.MappingPanel)
    calls = []

    class _Sub:
        def __init__(self, key):
            self._key = key

        def refresh(self, cfg=None):
            calls.append((self._key, cfg))

    hub._calcio, hub._mercati, hub._guidato = _Sub("calcio"), _Sub("mercati"), _Sub("guidato")
    live = {"marker": "viva", "annidato": {"k": 1}}
    hub.refresh(live)
    assert [(k, c) for k, c in calls] == [("calcio", live), ("mercati", live),
                                          ("guidato", live)]
    # Review Fable/GPT #92: UGUALI ma NON identiche — deepcopy per area, nessun dict
    # annidato condiviso tra le sorelle né con la config viva del chiamante.
    ricevute = [c for _k, c in calls]
    for c in ricevute:
        assert c is not live and c["annidato"] is not live["annidato"]
    assert ricevute[0] is not ricevute[1] and ricevute[1] is not ricevute[2]

    calls.clear()
    hub.refresh()                                    # storico: None inoltrato tal quale
    assert calls == [("calcio", None), ("mercati", None), ("guidato", None)]


# ── app.py: il glue passa deepcopy(saved) — mai refresh() senza argomento ────────────

def test_app_inoltra_deepcopy_della_config_viva():
    """Sorgente pinnato (app.py non importabile headless, pattern #311): il refresh
    post-profilo deve inoltrare `copy.deepcopy(saved)` — dal disco tornerebbe lo stato
    pre-profilo quando il persist è fallito (P3-7 #76)."""
    src = _APP.read_text(encoding="utf-8")
    corpo = src[src.index("def _refresh_tool_panels_after_profile"):]
    corpo = corpo[:corpo.index("\n    def ", 10)]
    assert "_panel.refresh(copy.deepcopy(saved))" in corpo
    assert "_panel.refresh()" not in corpo, (
        "refresh() senza argomento = ricarica dal disco → anteprima pre-profilo (P3-7)")
    # Review Fugu #92: il pin sul CORPO non basterebbe se `import copy` sparisse dal
    # modulo — un NameError verrebbe inghiottito dall'except best-effort e TUTTI i
    # pannelli resterebbero stantii in silenzio. Pinna anche l'import a livello modulo.
    assert re.search(r"^import copy$", src, re.M), (
        "app.py: manca `import copy` a livello modulo — deepcopy(saved) fallirebbe in "
        "NameError silenzioso dentro il try best-effort")
