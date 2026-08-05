"""La pagina contatti deve arrivare a una casella che esiste.

Il form apre un `mailto:` precompilato. Se l'indirizzo è un placeholder, ogni richiesta di
supporto va nel vuoto — e nessuno se ne accorge, perché dal lato dell'utente il client email
si apre normalmente e il messaggio "parte". È un guasto silenzioso, quindi va tenuto da un test.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PAGINA = _ROOT / "website" / "static" / "contatti.html"


def _html() -> str:
    return _PAGINA.read_text(encoding="utf-8")


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


def test_l_indirizzo_non_compare_in_chiaro_nel_sorgente():
    """La forma completa `nome@dominio` non deve stare nell'HTML servito: è esattamente il
    pattern che i raccoglitori automatici cercano. Non è protezione forte — chi apre la
    pagina lo ricompone — ma evita la raccolta di massa."""
    testo = _html()
    trovati = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", testo)
    assert not trovati, "indirizzi email in chiaro nella pagina: %s" % trovati
