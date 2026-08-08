"""Layout della scheda «⚙️ Generale» misurato su Tk REALE, non modellato (#321 A).

Perché esiste, accanto a `test_gen_layout_budget.py`: quel test somma le larghezze
*richieste* dai widget, e proprio per questo è rimasto **verde su un difetto visibile a
occhio nudo**. Sommava `_CSV_PATH_ENTRY_WIDTH` (250) per la colonna 1, mentre il gestore di
geometria ne disegnava 478 — perché in un `grid` **la larghezza di una colonna è quella del
widget più largo che contiene**, e quella colonna è condivisa con le altre quattro righe
della scheda, larghe `_GEN_FIELD_ENTRY_WIDTH` (470).

Risultato: «📁 Sfoglia…» finiva 28px oltre il bordo della finestra e «📄 Crea CSV» 134px
oltre — cioè **non esisteva a schermo** alla dimensione con cui il programma si apre. Il
proprietario l'ha segnalato su Windows reale; la misura sotto Xvfb l'ha riprodotto.

Questo modulo non modella niente: costruisce la riga con CustomTkinter vero e **chiede a Tk
dove sono finiti i widget**. Un guard così è indifferente alla struttura — regge sia la
disposizione a quattro colonne sia quella a cella unica, e resta valido se domani cambia
ancora.

Gira dove c'è un display: sotto Xvfb in sviluppo e sui runner **Windows** della CI, che è la
piattaforma bersaglio. Senza display si salta, dichiarandolo.
"""

import os

import pytest

_ROOT_DISPONIBILE = bool(os.environ.get("DISPLAY") or os.name == "nt")

pytestmark = pytest.mark.skipif(
    not _ROOT_DISPONIBILE,
    reason="serve un display reale (Xvfb in sviluppo, runner Windows in CI): "
           "senza, Tk non calcola alcuna geometria e la misura non esisterebbe",
)


@pytest.fixture
def riga_generale():
    """Ricostruisce la riga «📄 CSV Path» della scheda Generale con le costanti REALI di
    `app.py`, dentro una finestra larga esattamente il minimo dichiarato.

    Ricostruita e non importata da `App`: istanziare l'app intera qui trascinerebbe config,
    licenza e listener dentro un test di layout. Le costanti però sono quelle vere, quindi
    un cambio di larghezza in `app.py` si riflette qui senza toccare questo file."""
    import tkinter

    ctk = pytest.importorskip("customtkinter")
    import xtrader_bridge.app as m

    # `TclError` e non `Exception`: l'unico fallimento previsto qui è «il display c'è come
    # variabile d'ambiente ma Tk non riesce ad aprirlo». Qualunque altro errore è un difetto
    # del test o dell'app, e deve emergere invece di travestirsi da skip.
    try:
        root = ctk.CTk()
    except tkinter.TclError as exc:               # pragma: no cover - display dichiarato ma inservibile
        pytest.skip(f"Tk non inizializzabile: {exc}")

    try:
        root.geometry(f"{m._WINDOW_WIDTH}x760")
        tab = ctk.CTkFrame(root)
        tab.pack(fill="both", expand=True, padx=m._TABVIEW_PADX)

        campi = [("🔑 Bot Token", "bot_token"), ("💬 Chat ID", "chat_id"),
                 ("📄 CSV Path", "csv_path"), ("⏱️ Timeout (sec)", "clear_delay"),
                 ("🏷️ Provider", "provider")]
        pulsanti = {}
        for r, (etichetta, key) in enumerate(campi):
            ctk.CTkLabel(tab, text=etichetta, width=m._GEN_LABEL_WIDTH, anchor="w").grid(
                row=r, column=0, padx=m._GEN_LABEL_PADX, pady=4, sticky="w")
            larghezza = (m._CSV_PATH_ENTRY_WIDTH if key == "csv_path"
                         else m._GEN_FIELD_ENTRY_WIDTH)
            if key == "csv_path" and getattr(m, "_CSV_ROW_BTN_IN_FIELD_CELL", False):
                # Struttura a cella unica: casella e pulsanti stanno nella stessa cella.
                cella = ctk.CTkFrame(tab, fg_color="transparent")
                cella.grid(row=r, column=1, padx=m._GEN_ENTRY_PADX, pady=4, sticky="w")
                ctk.CTkEntry(cella, width=larghezza).pack(side="left")
                for testo, padx in (("📁 Sfoglia…", m._CSV_BROWSE_PADX),
                                    ("📄 Crea CSV", m._CSV_CREATE_PADX)):
                    b = ctk.CTkButton(cella, text=testo, width=m._CSV_ROW_BTN_WIDTH)
                    b.pack(side="left", padx=padx)
                    pulsanti[testo] = b
            else:
                ctk.CTkEntry(tab, width=larghezza).grid(
                    row=r, column=1, padx=m._GEN_ENTRY_PADX, pady=4, sticky="w")
                if key == "csv_path":
                    for col, (testo, padx) in enumerate(
                            (("📁 Sfoglia…", m._CSV_BROWSE_PADX),
                             ("📄 Crea CSV", m._CSV_CREATE_PADX)), start=2):
                        b = ctk.CTkButton(tab, text=testo, width=m._CSV_ROW_BTN_WIDTH)
                        b.grid(row=r, column=col, padx=padx, pady=4, sticky="w")
                        pulsanti[testo] = b

        root.update()
        root.update_idletasks()
        yield root, tab, pulsanti, m
    finally:
        try:
            root.destroy()
        except tkinter.TclError:                   # pragma: no cover - root già distrutta dal teardown Tk
            pass


def test_i_due_pulsanti_della_riga_csv_sono_INTERAMENTE_dentro_la_finestra(riga_generale):
    """Il difetto della #321 A, misurato invece che dedotto.

    Non «il conto torna»: **dove finisce il pulsante**. Alla larghezza minima della finestra
    il bordo destro di ciascun pulsante deve stare dentro la finestra, altrimenti l'utente
    non ha modo di premerlo — e «📄 Crea CSV» è la via d'uscita documentata quando il CSV
    esistente non è del bridge (§6.4 del design handoff), non un ornamento."""
    root, _tab, pulsanti, m = riga_generale
    assert pulsanti, "la riga CSV Path non ha prodotto i due pulsanti attesi"

    larghezza_finestra = root.winfo_width()
    origine = root.winfo_rootx()
    fuori = {}
    for testo, b in pulsanti.items():
        fine = (b.winfo_rootx() - origine) + b.winfo_width()
        if fine > larghezza_finestra:
            fuori[testo] = fine - larghezza_finestra

    assert not fuori, (
        f"finestra {larghezza_finestra}px (minimo dichiarato {m._WINDOW_WIDTH}px): "
        + " · ".join(f"«{t}» sborda di {px}px" for t, px in fuori.items())
        + " — alla dimensione con cui il programma si APRE quei controlli non sono premibili"
    )


def test_la_colonna_condivisa_non_e_quella_della_sola_casella_csv(riga_generale):
    """Inchioda la CAUSA, non solo il sintomo (regola 2: la classe, non il sito).

    È il fatto che il test modellato ignorava: la colonna 1 non vale
    `_CSV_PATH_ENTRY_WIDTH`, vale il massimo della colonna. Se un domani qualcuno
    «ottimizzasse» la riga restringendo di nuovo la sola casella CSV credendo di guadagnare
    spazio, questo test dice subito che non ne guadagna nulla."""
    _root, tab, _pulsanti, m = riga_generale
    larghezza_colonna_1 = tab.grid_bbox(column=1, row=2)[2]
    assert larghezza_colonna_1 >= m._GEN_FIELD_ENTRY_WIDTH, (
        f"colonna 1 larga {larghezza_colonna_1}px: attesa almeno "
        f"{m._GEN_FIELD_ENTRY_WIDTH}px (la impongono gli altri campi della stessa colonna)"
    )
