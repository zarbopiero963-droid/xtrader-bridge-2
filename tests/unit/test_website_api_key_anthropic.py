"""La guida «Ottenere la API key Anthropic»: la pagina che dice a un utente dove spendere soldi.

È diversa dalle altre guide del sito. Le altre spiegano il nostro programma; questa manda
l'utente su un servizio a **pagamento di terzi**, gli fa creare una credenziale che spende dal
suo credito, e gli chiede di incollarla nel nostro software. Tre cose che, se raccontate male,
costano all'utente soldi o una chiave compromessa:

* **l'indirizzo giusto** — la Console è su `platform.claude.com`; `console.anthropic.com`
  oggi rimanda lì. Una guida che manda al posto sbagliato fa perdere tempo, e uno screenshot
  che non combacia con il testo fa credere all'utente di essersi perso;
* **il credito** — senza, la chiave si crea benissimo e poi *ogni* richiesta viene rifiutata.
  È il modo più comune di perdere mezz'ora convinti che sia sbagliata la chiave;
* **che la chiave è una password che spende** — chi la ottiene usa il credito di chi l'ha fatta.

E c'è una regola del sito che qui è più facile violare che altrove
(`docs/policy_lingue_sito.md` §3-§4): la Console è **solo in inglese**, quindi le versioni
IT/ES devono dirlo e citare i pulsanti verbatim invece di tradurli.
"""

import re
from pathlib import Path

import pytest

from tests.conftest import dizionari_i18n_sito

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "website" / "static"
_PAGINA = _STATIC / "api-key-anthropic.html"
_DOCS = _STATIC / "documentazione.html"
_I18N = _STATIC / "i18n.js"
_MAIN = _ROOT / "website" / "main.py"


def _html() -> str:
    return _PAGINA.read_text(encoding="utf-8")


def _dizionari() -> dict:
    return dizionari_i18n_sito(_I18N)


def test_la_pagina_esiste_ed_e_servita():
    """Una pagina che esiste su disco ma non ha la rotta è invisibile: 404 per tutti."""
    assert _PAGINA.is_file(), "manca website/static/api-key-anthropic.html"
    main = _MAIN.read_text(encoding="utf-8")
    assert '"/guida/api-key-anthropic": "api-key-anthropic.html"' in main, \
        "la pagina non è in _PAGES: nessuna rotta la serve"


def test_e_raggiungibile_dalla_documentazione():
    """Nessun menu la elenca: se `/documentazione` non la linka, l'unico modo di arrivarci è
    conoscere l'URL a memoria — cioè nessuno."""
    docs = _DOCS.read_text(encoding="utf-8")
    assert "/guida/api-key-anthropic" in docs, \
        "la pagina documentazione non linka la guida della API key"


def test_manda_alla_console_giusta():
    """`console.anthropic.com` **rimanda** a `platform.claude.com` (301, verificato).

    Una guida con lo screenshot della Console nuova e il testo che nomina l'indirizzo vecchio
    come destinazione è il tipo di incoerenza che fa richiudere la pagina. L'indirizzo vecchio
    può comparire — la pagina lo cita apposta, perché è quello che la gente ricorda — ma
    quello **operativo** dev'essere il nuovo.
    """
    testo = _html()
    assert "platform.claude.com" in testo, "la guida non nomina la Console attuale"
    assert "platform.claude.com/settings/keys" in testo, \
        "manca l'indirizzo diretto della pagina API keys"


def test_avvisa_del_credito_prima_che_la_chiave_non_funzioni():
    """Il passo che salta chiunque. Senza credito la chiave è valida e inutile, e il messaggio
    d'errore parla di «balance», non di «chiave»: chi non è stato avvisato cerca il problema
    dove non è. È successo su questo stesso repository, ai workflow di review."""
    testo = _html()
    assert "credit balance is too low" in testo, \
        "la guida non riporta il messaggio d'errore vero del credito esaurito"
    assert "Billing" in testo, "non dice dove si ricarica"


def test_distingue_la_chiave_dall_abbonamento_a_claude():
    """Chi paga già Claude Pro dà per scontato di avere l'API inclusa. Non è così, e scoprirlo
    dopo aver pagato due volte è il genere di sorpresa che si evita con una riga."""
    testo = _html()
    assert re.search(r"non è l'abbonamento|Non è l'abbonamento", testo), \
        "manca l'avviso che l'abbonamento a Claude non comprende l'uso da programma"


def test_avvisa_che_la_chiave_si_vede_una_volta_sola():
    """Chiusa la finestra, Anthropic non la rimostra. Chi non lo sa la perde e deve rifarla."""
    testo = _html()
    assert re.search(r"una volta sola|non te la rimostra", testo), \
        "la guida non avvisa che la chiave è mostrata una sola volta"


def test_dice_che_la_chiave_e_una_password_che_spende():
    """Non è la solita formula: questa credenziale ha un costo diretto per chi la possiede.
    L'avviso deve dire **anche** come rimediare (revoca), non solo spaventare."""
    testo = _html()
    assert "password" in testo.lower(), "manca l'avviso che la chiave è una password"
    assert re.search(r"revoca|revócala|revoke", testo, re.I), \
        "non spiega come revocare una chiave sfuggita di mano"


def test_dichiara_la_non_affiliazione_ad_anthropic():
    """Il footer copre TradingSportivo e Betting Toolkit. Questa pagina nomina Anthropic in
    ogni passo e ne mostrerà le schermate: senza una riga esplicita può leggersi come se
    BetRelay rivendesse il loro servizio, che non è vero e non deve sembrarlo."""
    testo = _html()
    assert "non è affiliata ad Anthropic" in testo, \
        "manca la dichiarazione di non affiliazione ad Anthropic"


def test_nessuna_chiave_vera_nella_pagina_o_nei_dizionari():
    """Il test più importante del file, e il meno ovvio.

    Questa è la pagina che parla di API key: è il posto del sito dove è più probabile che una
    chiave vera ci finisca per sbaglio — un copia-incolla mentre si scrive l'esempio, una
    didascalia presa da uno screenshot. Una chiave pubblicata è spendibile da chiunque la
    legga, e il sito è indicizzato.
    """
    sospette = []
    for percorso in (_PAGINA, _I18N, _DOCS):
        testo = percorso.read_text(encoding="utf-8")
        # `sk-ant-` seguito da abbastanza materiale da essere una chiave vera: la guida cita il
        # prefisso da solo (`sk-ant-`), e quello deve restare lecito.
        for trovata in re.findall(r"sk-ant-[A-Za-z0-9_\-]{16,}", testo):
            sospette.append("%s: %s…" % (percorso.name, trovata[:20]))
    assert not sospette, (
        "sembra esserci una API key vera nel sito: %s — se è reale va REVOCATA su "
        "platform.claude.com, non solo cancellata da qui" % "; ".join(sospette))


@pytest.mark.parametrize("lingua, parola", [("en", "Italian"), ("es", "italiano")])
def test_le_versioni_en_es_dichiarano_che_le_schermate_sono_in_italiano(lingua, parola):
    """`policy_lingue_sito.md` §4: il ripiego non è silenzioso.

    **Avevo scritto il contrario.** La prima stesura diceva che la Console esiste solo in
    inglese: gli screenshot del proprietario hanno dimostrato che è **tradotta** e segue la
    lingua del browser — la sua è in italiano. Quindi il ripiego non è «mostriamo l'inglese
    perché l'italiano non esiste», è «mostriamo l'italiano perché sono le schermate che
    abbiamo», e va detto per quello che è: un utente inglese vedrà la SUA Console in inglese,
    e deve sapere perché le figure non gli combaciano.
    """
    valore = _dizionari()[lingua].get("apikey.shots.lang")
    assert valore, "«apikey.shots.lang» non è tradotta in «%s»" % lingua
    assert parola in valore, (
        "la nota sulle schermate in «%s» non dice che le figure sono in italiano: %r"
        % (lingua, valore))


@pytest.mark.parametrize("etichetta", ["API key Anthropic:", "💾 Salva chiave", "▶ Abilita"])
def test_le_etichette_di_betrelay_restano_verbatim_in_en_es(etichetta):
    """`policy_lingue_sito.md` §3, applicato al nostro stesso programma.

    Il passo 6 dice dove incollare la chiave dentro BetRelay — e il pannello dell'assistente è
    **in italiano anche nell'app in inglese** (debito noto). Tradurre «💾 Salva chiave» in
    «Save key» manderebbe l'utente inglese a cercare un pulsante che sullo schermo non esiste:
    finché l'app non è tradotta, le etichette si citano come sono.
    """
    dizionari = _dizionari()
    for lingua in ("en", "es"):
        blocco = dizionari[lingua]
        testo = " ".join(v for k, v in blocco.items() if k.startswith("apikey."))
        assert etichetta in testo, (
            "in «%s» l'etichetta «%s» di BetRelay non compare verbatim: l'utente non "
            "troverebbe il campo" % (lingua, etichetta))


def test_ogni_passo_ha_una_figura_o_un_segnaposto_dichiarato():
    """Nessun passo può restare senza illustrazione **e** senza dirlo.

    Gli screenshot della Console li ha fatti il proprietario (io non posso: è dietro il login,
    e ricostruirla sarebbe fabbricare schermate — §2 della policy). Quello di BetRelay non c'è
    ancora, e finché manca il suo riquadro lo dichiara invece di lasciare un buco muto.

    Il test non conta un numero fisso: guarda **ogni** `<section class="step">` e pretende che
    contenga o una `<figure class="shot">` o un `<div class="attesa">`. Così regge sia oggi sia
    quando l'ultima figura arriverà.
    """
    html = _html()
    passi = re.findall(r'<section class="step">(.*?)</section>', html, re.S)
    assert len(passi) >= 6, "i passi della guida sono %d: la pagina è cambiata" % len(passi)
    for n, corpo in enumerate(passi, 1):
        assert 'class="shot"' in corpo or 'class="attesa"' in corpo, \
            "il passo %d non ha né una figura né un segnaposto dichiarato" % n

    # e i segnaposto rimasti devono essere tradotti come tutto il resto
    for chiave in re.findall(r'data-i18n="(apikey\.[^"]*attesa)"', html):
        for lingua in ("en", "es"):
            assert _dizionari()[lingua].get(chiave), \
                "il segnaposto «%s» non è tradotto in «%s»" % (chiave, lingua)


def test_le_immagini_esistono_e_hanno_un_alt():
    """Un `<img>` con il percorso sbagliato è un rettangolo vuoto in pagina, e nessun test di
    contenuto se ne accorge. L'`alt` serve a chi non vede le immagini — e su una guida fatta
    di schermate è metà del contenuto.

    E dev'essere **tradotto** (rilievo CodeRabbit #300): `i18n.js` cambiava solo il contenuto dei
    `[data-i18n]`, quindi per un utente EN o ES le immagini restavano descritte in italiano. Su
    questa pagina è metà del testo che non cambiava lingua.
    """
    html = _html()
    dizionari = _dizionari()
    immagini = re.findall(r'<img[^>]+>', html)
    assert immagini, "la guida non ha più nessuna immagine"
    for tag in immagini:
        src = re.search(r'src="([^"]+)"', tag).group(1)
        percorso = _ROOT / "website" / src.lstrip("/")
        assert percorso.is_file(), "immagine mancante sul disco: %s" % src

        # `(?<![-\w])alt=` e non `alt=`: `data-i18n-alt="…"` contiene la sottostringa `alt="`, e
        # un match ingenuo leggerebbe la CHIAVE al posto della descrizione.
        alt = re.search(r'(?<![-\w])alt="([^"]*)"', tag)
        assert alt and len(alt.group(1)) > 15, "alt assente o troppo corto: %s" % src

        chiave = re.search(r'data-i18n-alt="([^"]+)"', tag)
        assert chiave, (
            "l'immagine %s non ha `data-i18n-alt`: il suo alt resterebbe in italiano per gli "
            "utenti EN/ES" % src)
        for lingua in ("en", "es"):
            tradotto = dizionari[lingua].get(chiave.group(1))
            assert tradotto and len(tradotto.strip()) > 15, (
                "l'alt di %s non è tradotto in «%s» (chiave %s)" % (src, lingua, chiave.group(1)))
            assert tradotto.strip() != alt.group(1).strip(), (
                "l'alt di %s in «%s» è identico all'italiano" % (src, lingua))


def test_il_riquadro_che_copriva_la_chiave_e_davvero_pieno():
    """La schermata del passo 5 conteneva una API key **vera**, in chiaro.

    Nessun reviewer la guarderà mai: CodeRabbit esclude i `.jpg` per configurazione
    (`!**/*.jpg`), e i due reviewer forti saltano i binari per costruzione. Su questa immagine
    l'unico controllo possibile è quello automatico, e deve guardare **i pixel**, non il peso
    del file: un originale ricompresso peserebbe meno e passerebbe una guardia sulla dimensione.

    Qui si campiona l'area dove stava la chiave e si pretende che sia **uniforme**: se qualcuno
    rimettesse una versione con il testo scoperto, lì dentro comparirebbero i pixel chiari delle
    lettere e la deviazione salirebbe.

    Resta vero che il presidio ultimo è umano ed è scritto in pagina: una chiave che si è vista
    si **revoca**. Questo test impedisce solo che torni visibile per distrazione.
    """
    Image = pytest.importorskip("PIL.Image", reason="Pillow assente: il controllo sui pixel "
                                                   "gira dove le immagini si possono aprire")
    percorso = _ROOT / "website" / "static" / "img" / "apikey" / "06-chiave-mostrata.jpg"
    assert percorso.is_file(), "manca la schermata del passo 5"

    img = Image.open(percorso).convert("L")
    larghezza, altezza = img.size
    # il riquadro nero sulla chiave, in frazioni della figura (indipendenti dalla risoluzione)
    area = img.crop((int(larghezza * 0.27), int(altezza * 0.505),
                     int(larghezza * 0.72), int(altezza * 0.535)))
    # `tobytes()` e non `getdata()`: su un'immagine «L» è un byte per pixel, e non è deprecato
    # (Pillow toglie `getdata` nella 14). Stesso dato, senza un warning che sporca la suite.
    valori = list(area.tobytes())
    media = sum(valori) / len(valori)
    massimo = max(valori)
    assert media < 60, (
        "l'area dove stava la chiave non è più scura (media %.1f): sembra scoperta. Se la "
        "chiave è tornata visibile va REVOCATA su platform.claude.com, non solo ricoperta"
        % media)
    assert massimo < 140, (
        "nell'area della chiave ci sono pixel chiari (max %d): probabile testo leggibile" % massimo)


def _blocco_job(testo: str, nome: str) -> str:
    """Il corpo del job `nome` dentro un workflow, per indentazione.

    Niente PyYAML: non è una dipendenza del progetto (vedi `test_yaml_dei_workflow_ai_e_parsabile`,
    che infatti lo salta), e una guardia che si salta è il difetto che questo file combatte.
    """
    righe = testo.splitlines()
    for i, riga in enumerate(righe):
        if re.match(r"^  %s:\s*$" % re.escape(nome), riga):
            corpo = []
            for successiva in righe[i + 1:]:
                if successiva.strip() and not successiva.startswith("   "):
                    break
                corpo.append(successiva)
            return "\n".join(corpo)
    raise AssertionError("job «%s» non trovato nel workflow" % nome)


def _comandi_eseguiti(blocco: str) -> str:
    """Il blocco senza i commenti YAML, con i `run: >` ricongiunti in una riga sola.

    Rilievo GPT-5.5 (#300): cercare una stringa nel testo grezzo la trova anche dentro un
    commento o uno step disattivato — cioè una CI che *sembra* installare Pillow e non lo fa.
    È la stessa cecità che `test_dev_lockfile_76` ha già pagato sul guard delle constraints, e
    la lezione lì era esattamente questa: guardare ciò che la shell riceve, non ciò che si legge.
    """
    ripulite = []
    for riga in blocco.splitlines():
        senza = re.sub(r"(^|\s)#.*$", "", riga)          # commento a inizio riga o dopo spazio
        if senza.strip():
            ripulite.append(senza)
    # `run: >` è uno scalare *folded*: le righe successive più indentate sono UN comando solo.
    return re.sub(r"run:\s*>[-+]?\s*\n", "run: ", "\n".join(ripulite))


def test_il_job_unit_installa_pillow_altrimenti_la_guardia_sui_pixel_e_decorativa():
    """La CI deve installare Pillow, o il controllo sui pixel non gira mai.

    Rilievo **indipendente di Claude Fable 5 e OpenRouter Fugu Ultra** sulla #300, entrambi con
    le stesse parole: senza Pillow `importorskip` salta il test **in silenzio**, e quella è
    l'unica guardia che guarda il *contenuto* dell'immagine invece dei suoi byte.

    Perché serve, dato che c'è già lo `sha256`: le due guardie coprono cose diverse. Le impronte
    beccano l'immagine cambiata **per distrazione**; non beccano chi cambia immagine **e**
    impronta nello stesso commit — che è il caso in cui una schermata con la chiave scoperta
    tornerebbe in pagina passando i test. Lì serve qualcosa che apra il file e guardi i pixel.

    Perché l'install sta nel workflow e **non** in `requirements-dev.txt`: quel file scende in
    `requirements-build.in` (`-r requirements-dev.txt`), quindi Pillow finirebbe nel lock hashato
    dell'EXE — una libreria di immagini dentro l'eseguibile, che il programma non usa — e
    renderebbe stantii i lock Windows/Linux, da rigenerare a mano su runner dedicati. Decisione
    del proprietario del 6 agosto: pin esatto nel solo job che esegue il test.

    Questo test esiste perché quella riga non sparisca in silenzio, che è esattamente il modo in
    cui la guardia era sparita la prima volta.
    """
    workflow = (_ROOT / ".github" / "workflows" / "pr-checks.yml").read_text(encoding="utf-8")
    unit = _comandi_eseguiti(_blocco_job(workflow, "unit"))

    posa = unit.find("requirements-imgcheck.txt")
    assert posa != -1, (
        "il job `unit` di pr-checks.yml non installa più requirements-imgcheck.txt: il test sui "
        "pixel della schermata che conteneva una API key vera tornerebbe a saltarsi IN SILENZIO "
        "in CI. Se lo togli di proposito, togli anche il test sui pixel e dichiaralo nel PR.")

    assert re.search(r"pip install[^\n]*--require-hashes[^\n]*requirements-imgcheck\.txt", unit), (
        "l'install di requirements-imgcheck.txt ha perso `--require-hashes`: senza, pip accetta "
        "qualunque file il server gli dia, e questa dipendenza sta FUORI dal lock hashato del repo")

    # L'ORDINE conta (rilievo CodeRabbit #300): l'install spostato sotto il pytest lascerebbe il
    # guard verde e il test sui pixel saltato, che è precisamente il difetto da cui nasce tutto.
    posa_pytest = unit.find("pytest tests/unit")
    assert posa_pytest != -1, "il job `unit` non esegue più `pytest tests/unit`: workflow cambiato"
    assert posa < posa_pytest, (
        "l'install di Pillow viene DOPO `pytest tests/unit`: quando i test girano Pillow non c'è "
        "ancora, quindi il controllo sui pixel si salta lo stesso — con questo guard verde")

    # Il pin e i suoi hash stanno nello stesso file, così non possono divergere.
    imgcheck = (_ROOT / "requirements-imgcheck.txt").read_text(encoding="utf-8")
    versione = re.search(r"(?m)^pillow==([0-9][0-9A-Za-z.\-]*)", imgcheck)
    assert versione, (
        "requirements-imgcheck.txt non pinna più Pillow con `==`: sta fuori dal lock, quindi un "
        "range lo lascerebbe libero di cambiare da una notte all'altra")
    assert not re.search(r"(?mi)^pillow\s*[><~]", imgcheck), (
        "requirements-imgcheck.txt usa un range invece di `==`")
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}\b", imgcheck)) >= 1, (
        "requirements-imgcheck.txt ha perso gli `--hash`: con `--require-hashes` l'install "
        "fallirebbe, e senza `--require-hashes` non ci sarebbe più alcuna garanzia d'integrità")


def test_pillow_resta_fuori_dalla_catena_che_finisce_nell_exe():
    """L'altra metà della decisione: Pillow **non** deve entrare nelle dipendenze dichiarate.

    Rilievo GPT-5.5 (#300): «controllare che merge-simulation / build EXE non includano Pillow
    transitivamente». È il motivo per cui l'install sta nel workflow — ma senza un test la scelta
    resta un commento, e il primo che vorrà «sistemare» quell'anomalia sposterà la riga in
    `requirements-dev.txt` in buona fede, portandosi dietro il lock hashato dell'EXE e i due
    lockfile da rigenerare a mano.
    """
    for nome in ("requirements.in", "requirements.txt", "requirements-dev.txt",
                 "requirements-build.in", "requirements-build-linux.in"):
        testo = (_ROOT / nome).read_text(encoding="utf-8")
        righe = [r for r in testo.splitlines()
                 if r.strip() and not r.strip().startswith("#")]
        assert not any(re.match(r"^\s*pillow\b", r, re.I) for r in righe), (
            "%s dichiara Pillow: da lì scende in requirements-build.in (`-r requirements-dev.txt`) "
            "e quindi nel lock HASHATO dell'EXE, che va rigenerato a mano su runner Windows/Linux. "
            "Se la scelta è cambiata, aggiorna anche README e il commento in pr-checks.yml." % nome)


# I byte esatti delle otto schermate, così come sono state oscurate e verificate a mano.
# Lo `sha256` qui sotto gira sempre; il controllo sui pixel più in alto gira perché il job
# `unit` installa Pillow — e il test qui sopra pretende che continui a farlo.
_IMPRONTE = {
    "01-console-accesso.jpg":
        "380a18a6d290667033cf20edff9a70b840e44847f384881cc3b14533307b2f2f",
    "02-console-dashboard.jpg":
        "e16329f9a4018d827440cf7118f713cacced124499ed3573be5ba713379c0b50",
    "03-chiavi-api.jpg":
        "8cb95efbb712128624be691c70b07e79f285219b7d4a1b7ad491a97ef95ef0bc",
    "04-crea-chiave.jpg":
        "209f09af63fa9c688c9cd3a026c6bbfa6b90a672fd08794ad333cb2c25f6932a",
    "05-scadenza.jpg":
        "171dfac0ca8d4abb4bbc466e49f00e5bad6072269876476ffd87863208e99d24",
    "06-chiave-mostrata.jpg":
        "4cee9f653841edc1d77049c94ae1d1e891fc980cd88a7a365b7f8ac5f3bd121b",
    "07-fatturazione.jpg":
        "46172b7b9d06efb56b9eab7e45bf4090219bd2c44c3aacf9c835519e08cc2ed6",
    "08-aggiungi-crediti.jpg":
        "c09ee9a6ca31ac277c91769eb6e407de7c281a25cf4f9b5b6ed9572d2359b65d",
}


def test_le_schermate_sono_esattamente_quelle_oscurate():
    """Le immagini oscurate sono immutabili, e questo è il controllo che gira **in CI**.

    Il test sui pixel qui sopra apre il file con Pillow, e Pillow **non è fra le dipendenze di
    test** (`requirements-dev.txt` non lo nomina): in CI `importorskip` lo salta in silenzio.
    Una guardia che si salta senza dirlo protegge esattamente nulla — ed è il difetto contro
    cui è nato metà di questo file. Qui invece si confronta lo `sha256` dei byte con la stringa
    scritta sopra: `hashlib` è nella libreria standard, quindi gira **sempre**, ovunque.

    Cosa becca: la sostituzione di una schermata oscurata con l'originale scoperto, la
    ricompressione «innocua» che riscopre il testo sotto, l'aggiunta di una nona immagine mai
    ispezionata, la sparizione di una delle otto. Per cambiare una figura davvero si aggiorna
    l'impronta **nello stesso commit**: allora la modifica è deliberata e la si vede nel diff,
    che è il punto.
    """
    import hashlib

    cartella = _ROOT / "website" / "static" / "img" / "apikey"
    assert cartella.is_dir(), "la cartella delle schermate non c'è più"

    sul_disco = sorted(p.name for p in cartella.iterdir() if p.is_file())
    assert sul_disco == sorted(_IMPRONTE), (
        "le schermate sul disco non sono più quelle attese.\n"
        "sul disco: %s\nattese:    %s\n"
        "Se ne hai aggiunta o rimossa una di proposito, aggiorna _IMPRONTE nello stesso commit."
        % (sul_disco, sorted(_IMPRONTE)))

    for nome, atteso in sorted(_IMPRONTE.items()):
        letto = hashlib.sha256((cartella / nome).read_bytes()).hexdigest()
        assert letto == atteso, (
            "la schermata «%s» non è più quella oscurata e verificata.\n"
            "atteso %s\nletto  %s\n"
            "Se il cambio è voluto, RIGUARDA l'immagine prima di aggiornare l'impronta: su "
            "queste figure c'era una API key vera, e nessun reviewer AI guarda i .jpg."
            % (nome, atteso, letto))
