"""Pannello 🧩 Parser — #182 PR A punti ⑦ ⑧ ⑨.

Tre difetti **osservati dal vivo** dal proprietario, non ipotesi di design:

- **⑦** il pulsante di salvataggio si chiamava «💾 Salva» e non diceva *cosa* salva → un parser
  completo, configurato e collaudato, è rimasto **non persistito** («Parser salvati» su
  `(nessuno)`), a rischio di sparire chiudendo la finestra;
- **⑧** BetType era testo libero → `⛔ INVALID_BETTYPE` con **tutte** le altre colonne a `OK`,
  e il valore andava indovinato e digitato a mano;
- **⑨** l'avviso «separatore non trovato» diceva *cosa* era successo, non *cosa fare*; e col
  campo vuoto non diceva **nulla**, nemmeno su un nome palesemente divisibile.

Nessuno dei tre cambia il comportamento: nessuna riga CSV che oggi non verrebbe scritta viene
scritta, e nessuna che oggi viene scritta smette. Il blocco è la **PR S**, separata.
"""

import ast
import importlib
import inspect
import sys
import types

import pytest

from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import name_mapping_store, parser_builder, validator


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def cpg(monkeypatch):
    """Il modulo GUI sotto un finto `customtkinter` (stesso schema di
    `test_parser_panel_182.py`): headless non è istanziabile, ma la logica è quella vera."""
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.custom_parser_gui")
    yield mod
    sys.modules.pop("xtrader_bridge.custom_parser_gui", None)


def _bottoni_costruiti(func) -> list:
    """Etichette dei `CTkButton` davvero COSTRUITI in `func`, via AST (non ricerca testuale):
    un pulsante commentato non è una chiamata, e un refactor dell'indentazione non conta."""
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


# ── ⑦ «💾 Salva parser» ──────────────────────────────────────────────────────────────

def test_il_pulsante_dice_COSA_salva(cpg):
    """Fail-first: prima la label era «💾 Salva», muta sull'oggetto salvato."""
    bottoni = _bottoni_costruiti(cpg.CustomParserPanel._build_ui)
    assert "💾 Salva parser" in bottoni, f"la label non dice cosa salva: {bottoni}"
    assert "💾 Salva" not in bottoni, (
        "la label muta è tornata: nell'app ci sono già «💾 Salva Config», «💾 Salva profilo» "
        "e «💾 Salva chiave», e questo pulsante è il primo di quattro in fila con tre comandi "
        "di PROVA — senza l'oggetto si legge come parte di quel gruppo")


def test_il_comando_del_pulsante_e_ancora__save(cpg):
    """⑦ è **solo** la label: il comportamento del salvataggio non è toccato.

    Guardia AST sul `command=` del pulsante: se un domani qualcuno cambiasse anche l'azione
    credendo di ritoccare un'etichetta, questo test lo ferma."""
    import textwrap
    albero = ast.parse(textwrap.dedent(inspect.getsource(cpg.CustomParserPanel._build_ui)))
    comandi = []
    for n in ast.walk(albero):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "CTkButton"):
            continue
        etichetta = cmd = None
        for kw in n.keywords:
            v = kw.value
            if kw.arg == "text":
                if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                        and v.func.attr == "tr" and v.args):
                    v = v.args[0]
                if isinstance(v, ast.Constant):
                    etichetta = v.value
            elif kw.arg == "command" and isinstance(v, ast.Attribute):
                cmd = v.attr
        if etichetta == "💾 Salva parser":
            comandi.append(cmd)
    assert comandi == ["_save"], f"il comando del pulsante non è più `_save`: {comandi}"


def test_la_label_nuova_e_tradotta():
    """Ogni label nuova passa da EN/ES (principio comune della #182).

    Valore **esatto**, non «diverso dall'italiano»: il rilievo di CodeRabbit sulla PR #225 vale
    per tutta la classe, non solo per la riga che aveva citato — una traduzione sbagliata è
    comunque diversa dalla chiave, quindi il controllo di sola non-identità la lascia passare."""
    from xtrader_bridge import i18n
    prima = i18n.get_language()
    try:
        i18n.set_language("EN")
        assert i18n.tr("💾 Salva parser") == "💾 Save parser"
        i18n.set_language("ES")
        assert i18n.tr("💾 Salva parser") == "💾 Guardar parser"
    finally:
        i18n.set_language(prima)


def test_anche_la_nota_bettype_e_tradotta_col_testo_giusto():
    """L'altra chiave i18n introdotta da questa PR (#182 PR A ⑧): stessa regola, valore esatto.

    Cercare la CLASSE e non il sito: se si pretende il testo esatto per la label del pulsante,
    va preteso anche per la nota sotto la griglia, altrimenti la guardia copre metà del lavoro."""
    from xtrader_bridge import i18n
    chiave = ("ℹ️ BetType: PUNTA o BANCA sono gli unici valori che il CSV può contenere. "
              "BACK/LAY sono accettati in ingresso e convertiti automaticamente; "
              "FAVOR/CONTRA non sono supportati.")
    prima = i18n.get_language()
    try:
        i18n.set_language("EN")
        assert i18n.tr(chiave) == (
            "ℹ️ BetType: PUNTA or BANCA are the only values the CSV can contain. "
            "BACK/LAY are accepted as input and converted automatically; "
            "FAVOR/CONTRA are not supported.")
        i18n.set_language("ES")
        assert i18n.tr(chiave) == (
            "ℹ️ BetType: PUNTA o BANCA son los únicos valores que el CSV puede contener. "
            "BACK/LAY se aceptan como entrada y se convierten automáticamente; "
            "FAVOR/CONTRA no están soportados.")
        # …e i valori di dominio NON sono tradotti nemmeno dentro la nota che li nomina.
        for lingua in ("EN", "ES"):
            i18n.set_language(lingua)
            assert "PUNTA" in i18n.tr(chiave) and "BANCA" in i18n.tr(chiave)
    finally:
        i18n.set_language(prima)


# ── ⑧ tendina BetType ────────────────────────────────────────────────────────────────

def _regola(target, fixed_value=""):
    return types.SimpleNamespace(target=target, fixed_value=fixed_value, start_after="",
                                 end_before="", transform="", value_map="", required=False)


def _pannello_finto(cpg):
    """Un `self` finto con il minimo che serve a `_add_row`, e widget-spia al posto di Tk."""
    mod = cpg
    creati = {}

    class _Var:
        def __init__(self, value=""): self._v = value
        def get(self): return self._v
        def set(self, v): self._v = v

    class _Menu:
        def __init__(self, master=None, **k):
            self.values = list(k.get("values") or [])
            self.variable = k.get("variable")
            creati.setdefault("menu", []).append(self)
        def pack(self, **k): pass
        def configure(self, **k): self.values = list(k.get("values", self.values))

    class _Entry:
        def __init__(self, master=None, **k):
            creati.setdefault("entry", []).append(self)
            self._v = ""
        def insert(self, i, v): self._v = v
        def pack(self, **k): pass
        def get(self): return self._v
        def bind(self, evento, cb, add=None): pass

    class _Muto:
        def __init__(self, *a, **k): pass
        def pack(self, **k): pass

    finto = object.__new__(mod.CustomParserPanel)
    finto._rows = []
    finto._rows_frame = None
    finto._providers = ["Bet365"]
    finto._show_advanced = False
    finto._transforms = [""]
    finto._value_maps = [""]
    finto._market_terms = {}
    return mod, finto, creati, _Var, _Menu, _Entry, _Muto


def _disegna(monkeypatch, cpg, rule):
    """Esegue il VERO `_add_row` con widget-spia, e ritorna i `refs` prodotti."""
    mod, finto, creati, _Var, _Menu, _Entry, _Muto = _pannello_finto(cpg)
    monkeypatch.setattr(mod.ctk, "StringVar", _Var, raising=False)
    monkeypatch.setattr(mod.ctk, "BooleanVar", _Var, raising=False)
    monkeypatch.setattr(mod.ctk, "CTkOptionMenu", _Menu, raising=False)
    monkeypatch.setattr(mod.ctk, "CTkComboBox", _Menu, raising=False)
    monkeypatch.setattr(mod.ctk, "CTkEntry", _Entry, raising=False)
    monkeypatch.setattr(mod.ctk, "CTkFrame", _Muto, raising=False)
    monkeypatch.setattr(mod.ctk, "CTkLabel", _Muto, raising=False)
    monkeypatch.setattr(mod.ctk, "CTkCheckBox", _Muto, raising=False)
    mod.CustomParserPanel._add_row(finto, rule)
    return finto._rows[0]


def test_bettype_e_una_tendina_chiusa_con_i_soli_valori_del_csv(monkeypatch, cpg):
    """Fail-first: prima BetType cadeva nel ramo `else` = `CTkEntry` a testo libero.

    Conseguenza osservata: `⛔ INVALID_BETTYPE` con tutte le altre colonne a `OK`, perché il
    campo era vuoto e niente diceva cosa scrivere."""
    refs = _disegna(monkeypatch, cpg, _regola("BetType"))
    assert "bettype_menu" in refs, "BetType è ancora un campo di testo libero"
    assert refs["bettype_menu"].values == ["", "PUNTA", "BANCA"], refs["bettype_menu"].values


def test_la_tendina_NON_offre_back_lay_ne_favor_contra(monkeypatch, cpg):
    """Le tre esclusioni, motivate e bloccate contro una riapertura distratta.

    `BACK`/`LAY` sono accettati in INGRESSO e canonicalizzati, quindi in tendina sarebbero
    fuorvianti: sceglieresti `BACK` e nel CSV uscirebbe `PUNTA`. `FAVOR`/`CONTRA` non sono
    supportati: sceglierli darebbe **sempre** errore."""
    refs = _disegna(monkeypatch, cpg, _regola("BetType"))
    for escluso in ("BACK", "LAY", "FAVOR", "CONTRA"):
        assert escluso not in refs["bettype_menu"].values, (
            f"«{escluso}» non deve stare in tendina: {refs['bettype_menu'].values}")


def test_un_parser_salvato_con_BACK_non_perde_il_lato(monkeypatch, cpg):
    """⚠️ La regressione silenziosa che questo punto poteva introdurre.

    `BACK` è **valido** in ingresso (`_BETTYPE_CANON` lo converte in `PUNTA`), quindi un parser
    salvato può portarlo. Una tendina CHIUSA che non lo preservasse lo cancellerebbe alla prima
    apertura del pannello: il lato sparirebbe da un parser che oggi funziona, e il lato è
    l'unica colonna obbligatoria che non si indovina mai. Stesso trattamento che il ramo
    Provider riserva a un provider non più in anagrafica."""
    refs = _disegna(monkeypatch, cpg, _regola("BetType", fixed_value="BACK"))
    assert "BACK" in refs["bettype_menu"].values, (
        f"il valore salvato è stato cancellato dalla tendina: {refs['bettype_menu'].values}")
    assert refs["fixed_value"].get() == "BACK", "la selezione corrente non è più quella salvata"
    # …e resta valido a valle: la canonicalizzazione lo porta al lato giusto.
    assert validator.canonical_bettype("BACK") == "PUNTA"


def test_i_valori_della_tendina_NON_sono_tradotti():
    """Sono **value-as-key**: finiscono verbatim nel CSV, che non ha un BetType per lingua.

    Tradurli imporrebbe una ri-traduzione inversa al confine del contratto, col rischio di
    **invertire il lato della scommessa**. Guardia esplicita: se qualcuno li mettesse a
    catalogo, questo test fallisce."""
    from xtrader_bridge import i18n
    prima = i18n.get_language()
    try:
        for lingua in ("EN", "ES"):
            i18n.set_language(lingua)
            for valore in validator.CANONICAL_BETTYPES:
                assert i18n.tr(valore) == valore, (
                    f"«{valore}» è finito nel catalogo {lingua}: è un valore di dominio scritto "
                    "verbatim nel CSV, tradurlo può invertire il lato della scommessa")
    finally:
        i18n.set_language(prima)


def test_la_tendina_eredita_dal_validator_non_da_una_copia():
    """Fonte unica: la tendina legge `validator.CANONICAL_BETTYPES`, alias del privato usato
    dalla validazione. Se il contratto ammettesse un terzo lato, la tendina lo eredita senza
    che nessuno debba ricordarsi di allinearla."""
    assert validator.CANONICAL_BETTYPES is validator._CANONICAL_BETTYPES


# ── ⑨ avvisi separatore azionabili ───────────────────────────────────────────────────

@pytest.mark.parametrize("nome, atteso", [
    ("Al-Kholood Club v Al-Hilal", "v"),        # il caso reale che ha motivato il punto
    ("Milan vs Inter", "vs"),
    ("Roma - Lazio", "-"),
    ("Marseille / Lyon", "/"),
])
def test_detect_separator_riconosce_le_forme_spaziate(nome, atteso):
    assert name_mapping_store.detect_separator(nome) == atteso


@pytest.mark.parametrize("nome", [
    "", "   ", "Juventus",                       # niente da dividere
    "Al-Kholood Club",                           # trattino INTERNO, non spaziato
    "Marseille/Lyon",                            # slash compatto: non è una forma spaziata
])
def test_detect_separator_non_inventa(nome):
    """Non si suggerisce mai un separatore che poi non dividerebbe.

    `Al-Kholood Club` e `Marseille/Lyon` sono i due casi che contano: la guardia `spaced_only`
    esclude le forme compatte, quindi un `-` interno a un nome non viene mai proposto — è
    esattamente il taglio sbagliato che la #38 aveva già bloccato."""
    assert name_mapping_store.detect_separator(nome) is None


def test_il_suggerimento_e_sempre_un_separatore_che_FUNZIONA():
    """Proprietà, non esempio: qualunque separatore suggerito, scritto nel campo, divide davvero.

    È la ragione per cui `detect_separator` prova con `split_event` invece di una regex propria
    (fonte unica): un suggerimento che non funziona sarebbe peggio del silenzio."""
    for nome in ("Al-Kholood Club v Al-Hilal", "Milan vs Inter", "Roma - Lazio",
                 "Marseille / Lyon", "Paris Saint-Germain v Lyon"):
        sep = name_mapping_store.detect_separator(nome)
        assert sep is not None, nome
        assert name_mapping_store.split_event(nome, sep, spaced_only=True) is not None, (
            f"suggerito «{sep}» per «{nome}», ma non divide")


def test_avviso_azionabile_nomina_il_separatore_e_conserva_il_prefisso():
    """Fail-first: prima il testo era la costante fissa, senza dire cosa fare.

    Il prefisso storico resta invariato — è cercabile nel log dell'operatore e confrontato in
    molti test — e il suggerimento si aggiunge in coda."""
    testo = pipe.warn_team_separator_not_found("Al-Kholood Club v Al-Hilal")
    assert testo.startswith(pipe.WARN_TEAM_SEPARATOR_NOT_FOUND)
    assert "«v»" in testo and "Separatore squadre" in testo, testo


def test_avviso_invariato_quando_non_si_puo_suggerire_nulla():
    """Nessun suggerimento inventato: su un nome non divisibile il testo resta quello storico,
    identico al carattere."""
    assert pipe.warn_team_separator_not_found("Juventus") == pipe.WARN_TEAM_SEPARATOR_NOT_FOUND
    assert pipe.warn_team_separator_not_found("") == pipe.WARN_TEAM_SEPARATOR_NOT_FOUND


def test_hint_campo_vuoto_suggerisce_solo_se_il_nome_e_divisibile():
    """Fail-first: col campo vuoto non veniva detto **nulla**, mai."""
    hint = parser_builder.ParserBuilder.separator_hint("Al-Kholood Club v Al-Hilal", "")
    assert "«v»" in hint and "Separatore squadre" in hint, hint
    # nome non divisibile → silenzio (nessun suggerimento a vuoto)
    assert parser_builder.ParserBuilder.separator_hint("Juventus", "") == ""
    assert parser_builder.ParserBuilder.separator_hint("", "") == ""


def test_hint_tace_se_il_campo_e_gia_impostato():
    """Col campo impostato se ne occupa l'avviso #38: due messaggi sullo stesso tema sarebbero
    rumore. Vale anche col separatore SBAGLIATO (`-` su un nome che usa `v`): lì l'avviso #38
    scatta ed è già azionabile, quindi il suggerimento tacerebbe comunque."""
    assert parser_builder.ParserBuilder.separator_hint("Milan vs Inter", "vs") == ""
    assert parser_builder.ParserBuilder.separator_hint("Milan vs Inter", "-") == ""


def test_separatore_di_soli_spazi_conta_come_VUOTO():
    """Allineamento col runtime, che guarda `(defn.team_separator or "").strip()`: un campo di
    soli spazi **non** attiva la riformattazione, quindi per l'utente è vuoto — e il
    suggerimento deve comparire, altrimenti resterebbe nel silenzio proprio il caso in cui ha
    battuto uno spazio per sbaglio."""
    hint = parser_builder.ParserBuilder.separator_hint("Milan vs Inter", "  ")
    assert "«vs»" in hint, hint


def test_il_suggerimento_NON_passa_dai_warnings_del_runtime():
    """**Il consumatore, non il sito** (regola 2-bis) — e la decisione del proprietario.

    I `warnings` di `PipelineResult` sono loggati dal runtime a OGNI segnale (`app.py`, sia sul
    percorso piazzabile sia su quello scartato). Se il suggerimento a campo vuoto passasse di
    lì, un parser che funziona benissimo scriverebbe una riga identica per ogni segnale
    ricevuto, seppellendo gli avvisi veri. Vive solo nell'anteprima.

    Qui si esercita la pipeline VERA con separatore vuoto su un nome divisibile: nessun avviso."""
    from xtrader_bridge.custom_parser import CustomParserDef, FieldRule

    defn = CustomParserDef(
        name="P", mode="NAME_ONLY", team_separator="",
        rules=[FieldRule(target="EventName", fixed_value="Al-Kholood Club v Al-Hilal"),
               FieldRule(target="BetType", fixed_value="PUNTA"),
               FieldRule(target="Price", fixed_value="2.0"),
               FieldRule(target="Stake", fixed_value="5")])
    res = pipe.build_validated_row(defn, "messaggio qualunque")
    assert list(res.warnings) == [], (
        f"il suggerimento è finito nei warnings del runtime: {res.warnings}")


def test_il_verdetto_mostra_il_suggerimento_senza_cambiare_la_piazzabilita():
    """Il suggerimento si accoda al verdetto con 💡 (non ⚠: non è successo niente di anomalo),
    e «✅ Pronto» resta «✅ Pronto»."""
    vb = parser_builder.ParserBuilder.test_verdict
    comune = dict(errors=[], preview_rows=[], diag_placeable=True, diag_status="VALID",
                  res_row={"EventName": "Milan v Inter"}, res_missing_required=[],
                  res_detail=None)
    senza = vb(**comune)
    con = vb(**comune, res_hint="prova a mettere «v»")
    assert senza.startswith("✅ Pronto") and con.startswith("✅ Pronto"), (senza, con)
    assert con == senza + " · 💡 prova a mettere «v»"


def test_il_verdetto_e_invariato_senza_suggerimento():
    """Guardia anti-regressione: i chiamanti che non passano `res_hint` vedono esattamente il
    verdetto di prima (default retro-compatibile)."""
    vb = parser_builder.ParserBuilder.test_verdict
    comune = dict(errors=[], preview_rows=[], diag_placeable=True, diag_status="VALID",
                  res_row={"EventName": "X"}, res_missing_required=[], res_detail=None)
    assert vb(**comune) == vb(**comune, res_hint="")
