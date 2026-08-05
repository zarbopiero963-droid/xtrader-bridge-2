"""#269 — i quattro punti dell'interfaccia rimasti in italiano in EN/ES.

L'epica multilingua #3 dà la slice «UI localizzata» per completata, ma quattro punti restavano
in italiano anche scegliendo *English* o *Español* all'avvio. Emersero generando gli screenshot
dell'app per il sito, e nessuno dei quattro era nell'elenco di ciò che resta italiano **per
contratto** (messaggi di dominio di `config_store`, errori di validazione, log `_dbg`, il dialog
«già in esecuzione» che renderizza prima di `set_language`). Erano lacune vere.

Il più grave è il **selettore Modalità bridge**: è il controllo che decide se il CSV operativo
viene scritto, e un utente inglese o spagnolo leggeva tre voci in una lingua che non conosce
proprio nel punto in cui sceglie fra «non scrivo niente», «scrivo col software in simulazione» e
«scommesse vere».

**Perché la correzione ingenua è peggio del difetto.** L'etichetta della tendina non è solo
display: la GUI salva nel form la stringa **visualizzata** e `mode_for_form_value` la riconverte
nella modalità canonica. Tradurre la sola resa fa restituire `None` — fail-closed, il chiamante
non applica nulla e mai indovina — ma in EN/ES l'utente **non potrebbe più cambiare modalità**.
Perciò qui si testa la coppia: la resa tradotta *e* il consumatore che deve continuare a
riconoscerla.
"""

import pytest

from xtrader_bridge import bridge_mode, health_check, i18n, multi_signal


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")     # stato di modulo: mai leak verso altri test


#: Le stringhe che NON devono più comparire quando la lingua è EN o ES. Verbatim dal sorgente.
FRAMMENTI_ITALIANI = (
    "Righe attive",
    "Simulazione Bridge",
    "Collaudo XTrader",
    "scommesse vere",
    "Ultimo messaggio",
    "Parser Personalizzato",
    "CSV scrivibile",
    "Conferme XTrader",
    "Ultimo segnale",
    "premi AVVIA per ascoltare",
    "Il bridge ascolterà",
)


# ── ① indicatore «Righe attive» ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_righe_attive_e_tradotto(lingua):
    """È in **header, sempre a schermo**: la prima cosa che un utente EN/ES vedeva in italiano."""
    i18n.set_language(lingua)

    testo = multi_signal.active_count_text(2, 5)

    assert "Righe attive" not in testo, testo
    assert "2" in testo and "5" in testo, f"i numeri devono sopravvivere alla traduzione: {testo}"


def test_269_righe_attive_invariato_in_italiano():
    """In IT `tr` è identità: il testo storico non deve cambiare di una virgola."""
    i18n.set_language("IT")

    assert multi_signal.active_count_text(2, 5) == "Righe attive: 2/5"
    assert multi_signal.active_count_text(3, 0) == "Righe attive: 3"


# ── ② selettore Modalità bridge — il più grave ─────────────────────────────────────────────

@pytest.mark.parametrize("lingua", ["EN", "ES"])
@pytest.mark.parametrize("modo", [bridge_mode.SIMULAZIONE, bridge_mode.COLLAUDO, bridge_mode.REALE])
def test_269_etichette_modalita_tradotte(lingua, modo):
    i18n.set_language(lingua)

    etichetta = i18n.tr(bridge_mode.LABELS[modo])

    assert etichetta != bridge_mode.LABELS[modo], f"{lingua}/{modo}: etichetta non tradotta"
    for frammento in ("Simulazione Bridge", "Collaudo XTrader", "scommesse vere"):
        assert frammento not in etichetta, f"{lingua}/{modo}: resta italiano — {etichetta!r}"


@pytest.mark.parametrize("lingua", ["IT", "EN", "ES"])
@pytest.mark.parametrize("modo", [bridge_mode.SIMULAZIONE, bridge_mode.COLLAUDO, bridge_mode.REALE])
def test_269_l_etichetta_TRADOTTA_resta_riconoscibile(lingua, modo):
    """**Il test che conta.** La GUI salva nel form l'etichetta *visualizzata*; se
    `mode_for_form_value` non la riconosce, l'utente EN/ES non può più cambiare modalità — e
    la modalità è ciò che decide se il CSV operativo viene scritto.

    Senza questo test, la traduzione delle etichette sarebbe una regressione mascherata da
    miglioramento: fail-closed (nessuna modalità applicata invece di una sbagliata), ma il
    controllo diventerebbe inservibile in due lingue su tre.
    """
    i18n.set_language(lingua)

    visualizzata = i18n.tr(bridge_mode.LABELS[modo])

    assert bridge_mode.mode_for_form_value(visualizzata) == modo, (
        f"{lingua}: l'etichetta mostrata all'utente ({visualizzata!r}) non viene riconosciuta → "
        "il selettore Modalità è rotto in questa lingua.")


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_il_nome_canonico_e_l_italiano_restano_validi(lingua):
    """Contro-guardia: un `config.json` salvato in un'altra lingua, o col nome canonico, deve
    continuare a caricarsi. La traduzione **aggiunge** una forma riconosciuta, non ne toglie."""
    i18n.set_language(lingua)

    for modo in (bridge_mode.SIMULAZIONE, bridge_mode.COLLAUDO, bridge_mode.REALE):
        assert bridge_mode.mode_for_form_value(modo) == modo                    # nome canonico
        assert bridge_mode.mode_for_form_value(bridge_mode.LABELS[modo]) == modo  # etichetta IT


@pytest.mark.parametrize("lingua", ["IT", "EN", "ES"])
def test_269_una_stringa_sconosciuta_resta_None(lingua):
    """L'invariante fail-closed del docstring — «sconosciuto → None, mai indovinare una
    modalità» — non deve essere allentata dall'aggiunta delle traduzioni."""
    i18n.set_language(lingua)

    assert bridge_mode.mode_for_form_value("qualunque cosa") is None
    assert bridge_mode.mode_for_form_value("") is None
    assert bridge_mode.mode_for_form_value(None) is None


# ── ③ i sette semafori del pannello Salute ─────────────────────────────────────────────────

def _semafori(**kw):
    """Nomi dei parametri presi **verbatim** dalla firma reale di `build_semaphores`.

    La prima stesura usava `listener_state`/`confirmations` e il test moriva con `TypeError` —
    cioè un fake infedele al contratto vero, la stessa classe di difetto della R1 della #211.
    Vale la pena averlo scritto qui: un helper di test che non combacia con la firma reale
    fallisce per la ragione sbagliata, e maschera se il comportamento sia giusto o no.
    """
    base = dict(listener_status=health_check.LISTENER_OFFLINE, last_message="", last_signal="",
                last_error="", parser_active=True, csv_state=health_check.GREEN,
                csv_detail="ok", last_confirmation="", confirmations_enabled=False,
                mode=bridge_mode.SIMULAZIONE)
    base.update(kw)
    return health_check.build_semaphores(**base)


def test_269_build_semaphores_resta_CANONICO():
    """`build_semaphores` è la funzione **pura** su cui girano le decisioni e i test esistenti:
    non deve tradurre nulla. La localizzazione è un passo separato di presentazione — così le
    chiavi (`message`, `csv`, …) restano identificatori stabili, come chiede la #269."""
    i18n.set_language("EN")

    items = _semafori()

    etichette = {i.label for i in items}
    assert "Ultimo messaggio" in etichette, "build_semaphores deve restare in italiano canonico"


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_i_semafori_localizzati_non_hanno_italiano(lingua):
    i18n.set_language(lingua)

    resi = [health_check.localized(i) for i in _semafori()]

    for item in resi:
        testo = f"{item.label}: {item.detail}"
        for frammento in FRAMMENTI_ITALIANI:
            assert frammento not in testo, f"{lingua}: semaforo {item.key!r} resta italiano — {testo!r}"


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_localized_non_cambia_chiave_ne_stato(lingua):
    """La localizzazione tocca **solo** ciò che si legge. Se cambiasse `key` o `state`, il
    pannello dipingerebbe il semaforo del colore sbagliato o non lo troverebbe affatto —
    `_refresh_health_inner` cerca le label per `item.key`."""
    i18n.set_language(lingua)

    for originale in _semafori():
        reso = health_check.localized(originale)
        assert reso.key == originale.key
        assert reso.state == originale.state


def test_269_localized_e_identita_in_italiano():
    i18n.set_language("IT")

    for originale in _semafori():
        reso = health_check.localized(originale)
        assert (reso.label, reso.detail) == (originale.label, originale.detail)


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_il_semaforo_offline_e_tradotto(lingua):
    """Lo stato che l'utente vede all'avvio, prima di premere AVVIA: era italiano per tutti."""
    i18n.set_language(lingua)

    telegram = next(i for i in _semafori(listener_status=health_check.LISTENER_OFFLINE)
                    if i.key == "telegram")
    reso = health_check.localized(telegram)

    assert "premi AVVIA per ascoltare" not in reso.detail, reso.detail


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_il_semaforo_modalita_usa_l_etichetta_tradotta(lingua):
    """Il semaforo «Modalità» mostra `bridge_mode.label_for(...)`: tradurre le etichette in un
    punto solo sistema due voci, come annotava la #269."""
    i18n.set_language(lingua)

    modo = next(i for i in _semafori(mode=bridge_mode.REALE) if i.key == "mode")
    reso = health_check.localized(modo)

    assert "scommesse vere" not in reso.detail, reso.detail


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_un_dettaglio_dinamico_sopravvive(lingua):
    """I dettagli non sono tutti catalogabili: `csv_detail` e l'ultimo messaggio arrivano dal
    runtime. `tr()` è fail-safe e li restituisce tali e quali — non devono sparire né esplodere."""
    i18n.set_language(lingua)

    items = _semafori(last_message="Juventus v Milan 1.85", csv_detail="D:\\percorso\\segnali.csv")
    resi = {i.key: health_check.localized(i) for i in items}

    assert "Juventus v Milan 1.85" in resi["message"].detail
    assert "D:\\percorso\\segnali.csv" in resi["csv"].detail


# ── la parola di conferma REALE non si traduce, per contratto ──────────────────────────────

@pytest.mark.parametrize("lingua", ["IT", "EN", "ES"])
def test_269_la_frase_di_conferma_REALE_e_mostrata_NON_tradotta(lingua):
    """Invariante di sicurezza, non cosmesi — e il confine più facile da superare per
    distrazione mentre si traducono le etichette accanto.

    Questa PR traduce le **etichette** che spiegano cosa fa ciascuna modalità, REALE inclusa.
    La **frase da digitare** per attivarla è un'altra cosa: `confirmation_ok` la confronta
    verbatim, quindi se il dialog mostrasse la parola tradotta l'utente EN/ES digiterebbe
    quello che legge e la conferma **fallirebbe** — oppure, peggio, qualcuno «aggiusterebbe»
    il gate accettando entrambe, allargando la superficie del gesto più pericoloso dell'app.

    Attenzione a cosa NON si può asserire: la stringa «REALE» **è** legittimamente a catalogo
    (`app.py:874`, l'indicatore che mostra la modalità corrente, dove va tradotta). L'invariante
    non è «REALE non sta nel catalogo», è «il dialog di conferma la interpola grezza» — ed è
    esattamente ciò che si riproduce qui, con lo stesso template del sorgente.
    """
    from xtrader_bridge import real_mode

    i18n.set_language(lingua)

    testo = i18n.tr("ATTENZIONE: stai per attivare la MODALITÀ REALE.\n"
                    "XTrader potrà piazzare scommesse REALI.\n\n"
                    "Per confermare digita:  {phrase}").format(phrase=real_mode.CONFIRM_PHRASE)

    assert real_mode.CONFIRM_PHRASE in testo, (
        f"{lingua}: il dialog non mostra la frase grezza — l'utente digiterebbe una parola "
        f"che il gate rifiuta: {testo!r}")
    assert real_mode.confirmation_ok(real_mode.CONFIRM_PHRASE) is True


# ── i due bloccanti trovati da Claude Fable 5 sulla PR #281 ────────────────────────────────

@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_build_semaphores_e_canonico_anche_nei_DETTAGLI(lingua):
    """Bloccante ② di Fable, ed era un difetto vero introdotto da questa PR.

    La prima stesura chiamava `i18n.tr` **dentro** `build_semaphores` per il solo dettaglio
    interpolato «ultimo errore: {err}» — contraddicendo la canonicità che il docstring della
    funzione dichiara, e producendo una **doppia traduzione** quando `localized` ci ripassa
    sopra. Non era visibile all'utente (la seconda `tr` non trova la chiave e restituisce
    l'input), ma rompeva il contratto su cui si appoggiano i test esistenti e l'assistente,
    che legge lo stato canonico via `explain_health`.

    Il mio `test_269_build_semaphores_resta_CANONICO` non l'ha visto perché guardava **solo le
    etichette**. Questo guarda i dettagli — che è dove il difetto stava.
    """
    i18n.set_language(lingua)

    segnale = next(i for i in _semafori(last_error="boom", last_signal="") if i.key == "signal")

    assert segnale.detail == "nessun segnale; ultimo errore: boom", (
        f"build_semaphores deve restare canonico: {segnale.detail!r}")


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_269_il_dettaglio_interpolato_e_tradotto_alla_presentazione(lingua):
    """...e la traduzione deve comunque avvenire, ma nel posto giusto: `localized`."""
    i18n.set_language(lingua)

    segnale = next(i for i in _semafori(last_error="boom", last_signal="") if i.key == "signal")
    reso = health_check.localized(segnale)

    assert "nessun segnale" not in reso.detail, reso.detail
    assert "boom" in reso.detail, f"il testo dell'errore runtime deve sopravvivere: {reso.detail!r}"


@pytest.mark.parametrize("lingua_scelta", ["IT", "EN", "ES"])
@pytest.mark.parametrize("lingua_etichetta", ["IT", "EN", "ES"])
def test_269_l_etichetta_di_QUALUNQUE_lingua_e_riconosciuta(lingua_scelta, lingua_etichetta):
    """Bloccante ① di Fable. Il rischio che nomina — una modalità salvata e persa in silenzio —
    **non si realizza** per come sta il codice oggi: `settings_controller` scrive a disco il
    **nome canonico** (`REALE`), non l'etichetta, quindi la stringa tradotta non arriva mai al
    `config.json`. L'ho misurato prima di rispondere.

    Ma la correzione che propone è comunque migliore, e gratuita: confrontare le etichette di
    **tutte** le lingue invece che della sola lingua attiva rende `mode_for_form_value`
    **indipendente dallo stato globale** di `i18n`. Una funzione di riconoscimento che dà
    risultati diversi a seconda di quando la chiami è una trappola anche se oggi nessuno ci
    cade — e questo è il controllo che decide se il CSV operativo viene scritto.
    """
    i18n.set_language(lingua_etichetta)
    etichetta = i18n.tr(bridge_mode.LABELS[bridge_mode.REALE])

    i18n.set_language(lingua_scelta)

    assert bridge_mode.mode_for_form_value(etichetta) == bridge_mode.REALE, (
        f"etichetta scritta in {lingua_etichetta}, letta con lingua {lingua_scelta}: "
        f"{etichetta!r} non riconosciuta")


# ── rilievi non bloccanti di GPT-5.5 e Fable sul secondo push ──────────────────────────────

def test_269_nessuna_COLLISIONE_fra_etichette_tradotte():
    """Rilievo GPT-5.5. `mode_for_form_value` confronta le etichette di tutte le lingue e
    **vince il primo match** in `LABELS`: se due modi avessero la stessa etichetta in qualche
    lingua, uno dei due diventerebbe irraggiungibile — su un selettore che decide se il CSV
    operativo viene scritto.

    Oggi non succede (9 etichette distinte su 3 modi × 3 lingue). Questo test lo blocca per il
    futuro, che è il punto: la collisione la introdurrebbe un traduttore, non un programmatore,
    e nessun'altra guardia la vedrebbe.
    """
    import collections

    per_etichetta = collections.defaultdict(set)
    for lingua in i18n.LANGUAGES:
        for modo, etichetta in bridge_mode.LABELS.items():
            per_etichetta[i18n.tr_in(lingua, etichetta)].add(modo)

    collisioni = {e: modi for e, modi in per_etichetta.items() if len(modi) > 1}

    assert collisioni == {}, (
        f"etichette che mappano a PIÙ modalità: {collisioni} — una diventerebbe irraggiungibile")


def test_269_una_traduzione_MALFORMATA_non_rompe_il_pannello(monkeypatch):
    """Rilievo Claude Fable 5, e misurato vero: prima della correzione questo sollevava
    `KeyError`.

    `localized` fa `.format(err=…)` su una stringa che viene dal **catalogo**. Una traduzione
    con una graffa sbagliata — `{sbagliato}` invece di `{err}`, o una graffa non chiusa — è un
    errore di battitura plausibile, e faceva esplodere la funzione. Il pannello 🚦 Salute si
    dichiara **diagnostica best-effort**: un refuso in una traduzione non deve poterlo
    spegnere. Ora il template rotto degrada al testo canonico invece di sollevare.
    """
    monkeypatch.setitem(i18n._CATALOG["EN"], health_check.DETTAGLIO_ERRORE,
                        "no signal; last error: {sbagliato}")
    i18n.set_language("EN")

    item = health_check.HealthItem("signal", "Ultimo segnale", health_check.YELLOW,
                                   health_check.DETTAGLIO_ERRORE.format(err="boom"))

    reso = health_check.localized(item)          # non deve sollevare

    assert "boom" in reso.detail, f"il testo dell'errore non deve sparire: {reso.detail!r}"


def test_269_tr_in_e_fail_safe():
    """`tr_in` è la nuova API pubblica su cui si appoggia il riconoscimento cross-lingua:
    una lingua inesistente o una chiave mai catalogata devono restituire il testo, mai
    sollevare — altrimenti il selettore Modalità si romperebbe invece di rifiutare."""
    assert i18n.tr_in("XX", "qualunque") == "qualunque"      # lingua sconosciuta
    assert i18n.tr_in("EN", "mai catalogata") == "mai catalogata"
    assert i18n.tr_in("IT", "▶  AVVIA") == "▶  AVVIA"        # IT è il riferimento
    assert i18n.tr_in("EN", "") == ""


@pytest.mark.parametrize("template_rotto,errore", [
    ("no signal; last error: {sbagliato}", "KeyError"),
    ("no signal; last error: {err.inesistente}", "AttributeError"),
    ("no signal; last error: {0}", "IndexError"),
    ("no signal; last error: {err!z}", "ValueError"),
])
def test_269_ogni_forma_di_template_rotto_degrada(template_rotto, errore, monkeypatch):
    """Rilievo GPT-5.5 sul terzo push, ed era fondato: la prima stesura del fallback copriva
    `KeyError/IndexError/ValueError` ma **non** `AttributeError`, che `str.format` solleva su
    `{err.qualcosa}` — un refuso plausibile quanto gli altri.

    Le quattro forme qui sono state misurate una per una su `str.format`, non indovinate.
    L'`except` resta **stretto e nominato**: quattro eccezioni documentate, non un blind-except.
    """
    monkeypatch.setitem(i18n._CATALOG["EN"], health_check.DETTAGLIO_ERRORE, template_rotto)
    i18n.set_language("EN")

    item = health_check.HealthItem("signal", "Ultimo segnale", health_check.YELLOW,
                                   health_check.DETTAGLIO_ERRORE.format(err="boom"))

    reso = health_check.localized(item)          # nessuna delle quattro deve sfuggire

    assert "boom" in reso.detail, f"{errore}: il testo dell'errore è sparito — {reso.detail!r}"
