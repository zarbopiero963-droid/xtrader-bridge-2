"""Pannello 🧩 Parser — #182 PR A: elenco a vista, autoload, anagrafiche, etichette.

`custom_parser_gui` importa `customtkinter` e non è istanziabile headless: qui si stubbia SOLO
la libreria GUI e si esercitano i **metodi veri** su un `self` finto, come già fanno
`test_name_mapping_gui_prefill.py` e `test_running_edit_wiring_176.py`. La logica sotto test è
quella reale del pannello.
"""

import ast
import importlib
import inspect
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def cpg(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.custom_parser_gui")
    yield mod
    sys.modules.pop("xtrader_bridge.custom_parser_gui", None)


def _bottoni_costruiti(func) -> list:
    """Etichette dei `CTkButton` COSTRUITI in `func`, via AST (non ricerca testuale)."""
    import textwrap
    albero = ast.parse(textwrap.dedent(inspect.getsource(func)))
    fuori = []
    for n in ast.walk(albero):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "CTkButton"):
            continue
        for kw in n.keywords:
            if kw.arg != "text":
                continue
            v = kw.value
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                    and v.func.attr == "tr" and v.args):
                v = v.args[0]
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                fuori.append(v.value)
    return fuori


# ── ① elenco sempre visibile ─────────────────────────────────────────────────────────

def test_la_tendina_dei_parser_salvati_non_esiste_piu(cpg):
    """Fail-first: prima c'era `self._saved_menu = ctk.CTkOptionMenu(...)`.

    L'elenco deve essere un contenitore a vista, non una tendina da aprire."""
    src = inspect.getsource(cpg.CustomParserPanel._build_ui)
    assert "_saved_menu" not in src, "la tendina dei parser salvati è tornata"
    assert "_saved_list" in src, "manca l'elenco sempre visibile dei parser"


def test_carica_e_assorbito_dal_doppio_click(cpg):
    """«📂 Carica» esce dalla barra; restano 🆕 · 📑 · 🗑."""
    bottoni = _bottoni_costruiti(cpg.CustomParserPanel._build_ui)
    assert "📂 Carica" not in bottoni, "«📂 Carica» è tornato: lo sostituisce il doppio click"
    for atteso in ("🆕 Nuovo", "📑 Duplica", "🗑 Elimina"):
        assert atteso in bottoni, f"manca «{atteso}»: {bottoni}"


def test_ordine_alfabetico_e_marcatori(cpg):
    """L'elenco è ordinato case-insensitive e mostra «✓ attivo» / «📡 N».

    Esegue il VERO `_refresh_saved` con `saved_parsers` e config finti."""
    mod = cpg
    disegnate = {}

    finto = types.SimpleNamespace(
        _saved_map={}, _saved_var=types.SimpleNamespace(_v="", get=lambda: "", set=lambda v: None),
        _NONE_SAVED=mod.CustomParserPanel._NONE_SAVED,
        _render_saved_rows=lambda labels: disegnate.setdefault("labels", labels),
    )
    monkey = [
        {"name": "zeta", "path": "/z"},
        {"name": "Alfa", "path": "/a"},
        {"name": "mid", "path": "/m"},
    ]
    vero = mod.ParserBuilder.saved_parsers
    try:
        mod.ParserBuilder.saved_parsers = staticmethod(lambda: monkey)
        mod.CustomParserPanel._refresh_saved(finto)
    finally:
        mod.ParserBuilder.saved_parsers = vero

    assert disegnate["labels"] == ["Alfa", "mid", "zeta"], disegnate["labels"]


def test_parser_usage_conta_le_chat_e_regge_una_config_illeggibile(cpg):
    """I marcatori usano solo API pubbliche e degradano senza rompere l'elenco."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)

    cfg = {"active_parser": "P1", "parser_by_chat": {"-100": "P1", "-200": "P2", "-300": "P1"}}
    orig_load = mod.config_store.load_config
    try:
        mod.config_store.load_config = lambda *_a, **_k: cfg
        attivo, conteggio = mod.CustomParserPanel._parser_usage(finto)
        assert attivo == "P1"
        assert conteggio == {"P1": 2, "P2": 1}

        # config illeggibile → nessun marcatore, MAI un'eccezione (l'elenco resta usabile)
        def _esplode(*_a, **_k):
            raise OSError("config illeggibile")
        mod.config_store.load_config = _esplode
        assert mod.CustomParserPanel._parser_usage(finto) == ("", {})
    finally:
        mod.config_store.load_config = orig_load


# ── ② autoload del parser attivo ─────────────────────────────────────────────────────

def test_autoload_carica_il_parser_attivo(cpg):
    """Decisione del proprietario 2026-08-03: aprendo la scheda si vede subito il parser attivo."""
    mod = cpg
    caricati = []
    finto = types.SimpleNamespace(
        _saved_map={"P1": "/p1", "P2": "/p2"},
        _parser_usage=lambda: ("P1", {}),
        _select_saved=lambda n: caricati.append(("sel", n)),
        _load_selected=lambda: caricati.append(("load", None)),
        _builder_snapshot=dict, _saved_snapshot=None,
    )
    mod.CustomParserPanel._autoload_active_parser(finto)
    assert caricati == [("sel", "P1"), ("load", None)]


@pytest.mark.parametrize("attivo, mappa", [
    ("", {"P1": "/p1"}),                 # nessun parser attivo
    ("Fantasma", {"P1": "/p1"}),         # attivo che non risolve a un file salvato
])
def test_autoload_resta_sull_editor_vuoto_se_non_puo_caricare(cpg, attivo, mappa):
    """Fail-safe: senza un attivo caricabile NON si tocca l'editor (comportamento storico)."""
    mod = cpg
    caricati = []
    finto = types.SimpleNamespace(
        _saved_map=mappa, _parser_usage=lambda: (attivo, {}),
        _select_saved=lambda n: caricati.append(n),
        _load_selected=lambda: caricati.append("load"),
    )
    mod.CustomParserPanel._autoload_active_parser(finto)
    assert caricati == []


def test_autoload_ingoia_un_parser_attivo_illeggibile(cpg):
    """Un file corrotto non deve impedire di APRIRE il pannello."""
    mod = cpg

    def _rotto():
        raise ValueError("parser corrotto")

    finto = types.SimpleNamespace(
        _saved_map={"P1": "/p1"}, _parser_usage=lambda: ("P1", {}),
        _select_saved=lambda n: None, _load_selected=_rotto,
        _builder_snapshot=dict, _saved_snapshot=None,
    )
    mod.CustomParserPanel._autoload_active_parser(finto)      # non deve sollevare


def test_autoload_solo_su_pannello_NUOVO(cpg):
    """Vincolo: non deve mai calpestare un parser già in costruzione.

    Guardia sul sorgente: la chiamata sta sotto `if is_new`."""
    src = inspect.getsource(cpg.CustomParserPanel.__init__)
    righe = [r.strip() for r in src.splitlines() if not r.strip().startswith("#")]
    i_chiamata = next(i for i, r in enumerate(righe) if "_autoload_active_parser()" in r)
    assert righe[i_chiamata - 1] == "if is_new:", (
        "l'autoload deve stare sotto `if is_new`, altrimenti sovrascrive l'editor in uso")


# ── ④ riquadro anagrafiche ───────────────────────────────────────────────────────────

def test_riquadro_anagrafiche_ha_i_tre_pulsanti(cpg):
    bottoni = _bottoni_costruiti(cpg.CustomParserPanel._build_ui)
    for atteso in ("📇 Provider", "🗺️ Dizionario nomi", "🎯 Dizionario mercati"):
        assert atteso in bottoni, f"manca «{atteso}» nel riquadro anagrafiche: {bottoni}"
    # e non devono comparire DUE volte (erano dentro le righe Traduzioni)
    assert bottoni.count("🗺️ Dizionario nomi") == 1
    assert bottoni.count("🎯 Dizionario mercati") == 1


def test_provider_apre_l_anagrafica_e_degrada_se_l_hub_non_c_e(cpg):
    """Con il callback dell'hub porta sulla scheda Provider; senza, ricade sull'aggiunta rapida."""
    mod = cpg
    visti = []
    con_hub = types.SimpleNamespace(_on_open_tool=lambda t: visti.append(("tab", t)),
                                    _add_provider=lambda: visti.append(("add", None)))
    mod.CustomParserPanel._open_provider_registry(con_hub)
    assert visti == [("tab", "📇 Provider")]

    visti.clear()
    senza_hub = types.SimpleNamespace(_on_open_tool=None,
                                      _add_provider=lambda: visti.append(("add", None)))
    mod.CustomParserPanel._open_provider_registry(senza_hub)
    assert visti == [("add", None)], "senza hub il pulsante deve fare comunque qualcosa"

    visti.clear()
    def _rotto(_t):
        raise RuntimeError("hub distrutto")
    hub_rotto = types.SimpleNamespace(_on_open_tool=_rotto,
                                      _add_provider=lambda: visti.append(("add", None)))
    mod.CustomParserPanel._open_provider_registry(hub_rotto)
    assert visti == [("add", None)], "hub rotto → fallback, mai un crash"


# ── ⑤ etichette delle due tendine a cascata ──────────────────────────────────────────

def test_le_due_tendine_del_catalogo_hanno_ciascuna_la_sua_etichetta(cpg):
    """Fail-first: prima «Catalogo XTrader:» era l'unica etichetta, davanti alla PRIMA tendina;
    la seconda non diceva cosa fosse."""
    import textwrap
    src = textwrap.dedent(inspect.getsource(cpg.CustomParserPanel._build_ui))
    etichette = []
    for n in ast.walk(ast.parse(src)):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "CTkLabel"):
            for kw in n.keywords:
                if kw.arg == "text":
                    v = kw.value
                    if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                            and v.func.attr == "tr" and v.args):
                        v = v.args[0]
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        etichette.append(v.value)
    assert "Mercato:" in etichette and "Selezione:" in etichette, etichette


def test_le_etichette_nuove_sono_tradotte(cpg):
    """Ogni label nuova passa da `i18n.tr` con EN/ES (principio comune della #182)."""
    from xtrader_bridge import i18n
    prima = i18n.get_language()
    try:
        for lingua in ("EN", "ES"):
            i18n.set_language(lingua)
            for chiave in ("Mercato:", "Selezione:", "🧰 Anagrafiche e dizionari"):
                assert i18n.tr(chiave) != chiave, f"{chiave!r} non tradotta in {lingua}"
    finally:
        i18n.set_language(prima)


def test_autoload_non_apre_la_conferma_modifiche_non_salvate(cpg):
    """Il difetto che l'autoload poteva introdurre, e che il test blinda.

    `_saved_snapshot` è fotografato nel prologo di `__init__`, PRIMA che
    `apply_mode_defaults` tocchi il builder di un parser NUOVO. Senza ri-fotografare,
    `_has_unsaved_changes()` sarebbe vero e l'autoload avrebbe aperto la conferma
    «modifiche non salvate» **a ogni apertura della scheda** — un dialogo per nulla,
    ogni volta, che avrebbe reso la funzione odiosa invece che comoda."""
    mod = cpg
    eventi = []
    finto = types.SimpleNamespace(
        _saved_map={"P1": "/p1"},
        _parser_usage=lambda: ("P1", {}),
        _select_saved=lambda n: None,
        _load_selected=lambda: eventi.append("load"),
        _builder_snapshot=lambda: eventi.append("snapshot") or {"stato": "nuovo"},
        _saved_snapshot=None,
    )
    mod.CustomParserPanel._autoload_active_parser(finto)

    assert eventi == ["snapshot", "load"], (
        f"la baseline va ri-fotografata PRIMA del caricamento, non dopo: {eventi}")
    assert finto._saved_snapshot == {"stato": "nuovo"}


# ── ⑥ valore fisso + trasformazione ──────────────────────────────────────────────────

def _riga(fisso, transform="", value_map="", con_menu=True):
    class _Menu:
        def __init__(self): self.stato = "normal"
        def configure(self, **k): self.stato = k.get("state", self.stato)
    refs = {"fixed_value": types.SimpleNamespace(get=lambda: fisso),
            "transform": types.SimpleNamespace(get=lambda: transform),
            "value_map": types.SimpleNamespace(get=lambda: value_map)}
    if con_menu:
        refs["transform_menu"] = _Menu()
        refs["value_map_menu"] = _Menu()
    return refs


def test_valore_fisso_disabilita_trasformazione_e_valuemap(cpg):
    """Opzione A del proprietario: le due tendine si disattivano sulle righe con valore fisso."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)

    con_fisso = _riga("Sì", transform="score_to_over")
    assert mod.CustomParserPanel._gate_fixed_value(finto, con_fisso) is True
    assert con_fisso["transform_menu"].stato == "disabled"
    assert con_fisso["value_map_menu"].stato == "disabled"

    senza = _riga("", transform="score_to_over")
    assert mod.CustomParserPanel._gate_fixed_value(finto, senza) is False
    assert senza["transform_menu"].stato == "normal"
    assert senza["value_map_menu"].stato == "normal"


def test_gate_non_esplode_senza_le_tendine_avanzate(cpg):
    """Con le colonne avanzate nascoste i menu non esistono: il gate deve essere un no-op."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)
    assert mod.CustomParserPanel._gate_fixed_value(finto, _riga("Sì", con_menu=False)) is True


def test_avviso_solo_quando_serve_e_conta_le_righe(cpg):
    """L'avviso compare solo se una riga ha valore fisso E una trasformazione/value-map."""
    mod = cpg

    def _finto(righe):
        f = object.__new__(mod.CustomParserPanel)
        f._rows = righe
        return f

    # valore fisso ma nessuna trasformazione → niente avviso (non c'è nulla da spiegare)
    assert mod.CustomParserPanel._avviso_valore_fisso(_finto([_riga("Sì")])) == ""
    # nessun valore fisso → niente avviso
    assert mod.CustomParserPanel._avviso_valore_fisso(_finto([_riga("", transform="upper")])) == ""
    # due righe interessate → avviso che le conta
    testo = mod.CustomParserPanel._avviso_valore_fisso(_finto([
        _riga("Sì", transform="score_to_over"),
        _riga("PUNTA", value_map="lato"),
        _riga("", transform="upper"),
    ]))
    assert "2" in testo and "VALORE FISSO" in testo, testo


def test_il_gate_NON_tocca_validate_parser_def(cpg):
    """Vincolo esplicito della #182 (opzione B SCARTATA).

    Irrigidire `validate_parser_def` renderebbe INVALIDI i parser già salvati:
    `parser_manager._load_by_name` li scarterebbe via `is_valid()` e una chat smetterebbe di
    produrre segnali **in silenzio**. Il gate deve restare a video."""
    src = inspect.getsource(cpg.CustomParserPanel._gate_fixed_value)
    src += inspect.getsource(cpg.CustomParserPanel._avviso_valore_fisso)
    assert "validate_parser_def" not in src, (
        "il gate ⑥ non deve passare dal validatore: renderebbe invalidi i parser salvati")
    # …e non deve nemmeno riscrivere i valori salvati del builder
    for vietato in ("rule.transform =", "rule.value_map =", ".set("):
        assert vietato not in src, f"il gate ⑥ modifica lo stato salvato ({vietato}): è sola presentazione"
