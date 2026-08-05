"""Pagina /documentazione del sito + manuale XTrader ospitato (W9.6, issue #229).

Due gruppi di verifiche, deliberatamente separati:

* **Verifiche su file** — girano SEMPRE, in qualunque ambiente, perché leggono solo
  i sorgenti del sito: esistenza e integrità del PDF, copertura delle traduzioni
  EN/ES, presenza del disclaimer di non-affiliazione su ogni pagina, coerenza fra
  la tabella delle colonne CSV mostrata sul sito e `csv_writer.CSV_HEADER`.
* **Verifiche HTTP** — richiedono FastAPI, che sta in `website/requirements.txt` e
  NON fra le dipendenze del bridge: se manca vengono saltate con motivo esplicito
  (`importorskip`), mentre il gruppo sopra continua a coprire il contenuto.

Perché contano: il PDF è materiale di terzi ospitato su autorizzazione, quindi il
disclaimer e l'attribuzione non sono decorazione — se sparissero nessuno se ne
accorgerebbe fino a una segnalazione. E una pagina nuova con chiavi `data-i18n`
senza traduzione resterebbe muta in EN/ES senza errori a schermo.
"""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_STATIC = _REPO / "website" / "static"
_PDF = _STATIC / "docs" / "guida-xtrader.pdf"
_I18N = _STATIC / "i18n.js"
_DOCS_PAGE = _STATIC / "documentazione.html"

# Pagine che condividono nav+footer del sito. `demo.html` è a sé (replica dell'app,
# chrome proprio) ma deve comunque portare il disclaimer, in forma testuale.
_SHARED_PAGES = ("index.html", "faq.html", "contatti.html", "guida-bot.html",
                 "documentazione.html")


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def _i18n_keys(lang: str) -> set:
    """Chiavi tradotte per `lang` estratte dal dizionario JS (nessun eval)."""
    src = _I18N.read_text(encoding="utf-8")
    start = src.index("    %s: {" % lang)
    # il blocco finisce alla prima riga che chiude l'oggetto della lingua
    end = src.index("\n    }", start)
    return set(re.findall(r'"([A-Za-z0-9._]+)":', src[start:end]))


# ─────────────────────────── PDF ospitato ───────────────────────────

def test_pdf_manuale_presente_e_valido():
    """Il PDF deve esserci ed essere un vero PDF: un file troncato dal commit o
    sostituito da un placeholder darebbe un link rotto sul sito."""
    assert _PDF.is_file(), "manuale XTrader mancante in website/static/docs/"
    head = _PDF.read_bytes()[:5]
    assert head == b"%PDF-", "il file non ha la firma PDF: %r" % head
    # Il manuale reale pesa ~3,8 MB: sotto 1 MB è quasi certamente un troncamento.
    assert _PDF.stat().st_size > 1_000_000, "PDF sospettosamente piccolo"


def test_pagina_documentazione_cita_pdf_versione_e_diritti():
    """Ospitiamo materiale di terzi: link, data della versione e attribuzione devono
    stare TUTTI sulla pagina. La data serve perché il manuale online viene aggiornato
    e la nostra copia no."""
    html = _read("documentazione.html")
    assert "/static/docs/guida-xtrader.pdf" in html
    assert "docs.pdf.version" in html, "manca la riga con la data della versione ospitata"
    assert "TradingSportivo" in html
    assert "autorizzazione" in html.lower()


# ─────────────────────────── disclaimer ───────────────────────────

@pytest.mark.parametrize("page", _SHARED_PAGES)
def test_disclaimer_non_affiliazione_su_ogni_pagina(page):
    html = _read(page)
    assert 'data-i18n="footer.independent"' in html, (
        "%s non porta il disclaimer di non-affiliazione nel footer" % page)


def test_disclaimer_anche_sulla_demo():
    """`demo.html` ha un footer proprio (non quello condiviso): il disclaimer c'è
    comunque, in forma testuale."""
    html = _read("demo.html")
    assert "non è affiliato" in html and "TradingSportivo" in html


# ─────────────────────────── traduzioni ───────────────────────────

@pytest.mark.parametrize("lang", ("en", "es"))
def test_pagina_documentazione_tradotta(lang):
    """Ogni chiave `data-i18n` della pagina deve avere la traduzione: senza, il
    visitatore EN/ES vedrebbe quel blocco in italiano senza alcun errore visibile."""
    used = set(re.findall(r'data-i18n="([^"]+)"', _DOCS_PAGE.read_text(encoding="utf-8")))
    assert used, "la pagina non usa data-i18n: i18n rotta"
    missing = sorted(used - _i18n_keys(lang))
    assert not missing, "chiavi senza traduzione %s: %s" % (lang, missing)


@pytest.mark.parametrize("lang", ("en", "es"))
def test_nav_documentazione_tradotta(lang):
    assert "nav.docs" in _i18n_keys(lang)


# ─────────────────── coerenza col contratto CSV reale ───────────────────

def test_tabella_colonne_coerente_con_csv_header():
    """La tabella pubblicata deve elencare ESATTAMENTE le colonne che il bridge
    scrive, nello stesso ordine: una colonna aggiunta al contratto senza aggiornare
    il sito darebbe documentazione falsa a chi configura XTrader."""
    from xtrader_bridge.csv_writer import CSV_HEADER

    html = _DOCS_PAGE.read_text(encoding="utf-8")
    table = html[html.index('<table'):html.index('</table>')]
    # le colonne sono le <code> della seconda cella di ogni riga della tabella
    listed = re.findall(r'<td[^>]*><code>([A-Za-z]+)</code></td>', table)
    assert listed == list(CSV_HEADER), (
        "tabella del sito disallineata dal contratto CSV: %s" % listed)


def test_pagina_non_promette_conversione_bettype():
    """Il supporto ha confermato (issue #3) che PUNTA/BANCA e BACK/LAY valgono
    indifferentemente: la pagina deve dirlo, non spaventare l'utente straniero."""
    html = _DOCS_PAGE.read_text(encoding="utf-8")
    assert "PUNTA" in html and "BANCA" in html and "BACK" in html and "LAY" in html


# ─────────────────────────── rotte HTTP ───────────────────────────

def _client():
    pytest.importorskip(
        "fastapi",
        reason="FastAPI sta in website/requirements.txt, non fra le dipendenze del "
               "bridge: le verifiche su file coprono comunque il contenuto",
    )
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "betrelay_site_main", _REPO / "website" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    from fastapi.testclient import TestClient
    return TestClient(mod.app)


def test_rotta_documentazione_serve_la_pagina():
    resp = _client().get("/documentazione")
    assert resp.status_code == 200
    assert 'data-i18n="docs.h1"' in resp.text


def test_pdf_scaricabile_dalla_rotta_statica():
    resp = _client().get("/static/docs/guida-xtrader.pdf")
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
