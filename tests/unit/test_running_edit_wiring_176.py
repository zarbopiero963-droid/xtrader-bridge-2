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


def test_il_contenitore_INOLTRA_la_sonda_a_tutte_le_schede_VISIBILI(monkeypatch):
    """`MappingPanel` incapsula le schede Calcio e Mercati. Se la sonda arrivasse solo ad
    alcune, l'avviso comparirebbe in una scheda e non nelle sorelle — incoerenza peggiore sia
    di averlo ovunque sia di non averlo affatto.

    Erano tre: «🌳 Mapping guidato» è NASCOSTA da #182 PR N. L'invariante non è cambiata, è
    cambiato il numero di aree visibili a cui si applica."""
    mod = _importa(monkeypatch, "name_mapping_gui")
    visti = {}

    def _spia(nome):
        def _fake(master=None, **k):
            visti[nome] = k.get("is_running")
            return types.SimpleNamespace(pack=lambda **kk: None)
        return _fake

    monkeypatch.setattr(mod, "NameMappingPanel", _spia("calcio"))
    monkeypatch.setattr(mod, "MarketMappingPanel", _spia("mercati"))
    # #182 PR N: la terza sotto-area («🌳 Mapping guidato») e' NASCOSTA, quindi qui non c'e' piu'
    # nulla da spiare — `MappingPanel` non importa piu' `GuidedMappingPanel`. L'INVARIANTE #176
    # resta identica e vale ancora: la sonda «bridge ATTIVO» deve scendere a TUTTE le sotto-aree
    # VISIBILI, altrimenti l'avviso comparirebbe in una scheda e non nella sorella — incoerenza
    # peggiore sia di averlo ovunque sia di non averlo affatto. Cambia il numero, non la regola.
    sonda = object()
    tabs = types.SimpleNamespace(add=lambda nome: None, pack=lambda **k: None)
    monkeypatch.setattr(mod.ctk, "CTkTabview", lambda master: tabs, raising=False)
    # istanza REALE non inizializzata: `super().__init__` dentro `MappingPanel` richiede un
    # oggetto della classe, non un namespace finto.
    finto = object.__new__(mod.MappingPanel)
    monkeypatch.setattr(mod.ctk.CTkFrame, "__init__", lambda self, *a, **k: None, raising=False)

    mod.MappingPanel.__init__(finto, None, is_running=sonda)

    assert set(visti) == {"calcio", "mercati"}, visti
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
    """L'invariante dichiarata nel design handoff: l'avviso non deve comparire sull'auto-save
    al cambio sport, perche' l'utente non l'ha chiesto.

    Verificata ESEGUENDO (rilievo GPT-5.5): si sostituisce `_save` con una sentinella che
    esplode se chiamata, e si fa girare l'auto-save reale. Il controllo precedente guardava
    il TESTO del sorgente — lo stesso `inspect.getsource` che questa serie ha gia' criticato
    due volte: un alias o una delega gli sfuggirebbero, e una riformattazione lo romperebbe
    senza che nulla sia regredito."""
    mod = _importa(monkeypatch, "guided_mapping_gui")
    monkeypatch.setattr(mod.config_store, "save_config", lambda cfg, path=None: (cfg, True))

    chiamate = []
    monkeypatch.setattr(mod.GuidedMappingPanel, "_save",
                        lambda self: chiamate.append("_save"))

    finto = _self_guided(running=True)
    finto._baseline = {}
    finto._team_vars = {"Inter": types.SimpleNamespace(get=lambda: "Inter Milano")}
    mod.GuidedMappingPanel._autosave_leaving(finto, "Calcio")

    assert chiamate == [], (
        "l'auto-save e' passato da _save: mostrerebbe l'avviso su un'azione non richiesta")
    testi = " ".join(finto._status.testi)
    assert "Bridge ATTIVO" not in testi, f"l'auto-save ha mostrato l'avviso: {testi}"


def _self_rename(*, running):
    """`self` finto per `_rename_profile`: persist riuscito, con parser aggiornati."""
    return types.SimpleNamespace(
        _current="Vecchio",
        _status=_Widget(),
        _is_running=(lambda: running),
        _persist=lambda *a, **k: True,
        _load_cfg=lambda: {},
        _name_entry=types.SimpleNamespace(get=lambda: "Nuovo"),
        _collect_rows=lambda: [],
    )


@pytest.mark.parametrize("classe", ["NameMappingPanel", "MarketMappingPanel"])
@pytest.mark.parametrize("running", [True, False])
def test_la_RINOMINA_riuscita_non_perde_l_avviso(monkeypatch, classe, running):
    """Buco trovato da CodeRabbit: `_persist` mette l'avviso, poi il ramo «parser aggiornati»
    SOVRASCRIVE lo stato con testo semplice — e l'avviso spariva in silenzio, proprio su
    un'operazione che questa feature deve coprire.

    Misurato: quattro operazioni (rinomina ed elimina, in entrambi i pannelli) lo perdevano."""
    mod = _importa(monkeypatch, "name_mapping_gui")
    monkeypatch.setattr(mod.custom_parser, "rename_mapping_profile_in_files",
                        lambda old, new: (["ParserA"], []))
    monkeypatch.setattr(mod.custom_parser, "rename_market_mapping_profile_in_files",
                        lambda old, new: (["ParserA"], []), raising=False)
    monkeypatch.setattr(mod.market_mapping_store, "set_entries", lambda cfg, n, r: cfg,
                        raising=False)
    # il dialogo del nuovo nome: lo stub ctk non ha `get_input`, e senza questo il metodo
    # morirebbe subito lasciando lo stato VUOTO — il test passerebbe/fallirebbe per il
    # motivo sbagliato.
    monkeypatch.setattr(mod.ctk, "CTkInputDialog",
                        lambda **k: types.SimpleNamespace(get_input=lambda: "Nuovo"),
                        raising=False)
    monkeypatch.setattr(mod.name_mapping_store, "profile_names", lambda cfg: [])
    monkeypatch.setattr(mod.name_mapping_store, "rename_profile", lambda cfg, o, n: cfg)
    monkeypatch.setattr(mod.market_mapping_store, "profile_names", lambda cfg: [], raising=False)
    monkeypatch.setattr(mod.market_mapping_store, "rename_profile", lambda cfg, o, n: cfg,
                        raising=False)

    getattr(mod, classe)._rename_profile(finto := _self_rename(running=running))

    testi = " ".join(finto._status.testi)
    if running:
        assert "Bridge ATTIVO" in testi, (
            f"{classe}: la rinomina riuscita ha perso l'avviso — {testi}")
    else:
        # Il caso negativo chiesto da Fable 5: la sonda e' una CALLABLE, non un booleano.
        # Se `with_running_notice` la valutasse per verita' invece di chiamarla, un metodo
        # bound sarebbe sempre truthy e l'avviso comparirebbe anche a bridge FERMO.
        assert "Bridge ATTIVO" not in testi, (
            f"{classe}: avviso mostrato a bridge FERMO — la sonda non viene chiamata? {testi}")


@pytest.mark.parametrize("classe", ["NameMappingPanel", "MarketMappingPanel"])
def test_l_ELIMINAZIONE_con_parser_referenzianti_non_perde_l_avviso(monkeypatch, classe):
    """`_delete_profile` e' stato modificato allo stesso modo di `_rename_profile` e puo'
    regredire in modo indipendente (rilievo GPT-5.5). Il ramo con `affected` NON vuoto e'
    proprio quello che sovrascriveva lo stato dopo il `_persist`."""
    mod = _importa(monkeypatch, "name_mapping_gui")
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a, **k: True)
    monkeypatch.setattr(mod.custom_parser, "parsers_using_mapping_profile",
                        lambda name: ["ParserA"], raising=False)
    monkeypatch.setattr(mod.custom_parser, "parsers_using_market_mapping_profile",
                        lambda name: ["ParserA"], raising=False)
    monkeypatch.setattr(mod.name_mapping_store, "delete_profile", lambda cfg, n: cfg)
    monkeypatch.setattr(mod.market_mapping_store, "delete_profile", lambda cfg, n: cfg,
                        raising=False)

    finto = _self_rename(running=True)
    getattr(mod, classe)._delete_profile(finto)

    testi = " ".join(finto._status.testi)
    assert "Bridge ATTIVO" in testi, (
        f"{classe}: l'eliminazione ha perso l'avviso — {testi}")
