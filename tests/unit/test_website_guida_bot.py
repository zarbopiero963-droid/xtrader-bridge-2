"""La guida «Crea il bot Telegram» — la pagina che un reviewer ha bloccato in pubblicazione.

Il rilievo (CodeRabbit sulla PR #277, registrato nella Issue #287): la pagina era pubblicata
**solo in italiano**, senza selettore di lingua e senza caricare `i18n.js`. Chi arrivava da un
sito in inglese leggeva una guida in italiano, senza modo di cambiarla — e i quattro
`data-i18n` che il footer già aveva erano **morti**, perché nessuno script li applicava.

Qui si controlla che la pagina sia davvero trilingue, e — più importante — si mette un gate di
classe che vale per **tutte** le pagine: ogni chiave `data-i18n` usata in un HTML deve avere una
traduzione in ogni dizionario. È il controllo che avrebbe visto il difetto originale mentre
nasceva, invece che due PR dopo.

C'è anche una regola del sito che è facile violare senza accorgersene
(`docs/policy_lingue_sito.md`): **il testo si traduce, gli screenshot no**. Gli screenshot di
questa guida sono quelli veri dell'app Telegram in **italiano**, quindi le versioni EN/ES devono
(a) dirlo, e (b) citare le etichette **verbatim in italiano**, con la traduzione fra parentesi.
Tradurre «Amministratori» in «Administrators» farebbe cercare all'utente un pulsante che sullo
schermo non esiste.
"""

import re
from pathlib import Path

import pytest

from tests.conftest import _testo_js, dizionari_i18n_sito

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "website" / "static"
_GUIDA = _STATIC / "guida-bot.html"
_I18N = _STATIC / "i18n.js"

_PAGINE = sorted(p.name for p in _STATIC.glob("*.html"))
if not _PAGINE:  # pragma: no cover - scatta solo se la cartella sparisce
    raise RuntimeError("nessuna pagina in website/static: il gate non coprirebbe nulla")


def _dizionari() -> dict:
    """`{lingua: {chiave: valore}}`. Il lettore sta in `tests/conftest.py`: era scritto tre
    volte in tre test, tutte e tre ancorate all'indentazione del file JS (Regola 3)."""
    return dizionari_i18n_sito(_I18N)


def _valore(dizionario: dict, chiave: str):
    """Il valore tradotto per una chiave, o `None` se la chiave non c'è."""
    return dizionario.get(chiave)


def _chiavi(pagina: str) -> set:
    html = (_STATIC / pagina).read_text(encoding="utf-8")
    return set(re.findall(r'data-i18n(?:-ph)?="([^"]+)"', html))


@pytest.mark.parametrize("pagina", _PAGINE)
def test_ogni_chiave_data_i18n_ha_una_traduzione_in_ogni_lingua(pagina):
    """Il gate di classe: una chiave nel markup senza voce nel dizionario è testo morto.

    Non fa rumore e non rompe niente — la pagina resta semplicemente in italiano per tutti,
    che è esattamente il difetto che ha fatto bloccare la guida bot. Vale per ogni pagina
    presente e futura, perché il parametro è la cartella.
    """
    dizionari = _dizionari()
    for chiave in sorted(_chiavi(pagina)):
        for lingua, dizionario in dizionari.items():
            valore = _valore(dizionario, chiave)
            assert valore is not None, \
                "%s usa «%s» ma «%s» non la traduce" % (pagina, chiave, lingua)
            assert len(valore.strip()) >= 2, \
                "«%s» in «%s» è vuota: %r" % (chiave, lingua, valore)


def test_la_guida_bot_e_trilingue_come_le_altre():
    """Selettore + script. Senza lo script, i `data-i18n` che la pagina già aveva erano morti."""
    html = _GUIDA.read_text(encoding="utf-8")
    assert "/static/i18n.js" in html, \
        "guida-bot.html non carica i18n.js: nessuna traduzione verrebbe applicata"
    assert 'class="lang-sw"' in html, "guida-bot.html non ha il selettore di lingua"
    for lingua in ("it", "en", "es"):
        assert 'data-lang="%s"' % lingua in html, "manca il pulsante «%s»" % lingua


def _corpo_main(html: str) -> str:
    match = re.search(r"<main[^>]*>(.*?)</main>", html, re.S)
    assert match, "guida-bot.html non ha un <main>"
    return match.group(1)


@pytest.mark.parametrize("tag", ["h1", "h2", "p", "figcaption"])
def test_nessun_testo_della_guida_resta_fuori_dalla_traduzione(tag):
    """Ogni blocco di prosa dentro `<main>` deve portare la sua chiave.

    Il modo in cui questa pagina è nata monca è banale: si traduce il grosso e si dimentica una
    didascalia o l'avviso in fondo. Contare i tag invece di fidarsi rende impossibile
    dimenticarne uno in silenzio.
    """
    corpo = _corpo_main(_GUIDA.read_text(encoding="utf-8"))
    aperture = re.findall(r"<%s\b[^>]*>" % tag, corpo)
    assert aperture, "nessun <%s> in <main>: la pagina è cambiata di struttura" % tag
    orfani = [a for a in aperture if "data-i18n" not in a]
    assert not orfani, (
        "%d <%s> senza data-i18n nella guida: resterebbero in italiano in EN/ES → %s"
        % (len(orfani), tag, orfani[:3]))


def test_la_guida_non_pubblica_note_interne_di_lavorazione():
    """C'era, davvero, un riquadro «Nota di lavorazione (non va in pubblicazione)» — pubblicato.

    Diceva quali screenshot erano ricostruiti e che le traduzioni sarebbero arrivate dopo
    l'approvazione dei testi: appunti fra me e il proprietario, serviti a un utente qualsiasi su
    internet. La trasparenza sugli screenshot va detta, ma **rivolta all'utente**, non copiando
    una nota di cantiere.
    """
    html = _GUIDA.read_text(encoding="utf-8")
    for frase in ("non va in pubblicazione", "Nota di lavorazione",
                  "dopo l'approvazione dei testi"):
        assert frase not in html, \
            "guida-bot.html pubblica ancora una nota interna: «%s»" % frase


def test_le_versioni_en_es_dichiarano_che_gli_screenshot_sono_in_italiano():
    """`policy_lingue_sito.md` §4: «il fallback non è silenzioso».

    Gli screenshot sono l'app Telegram reale del proprietario, in italiano. Un utente inglese
    ha diritto di sapere *perché* le schermate non sono nella sua lingua, invece di credere di
    avere sbagliato pagina.
    """
    dizionari = _dizionari()
    atteso = {"en": "Italian", "es": "italiano"}
    for lingua, parola in atteso.items():
        valore = _valore(dizionari[lingua], "guida.shots.lang")
        assert valore, "«guida.shots.lang» non è tradotta in «%s»" % lingua
        assert parola in valore, (
            "la nota sugli screenshot in «%s» non dice che l'interfaccia mostrata è in "
            "italiano: %r" % (lingua, valore))


@pytest.mark.parametrize("etichetta", ["Amministratori", "Aggiungi amministratore"])
def test_le_etichette_telegram_restano_verbatim_anche_in_en_es(etichetta):
    """`policy_lingue_sito.md` §3, il punto che si sbaglia più facilmente.

    Se il testo inglese dicesse «tap Administrators» ma lo screenshot mostra
    «Amministratori», l'utente cercherebbe un pulsante che non esiste. L'etichetta si cita
    verbatim; la traduzione va fra parentesi.
    """
    dizionari = _dizionari()
    for lingua in ("en", "es"):
        blocco = dizionari[lingua]
        chiavi_guida = [c for c in blocco if c.startswith("guida.")]
        assert chiavi_guida, "«%s» non ha nessuna stringa della guida" % lingua
        testo = " ".join(blocco[c] for c in chiavi_guida)
        assert etichetta in testo, (
            "in «%s» l'etichetta Telegram «%s» non compare verbatim: l'utente non troverebbe "
            "il comando sullo schermo" % (lingua, etichetta))


def test_il_token_resta_descritto_come_una_password_in_ogni_lingua():
    """L'avviso più importante della pagina. Se si perde nella traduzione, si perde in tre
    quarti dei lettori: chi possiede il token controlla il bot."""
    dizionari = _dizionari()
    for lingua, atteso in (("en", "revoke"), ("es", "revoke")):
        valore = _valore(dizionari[lingua], "guida.warn.token.p")
        assert valore, "«guida.warn.token.p» non è tradotta in «%s»" % lingua
        # NB: il messaggio evita di proposito la sequenza «token» + due punti. La redazione
        # anti-segreto dei workflow di review la sostituisce con `token=[REDACTED]`, portandosi
        # via il segnaposto `%r` — e i due reviewer forti hanno segnalato tre volte, in tre
        # giri diversi, un format string rotto che nel file non c'è mai stato. Costava ~$0.85
        # a giro. Il messaggio dice la stessa cosa senza innescare la redazione.
        assert atteso in valore.lower(), (
            "la versione «%s» dell'avviso non spiega più come revocarlo: %r" % (lingua, valore))


def test_il_lettore_dei_dizionari_regge_una_riformattazione(tmp_path):
    """Il lettore non deve dipendere da come è formattato il JavaScript.

    Rilievo GPT-5.5 sulla #289: le tre copie del parser erano ancorate a «quattro spazi di
    indentazione», quindi un `prettier` sul file avrebbe fatto fallire i test **pur con le
    traduzioni giuste** — il modo peggiore di fallire, perché manda a cercare il problema nel
    posto sbagliato. Qui il file viene riscritto su una riga sola, con graffe dentro le
    stringhe: se il lettore regge questo, regge una riformattazione qualsiasi.
    """
    finto = tmp_path / "i18n.js"
    finto.write_text(
        '(function(){var T={en:{"a.x":"uno {non una graffa vera}","a.y":"due"},'
        'es:{"a.x":"uno","a.y":"dos"}};})();',
        encoding="utf-8")
    letti = dizionari_i18n_sito(finto)
    assert sorted(letti) == ["en", "es"], letti
    assert letti["en"]["a.x"] == "uno {non una graffa vera}"
    assert letti["es"]["a.y"] == "dos"


@pytest.mark.parametrize("grezzo, atteso", [
    (r'class=\"num\"', 'class="num"'),          # il caso che serve davvero alle traduzioni
    (r'a\u00e8b', "aèb"),                        # accenti scritti come codepoint
    (r'a\tb', "a\tb"),                            # tabulazione
    (r'a\/b', "a/b"),                            # slash sfuggita, legale in JSON
    (r"non e\' JSON", "non e' JSON"),            # escape che JSON NON conosce: ripiego a mano
])
def test_le_sequenze_di_escape_diventano_il_testo_che_si_vede(grezzo, atteso):
    """Il sorgente JS non è il testo: `\\"` a schermo è `"`.

    Gestivo a mano solo tre escape e ne avevo dimenticati almeno quattro (rilievo GPT-5.5 sulla
    #289). Adesso il grosso lo scioglie `json.loads`, e resta un ripiego per gli escape che JS
    ammette e JSON no — perché un test che esplode su una virgoletta sfuggita è peggio del
    problema che vuole prevenire.
    """
    assert _testo_js(grezzo) == atteso


def test_il_lettore_ignora_stringhe_e_commenti_che_sembrano_dizionari(tmp_path):
    """Un `xx: {` dentro una stringa o un commento non è un dizionario.

    Rilievo Claude Fable 5 sulla #289: la ricerca dei blocchi girava sul sorgente grezzo, quindi
    una frase tradotta che contenesse `es: {` — o un commento di esempio — avrebbe fatto partire
    un blocco inesistente, sfasando tutto quello che viene dopo. Ora le posizioni si cercano su
    una maschera in cui stringhe e commenti sono spazi.
    """
    finto = tmp_path / "i18n.js"
    finto.write_text(
        '// esempio nel commento: es: { "finta": "roba" }\n'
        'var T = {\n'
        '  en: {"vero.a": "scrivi es: { così", "vero.b": "due"},\n'
        '  /* blocco: fr: { "mai": "letta" } */\n'
        '  es: {"vero.a": "uno", "vero.b": "dos"}\n'
        '};', encoding="utf-8")
    letti = dizionari_i18n_sito(finto)
    assert sorted(letti) == ["en", "es"], letti
    assert "finta" not in letti["en"] and "mai" not in letti.get("fr", {})
    assert letti["en"]["vero.a"] == "scrivi es: { così"


def test_anche_le_chiavi_hanno_gli_escape_sciolti(tmp_path):
    """Una chiave con `\\u2026` nel sorgente è la stessa chiave che l'HTML scrive per esteso.

    Se il lettore la lasciasse grezza, il gate di classe direbbe «questa chiave non è tradotta»
    su una chiave che invece c'è — e si cercherebbe il problema nel dizionario invece che nel
    lettore (rilievo Claude Fable 5 sulla #289).
    """
    finto = tmp_path / "i18n.js"
    finto.write_text('var T={en:{"a\\u002eb":"x","c":"y"}};', encoding="utf-8")
    assert dizionari_i18n_sito(finto)["en"]["a.b"] == "x"


def test_i18n_non_usa_i_costrutti_che_il_lettore_non_sa_leggere():
    """La garanzia scritta nel docstring del lettore, resa un gate.

    `_maschera_codice` dichiara di non riconoscere i *regex literal* JS, e si difende dicendo
    che «i18n.js non ne ha — verificato». Ma «verificato» è una fotografia: vale il giorno che
    l'ho scritto (rilievo GPT-5.5 sulla #289). Se domani qualcuno mettesse una regex o un
    template literal in `i18n.js`, il lettore inizierebbe a sbagliare in silenzio e il docstring
    continuerebbe a giurare il contrario.

    Questo test è quella promessa trasformata in controllo: il giorno che il file cambia natura,
    è rosso **qui**, con scritto perché — invece che rosso in un test di traduzione qualsiasi,
    dove nessuno penserebbe di guardare il parser.
    """
    testo = _I18N.read_text(encoding="utf-8")
    assert "`" not in testo, (
        "i18n.js ora usa i template literal: il lettore in tests/conftest.py li tratta come "
        "stringhe semplici e non valuta `${...}` — vanno gestiti prima di usarli qui")
    # una regex literal si riconosce da un `/` che apre dopo `=`, `(` o `,` e non è un commento
    sospette = re.findall(r"[=(,]\s*/(?![/*])[^\n]*?/[gimsuy]*", testo)
    assert not sospette, (
        "i18n.js ora contiene quelle che sembrano regex literal: %r — il lettore non le "
        "riconosce e potrebbe scambiarne il contenuto per un commento (limite dichiarato in "
        "`_maschera_codice`)" % sospette[:2])
