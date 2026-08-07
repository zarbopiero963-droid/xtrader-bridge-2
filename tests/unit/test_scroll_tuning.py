"""Scorrimento fluido delle CTkScrollableFrame (segnalazione proprietario 2026-08-04).

Sintomo su Windows: nella scheda Parser Personalizzato (soprattutto sulla
«Griglia regole — 14 colonne CSV») lo scroll con la rotellina «scatta/trema».
Causa misurata: CustomTkinter su Windows imposta ``yscrollincrement=1`` e scrolla
``-delta/6`` (=20) unità per scatto → **20px a scatto** su un contenuto di
~2600px: ~130 scatti per attraversarlo, e OGNI scatto ridisegna decine di widget
con angoli arrotondati → tremolio percepito.

Rimedio di allora (fonte unica, regola 3): ``ui_cards.tune_scrolling(sf)`` regola
gli increment del canvas — **oggi 1px**, era 3px fino alla #319 (vedi sotto). Va
chiamata su OGNI CTkScrollableFrame del package (la classe, non il sito — regola
2): il test sorgente qui sotto lo impone contando costruzioni e chiamate per
modulo. Dalla #320 si applica **solo su Windows**: altrove CTk scrolla un numero
di unità diverso e forzare il passo di Windows rende lo scroll inservibile.

⚠️ **Aggiornamento #319 (2026-08-07): il passo è tornato a 1px come MISURA**, non
come configurazione definitiva. Il proprietario ha filmato l'effetto opposto al
tremolio — scorrendo, il testo lascia una **scia di decine di copie**.

**Cosa è accertato e cosa no** (rilievo CodeRabbit sulla #320, fondato). Accertato:
CTk chiede a Tk **20 unità** di scorrimento per scatto (``-int(event.delta / 6)``
con ``delta=120``), il valore è cablato nel suo sorgente, e ``tune_scrolling``
regola solo la **dimensione** dell'unità. **Non** accertato: quanti ridisegni Tk
esegua davvero — Tk accorpa i ridisegni a idle, quindi 20 unità richieste non sono
necessariamente 20 ridisegni. I fotogrammi mostrano una scia di molte copie, ma il
numero non è stato misurato: dedurlo sarebbe un'inferenza travestita da dato.

Quello che la misura vuole sapere è solo questo: con il passo a **1** il
proprietario rivede la **sfocatura** del 04/08 o resta la **scia**? La risposta
dice se il passo c'entra, e nient'altro.
"""
from __future__ import annotations

import ast
import pathlib

from xtrader_bridge import ui_cards

import license_manager as _license_manager_pkg

PKG = pathlib.Path(ui_cards.__file__).parent
# Anche l'app License Manager (separata) ha GUI scrollabili: la guardia copre
# entrambe (segnalazione proprietario 2026-08-04: «controlla anche le altre
# parti dove ho lo scroll» — l'audit runtime ha trovato il suo pannello nudo).
# I path vengono dai moduli IMPORTATI, non da posizioni relative (Sourcery #242).
PACKAGES = (PKG, pathlib.Path(_license_manager_pkg.__file__).parent)


class _CanvasDoppio:
    def __init__(self):
        self.kwargs = {}

    def configure(self, **kw):
        self.kwargs.update(kw)


class _ScrollableDoppio:
    def __init__(self):
        self._parent_canvas = _CanvasDoppio()


def test_tune_scrolling_imposta_gli_increment_a_1px(monkeypatch):
    """⚠️ Valore di MISURA (#319, 2026-08-07), non configurazione definitiva.

    Era `3`, scelto il 04/08 contro il «tremolio». Il 07/08 il proprietario ha
    filmato l'effetto opposto — una scia di decine di copie — e la Phase 0 ha
    stabilito che i due valori non sono due rimedi ma una **scelta estetica sullo
    stesso difetto**: `tune_scrolling` regola la dimensione del quanto, non il
    numero di quanti richiesti per scatto (vedi il test qui sotto), quindi cambia
    solo quanto sono distanziate le copie, non che ci siano.

    Tornare a `1` risponde a una domanda sola: il proprietario rivede la sfocatura
    del 04/08? Se sì, il difetto è nella ripulitura del canvas ed è lì che va la
    correzione vera. Questo test **pinna il valore** perché il ritorno a 1 sia una
    decisione leggibile e non una regressione silenziosa.

    È anche il lato POSITIVO del gate di piattaforma introdotto dalla #320 — il lato
    negativo è `test_su_linux_e_macos_NON_si_tocca_il_default_di_customtkinter`:
    l'accordatura si applica su Windows, e solo lì. Per questo il test **dichiara** la
    piattaforma invece di ereditare quella del runner: senza il monkeypatch passerebbe
    su Windows e fallirebbe in CI, cioè misurerebbe il runner e non il codice."""
    monkeypatch.setattr(ui_cards.sys, "platform", "win32")
    sf = _ScrollableDoppio()
    ui_cards.tune_scrolling(sf)
    assert sf._parent_canvas.kwargs == {"xscrollincrement": 1, "yscrollincrement": 1}


def test_su_linux_e_macos_NON_si_tocca_il_default_di_customtkinter(monkeypatch):
    """Rilievo GPT-5.5 sulla #320, e il conto è peggio di come l'avevo scritto.

    `tune_scrolling` sovrascriveva l'increment su **tutte** le piattaforme, ma CTk non
    scrolla lo stesso numero di unità ovunque:

    | piattaforma | unità per scatto | increment CTk | px per scatto |
    |---|---|---|---|
    | Windows | 20 (`-delta/6`) | 1 | 20 |
    | macOS   | `-delta`        | 4/8 | dipende dal delta |
    | Linux   | **1** (`yview_scroll(±1)`) | **30** | **30** |

    Su Linux una rotellina vale **una sola unità**: l'increment È il passo. Quindi dal
    04/08 `tune_scrolling(3)` ha reso lo scorrimento **3 px per scatto** invece di 30 —
    dieci volte più lento, di fatto inservibile — e la misura a 1 px lo avrebbe portato a
    **1 px per scatto**.

    Nessuno se n'era accorto perché il bersaglio è Windows e su Linux gira solo la
    pipeline screenshot, che non scrolla. Ma è una regressione vera, introdotta da una
    correzione pensata per un'altra piattaforma: la Regola 2-bis presa in flagrante.

    L'accordatura si applica **solo dove il suo ragionamento vale** — Windows, l'unica
    piattaforma nominata nel docstring della funzione. Altrove si lascia il default di CTk.
    """
    for piattaforma in ("linux", "darwin"):
        monkeypatch.setattr(ui_cards.sys, "platform", piattaforma)
        sf = _ScrollableDoppio()
        ui_cards.tune_scrolling(sf)
        assert sf._parent_canvas.kwargs == {}, (
            f"su {piattaforma!r} l'increment è stato sovrascritto: CTk lì scrolla un numero "
            "di unità diverso, e forzare il passo di Windows rende lo scorrimento inutilizzabile")


def test_customtkinter_scrolla_VENTI_unita_per_scatto_e_non_e_configurabile():
    """La scoperta della Phase 0 #319, resa eseguibile invece che lasciata in un commento.

    `tune_scrolling` regola il **quanto** di scorrimento. Il **numero** di quanti per
    scatto di rotellina non è nostro: sta cablato in CustomTkinter come
    `-int(event.delta / 6)`, e con il `delta` di Windows (±120) fa **20 unità**.

    Da qui la conseguenza che governa tutta la #319: qualunque valore di `step_px`
    lascia **lo stesso numero di unità richieste** — venti — e cambia solo di quanti
    pixel vale ognuna. Quindi `tune_scrolling` sposta la geometria dello scorrimento,
    non la quantità di lavoro che Tk riceve.

    ⚠️ Quello che questo test dimostra è **il divisore, non i ridisegni** (rilievo
    CodeRabbit sulla #320, fondato): `_mouse_wheel_all` emette UN solo comando
    `yview("scroll", -int(event.delta/6), "units")`, e Tk accorpa i ridisegni a idle.
    Venti unità richieste NON sono per forza venti ridisegni: quel conto non è stato
    misurato e qui non viene asserito. Resta accertato solo che il numero di unità è
    cablato in CTk e fuori dalla nostra portata.

    Il test legge il sorgente di CTk installato: se una versione futura cambiasse
    quel divisore, la premessa della #319 cadrebbe e va rifatta l'analisi invece di
    ereditarla. È esattamente il tipo di assunzione di terze parti che rompe in
    silenzio."""
    import customtkinter
    from customtkinter.windows.widgets import ctk_scrollable_frame

    src = pathlib.Path(ctk_scrollable_frame.__file__).read_text(encoding="utf-8")
    assert "event.delta / 6" in src, (
        f"CustomTkinter {customtkinter.__version__} non divide più il delta per 6: il conto "
        "«20 unità per scatto» su cui poggia la #319 non vale più, rifare la misura")

    # E il quanto lo impostiamo NOI dopo la costruzione: CTk lo tocca una volta sola
    # nell'__init__, quindi `tune_scrolling` non viene sovrascritta a runtime. Se un
    # domani `_set_scroll_increments` venisse richiamata (es. al cambio di scaling),
    # la nostra accordatura sparirebbe senza che nessuno se ne accorga.
    assert src.count("self._set_scroll_increments()") == 1, (
        "CustomTkinter ora chiama `_set_scroll_increments` più di una volta: può "
        "sovrascrivere `tune_scrolling` a runtime, verificare quando")


def test_tune_scrolling_passo_personalizzato(monkeypatch):
    monkeypatch.setattr(ui_cards.sys, "platform", "win32")
    sf = _ScrollableDoppio()
    ui_cards.tune_scrolling(sf, step_px=5)
    assert sf._parent_canvas.kwargs == {"xscrollincrement": 5, "yscrollincrement": 5}


def test_tune_scrolling_best_effort_su_doppio_senza_canvas(monkeypatch):
    """Doppio headless senza `_parent_canvas` (o canvas che solleva): mai un crash —
    lo scroll resta quello di default, la GUI vive.

    Il monkeypatch a `win32` non è cosmesi: senza, il gate di piattaforma della #320
    farebbe uscire la funzione PRIMA del `try`, e il test passerebbe **a vuoto** su
    Linux — verde senza aver mai esercitato il best-effort che pretende di coprire."""
    monkeypatch.setattr(ui_cards.sys, "platform", "win32")
    ui_cards.tune_scrolling(object())          # nessun _parent_canvas

    class _CanvasRotto:
        def configure(self, **kw):
            raise RuntimeError("canvas distrutto")

    class _SfRotto:
        _parent_canvas = _CanvasRotto()

    ui_cards.tune_scrolling(_SfRotto())        # configure che solleva → assorbito


def test_la_scansione_copre_anche_i_sottopackage():
    """Rilievo CodeRabbit #241: `glob` vedeva solo i figli diretti — una scrollable
    aggiunta in un sottopackage (es. `betfair/`) avrebbe bypassato la guardia.
    Il contratto è ricorsivo: la scansione deve includere i moduli annidati."""
    annidati = [p for p in PKG.rglob("*.py") if p.parent != PKG]
    assert annidati, "il package ha sottomoduli: se spariscono, rivedere la guardia"
    assert set(PKG.rglob("*.py")) >= set(annidati)


def _nome_target(nodo) -> str | None:
    """Rappresentazione testuale del bersaglio: `x` o `self._x` (altro → None)."""
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        return f"{nodo.value.id}.{nodo.attr}"
    return None


def _scrollable_non_accordate(src: str) -> list[str]:
    """Analisi STRUTTURALE (rilievo CodeRabbit #242: il conteggio testuale poteva
    essere ingannato da un commento o da una chiamata doppia): ogni variabile a cui
    è assegnata una `ctk.CTkScrollableFrame(...)` deve comparire come argomento di
    una `ui_cards.tune_scrolling(...)` nello stesso modulo."""
    tree = ast.parse(src)
    costruite: list[str] = []
    accordate: set[str] = set()
    for nodo in ast.walk(tree):
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call):
            f = nodo.value.func
            if isinstance(f, ast.Attribute) and f.attr == "CTkScrollableFrame":
                for t in nodo.targets:
                    nome = _nome_target(t)
                    if nome:
                        costruite.append(nome)
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "tune_scrolling" and nodo.args):
            nome = _nome_target(nodo.args[0])
            if nome:
                accordate.add(nome)
    return [n for n in costruite if n not in accordate]


def test_ogni_scrollable_di_entrambi_i_package_viene_accordata():
    """La classe, non il sito — su ENTRAMBI i package (bridge + License Manager):
    ogni `CTkScrollableFrame` costruita deve essere passata a `tune_scrolling`,
    con associazione per-variabile (non per conteggio)."""
    rotti = []
    for pkg in PACKAGES:
        for path in sorted(pkg.rglob("*.py")):
            if path.name == "ui_cards.py":
                continue
            for nome in _scrollable_non_accordate(path.read_text(encoding="utf-8")):
                rotti.append(f"{path.name}: `{nome}` costruita ma mai accordata")
    assert rotti == [], "\n".join(rotti)


def test_guardia_strutturale_non_si_fa_ingannare():
    """Le fixture del rilievo: un commento non conta come accordatura, una chiamata
    doppia su un'altra variabile non copre quella nuda."""
    assert _scrollable_non_accordate(
        "a = ctk.CTkScrollableFrame(x)\n# ui_cards.tune_scrolling(a)\n") == ["a"]
    assert _scrollable_non_accordate(
        "a = ctk.CTkScrollableFrame(x)\nb = ctk.CTkScrollableFrame(x)\n"
        "ui_cards.tune_scrolling(a)\nui_cards.tune_scrolling(a)\n") == ["b"]
    assert _scrollable_non_accordate(
        "self._lista = ctk.CTkScrollableFrame(x)\n"
        "ui_cards.tune_scrolling(self._lista)\n") == []
