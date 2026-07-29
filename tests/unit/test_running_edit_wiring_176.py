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
])
def test_anche_il_ramo_FALLITO_avvisa_e_non_si_contraddice(monkeypatch, modulo, classe):
    """Il ramo d'errore, che il primo giro di test non esercitava (rilievo Fugu Ultra #177).

    Due cose insieme: l'avviso deve arrivare **anche** quando il salvataggio fallisce (il
    bridge e' attivo comunque, l'informazione serve lo stesso), e non deve **contraddire**
    l'errore. La versione precedente diceva «la modifica e' salvata» accanto a «FALLITO»."""
    mod = _importa(monkeypatch, modulo)
    monkeypatch.setattr(mod.config_store, "save_config", lambda cfg, path=None: (cfg, False))
    persist = getattr(mod, classe)._persist

    finto = _self_persist(running=True)
    persist(finto, {}, "✅ Salvato.", "❌ Salvataggio FALLITO.")
    testo = finto._status.testi[-1]

    assert testo.startswith("❌ Salvataggio FALLITO."), testo
    assert "Bridge ATTIVO" in testo, f"{classe}: nessun avviso sul ramo fallito — {testo}"
    coda = testo[len("❌ Salvataggio FALLITO."):]
    assert "salvat" not in coda.lower(), (
        f"{classe}: l'avviso afferma un salvataggio accanto a un errore — {testo}")


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


def _self_guided(*, running, profilo="Serie A"):
    """`self` finto per il `_save` REALE del Mapping guidato."""
    return types.SimpleNamespace(
        _current=profilo,
        _team_vars={"Inter": types.SimpleNamespace(get=lambda: "Inter Milano")},
        _load_cfg=lambda: {"name_mappings": {profilo: []}},
        _selected_sport=lambda: "Calcio",
        _on_saved=None,
        _baseline={},
        _status=_Widget(),
        _is_running=(lambda: running),
    )


def test_guided_mapping_ramo_FALLITO_avvisa_senza_contraddire(monkeypatch):
    """Copertura diretta chiesta da GPT-5.5 sul ramo che questa PR ha toccato per ultimo.

    E' l'unico pannello senza un `_persist` condiviso, quindi il suo ramo d'errore va
    esercitato a parte: e' proprio dove una divergenza passerebbe inosservata."""
    mod = _importa(monkeypatch, "guided_mapping_gui")
    monkeypatch.setattr(mod.config_store, "save_config", lambda cfg, path=None: (cfg, False))

    finto = _self_guided(running=True)
    mod.GuidedMappingPanel._save(finto)
    testo = finto._status.testi[-1]

    assert testo.startswith("❌"), testo
    assert "Bridge ATTIVO" in testo, f"nessun avviso sul ramo fallito: {testo}"
    assert "salvat" not in testo.split("⚠️")[-1].lower(), (
        f"l'avviso afferma un salvataggio accanto a un errore: {testo}")


def test_guided_mapping_da_fermo_il_messaggio_e_invariato(monkeypatch):
    """Il contrasto: senza bridge attivo il ramo fallito non guadagna nessuna coda."""
    mod = _importa(monkeypatch, "guided_mapping_gui")
    monkeypatch.setattr(mod.config_store, "save_config", lambda cfg, path=None: (cfg, False))

    finto = _self_guided(running=False)
    mod.GuidedMappingPanel._save(finto)
    assert "Bridge ATTIVO" not in finto._status.testi[-1], finto._status.testi[-1]


def test_l_AUTO_save_al_cambio_sport_NON_passa_da_save(monkeypatch):
    """L'invariante dichiarata nel design handoff, ora fissata (dubbio di Fable 5 #177).

    L'avviso non deve comparire sull'auto-save al cambio sport: l'utente non l'ha chiesto.
    Regge perche' `_autosave_leaving` ha un percorso di scrittura PROPRIO e `_save` e'
    invocato solo dal pulsante. Se un domani l'auto-save venisse instradato su `_save`,
    questo test diventa rosso e obbliga a riconsiderare la scelta invece di scoprirla dalla
    UI."""
    import inspect
    mod = _importa(monkeypatch, "guided_mapping_gui")

    sorgente_autosave = inspect.getsource(mod.GuidedMappingPanel._autosave_leaving)
    assert "self._save(" not in sorgente_autosave, (
        "l'auto-save ora passa da _save: mostrerebbe l'avviso su un'azione non richiesta")
    # e ha davvero una scrittura propria: non e' un guscio che delega altrove
    assert "save_config" in sorgente_autosave, sorgente_autosave
