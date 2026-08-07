"""Il tool degli screenshot non deve distruggere la licenza vera di chi lo lancia.

Rilievo **GPT-5.5 sulla PR #310**, e non era teorico: `app_con_licenza_di_prova.py` scriveva la
licenza di TEST dritta in `license_state.json` della cartella dati. Su una macchina con una
licenza reale — quella del proprietario — il token vero spariva, e l'app normale poi rifiutava
quello di prova perché firmato con la chiave di test. Cioè: **scattare uno screenshot
disattivava il programma**, e l'originale non era più recuperabile.

Questi test esercitano le due funzioni reali del tool, non una copia della logica.
"""

import importlib.util
import pathlib
import signal

import pytest

from xtrader_bridge.licensing import license as _lic
from xtrader_bridge.licensing import revocation as _rev

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MODULO = _ROOT / "tools" / "screenshots" / "app_con_licenza_di_prova.py"

# Catturata all'IMPORT del modulo di test, cioè in fase di collection, prima che qualunque test
# giri: è la chiave pubblica **reale** deployata nel prodotto. Serve al canarino in fondo al file.
# Stesso schema già usato da `test_licensing_license.py` e `test_license_status.py`.
_CHIAVE_DEPLOYATA_REALE = _lic.LICENSE_PUBLIC_KEY_HEX

# Stessa idea, altro pezzo di stato condiviso: i gestori di segnale che pytest aveva PRIMA che
# questo file girasse. `_attiva_licenza_di_prova` ne installa di propri, e `monkeypatch` non disfa
# `signal.signal` (rilievo CodeRabbit sulla #310). Serve al secondo canarino in fondo al file.
_GESTORI_ORIGINALI = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}

# Impronta hardware finta, ma nel formato vero (`HW1-` + 16 hex a gruppi di 4), così
# `hwid.is_identifiable` la accetta come accetterebbe quella di una macchina reale.
HARDWARE_FINTO = "HW1-ABCD-1234-EF56-7890"


def _carica():
    """Importa il launcher per percorso: `tools/` non è un pacchetto importabile."""
    spec = importlib.util.spec_from_file_location("app_con_licenza_di_prova", _MODULO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def tool():
    return _carica()


@pytest.fixture(autouse=True)
def _chiave_deployata_ripristinata():
    """Rimette a posto `LICENSE_PUBLIC_KEY_HEX` dopo ogni test di questo file.

    Rilievo **Claude Fable 5** sulla #310, ed è il più grave dei tre: `_attiva_licenza_di_prova`
    **assegna** la chiave pubblica di test ai moduli `licensing.license` e `licensing.revocation`
    — non è un monkeypatch, è una scrittura sul modulo condiviso, e il tool fa bene a farla
    perché deve valere per tutta la vita del processo che scatta. Ma dentro pytest quei moduli
    sono gli stessi che usano **tutti gli altri test della sessione**: senza ripristino, da qui in
    poi ogni verifica di firma Ed25519 girerebbe con la chiave di TEST, e una regressione vera
    sulla verifica passerebbe inosservata.

    **Non** è un doppione della fixture `chiave_pubblica_di_test` di `conftest.py`, che fa la cosa
    opposta: quella *installa* la chiave di test per i test che devono verificare licenze firmate
    col seed di test. Qui non si installa niente — si salva ciò che c'è e lo si rimette, perché il
    valore lo scrive il tool sotto esame. Usare quella renderebbe il canarino in fondo al file
    cieco: vedrebbe la chiave di test messa dalla fixture e non saprebbe distinguerla da quella
    lasciata dal tool.

    Entrambi i moduli, non uno: `revocation.py` fa `from .license import LICENSE_PUBLIC_KEY_HEX`,
    cioè copia il valore all'import, ed è il posto che si dimentica.
    """
    originale_lic = _lic.LICENSE_PUBLIC_KEY_HEX
    originale_rev = _rev.LICENSE_PUBLIC_KEY_HEX
    yield
    _lic.LICENSE_PUBLIC_KEY_HEX = originale_lic
    _rev.LICENSE_PUBLIC_KEY_HEX = originale_rev


@pytest.fixture(autouse=True)
def _gestori_di_segnale_ripristinati():
    """Rimette a posto i gestori di SIGTERM e SIGINT dopo ogni test di questo file.

    Rilievo **CodeRabbit** sulla #310, ed è **la stessa classe** che Fable aveva trovato sulla
    chiave pubblica — sfuggita a me una seconda volta, sull'altro pezzo di stato condiviso.
    I test che eseguono `_attiva_licenza_di_prova` patchano `atexit.register` ma non
    `signal.signal`, quindi il launcher installa gestori **veri** nel processo pytest, e
    `monkeypatch` non li disfa.

    Due conseguenze, entrambe reali: un Ctrl+C in un test successivo finirebbe nel gestore del
    launcher e in `sys.exit(0)` invece che nel percorso di interruzione di pytest; e la chiusura
    trattenuta punta a uno `stato` con una `tmp_path` ormai cancellata.

    Non copre `test_i_gestori_di_segnale_sono_installati_prima_di_toccare_la_licenza`, che
    `signal.signal` se lo patcha da sé e quindi non installa niente per davvero.
    """
    originali = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield
    for numero, gestore in originali.items():
        signal.signal(numero, gestore)


@pytest.fixture
def hardware_finto(tool, monkeypatch):
    """Impronta hardware **deterministica**, per i test che eseguono `_attiva_licenza_di_prova`.

    Rilievo **Claude Fable 5** sulla #310: quella funzione chiama `hwid.hardware_id()` vero e si
    ferma con `SystemExit` se l'hardware non è identificabile (nessun MAC reale, niente registro).
    Su un runner CI è una condizione plausibile — un container senza NIC fisica — e il test
    fallirebbe per una ragione che non c'entra con ciò che verifica. Il ramo fail-closed ha un suo
    test dedicato più sotto, dove è il **soggetto** invece che un presupposto.
    """
    monkeypatch.setattr(tool.hwid, "hardware_id", lambda: HARDWARE_FINTO)
    return HARDWARE_FINTO


def test_una_licenza_esistente_viene_messa_al_riparo_non_persa(tool, tmp_path):
    """Il caso che il rilievo descrive: c'è una licenza vera e il tool sta per sovrascriverla."""
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    backup = tool.preserva_licenza_esistente(percorso)

    assert backup, "nessun backup creato: la licenza vera verrebbe sovrascritta e persa"
    assert pathlib.Path(backup).read_bytes() == originale, \
        "il backup non contiene la licenza originale byte per byte"
    assert not percorso.exists(), \
        "la licenza vera è ancora al suo posto: il tool la sovrascriverebbe invece di spostarla"


def test_il_ripristino_rimette_esattamente_la_licenza_di_prima(tool, tmp_path):
    """Fine della sessione di scatto: quello che si ritrova dev'essere il token ORIGINALE,
    non quello di prova — altrimenti l'app resta disattivata dopo gli screenshot."""
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    backup = tool.preserva_licenza_esistente(percorso)
    # il launcher scrive la sua licenza di prova al posto di quella vera
    percorso.write_text('{"token": "LICENZA-DI-PROVA-FIRMATA-COL-SEED-DI-TEST", "last_seen": 2}',
                        encoding="utf-8")

    tool.ripristina_licenza(backup, percorso, "LICENZA-DI-PROVA-FIRMATA-COL-SEED-DI-TEST")

    assert percorso.read_bytes() == originale, \
        "dopo il ripristino non c'è la licenza vera: l'app resterebbe disattivata"
    assert not pathlib.Path(backup).exists(), \
        "il backup è rimasto sul disco: alla corsa dopo il tool si rifiuterebbe di partire"


def test_senza_licenza_non_crea_nessun_backup(tool, tmp_path):
    """La macchina di documentazione tipica non ha licenza: non deve nascere un file inutile
    che poi bloccherebbe la corsa successiva."""
    percorso = tmp_path / "license_state.json"

    assert tool.preserva_licenza_esistente(percorso) is None
    assert not (tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)).exists()


def test_un_backup_gia_presente_ferma_il_tool_invece_di_sovrascriverlo(tool, tmp_path):
    """Il caso pericoloso di seconda istanza.

    Se una corsa precedente è stata uccisa prima del ripristino, il backup contiene la licenza
    VERA. Ripartire sovrascrivendolo la distruggerebbe — cioè il danno esatto da cui questa
    funzione difende, arrivato per un'altra strada. Deve fermarsi.
    """
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "licenza-di-prova-rimasta", "last_seen": 2}', encoding="utf-8")
    backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
    backup.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                      encoding="utf-8")
    intatto = backup.read_bytes()

    with pytest.raises(SystemExit) as errore:
        tool.preserva_licenza_esistente(percorso)

    assert tool.SUFFISSO_BACKUP in str(errore.value), \
        "il messaggio non dice quale file rimettere a posto: inutile a chi lo legge"
    assert backup.read_bytes() == intatto, \
        "il backup con la licenza VERA è stato sovrascritto: è il danno che il tool deve evitare"


def test_il_percorso_completo_salva_prima_di_scrivere_e_ripristina_dopo(tool, tmp_path,
                                                                       monkeypatch,
                                                                       hardware_finto):
    """Il test che chiude il cerchio: `_attiva_licenza_di_prova` intero, sulla cartella finta.

    Rilievo GPT-5.5 sulla #310: gli altri test coprono le due funzioni helper, ma non che il
    launcher le usi **nell'ordine giusto** — mettere al riparo la licenza vera *prima* di
    scrivere quella di prova. Un ordine invertito passerebbe tutti gli altri test e
    distruggerebbe comunque la licenza.
    """
    from xtrader_bridge import config_store, license_store

    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    percorso = pathlib.Path(license_store.license_state_path(str(tmp_path)))
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    registrati = []
    monkeypatch.setattr(tool.atexit, "register",
                        lambda fn, *a, **k: registrati.append((fn, a, k)))

    tool._attiva_licenza_di_prova()

    assert percorso.read_bytes() != originale, \
        "la licenza di prova non è stata scritta: il test non sta esercitando niente"
    backup = percorso.with_name(percorso.name + tool.SUFFISSO_BACKUP)
    assert backup.read_bytes() == originale, \
        "la licenza VERA non è stata messa al riparo prima di scrivere quella di prova"

    assert registrati, "nessun ripristino registrato: all'uscita la licenza vera non tornerebbe"
    fn, args, _ = registrati[0]
    fn(*args)
    assert percorso.read_bytes() == originale, \
        "dopo il ripristino la licenza vera non è tornata al suo posto"


@pytest.mark.parametrize("precedente, deve_uscire, motivo", [
    ("SIG_DFL", True, "col default nessuno aveva chiesto niente: si esce e `atexit` ripristina"),
    ("SIG_IGN", False,
     "il processo aveva scelto di IGNORARE il segnale: uscire lo contraddirebbe"),
    ("custom", True, "l'handler precedente va richiamato, poi si esce"),
])
def test_il_gestore_di_segnale_conserva_il_comportamento_precedente(tool, monkeypatch,
                                                                   precedente, deve_uscire,
                                                                   motivo):
    """Rilievo GPT-5.5 sulla #310, secondo giro: il codice *diceva* di conservare l'handler
    precedente e su `SIG_IGN` non lo faceva — usciva lo stesso. `main.py` gira nello STESSO
    processo, quindi cambiare la sua semantica di spegnimento è una regressione vera."""
    import signal as _signal

    chiamato = []
    vecchio = {"SIG_DFL": _signal.SIG_DFL, "SIG_IGN": _signal.SIG_IGN,
               "custom": lambda *_a: chiamato.append("precedente")}[precedente]

    installato = {}
    monkeypatch.setattr(tool.signal, "getsignal", lambda _s: vecchio)
    monkeypatch.setattr(tool.signal, "signal",
                        lambda s, fn: installato.__setitem__("fn", fn))

    tool._installa_ripristino_su_segnale(_signal.SIGTERM)
    gestore = installato["fn"]

    if deve_uscire:
        with pytest.raises(SystemExit):
            gestore(_signal.SIGTERM, None)
    else:
        gestore(_signal.SIGTERM, None)   # non deve sollevare: motivo → %s

    if precedente == "custom":
        assert chiamato == ["precedente"], \
            "l'handler precedente non e' stato richiamato: lo spegnimento dell'app cambia"


def test_senza_licenza_preesistente_quella_di_prova_NON_resta_sul_disco(tool, tmp_path,
                                                                       monkeypatch,
                                                                       hardware_finto):
    """Rilievo **Claude Fable 5** sulla #310, e mi era sfuggito.

    Sulla macchina di documentazione tipica — quella **senza** licenza — non c'è niente da
    mettere al riparo, quindi il ramo `backup` non scattava e **nessuna pulizia veniva
    registrata**. Il token di test restava in `license_state.json` per sempre, e l'app di
    produzione lo rifiuta perché firmato con la chiave di test: il computer passava da «non
    attivato» a «licenza non valida: bridge bloccato». Peggio di prima, ed è la stessa classe
    di danno che questo tool esiste per prevenire.
    """
    from xtrader_bridge import config_store, license_store

    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    percorso = pathlib.Path(license_store.license_state_path(str(tmp_path)))
    assert not percorso.exists(), "il test parte da una macchina SENZA licenza"

    registrati = []
    monkeypatch.setattr(tool.atexit, "register",
                        lambda fn, *a, **k: registrati.append((fn, a)))

    tool._attiva_licenza_di_prova()
    assert percorso.exists(), "la licenza di prova non è stata scritta: il test non prova nulla"

    assert registrati, (
        "nessuna pulizia registrata: la licenza di PROVA resterebbe sul disco e l'app di "
        "produzione la rifiuterebbe — da «non attivato» a «licenza non valida»")
    fn, args = registrati[0]
    fn(*args)

    assert not percorso.exists(), \
        "la licenza di prova è ancora sul disco dopo la pulizia"


def test_il_ripristino_non_sovrascrive_una_licenza_vera_attivata_durante_gli_scatti(tool,
                                                                                    tmp_path):
    """Rilievo **Claude Fable 5** sulla #310 — il TERZO della stessa classe in questa PR.

    La protezione «non toccare un token che non è il nostro» c'era in
    `rimuovi_licenza_di_prova` e **non** in `ripristina_licenza`: una gemella difesa e una no.
    Scenario: l'utente ha una licenza vecchia, lancia gli scatti, e **durante** la sessione ne
    attiva una **nuova** nella scheda «🔒 Licenza». All'uscita il ripristino cieco sovrascriveva
    il token appena attivato con quello vecchio — distruggendo l'attivazione.

    Il tool deve **non toccare niente**: meglio due licenze sul disco che una distrutta.
    """
    percorso = tmp_path / "license_state.json"
    backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
    backup.write_text('{"token": "LICENZA-VECCHIA", "last_seen": 1}', encoding="utf-8")
    percorso.write_text('{"token": "LICENZA-NUOVA-ATTIVATA-ADESSO", "last_seen": 9}',
                        encoding="utf-8")
    nuova = percorso.read_bytes()
    vecchia = backup.read_bytes()

    tool.ripristina_licenza(str(backup), percorso, "IL-TOKEN-DI-PROVA-CHE-AVEVAMO-SCRITTO")

    assert percorso.read_bytes() == nuova, \
        "la licenza appena attivata è stata sovrascritta dal backup: attivazione distrutta"
    assert backup.read_bytes() == vecchia, \
        "il backup è stato consumato: la licenza vecchia è persa e la nuova pure a rischio"


def test_se_la_licenza_e_sparita_durante_gli_scatti_il_backup_torna_comunque(tool, tmp_path):
    """Caso limite sollevato da GPT-5.5 sulla #310: e se il file licenza sparisce durante la
    sessione? Il timore era che `_e_ancora_la_nostra` ritornasse `False` e il backup restasse
    orfano, lasciando l'utente senza licenza pur avendone una salvata.

    Non succede, perché la guardia è `esiste() AND non è la nostra`: se il file non c'è non c'è
    niente da proteggere, e il ripristino procede. Questo test lo **fissa**, così la protezione
    aggiunta per un caso non introduce una regressione nell'altro.
    """
    percorso = tmp_path / "license_state.json"
    backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
    backup.write_text('{"token": "LICENZA-VERA", "last_seen": 1}', encoding="utf-8")
    originale = backup.read_bytes()
    assert not percorso.exists(), "il test parte con la licenza SPARITA"

    tool.ripristina_licenza(str(backup), percorso, "IL-TOKEN-DI-PROVA")

    assert percorso.read_bytes() == originale, \
        "la licenza vera non e' tornata: l'utente resta senza licenza pur avendo un backup"
    assert not backup.exists(), "il backup e' rimasto orfano: bloccherebbe la corsa successiva"


def test_una_licenza_corrotta_durante_gli_scatti_non_viene_sovrascritta(tool, tmp_path):
    """Secondo caso da chiarire, sempre di GPT-5.5: file corrente illeggibile e backup valido.

    Comportamento voluto e fissato qui: **non si tocca niente**. Un file che non riusciamo a
    leggere non è attribuibile a noi — potrebbe essere una licenza vera scritta a metà — e
    sovrascriverlo consumerebbe anche il backup. Restano entrambi sul disco, con l'avviso:
    l'utente ha tutto ciò che serve per decidere, e non abbiamo distrutto nulla.
    """
    percorso = tmp_path / "license_state.json"
    backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
    percorso.write_text("non e' JSON {{{", encoding="utf-8")
    backup.write_text('{"token": "LICENZA-VERA", "last_seen": 1}', encoding="utf-8")
    corrotto = percorso.read_bytes()
    salvato = backup.read_bytes()

    tool.ripristina_licenza(str(backup), percorso, "IL-TOKEN-DI-PROVA")

    assert percorso.read_bytes() == corrotto, "un file non leggibile e' stato sovrascritto"
    assert backup.read_bytes() == salvato, "il backup e' stato consumato su un caso ambiguo"


def test_non_cancella_una_licenza_vera_attivata_durante_gli_scatti(tool, tmp_path):
    """Caso opposto e altrettanto rovinoso: durante la sessione l'utente incolla una licenza
    VERA nella scheda «🔒 Licenza». A fine scatti la pulizia non deve portarsela via."""
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "LICENZA-VERA-APPENA-ATTIVATA", "last_seen": 9}',
                        encoding="utf-8")

    tool.rimuovi_licenza_di_prova(percorso, "IL-TOKEN-DI-PROVA-CHE-AVEVAMO-SCRITTO")

    assert percorso.exists(), \
        "la licenza vera attivata durante la sessione è stata cancellata dalla pulizia"


@pytest.mark.parametrize("quale", ["ripristina_licenza", "rimuovi_licenza_di_prova"])
def test_nessuna_pulizia_solleva_mai_se_il_file_e_lockato(tool, tmp_path, monkeypatch, quale):
    """**Nessuna** delle due pulizie deve sollevare: girano entrambe da `atexit`.

    Rilievo GPT-5.5 sulla #310 su `rimuovi_licenza_di_prova`, ma il difetto era di **classe**:
    anche `ripristina_licenza` chiamava `os.replace` nudo. Un'eccezione da `atexit` non la
    gestisce nessuno — Python stampa un traceback a fine processo e l'utente non capisce quale
    file sistemare. Su Windows è verosimile: antivirus e indicizzatore tengono aperti i file
    appena scritti.

    Parametrizzato apposta sulle DUE funzioni: correggerne una sola era l'errore che questa PR
    ha già fatto due volte (Regola 2 — cerca la classe, non il sito).
    """
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "TOK", "last_seen": 1}', encoding="utf-8")

    def _esplode(*_a, **_k):
        raise PermissionError("file lockato dall'antivirus")

    monkeypatch.setattr(tool.os, "replace", _esplode)
    monkeypatch.setattr(pathlib.Path, "unlink", _esplode)

    if quale == "ripristina_licenza":
        backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
        backup.write_text('{"token": "VERA", "last_seen": 0}', encoding="utf-8")
        tool.ripristina_licenza(str(backup), percorso, "TOK")   # non deve sollevare
    else:
        tool.rimuovi_licenza_di_prova(percorso, "TOK")      # non deve sollevare


def test_un_file_di_licenza_corrotto_non_viene_cancellato_ne_fa_esplodere(tool, tmp_path):
    """Se `license_state.json` non è JSON valido non è roba nostra: non si tocca e non si
    solleva. Copre il caso segnalato da GPT-5.5 («JSON illeggibile / file corrotto»)."""
    percorso = tmp_path / "license_state.json"
    percorso.write_text("questo non e' JSON {{{", encoding="utf-8")

    tool.rimuovi_licenza_di_prova(percorso, "IL-NOSTRO-TOKEN")

    assert percorso.exists(), "un file corrotto e' stato cancellato: non era nostro da toccare"


def test_un_handler_precedente_che_solleva_vince_sul_nostro_sys_exit(tool, monkeypatch):
    """Contratto fissato su richiesta di GPT-5.5 (#310, quarto giro).

    Se l'handler che c'era prima **termina da sé** o solleva, la nostra `sys.exit(0)` non viene
    raggiunta e il codice d'uscita è il suo. È il comportamento giusto — chi aveva installato
    quell'handler ha deciso lui come si esce — ma finché non è fissato da un test resta
    un'inerzia, non una scelta: un domani qualcuno potrebbe avvolgere la chiamata in un
    `try/except` e cambiarlo senza accorgersene.

    Il ripristino della licenza **non si perde comunque**: `atexit` gira su qualunque uscita.
    """
    import signal as _signal

    def _handler_che_termina(*_a):
        raise SystemExit(3)

    installato = {}
    monkeypatch.setattr(tool.signal, "getsignal", lambda _s: _handler_che_termina)
    monkeypatch.setattr(tool.signal, "signal", lambda s, fn: installato.__setitem__("fn", fn))

    tool._installa_ripristino_su_segnale(_signal.SIGTERM)

    with pytest.raises(SystemExit) as errore:
        installato["fn"](_signal.SIGTERM, None)

    assert errore.value.code == 3, (
        f"il codice d'uscita non è quello dell'handler precedente ({errore.value.code!r}): la "
        "nostra `sys.exit(0)` lo sta scavalcando, e chi aveva installato quell'handler perde "
        "il controllo di come il processo esce")


def test_il_ripristino_non_solleva_se_non_ce_niente_da_ripristinare(tool, tmp_path):
    """`ripristina_licenza` gira da `atexit`, dove un'eccezione non serve a nessuno e sporca
    l'uscita del processo."""
    percorso = tmp_path / "license_state.json"
    tool.ripristina_licenza(None, percorso, "TOK")                 # nessun backup registrato
    tool.ripristina_licenza(str(tmp_path / "inesistente"), percorso, "TOK")  # backup sparito


def test_se_il_processo_muore_subito_dopo_lo_spostamento_la_licenza_vera_torna(tool, tmp_path,
                                                                               monkeypatch,
                                                                               hardware_finto):
    """Rilievo **Claude Fable 5** sulla #310: la finestra fra lo spostamento e la registrazione.

    La pulizia veniva registrata **dopo** `save_license`, cioè dopo che `shutil.move` aveva già
    portato via la licenza vera. Se il processo muore in quella finestra — un `SystemExit` da
    `issue_license`, un errore di firma, un SIGTERM — non c'è nessun `atexit` da eseguire: la
    licenza vera resta **in ostaggio** dentro `license_state.json.pre-screenshot`, l'app non ne
    trova nessuna, e alla corsa successiva il tool si rifiuta pure di ripartire perché quel
    backup esiste. Cioè lo stesso danno che questa PR esiste per prevenire, con un passaggio in
    più.

    Qui si simula la morte nel punto peggiore — subito dopo lo spostamento — e si pretende che la
    pulizia sia **già registrata** e che rimetta a posto la licenza vera.
    """
    from license_manager import core
    from xtrader_bridge import config_store, license_store

    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    percorso = pathlib.Path(license_store.license_state_path(str(tmp_path)))
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    registrati = []
    monkeypatch.setattr(tool.atexit, "register",
                        lambda fn, *a, **k: registrati.append((fn, a, k)))

    def _muore(*_a, **_k):
        raise KeyboardInterrupt("il processo muore mentre emette la licenza")

    monkeypatch.setattr(core, "issue_license", _muore)

    with pytest.raises(KeyboardInterrupt):
        tool._attiva_licenza_di_prova()

    backup = percorso.with_name(percorso.name + tool.SUFFISSO_BACKUP)
    assert backup.exists() and not percorso.exists(), \
        "il test non è nella finestra che vuole esercitare (spostamento già fatto, scrittura no)"

    assert registrati, (
        "nessuna pulizia registrata al momento della morte: la licenza vera resta in ostaggio nel "
        "backup e l'utente si ritrova il bridge bloccato")
    for fn, args, kwargs in registrati:
        fn(*args, **kwargs)

    assert percorso.read_bytes() == originale, \
        "la licenza vera non è tornata al suo posto dopo la morte nella finestra"


def test_i_gestori_di_segnale_sono_installati_prima_di_toccare_la_licenza(tool, tmp_path,
                                                                         monkeypatch,
                                                                         hardware_finto):
    """Stesso rilievo, altra metà: `atexit` da solo non basta.

    Un SIGTERM con disposizione **di default** termina il processo *senza* eseguire gli handler
    `atexit`: è proprio per questo che il tool installa i propri gestori. Installarli dopo aver
    spostato la licenza vera lascia scoperta esattamente la finestra in cui il danno è massimo.

    Si registra l'ordine reale delle chiamate invece di ispezionare il sorgente: un `grep` sul
    file direbbe solo dove stanno le righe, non in che ordine vengono eseguite.
    """
    from xtrader_bridge import config_store, license_store

    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    percorso = pathlib.Path(license_store.license_state_path(str(tmp_path)))
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")

    eventi = []
    monkeypatch.setattr(tool.atexit, "register", lambda fn, *a, **k: eventi.append("atexit"))
    monkeypatch.setattr(tool.signal, "signal", lambda s, fn: eventi.append("segnale"))
    vero_move = tool.shutil.move

    def _traccia_move(src, dst):
        eventi.append("sposta")
        return vero_move(src, dst)

    monkeypatch.setattr(tool.shutil, "move", _traccia_move)

    tool._attiva_licenza_di_prova()

    assert "sposta" in eventi, "il test non ha esercitato lo spostamento della licenza vera"
    assert eventi.index("segnale") < eventi.index("sposta"), (
        f"i gestori di segnale sono installati DOPO lo spostamento (ordine: {eventi}): un SIGTERM "
        "in quella finestra uccide il processo senza eseguire `atexit` e la licenza vera resta "
        "nel backup")
    assert eventi.index("atexit") < eventi.index("sposta"), (
        f"la pulizia è registrata DOPO lo spostamento (ordine: {eventi}): nella finestra non c'è "
        "niente da eseguire")


def test_hardware_non_identificabile_si_ferma_senza_toccare_la_licenza(tool, tmp_path,
                                                                      monkeypatch):
    """Il ramo fail-closed, qui come **soggetto** e non come presupposto.

    Su una macchina senza sorgenti hardware `hwid.hardware_id()` ritorna la sentinella
    `HW1-0000-…`: una licenza legata a essa varrebbe su tutte le macchine cieche, quindi il tool
    si ferma. Questo test lo fissa e — cosa che conta di più — pretende che fermandosi **non
    abbia già spostato** la licenza vera.
    """
    from xtrader_bridge import config_store, license_store
    from xtrader_bridge.licensing import hwid

    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    monkeypatch.setattr(tool.hwid, "hardware_id", lambda: hwid.NO_HARDWARE_ID)
    percorso = pathlib.Path(license_store.license_state_path(str(tmp_path)))
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    with pytest.raises(SystemExit) as errore:
        tool._attiva_licenza_di_prova()

    assert "hardware" in str(errore.value).lower(), \
        "il messaggio non spiega perché si è fermato: inutile a chi lo legge"
    assert percorso.read_bytes() == originale, \
        "si è fermato DOPO aver toccato la licenza vera: il rifiuto deve venire prima"
    assert not percorso.with_name(percorso.name + tool.SUFFISSO_BACKUP).exists(), \
        "ha lasciato un backup che bloccherebbe la corsa successiva pur non avendo fatto nulla"


@pytest.mark.parametrize("quale", ["ripristina_licenza", "rimuovi_licenza_di_prova"])
@pytest.mark.parametrize("token_non_emesso, sul_disco", [
    (None, "None"),     # `str(None)` combaciava con un token letteralmente «None»
    ("", ""),           # `== ""` combacia con un file il cui token è vuoto: corrotto, non nostro
])
def test_prima_che_il_token_esista_nessuna_pulizia_si_attribuisce_il_file(
        tool, tmp_path, quale, token_non_emesso, sul_disco):
    """Rilievo **GPT-5.5** sulla #310, secondo e terzo giro, coda della correzione precedente.

    Da quando la pulizia si registra *prima* di emettere il token, esiste un istante in cui può
    girare senza token. GPT-5.5 chiedeva di verificare che in quell'istante sia sempre un no-op
    sicuro. Non lo era: il confronto finiva in `str(None)`, cioè nella stringa `"None"`, che
    combacia con un file il cui token fosse letteralmente `"None"`.

    Coincidenza assurda, conseguenza no: nel ramo `rimuovi` il file veniva **cancellato**, nel
    ramo `ripristina` veniva **sovrascritto** col backup, che veniva pure consumato.

    Al terzo giro GPT-5.5 chiedeva di aggiungere il caso `""`. La risposta giusta non era
    aggiungere un caso ma **allargare la guardia** a qualunque token falsy (Regola 2: la classe,
    non il sito): la stringa vuota è la stessa condizione — non abbiamo un token da riconoscere —
    e con `== ""` combacerebbe con un file dal token vuoto, cioè corrotto o modificato a mano.
    I due casi restano parametrizzati qui perché è la coppia che il difetto produceva, e su
    **entrambe** le pulizie, non solo su quella segnalata.
    """
    percorso = tmp_path / "license_state.json"
    percorso.write_text(f'{{"token": "{sul_disco}", "last_seen": 1}}', encoding="utf-8")
    intatto = percorso.read_bytes()
    backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
    backup.write_text('{"token": "LICENZA-VERA", "last_seen": 0}', encoding="utf-8")
    salvato = backup.read_bytes()

    if quale == "rimuovi_licenza_di_prova":
        tool.rimuovi_licenza_di_prova(percorso, token_non_emesso)
    else:
        tool.ripristina_licenza(str(backup), percorso, token_non_emesso)

    assert percorso.read_bytes() == intatto, (
        "senza un token nostro la pulizia ha comunque toccato il file: prima di scrivere qualcosa "
        "non c'è niente che possiamo attribuirci")
    assert backup.read_bytes() == salvato, \
        "il backup è stato consumato su un caso in cui non avevamo ancora scritto nulla"


def test_due_invocazioni_nello_stesso_processo_lasciano_la_licenza_vera_al_suo_posto(
        tool, tmp_path, monkeypatch, hardware_finto):
    """Secondo rischio manuale segnalato da **GPT-5.5** sulla #310: gli `atexit` non si rimuovono,
    quindi due invocazioni nello stesso processo accumulano due pulizie con stati diversi.

    Non è raggiungibile dalla CLI — `__main__` chiama una volta sola — ma è il genere di contratto
    che va **fissato** invece che dedotto, perché domani qualcuno potrebbe importare il launcher.
    Il risultato deve essere: la seconda invocazione si ferma (il backup esiste già), le due
    pulizie girano in ordine LIFO come fa `atexit` vero, e alla fine sul disco c'è la licenza
    VERA e nient'altro.
    """
    from xtrader_bridge import config_store, license_store

    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    percorso = pathlib.Path(license_store.license_state_path(str(tmp_path)))
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    registrati = []
    monkeypatch.setattr(tool.atexit, "register",
                        lambda fn, *a, **k: registrati.append((fn, a, k)))

    tool._attiva_licenza_di_prova()
    with pytest.raises(SystemExit) as errore:
        tool._attiva_licenza_di_prova()
    assert tool.SUFFISSO_BACKUP in str(errore.value), \
        "la seconda invocazione non si è fermata sul backup già presente"

    assert len(registrati) == 2, f"pulizie registrate: {len(registrati)}, attese 2"
    for fn, args, kwargs in reversed(registrati):      # `atexit` esegue in ordine LIFO
        fn(*args, **kwargs)

    assert percorso.read_bytes() == originale, \
        "dopo due invocazioni la licenza vera non è tornata al suo posto"
    assert not percorso.with_name(percorso.name + tool.SUFFISSO_BACKUP).exists(), \
        "è rimasto un backup orfano: bloccherebbe la corsa successiva"


@pytest.mark.parametrize("payload", ["[]", "3", '"abc"', "null"])
@pytest.mark.parametrize("quale", ["ripristina_licenza", "rimuovi_licenza_di_prova"])
def test_un_json_valido_che_non_e_un_oggetto_non_fa_sollevare_la_pulizia(tool, tmp_path, quale,
                                                                        payload):
    """Rilievo **CodeRabbit** sulla #310, e il test che avevo scritto non lo copriva.

    `json.loads` accetta anche JSON validi che **non sono oggetti** — `[]`, `3`, `"abc"`, `null`
    — e su quelli `.get` solleva `AttributeError`, che non era catturato. L'eccezione usciva da
    `ripristina_licenza` / `rimuovi_licenza_di_prova`, cioè **da `atexit`**, rompendo il contratto
    «MAI sollevare da atexit» scritto nel file stesso: traceback a fine processo e l'utente che
    non capisce quale file sistemare.

    Il mio test sul file corrotto usava `"non e' JSON {{{"`, che solleva `ValueError` e non
    arriva mai a `.get`: passava senza toccare il difetto. Un `license_state.json` modificato a
    mano che contiene `[]` ci arriva eccome.
    """
    percorso = tmp_path / "license_state.json"
    percorso.write_text(payload, encoding="utf-8")
    intatto = percorso.read_bytes()

    if quale == "rimuovi_licenza_di_prova":
        tool.rimuovi_licenza_di_prova(percorso, "IL-NOSTRO-TOKEN")   # non deve sollevare
    else:
        backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
        backup.write_text('{"token": "LICENZA-VERA", "last_seen": 0}', encoding="utf-8")
        tool.ripristina_licenza(str(backup), percorso, "IL-NOSTRO-TOKEN")   # non deve sollevare
        assert backup.read_bytes(), "il backup è stato consumato su un file non attribuibile"

    assert percorso.read_bytes() == intatto, \
        "un file che non è un oggetto JSON non è nostro: non va né cancellato né sovrascritto"


def test_canarino_i_gestori_di_segnale_sono_quelli_di_pytest():
    """Secondo canarino di fine file, gemello di quello sulla chiave pubblica.

    `_attiva_licenza_di_prova` installa gestori **veri** per SIGTERM e SIGINT, e `monkeypatch`
    non disfa `signal.signal`: senza il ripristino, da qui in poi un Ctrl+C nella sessione pytest
    finirebbe nel gestore del launcher invece che nel percorso di interruzione normale.

    Come l'altro canarino vive in fondo di proposito — pytest esegue in ordine di scrittura — e
    da solo passa banalmente: serve nel giro completo del file, che è come gira in CI.
    """
    for numero, atteso in _GESTORI_ORIGINALI.items():
        assert signal.getsignal(numero) == atteso, (
            f"il gestore di {numero!r} è rimasto quello installato dal launcher: un Ctrl+C nel "
            "resto della sessione pytest non finirebbe più dove deve, e la chiusura trattenuta "
            "punta a una cartella temporanea già cancellata")


def test_canarino_la_chiave_deployata_e_ancora_quella_reale():
    """Canarino di fine file: la sessione pytest non deve restare con la chiave di TEST.

    `_attiva_licenza_di_prova` **assegna** `LICENSE_PUBLIC_KEY_HEX` sui moduli condivisi
    `licensing.license` e `licensing.revocation`. Dentro pytest quei moduli sono gli stessi di
    tutti gli altri test: se la modifica non venisse disfatta, da qui in poi ogni verifica di
    firma Ed25519 girerebbe con la chiave di test e una regressione vera sulla verifica passerebbe
    senza che nessuno se ne accorga.

    Vive in fondo al file di proposito: pytest esegue i test nell'ordine in cui sono scritti,
    quindi quando questo gira i test che chiamano il launcher sono già passati. Eseguito **da
    solo** passa banalmente — è un canarino, non una dimostrazione: la sua utilità è nel giro
    completo del file, che è come gira in CI.
    """
    assert _lic.LICENSE_PUBLIC_KEY_HEX == _CHIAVE_DEPLOYATA_REALE, (
        "la chiave pubblica deployata è rimasta quella di TEST dopo i test di questo file: da qui "
        "in poi l'intera sessione pytest verifica le firme con la chiave sbagliata")
    assert _rev.LICENSE_PUBLIC_KEY_HEX == _CHIAVE_DEPLOYATA_REALE, (
        "stessa cosa su `revocation`, che copia il valore all'import: è il posto che si dimentica")
