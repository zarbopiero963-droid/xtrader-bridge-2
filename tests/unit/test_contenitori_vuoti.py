"""Un contenitore VUOTO non deve riservare spazio (segnalazione proprietario 2026-08-04).

Sintomo: nella scheda «Parser Personalizzato» le sezioni «Output multi-riga» e
«Condizioni di gate» lasciano un buco alto anche quando non c'è nessuna riga, e
sotto «Prova messaggio» le due tabelle vuote fanno lo stesso.

Causa MISURATA (Xvfb, CustomTkinter reale, non dedotta):

    CTkFrame vuoto            → altezza richiesta 200 px  ← default di CustomTkinter
    CTkFrame con una riga     → altezza richiesta  32 px
    CTkFrame vuoto, height=0  → altezza richiesta   1 px

L'audit runtime dell'app vera ha trovato **cinque** contenitori che sprecano quei
200px a riposo — non i tre che si vedono a colpo d'occhio: `_multi_markets_box`,
`_multi_selections_box`, `_conditions_box` e anche `_preview_table` e `_diag_table`.
Totale **1000 px** di spazio morto nella scheda: più di uno schermo intero di
scorrimento inutile.

La guardia sorgente qui sotto ne trova **otto**, ed è la differenza che conta
(regola 2, la classe e non il sito): `_rules_head`, `_rows_frame` e l'intestazione
del diario si riempiono subito dopo la costruzione, quindi a riposo non si vedono —
ma sono contenitori dinamici uguali agli altri, e su un percorso d'errore restano
vuoti davvero. Il diario è il caso concreto: se la lettura del ledger fallisce si
esce con l'intestazione appena svuotata, e lì il buco compare.

Seconda misura, quella che decide il rimedio: svuotare un contenitore NON lo fa
tornare basso da solo — l'altezza richiesta resta quella dell'ultimo contenuto
(102 px con zero figli). Serve rimettere `height=0` DOPO la rimozione, non solo
alla costruzione: per questo `collapse_when_empty` va chiamata a ogni mutazione
delle righe, e non basta un `height=0` nel costruttore.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import sys
import types

import pytest

import license_manager as _license_manager_pkg

from xtrader_bridge import ui_cards

PKG = pathlib.Path(ui_cards.__file__).parent
# Stessa copertura della guardia scroll: bridge + app License Manager, path presi
# dai moduli IMPORTATI (non da posizioni relative).
PACKAGES = (PKG, pathlib.Path(_license_manager_pkg.__file__).parent)


# ── comportamento dell'helper ────────────────────────────────────────────────
class _BoxDoppio:
    """Doppio di un CTkFrame: registra le `configure` ricevute."""

    def __init__(self, figli=()):
        self._figli = list(figli)
        self.configurato = {}

    def winfo_children(self):
        return self._figli

    def configure(self, **kw):
        self.configurato.update(kw)


def test_contenitore_vuoto_viene_collassato():
    box = _BoxDoppio()
    ui_cards.collapse_when_empty(box)
    assert box.configurato == {"height": 0}


def test_contenitore_pieno_resta_intatto():
    """Con dei figli la propagazione del pack decide l'altezza: toccare `height`
    non serve, e un contenitore pieno non va mai ridimensionato a mano."""
    box = _BoxDoppio(figli=["riga"])
    ui_cards.collapse_when_empty(box)
    assert box.configurato == {}


def test_ricollassa_dopo_lo_svuotamento():
    """Il caso che il solo `height=0` alla costruzione NON copre (misurato): il
    contenitore si riempie, poi si svuota, e deve tornare basso."""
    box = _BoxDoppio(figli=["riga"])
    ui_cards.collapse_when_empty(box)
    assert box.configurato == {}
    box._figli.clear()
    ui_cards.collapse_when_empty(box)
    assert box.configurato == {"height": 0}


def test_best_effort_su_doppi_e_widget_distrutti():
    """Stessa promessa di `tune_scrolling`: presentazione, mai un crash."""
    ui_cards.collapse_when_empty(object())        # nessun winfo_children

    class _Rotto:
        def winfo_children(self):
            raise RuntimeError("widget distrutto")

        def configure(self, **kw):
            raise RuntimeError("widget distrutto")

    ui_cards.collapse_when_empty(_Rotto())


# ── la CLASSE, non i cinque siti visibili (regola 2) ─────────────────────────
def _nome_target(nodo) -> str | None:
    """Rappresentazione testuale del bersaglio: `x` o `self._x` (altro → None)."""
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        return f"{nodo.value.id}.{nodo.attr}"
    return None


def _funzioni(tree):
    """Ogni FunctionDef del modulo con i nomi che RIEMPIE.

    «Riempire» è un segnale preciso, non una menzione qualsiasi: il nome compare
    come argomento posizionale di una chiamata — cioè come genitore di un widget
    (``ctk.CTkLabel(self._box, …)``) o come contenitore passato a un disegnatore
    (``self._add_row(self._box, …)``, ``self._clear(self._box)``) — oppure gli si
    chiedono i figli (``self._box.winfo_children()``) per distruggerli.

    Restano fuori le referenze di sola geometria/ciclo di vita (``pack``,
    ``pack_forget``, ``destroy``, ``configure``): nascondere o ri-impaccare un
    contenitore non lo riempie, e chi lo costruisce già pieno non ha il difetto.
    """
    for nodo in ast.walk(tree):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            riempiti = set()
            for sotto in ast.walk(nodo):
                if not isinstance(sotto, ast.Call):
                    continue
                for arg in sotto.args:
                    nome = _nome_target(arg)
                    if nome:
                        riempiti.add(nome)
                if (isinstance(sotto.func, ast.Attribute)
                        and sotto.func.attr == "winfo_children"):
                    nome = _nome_target(sotto.func.value)
                    if nome:
                        riempiti.add(nome)
            yield nodo, riempiti


def contenitori_dinamici_non_collassati(src: str) -> list[str]:
    """Contenitori RIEMPITI DA ALTRE FUNZIONI che nessuno collassa.

    Un frame costruito e riempito nella stessa funzione ha sempre il suo contenuto:
    non è mai vuoto, e non c'entra. Il difetto sta nei contenitori *dinamici* —
    quelli il cui nome ricompare in un'ALTRA funzione, che è dove le righe vengono
    aggiunte, distrutte o ridisegnate: quelli nascono vuoti, e possono tornare
    vuoti. Ognuno di loro deve passare da `ui_cards.collapse_when_empty`.
    """
    tree = ast.parse(src)
    definiti: dict[str, ast.AST] = {}      # nome → funzione che lo costruisce
    for fn, _ in _funzioni(tree):
        for nodo in ast.walk(fn):
            if not (isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call)):
                continue
            f = nodo.value.func
            # SOLO `CTkFrame`: una `CTkScrollableFrame` è un VISORE, non un
            # contenitore di righe — porta la sua altezza dal geometry manager e
            # collassarla cancellerebbe l'area di scorrimento invece del vuoto.
            if not (isinstance(f, ast.Attribute) and f.attr == "CTkFrame"):
                continue
            for t in nodo.targets:
                nome = _nome_target(t)
                # Solo attributi d'istanza: un frame LOCALE muore con la funzione
                # che lo ha costruito, quindi nessun'altra può riempirlo.
                if nome and nome.startswith("self."):
                    definiti[nome] = fn

    dinamici = {nome for nome, fn_def in definiti.items()
                if any(nome in riempiti and fn is not fn_def
                       for fn, riempiti in _funzioni(tree))}

    collassati = set()
    for nodo in ast.walk(tree):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "collapse_when_empty" and nodo.args):
            nome = _nome_target(nodo.args[0])
            if nome:
                collassati.add(nome)
    return sorted(dinamici - collassati)


def test_ogni_contenitore_dinamico_dei_due_package_viene_collassato():
    rotti = []
    for pkg in PACKAGES:
        for path in sorted(pkg.rglob("*.py")):
            if path.name == "ui_cards.py":
                continue
            for nome in contenitori_dinamici_non_collassati(
                    path.read_text(encoding="utf-8")):
                rotti.append(f"{path.name}: `{nome}` riempito altrove ma mai collassato "
                             "→ 200px di vuoto quando non ha righe")
    assert rotti == [], "\n".join(rotti)


def test_la_guardia_riconosce_il_difetto_e_non_grida_al_lupo():
    """Le fixture della guardia, così un domani non la si allenta per sbaglio."""
    costruzione = ("class P:\n"
                   "    def _build(self):\n"
                   "        self._box = ctk.CTkFrame(sec)\n")
    riempimento = ("    def _aggiungi(self):\n"
                   "        ctk.CTkFrame(self._box).pack()\n")
    # riempito da un'altra funzione e mai collassato → difetto
    assert contenitori_dinamici_non_collassati(costruzione + riempimento) == ["self._box"]
    # collassato → a posto
    assert contenitori_dinamici_non_collassati(
        costruzione + riempimento
        + "    def _togli(self):\n        ui_cards.collapse_when_empty(self._box)\n") == []
    # costruito E riempito nella stessa funzione → non è un contenitore dinamico
    assert contenitori_dinamici_non_collassati(
        "class P:\n"
        "    def _build(self):\n"
        "        self._riga = ctk.CTkFrame(sec)\n"
        "        ctk.CTkLabel(self._riga, text='x').pack()\n") == []
    # frame LOCALE riempito altrove: impossibile, e infatti non viene segnalato
    assert contenitori_dinamici_non_collassati(
        "class P:\n"
        "    def _build(self):\n"
        "        box = ctk.CTkFrame(sec)\n"
        "    def _altro(self):\n"
        "        ctk.CTkLabel(box).pack()\n") == []
    # nato PIENO e altrove solo mostrato/nascosto: non è un contenitore dinamico
    # (è il caso reale della barra proposta dell'assistente) → niente falso allarme
    assert contenitori_dinamici_non_collassati(
        "class P:\n"
        "    def _build(self):\n"
        "        self._bar = ctk.CTkFrame(outer)\n"
        "        ctk.CTkLabel(self._bar, text='x').pack()\n"
        "    def _mostra(self):\n"
        "        self._bar.pack(fill='x')\n"
        "    def _nascondi(self):\n"
        "        self._bar.pack_forget()\n") == []
    # svuotato da un'altra funzione: è dinamico eccome
    assert contenitori_dinamici_non_collassati(
        "class P:\n"
        "    def _build(self):\n"
        "        self._t = ctk.CTkFrame(outer)\n"
        "    def _render(self):\n"
        "        for c in self._t.winfo_children():\n"
        "            c.destroy()\n") == ["self._t"]


# ── il percorso REALE: togliere l'ultima riga deve ricollassare ──────────────
class _WidgetFinto:
    """Doppio di widget che simula la PARENTELA vera: chi nasce con un genitore
    diventa suo figlio, `destroy()` lo toglie. Serve perché `collapse_when_empty`
    decide proprio su `winfo_children()` — un doppio senza figli direbbe sempre
    «vuoto» e il test non proverebbe nulla."""

    def __init__(self, parent=None, **kwargs):
        self.kwargs = kwargs
        self._figli = []
        self._parent = parent
        self.configurato = {}
        if isinstance(parent, _WidgetFinto):
            parent._figli.append(self)

    def winfo_children(self):
        return list(self._figli)

    def configure(self, **kw):
        self.configurato.update(kw)

    def destroy(self):
        if isinstance(self._parent, _WidgetFinto) and self in self._parent._figli:
            self._parent._figli.remove(self)

    def get(self):
        return ""

    def __getattr__(self, _name):        # pack/grid/insert/bind/set/…
        return lambda *a, **k: None


class _CtkEseguibile(types.ModuleType):
    """Stub CTk *eseguibile*: i widget si costruiscono davvero, così i metodi del
    pannello girano headless (stesso pattern di `test_transform_whitelist`)."""

    def __getattr__(self, name):
        setattr(self, name, _WidgetFinto)
        return _WidgetFinto


@pytest.fixture()
def gui(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _CtkEseguibile("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.custom_parser_gui")
    yield mod
    sys.modules.pop("xtrader_bridge.custom_parser_gui", None)


def test_togliere_l_ultima_riga_multi_ricollassa_il_contenitore(gui):
    """Il difetto che il solo `height=0` alla costruzione NON copre, sul codice
    vero: si aggiunge una riga (il contenitore cresce), la si toglie, e il
    contenitore deve tornare a chiedere altezza zero invece di lasciare il buco."""
    pannello = types.SimpleNamespace(
        _MULTI_FIELDS=gui.CustomParserPanel._MULTI_FIELDS,
        _refresh_multi_warnings=lambda: None)
    box = _WidgetFinto()
    righe = []
    gui.CustomParserPanel._add_multi_row_widget(
        pannello, box, righe, gui.MultiRowRule())

    assert box.winfo_children(), "la riga non è finita nel contenitore"
    box.configurato.clear()          # dimentica il collasso della costruzione

    gui.CustomParserPanel._remove_multi_row(pannello, righe, righe[0])
    assert righe == []
    assert box.winfo_children() == []
    assert box.configurato == {"height": 0}, (
        "tolta l'ultima riga il contenitore resta alto quanto il contenuto vecchio: "
        "al posto delle righe compare un buco della stessa altezza")


def test_togliere_una_riga_su_due_non_collassa(gui):
    """Il contenitore che ha ancora righe non va toccato: decide la propagazione."""
    pannello = types.SimpleNamespace(
        _MULTI_FIELDS=gui.CustomParserPanel._MULTI_FIELDS,
        _refresh_multi_warnings=lambda: None)
    box = _WidgetFinto()
    righe = []
    for _ in range(2):
        gui.CustomParserPanel._add_multi_row_widget(
            pannello, box, righe, gui.MultiRowRule())
    box.configurato.clear()

    gui.CustomParserPanel._remove_multi_row(pannello, righe, righe[0])
    assert len(box.winfo_children()) == 1
    assert box.configurato == {}


def test_togliere_l_ultima_condizione_ricollassa_il_contenitore(gui):
    """Stessa invariante sull'altra sezione, per il suo percorso di rimozione."""
    pannello = types.SimpleNamespace(
        _conditions_box=_WidgetFinto(), _condition_rows=[],
        _COND_CONTAINS=gui.CustomParserPanel._COND_CONTAINS,
        _COND_NOT_CONTAINS=gui.CustomParserPanel._COND_NOT_CONTAINS)
    gui.CustomParserPanel._add_condition_row_widget(pannello, gui.Condition())
    assert pannello._conditions_box.winfo_children()
    pannello._conditions_box.configurato.clear()

    gui.CustomParserPanel._remove_condition_row(pannello, pannello._condition_rows[0])
    assert pannello._condition_rows == []
    assert pannello._conditions_box.configurato == {"height": 0}


def test_non_collassa_quando_non_puo_SAPERE_se_e_vuoto():
    """Rilievo bloccante di Claude Fable 5 sulla #249, accolto.

    `_best_effort` ritorna `None` sia per «metodo assente» sia per «ha sollevato»:
    trattare quel `None` come «nessun figlio» confonde *non lo so* con *è vuoto*, e
    su un widget in distruzione si finiva a chiamare `configure` comunque. È il
    contrario del fail-safe — quando l'informazione manca la cosa giusta è non
    toccare nulla, non indovinare.

    Il caso è benigno oggi (con figli la propagazione ignora `height`, e l'errore
    verrebbe assorbito), ma la regola vale prima del prossimo chiamante, non dopo."""
    chiamate = []

    class _FigliIllegibili:
        def winfo_children(self):
            raise RuntimeError("widget in distruzione")

        def configure(self, **kw):
            chiamate.append(kw)

    ui_cards.collapse_when_empty(_FigliIllegibili())
    assert chiamate == [], (
        "non si sapeva se fosse vuoto e lo si è ridimensionato lo stesso")


def test_non_collassa_un_doppio_che_non_sa_dire_i_figli():
    """Stessa ambiguità dall'altro lato: metodo del tutto assente."""
    chiamate = []

    class _SenzaFigli:
        def configure(self, **kw):
            chiamate.append(kw)

    ui_cards.collapse_when_empty(_SenzaFigli())
    assert chiamate == []
