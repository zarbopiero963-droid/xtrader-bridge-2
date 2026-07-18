"""P3-30 + P3-31 audit #76 — cap di render sulle liste grandi + delete parser per path.

- **P3-30**: i pannelli Dizionario nomi/mercati e «🧹 Nomi squadra» creavano UN widget
  per riga senza cap: migliaia di righe → thread Tk congelato. VINCOLO CRITICO del fix:
  `_collect_rows` legge i widget al Salva — il cap di render deve conservare la coda
  (`_overflow_entries`) e riconsegnarla INTATTA, o il Salva troncherebbe il profilo.
- **P3-31**: la lista parser della GUI mappa nome-NEL-FILE → path, ma l'eliminazione
  usava `delete_saved(name)` che RISOLVE il path dal nome (`_safe_filename`): con un
  file rinominato a mano cancellava un file DIVERSO da quello selezionato.

Fix testato: `_ROW_RENDER_CAP=500` con coda conservata e avviso ambra; cap solo-display
sui nomi noti col totale vero; `custom_parser.delete_parser_file(path)` con guardia
anti-traversal (realpath dentro la cartella parser) + `ParserBuilder.delete_saved_path`
+ GUI che elimina per path. File REALI in tmp per il delete; store reali per le righe."""

import importlib
import sys
import types

import pytest

from xtrader_bridge import custom_parser, name_mapping_store
from xtrader_bridge.parser_builder import ParserBuilder


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


class _Status:
    text = ""
    color = ""

    def configure(self, **k):
        self.text = k.get("text", self.text)
        self.color = k.get("text_color", self.color)


def _mod(monkeypatch, name):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, f"xtrader_bridge.{name}", raising=False)
    return importlib.import_module(f"xtrader_bridge.{name}")


# ── P3-30: cap con coda conservata (Dizionario nomi, store REALE) ────────────────────

def _cfg_con_righe(n):
    """Config REALE con un profilo di `n` righe (store puro, nessun mock)."""
    cfg = name_mapping_store.add_profile({}, "GRANDE")
    rows = [{"country": "", "betfair": f"Team {i}", "provider": f"team {i}",
             "sport": "", "entity_type": "", "language": ""} for i in range(n)]
    return name_mapping_store.set_entries(cfg, "GRANDE", rows)


def _name_panel(mod):
    panel = mod.NameMappingPanel.__new__(mod.NameMappingPanel)
    panel._status = _Status()
    panel._current = "GRANDE"
    panel._row_widgets = []
    panel._rows_frame = types.SimpleNamespace(winfo_children=lambda: [])
    appese = []
    panel._append_row_widget = lambda *a, **k: appese.append(a)
    return panel, appese


def test_render_cappato_e_coda_conservata(monkeypatch):
    """FAIL-FIRST: pre-patch 750 righe = 750 widget (freeze) e nessuna coda."""
    mod = _mod(monkeypatch, "name_mapping_gui")
    panel, appese = _name_panel(mod)

    mod.NameMappingPanel._reload_rows(panel, _cfg_con_righe(750))

    assert len(appese) == mod._ROW_RENDER_CAP == 500      # widget cappati
    assert len(panel._overflow_entries) == 250            # coda IN MEMORIA, non persa
    assert panel._overflow_entries[0]["betfair"] == "Team 500"   # ordine preservato
    assert "500" in panel._status.text and "750" in panel._status.text
    assert panel._status.color == "#ffa726"               # avviso ambra


def test_collect_rows_riconsegna_la_coda_intatta(monkeypatch):
    """Il VINCOLO del fix: il Salva deve conservare l'intero profilo — le righe oltre
    il cap tornano da _collect_rows in coda, identiche."""
    mod = _mod(monkeypatch, "name_mapping_gui")
    panel, _ = _name_panel(mod)
    mod.NameMappingPanel._reload_rows(panel, _cfg_con_righe(750))

    raccolte = mod.NameMappingPanel._collect_rows(panel)   # _row_widgets è vuoto (stub)

    assert len(raccolte) == 250                            # tutta la coda riconsegnata
    assert raccolte[0]["provider"] == "team 500"
    assert raccolte[-1]["provider"] == "team 749"


def test_sotto_il_cap_nessun_avviso(monkeypatch):
    mod = _mod(monkeypatch, "name_mapping_gui")
    panel, appese = _name_panel(mod)

    mod.NameMappingPanel._reload_rows(panel, _cfg_con_righe(10))

    assert len(appese) == 10
    assert panel._overflow_entries == []
    assert panel._status.text == ""                        # niente avviso spurio


def test_market_panel_stesso_cap(monkeypatch):
    """Il pannello mercati usa lo stesso cap (stub dello store: 600 entry)."""
    mod = _mod(monkeypatch, "name_mapping_gui")
    panel = mod.MarketMappingPanel.__new__(mod.MarketMappingPanel)
    panel._status = _Status()
    panel._current = "P"
    panel._row_widgets = []
    panel._rows_frame = types.SimpleNamespace(winfo_children=lambda: [])
    appese = []
    panel._append_row_widget = lambda *a, **k: appese.append(a)
    entries = [{"start_after": f"s{i}", "end_before": "", "phrase": "",
                "market_name": "", "selection_name": "", "language": ""}
               for i in range(600)]
    monkeypatch.setattr(mod.market_mapping_store, "get_entries", lambda cfg, name: entries)

    mod.MarketMappingPanel._reload_rows(panel, {"qualunque": True})

    assert len(appese) == 500 and len(panel._overflow_entries) == 100
    out = mod.MarketMappingPanel._collect_rows(panel)
    assert len(out) == 100 and out[0]["start_after"] == "s500"


# ── P3-30: nomi noti (cap solo display, totale vero nel contatore) ───────────────────

def test_nomi_noti_cap_display(monkeypatch):
    mod = _mod(monkeypatch, "known_teams_gui")
    panel = mod.KnownTeamsPanel.__new__(mod.KnownTeamsPanel)
    panel._counts = _Status()
    panel._clear_rows = lambda: None
    panel._sport = types.SimpleNamespace(get=lambda: mod._SPORT_ALL)
    panel._teams_provider = lambda sport: [{"display_name": f"T{i}"} for i in range(620)]
    appese = []
    panel._append_row = lambda team: appese.append(team)

    mod.KnownTeamsPanel._refresh(panel)

    assert len(appese) == 500                              # display cappato
    assert "620" in panel._counts.text and "500" in panel._counts.text   # totale VERO


# ── P3-31: eliminazione per PATH con guardia anti-traversal (file REALI) ─────────────

def test_delete_per_path_rimuove_il_file_rinominato(tmp_path):
    """FAIL-FIRST del bug: file rinominato a mano (`pippo.json` che contiene il parser
    «Parser A»). Il delete per NOME risolverebbe `parser_a.json` (un ALTRO file);
    quello per PATH rimuove esattamente il file selezionato."""
    rinominato = tmp_path / "pippo.json"
    rinominato.write_text("{}", encoding="utf-8")
    altro = tmp_path / "parser_a.json"                    # l'omonimo che NON va toccato
    altro.write_text("{}", encoding="utf-8")

    removed = custom_parser.delete_parser_file(str(rinominato), dir_path=str(tmp_path))

    assert removed is True
    assert not rinominato.exists()                        # rimosso QUELLO selezionato
    assert altro.exists()                                 # l'omonimo è intatto


def test_delete_per_path_fuori_cartella_rifiutato(tmp_path):
    fuori = tmp_path / "fuori.json"
    fuori.write_text("{}", encoding="utf-8")
    dentro = tmp_path / "parsers"
    dentro.mkdir()
    with pytest.raises(ValueError):
        custom_parser.delete_parser_file(str(fuori), dir_path=str(dentro))
    assert fuori.exists()                                  # mai toccato
    with pytest.raises(ValueError):                        # traversal esplicito
        custom_parser.delete_parser_file(str(dentro / ".." / "fuori.json"),
                                         dir_path=str(dentro))
    with pytest.raises(ValueError):                        # estensione sbagliata
        custom_parser.delete_parser_file(str(dentro / "x.txt"), dir_path=str(dentro))


def test_delete_per_path_assente_false(tmp_path):
    assert custom_parser.delete_parser_file(str(tmp_path / "manca.json"),
                                            dir_path=str(tmp_path)) is False


def test_builder_e_gui_usano_il_path(monkeypatch, tmp_path):
    """`ParserBuilder.delete_saved_path` passa dal file-delete; la GUI elimina col path
    della mappa (quello selezionato in lista), mai col nome."""
    f = tmp_path / "salvato.json"
    f.write_text("{}", encoding="utf-8")
    assert ParserBuilder.delete_saved_path(str(f), dir_path=str(tmp_path)) is True

    mod = _mod(monkeypatch, "custom_parser_gui")
    panel = mod.CustomParserPanel.__new__(mod.CustomParserPanel)
    panel._result = _Status()
    panel._saved_var = types.SimpleNamespace(get=lambda: "Parser A")
    panel._saved_map = {"Parser A": "/dir/pippo.json"}    # nome-nel-file → path REALE
    panel._NONE_SAVED = "(nessuno)"
    panel._refresh_saved = lambda: None
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a: True)
    ricevuti = []
    monkeypatch.setattr(mod.ParserBuilder, "delete_saved_path",
                        staticmethod(lambda path, dir_path=None: ricevuti.append(path) or True))

    mod.CustomParserPanel._delete_selected(panel)

    assert ricevuti == ["/dir/pippo.json"], "la GUI deve eliminare per PATH (P3-31)"
