"""Disclaimer di non-affiliazione e policy lingue del sito (regola permanente).

Perché questi test esistono: il sito **nomina XTrader e Betting Toolkit ovunque** e ne mostra le
schermate. Senza il disclaimer, una sezione intitolata «BetRelay for BETTINGTOOLKIT.COM» si legge
come un prodotto ufficiale del network — cosa che BetRelay non è. È l'unico punto del sito dove
un'omissione non produce un bug visibile ma un'affermazione falsa, quindi va tenuto da un test e
non dalla memoria di chi aggiunge la prossima pagina.

La regola sulle lingue (testo tradotto sempre, screenshot solo IT/EN/ES con fallback EN) sta in
`docs/policy_lingue_sito.md` e in `CLAUDE.md`: qui si verifica che entrambi la contengano ancora.
"""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "website" / "static"
_POLICY = _ROOT / "docs" / "policy_lingue_sito.md"
_CLAUDE = _ROOT / "CLAUDE.md"

_PAGINE = sorted(p.name for p in _STATIC.glob("*.html"))

# I due soggetti da cui BetRelay deve dichiararsi indipendente.
_SOGGETTI = ("TradingSportivo", "Betting Toolkit")


@pytest.mark.parametrize("pagina", _PAGINE)
def test_ogni_pagina_dichiara_la_non_affiliazione(pagina):
    """Vale per TUTTE le pagine, comprese quelle future: il parametro è la lista dei file su
    disco, quindi una pagina nuova senza disclaimer fa fallire la suite da sola."""
    html = (_STATIC / pagina).read_text(encoding="utf-8")
    assert "non è affiliato" in html, "%s non dichiara la non-affiliazione" % pagina
    for soggetto in _SOGGETTI:
        assert soggetto in html, "%s non nomina «%s» nel disclaimer" % (pagina, soggetto)


def _clausola_affiliazione(testo: str) -> str:
    """La prima frase del disclaimer — quella che dice «non siamo affiliati a…».

    Va isolata dalla seconda («i marchi appartengono ai rispettivi proprietari»): entrambe
    nominano gli stessi soggetti, quindi cercarli nell'intero paragrafo non distinguerebbe un
    disclaimer completo da uno che si è dimenticato metà dei prodotti.
    """
    piatto = " ".join(testo.split())
    return piatto.split(". ")[0]


@pytest.mark.parametrize("pagina", _PAGINE)
def test_il_disclaimer_nomina_entrambi_i_prodotti(pagina):
    """Nominare solo TradingSportivo non basta: gli utenti Betting Toolkit devono leggere il
    nome del LORO software nella clausola di non-affiliazione, altrimenti non li riguarda."""
    html = (_STATIC / pagina).read_text(encoding="utf-8")
    # si parte DAL match, senza guardare indietro: su `demo.html` il footer contiene già una
    # frase prima del disclaimer, e includerla farebbe finire il taglio nel punto sbagliato
    inizio = html.index("non è affiliato")
    clausola = _clausola_affiliazione(html[inizio:inizio + 400])
    for soggetto in ("TradingSportivo", "XTrader", "Betting Toolkit", "BETTINGTOOLKIT"):
        assert soggetto in clausola, \
            "%s: «%s» non compare nella clausola di non-affiliazione" % (pagina, soggetto)


@pytest.mark.parametrize("lang", ("en", "es"))
def test_il_disclaimer_e_tradotto(lang):
    """Un disclaimer che resta in italiano per un utente inglese non è un disclaimer."""
    i18n = (_STATIC / "i18n.js").read_text(encoding="utf-8")
    blocco = i18n[i18n.index("    %s: {" % lang):]
    blocco = blocco[:blocco.index("\n    }")]
    assert '"footer.independent"' in blocco, "manca la traduzione %s del disclaimer" % lang
    # `split` e non `index("\n")`: la voce può essere l'ULTIMA del blocco, quindi senza newline
    riga = blocco[blocco.index('"footer.independent"'):].split("\n")[0]
    clausola = _clausola_affiliazione(riga)
    for soggetto in ("TradingSportivo", "XTrader", "Betting Toolkit", "BETTINGTOOLKIT"):
        assert soggetto in clausola, \
            "la traduzione %s non nomina «%s» nella clausola di non-affiliazione" % (lang, soggetto)


def test_la_policy_lingue_esiste_ed_e_completa():
    testo = _POLICY.read_text(encoding="utf-8")
    for punto in ("Il testo si traduce in tutte le lingue del sito. Gli screenshot no",
                  "INGLESE", "verbatim", "BETTINGTOOLKIT.COM", "non-affiliazione"):
        assert punto in testo, "la policy lingue non copre più «%s»" % punto


def test_la_regola_e_anche_in_claude_md():
    """La policy dettagliata sta in docs/, ma la regola in breve deve restare nel file che
    ogni agente legge per primo: se vive solo in docs/ prima o poi qualcuno non la vedrà."""
    testo = _CLAUDE.read_text(encoding="utf-8")
    assert "REGOLA LINGUE SITO E SCREENSHOT" in testo
    assert "policy_lingue_sito.md" in testo, "CLAUDE.md non rimanda più alla policy completa"
