"""Rinomina display «Provider» → «Come lo scrive il canale» nel Dizionario nomi squadra (#293).

È SOLO l'etichetta VISIBILE della colonna a cambiare: la **chiave dati** nello store resta
`provider` e la colonna **CSV «Provider»** (anagrafica) è invariata. Verifica le funzioni/costanti
REALI del progetto (store puro + costante GUI via import con `customtkinter` stubbato).
"""

import importlib
import pathlib
import sys
import types

import pytest

from xtrader_bridge import name_mapping_store as nms
from xtrader_bridge.csv_writer import CSV_HEADER


def test_store_usa_ancora_la_chiave_dati_provider():
    # Il round-trip set/get preserva la chiave dati `provider` (il rename è solo display).
    cfg = nms.set_entries(
        {}, "P", [{"betfair": "Liverpool", "provider": "Liverpool FC", "sport": "Calcio"}])
    entries = nms.get_entries(cfg, "P")
    assert entries and entries[0]["provider"] == "Liverpool FC"
    assert entries[0]["betfair"] == "Liverpool"


def test_csv_provider_anagrafica_invariata():
    # La colonna CSV «Provider» (anagrafica, DIVERSA dall'alias del canale) NON è toccata.
    assert "Provider" in CSV_HEADER


@pytest.fixture
def gui_mod(monkeypatch):
    """Importa `name_mapping_gui` con `customtkinter` stubbato (modulo GUI, no display)."""
    fake = types.ModuleType("customtkinter")
    fake.__getattr__ = lambda _n: object
    monkeypatch.setitem(sys.modules, "customtkinter", fake)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    return importlib.import_module("xtrader_bridge.name_mapping_gui")


def test_colonna_rinominata_nel_dizionario_nomi(gui_mod):
    assert gui_mod._CHANNEL_ALIAS_COLUMN == "Come lo scrive il canale"


def test_vecchia_etichetta_provider_non_piu_header_di_colonna(gui_mod):
    # Guardia anti-ripristino: la vecchia tupla header `("Provider", 240)` non deve tornare.
    src = pathlib.Path(gui_mod.__file__).read_text(encoding="utf-8")
    assert '("Provider", 240)' not in src
    assert "Come lo scrive il canale" in src
