"""Test di regressione del budget di layout della riga CSV Path (#286, CodeRabbit #330).

La finestra ha larghezza **fissa** (`_WINDOW_WIDTH`, `resizable(False, True)`). La riga CSV Path
porta DUE pulsanti accanto alla casella (Sfoglia #284 + Crea CSV #286): la somma delle larghezze
(etichetta + casella ristretta + 2 pulsanti) deve stare nella larghezza utile del tab, altrimenti
«📄 Crea CSV» viene tagliato a runtime. Questo test blocca un futuro allargamento che rifarebbe
sforare la riga (fallisce in CI invece di clippare in silenzio). Usa le costanti REALI di `app.py`
(esposte via l'harness headless, che stubba `customtkinter`).
"""


def _px(padx):
    """Somma dei due lati di un `padx` `(sinistra, destra)` (o di uno scalare per lato)."""
    return padx[0] + padx[1] if isinstance(padx, tuple) else padx + padx


def test_riga_csv_path_sta_nella_finestra_fissa(app_mod):
    m = app_mod
    # Larghezze fisse effettivamente renderizzate nella riga (come in `_build_ui`).
    content = m._GEN_LABEL_WIDTH + m._CSV_PATH_ENTRY_WIDTH + 2 * m._CSV_ROW_BTN_WIDTH
    # Budget = larghezza fissa finestra MENO il padding orizzontale ESPLICITO, derivato dalle
    # STESSE costanti che `_build_ui` usa per disegnare (nessun numero magico duplicato → niente
    # drift, GPT-5.5 + GLM 5.2 #330): la CTkTabview è impaccata a `_TABVIEW_PADX` per lato e i 4
    # widget della riga usano i loro `padx`. Il padding INTERNO della tabview (barra schede/bordo
    # contenuto) è margine ulteriore non modellabile offline, quindi la soglia è conservativa.
    tab_padding = _px(m._TABVIEW_PADX)
    row_padding = (_px(m._GEN_LABEL_PADX) + _px(m._GEN_ENTRY_PADX)
                   + _px(m._CSV_BROWSE_PADX) + _px(m._CSV_CREATE_PADX))
    budget = m._WINDOW_WIDTH - tab_padding - row_padding
    assert content <= budget, (
        f"riga CSV Path {content}px oltre il budget {budget}px della finestra "
        f"({m._WINDOW_WIDTH}px fissa): «Crea CSV» verrebbe tagliato")


def test_csv_path_entry_piu_stretta_dei_campi_normali(app_mod):
    # La casella CSV Path è più stretta perché la sua riga porta i due pulsanti; gli altri
    # campi (senza pulsanti) restano alla larghezza piena.
    m = app_mod
    assert m._CSV_PATH_ENTRY_WIDTH < m._GEN_FIELD_ENTRY_WIDTH
