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
    di schermate è metà del contenuto."""
    html = _html()
    immagini = re.findall(r'<img[^>]+>', html)
    assert immagini, "la guida non ha più nessuna immagine"
    for tag in immagini:
        src = re.search(r'src="([^"]+)"', tag).group(1)
        percorso = _ROOT / "website" / src.lstrip("/")
        assert percorso.is_file(), "immagine mancante sul disco: %s" % src
        alt = re.search(r'alt="([^"]*)"', tag)
        assert alt and len(alt.group(1)) > 15, "alt assente o troppo corto: %s" % src


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
    valori = list(area.getdata())
    media = sum(valori) / len(valori)
    massimo = max(valori)
    assert media < 60, (
        "l'area dove stava la chiave non è più scura (media %.1f): sembra scoperta. Se la "
        "chiave è tornata visibile va REVOCATA su platform.claude.com, non solo ricoperta"
        % media)
    assert massimo < 140, (
        "nell'area della chiave ci sono pixel chiari (max %d): probabile testo leggibile" % massimo)
