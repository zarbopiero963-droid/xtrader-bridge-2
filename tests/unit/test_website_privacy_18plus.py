"""Le due pagine che il sito non poteva pubblicare senza: privacy e gioco responsabile.

Non sono pagine di contorno. La privacy dichiara che il chatbot **manda i messaggi degli
utenti ad Anthropic**: se quella frase sparisse, il sito raccoglierebbe dati senza dirlo. E la
pagina 18+ è l'unico posto dove sta scritto, per esteso, che BetRelay **non fa vincere nessuno**
— su un sito che parla di software di scommesse, è la differenza fra uno strumento tecnico e una
promessa.

Un test che verificasse solo «la pagina risponde 200» non proteggerebbe niente di tutto questo:
qui si controlla che ci siano le affermazioni che contano, in tutte e tre le lingue.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "website" / "static"
_PRIVACY = _STATIC / "privacy.html"
_RESP = _STATIC / "gioco-responsabile.html"
_I18N = _STATIC / "i18n.js"

# Ogni pagina HTML del sito deve linkare le due pagine e mostrare il richiamo 18+.
_PAGINE = sorted(p.name for p in _STATIC.glob("*.html"))
# NON un `assert`: `python -O` li rimuove, e questa riga esiste proprio per impedire che
# il gate diventi un no-op silenzioso. Una guardia che sparisce con un flag
# dell'interprete è la stessa cosa che sta cercando di prevenire.
if not _PAGINE:  # pragma: no cover - scatta solo se la cartella sparisce
    raise RuntimeError("nessuna pagina in website/static: il gate non coprirebbe nulla")


def _dizionari() -> dict:
    """I dizionari di traduzione, uno per lingua (stessa lettura di test_website_contatti)."""
    testo = _I18N.read_text(encoding="utf-8")
    fuori = {}
    for match in re.finditer(r"^    ([a-z]{2}): \{$(.*?)^    \},?$", testo, re.M | re.S):
        fuori[match.group(1)] = match.group(2)
    assert fuori, "nessun dizionario di lingua trovato in i18n.js"
    return fuori


def test_le_due_pagine_esistono():
    assert _PRIVACY.is_file(), "manca la pagina privacy"
    assert _RESP.is_file(), "manca la pagina gioco responsabile"


def test_la_privacy_dichiara_che_i_messaggi_vanno_ad_anthropic():
    """È il punto per cui questa pagina esiste. Il chatbot inoltra il testo dell'utente a un
    fornitore terzo: taciuto, sarebbe una raccolta di dati non dichiarata."""
    testo = _PRIVACY.read_text(encoding="utf-8")
    assert "Anthropic" in testo, "la privacy non nomina più il destinatario dei messaggi"
    assert "chatbot" in testo.lower()


def test_la_privacy_descrive_gli_altri_tre_flussi_di_dati():
    """IP per il rate limit, form contatti, e la lingua in localStorage: sono gli unici altri
    dati che il sito tocca (verificati in `website/main.py`). Se uno sparisce dalla pagina,
    il sito starebbe facendo qualcosa che non dichiara."""
    testo = _PRIVACY.read_text(encoding="utf-8")
    for atteso, cosa in (("IP", "indirizzo IP del rate limit"),
                         ("localStorage", "la lingua salvata nel browser"),
                         ("Railway", "il fornitore che ospita e registra i log")):
        assert atteso in testo, "la privacy non parla più di: %s" % cosa


def test_la_privacy_dichiara_il_trasferimento_fuori_dalla_ue():
    """Anthropic è una società statunitense: i messaggi della chat escono dallo Spazio
    Economico Europeo. È un fatto, non un'opinione, ed è dei pochi che un utente ha diritto
    di sapere *prima* di scrivere qualcosa in quella chat (rilievo CodeRabbit sulla #284)."""
    testo = _PRIVACY.read_text(encoding="utf-8")
    assert "Spazio Economico Europeo" in testo, "manca la dichiarazione sul trasferimento"
    assert "statunitense" in testo, "non è detto dove ha sede il fornitore del modello"


def test_la_privacy_dice_per_quanto_restano_i_dati():
    """«Quali dati» senza «per quanto tempo» è mezza informazione: sono i periodi di
    conservazione, e qui sono verificabili nel codice (chat: mai; IP: un'ora)."""
    testo = _PRIVACY.read_text(encoding="utf-8")
    assert "Per quanto tempo" in testo
    assert "un'ora" in testo, "non è più dichiarata la durata del conteggio per IP"


def test_la_privacy_distingue_il_sito_dal_programma():
    """Il programma gira sul PC dell'utente e non manda nulla a noi. Confondere le due cose
    farebbe credere che il bridge telefoni a casa — cosa che non fa, ed è un punto di fiducia
    su cui l'intero progetto si regge."""
    testo = _PRIVACY.read_text(encoding="utf-8")
    assert "keyring" in testo, "manca la spiegazione su dove sta il token (sul PC dell'utente)"
    assert re.search(r"non manda niente a noi|non ci manda", testo), \
        "la privacy non dice più che il programma non invia dati a noi"


def test_la_pagina_18plus_dice_cosa_betrelay_NON_fa():
    """La frase che conta davvero: non piazza scommesse, non dà pronostici, non fa vincere.
    Senza, la pagina diventa un adempimento formale invece di un'informazione."""
    testo = _RESP.read_text(encoding="utf-8")
    for atteso in ("non piazza scommesse", "non ti fa vincere", "garantisce vincite"):
        assert atteso in testo, "la pagina 18+ non dice più «%s»" % atteso


def test_la_pagina_18plus_da_contatti_di_aiuto_reali():
    """Un numero sbagliato o assente rende la pagina inutile proprio a chi ne ha bisogno."""
    testo = _RESP.read_text(encoding="utf-8")
    assert "800 558822" in testo, "manca il Telefono Verde dell'Istituto Superiore di Sanità"
    assert "Ser.D." in testo, "mancano i servizi pubblici per le dipendenze"
    assert "giocatorianonimi.org" in testo


def test_la_pagina_18plus_dice_che_l_automazione_accelera_il_rischio():
    """È il rischio specifico di QUESTO software, quello che un avviso generico non copre."""
    testo = _RESP.read_text(encoding="utf-8")
    assert "18 anni" in testo, "manca il divieto ai minori"
    assert "Simulazione" in testo, "non spiega più perché il programma parte in Simulazione"


def _footer(pagina: str) -> str:
    """Il blocco `<footer>…</footer>` della pagina, non tutto il documento.

    Cercare in tutto l'HTML rendeva il controllo compiacente: sarebbe passato con i link in
    un menu, in un commento o in una stringa JavaScript qualsiasi. Il richiamo 18+ e i due
    link devono stare **nel footer**, che è il posto che l'utente trova su ogni pagina.
    """
    html = (_STATIC / pagina).read_text(encoding="utf-8")
    match = re.search(r"<footer[^>]*>(.*?)</footer>", html, re.S)
    assert match, "%s non ha un blocco <footer>" % pagina
    return match.group(1)


@pytest.mark.parametrize("pagina", _PAGINE)
def test_ogni_pagina_richiama_il_18plus_e_linka_le_due_pagine(pagina):
    """Vale per TUTTE le pagine, comprese quelle future: il parametro è la lista dei file su
    disco. Una pagina nuova senza il richiamo fa fallire la suite da sola — esattamente come
    per il disclaimer di non-affiliazione."""
    footer = _footer(pagina)
    assert "18+" in footer, "%s non richiama il 18+ nel footer" % pagina
    assert "/gioco-responsabile" in footer, \
        "%s non linka il gioco responsabile dal footer" % pagina
    assert "/privacy" in footer, "%s non linka la privacy dal footer" % pagina


# Le pagine trilingui. Escluse di proposito: `demo.html`, `demo-xtrader.html` e
# `guida-bot.html`, che sono ancora solo in italiano — è un debito tracciato nella roadmap
# (S8), non una dimenticanza. Elencarle a mano invece di leggere la cartella serve proprio a
# questo: quando saranno tradotte, aggiungerle qui è il modo di dichiararlo.
_TRILINGUI = ("index.html", "faq.html", "contatti.html", "documentazione.html",
              "privacy.html", "gioco-responsabile.html")


@pytest.mark.parametrize("pagina", _TRILINGUI)
def test_ogni_pagina_trilingue_ha_il_selettore_di_lingua(pagina):
    """Le traduzioni senza il selettore non servono a nulla.

    È successo davvero: privacy e gioco-responsabile sono nate con tutte le stringhe tradotte
    in `i18n.js` ma senza i pulsanti IT/EN/ES nella nav, quindi un utente inglese vedeva la
    pagina in italiano senza alcun modo di cambiarla. Le traduzioni c'erano, erano irraggiungibili.
    """
    html = (_STATIC / pagina).read_text(encoding="utf-8")
    assert 'class="lang-sw"' in html, "%s non ha il selettore di lingua" % pagina
    for lingua in ("it", "en", "es"):
        assert 'data-lang="%s"' % lingua in html, \
            "%s non ha il pulsante per «%s»" % (pagina, lingua)
    assert "/static/i18n.js" in html, "%s non carica i18n.js: nulla verrebbe tradotto" % pagina


@pytest.mark.parametrize("chiave", ["footer.age", "footer.privacy", "footer.responsible",
                                    "privacy.h1", "privacy.chat.p", "privacy.detail.transfer",
                                    "privacy.detail.keep", "resp.h1", "resp.what.not",
                                    "resp.help.iss"])
def test_i_contenuti_nuovi_sono_tradotti_in_ogni_lingua(chiave):
    """Regola del sito: il testo si traduce in tutte le lingue attive (l'italiano è il default
    nel markup). Una pagina legale visibile solo agli italiani non protegge gli altri utenti."""
    for lingua, dizionario in _dizionari().items():
        match = re.search(r'"%s":\s*"((?:[^"\\]|\\.)*)"' % re.escape(chiave), dizionario)
        assert match, "«%s» non è tradotta in «%s»" % (chiave, lingua)
        # il VALORE, non solo la chiave: `"privacy.h1": ""` passerebbe un controllo che
        # cerca il nome, e la pagina mostrerebbe uno spazio vuoto al posto del titolo
        valore = match.group(1).strip()
        assert len(valore) >= 3, \
            "«%s» in «%s» è vuota o troppo corta: %r" % (chiave, lingua, valore)


def test_il_numero_verde_e_uguale_in_tutte_le_lingue():
    """Un numero di aiuto tradotto male è peggio di nessun numero: qui si verifica che le
    versioni EN/ES riportino lo stesso recapito italiano, non una traduzione creativa."""
    for lingua, dizionario in _dizionari().items():
        assert "800 558822" in dizionario, \
            "il numero del Telefono Verde manca o è diverso in «%s»" % lingua
