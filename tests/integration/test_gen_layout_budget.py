"""Test di regressione del budget di layout della riga CSV Path (#286, CodeRabbit #330).

La finestra ha larghezza **minima** `_WINDOW_WIDTH` (dal collaudo #12 è ridimensionabile:
può solo crescere). La riga CSV Path, alla larghezza minima,
porta DUE pulsanti accanto alla casella (Sfoglia #284 + Crea CSV #286): la somma delle larghezze
(etichetta + casella ristretta + 2 pulsanti) deve stare nella larghezza utile del tab, altrimenti
«📄 Crea CSV» viene tagliato a runtime. Questo test blocca un futuro allargamento che rifarebbe
sforare la riga (fallisce in CI invece di clippare in silenzio). Usa le costanti REALI di `app.py`
(esposte via l'harness headless, che stubba `customtkinter`).
"""

import pytest


def _px(padx):
    """Somma dei due lati di un `padx` `(sinistra, destra)` (o di uno scalare per lato)."""
    return padx[0] + padx[1] if isinstance(padx, tuple) else padx + padx


def _larghezza_pulsanti_riga_csv(m):
    """Px che i due pulsanti aggiungono alla riga OLTRE la colonna condivisa.

    Dipende da DOVE stanno: finché sono celle proprie del grid (colonne 2 e 3) si sommano
    interi alla riga; una volta dentro la cella della colonna 1 insieme alla casella non
    allargano più la riga, perché competono con `_GEN_FIELD_ENTRY_WIDTH` invece di
    aggiungersi. `_CSV_ROW_BTN_IN_FIELD_CELL` dice quale delle due è la struttura corrente —
    e `test_il_flag_di_struttura_non_puo_mentire` verifica che dica il vero."""
    return 0 if m._CSV_ROW_BTN_IN_FIELD_CELL else 2 * m._CSV_ROW_BTN_WIDTH


def _master_dei_widget_della_riga_csv():
    """Nome della variabile passata come *master* a casella e pulsanti della riga CSV Path,
    letto dal SORGENTE di `app.py` con l'AST — non dal flag, non da un commento.

    Returns:
        Dict `{"entry": nome, "📁 Sfoglia…": nome, "📄 Crea CSV": nome}`; una chiave manca
        se quel widget non è stato trovato.
    """
    import ast
    import pathlib

    sorgente = (pathlib.Path(__file__).resolve().parents[2]
                / "xtrader_bridge" / "app.py").read_text(encoding="utf-8")
    trovati = {}

    def _nome_master(chiamata):
        arg = chiamata.args[0] if chiamata.args else None
        return arg.id if isinstance(arg, ast.Name) else None

    def _testo_letterale(chiamata):
        """Il `text=` della chiamata, anche avvolto in `i18n.tr("…")`."""
        for kw in chiamata.keywords:
            if kw.arg != "text":
                continue
            nodo = kw.value
            if isinstance(nodo, ast.Call) and nodo.args:
                nodo = nodo.args[0]
            if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                return nodo.value
        return None

    for nodo in ast.walk(ast.parse(sorgente)):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
            continue
        if nodo.func.attr == "CTkButton":
            testo = _testo_letterale(nodo)
            if testo in ("📁 Sfoglia…", "📄 Crea CSV"):
                trovati[testo] = _nome_master(nodo)
        elif nodo.func.attr == "CTkEntry":
            master = _nome_master(nodo)
            # La sola CTkEntry della scheda Generale: la si riconosce dal master dedicato
            # introdotto per questa riga, o dal contenitore della scheda.
            if master in ("contenitore_campo", "tab_gen"):
                trovati["entry"] = master
    return trovati


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


def test_il_flag_di_struttura_non_puo_mentire(app_mod):
    """`_CSV_ROW_BTN_IN_FIELD_CELL` deve dire la verità sul codice di PRODUZIONE.

    Rilievo convergente di **quattro** reviewer sulla PR #326 (CodeRabbit lo classifica
    Major, e concordano Sourcery, Claude Fable 5 e GPT-5.5), ed è fondato: un flag scritto a
    mano è una copia della struttura, e le copie divergono. Se un domani `_build_ui`
    rimettesse un pulsante in una colonna propria lasciando il flag a `True`, il modello
    offline tornerebbe a calcolare la geometria vecchia — e sarebbe di nuovo verde su un
    pulsante tagliato, esattamente il difetto che questa PR sta correggendo.

    Il guard quindi non chiede al flag: **legge `app.py` con l'AST** e guarda a quale
    contenitore vengono passati casella e pulsanti. Se il codice cambia e il flag no, qui
    diventa rosso — offline, senza display, quindi in ogni job della CI.
    """
    master = _master_dei_widget_della_riga_csv()
    assert set(master) >= {"entry", "📁 Sfoglia…", "📄 Crea CSV"}, (
        f"riga CSV Path non riconosciuta nel sorgente di app.py: trovato {master}. "
        "Se i widget sono stati rinominati va aggiornato questo guard, non rimosso: "
        "senza, il modello offline torna a fidarsi di una costante dichiarativa")

    stessa_cella = master["entry"] == master["📁 Sfoglia…"] == master["📄 Crea CSV"]
    assert stessa_cella == app_mod._CSV_ROW_BTN_IN_FIELD_CELL, (
        f"_CSV_ROW_BTN_IN_FIELD_CELL={app_mod._CSV_ROW_BTN_IN_FIELD_CELL} ma nel sorgente i "
        f"master sono {master}: il flag descrive una struttura che il codice non ha più")


def test_la_cella_del_campo_csv_ci_sta_nella_colonna_condivisa(app_mod):
    """Casella + due pulsanti + i loro `padx` devono stare nella colonna condivisa.

    Rilievo GPT-5.5 sulla PR #326, ed è il pezzo che mancava: gli altri test verificano che
    la riga non sfori la finestra, non che il CONTENUTO della cella stia nella colonna. Senza
    questo, allargare i due pulsanti farebbe crescere la cella oltre i
    `_GEN_FIELD_ENTRY_WIDTH` degli altri campi, la colonna condivisa si allargherebbe per
    contenerla e la riga tornerebbe a sforare — per una strada diversa, ma con lo stesso
    esito a schermo.
    """
    m = app_mod
    if not m._CSV_ROW_BTN_IN_FIELD_CELL:
        pytest.skip("i pulsanti non sono nella cella del campo: vincolo non applicabile")
    dentro_cella = (m._CSV_PATH_ENTRY_WIDTH + 2 * m._CSV_ROW_BTN_WIDTH
                    + _px(m._CSV_BROWSE_PADX) + _px(m._CSV_CREATE_PADX))
    assert dentro_cella <= m._GEN_FIELD_ENTRY_WIDTH, (
        f"la cella del campo CSV misura {dentro_cella}px contro i "
        f"{m._GEN_FIELD_ENTRY_WIDTH}px degli altri campi: allargherebbe la colonna condivisa "
        "e la riga tornerebbe a sforare la finestra")


def test_csv_path_entry_piu_stretta_dei_campi_normali(app_mod):
    # La casella CSV Path è più stretta perché la sua riga porta i due pulsanti; gli altri
    # campi (senza pulsanti) restano alla larghezza piena.
    m = app_mod
    assert m._CSV_PATH_ENTRY_WIDTH < m._GEN_FIELD_ENTRY_WIDTH
