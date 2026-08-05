"""Demo interattiva della finestra Segnali di XTrader (W9.5, issue #229).

La demo replica una finestra di un programma di terzi a partire dagli screenshot reali. Il rischio
non è che si rompa il codice: è che **diverga dall'originale** senza che nessuno se ne accorga —
etichette riscritte a memoria, una colonna persa, il contratto CSV cambiato nel bridge e non qui.
Una demo che mostra una finestra che non esiste è peggio di nessuna demo, perché l'utente la usa
per orientarsi nel programma vero.

Questi test ancorano la demo a due fonti di verità: le **etichette verbatim** viste negli
screenshot `varie/02`, `varie/03`, `varie/04`, e `csv_writer.CSV_HEADER` per le colonne lette
dal file.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PAGE = _ROOT / "website" / "static" / "demo-xtrader.html"


def _html() -> str:
    return _PAGE.read_text(encoding="utf-8")


# Colonne dell'elenco FONTI, dallo screenshot varie/02.
_COL_FONTI = ("Nome Servizio", "Nome File", "Url", "Ricarica Automaticamente",
              "Intervallo", "Escludi N.V.", "Riconoscimento Sel", "Ultimo Agg.")

# Etichette della dialog «Fonte Segnali», dagli screenshot varie/03 e varie/04.
_DIALOG = ("Fonte Segnali", "Nome Servizio", "URL", "Nome File",
           "Aggiorna automaticamente ogni", "Escludi automaticamente segnali non validati",
           "Riconoscimento selezioni", "Lingua Palinsesto")


@pytest.mark.parametrize("etichetta", _COL_FONTI)
def test_colonne_elenco_fonti_verbatim(etichetta):
    assert etichetta in _html(), "colonna «%s» assente: la demo non combacia con varie/02" % etichetta


@pytest.mark.parametrize("etichetta", _DIALOG)
def test_dialog_fonte_segnali_verbatim(etichetta):
    assert etichetta in _html(), "etichetta «%s» assente: la dialog non combacia con varie/03-04" % etichetta


def test_fonti_predefinite_presenti():
    """«Segnali Importati» e «Segnali Creati» esistono in ogni installazione e non sono
    eliminabili: se sparissero dalla demo, l'utente non riconoscerebbe la finestra."""
    html = _html()
    assert "Segnali Importati" in html and "Segnali Creati" in html


def test_le_tre_lingue_palinsesto():
    """Le lingue della fonte sono esattamente IT/EN/ES, le stesse del bridge (issue #3)."""
    html = _html()
    blocco = html[html.index('id="fLang"'):]
    blocco = blocco[:blocco.index("</select>")]
    lingue = set(re.findall(r">(\w+)</option>", blocco))
    assert lingue == {"IT", "EN", "ES"}, "lingue della fonte errate: %s" % sorted(lingue)


def test_i_due_metodi_di_riconoscimento():
    """Il manuale ne prevede due e SOLO due: se ne comparisse un terzo sarebbe inventato."""
    html = _html()
    blocco = html[html.index('id="fRic"'):]
    blocco = blocco[:blocco.index("</select>")]
    opzioni = re.findall(r">([^<]+)</option>", blocco)
    assert opzioni == ["MarketId, SelectionId", "EventName,MarketType,SelectionName"], opzioni


def test_colonne_lette_dal_csv_coerenti_col_contratto():
    """Nell'elenco segnali le colonne fra parentesi quadre sono quelle LETTE dal file: devono
    essere un sottoinsieme esatto delle colonne che il bridge scrive davvero. Se il contratto CSV
    cambia e la demo no, la demo mente su cosa arriva a XTrader."""
    from xtrader_bridge.csv_writer import CSV_HEADER

    quadre = set(re.findall(r"<th>\[(\w+)\]</th>", _html()))
    assert quadre, "nessuna colonna fra parentesi quadre: elenco segnali non replicato"
    fuori = sorted(quadre - set(CSV_HEADER))
    assert not fuori, "la demo mostra colonne che il bridge non scrive: %s" % fuori


def test_entrambi_gli_esiti_sono_rappresentati():
    """Verde e rosso sono il punto della demo: se sparisse uno dei due stati resterebbe una
    replica statica. Le classi sono composte a runtime (`"dot " + (valido ? "ok" : "ko")`),
    quindi si verificano le regole CSS e il ramo che le sceglie, non una stringa nel markup."""
    html = _html()
    assert ".dot.ok{" in html and ".dot.ko{" in html, "manca lo stile di uno dei due esiti"
    assert 'class="dot ' in html, "l'icona di stato non viene più costruita"
    assert re.search(r'r\.valido\s*\?\s*"ok"\s*:\s*"ko"', html), \
        "il codice non assegna più l'icona in base alla validità del segnale"
    assert "Solo Validi" in html, "manca il filtro che nasconde i non validi"


def test_dichiara_cosa_e_simulato():
    """Onestà: la validazione qui è finta, il programma vero interroga il palinsesto Betfair.
    Senza questo avviso la demo si spaccia per una prova reale."""
    html = _html()
    assert "finto" in html and "palinsesto Betfair" in html


def test_disclaimer_di_non_affiliazione():
    assert "non è affiliato" in _html() and "TradingSportivo" in _html()


def test_la_rotta_serve_la_demo():
    pytest.importorskip(
        "fastapi",
        reason="FastAPI sta in website/requirements.txt, non fra le dipendenze del bridge: "
               "le verifiche sul contenuto della pagina girano comunque",
    )
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("betrelay_site_demo", _ROOT / "website" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    from fastapi.testclient import TestClient
    resp = TestClient(mod.app).get("/demo/xtrader")
    assert resp.status_code == 200 and "Fonte Segnali" in resp.text
