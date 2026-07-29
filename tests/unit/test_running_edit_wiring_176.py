"""Il CABLAGGIO dell'avviso «bridge ATTIVO» nelle finestre (issue #176).

La logica pura sta in `gui_utils` ed e' coperta a parte. Qui si verifica la meta' che
in questa serie e' gia' sfuggita due volte (#171, #172): **helper corretto, finestra che
non lo usa**. Si esegue il metodo REALE di salvataggio su un `self` finto — niente
`inspect.getsource`, che direbbe verde anche se il risultato venisse buttato via.
"""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo e' una classe reale vuota, cosi' le
    `class Panel(ctk.CTkFrame)` si importano headless."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


def _importa(monkeypatch, modulo):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, f"xtrader_bridge.{modulo}", raising=False)
    return importlib.import_module(f"xtrader_bridge.{modulo}")


class _Widget:
    """Widget di stato finto che REGISTRA il testo con cui viene configurato."""

    def __init__(self):
        self.testi = []

    def configure(self, text=None, **k):
        self.testi.append(str(text))


def _self_persist(*, running):
    """`self` finto per un `_persist` reale: salvataggio riuscito, nessun reload."""
    return types.SimpleNamespace(
        _status=_Widget(),
        _on_saved=None,
        _is_running=(lambda: running),
        _reload=lambda *a, **k: None,
        _reload_profiles=lambda *a, **k: None,
    )


@pytest.mark.parametrize("modulo,classe", [
    ("provider_gui", "ProviderPanel"),
    ("name_mapping_gui", "NameMappingPanel"),
    ("name_mapping_gui", "MarketMappingPanel"),
])
def test_il_persist_REALE_accoda_l_avviso_col_bridge_attivo(monkeypatch, modulo, classe):
    """Il metodo di salvataggio vero deve mostrare l'avviso, e solo col bridge attivo.

    Si esercita `_persist` di ciascun pannello su un `self` finto, monkeypatchando la
    scrittura su disco a «riuscita»: interessa cosa finisce nel widget di stato, non l'I/O."""
    mod = _importa(monkeypatch, modulo)
    monkeypatch.setattr(mod.config_store, "save_config", lambda cfg, path=None: (cfg, True))
    persist = getattr(mod, classe)._persist

    acceso = _self_persist(running=True)
    persist(acceso, {}, "✅ Salvato.", "❌ Fallito.")
    testo_acceso = acceso._status.testi[-1]

    spento = _self_persist(running=False)
    persist(spento, {}, "✅ Salvato.", "❌ Fallito.")
    testo_spento = spento._status.testi[-1]

    assert "✅ Salvato." in testo_acceso, testo_acceso
    assert "Bridge ATTIVO" in testo_acceso, (
        f"{classe}: l'avviso non arriva al widget — helper corretto ma finestra che non lo usa")
    # e il contrasto che rende il test non vacuo: da fermo il messaggio e' INVARIATO
    assert testo_spento == "✅ Salvato.", testo_spento


@pytest.mark.parametrize("modulo,classe", [
    ("provider_gui", "ProviderPanel"),
    ("name_mapping_gui", "NameMappingPanel"),
    ("name_mapping_gui", "MarketMappingPanel"),
    ("name_mapping_gui", "MappingPanel"),
    ("source_chats_gui", "SourceChatsPanel"),
    ("custom_parser_gui", "CustomParserPanel"),
    ("guided_mapping_gui", "GuidedMappingPanel"),
])
def test_ogni_pannello_ACCETTA_la_sonda(monkeypatch, modulo, classe):
    """Contratto della firma: senza il parametro, `app.py` non potrebbe iniettare nulla e
    l'avviso non comparirebbe MAI, in silenzio. `inspect.signature` guarda il callable
    reale, non il testo del sorgente, quindi non si rompe per una riformattazione."""
    import inspect
    mod = _importa(monkeypatch, modulo)
    firma = inspect.signature(getattr(mod, classe).__init__)
    assert "is_running" in firma.parameters, f"{classe}: {list(firma.parameters)}"


def test_il_contenitore_INOLTRA_la_sonda_a_tutte_e_tre_le_schede(monkeypatch):
    """`MappingPanel` incapsula tre schede (Calcio, Mercati, Mapping guidato). Se la sonda
    arrivasse solo ad alcune, l'avviso comparirebbe in una scheda e non nelle sorelle —
    incoerenza peggiore sia di averlo ovunque sia di non averlo affatto."""
    mod = _importa(monkeypatch, "name_mapping_gui")
    visti = {}

    def _spia(nome):
        def _fake(master=None, **k):
            visti[nome] = k.get("is_running")
            return types.SimpleNamespace(pack=lambda **kk: None)
        return _fake

    monkeypatch.setattr(mod, "NameMappingPanel", _spia("calcio"))
    monkeypatch.setattr(mod, "MarketMappingPanel", _spia("mercati"))
    # `MappingPanel.__init__` importa GuidedMappingPanel LOCALMENTE (`from .guided_mapping_gui
    # import ...`), quindi l'import risolve via `sys.modules` al momento della chiamata:
    # patchare l'attributo su un riferimento-modulo preso prima non e' deterministico in suite
    # completa, dove un altro test puo' aver gia' importato/ripristinato quel modulo. Si
    # sostituisce direttamente la voce in `sys.modules` (monkeypatch la ripristina a fine test).
    finto_gmg = types.ModuleType("xtrader_bridge.guided_mapping_gui")
    finto_gmg.GuidedMappingPanel = _spia("guidato")
    monkeypatch.setitem(sys.modules, "xtrader_bridge.guided_mapping_gui", finto_gmg)

    sonda = object()
    tabs = types.SimpleNamespace(add=lambda nome: None, pack=lambda **k: None)
    monkeypatch.setattr(mod.ctk, "CTkTabview", lambda master: tabs, raising=False)
    # istanza REALE non inizializzata: `super().__init__` dentro `MappingPanel` richiede un
    # oggetto della classe, non un namespace finto.
    finto = object.__new__(mod.MappingPanel)
    monkeypatch.setattr(mod.ctk.CTkFrame, "__init__", lambda self, *a, **k: None, raising=False)

    mod.MappingPanel.__init__(finto, None, is_running=sonda)

    assert set(visti) == {"calcio", "mercati", "guidato"}, visti
    for nome, ricevuta in visti.items():
        assert ricevuta is sonda, f"la scheda «{nome}» non ha ricevuto la sonda: {ricevuta!r}"
