"""🎯 Dizionario mercati — colonna profili sempre visibile (#182 PR C).

Speculare alla PR B (⚽ nomi), con una differenza che è il punto di questa PR: il disegno **non**
è stato duplicato. `ui_widgets.disegna_elenco_profili` è la **fonte unica** dei due elenchi, che
differiscono solo per lo store che conta le righe e per la mappa d'uso. Due copie corrette oggi
sarebbero due copie divergenti al primo ritocco (regola 3).

⚠️ Il rischio resta quello della PR B, ed è nei **consumatori**: `_on_profile_change` del pannello
Mercati ha gli **stessi due rollback** (`_profile_var.set(self._current)`) che annullano un cambio
profilo quando la config è illeggibile o il salvataggio fallisce. Tolta la tendina che mostrava la
variabile, senza il `trace_add` il rollback sarebbe corretto nel codice e invisibile a schermo.
"""

import importlib
import json
import os
import sys
import types

import pytest

from conftest import leggi_sorgente

from xtrader_bridge import custom_parser, market_mapping_store, ui_widgets


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def nmg(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    yield mod
    sys.modules.pop("xtrader_bridge.name_mapping_gui", None)


# ── la fonte unica ──────────────────────────────────────────────────────────────────

class _Label:
    def __init__(self, master=None, **k):
        self.testo = k.get("text", "")
        self.legati = {}
        self.opzioni = dict(k)
    def pack(self, **k): pass
    def bind(self, evento, cb): self.legati[evento] = cb
    def configure(self, **k): self.opzioni.update(k)


class _Frame:
    def __init__(self, master=None, **k):
        self.legati = {}
        self.opzioni = dict(k)
        self.figli = []
    def pack(self, **k): pass
    def bind(self, evento, cb): self.legati[evento] = cb
    def configure(self, **k): self.opzioni.update(k)
    def winfo_children(self): return list(self.figli)
    def destroy(self): pass


def _ctk_spia(disegnate):
    class _L(_Label):
        def __init__(self, master=None, **k):
            super().__init__(master, **k)
            disegnate.append(self.testo)
    return types.SimpleNamespace(CTkLabel=_L, CTkFrame=_Frame, CTkFont=lambda **k: None)


def _i18n_identita():
    return types.SimpleNamespace(tr=lambda s: s)


def test_la_fonte_unica_disegna_marcatori_e_fantasmi():
    """Fail-first: `disegna_elenco_profili` non esisteva — il disegno viveva solo nel pannello
    nomi, e la PR C avrebbe dovuto copiarlo."""
    disegnate = []
    contenitore = _Frame()
    righe = ui_widgets.disegna_elenco_profili(
        _ctk_spia(disegnate), _i18n_identita(),
        types.SimpleNamespace(STATUS_WARN="warn"),
        contenitore, ["Esiste"],
        uso={"Esiste": ["P1", "P2"], "Sparito": ["P3"]},
        conta_righe=lambda nome: 7,
        on_click=lambda nome: (lambda _e=None: "break"))

    assert set(righe) == {"Esiste"}, "solo i profili REALI sono righe selezionabili"
    assert any("🧩" in t and "2" in t for t in disegnate), disegnate
    assert any("righe" in t and "7" in t for t in disegnate), disegnate
    assert any("Sparito" in t and "⚠" in t for t in disegnate), (
        f"il profilo fantasma non è segnalato: {disegnate}")
    assert "Sparito" not in righe, "un fantasma non deve essere cliccabile: non esiste"


def test_badge_omesso_a_zero_parser():
    """«🧩 0» sarebbe rumore: un profilo non ancora collegato a un parser è normale."""
    disegnate = []
    ui_widgets.disegna_elenco_profili(
        _ctk_spia(disegnate), _i18n_identita(), types.SimpleNamespace(STATUS_WARN="warn"),
        _Frame(), ["Nuovo"], uso={}, conta_righe=lambda n: 0,
        on_click=lambda nome: (lambda _e=None: "break"))
    assert not any("🧩" in t for t in disegnate), disegnate
    assert any("righe" in t for t in disegnate), "il conteggio righe deve esserci comunque"


def test_elenco_vuoto_lo_dice():
    disegnate = []
    ui_widgets.disegna_elenco_profili(
        _ctk_spia(disegnate), _i18n_identita(), types.SimpleNamespace(STATUS_WARN="warn"),
        _Frame(), [], uso={}, conta_righe=lambda n: 0,
        on_click=lambda nome: (lambda _e=None: "break"))
    assert any("Nessun profilo" in t for t in disegnate), disegnate


def test_un_solo_tab_stop_per_riga_nella_fonte_unica():
    """La regola vale una volta sola perché il disegno è uno solo — ed è verificata sul
    comportamento, non sul sorgente: la riga entra nel giro del Tab, l'etichetta no."""
    creati = []

    class _F(_Frame):
        def __init__(self, master=None, **k):
            super().__init__(master, **k)
            creati.append(self)

    class _L(_Label):
        def __init__(self, master=None, **k):
            super().__init__(master, **k)
            creati.append(self)

    ctk = types.SimpleNamespace(CTkLabel=_L, CTkFrame=_F, CTkFont=lambda **k: None)
    righe = ui_widgets.disegna_elenco_profili(
        ctk, _i18n_identita(), types.SimpleNamespace(STATUS_WARN="warn"),
        _Frame(), ["A"], uso={}, conta_righe=lambda n: 0,
        on_click=lambda nome: (lambda _e=None: "break"))

    focusabili = [w for w in creati if w.opzioni.get("takefocus") == 1]
    assert len(focusabili) == 1, f"{len(focusabili)} tab-stop per riga invece di 1"
    assert focusabili[0] is righe["A"], "il tab-stop deve essere la RIGA, non l'etichetta"
    # …e l'etichetta resta cliccabile col mouse.
    etichette = [w for w in creati if isinstance(w, _L) and w.testo == "A"]
    assert etichette, "l'etichetta col nome del profilo non è stata disegnata"
    assert "<Button-1>" in etichette[0].legati
    assert "<Return>" not in etichette[0].legati, "l'etichetta non deve essere un 2° tab-stop"


def test_evidenzia_profilo_accende_uno_e_spegne_gli_altri():
    class _Riga:
        def __init__(self): self.colore = "transparent"
        def configure(self, **k): self.colore = k.get("fg_color", self.colore)

    righe = {"A": _Riga(), "B": _Riga()}
    ui_widgets.evidenzia_profilo(righe, "B", "acceso")
    assert righe["B"].colore == "acceso"
    assert righe["A"].colore == "transparent"
    # nessuna riga selezionata → tutte spente, nessun crash
    ui_widgets.evidenzia_profilo(righe, "", "acceso")
    assert righe["A"].colore == righe["B"].colore == "transparent"
    ui_widgets.evidenzia_profilo(None, "A", "acceso")          # niente righe: no-op


def test_una_riga_distrutta_non_ferma_l_evidenziazione_delle_altre():
    class _Morta:
        def configure(self, **k): raise RuntimeError("widget distrutto")

    class _Viva:
        def __init__(self): self.colore = "transparent"
        def configure(self, **k): self.colore = k.get("fg_color", self.colore)

    viva = _Viva()
    ui_widgets.evidenzia_profilo({"morta": _Morta(), "viva": viva}, "viva", "acceso")
    assert viva.colore == "acceso", "una riga distrutta ha impedito di evidenziare le altre"


# ── il pannello mercati: mappa d'uso e rollback ─────────────────────────────────────

def test_market_mapping_profile_usage_e_separata_da_quella_dei_nomi(tmp_path):
    d = str(tmp_path)
    with open(os.path.join(d, "A.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "A", "mode": "NAME_ONLY", "rules": [],
                   "market_mapping_profiles": ["Mercati", "Mercati"],
                   "name_mapping_profiles": ["Nomi"]}, fh)

    assert custom_parser.market_mapping_profile_usage(d) == {"Mercati": ["A"]}, (
        "dedup per parser: un profilo ripetuto nello stesso file conta UNA volta")
    assert custom_parser.mapping_profile_usage(d) == {"Nomi": ["A"]}


def _pannello_mercati(nmg, corrente="A"):
    class _Var:
        def __init__(self, v=""):
            self._v, self._cb = v, None
        def get(self): return self._v
        def set(self, v):
            self._v = v
            if self._cb:
                self._cb()
        def trace_add(self, _m, cb): self._cb = cb

    class _Riga:
        def __init__(self): self.colore = "transparent"
        def configure(self, **k): self.colore = k.get("fg_color", self.colore)

    finto = object.__new__(nmg.MarketMappingPanel)
    finto._profile_var = _Var(corrente)
    finto._current = corrente
    finto._profile_rows = {"A": _Riga(), "B": _Riga()}
    finto._NO_PROFILE = nmg.MarketMappingPanel._NO_PROFILE
    finto._profile_var.trace_add("write", lambda *_a: finto._highlight_profiles())
    return finto


def test_rollback_mercati_su_config_illeggibile_riporta_indietro_l_elenco(nmg):
    """⚠️ Il difetto che questa PR poteva introdurre, gemello di quello della PR B.

    Config illeggibile durante un cambio profilo → lo switch è ANNULLATO per non far cancellare
    a `_reload_rows` le righe non salvate. Senza il `trace_add`, il codice resterebbe sul profilo
    A mentre l'elenco continua a evidenziare B: l'utente crederebbe di essere su B e ci
    scriverebbe sopra le righe di A."""
    finto = _pannello_mercati(nmg)
    finto._profile_var.set("B")
    assert finto._profile_rows["B"].colore != "transparent"

    finto._load_cfg = lambda: None
    finto._status = types.SimpleNamespace(configure=lambda **k: None)
    finto._reload_rows = lambda cfg=None: pytest.fail(
        "switch annullato: ricaricare le righe cancellerebbe l'editing")

    nmg.MarketMappingPanel._on_profile_change(finto, "B")

    assert finto._current == "A", "lo switch doveva essere annullato"
    assert finto._profile_rows["A"].colore != "transparent", (
        "l'elenco è rimasto su B mentre il codice è tornato ad A: il rollback è invisibile")
    assert finto._profile_rows["B"].colore == "transparent"


def test_rollback_mercati_su_salvataggio_fallito_riporta_indietro_l_elenco(nmg, monkeypatch):
    finto = _pannello_mercati(nmg)
    finto._profile_var.set("B")
    finto._load_cfg = lambda: {"market_mappings": {"A": [], "B": []}}
    finto._collect_rows = lambda: []
    finto._status = types.SimpleNamespace(configure=lambda **k: None)
    finto._on_saved = None
    finto._reload_rows = lambda cfg=None: pytest.fail("switch annullato: niente reload")
    monkeypatch.setattr(nmg.config_store, "save_config", lambda *a, **k: ({}, False))

    nmg.MarketMappingPanel._on_profile_change(finto, "B")

    assert finto._current == "A"
    assert finto._profile_rows["A"].colore != "transparent"


def test_il_click_mercati_apre_e_ferma_la_propagazione(nmg):
    aperti = []
    finto = types.SimpleNamespace(_on_profile_change=lambda n: aperti.append(n))
    gestore = nmg.MarketMappingPanel._gestore_click(finto, "Mercati")
    assert gestore("evento-finto") == "break"      # chiamato come fa Tk: un solo argomento
    assert gestore() == "break"
    assert aperti == ["Mercati", "Mercati"]


def test_i_badge_mercati_spariscono_se_i_parser_non_sono_leggibili(nmg, monkeypatch):
    """Fail-safe: la cartella dei parser illeggibile non deve impedire di aprire un profilo."""
    finto = object.__new__(nmg.MarketMappingPanel)

    def _esplode(*_a, **_k):
        raise OSError("cartella parser illeggibile")

    monkeypatch.setattr(nmg.custom_parser, "market_mapping_profile_usage", _esplode)
    assert nmg.MarketMappingPanel._profile_usage(finto) == {}


def test_i_due_pannelli_usano_LA_STESSA_funzione_di_disegno():
    """Regola 3 resa verificabile: se un domani qualcuno ricopiasse il disegno dentro uno dei due
    pannelli invece di usare la fonte unica, questo test lo intercetta."""
    import ast
    import pathlib
    albero = ast.parse(leggi_sorgente("xtrader_bridge/name_mapping_gui.py"))
    chiamate = [n for n in ast.walk(albero)
                if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "disegna_elenco_profili"]
    assert len(chiamate) == 2, (
        f"attese 2 chiamate alla fonte unica (⚽ nomi + 🎯 mercati), trovate {len(chiamate)}: "
        f"un pannello ha smesso di usarla")
    # …e nessuno dei due ricrea le righe a mano.
    sorgente = leggi_sorgente("xtrader_bridge/name_mapping_gui.py")
    assert "solo riferito" not in sorgente, (
        "il testo dei fantasmi è ricomparso nel pannello: il disegno è stato duplicato")


def test_click_ed_evidenziazione_hanno_UNA_sola_definizione(nmg):
    """Rilievo CodeRabbit sulla PR #228: `_gestore_click` e `_highlight_profiles` erano rimasti
    duplicati **byte per byte** nei due pannelli, pur avendo estratto il disegno.

    Era una contraddizione col principio stesso di questa PR: una correzione futura alla
    propagazione del click o all'evidenziazione sarebbe dovuta atterrare in due posti. Ora
    vivono in `_ElencoProfiliMixin` e i pannelli le ereditano — questo test lo pretende sia
    contando le definizioni nel sorgente, sia verificando che i due pannelli condividano
    davvero **lo stesso oggetto funzione** (non due copie che sembrano uguali)."""
    import ast
    import pathlib
    sorgente = leggi_sorgente("xtrader_bridge/name_mapping_gui.py")
    albero = ast.parse(sorgente)
    for nome in ("_gestore_click", "_highlight_profiles"):
        definizioni = [n for n in ast.walk(albero)
                       if isinstance(n, ast.FunctionDef) and n.name == nome]
        assert len(definizioni) == 1, (
            f"{nome}: {len(definizioni)} definizioni invece di 1 — la duplicazione è tornata")

    # …e l'ereditarietà è reale: stesso oggetto funzione per entrambi i pannelli.
    assert nmg.NameMappingPanel._gestore_click is nmg.MarketMappingPanel._gestore_click
    assert nmg.NameMappingPanel._highlight_profiles is nmg.MarketMappingPanel._highlight_profiles
    # …e il mixin precede il framework nella MRO, altrimenti un omonimo di CTkFrame vincerebbe.
    mro = nmg.NameMappingPanel.__mro__
    assert mro.index(nmg._ElencoProfiliMixin) < len(mro) - 1


def test_conta_righe_legge_lo_store_MERCATI(nmg):
    """Il conteggio del pannello mercati deve venire da `market_mapping_store`, non da quello
    dei nomi: sono due dizionari diversi e confonderli mostrerebbe numeri di un altro profilo."""
    cfg = market_mapping_store.add_profile({}, "M")
    cfg = market_mapping_store.set_entries(cfg, "M", [
        # I nomi dei campi sono quelli dello STORE (`market_name`/`selection_name`), non le
        # chiavi dei widget della GUI: una voce senza di essi viene scartata da `_clean_entry`
        # perché non può formare un mercato.
        {"start_after": "Quota", "end_before": "Prematch", "phrase": "0,5 HT",
         "market_name": "Over/Under 0.5 HT", "selection_name": "Over 0.5"},
    ])
    assert len(market_mapping_store.get_entries(cfg, "M")) == 1
    # la config dei mercati non contiene profili NOMI: il conteggio nomi su di essa è 0
    from xtrader_bridge import name_mapping_store
    assert name_mapping_store.get_entries(cfg, "M") == []
