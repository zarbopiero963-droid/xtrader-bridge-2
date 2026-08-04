"""Whitelist per-colonna delle tendine Trasformazione/Value-map (ordine proprietario 2026-08-04).

«Le colonne esatte me le deve dire il codice»: dette.

- Le TRASFORMAZIONI (`score_to_over`/`score_to_over_ht`) producono «Over N,5» /
  «over N,5 ht» — forme che solo le value-map `markettype`/`marketname`/
  `selectionname` risolvono (docstring di `_score_to_over_ht`; test end-to-end
  canonici: SelectionName e MarketType). → whitelist Trasformazione:
  **SelectionName, MarketType, MarketName**.
- Le VALUE-MAP esistenti sono le tre del dizionario PIÙ la built-in `bettype`
  (BACK→PUNTA / LAY→BANCA) che serve la colonna BetType. → whitelist Value-map:
  **SelectionName, MarketType, MarketName, BetType**.

Via di fuga anti-comportamento-invisibile (precedente valore-fisso, decisione
proprietario 2026-08-03): se una regola SALVATA ha già transform/value-map su una
colonna fuori lista, la tendina resta visibile lì — nascondere il controllo non
disattiva la trasformazione, toglie solo il modo di vederla e ripararla.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest

from xtrader_bridge import value_maps


class _FakeCtkModule(types.ModuleType):
    """Stub minimo (stesso pattern di test_parser_panel_182): qualsiasi attributo
    diventa una classe vuota — basta per IMPORTARE il modulo GUI headless."""

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
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.custom_parser_gui")
    yield mod
    sys.modules.pop("xtrader_bridge.custom_parser_gui", None)


def test_whitelist_trasformazione_sono_le_tre_colonne_dette_dal_codice(gui):
    assert gui.TRANSFORM_COLS == frozenset({"SelectionName", "MarketType", "MarketName"})


def test_whitelist_value_map_aggiunge_bettype(gui):
    assert gui.VALUE_MAP_COLS == gui.TRANSFORM_COLS | {"BetType"}


def test_whitelist_value_map_coerente_con_le_mappe_reali(gui):
    """La whitelist non è un'opinione: ogni famiglia di value-map esistente
    (dizionario + built-in) deve avere la sua colonna in whitelist — se domani
    nasce una mappa nuova senza colonna ammessa, questo test lo dice."""
    per_colonna = {"markettype": "MarketType", "marketname": "MarketName",
                   "selectionname": "SelectionName", "bettype": "BetType"}
    # Solo API pubbliche (rilievo Fable #244): i nomi delle famiglie dizionario
    # vengono da `dizionario_value_maps([])` (righe vuote → mappe vuote ma nomi
    # presenti), i built-in da `registry()`.
    nomi_mappe = set(value_maps.registry()) | set(value_maps.dizionario_value_maps([]))
    # Rilievo GPT #244 (giro 2): se l'API tornasse {} con righe vuote, il loop
    # passerebbe con le sole built-in e la copertura sparirebbe IN SILENZIO —
    # l'assert la rende rumorosa.
    assert {"markettype", "marketname", "selectionname", "bettype"} <= nomi_mappe
    for nome in nomi_mappe:
        assert nome in per_colonna, f"value-map `{nome}` senza colonna associata"
        assert per_colonna[nome] in gui.VALUE_MAP_COLS


def test_visibilita_colonne_in_whitelist(gui):
    assert gui.colonne_avanzate_visibili("SelectionName") == (True, True)
    assert gui.colonne_avanzate_visibili("MarketType") == (True, True)
    assert gui.colonne_avanzate_visibili("MarketName") == (True, True)
    assert gui.colonne_avanzate_visibili("BetType") == (False, True)


def test_visibilita_colonne_fuori_whitelist(gui):
    for colonna in ("Provider", "EventId", "EventName", "MarketId", "SelectionId",
                    "Handicap", "Price", "MinPrice", "MaxPrice", "Points"):
        assert gui.colonne_avanzate_visibili(colonna) == (False, False), colonna


def test_via_di_fuga_regola_salvata_fuori_lista_resta_visibile(gui):
    """Un parser salvato con transform su EventId (oggi possibile) deve mostrare
    la tendina LÌ, per vederla e ripararla — mai comportamento invisibile."""
    assert gui.colonne_avanzate_visibili("EventId", transform="score_to_over") == (True, False)
    assert gui.colonne_avanzate_visibili("Price", value_map="bettype") == (False, True)
    assert gui.colonne_avanzate_visibili(
        "EventName", transform="score_to_over", value_map="marketname") == (True, True)
