"""Test di regressione del budget di layout della riga CSV Path (#286, CodeRabbit #330).

La finestra ha larghezza **minima** `_WINDOW_WIDTH` (dal collaudo #12 è ridimensionabile:
può solo crescere). La riga CSV Path, alla larghezza minima,
porta DUE pulsanti accanto alla casella (Sfoglia #284 + Crea CSV #286): la somma delle larghezze
(etichetta + casella ristretta + 2 pulsanti) deve stare nella larghezza utile del tab, altrimenti
«📄 Crea CSV» viene tagliato a runtime. Questo test blocca un futuro allargamento che rifarebbe
sforare la riga (fallisce in CI invece di clippare in silenzio). Usa le costanti REALI di `app.py`
(esposte via l'harness headless, che stubba `customtkinter`).
"""


def _px(padx):
    """Somma dei due lati di un `padx` `(sinistra, destra)` (o di uno scalare per lato)."""
    return padx[0] + padx[1] if isinstance(padx, tuple) else padx + padx


def _larghezza_pulsanti_riga_csv(m):
    """Px che i due pulsanti aggiungono alla riga OLTRE la colonna condivisa.

    Dipende da DOVE stanno: finché sono celle proprie del grid (colonne 2 e 3) si sommano
    interi alla riga; una volta dentro la cella della colonna 1 insieme alla casella non
    allargano più la riga, perché competono con `_GEN_FIELD_ENTRY_WIDTH` invece di
    aggiungersi. `_CSV_ROW_BTN_IN_FIELD_CELL` dice quale delle due è la struttura corrente."""
    if getattr(m, "_CSV_ROW_BTN_IN_FIELD_CELL", False):
        return 0
    return 2 * m._CSV_ROW_BTN_WIDTH


def test_px_helper_tuple_e_scalare():
    # Copre ESPLICITAMENTE entrambi i rami di `_px` (GLM #331): un `padx` tuple somma i due lati,
    # uno scalare (come `_TABVIEW_PADX`) vale per lato → raddoppiato. Senza questo, un errore nel
    # ramo scalare passerebbe inosservato sotto la disuguaglianza larga del budget.
    assert _px((10, 5)) == 15
    assert _px((0, 8)) == 8
    assert _px(15) == 30


def test_riga_csv_path_sta_nella_finestra_fissa(app_mod):
    """La riga CSV Path deve stare nella finestra alla sua larghezza MINIMA.

    ⚠️ **Questo test è nato VACUO e va letto sapendo perché** (#321 A). Fino alla correzione
    sommava `_CSV_PATH_ENTRY_WIDTH` (250) per la colonna 1 — cioè la larghezza *richiesta*
    dalla sola casella CSV. Ma quella colonna è **condivisa** con le altre quattro righe della
    scheda, larghe `_GEN_FIELD_ENTRY_WIDTH` (470), e in un `grid` **la larghezza di una colonna
    è quella del widget più largo che contiene**, non quella del widget della propria riga.

    Il test tornava 590px contro un budget di 651 e restava verde, mentre a schermo la riga
    ne occupava 810: «📁 Sfoglia…» finiva 28px oltre il bordo e «📄 Crea CSV» 134px oltre,
    cioè **invisibile**. Misurato su CustomTkinter reale sotto Xvfb a 720px::

        colonna 0: x=  0  larghezza=155
        colonna 1: x=155  larghezza=478      <- 478, NON 258
        📁 Sfoglia…  finisce a 748   (fuori di  28px)
        📄 Crea CSV  finisce a 854   (fuori di 134px)

    Un guard che somma le larghezze *richieste* non modella il gestore di geometria: modella
    un'app che non esiste. Ora il conto usa il **massimo della colonna**, che è la regola vera.
    """
    m = app_mod
    # Regola del grid: la colonna 1 vale quanto il suo widget più largo. La casella CSV è
    # ristretta, ma le altre quattro righe della stessa colonna no — quindi comanda la loro.
    colonna_condivisa = max(m._CSV_PATH_ENTRY_WIDTH, m._GEN_FIELD_ENTRY_WIDTH)
    content = m._GEN_LABEL_WIDTH + colonna_condivisa + _larghezza_pulsanti_riga_csv(m)
    # Budget = larghezza MINIMA finestra MENO il padding orizzontale ESPLICITO, derivato dalle
    # STESSE costanti che `_build_ui` usa per disegnare (nessun numero magico duplicato → niente
    # drift, GPT-5.5 + GLM 5.2 #330). Il padding INTERNO della tabview (barra schede/bordo
    # contenuto) è margine ulteriore non modellabile offline, quindi la soglia è conservativa.
    tab_padding = _px(m._TABVIEW_PADX)
    row_padding = (_px(m._GEN_LABEL_PADX) + _px(m._GEN_ENTRY_PADX)
                   + _px(m._CSV_BROWSE_PADX) + _px(m._CSV_CREATE_PADX))
    budget = m._WINDOW_WIDTH - tab_padding - row_padding
    assert content <= budget, (
        f"riga CSV Path {content}px oltre il budget {budget}px alla larghezza minima "
        f"({m._WINDOW_WIDTH}px): «Crea CSV» verrebbe tagliato")


def test_csv_path_entry_piu_stretta_dei_campi_normali(app_mod):
    # La casella CSV Path è più stretta perché la sua riga porta i due pulsanti; gli altri
    # campi (senza pulsanti) restano alla larghezza piena.
    m = app_mod
    assert m._CSV_PATH_ENTRY_WIDTH < m._GEN_FIELD_ENTRY_WIDTH
