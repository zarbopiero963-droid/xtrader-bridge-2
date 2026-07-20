"""P3-26 + P3-32 audit #76 — robustezza di cambio profilo e Rinomina nel Mapping.

- **P3-26**: con la config ILLEGGIBILE al cambio profilo, l'auto-save veniva saltato ma
  lo switch PROSEGUIVA: `_reload_rows` ricaricava dal profilo nuovo cancellando le righe
  in editing (perse senza avviso). Il ramo save-FALLITO invece annullava già (Codex).
- **P3-32**: se `rename_*_mapping_profile_in_files` sollevava wholesale (cartella parser
  illeggibile…), l'eccezione era inghiottita (`updated=failed=[]`): restava il messaggio
  VERDE di successo mentre i parser salvati potevano puntare ancora al vecchio nome →
  segnali scartati in silenzio (MAPPING_MISSING / MARKET_MAPPING_MISSING).

Fix testato (entrambi i pannelli, ⚽ nomi e 🎯 mercati): config illeggibile → switch
ANNULLATO (profilo corrente a schermo, righe intatte, messaggio rosso); verifica parser
fallita → avviso AMBRA onesto con la causa e il vecchio nome, mai il verde con stato
ignoto. Pattern `__new__` + ctk finto, store/config veri dove servono."""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _Status:
    text = ""
    color = ""

    def configure(self, **k):
        self.text = k.get("text", self.text)
        self.color = k.get("text_color", self.color)


def _mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    return importlib.import_module("xtrader_bridge.name_mapping_gui")


def _panel(mod, cls_name):
    panel = getattr(mod, cls_name).__new__(getattr(mod, cls_name))
    panel._status = _Status()
    panel._current = "VECCHIO"
    panel._profile_var = _Var("VECCHIO")
    return panel


# ── P3-26: config illeggibile al cambio profilo → switch ANNULLATO ───────────────────

@pytest.mark.parametrize("cls_name", ["NameMappingPanel", "MarketMappingPanel"])
def test_config_illeggibile_annulla_lo_switch(monkeypatch, cls_name):
    """FAIL-FIRST: pre-patch lo switch proseguiva e `_reload_rows` cancellava le
    righe in editing."""
    mod = _mod(monkeypatch)
    panel = _panel(mod, cls_name)
    panel._load_cfg = lambda: None                       # config ILLEGGIBILE
    panel._collect_rows = lambda: pytest.fail("annullo: le righe non vanno nemmeno lette")
    panel._reload_rows = lambda *a, **k: pytest.fail("annullo: MAI ricaricare le righe")

    panel._on_profile_change("NUOVO")

    assert panel._current == "VECCHIO"                   # switch annullato
    assert panel._profile_var.get() == "VECCHIO"         # tendina ripristinata
    assert "illeggibile" in panel._status.text.lower()
    assert "annullato" in panel._status.text.lower()


@pytest.mark.parametrize("cls_name", ["NameMappingPanel", "MarketMappingPanel"])
def test_config_leggibile_switch_procede(monkeypatch, cls_name):
    """Regressione: con config sana e save ok lo switch resta quello storico."""
    mod = _mod(monkeypatch)
    panel = _panel(mod, cls_name)
    panel._on_saved = None
    panel._load_cfg = lambda: {}
    panel._collect_rows = lambda: []
    ricaricate = []
    panel._reload_rows = lambda *a, **k: ricaricate.append(True)
    store = mod.name_mapping_store if cls_name == "NameMappingPanel" else mod.market_mapping_store
    monkeypatch.setattr(store, "set_entries", lambda cfg, name, rows: cfg)
    monkeypatch.setattr(mod.config_store, "save_config", lambda cfg, path: (cfg, True))

    panel._on_profile_change("NUOVO")

    assert panel._current == "NUOVO" and ricaricate == [True]


# ── P3-32: verifica parser fallita in Rinomina → mai il verde con stato ignoto ───────

def _panel_per_rename(mod, cls_name, monkeypatch):
    panel = _panel(mod, cls_name)
    panel._load_cfg = lambda: {}
    panel._collect_rows = lambda: []
    panel._persist = lambda cfg, ok_msg, fail_msg, select=None: (
        panel._status.configure(text=ok_msg, text_color=mod.ui_theme.STATUS_OK) or True)
    store = mod.name_mapping_store if cls_name == "NameMappingPanel" else mod.market_mapping_store
    monkeypatch.setattr(store, "profile_names", lambda cfg: ["VECCHIO"])
    monkeypatch.setattr(store, "set_entries", lambda cfg, name, rows: cfg)
    monkeypatch.setattr(store, "rename_profile", lambda cfg, old, new: cfg)
    # il dialog CTkInputDialog finto deve ritornare il nuovo nome
    monkeypatch.setattr(mod.ctk, "CTkInputDialog",
                        lambda **k: types.SimpleNamespace(get_input=lambda: "NUOVO"),
                        raising=False)
    return panel


@pytest.mark.parametrize("cls_name,fn,marker", [
    ("NameMappingPanel", "rename_mapping_profile_in_files", "MAPPING_MISSING"),
    ("MarketMappingPanel", "rename_market_mapping_profile_in_files", "MARKET_MAPPING_MISSING"),
])
def test_verifica_parser_fallita_avvisa_in_ambra(monkeypatch, cls_name, fn, marker):
    """FAIL-FIRST: pre-patch l'eccezione wholesale produceva updated=failed=[] e restava
    il messaggio VERDE («Profilo rinominato») con i parser forse ancora sul vecchio nome."""
    mod = _mod(monkeypatch)
    panel = _panel_per_rename(mod, cls_name, monkeypatch)

    def _boom(old, new):
        raise OSError("cartella parser illeggibile")

    monkeypatch.setattr(mod.custom_parser, fn, _boom)

    panel._rename_profile()

    assert "fallita" in panel._status.text.lower(), "serve l'avviso onesto, non il verde"
    assert "VECCHIO" in panel._status.text            # il vecchio nome da controllare a mano
    assert marker in panel._status.text               # conseguenza esplicita
    assert panel._status.color == mod.ui_theme.STATUS_WARN   # AMBRA, mai il verde di successo


@pytest.mark.parametrize("cls_name,fn", [
    ("NameMappingPanel", "rename_mapping_profile_in_files"),
    ("MarketMappingPanel", "rename_market_mapping_profile_in_files"),
])
def test_verifica_parser_riuscita_flusso_storico(monkeypatch, cls_name, fn):
    """Regressione: verifica riuscita con parser aggiornati → messaggio verde storico."""
    mod = _mod(monkeypatch)
    panel = _panel_per_rename(mod, cls_name, monkeypatch)
    monkeypatch.setattr(mod.custom_parser, fn, lambda old, new: (["p1"], []))

    panel._rename_profile()

    assert "rinominato" in panel._status.text.lower()
    assert panel._status.color == mod.ui_theme.STATUS_OK   # verde legittimo
