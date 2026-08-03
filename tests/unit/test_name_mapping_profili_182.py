"""⚽ Dizionario nomi — colonna profili sempre visibile (#182 PR B).

Prima i profili vivevano in un `CTkOptionMenu`: per sapere quali esistessero bisognava aprirlo,
e nulla diceva **quali parser li usassero**, **quante righe** avessero, né che un parser ne
riferisse uno **inesistente** — che a runtime significa `MAPPING_MISSING`, cioè ogni segnale di
quella chat scartato in silenzio.

⚠️ **Il rischio vero di questa PR non è il disegno, sono i consumatori.** `_on_profile_change`
usa `_profile_var.set(self._current)` per **annullare** un cambio profilo quando la config è
illeggibile o il salvataggio fallisce: senza quel rollback `_reload_rows` cancellerebbe righe non
salvate. Tolta la tendina che mostrava la variabile, il rollback sarebbe rimasto corretto nel
codice ma **invisibile a schermo**. È la stessa classe di difetto della PR N (#222), dove
nascondere una sotto-scheda senza guardare chi la usava rompeva `MappingPanel.refresh`.

I test qui sotto coprono entrambe le metà: i badge *e* il rollback.
"""

import importlib
import json
import os
import sys
import types

import pytest

from xtrader_bridge import custom_parser, name_mapping_store


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


# ── la mappa d'uso: una sola passata, non una per profilo ────────────────────────────

def _scrivi_parser(dir_path, nome, profili):
    with open(os.path.join(dir_path, f"{nome}.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": nome, "mode": "NAME_ONLY", "rules": [],
                   "name_mapping_profiles": list(profili)}, fh)


def test_mapping_profile_usage_mappa_tutti_i_profili_in_una_passata(tmp_path):
    """Fail-first: `mapping_profile_usage` non esisteva.

    Disegnare i badge con la funzione per-singolo-profilo avrebbe riletto TUTTI i file una
    volta per profilo — O(profili × file) di I/O a ogni ridisegno dell'elenco."""
    d = str(tmp_path)
    _scrivi_parser(d, "A", ["Premier", "Serie A"])
    _scrivi_parser(d, "B", ["Serie A"])
    _scrivi_parser(d, "C", [])

    uso = custom_parser.mapping_profile_usage(d)
    assert uso == {"Premier": ["A"], "Serie A": ["A", "B"]}, uso
    assert "C" not in str(uso), "un parser senza profili non deve comparire da nessuna parte"


def test_la_funzione_storica_resta_identica_dopo_il_refactor(tmp_path):
    """**Il consumatore, non il sito** (regola 2-bis): `parsers_using_mapping_profile` ora
    DELEGA alla mappa completa. Il contratto che i suoi chiamanti si aspettano — l'avviso
    prima di eliminare un profilo in uso — deve essere invariato: stessa lista, stesso ordine,
    `[]` sui casi limite."""
    d = str(tmp_path)
    _scrivi_parser(d, "A", ["Premier", "Serie A"])
    _scrivi_parser(d, "B", ["Serie A"])

    assert custom_parser.parsers_using_mapping_profile("Premier", d) == ["A"]
    assert custom_parser.parsers_using_mapping_profile("Serie A", d) == ["A", "B"]
    assert custom_parser.parsers_using_mapping_profile("Inesistente", d) == []
    assert custom_parser.parsers_using_mapping_profile("", d) == []
    assert custom_parser.parsers_using_mapping_profile("  ", d) == []


def test_un_parser_che_ripete_lo_stesso_profilo_conta_UNA_volta(tmp_path):
    """Rilievo Fable/GPT-5.5 sulla PR #226 — **regressione introdotta dal refactor**.

    Il codice storico faceva `if n in profili: out.append(defn.name)`: una sola occorrenza per
    parser, qualunque cosa contenesse la lista. La prima versione di `_profile_usage` appendeva
    invece **per occorrenza**, quindi un parser con `["Premier", "Premier"]` compariva due volte.

    Due conseguenze, entrambe misurate: il badge «🧩 2» su **un solo** parser, e — peggio —
    l'avviso prima di eliminare un profilo in uso che elenca lo stesso parser due volte.

    `CustomParserDef.from_dict` NON deduplica (`profiles = [str(p).strip() for p in raw ...]`),
    quindi la lista duplicata arriva davvero fin qui: non è un caso teorico.

    Fail-first misurato: `parsers_using_mapping_profile("Premier", d)` ritornava `['A', 'A']`."""
    d = str(tmp_path)
    _scrivi_parser(d, "A", ["Premier", "Premier"])
    _scrivi_parser(d, "B", ["Premier"])

    assert custom_parser.mapping_profile_usage(d) == {"Premier": ["A", "B"]}
    assert custom_parser.parsers_using_mapping_profile("Premier", d) == ["A", "B"], (
        "contratto storico violato: un parser deve comparire UNA volta sola")


def test_profili_con_spazi_ai_bordi_non_diventano_fantasmi(tmp_path):
    """Controprova del secondo rilievo di Fable, che sospettava un'asimmetria di `strip()`.

    L'asimmetria non c'è: `name_mapping_store.profile_names` strippa le chiavi della config
    (`[str(k).strip() for k in ...]`) esattamente come `_profile_usage` strippa i nomi letti dai
    parser. Un profilo salvato a mano con spazi ai bordi resta quindi confrontabile da entrambi
    i lati e **non** compare come «solo riferito». Questo test blinda l'invariante: se un domani
    uno dei due lati smettesse di normalizzare, il falso allarme comparirebbe e il test cade."""
    d = str(tmp_path)
    _scrivi_parser(d, "A", ["  Premier  "])
    assert custom_parser.mapping_profile_usage(d) == {"Premier": ["A"]}
    assert name_mapping_store.profile_names({"name_mappings": {"  Premier  ": []}}) == ["Premier"]


def test_un_parser_corrotto_non_fa_sparire_i_badge_degli_altri(tmp_path):
    """Best-effort: un file illeggibile si salta, non azzera la mappa."""
    d = str(tmp_path)
    _scrivi_parser(d, "Buono", ["Premier"])
    with open(os.path.join(d, "Rotto.json"), "w", encoding="utf-8") as fh:
        fh.write("{ questo non e' json")

    assert custom_parser.mapping_profile_usage(d) == {"Premier": ["Buono"]}


def test_profili_mercati_hanno_la_loro_mappa(tmp_path):
    """La stessa logica su `market_mapping_profiles` (serve alla PR C): due attributi, una
    sola implementazione — se domani cambia il formato dei file, cambia in un posto solo."""
    d = str(tmp_path)
    with open(os.path.join(d, "M.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "M", "mode": "NAME_ONLY", "rules": [],
                   "market_mapping_profiles": ["Mercati"]}, fh)
    assert custom_parser.market_mapping_profile_usage(d) == {"Mercati": ["M"]}
    assert custom_parser.mapping_profile_usage(d) == {}, (
        "i profili MERCATI non devono finire nella mappa dei profili NOMI")


# ── il rollback: la parte che poteva rompersi in silenzio ────────────────────────────

def _pannello(nmg, corrente="A"):
    """Un `self` finto col minimo per esercitare rollback ed evidenziazione."""
    class _Var:
        def __init__(self, v=""):
            self._v = v
            self._cb = None
        def get(self):
            return self._v
        def set(self, v):
            self._v = v
            if self._cb:
                self._cb()
        def trace_add(self, _modo, cb):
            self._cb = cb

    class _Riga:
        def __init__(self):
            self.colore = "transparent"
        def configure(self, **k):
            self.colore = k.get("fg_color", self.colore)

    finto = object.__new__(nmg.NameMappingPanel)
    finto._profile_var = _Var(corrente)
    finto._current = corrente
    finto._profile_rows = {"A": _Riga(), "B": _Riga()}
    finto._NO_PROFILE = nmg.NameMappingPanel._NO_PROFILE
    # il trace è agganciato come nel `_build_ui` vero
    finto._profile_var.trace_add("write", lambda *_a: finto._highlight_profiles())
    return finto


def test_evidenziazione_segue_la_variabile(nmg):
    """L'elenco si riallinea da solo a ogni `_profile_var.set(...)`, senza che i chiamanti
    debbano saperne nulla — è il meccanismo che tiene vivi i rollback esistenti."""
    finto = _pannello(nmg)
    nmg.NameMappingPanel._highlight_profiles(finto)
    assert finto._profile_rows["A"].colore != "transparent"
    assert finto._profile_rows["B"].colore == "transparent"

    finto._profile_var.set("B")
    assert finto._profile_rows["B"].colore != "transparent"
    assert finto._profile_rows["A"].colore == "transparent", (
        "il profilo precedente deve smettere di risultare selezionato")


def test_rollback_su_config_illeggibile_riporta_indietro_ANCHE_l_elenco(nmg, monkeypatch):
    """⚠️ Il difetto che questa PR poteva introdurre.

    Config illeggibile durante un cambio profilo → `_on_profile_change` ANNULLA lo switch, per
    non far cancellare a `_reload_rows` le righe non salvate. Con la tendina, `_profile_var.set`
    riportava indietro anche ciò che si vedeva. Senza il `trace_add`, il codice sarebbe rimasto
    sul profilo A mentre l'elenco continuava a evidenziare B: l'utente avrebbe creduto di essere
    su B e ci avrebbe scritto sopra le righe di A.

    Fail-first: senza l'aggancio dell'evidenziazione alla variabile, l'ultima assert fallisce."""
    finto = _pannello(nmg)
    finto._profile_var.set("B")                      # l'utente clicca B
    assert finto._profile_rows["B"].colore != "transparent"

    finto._load_cfg = lambda: None                   # config illeggibile
    finto._status = types.SimpleNamespace(configure=lambda **k: None)
    finto._reload_rows = lambda cfg=None: pytest.fail(
        "le righe NON vanno ricaricate quando lo switch è annullato: cancellerebbe l'editing")

    nmg.NameMappingPanel._on_profile_change(finto, "B")

    assert finto._current == "A", "lo switch doveva essere annullato"
    assert finto._profile_rows["A"].colore != "transparent", (
        "l'elenco è rimasto su B mentre il codice è tornato ad A: il rollback è invisibile")
    assert finto._profile_rows["B"].colore == "transparent"


def test_rollback_su_salvataggio_fallito_riporta_indietro_l_elenco(nmg, monkeypatch):
    """Stesso rollback, altro ramo: l'auto-save del profilo che stai lasciando fallisce."""
    finto = _pannello(nmg)
    finto._profile_var.set("B")
    finto._load_cfg = lambda: {"name_mappings": {"A": [], "B": []}}
    finto._collect_rows = lambda: []
    finto._status = types.SimpleNamespace(configure=lambda **k: None)
    finto._on_saved = None
    finto._reload_rows = lambda cfg=None: pytest.fail("switch annullato: niente reload")
    monkeypatch.setattr(nmg.config_store, "save_config", lambda *a, **k: ({}, False))

    nmg.NameMappingPanel._on_profile_change(finto, "B")

    assert finto._current == "A"
    assert finto._profile_rows["A"].colore != "transparent", (
        "salvataggio fallito: l'elenco deve tornare sul profilo corrente")


def test_il_click_apre_il_profilo_e_ferma_la_propagazione(nmg):
    """Riga ed etichetta sono entrambe legate: senza `"break"` un click sull'etichetta
    risalirebbe al frame e cambierebbe profilo DUE volte — e un cambio profilo **auto-salva**,
    quindi non è un doppione innocuo."""
    aperti = []
    finto = types.SimpleNamespace(_on_profile_change=lambda n: aperti.append(n))
    gestore = nmg.NameMappingPanel._gestore_click(finto, "Premier")

    assert gestore(None) == "break", "il gestore non ferma la propagazione"
    assert aperti == ["Premier"]


def test_il_gestore_accetta_la_firma_che_TK_usa_davvero(nmg):
    """Tk invoca l'handler con il **solo evento**. Un `staticmethod` avrebbe raccolto l'evento
    credendolo `self` — questo test lo intercetterebbe."""
    finto = types.SimpleNamespace(_on_profile_change=lambda n: None)
    gestore = nmg.NameMappingPanel._gestore_click(finto, "X")
    assert gestore("evento-finto") == "break"        # chiamato come fa Tk: un solo argomento
    assert gestore() == "break"                      # e regge anche senza argomenti


# ── i badge ─────────────────────────────────────────────────────────────────────────

def _spia_render(nmg, monkeypatch, names, cfg, uso):
    """Esegue il VERO `_render_profile_rows` con widget-spia e ritorna le etichette disegnate."""
    disegnate = []

    class _Label:
        def __init__(self, master=None, **k):
            disegnate.append(k.get("text", ""))
        def pack(self, **k): pass
        def bind(self, evento, cb): pass          # le etichette sono cliccabili quanto la riga

    class _Frame:
        def __init__(self, master=None, **k): pass
        def pack(self, **k): pass
        def configure(self, **k): pass
        def winfo_children(self): return []
        def bind(self, evento, cb): pass

    monkeypatch.setattr(nmg.ctk, "CTkLabel", _Label, raising=False)
    monkeypatch.setattr(nmg.ctk, "CTkFrame", _Frame, raising=False)
    monkeypatch.setattr(nmg.ctk, "CTkFont", lambda **k: None, raising=False)

    finto = object.__new__(nmg.NameMappingPanel)
    finto._profile_list = _Frame()
    finto._profile_rows = {}
    finto._profile_var = types.SimpleNamespace(get=lambda: "")
    finto._profile_usage = lambda: uso
    finto._highlight_profiles = lambda: None
    nmg.NameMappingPanel._render_profile_rows(finto, names, cfg)
    return disegnate


def test_badge_mostra_quanti_parser_usano_il_profilo_e_quante_righe(nmg, monkeypatch):
    """Fail-first: prima la tendina mostrava solo il nome."""
    cfg = name_mapping_store.add_profile({}, "Premier")
    cfg = name_mapping_store.set_entries(cfg, "Premier", [
        {"betfair": "Liverpool", "provider": "LFC"},
        {"betfair": "Arsenal", "provider": "AFC"},
    ])
    testi = _spia_render(nmg, monkeypatch, ["Premier"], cfg, {"Premier": ["P1", "P2"]})

    assert "Premier" in testi
    assert any("2" in t and "🧩" in t for t in testi), f"manca il badge dei parser: {testi}"
    assert any("righe" in t and "2" in t for t in testi), f"manca il conteggio righe: {testi}"


def test_profilo_non_usato_non_mostra_il_badge_parser(nmg, monkeypatch):
    """«🧩 0» sarebbe rumore: un profilo non ancora collegato a un parser è normale."""
    cfg = name_mapping_store.add_profile({}, "Nuovo")
    testi = _spia_render(nmg, monkeypatch, ["Nuovo"], cfg, {})
    assert not any("🧩" in t for t in testi), testi
    assert any("righe" in t for t in testi), "il conteggio righe deve esserci comunque"


def test_profilo_SOLO_RIFERITO_compare_in_coda_con_l_avviso(nmg, monkeypatch):
    """Il caso che a runtime scarta i segnali: un parser chiede un profilo che non esiste più.

    Prima il pannello non lo diceva in alcun modo — si vedeva solo `MAPPING_MISSING` nel log,
    a valle. Ora è in fondo all'elenco, marcato ⚠."""
    cfg = name_mapping_store.add_profile({}, "Esiste")
    testi = _spia_render(nmg, monkeypatch, ["Esiste"],
                         cfg, {"Esiste": ["P1"], "Sparito": ["P1", "P2"]})

    assert any("Sparito" in t and "⚠" in t for t in testi), (
        f"il profilo fantasma non è segnalato: {testi}")
    assert not any("Esiste" in t and "⚠" in t for t in testi), (
        "un profilo esistente non deve essere marcato come fantasma")


def test_elenco_vuoto_lo_dice(nmg, monkeypatch):
    testi = _spia_render(nmg, monkeypatch, [], {}, {})
    assert any("Nessun profilo" in t for t in testi), testi


def test_i_badge_spariscono_se_i_parser_non_sono_leggibili_ma_l_elenco_resta(nmg, monkeypatch):
    """Fail-safe: la cartella dei parser illeggibile non deve impedire di aprire un profilo."""
    finto = object.__new__(nmg.NameMappingPanel)

    def _esplode(*_a, **_k):
        raise OSError("cartella parser illeggibile")

    monkeypatch.setattr(nmg.custom_parser, "mapping_profile_usage", _esplode)
    assert nmg.NameMappingPanel._profile_usage(finto) == {}


def test_le_etichette_nuove_sono_tradotte():
    """Ogni label nuova passa da EN/ES (principio comune della #182). Valore esatto, non
    «diverso dall'italiano» (rilievo CodeRabbit sulla PR #225)."""
    from xtrader_bridge import i18n
    prima = i18n.get_language()
    try:
        i18n.set_language("EN")
        assert i18n.tr("(clicca un profilo per aprirlo)") == "(click a profile to open it)"
        assert i18n.tr("· {n} righe").format(n=3) == "· 3 rows"
        assert i18n.tr("⚠ {name} (solo riferito)").format(name="X") == "⚠ X (referenced only)"
        i18n.set_language("ES")
        assert i18n.tr("(clicca un profilo per aprirlo)") == "(haz clic en un perfil para abrirlo)"
        assert i18n.tr("· {n} righe").format(n=3) == "· 3 filas"
    finally:
        i18n.set_language(prima)
