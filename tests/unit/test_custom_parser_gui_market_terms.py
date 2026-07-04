"""Test della glue «tendine Betfair MarketType/MarketName/SelectionName» del Parser (#283 PR 13).

`custom_parser_gui` importa `customtkinter` (un display) e non è importabile headless: qui
stubbiamo la libreria GUI con widget no-op (ma `StringVar` e `CTkComboBox` FINTI ma funzionanti,
così testiamo davvero i `values` della tendina e il valore preservato), ed esercitiamo i VERI
metodi di `CustomParserPanel` su un `self` finto. La logica sotto test è quella reale: la riga
MarketType/MarketName/SelectionName crea una tendina EDITABILE coi valori del provider filtrati
per sport, il testo libero (valore non ancora sincronizzato) è preservato, e `_refresh_term_combos`
riaggiorna i valori mantenendo la selezione. Fail-safe: provider assente / sync in corso → nessun
suggerimento, testo libero comunque digitabile.
"""

import importlib
import sys
import types

import pytest

from xtrader_bridge.betfair.dictionary_viewer import DictionaryBusy
from xtrader_bridge.custom_parser import FieldRule


class _FakeStringVar:
    def __init__(self, value="", **_k):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _FakeCombo:
    # Tendina finta ma ISPEZIONABILE: registra i `values` (e li aggiorna in configure()).
    def __init__(self, *a, **k):
        self.variable = k.get("variable")
        self.values = list(k.get("values") or [])

    def configure(self, **k):
        if "values" in k:
            self.values = list(k["values"])

    def pack(self, *a, **k):
        return self

    def __getattr__(self, _n):
        return lambda *a, **k: None


class _Noop:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: _Noop()


class _FakeCtkModule(types.ModuleType):
    StringVar = _FakeStringVar
    CTkComboBox = _FakeCombo

    def __getattr__(self, name):       # ogni altro widget → no-op
        return _Noop


@pytest.fixture()
def gui_mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.custom_parser_gui")
    return mod


_TERMS = {
    "market_types": ["MATCH_ODDS", "OVER_UNDER_25"],
    "market_names": ["Esito Finale", "Over/Under 2,5"],
    "selection_names": ["Over 2,5", "Under 2,5"],
}


def _fake_self(gui_mod, *, provider=None, sport="Calcio", terms=None):
    fake = types.SimpleNamespace(
        _market_terms_provider=provider if provider is not None else (lambda s=None: _TERMS),
        _market_terms=terms if terms is not None else dict(_TERMS),
        _rows=[],
        _rows_frame=_Noop(),
        _providers=[],
        _transforms=[],
        _value_maps=[],
        _sport_var=_FakeStringVar(sport),
        _SPORT_UNSPECIFIED=gui_mod.CustomParserPanel._SPORT_UNSPECIFIED,
    )
    Panel = gui_mod.CustomParserPanel
    for name in ("_add_row", "_fetch_market_terms", "_term_values",
                 "_refresh_term_combos", "_label_to_sport"):
        setattr(fake, name, types.MethodType(getattr(Panel, name), fake))
    return fake


def test_add_row_selectionname_crea_tendina_editabile(gui_mod):
    fake = _fake_self(gui_mod)
    fake._add_row(FieldRule(target="SelectionName", fixed_value="Over 2,5"))
    refs = fake._rows[-1]
    combo = refs["term_combo"]
    assert combo.values == ["", "Over 2,5", "Under 2,5"]     # valori del provider (per sport)
    assert refs["fixed_value"].get() == "Over 2,5"           # valore corrente preservato
    assert refs["target"] == "SelectionName"


def test_add_row_markettype_e_marketname(gui_mod):
    fake = _fake_self(gui_mod)
    fake._add_row(FieldRule(target="MarketType"))
    fake._add_row(FieldRule(target="MarketName"))
    assert fake._rows[0]["term_combo"].values == ["", "MATCH_ODDS", "OVER_UNDER_25"]
    assert fake._rows[1]["term_combo"].values == ["", "Esito Finale", "Over/Under 2,5"]


def test_add_row_preserva_valore_non_sincronizzato(gui_mod):
    # Un valore digitato NON presente tra i suggerimenti resta in lista (no fail-closed).
    fake = _fake_self(gui_mod)
    fake._add_row(FieldRule(target="MarketType", fixed_value="ANYTHING_ELSE"))
    combo = fake._rows[-1]["term_combo"]
    assert "ANYTHING_ELSE" in combo.values
    assert fake._rows[-1]["fixed_value"].get() == "ANYTHING_ELSE"


def test_add_row_altra_colonna_resta_entry(gui_mod):
    # Una colonna non-term (es. Price) NON crea una tendina term (resta Entry: no term_combo).
    fake = _fake_self(gui_mod)
    fake._add_row(FieldRule(target="Price"))
    assert "term_combo" not in fake._rows[-1]


def test_fetch_market_terms_provider_assente(gui_mod):
    fake = _fake_self(gui_mod, provider=False)   # provider non callable
    fake._market_terms_provider = None
    out = fake._fetch_market_terms()
    assert out == {"market_types": [], "market_names": [], "selection_names": []}


def test_fetch_market_terms_sync_in_corso(gui_mod):
    def _busy(sport=None):
        raise DictionaryBusy()
    fake = _fake_self(gui_mod, provider=_busy)
    out = fake._fetch_market_terms()               # nessun crash, liste vuote
    assert out == {"market_types": [], "market_names": [], "selection_names": []}


def test_fetch_market_terms_passa_lo_sport(gui_mod):
    seen = {}

    def _provider(sport=None):
        seen["sport"] = sport
        return _TERMS
    fake = _fake_self(gui_mod, provider=_provider, sport="Tennis")
    fake._fetch_market_terms()
    assert seen["sport"] == "Tennis"               # filtro per lo sport del parser


def test_fetch_market_terms_sport_agnostico_passa_none(gui_mod):
    seen = {}

    def _provider(sport=None):
        seen["sport"] = sport
        return _TERMS
    fake = _fake_self(gui_mod, provider=_provider, sport="(non specificato)")
    fake._fetch_market_terms()
    assert seen["sport"] is None                   # "" agnostico → tutti gli sport


def test_refresh_term_combos_riaggiorna_preservando_selezione(gui_mod):
    # Cambia i termini disponibili (es. nuova sync o cambio sport): i combo si aggiornano ma
    # il valore corrente resta (anche se non più tra i suggerimenti).
    fake = _fake_self(gui_mod)
    fake._add_row(FieldRule(target="SelectionName", fixed_value="X vecchio"))
    fake._market_terms_provider = lambda s=None: {
        "market_types": [], "market_names": [], "selection_names": ["Sì", "No"]}
    fake._refresh_term_combos()
    combo = fake._rows[-1]["term_combo"]
    assert combo.values == ["", "Sì", "No", "X vecchio"]    # nuovi valori + selezione preservata
    assert fake._rows[-1]["fixed_value"].get() == "X vecchio"
