"""#258 — il semaforo Dizionari nel pannello 🚦 Salute: cablaggio reale.

`tests/unit/test_dictionary_health_258.py` tiene le due regole che decidono il **colore**.
Qui si tiene ciò che sta fra quel calcolo e l'occhio dell'utente, e che il calcolo giusto da
solo non garantisce:

- il semaforo compare davvero fra gli item del pannello, con la chiave che la GUI cerca;
- il calcolo **non** viene rifatto a ogni messaggio (girerebbe sul thread Tk, leggendo i
  parser da disco: la finestra si congelerebbe come faceva la sonda CSV prima della #76);
- «🔄 Aggiorna» — il «Controlla adesso» della issue — ricalcola **davvero**;
- un calcolo che fallisce dà GIALLO che lo dice, mai un verde dedotto da un errore.
"""

from xtrader_bridge import health_check


def _predisponi(a, app_mod):
    a._last_vals = {}
    a._listener_state = app_mod.health_check.LISTENER_OFFLINE


def _orologio_fermo(app_mod, monkeypatch):
    """Tempo congelato: i refresh ravvicinati restano dentro il TTL per costruzione, invece
    che per fortuna. Un test che dipende da quanto è veloce la macchina è un test che un
    giorno diventa rosso senza che nulla sia cambiato."""
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)


def test_258_il_semaforo_dizionari_compare_nel_pannello(make_app, app_mod, monkeypatch):
    """Il calcolo può essere perfetto: se la chiave non è quella che la GUI cerca, la riga
    non compare e l'utente non vede nulla."""
    a = make_app(running=False)
    _predisponi(a, app_mod)
    monkeypatch.setattr(app_mod.dictionary_health, "stato_dizionari",
                        lambda cfg: {"stato": health_check.RED, "titolo": "3 conflitti su profili usati",
                                     "dettagli": ["x"], "nascosti": 0})

    items = app_mod.App._live_health_items(a)

    diz = next((i for i in items if i.key == "dictionary"), None)
    assert diz is not None, f"nessun semaforo Dizionari fra {[i.key for i in items]}"
    assert diz.state == health_check.RED
    assert "3 conflitti su profili usati" in diz.detail


def test_258_il_calcolo_NON_si_rifa_a_ogni_messaggio(make_app, app_mod, monkeypatch):
    """La ragione per cui esiste la cache. `_set_last` → `_refresh_health` gira a ogni
    messaggio ricevuto: senza TTL, ogni messaggio rileggerebbe tutti i parser da disco e
    rieseguirebbe le quattro funzioni di avviso **sul thread Tk**.

    È lo stesso difetto che la #76 ha corretto sulla sonda CSV, e la #257 sul dizionario
    mercati (108 ms → 7,6 ms per messaggio): qui sarebbe tornato dalla porta della diagnostica.
    """
    a = make_app(running=False)
    _predisponi(a, app_mod)
    _orologio_fermo(app_mod, monkeypatch)
    chiamate = []

    def _conta(cfg):
        chiamate.append(1)
        return {"stato": health_check.GREEN, "titolo": "pulito", "dettagli": [], "nascosti": 0}

    monkeypatch.setattr(app_mod.dictionary_health, "stato_dizionari", _conta)

    for _ in range(5):
        app_mod.App._live_health_items(a)

    assert len(chiamate) == 1, f"il calcolo è stato rifatto {len(chiamate)} volte entro il TTL"


def test_258_il_pulsante_aggiorna_ricalcola_DAVVERO(make_app, app_mod, monkeypatch):
    """Contro-guardia della cache: se «🔄 Aggiorna» leggesse anch'esso la cache, il pulsante
    sarebbe decorativo — e un pulsante che sembra fare qualcosa senza farla è peggio della sua
    assenza. È il «Controlla adesso» che la issue chiede: rieseguire il controllo senza
    riavviare l'app."""
    a = make_app(running=False)
    _predisponi(a, app_mod)
    _orologio_fermo(app_mod, monkeypatch)
    chiamate = []
    monkeypatch.setattr(app_mod.dictionary_health, "stato_dizionari",
                        lambda cfg: (chiamate.append(1) or
                                     {"stato": health_check.GREEN, "titolo": "pulito",
                                      "dettagli": [], "nascosti": 0}))

    app_mod.App._live_health_items(a)               # popola la cache
    app_mod.App._live_health_items(a, True)         # force → il pulsante

    assert len(chiamate) == 2, "il pulsante non ha ricalcolato: legge la cache come gli altri"


def test_258_un_calcolo_che_FALLISCE_da_giallo_che_lo_dice(make_app, app_mod, monkeypatch):
    """Il pannello Salute si costruisce all'apertura della finestra. Se il calcolo solleva —
    config manomessa, cartella parser sparita — l'app non deve cadere; ma nemmeno mostrare
    verde, che sarebbe una rassicurazione **dedotta da un errore**.

    Il giallo qui non è un ripiego di comodo: è l'unica affermazione vera disponibile, «non
    lo so», ed è la stessa scelta del ramo `stato non calcolabile`.
    """
    a = make_app(running=False)
    _predisponi(a, app_mod)

    def _esplode(cfg):
        raise RuntimeError("dizionario illeggibile")

    monkeypatch.setattr(app_mod.dictionary_health, "stato_dizionari", _esplode)

    items = app_mod.App._live_health_items(a)       # non deve sollevare

    diz = next(i for i in items if i.key == "dictionary")
    assert diz.state == health_check.YELLOW, diz
    assert "non si sa" in diz.detail or "non calcolabile" in diz.detail, diz.detail


def test_258_senza_stato_calcolato_il_semaforo_NON_compare_verde():
    """Guardia sul contratto della funzione pura, non sulla GUI.

    `dictionary_state=None` significa «non calcolato». Se il default fosse `GREEN`, ogni
    chiamante che si dimentica di passarlo — un test, un futuro pannello, l'assistente —
    vedrebbe una riga «Dizionari: nessun conflitto» prodotta dall'**omissione** invece che
    dai dati. Meglio nessuna riga che una riga che rassicura a vuoto.
    """
    items = health_check.build_semaphores()
    assert not any(i.key == "dictionary" for i in items), \
        "senza stato calcolato il semaforo non deve comparire, tantomeno verde"


def test_258_uno_stato_non_riconosciuto_e_ROSSO_non_verde():
    """Fail-closed come `csv_state`: un valore fuori dai tre ammessi è un difetto di chi
    chiama, e il colore sicuro davanti a un difetto è il rosso — non il verde."""
    items = health_check.build_semaphores(dictionary_state="BOH", dictionary_detail="x")
    diz = next(i for i in items if i.key == "dictionary")
    assert diz.state == health_check.RED


def test_258_il_semaforo_mostra_i_conflitti_non_solo_il_conteggio(make_app, app_mod, monkeypatch):
    """Rilievo CodeRabbit sulla PR #276: `stato_dizionari` cappa i dettagli e riporta i
    nascosti, ma una prima stesura passava al semaforo il **solo titolo** e buttava via
    entrambi.

    L'utente leggeva «3 conflitti su profili usati» senza poter vedere **quali**, e il tetto
    documentato non esisteva nell'interfaccia perché non c'era nulla da cappare. Un conteggio
    senza gli elementi contati chiede di fidarsi invece di far controllare — ed è la ragione
    per cui il log eventi allo START li elenca uno per uno.
    """
    a = make_app(running=False)
    _predisponi(a, app_mod)
    monkeypatch.setattr(app_mod.dictionary_health, "stato_dizionari",
                        lambda cfg: {"stato": health_check.RED,
                                     "titolo": "12 conflitti su profili usati dai tuoi parser",
                                     "dettagli": ["alias «Juve» punta a 2 nomi diversi",
                                                  "frase «over» combacia con 2 mercati"],
                                     "nascosti": 10})

    diz = next(i for i in app_mod.App._live_health_items(a) if i.key == "dictionary")

    assert "12 conflitti" in diz.detail, "il conteggio deve restare"
    assert "alias «Juve»" in diz.detail, "i conflitti vanno MOSTRATI, non solo contati"
    assert "frase «over»" in diz.detail
    assert "altri 10" in diz.detail, "il taglio va dichiarato: un cap muto dice «non ce n'è altri»"


def test_258_senza_dettagli_il_semaforo_resta_una_riga_sola(make_app, app_mod, monkeypatch):
    """Contro-guardia: il caso verde non deve guadagnare righe vuote o un «…e altri 0»."""
    a = make_app(running=False)
    _predisponi(a, app_mod)
    monkeypatch.setattr(app_mod.dictionary_health, "stato_dizionari",
                        lambda cfg: {"stato": health_check.GREEN, "titolo": "nessun conflitto",
                                     "dettagli": [], "nascosti": 0})

    diz = next(i for i in app_mod.App._live_health_items(a) if i.key == "dictionary")

    assert diz.detail == "nessun conflitto", diz.detail


def test_258_un_guasto_nelle_funzioni_di_avviso_da_GIALLO_non_un_verde_parziale(
        make_app, app_mod, monkeypatch):
    """Secondo rilievo CodeRabbit, ed è il più importante dei due.

    `dictionary_health` non cattura più nulla al suo interno: se una delle quattro funzioni di
    avviso solleva, l'errore **sale** al confine unico (`_dizionari_cached`) che mostra il
    giallo «non calcolabile». Prima, tre catture silenziose lo assorbivano e restituivano un
    risultato **parziale** — che con zero conflitti raccolti diventava un VERDE su un calcolo
    incompleto. Il fail-safe di troppo produceva la bugia che il fail-safe doveva impedire.
    """
    from xtrader_bridge import name_mapping_store as nms

    def _esplode(cfg):
        raise TypeError("chiavi di tipo misto")

    monkeypatch.setattr(nms, "ambiguous_alias_warnings", _esplode)
    a = make_app(running=False, config={"name_mappings": {"P": [{"provider": "x",
                                                                 "betfair": "y"}]}})
    _predisponi(a, app_mod)
    monkeypatch.setattr(app_mod.dictionary_health, "profili_usati",
                        lambda *a_, **k: {"nomi": {"P"}, "mercati": set(), "illeggibili": []})

    diz = next(i for i in app_mod.App._live_health_items(a) if i.key == "dictionary")

    assert diz.state == health_check.YELLOW, (
        f"un guasto nel calcolo ha prodotto {diz.state}: un verde su un risultato parziale")
    assert "non si sa" in diz.detail or "non calcolabile" in diz.detail, diz.detail


def test_258_cartella_parser_illeggibile_da_GIALLO_nel_pannello(make_app, app_mod, monkeypatch):
    """L'altra metà del bloccante Fable 5: la catena completa, fino al semaforo.

    Il test unitario prova che `profili_usati` **solleva**; qui si prova che quel sollevare
    diventa il 🟡 promesso dal design handoff, e non un 🟢 «nessun conflitto» dedotto dal fatto
    che, senza profili leggibili, non c'era niente da attribuire.
    """
    from xtrader_bridge import custom_parser as cp

    def _esplode(*a, **k):
        raise OSError("cartella parser illeggibile")

    monkeypatch.setattr(cp, "list_parser_files", _esplode)
    a = make_app(running=False)
    _predisponi(a, app_mod)

    diz = next(i for i in app_mod.App._live_health_items(a) if i.key == "dictionary")

    assert diz.state == health_check.YELLOW, (
        f"cartella parser illeggibile ha prodotto {diz.state}: non si sa quali profili siano "
        "in uso, quindi non si può dire che non ci siano conflitti")
