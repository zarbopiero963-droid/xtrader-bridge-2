"""Test di regressione del budget di layout della riga CSV Path (#286, CodeRabbit #330).

La finestra ha larghezza **fissa** (`_WINDOW_WIDTH`, `resizable(False, True)`). La riga CSV Path
porta DUE pulsanti accanto alla casella (Sfoglia #284 + Crea CSV #286): la somma delle larghezze
(etichetta + casella ristretta + 2 pulsanti) deve stare nella larghezza utile del tab, altrimenti
«📄 Crea CSV» viene tagliato a runtime. Questo test blocca un futuro allargamento che rifarebbe
sforare la riga (fallisce in CI invece di clippare in silenzio). Usa le costanti REALI di `app.py`
(esposte via l'harness headless, che stubba `customtkinter`).
"""


def test_riga_csv_path_sta_nella_finestra_fissa(app_mod):
    m = app_mod
    # Larghezze fisse effettivamente renderizzate nella riga (come in `_build_ui`).
    content = (m._GEN_LABEL_WIDTH + m._CSV_PATH_ENTRY_WIDTH + 2 * m._CSV_ROW_BTN_WIDTH)
    # Margine per il padding orizzontale della riga (padx dei 4 widget) + il padding della
    # CTkTabview impaccata a `padx=15` nella finestra fissa. Conservativo: se `content` sta
    # sotto questa soglia, la riga non taglia «Crea CSV».
    budget = m._WINDOW_WIDTH - 60
    assert content <= budget, (
        f"riga CSV Path {content}px oltre il budget {budget}px della finestra "
        f"({m._WINDOW_WIDTH}px fissa): «Crea CSV» verrebbe tagliato")


def test_csv_path_entry_piu_stretta_dei_campi_normali(app_mod):
    # La casella CSV Path è più stretta perché la sua riga porta i due pulsanti; gli altri
    # campi (senza pulsanti) restano alla larghezza piena.
    m = app_mod
    assert m._CSV_PATH_ENTRY_WIDTH < m._GEN_FIELD_ENTRY_WIDTH
