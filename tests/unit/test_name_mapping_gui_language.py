"""Colonna «Lingua» del Dizionario nomi squadra (epica #3 slice 5b — GUI).

`name_mapping_gui` richiede `customtkinter` (un display) e NON è importabile headless; qui
si stubba SOLO la libreria GUI con classi reali vuote, così il modulo si importa e si
esercitano i VERI helper/metodi puri (etichette lingua, header, `_collect_rows`) senza
creare widget. La resa visuale della tendina resta uno smoke manuale.
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


def test_helpers_lingua_round_trip(gui):
    # Agnostico ("") <-> etichetta «(tutte le lingue)»; una lingua valorizzata resta invariata.
    assert gui._language_to_label("") == gui._LANGUAGE_ALL
    assert gui._language_to_label("EN") == "EN"
    assert gui._label_to_language(gui._LANGUAGE_ALL) == ""
    assert gui._label_to_language("IT") == "IT"


def test_header_ha_colonna_lingua_senza_rimuovere_le_altre(gui):
    labels = [c[0] for c in gui._HEADER_COLUMNS]
    assert "Lingua" in labels
    # le colonne pre-esistenti restano nell'ordine (nessuna rimossa/rinominata)
    assert labels[:5] == ["Country (opz.)", "Betfair / XTrader",
                          gui._CHANNEL_ALIAS_COLUMN, "Sport", "Tipo"]


def _cell(v):
    return types.SimpleNamespace(get=lambda: v)


def _row(*, betfair="", provider="", lang_label=""):
    return {"country": _cell(""), "betfair": _cell(betfair), "provider": _cell(provider),
            "sport": _cell(""), "entity_type": _cell(""), "language": _cell(lang_label)}


def test_collect_rows_include_language_e_agnostica(gui):
    # `_collect_rows` deve emettere la chiave `language`: valorizzata resta, «(tutte le lingue)»
    # → "" (agnostica). Contratto store invariato (le altre chiavi restano tutte presenti).
    fake = types.SimpleNamespace(_row_widgets=[
        _row(betfair="Liverpool", provider="Reds", lang_label="EN"),
        _row(betfair="Inter", provider="Nerazzurri", lang_label=gui._LANGUAGE_ALL),
    ])
    rows = gui.NameMappingPanel._collect_rows(fake)
    assert rows[0]["language"] == "EN"
    assert rows[1]["language"] == ""
    assert set(rows[0]) == {"country", "betfair", "provider", "sport", "entity_type", "language"}


def test_reload_rows_carica_language_dalle_entries(gui, monkeypatch):
    """Il load-path reale (`_reload_rows`) deve passare la `language` salvata a
    `_append_row_widget`: una regressione sul `e.get("language","")` la perderebbe silenziosamente."""
    calls = []
    fake = types.SimpleNamespace(
        _rows_frame=types.SimpleNamespace(winfo_children=lambda: []),
        # P3-30 #76: _reload_rows ora azzera lo status a ogni render
        _status=types.SimpleNamespace(configure=lambda **k: None),
        _current="P",
        _load_cfg=lambda: {"name_mappings": {"P": []}},
        _append_row_widget=lambda *a, **k: calls.append(a),
        _row_widgets=["stale"],                         # deve essere azzerato dal metodo
    )
    monkeypatch.setattr(gui.name_mapping_store, "get_entries",
                        lambda cfg, prof: [{"betfair": "Liverpool", "language": "EN"},
                                           {"betfair": "Inter"}])   # senza lingua → ""
    gui.NameMappingPanel._reload_rows(fake)
    assert fake._row_widgets == []                      # tabella ridisegnata da zero
    # firma posizionale: (country, betfair, provider, sport, entity_type, language)
    assert [c[1] for c in calls] == ["Liverpool", "Inter"]
    assert calls[0][5] == "EN"                          # lingua salvata caricata
    assert calls[1][5] == ""                            # entry senza lingua → agnostica


def _rich_ctk():
    """Fake `customtkinter` più ricco: i widget espongono i metodi realmente chiamati da
    `_append_row_widget` (insert/pack/StringVar.get) e ogni `CTkOptionMenu` registra i suoi
    `values`, così si può esercitare il VERO costruttore di riga e ispezionare la tendina Lingua."""
    class _RichModule(types.ModuleType):
        # fallback: qualunque widget NON definito esplicitamente (CTkToplevel, CTkScrollableFrame…)
        # diventa una classe vuota subclassabile, così l'import del modulo GUI non rompe.
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


def test_append_row_widget_costruisce_tendina_lingua(monkeypatch):
    """Il VERO `_append_row_widget` deve costruire la tendina Lingua con ESATTAMENTE
    [«(tutte le lingue)», IT, EN, ES] e inizializzarla alla lingua passata, registrandola nei refs."""
    rich = _rich_ctk()
    monkeypatch.setitem(sys.modules, "customtkinter", rich)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    fake = types.SimpleNamespace(_rows_frame=object(), _row_widgets=[],
                                 _delete_row=lambda r: None)
    mod.NameMappingPanel._append_row_widget(fake, betfair="Liverpool", language="EN")
    # la riga è registrata con la var lingua inizializzata a "EN"
    assert len(fake._row_widgets) == 1
    assert fake._row_widgets[0]["language"].get() == "EN"
    # la tendina Lingua ha esattamente i valori attesi (agnostica + IT/EN/ES, nessun "" duplicato)
    lang_menus = [m for m in rich._created_menus if m.values and m.values[0] == mod._LANGUAGE_ALL]
    assert len(lang_menus) == 1
    assert lang_menus[0].values == [mod._LANGUAGE_ALL, "IT", "EN", "ES"]
    assert lang_menus[0].variable.get() == "EN"


def test_append_row_widget_default_lingua_agnostica(monkeypatch):
    """Senza `language` (default), la tendina si inizializza su «(tutte le lingue)» (agnostica)."""
    rich = _rich_ctk()
    monkeypatch.setitem(sys.modules, "customtkinter", rich)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    fake = types.SimpleNamespace(_rows_frame=object(), _row_widgets=[],
                                 _delete_row=lambda r: None)
    mod.NameMappingPanel._append_row_widget(fake)
    assert fake._row_widgets[0]["language"].get() == mod._LANGUAGE_ALL


def test_append_row_widget_lingua_sconosciuta_preservata(monkeypatch):
    """Resilienza (CodeRabbit #25): un valore `language` fuori da IT/EN/ES/agnostico (dato storico
    o di una lingua rimossa) NON deve essere perso silenziosamente dalla GUI — il var lo conserva
    e sopravvive al round-trip `_collect_rows`. La VALIDITÀ la impone lo store al salvataggio
    (slice 5b: fail-closed sui typo), non la GUI, che non deve mutare in silenzio il dato utente."""
    rich = _rich_ctk()
    monkeypatch.setitem(sys.modules, "customtkinter", rich)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    fake = types.SimpleNamespace(_rows_frame=object(), _row_widgets=[],
                                 _delete_row=lambda r: None)
    mod.NameMappingPanel._append_row_widget(fake, betfair="X", language="FR")
    # il valore sconosciuto resta nel var (non forzato ad agnostica)
    assert fake._row_widgets[0]["language"].get() == "FR"
    # e sopravvive al round-trip verso lo store (nessuna perdita silenziosa lato GUI)
    rows = mod.NameMappingPanel._collect_rows(fake)
    assert rows[0]["language"] == "FR"
