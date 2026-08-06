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


@pytest.mark.parametrize("lingua, parola", [("en", "English"), ("es", "inglés")])
def test_le_versioni_en_es_dichiarano_che_le_schermate_sono_in_inglese(lingua, parola):
    """`policy_lingue_sito.md` §4: il ripiego non è silenzioso.

    La Console Anthropic esiste **solo in inglese**: un utente spagnolo ha diritto di sapere
    perché le schermate non sono nella sua lingua, invece di pensare di aver sbagliato pagina.
    """
    valore = _dizionari()[lingua].get("apikey.shots.lang")
    assert valore, "«apikey.shots.lang» non è tradotta in «%s»" % lingua
    assert parola in valore, (
        "la nota sulle schermate in «%s» non dice che la Console è in inglese: %r"
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


def test_i_segnaposto_degli_screenshot_sono_dichiarati_e_contati():
    """Gli screenshot non ci sono ancora: li deve fare il proprietario (serve un account
    Anthropic, e ricostruirli sarebbe fabbricare schermate — §2 della policy).

    I riquadri di attesa sono **sei**, uno per passo, e ciascuno dice cosa ci andrà: sono al
    tempo stesso l'onestà verso il lettore e la lista di scatti da fare. Se un giorno le
    immagini arrivano e qualcuno ne innesta cinque su sei, questo test lo dice.
    """
    testo = _html()
    attese = re.findall(r'data-i18n="apikey\.s\d+\.attesa"', testo)
    immagini = re.findall(r'<img[^>]+src="/static/img/apikey/', testo)
    assert len(attese) + len(immagini) == 6, (
        "i passi con schermata sono 6: trovati %d segnaposto + %d immagini"
        % (len(attese), len(immagini)))
    if attese:
        for lingua in ("en", "es"):
            for chiave in re.findall(r'data-i18n="(apikey\.s\d+\.attesa)"', testo):
                assert _dizionari()[lingua].get(chiave), \
                    "il segnaposto «%s» non è tradotto in «%s»" % (chiave, lingua)
