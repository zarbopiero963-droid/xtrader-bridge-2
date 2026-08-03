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


def _corpo_senza_docstring(func) -> str:
    """Sorgente di `func` privato del docstring, via AST.

    Serve alle guardie che vietano una CHIAMATA (`validate_parser_def`, `.set(`): il docstring
    può legittimamente nominarla per spiegare che NON la si usa, e una ricerca testuale sul
    sorgente intero non distingue le due cose."""
    import textwrap
    albero = ast.parse(textwrap.dedent(inspect.getsource(func)))
    definizione = albero.body[0]
    corpo = definizione.body
    if (corpo and isinstance(corpo[0], ast.Expr)
            and isinstance(corpo[0].value, ast.Constant)
            and isinstance(corpo[0].value.value, str)):
        corpo = corpo[1:]
    return "\n".join(ast.unparse(n) for n in corpo)


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


def test_ordine_alfabetico_case_insensitive(cpg):
    """L'elenco è ordinato case-insensitive.

    Rilievo CodeRabbit (#223): il nome prometteva anche i marcatori «✓ attivo»/«📡 N», che
    qui NON sono esercitati perché `_render_saved_rows` è sostituito da uno stub. I marcatori
    hanno il loro test in `test_parser_usage_*`; questo verifica l'ordine, e ora lo dice."""
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


def test_valore_fisso_NON_disabilita_le_tendine_avanzate(cpg):
    """Decisione del proprietario 2026-08-03, che corregge il primo giro dopo il rilievo
    CodeRabbit sulla PR #223.

    Il primo giro DISABILITAVA Trasformazione/Value-map sulle righe con valore fisso. Misurando
    è emerso che disabilitare **non disattiva la trasformazione** (vedi
    `test_la_trasformazione_si_applica_ANCHE_col_valore_fisso`): toglieva solo l'unico comando
    con cui l'utente poteva ripararla, lasciando la riga «⛔ Non pronto» senza via d'uscita.
    Restano attive; a spiegare il rischio è l'avviso.

    Fail-first: sul commit f0baf1d le due tendine risultavano `disabled`."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)

    con_fisso = _riga("Sì", transform="score_to_over")
    assert mod.CustomParserPanel._gate_fixed_value(finto, con_fisso) is True
    assert con_fisso["transform_menu"].stato == "normal", (
        "la tendina Trasformazione è di nuovo disabilitata: la trasformazione si applica lo "
        "stesso e l'utente non può più svuotarla")
    assert con_fisso["value_map_menu"].stato == "normal"

    senza = _riga("", transform="score_to_over")
    assert mod.CustomParserPanel._gate_fixed_value(finto, senza) is False
    assert senza["transform_menu"].stato == "normal"
    assert senza["value_map_menu"].stato == "normal"


def test_la_trasformazione_si_applica_ANCHE_col_valore_fisso(cpg):
    """**Il consumatore, non il sito** (regola 2-bis): la prova che disabilitare era cosmetico.

    Esegue il vero `_sync_to_builder` su una riga con Valore fisso E Trasformazione, con le
    tendine messe a `disabled`: la regola che finisce nel builder porta comunque la
    trasformazione. È la ragione tecnica per cui le tendine restano attive — e se un domani
    qualcuno le ri-disabilitasse credendo di disattivare la trasformazione, questo test
    resterebbe verde e lo smentirebbe.

    È anche la giustificazione dell'AVVISO: la combinazione è davvero pericolosa."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)
    finto.builder = mod.ParserBuilder()
    finto._name_var = types.SimpleNamespace(get=lambda: "P1")
    finto._mode_var = types.SimpleNamespace(get=lambda: mod.CustomParserPanel._MODE_INHERIT)
    finto._sport_var = types.SimpleNamespace(get=lambda: mod.CustomParserPanel._SPORT_UNSPECIFIED)
    finto._separator_var = types.SimpleNamespace(get=lambda: "")
    finto._selected_profiles = lambda: []
    finto._selected_market_profiles = lambda: []
    finto._sync_multi_to_builder = lambda: None
    finto._sync_conditions_to_builder = lambda: None

    riga = _riga("OVER_UNDER_25", transform="score_to_over")
    riga["transform_menu"].configure(state="disabled")      # come faceva il primo giro
    riga["value_map_menu"].configure(state="disabled")
    riga["target"] = "MarketName"
    riga["start_after"] = types.SimpleNamespace(get=lambda: "")
    riga["end_before"] = types.SimpleNamespace(get=lambda: "")
    riga["required"] = types.SimpleNamespace(get=lambda: False)
    finto._rows = [riga]

    mod.CustomParserPanel._sync_to_builder(finto)

    regola = finto.builder.rules[0]
    assert regola.fixed_value == "OVER_UNDER_25"
    assert regola.transform == "score_to_over", (
        "con la tendina DISABILITATA la trasformazione finisce comunque nel parser salvato: "
        "disabilitare non disattiva nulla, nasconde solo il comando per toglierla")


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
    produrre segnali **in silenzio**. Il gate deve restare a video.

    Il sorgente è ispezionato SENZA docstring (via AST): il docstring di `_gate_fixed_value`
    *nomina* `validate_parser_def` per dire che non la tocca, e una guardia testuale ingenua
    l'avrebbe scambiato per una chiamata — un test che fallisce su una spiegazione corretta."""
    src = _corpo_senza_docstring(cpg.CustomParserPanel._gate_fixed_value)
    src += _corpo_senza_docstring(cpg.CustomParserPanel._avviso_valore_fisso)
    assert "validate_parser_def" not in src, (
        "il gate ⑥ non deve passare dal validatore: renderebbe invalidi i parser salvati")
    # …e non deve nemmeno riscrivere i valori salvati del builder
    for vietato in ("rule.transform =", "rule.value_map =", ".set("):
        assert vietato not in src, f"il gate ⑥ modifica lo stato salvato ({vietato}): è sola presentazione"


def test_il_gate_si_riapplica_quando_il_valore_fisso_CAMBIA(cpg):
    """Rilievo Fugu (#223): il gate valeva solo alla creazione della riga.

    Fail-first: prima della correzione `_segui_valore_fisso` non esisteva, e scrivendo il
    valore fisso DOPO il disegno le tendine avanzate restavano abilitate e l'avviso stantio."""
    mod = cpg
    riapplicati = []
    finto = types.SimpleNamespace(
        _gate_fixed_value=lambda r: riapplicati.append("gate"),
        _mostra_avviso_valore_fisso=lambda: riapplicati.append("avviso"),
    )

    # forma StringVar (menu Provider / combo): si aggancia con trace_add
    tracce = {}
    class _Var:
        def trace_add(self, modo, cb): tracce[modo] = cb
    refs_var = {"fixed_value": _Var()}
    mod.CustomParserPanel._segui_valore_fisso(finto, refs_var)
    assert "write" in tracce, "nessun trace agganciato al StringVar del valore fisso"
    tracce["write"]()                                  # simula la scrittura dell'utente
    assert riapplicati == ["gate", "avviso"]

    # forma CTkEntry (testo libero): si aggancia con bind
    riapplicati.clear()
    legati = {}
    class _Entry:
        def bind(self, evento, cb): legati[evento] = cb
    refs_entry = {"fixed_value": _Entry()}
    mod.CustomParserPanel._segui_valore_fisso(finto, refs_entry)
    assert "<KeyRelease>" in legati and "<FocusOut>" in legati, legati
    legati["<KeyRelease>"](None)
    assert riapplicati == ["gate", "avviso"]


def test_segui_valore_fisso_non_esplode_su_widget_inerte(cpg):
    """Un doppio senza trace né bind non deve impedire di disegnare la riga."""
    mod = cpg
    finto = types.SimpleNamespace(_gate_fixed_value=lambda r: None,
                                  _mostra_avviso_valore_fisso=lambda: None)
    mod.CustomParserPanel._segui_valore_fisso(finto, {"fixed_value": object()})
    mod.CustomParserPanel._segui_valore_fisso(finto, {})          # nemmeno la chiave


def test_il_gate_fallisce_APERTO_se_il_widget_solleva(cpg):
    """Rilievo Sourcery (#223): il ramo difensivo di `_riga_ha_valore_fisso` non era coperto.

    «Meglio nessun avviso che un avviso sbagliato»: un widget che solleva non deve far esplodere
    il disegno della riga né far comparire l'avviso su una riga senza valore fisso."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)

    class _Menu:
        def __init__(self): self.stato = "normal"
        def configure(self, **k): self.stato = k.get("state", self.stato)

    def _esplode():
        raise RuntimeError("widget distrutto")

    refs = {"fixed_value": types.SimpleNamespace(get=_esplode),
            "transform_menu": _Menu(), "value_map_menu": _Menu()}

    assert mod.CustomParserPanel._riga_ha_valore_fisso(refs) is False
    assert mod.CustomParserPanel._gate_fixed_value(finto, refs) is False
    assert refs["transform_menu"].stato == "normal", "tendina toccata a sproposito"
    assert refs["value_map_menu"].stato == "normal"


def test_i_gestori_del_doppio_click_fermano_la_propagazione(cpg):
    """Rilievo Sourcery (#223): riga ED etichetta erano entrambe legate, quindi un doppio click
    sull'etichetta scattava lì e poi risaliva al frame — `_open_saved` due volte.

    Verifica il VALORE ritornato dal gestore, non la stringa nel sorgente (rilievo CodeRabbit
    e Fugu sullo stesso punto): la forma precedente era `azione(n) or "break"`, che smetteva di
    fermare la propagazione appena l'azione avesse iniziato a ritornare qualcosa di truthy —
    e un test che legge il sorgente non se ne sarebbe accorto."""
    mod = cpg
    eseguite = []

    gestore = mod.CustomParserPanel._gestore_click("P1", lambda n: eseguite.append(n))
    assert gestore(None) == "break", "il gestore non ferma la propagazione"
    assert eseguite == ["P1"], "l'azione non è stata eseguita"

    # …e continua a fermarla anche se l'azione ritorna un valore TRUTHY
    gestore_truthy = mod.CustomParserPanel._gestore_click("P2", lambda n: "qualcosa")
    assert gestore_truthy(None) == "break", (
        "il «break» dipende ancora da cosa ritorna l'azione: torna il doppio caricamento")


def test_il_badge_conta_ANCHE_parser_list_by_chat(cpg):
    """Rilievo CodeRabbit (#223): `parser_list_by_chat` è una chiave di config SEPARATA.

    Fail-first: prima della correzione una chat instradata solo dal router multi-parser non
    veniva contata, e il badge «📡 N» diceva «nessuna chat» su un parser in realtà usato."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)
    cfg = {
        "active_parser": "P1",
        "parser_by_chat": {"-100": "P1"},
        "parser_list_by_chat": {"-200": ["P1", "P2"], "-300": ["P2"]},
    }
    orig = mod.config_store.load_config
    try:
        mod.config_store.load_config = lambda *_a, **_k: cfg
        attivo, conteggio = mod.CustomParserPanel._parser_usage(finto)
    finally:
        mod.config_store.load_config = orig
    assert attivo == "P1"
    assert conteggio == {"P1": 2, "P2": 2}, conteggio


def test_il_badge_conta_CHAT_DISTINTE_non_binding(cpg):
    """Rilievo Fable/GPT-5.5 (#223): la stessa chat può comparire in ENTRAMBE le chiavi.

    `parser_by_chat` (singolo, retro-compat) e `parser_list_by_chat` (router multi-parser) sono
    separate: sommarle gonfiava il badge, che diceva «📡 2» su una sola chat.

    Fail-first: sul commit f0baf1d il conteggio di P1 era 2."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)
    cfg = {
        "active_parser": "P1",
        "parser_by_chat": {"-100": "P1"},
        "parser_list_by_chat": {"-100": ["P1", "P2"]},      # STESSA chat, anche in lista
    }
    orig = mod.config_store.load_config
    try:
        mod.config_store.load_config = lambda *_a, **_k: cfg
        _attivo, conteggio = mod.CustomParserPanel._parser_usage(finto)
    finally:
        mod.config_store.load_config = orig
    assert conteggio == {"P1": 1, "P2": 1}, (
        f"badge gonfiato: la chat -100 è UNA sola, contata due volte → {conteggio}")


def test_una_API_di_routing_mancante_NON_viene_mascherata(cpg):
    """Rilievo Fugu (#223): l'`except Exception` copriva anche le chiamate a `parser_manager`.

    Un nome di API sbagliato (`parser_list_by_chat` rinominata, un refactor incompleto) sarebbe
    finito nell'`AttributeError` → `return "", {}` → badge silenziosamente vuoto: esattamente la
    regressione che questa PR dichiara di correggere, rimascherata. Ora l'`except` copre **solo**
    la lettura del file di config; le tre letture di routing stanno fuori e un nome sbagliato
    esplode qui, dove un test lo vede.

    Fail-first: sul commit f0baf1d questa chiamata ritornava `("", {})` senza sollevare."""
    mod = cpg
    finto = object.__new__(mod.CustomParserPanel)

    def _api_sparita(_cfg):
        raise AttributeError("module 'parser_manager' has no attribute 'parser_list_by_chat'")

    orig_cfg = mod.config_store.load_config
    orig_api = mod.parser_manager.parser_list_by_chat
    try:
        mod.config_store.load_config = lambda *_a, **_k: {"active_parser": "P1"}
        mod.parser_manager.parser_list_by_chat = _api_sparita
        with pytest.raises(AttributeError):
            mod.CustomParserPanel._parser_usage(finto)
    finally:
        mod.config_store.load_config = orig_cfg
        mod.parser_manager.parser_list_by_chat = orig_api


def test_il_riaggancio_lega_entrambi_gli_eventi_anche_se_il_primo_fallisce(cpg):
    """Rilievo Fugu (#223): il `return` sul primo evento lasciava «<FocusOut>» non agganciato."""
    mod = cpg
    finto = types.SimpleNamespace(_gate_fixed_value=lambda r: None,
                                  _mostra_avviso_valore_fisso=lambda: None)
    legati = []

    class _EntryCapricciosa:
        def bind(self, evento, cb, add=None):
            legati.append(evento)
            if evento == "<KeyRelease>":
                raise RuntimeError("primo evento non legabile")

    mod.CustomParserPanel._segui_valore_fisso(finto, {"fixed_value": _EntryCapricciosa()})
    assert legati == ["<KeyRelease>", "<FocusOut>"], (
        f"il secondo evento non è stato tentato: {legati}")


def test_il_riaggancio_usa_add_per_non_sostituire_gli_handler_esistenti(cpg):
    """Rilievo GPT-5.5 (#223): senza `add="+"` il bind SOSTITUISCE gli handler che CTkEntry ha
    già su quegli eventi — regressione invisibile ai test coi doppi finti."""
    mod = cpg
    finto = types.SimpleNamespace(_gate_fixed_value=lambda r: None,
                                  _mostra_avviso_valore_fisso=lambda: None)
    visti = []

    class _Entry:
        def bind(self, evento, cb, add=None):
            visti.append((evento, add))

    mod.CustomParserPanel._segui_valore_fisso(finto, {"fixed_value": _Entry()})
    assert visti == [("<KeyRelease>", "+"), ("<FocusOut>", "+")], visti


def test_un_TypeError_interno_non_fa_ri_legare_SENZA_add(cpg):
    """Rilievo Fugu/GPT-5.5 (#223): il fallback `except TypeError` era troppo largo.

    Serviva a coprire i widget il cui `bind` non accetta `add`, ma un `TypeError` può nascere
    anche DENTRO il bind vero (o da un callback con firma sbagliata): in quel caso il fallback
    ri-legava **senza** `add="+"`, sostituendo gli handler che CTkEntry ha già su quegli eventi.
    Invisibile ai doppi finti, che non hanno handler da perdere. Ora il supporto di `add` si
    decide ispezionando la FIRMA, una volta sola, e un `TypeError` interno resta un errore.

    Fail-first: sul commit f0baf1d le chiamate registrate erano
    `["+", None, "+", None]` — cioè due ri-bind distruttivi."""
    mod = cpg
    finto = types.SimpleNamespace(_gate_fixed_value=lambda r: None,
                                  _mostra_avviso_valore_fisso=lambda: None)
    chiamate = []

    class _EntryConAddMaEsplosiva:
        def bind(self, evento, cb, add=None):
            chiamate.append(add)
            raise TypeError("errore interno del bind, non la firma")

    mod.CustomParserPanel._segui_valore_fisso(finto, {"fixed_value": _EntryConAddMaEsplosiva()})
    assert chiamate == ["+", "+"], (
        f"il fallback ha ri-legato senza add='+', sovrascrivendo gli handler di CTkEntry: {chiamate}")


def test_widget_senza_add_viene_legato_lo_stesso(cpg):
    """Controprova: il caso che il fallback serviva a coprire (widget il cui `bind` NON accetta
    `add`) deve restare agganciato — la firma lo dice, e si usa la forma a due argomenti."""
    mod = cpg
    finto = types.SimpleNamespace(_gate_fixed_value=lambda r: None,
                                  _mostra_avviso_valore_fisso=lambda: None)
    legati = []

    class _EntryVecchia:
        def bind(self, evento, cb):          # nessun parametro `add`
            legati.append(evento)

    mod.CustomParserPanel._segui_valore_fisso(finto, {"fixed_value": _EntryVecchia()})
    assert legati == ["<KeyRelease>", "<FocusOut>"], legati


def test_bind_non_ispezionabile_usa_comunque_add(cpg, monkeypatch):
    """In dubbio si sceglie la forma NON distruttiva: se la firma non è ispezionabile
    (`inspect.signature` solleva su certi builtin/oggetti C) si prova `add="+"`, che è il caso
    reale di Tk. Il ramo è simulato facendo sollevare `signature`, perché in CPython 3.11 i
    builtin comuni una firma ce l'hanno — e un test che non lo forzasse non coprirebbe nulla."""
    mod = cpg
    visti = []

    def _niente_firma(_f):
        raise ValueError("no signature found for builtin")

    monkeypatch.setattr(mod.inspect, "signature", _niente_firma)

    finto = types.SimpleNamespace(_gate_fixed_value=lambda r: None,
                                  _mostra_avviso_valore_fisso=lambda: None)

    def _bind(evento, cb, add=None):
        visti.append(add)

    assert mod.bind_accetta_add(_bind) is True
    mod.CustomParserPanel._segui_valore_fisso(finto, {"fixed_value": types.SimpleNamespace(bind=_bind)})
    assert visti == ["+", "+"], visti
