"""Scorrimento delle `CTkScrollableFrame`: perché NON accordiamo più gli increment.

## Storia, in tre atti

**04/08/2026** — segnalazione proprietario: la griglia del Parser «scatta/trema» sotto
rotellina su Windows. Rimedio introdotto: `ui_cards.tune_scrolling(sf)`, che portava
`xscrollincrement`/`yscrollincrement` del canvas a 3px, chiamata su ogni scrollable dei
due package e presidiata da un test-guardia AST.

**07/08/2026 (#319)** — segnalazione proprietario: scorrendo, il testo lascia una **scia
di copie**. Costruito un EXE di misura col passo riportato a 1 e filmato: la scia è
**identica**.

**07/08/2026, sera** — la misura era un no-op, e l'accordatura pure. Vedi sotto.

## Perché l'accordatura è stata RIMOSSA

CustomTkinter imposta **già** gli increment, per piattaforma, in
`CTkScrollableFrame._set_scroll_increments()`:

    Windows → 1     macOS → 4/8     altrove (Linux) → 30

Quindi `tune_scrolling(1)` su Windows **riscriveva il valore che CTk aveva già scritto**:
zero effetto. E su Linux `tune_scrolling(3)` sostituiva 30 con 3, rendendo lo scorrimento
**dieci volte più lento** — una regressione introdotta da una correzione pensata per
un'altra piattaforma, rimasta su `main` dal 04/08 al 07/08.

Il valore dell'increment è stato **escluso come causa** della #319 da due prove
indipendenti sul PC del proprietario (scia identica a 1 e a 3). Rimuovere l'accordatura
restituisce a ogni piattaforma il default di CustomTkinter e toglie una funzione che non
configurava nulla, insieme al test-guardia che ne imponeva l'uso.

## Cosa resta presidiato qui

1. **nessuno** sovrascrive gli increment di CTk (guardia inversa di quella storica);
2. le **assunzioni su CustomTkinter** su cui poggia l'analisi della #319 — se una versione
   futura le cambia, questi test lo dicono invece di lasciare l'analisi scaduta in silenzio.

La #319 resta **aperta**: il difetto visivo non è stato risolto, e le ipotesi escluse sono
elencate lì.
"""
from __future__ import annotations

import ast
import pathlib

from xtrader_bridge import ui_cards

import license_manager as _license_manager_pkg

PKG = pathlib.Path(ui_cards.__file__).parent
# Anche l'app License Manager (separata) ha GUI scrollabili: la guardia copre entrambe.
# I path vengono dai moduli IMPORTATI, non da posizioni relative (Sourcery #242).
PACKAGES = (PKG, pathlib.Path(_license_manager_pkg.__file__).parent)


def test_nessuno_sovrascrive_gli_increment_di_customtkinter():
    """Guardia INVERSA di quella storica: nessun modulo deve toccare
    `xscrollincrement`/`yscrollincrement`.

    Prima si pretendeva che ogni `CTkScrollableFrame` passasse da `tune_scrolling`; ora si
    pretende il contrario, perché quell'accordatura è risultata inerte su Windows (riscriveva
    il default di CTk) e **dannosa** altrove (3px invece di 30 su Linux).

    Fail-first verificato: prima della rimozione questo test trovava 17 chiamate a
    `tune_scrolling` e la `configure(...)` dentro `ui_cards`, e falliva.
    """
    colpevoli = []
    for pkg in PACKAGES:
        for path in sorted(pkg.rglob("*.py")):
            testo = path.read_text(encoding="utf-8")
            for i, riga in enumerate(testo.splitlines(), start=1):
                if "scrollincrement" in riga:
                    colpevoli.append(f"{path.name}:{i}: {riga.strip()}")
                if "tune_scrolling" in riga:
                    colpevoli.append(f"{path.name}:{i}: chiamata a tune_scrolling (rimossa)")
    assert colpevoli == [], (
        "gli increment di scorrimento sono di nuovo sovrascritti:\n" + "\n".join(colpevoli)
        + "\n\nRimuovere l'override, oppure — se serve davvero — dichiarare nel PR perché "
          "il default per-piattaforma di CustomTkinter non va bene, con una misura a supporto.")


def test_customtkinter_imposta_gia_gli_increment_per_piattaforma():
    """L'assunzione che ha reso INERTE l'accordatura, resa eseguibile.

    `tune_scrolling(1)` su Windows scriveva `1` — lo stesso valore che CTk scrive da sé in
    `_set_scroll_increments()`. È il motivo per cui la build di misura della #319 non
    misurava niente: era CustomTkinter stock.

    Se una versione futura togliesse questi default (o li cambiasse), l'analisi della #319 e
    la motivazione della rimozione andrebbero rifatte — meglio saperlo da un test rosso che
    scoprirlo dal comportamento.
    """
    import customtkinter
    from customtkinter.windows.widgets import ctk_scrollable_frame

    src = pathlib.Path(ctk_scrollable_frame.__file__).read_text(encoding="utf-8")
    inizio = src.index("def _set_scroll_increments")
    corpo = src[inizio:inizio + 500]

    for atteso in ("xscrollincrement=1, yscrollincrement=1",          # Windows
                   "xscrollincrement=4, yscrollincrement=8",          # macOS
                   "xscrollincrement=30, yscrollincrement=30"):       # Linux e altri
        assert atteso in corpo, (
            f"CustomTkinter {customtkinter.__version__} non imposta più «{atteso}» in "
            "`_set_scroll_increments`: rivedere la #319 e la motivazione della rimozione "
            "di `tune_scrolling`")


def test_customtkinter_scrolla_VENTI_unita_per_scatto_e_non_e_configurabile():
    """La scoperta della Phase 0 #319, resa eseguibile invece che lasciata in un commento.

    Su Windows CTk chiede `-int(event.delta / 6)` unità di scorrimento per scatto: con il
    `delta` di Windows (±120) fa **20 unità**, cablate nel suo sorgente.

    ⚠️ Questo test prova **il divisore, non i ridisegni** (rilievo CodeRabbit sulla #320,
    fondato): `_mouse_wheel_all` emette UN solo comando `yview("scroll", N, "units")` e Tk
    accorpa i ridisegni a idle. «Venti unità» è il numero richiesto, non un conteggio di
    disegni — dedurlo sarebbe un'inferenza travestita da dato.

    Il test legge il sorgente di CTk installato: se una versione futura cambiasse quel
    divisore, la premessa della #319 cadrebbe e andrebbe rifatta l'analisi invece di
    ereditarla. È esattamente il tipo di assunzione di terze parti che rompe in silenzio.
    """
    import customtkinter
    from customtkinter.windows.widgets import ctk_scrollable_frame

    src = pathlib.Path(ctk_scrollable_frame.__file__).read_text(encoding="utf-8")
    assert "event.delta / 6" in src, (
        f"CustomTkinter {customtkinter.__version__} non divide più il delta per 6: il conto "
        "«20 unità per scatto» su cui poggia la #319 non vale più, rifare la misura")

    # CTk tocca gli increment una volta sola, nell'__init__. Il conteggio resta presidiato
    # perché documenta il ciclo di vita su cui poggiava (e poggerebbe di nuovo) qualunque
    # accordatura post-costruzione: se `_set_scroll_increments` venisse richiamata a runtime,
    # un eventuale override futuro sparirebbe senza che nessuno se ne accorga.
    assert src.count("self._set_scroll_increments()") == 1, (
        "CustomTkinter ora chiama `_set_scroll_increments` più di una volta: se un domani si "
        "reintroducesse un override degli increment, verrebbe sovrascritto a runtime")


def test_customtkinter_isola_le_scrollable_ANNIDATE():
    """La scheda Parser è l'unica con scrollable annidate (`_profiles_box` e
    `_market_profiles_box`, orizzontali, dentro `outer` verticale), ed era una delle
    ipotesi sulla causa della #319: una rotellina che sposta due viste.

    **Smentita, e qui pinnata**: `_check_if_valid_scroll` risale la catena dei master e
    incontra la scrollable INTERNA prima di quella esterna, applicando il ramo
    `widget._parent_canvas == self._parent_canvas` → `False` per l'esterna. Misurato sotto
    Xvfb su una struttura equivalente.

    Se una versione futura di CTk togliesse quel ramo, l'annidamento tornerebbe a scorrere
    doppio e questa esclusione della #319 andrebbe rifatta.
    """
    from customtkinter.windows.widgets import ctk_scrollable_frame

    src = pathlib.Path(ctk_scrollable_frame.__file__).read_text(encoding="utf-8")
    inizio = src.index("def _check_if_valid_scroll")
    corpo = src[inizio:inizio + 500]
    assert "isinstance(widget, CTkScrollableFrame)" in corpo, (
        "`_check_if_valid_scroll` non riconosce più le scrollable annidate: l'esclusione "
        "dell'ipotesi «annidamento» nella #319 va rifatta")
    assert "widget._parent_canvas == self._parent_canvas" in corpo, (
        "`_check_if_valid_scroll` non confronta più il canvas della scrollable annidata: "
        "una rotellina potrebbe tornare a spostare DUE viste")


def test_la_scansione_copre_anche_i_sottopackage():
    """Rilievo CodeRabbit #241, ancora valido per la guardia inversa: `glob` vedeva solo i
    figli diretti — un override reintrodotto in un sottopackage (es. `betfair/`) sfuggirebbe.
    Il contratto è ricorsivo."""
    annidati = [p for p in PKG.rglob("*.py") if p.parent != PKG]
    assert annidati, "il package ha sottomoduli: se spariscono, rivedere la guardia"
    assert set(PKG.rglob("*.py")) >= set(annidati)


def test_ui_cards_non_espone_piu_tune_scrolling():
    """La funzione è stata rimossa, non solo svuotata: chi la cercasse deve trovare un
    `AttributeError` esplicito, non un no-op silenzioso che sembra configurare qualcosa."""
    assert not hasattr(ui_cards, "tune_scrolling"), (
        "`tune_scrolling` è tornata in `ui_cards`: era inerte su Windows e dannosa altrove "
        "(vedi il docstring di questo modulo e la #319)")
    # Il modulo resta quello della composizione a card: le altre funzioni non si toccano.
    for superstite in ("card_style", "card", "badge", "hint", "collapse_when_empty"):
        assert hasattr(ui_cards, superstite), f"`{superstite}` non deve sparire con la rimozione"


def _nome_target(nodo) -> str | None:
    """Rappresentazione testuale del bersaglio: `x` o `self._x` (altro → None)."""
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        return f"{nodo.value.id}.{nodo.attr}"
    return None


def _scrollable_costruite(src: str) -> list[str]:
    """Le variabili a cui è assegnata una `ctk.CTkScrollableFrame(...)`, per censimento.

    Non serve più a pretendere un'accordatura (non c'è più): serve a documentare quante e
    quali sono, così una PR che ne aggiunge una in un punto inatteso resta visibile.
    """
    tree = ast.parse(src)
    costruite: list[str] = []
    for nodo in ast.walk(tree):
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call):
            f = nodo.value.func
            if isinstance(f, ast.Attribute) and f.attr == "CTkScrollableFrame":
                for t in nodo.targets:
                    nome = _nome_target(t)
                    if nome:
                        costruite.append(nome)
    return costruite


def test_censimento_scrollable_il_parser_e_l_unico_con_annidamento():
    """Censimento, non divieto: il Parser è l'unica scheda con più scrollable nello stesso
    file, ed è l'unica in cui il proprietario ha osservato la scia (#319). Il legame non è
    dimostrato — l'ipotesi annidamento è stata smentita — ma la coincidenza è il solo indizio
    rimasto, e va tenuta visibile finché la #319 è aperta."""
    per_file = {}
    for pkg in PACKAGES:
        for path in sorted(pkg.rglob("*.py")):
            trovate = _scrollable_costruite(path.read_text(encoding="utf-8"))
            if trovate:
                per_file[path.name] = trovate
    assert "custom_parser_gui.py" in per_file, "il Parser non costruisce più scrollable?"
    assert len(per_file["custom_parser_gui.py"]) >= 3, (
        "il Parser aveva 4 scrollable (outer + lista salvati + 2 box profili orizzontali): "
        f"ora {per_file['custom_parser_gui.py']}. Se sono state ridotte, aggiornare la #319: "
        "l'unico indizio rimasto è che la scia si vede SOLO in questa scheda.")
