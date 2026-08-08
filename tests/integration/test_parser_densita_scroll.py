"""Nessun contenitore scorrevole del pannello Parser deve tornare a reggere l'app intera.

Contesto (#319 + #321). Il proprietario ha filmato su Windows una **scia di ridisegno**
scorrendo la scheda 🧩 Parser: copie del contenuto sfalsate di pochi pixel, che spariscono
appena lo scorrimento si ferma. Solo lì, mai altrove nell'app.

Misurato su CustomTkinter reale, il perché è quantitativo:

===========================  ======  ==================================
contenitore                  widget  esito osservato su Windows
===========================  ======  ==================================
Parser, editor unico            467   smera
License Manager, il maggiore     61   pulito
ogni altra scheda dell'hub      ≤ 5   pulite
===========================  ======  ==================================

Su Windows Tk crea una finestra di sistema per **ogni** widget: scorrere un canvas con 467
figli significa chiedere al sistema di spostarli e ridipingerli tutti in un colpo. Da qui la
divisione in sotto-schede, che porta il contenitore più affollato a ~280.

⚠️ **Questo test non dimostra che la #319 sia risolta, e non va letto così.** La soglia non
viene da una misura del difetto — quella si può fare solo sul PC del proprietario — ma dalla
distanza fra i due estremi noti. Serve a impedire la **regressione strutturale**: che un
domani si torni a impilare tutto in un unico scorrimento, che è la condizione in cui il
difetto è stato osservato.

Gira dove c'è un display (Xvfb in sviluppo, runner Windows in CI): conta widget veri, non
modellati. Su Windows non degrada in skip, per la stessa ragione di
`test_gen_layout_reale.py`: è la piattaforma bersaglio.
"""

import os
import tkinter

import pytest

_TETTO_WIDGET = 320
"""Massimo di widget in UN contenitore scorrevole del pannello.

Scelto fra i due estremi misurati (61 pulito · 467 smera) e sopra il valore attuale della
griglia regole (~280), che è irriducibile senza costruire solo le righe visibili — lavoro
dichiarato e non fatto. Non è una soglia fisica: è un tetto che rende **rossa** la
ricomparsa del contenitore-monstre invece di lasciarla passare inosservata."""

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.name == "nt"),
    reason="serve un display reale: senza, Tk non costruisce widget da contare",
)


def _conta(widget) -> int:
    """Widget nell'albero che parte da `widget`, incluso lui."""
    totale, pila = 0, [widget]
    while pila:
        nodo = pila.pop()
        totale += 1
        try:
            pila.extend(nodo.winfo_children())
        except tkinter.TclError:                   # widget in teardown: non è un figlio in meno che invalida la misura
            pass
    return totale


@pytest.fixture
def pannello():
    """Il pannello Parser REALE, costruito con CustomTkinter vero."""
    ctk = pytest.importorskip("customtkinter")
    from xtrader_bridge.custom_parser_gui import CustomParserPanel
    from xtrader_bridge.parser_builder import ParserBuilder

    try:
        root = ctk.CTk()
    except tkinter.TclError as exc:                # pragma: no cover - display dichiarato ma inservibile
        if os.name == "nt":
            pytest.fail(
                f"Tk non inizializzabile su Windows: {exc}. È la piattaforma dove il "
                "difetto è stato osservato: qui il guard non deve degradare in skip."
            )
        pytest.skip(f"Tk non inizializzabile: {exc}")

    try:
        root.geometry("1140x720")
        pan = CustomParserPanel(root, builder=ParserBuilder())
        pan.pack(fill="both", expand=True)
        root.update()
        root.update_idletasks()
        yield pan
    finally:
        try:
            root.destroy()
        except tkinter.TclError:                   # pragma: no cover - root già distrutta
            pass


def _scorrevoli(pannello):
    """`[(widget_contenuti, contenitore)]` di ogni CTkScrollableFrame del pannello."""
    trovati, pila = [], [pannello]
    while pila:
        nodo = pila.pop()
        if type(nodo).__name__ == "CTkScrollableFrame":
            trovati.append((_conta(nodo), nodo))
        try:
            pila.extend(nodo.winfo_children())
        except tkinter.TclError:                   # widget in teardown: la scansione prosegue sugli altri rami
            pass
    return trovati


def test_nessuno_scorrevole_regge_da_solo_tutto_il_pannello(pannello):
    """Il difetto strutturale della #319: tutto l'editor in un unico scorrimento."""
    misure = sorted((n for n, _ in _scorrevoli(pannello)), reverse=True)
    assert misure, "nessun contenitore scorrevole trovato: il pannello non è stato costruito"
    assert misure[0] <= _TETTO_WIDGET, (
        f"un contenitore scorrevole regge {misure[0]} widget (tetto {_TETTO_WIDGET}). "
        f"Distribuzione: {misure}. È la condizione in cui il proprietario ha osservato la "
        "scia di ridisegno su Windows: le sezioni vanno divise fra le sotto-schede, non "
        "impilate in un unico scorrimento"
    )


def test_l_editor_e_diviso_in_sotto_schede(pannello):
    """Inchioda la STRUTTURA, non solo il numero.

    Senza questo, qualcuno potrebbe far scendere il conteggio togliendo funzioni invece che
    dividendole — il test resterebbe verde su un pannello impoverito. Le sotto-schede sono
    la forma che il proprietario ha approvato negli sketch, ed è quella che va difesa."""
    schede = list(getattr(pannello._tabs, "_name_list", []))
    assert len(schede) >= 3, f"attese almeno 3 sotto-schede nell'editor, trovate: {schede}"

    # Almeno tre contenitori scorrevoli NON banali: uno per sotto-scheda di contenuto.
    # I piccoli (lista parser, strisce dei profili) non contano come divisione dell'editor.
    sostanziali = [n for n, _ in _scorrevoli(pannello) if n >= 20]
    assert len(sostanziali) >= 3, (
        f"l'editor non risulta diviso: contenitori scorrevoli sostanziali {sostanziali}. "
        "Le sotto-schede esistono ma il contenuto è tornato in uno solo?"
    )
