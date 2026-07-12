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
