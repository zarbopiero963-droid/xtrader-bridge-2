"""P3-27 + P3-28 audit #76 — conferme sulle azioni distruttive della GUI.

- **P3-27**: «🗑 Elimina» distruggeva profili (app / dizionario nomi / dizionario
  mercati) e parser salvati AL CLICK, senza conferma né undo.
- **P3-28**: «🆕 Nuovo» e «📂 Carica» del costruttore parser sostituivano l'editor
  scartando le modifiche non salvate, senza conferma.

Fix testato: punto unico `gui_utils.ask_confirm` (fail-closed: dialog rotto/headless →
False, un'azione distruttiva non parte mai senza conferma esplicita); guardie in testa
alle 4 eliminazioni; dirty-check per Nuovo/Carica su snapshot `asdict(builder.to_def())`
(fail-safe: stato non fotografabile = modificato) con baseline aggiornata a
__init__/Nuovo/Carica/Salva.

Pattern `__new__` + ctk finto + logica REALE (ParserBuilder, store veri dove serve)."""

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

from xtrader_bridge import gui_utils
from xtrader_bridge.parser_builder import ParserBuilder


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


class _Status:
    text = ""

    def configure(self, **k):
        self.text = k.get("text", self.text)


def _mod(monkeypatch, name):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, f"xtrader_bridge.{name}", raising=False)
    return importlib.import_module(f"xtrader_bridge.{name}")


# ── gui_utils.ask_confirm: fail-closed reale ─────────────────────────────────────────

def test_ask_confirm_propaga_si_e_no(monkeypatch):
    fake_mb = types.SimpleNamespace(askyesno=lambda *a, **k: True)
    monkeypatch.setitem(sys.modules, "tkinter", types.ModuleType("tkinter"))
    sys.modules["tkinter"].messagebox = fake_mb
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", fake_mb)
    assert gui_utils.ask_confirm("t", "m") is True
    fake_mb.askyesno = lambda *a, **k: False
    assert gui_utils.ask_confirm("t", "m") is False


def test_ask_confirm_fail_closed_su_dialog_rotto(monkeypatch):
    """FAIL-FIRST: pre-patch l'helper non esisteva. Headless/root distrutta → dialog
    che solleva → MAI confermato (un'eliminazione non parte per un dialog rotto)."""
    def _boom(*_a, **_k):
        raise RuntimeError("no display")

    fake_mb = types.SimpleNamespace(askyesno=_boom)
    monkeypatch.setitem(sys.modules, "tkinter", types.ModuleType("tkinter"))
    sys.modules["tkinter"].messagebox = fake_mb
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", fake_mb)
    assert gui_utils.ask_confirm("t", "m") is False


# ── P3-27: le 4 eliminazioni chiedono conferma PRIMA di distruggere ──────────────────

def test_profili_app_delete_rifiutato_non_tocca_lo_store(monkeypatch):
    mod = _mod(monkeypatch, "profiles_gui")
    panel = mod.ProfilesPanel.__new__(mod.ProfilesPanel)
    panel._status = _Status()
    chiamate = []
    monkeypatch.setattr(mod.profile_store, "delete_profile",
                        lambda name: chiamate.append(name) or True)
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: False)

    panel._delete("P1")

    assert chiamate == [], "conferma rifiutata: lo store NON va toccato (P3-27)"
    assert "annullata" in panel._status.text.lower()


def test_profili_app_delete_confermato_procede(monkeypatch):
    mod = _mod(monkeypatch, "profiles_gui")
    panel = mod.ProfilesPanel.__new__(mod.ProfilesPanel)
    panel._status = _Status()
    panel._refresh_list = lambda: None
    chiamate = []
    monkeypatch.setattr(mod.profile_store, "delete_profile",
                        lambda name: chiamate.append(name) or True)
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: True)

    panel._delete("P1")

    assert chiamate == ["P1"]                    # flusso storico intatto dopo conferma
    assert "eliminato" in panel._status.text.lower()


@pytest.mark.parametrize("cls_name", ["NameMappingPanel", "MarketMappingPanel"])
def test_mapping_delete_rifiutato_non_tocca_la_config(monkeypatch, cls_name):
    mod = _mod(monkeypatch, "name_mapping_gui")
    panel = getattr(mod, cls_name).__new__(getattr(mod, cls_name))
    panel._status = _Status()
    panel._current = "PROF"
    panel._load_cfg = lambda: {"marker": True}
    persist = []
    panel._persist = lambda *a, **k: persist.append(a) or True
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: False)

    panel._delete_profile()

    assert persist == [], "conferma rifiutata: niente persist della config (P3-27)"
    assert "annullata" in panel._status.text.lower()


def test_parser_delete_rifiutato_non_tocca_il_file(monkeypatch):
    mod = _mod(monkeypatch, "custom_parser_gui")
    panel = mod.CustomParserPanel.__new__(mod.CustomParserPanel)
    panel._result = _Status()
    panel._saved_var = types.SimpleNamespace(get=lambda: "P")
    panel._saved_map = {"P": "/tmp/p.json"}
    panel._NONE_SAVED = "(nessuno)"
    chiamate = []
    monkeypatch.setattr(mod.ParserBuilder, "delete_saved",
                        staticmethod(lambda name: chiamate.append(name) or True))
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: False)

    panel._delete_selected()

    assert chiamate == [], "conferma rifiutata: il file parser NON va eliminato (P3-27)"
    assert "annullata" in panel._result.text.lower()


# ── P3-28: Nuovo/Carica proteggono le modifiche non salvate ──────────────────────────

def _panel_con_builder(mod):
    """Pannello minimale col VERO ParserBuilder e baseline pulita (come post-__init__)."""
    panel = mod.CustomParserPanel.__new__(mod.CustomParserPanel)
    panel._result = _Status()
    panel.builder = ParserBuilder()
    panel._sync_to_builder = lambda: None        # niente widget: il builder È lo stato
    panel._saved_snapshot = panel._builder_snapshot(sync=False)
    return panel


def test_dirty_check_reale_su_builder(monkeypatch):
    mod = _mod(monkeypatch, "custom_parser_gui")
    panel = _panel_con_builder(mod)
    assert panel._has_unsaved_changes() is False          # baseline appena fotografata
    panel.builder.name = "Nuovo nome"                     # modifica REALE non salvata
    assert panel._has_unsaved_changes() is True
    panel._saved_snapshot = panel._builder_snapshot()     # "salvataggio": nuova baseline
    assert panel._has_unsaved_changes() is False


def test_nuovo_su_editor_sporco_rifiutato_conserva_tutto(monkeypatch):
    """FAIL-FIRST: pre-patch _new azzerava l'editor senza chiedere nulla."""
    mod = _mod(monkeypatch, "custom_parser_gui")
    panel = _panel_con_builder(mod)
    panel.builder.name = "LavoroNonSalvato"
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: False)

    panel._new()

    assert panel.builder.name == "LavoroNonSalvato", "rifiuto = editor INTATTO (P3-28)"
    assert "annullato" in panel._result.text.lower()


def test_nuovo_su_editor_sporco_confermato_resetta(monkeypatch):
    mod = _mod(monkeypatch, "custom_parser_gui")
    panel = _panel_con_builder(mod)
    panel.builder.name = "LavoroNonSalvato"
    panel._name_var = types.SimpleNamespace(set=lambda v: None)
    panel._reload_rows_from_builder = lambda: None
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: True)

    panel._new()

    assert panel.builder.name == ""                       # reset avvenuto
    assert panel._has_unsaved_changes() is False          # baseline riallineata


def test_nuovo_su_editor_pulito_nessun_dialogo(monkeypatch):
    """Editor senza modifiche: zero attrito — il dialogo NON deve comparire."""
    mod = _mod(monkeypatch, "custom_parser_gui")
    panel = _panel_con_builder(mod)
    panel._name_var = types.SimpleNamespace(set=lambda v: None)
    panel._reload_rows_from_builder = lambda: None
    monkeypatch.setattr(mod.gui_utils, "ask_confirm",
                        lambda *a: pytest.fail("dialogo mostrato su editor pulito"))

    panel._new()

    assert "🆕" in panel._result.text


def test_carica_su_editor_sporco_rifiutato_non_carica(monkeypatch):
    mod = _mod(monkeypatch, "custom_parser_gui")
    panel = _panel_con_builder(mod)
    panel.builder.name = "LavoroNonSalvato"
    panel._selected_path = lambda: pytest.fail("rifiuto: non si arriva alla selezione")
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: False)

    panel._load_selected()

    assert panel.builder.name == "LavoroNonSalvato"
    assert "annullato" in panel._result.text.lower()
