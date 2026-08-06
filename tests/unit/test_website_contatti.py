"""La pagina contatti deve arrivare a una casella che esiste.

Il form apre un `mailto:` precompilato. Se l'indirizzo è un placeholder, ogni richiesta di
supporto va nel vuoto — e nessuno se ne accorge, perché dal lato dell'utente il client email
si apre normalmente e il messaggio "parte". È un guasto silenzioso, quindi va tenuto da un test.
"""

import re
from pathlib import Path

from tests.conftest import dizionari_i18n_sito

_ROOT = Path(__file__).resolve().parents[2]
_PAGINA = _ROOT / "website" / "static" / "contatti.html"


_I18N = _ROOT / "website" / "static" / "i18n.js"


def _html() -> str:
    return _PAGINA.read_text(encoding="utf-8")


def _dizionari() -> dict:
    """I dizionari di traduzione di `i18n.js`, uno per lingua.

    Il lettore sta in `tests/conftest.py`: era scritto tre volte, in tre test, tutte e tre
    ancorate all'indentazione del file JS (Regola 3 — fonte unica). Si individuano le lingue
    dalla struttura invece di contarle: la policy del sito ne prevede altre (francese,
    rumeno…), e un test che si aspetta «esattamente 2» diventerebbe rosso senza che nulla sia
    rotto — e la reazione naturale a un test così è alzare il numero, cioè disattivarlo.
    """
    return dizionari_i18n_sito(_I18N)


def test_nessun_indirizzo_placeholder():
    """`example.com` è riservato dalla RFC 2606 proprio per gli esempi: nessuna casella lì
    riceve niente. Se ricompare, il form ha smesso di funzionare."""
    testo = _html()
    for placeholder in ("example.com", "example.org", "TODO(owner)"):
        assert placeholder not in testo, \
            "la pagina contatti contiene ancora il placeholder «%s»" % placeholder


def test_il_form_manda_a_un_indirizzo_ricomponibile():
    """L'indirizzo sta spezzato nel sorgente per non farsi raccogliere dagli spam bot: qui si
    verifica che i pezzi ci siano ancora e che ricomposti diano un indirizzo valido.

    Senza questo controllo, un refactor del JavaScript potrebbe lasciare `mailto:` con una
    stringa vuota: il client email si aprirebbe lo stesso, senza destinatario.
    """
    match = re.search(r'var supporto=\["([^"]+)","([^"]+)"\]\.join\("@"\)', _html())
    assert match, "l'indirizzo di supporto non è più ricomponibile dal sorgente"
    indirizzo = "%s@%s" % match.groups()
    assert re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", indirizzo), \
        "indirizzo di supporto non valido: %s" % indirizzo

    assert 'window.location.href="mailto:"+supporto' in _html(), \
        "il mailto non usa più la variabile con l'indirizzo: rischio destinatario vuoto"


def test_c_e_un_ripiego_se_il_client_email_non_si_apre():
    """Il `mailto:` funziona solo dove esiste un client email configurato.

    Dove non c'è — parecchi PC Windows, e chiunque usi solo webmail — cliccare non produce
    NIENTE. Senza il ripiego la pagina direbbe «si apre il tuo client email» e la richiesta di
    supporto si perderebbe in silenzio: l'utente crede di aver scritto, il proprietario non
    riceve nulla. L'indirizzo va quindi mostrato dopo l'invio, copiabile.
    """
    testo = _html()
    assert 'SITE_T("contact.fallback")' in testo, "manca il messaggio di ripiego"
    assert 'link.textContent=supporto' in testo, \
        "l'indirizzo di ripiego non è più visibile: resta solo un mailto che può non aprirsi"

    # e deve esistere in OGNI dizionario di lingua, non solo in italiano
    for lingua, dizionario in _dizionari().items():
        assert "contact.fallback" in dizionario, \
            "il ripiego non è tradotto in «%s» (l'italiano è il default nel markup)" % lingua


def test_l_indirizzo_non_compare_in_chiaro_nel_sorgente():
    """La forma completa `nome@dominio` non deve stare nell'HTML servito: è esattamente il
    pattern che i raccoglitori automatici cercano. Non è protezione forte — chi apre la
    pagina lo ricompone — ma evita la raccolta di massa."""
    testo = _html()
    trovati = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", testo)
    assert not trovati, "indirizzi email in chiaro nella pagina: %s" % trovati
