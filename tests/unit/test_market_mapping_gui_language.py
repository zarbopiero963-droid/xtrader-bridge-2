"""Colonna «Lingua» del Dizionario mercati (epica #3 slice 5c — GUI).

`MarketMappingPanel` (in `name_mapping_gui`) richiede `customtkinter` (un display) e NON è
importabile headless; qui si stubba SOLO la libreria GUI, così il modulo si importa e si
esercitano i VERI metodi puri (header, `_collect_rows`, `_reload_rows`, `_append_row_widget`)
senza creare widget reali. La resa visuale della tendina resta uno smoke manuale.

Speculare a `test_name_mapping_gui_language.py` (5b) per il dizionario mercati.
"""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def gui(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    return importlib.import_module("xtrader_bridge.name_mapping_gui")


def test_market_header_ha_colonna_lingua_senza_rimuovere_le_altre(gui):
    labels = [c[0] for c in gui._MARKET_HEADER_COLUMNS]
    assert "Lingua" in labels
    # le colonne pre-esistenti restano nell'ordine (nessuna rimossa/rinominata)
    assert labels[:5] == ["Inizia dopo", "Finisce prima", "Testo mercato",
                          "Mercato (catalogo)", "Selezione (catalogo)"]


def _cell(v):
    return types.SimpleNamespace(get=lambda: v)


def _mrow(*, phrase="", market="", selection="", lang_label=""):
    return {"start_after": _cell(""), "end_before": _cell(""), "phrase": _cell(phrase),
            "market": _cell(market), "selection": _cell(selection), "language": _cell(lang_label)}


def test_collect_rows_mercati_include_language_e_agnostica(gui):
    # `_collect_rows` deve emettere la chiave `language`: valorizzata resta, «(tutte le lingue)»
    # → "" (agnostica). Le altre chiavi del contratto store restano tutte presenti.
    fake = types.SimpleNamespace(_row_widgets=[
        _mrow(phrase="gg", market="Entrambe le squadre a segno", selection="Sì", lang_label="EN"),
        _mrow(phrase="ng", market="Entrambe le squadre a segno", selection="No",
              lang_label=gui._LANGUAGE_ALL),
    ])
    rows = gui.MarketMappingPanel._collect_rows(fake)
    assert rows[0]["language"] == "EN"
    assert rows[1]["language"] == ""
    assert set(rows[0]) == {"start_after", "end_before", "phrase", "market_type",
                            "market_name", "selection_name", "language"}


def test_reload_rows_mercati_carica_language_dalle_entries(gui, monkeypatch):
    """Il load-path reale (`_reload_rows`) deve passare la `language` salvata a
    `_append_row_widget`: una regressione sul `e.get("language","")` la perderebbe."""
    calls = []
    fake = types.SimpleNamespace(
        _rows_frame=types.SimpleNamespace(winfo_children=lambda: []),
        _current="M",
        _load_cfg=lambda: {"market_mappings": {"M": []}},
        _append_row_widget=lambda *a, **k: calls.append(a),
        _row_widgets=["stale"],                         # deve essere azzerato dal metodo
    )
    monkeypatch.setattr(gui.market_mapping_store, "get_entries",
                        lambda cfg, prof: [
                            {"start_after": "M:", "end_before": "\n", "phrase": "gg",
                             "market_name": "Entrambe le squadre a segno",
                             "selection_name": "Sì", "language": "EN"},
                            {"start_after": "M:", "end_before": "\n", "phrase": "ng",
                             "market_name": "Entrambe le squadre a segno",
                             "selection_name": "No"}])   # senza lingua → ""
    gui.MarketMappingPanel._reload_rows(fake)
    assert fake._row_widgets == []                       # tabella ridisegnata da zero
    # firma posizionale: (start_after, end_before, phrase, market_name, selection_name, language)
    assert calls[0][5] == "EN"                           # lingua salvata caricata
    assert calls[1][5] == ""                             # entry senza lingua → agnostica


def _rich_ctk():
    """Fake `customtkinter` più ricco: i widget espongono i metodi realmente chiamati da
    `MarketMappingPanel._append_row_widget` (insert/pack/configure/StringVar.get) e ogni
    `CTkOptionMenu` registra i suoi `values`, così si esercita il VERO costruttore di riga e
    si ispeziona la tendina Lingua."""
    class _RichModule(types.ModuleType):
        def __getattr__(self, name):
            cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
            setattr(self, name, cls)
            return cls

    mod = _RichModule("customtkinter")
    created = []

    class _W:
        def __init__(self, *a, **k):
            self._kw = k

        def pack(self, *a, **k):
            return self

        def configure(self, *a, **k):
            if "values" in k:
                self.values = list(k["values"])
            return self

    class _Entry(_W):
        def insert(self, *a, **k):
            pass

        def get(self):
            return ""

    class _StringVar:
        def __init__(self, value="", *a, **k):
            self._v = value

        def get(self):
            return self._v

        def set(self, v):
            self._v = v

    class _OptionMenu(_W):
        def __init__(self, master=None, *, variable=None, values=None, **k):
            super().__init__()
            self.variable = variable
            self.values = list(values) if values is not None else None
            created.append(self)

    for name in ("CTkFrame", "CTkButton", "CTkLabel"):
        setattr(mod, name, _W)
    mod.CTkEntry = _Entry
    mod.CTkOptionMenu = _OptionMenu
    mod.StringVar = _StringVar
    mod._created_menus = created
    return mod


def _mk_panel_fake(mod):
    """Fake `self` minimale per esercitare il VERO `_append_row_widget` del pannello mercati."""
    return types.SimpleNamespace(
        _rows_frame=object(), _row_widgets=[], _markets=[],
        _selections_for=mod.MarketMappingPanel._selections_for,   # staticmethod reale (mercato "" → [])
        _on_row_market_change=lambda r: None, _delete_row=lambda r: None)


def test_append_row_widget_mercati_costruisce_tendina_lingua(monkeypatch):
    """Il VERO `_append_row_widget` (mercati) costruisce la tendina Lingua con ESATTAMENTE
    [«(tutte le lingue)», IT, EN, ES] e la inizializza alla lingua passata, registrandola nei refs."""
    rich = _rich_ctk()
    monkeypatch.setitem(sys.modules, "customtkinter", rich)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    fake = _mk_panel_fake(mod)
    mod.MarketMappingPanel._append_row_widget(fake, language="EN")
    assert len(fake._row_widgets) == 1
    assert fake._row_widgets[0]["language"].get() == "EN"
    lang_menus = [m for m in rich._created_menus if m.values and m.values[0] == mod._LANGUAGE_ALL]
    assert len(lang_menus) == 1
    assert lang_menus[0].values == [mod._LANGUAGE_ALL, "IT", "EN", "ES"]
    assert lang_menus[0].variable.get() == "EN"


def test_append_row_widget_mercati_default_agnostica(monkeypatch):
    """Senza `language` (default), la tendina si inizializza su «(tutte le lingue)» (agnostica)."""
    rich = _rich_ctk()
    monkeypatch.setitem(sys.modules, "customtkinter", rich)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    fake = _mk_panel_fake(mod)
    mod.MarketMappingPanel._append_row_widget(fake)
    assert fake._row_widgets[0]["language"].get() == mod._LANGUAGE_ALL


def test_append_row_widget_mercati_lingua_sconosciuta_preservata(monkeypatch):
    """Resilienza (come nomi 5c/CodeRabbit #25): un valore `language` fuori da IT/EN/ES/agnostico
    (dato storico) NON deve essere perso silenziosamente dalla GUI — il var lo conserva, la tendina
    lo espone come opzione extra, e sopravvive al round-trip `_collect_rows`. La validità la impone
    lo store al salvataggio (fail-closed sui typo), non la GUI."""
    rich = _rich_ctk()
    monkeypatch.setitem(sys.modules, "customtkinter", rich)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    fake = _mk_panel_fake(mod)
    mod.MarketMappingPanel._append_row_widget(fake, language="FR")
    assert fake._row_widgets[0]["language"].get() == "FR"
    # la tendina Lingua espone "FR" come opzione extra (non lo scarta)
    lang_menus = [m for m in rich._created_menus if m.values and m.values[0] == mod._LANGUAGE_ALL]
    assert "FR" in lang_menus[0].values
    # e sopravvive al round-trip verso lo store (nessuna perdita silenziosa lato GUI)
    rows = mod.MarketMappingPanel._collect_rows(fake)
    assert rows[0]["language"] == "FR"
