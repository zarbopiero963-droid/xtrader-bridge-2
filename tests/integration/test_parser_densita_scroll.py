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


def _CTkScrollableFrame():
    """La CLASSE, non il suo nome (rilievo Sourcery #327).

    Confrontare `type(x).__name__` con una stringa manca le sottoclassi e si rompe in
    silenzio se la libreria rinomina: un guard che smette di trovare i contenitori
    scorrevoli diventa verde su un pannello che li ha ancora tutti."""
    import customtkinter

    return customtkinter.CTkScrollableFrame


def _antenati(widget):
    """Catena dei genitori di `widget`, dal più vicino alla radice."""
    catena, nodo = [], widget
    while True:
        try:
            nodo = nodo.master
        except AttributeError:
            break
        if nodo is None:
            break
        catena.append(nodo)
    return catena


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
        if isinstance(nodo, _CTkScrollableFrame()):
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
    # `_tab_names` è il contratto del PANNELLO, non `_tabs._name_list` che è un attributo
    # privato di CustomTkinter: un upgrade della libreria non deve rompere un guard che
    # parla della nostra struttura (rilievo convergente Fable + GPT-5.5 #327).
    schede = list(getattr(pannello, "_tab_names", []))
    # I quattro NOMI attesi, non un conteggio (rilievo CodeRabbit #327: `>= 3` resta verde
    # se una scheda richiesta sparisce). Sui nomi e non su `== 4` perché una divisione
    # FUTURA in cinque schede è un miglioramento, non una regressione: qui si difende che
    # le quattro aree esistano, non che nessuno ne aggiunga.
    attese = {"🧰 Anagrafiche e traduzioni", "⚙️ Output e condizioni",
              "📊 Griglia regole", "🧪 Prova"}
    assert attese <= set(schede), (
        f"sotto-schede mancanti nell'editor: {sorted(attese - set(schede))}. "
        f"Presenti: {schede}")

    # Almeno tre contenitori scorrevoli NON banali: uno per sotto-scheda di contenuto.
    # I piccoli (lista parser, strisce dei profili) non contano come divisione dell'editor.
    sostanziali = [n for n, _ in _scorrevoli(pannello) if n >= 20]
    assert len(sostanziali) >= 3, (
        f"l'editor non risulta diviso: contenitori scorrevoli sostanziali {sostanziali}. "
        "Le sotto-schede esistono ma il contenuto è tornato in uno solo?"
    )


# Etichette dei pulsanti nella lingua GREZZA. Vanno passate da `i18n.tr` prima del
# confronto (bloccante Claude Fable 5 #327): i pulsanti sono costruiti con
# `i18n.tr(...)`, quindi con l'app in inglese o spagnolo il testo a schermo è tradotto e
# un confronto sulle stringhe grezze renderebbe rosso un pannello sano. In italiano `tr`
# è identità, ed è per questo che il difetto non si vedeva qui.
_AZIONI_GREZZE = ("💾 Salva parser", "🧪 Prova messaggio", "📋 Copia diagnostica")


def test_i_pulsanti_azione_restano_FUORI_da_ogni_scorrimento(pannello):
    """L'invariante centrale di questa PR, che nessun altro test difendeva.

    Rilievo Sourcery (#327), fondato: i test sulla densità e sulla struttura non dicono
    nulla su DOVE stanno i quattro pulsanti. «💾 Salva parser» e i comandi di prova servono
    da tutte le sotto-schede, e prima vivevano dentro il contenitore scorrevole: sparivano
    dalla vista proprio mentre si lavorava in fondo alla griglia, cioè quando servono di
    più. Il proprietario ha già perso il lavoro di un parser configurato e collaudato
    perché «Salva» non era dove lo cercava (#182 PR A ⑦).

    Senza questo guard, un refactor futuro potrebbe rimetterli dentro uno scorrimento e
    tutti gli altri test resterebbero verdi.
    """
    from xtrader_bridge import i18n

    ctk_scroll = _CTkScrollableFrame()
    # Nella lingua ATTIVA, qualunque sia: è così che i pulsanti sono stati disegnati.
    attese = {i18n.tr(t): t for t in _AZIONI_GREZZE}
    trovati = {}
    pila = [pannello]
    while pila:
        nodo = pila.pop()
        testo = None
        try:
            testo = nodo.cget("text")
        except (tkinter.TclError, ValueError, AttributeError):
            # widget senza opzione `text` (frame, canvas, textbox): non è un pulsante
            # azione. Le tre eccezioni sono quelle che Tk e CustomTkinter usano per
            # «questa opzione non esiste»; qualunque altra è un difetto e deve emergere.
            pass
        if isinstance(testo, str) and testo in attese:
            trovati[testo] = nodo
        try:
            pila.extend(nodo.winfo_children())
        except tkinter.TclError:                   # widget in teardown
            pass

    mancanti = [t for t in attese if t not in trovati]
    assert not mancanti, (
        f"pulsanti azione non trovati nel pannello: {mancanti}. Se sono stati rinominati "
        "va aggiornato questo guard, non rimosso: difende l'unica cosa che li tiene "
        "raggiungibili da tutte le sotto-schede")

    dentro_scroll = {
        testo: [type(a).__name__ for a in _antenati(w) if isinstance(a, ctk_scroll)]
        for testo, w in trovati.items()
    }
    colpevoli = {t: a for t, a in dentro_scroll.items() if a}
    assert not colpevoli, (
        f"pulsanti azione finiti DENTRO un contenitore scorrevole: {colpevoli}. "
        "Devono stare nella barra fissa: dentro uno scorrimento spariscono dalla vista "
        "proprio quando servono, ed è il difetto che questa struttura ha corretto")


@pytest.mark.parametrize("lingua", ["IT", "EN", "ES"])
def test_il_guard_dei_pulsanti_regge_in_TUTTE_le_lingue(lingua):
    """Il guard sopra non deve dipendere dalla lingua dell'app (bloccante Fable #327).

    I pulsanti sono costruiti con `i18n.tr(...)`: confrontarli con le stringhe grezze
    funziona **solo in italiano**, dove `tr` è l'identità. Con l'app in inglese o spagnolo
    il testo a schermo è tradotto e il confronto grezzo non trova nulla — cioè il guard
    diventerebbe **rosso su un pannello perfettamente sano**, che è il modo in cui un
    controllo si fa disattivare.

    Qui il pannello viene costruito DAVVERO nella lingua sotto esame e ci si esegue sopra
    la stessa ricerca del guard: se il confronto per lingua attiva si rompesse, questo
    diventerebbe rosso. Misurato: in EN «💾 Salva parser» diventa «💾 Save parser».
    """
    ctk = pytest.importorskip("customtkinter")
    from xtrader_bridge import i18n
    from xtrader_bridge.custom_parser_gui import CustomParserPanel
    from xtrader_bridge.parser_builder import ParserBuilder

    precedente = i18n.get_language()
    root = None
    try:
        i18n.set_language(lingua)
        root = ctk.CTk()
        root.geometry("1140x720")
        pan = CustomParserPanel(root, builder=ParserBuilder())
        pan.pack(fill="both", expand=True)
        root.update()
        root.update_idletasks()

        attese = {i18n.tr(t) for t in _AZIONI_GREZZE}
        assert len(attese) == len(_AZIONI_GREZZE), (
            f"in {lingua} due pulsanti diversi hanno la stessa etichetta: {attese}")

        trovati = set()
        pila = [pan]
        while pila:
            nodo = pila.pop()
            try:
                testo = nodo.cget("text")
            except (tkinter.TclError, ValueError, AttributeError):
                testo = None
            if isinstance(testo, str) and testo in attese:
                trovati.add(testo)
            try:
                pila.extend(nodo.winfo_children())
            except tkinter.TclError:
                pass

        assert trovati == attese, (
            f"con l'app in {lingua} il guard non trova i pulsanti azione: "
            f"attesi {sorted(attese)}, trovati {sorted(trovati)}. Il confronto deve usare "
            "la lingua ATTIVA, non le stringhe grezze")
    finally:
        i18n.set_language(precedente)
        if root is not None:
            try:
                root.destroy()
            except tkinter.TclError:               # pragma: no cover - root già distrutta
                pass
