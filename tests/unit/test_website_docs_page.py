"""Pagina /documentazione del sito (W9.6, issue #229).

Due gruppi di verifiche, deliberatamente separati:

* **Verifiche su file** — girano SEMPRE, in qualunque ambiente, perché leggono solo
  i sorgenti del sito: assenza del manuale di terzi, copertura delle traduzioni
  EN/ES, presenza del disclaimer di non-affiliazione su ogni pagina, coerenza fra
  la tabella delle colonne CSV mostrata sul sito e `csv_writer.CSV_HEADER`.
* **Verifiche HTTP** — richiedono FastAPI, che sta in `website/requirements.txt` e
  NON fra le dipendenze del bridge: se manca vengono saltate con motivo esplicito
  (`importorskip`), mentre il gruppo sopra continua a coprire il contenuto.

Perché contano: fino al 6 agosto 2026 il sito **ospitava** il manuale di XTrader
(opera di TradingSportivo, su autorizzazione). Il proprietario ha deciso di non
ospitarlo più, quindi i test qui sotto sono girati: pretendono che quel PDF **non**
torni e che nessuna pagina lo linki — un file ricopiato o un `<a href>` rimesso per
distrazione darebbero un 404 in faccia all'utente, o peggio rimetterebbero online
l'opera di qualcun altro. L'attribuzione a TradingSportivo invece resta, perché il
manuale è comunque opera loro e la pagina continua a nominarlo. E una pagina nuova
con chiavi `data-i18n` senza traduzione resterebbe muta in EN/ES senza errori a
schermo.
"""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_STATIC = _REPO / "website" / "static"
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


# ───────────────── manuale XTrader: NON ospitato (dal 6 agosto 2026) ─────────────────

def test_il_manuale_xtrader_non_e_piu_ospitato_ne_linkato():
    """Il PDF del manuale XTrader è stato **rimosso dal sito** (decisione del proprietario,
    6 agosto 2026): non lo ospitiamo più e nessuna pagina lo linka.

    Era materiale di terzi (TradingSportivo) servito da noi: 358 pagine, 3,8 MB. Ospitare
    l'opera di qualcun altro è una responsabilità che si sceglie di avere, e il proprietario
    ha scelto di non averla più. Questo test impedisce che rientri per distrazione — un
    `<a href>` rimesso in una pagina, o il file ricopiato nella cartella statica.

    Resta legittimo **nominare** il manuale e dire che sta sul sito del produttore: è quello
    che la pagina fa ora, senza link e senza copia.
    """
    pdf = _STATIC / "docs" / "guida-xtrader.pdf"
    assert not pdf.exists(), (
        "il manuale XTrader è tornato in website/static/docs/: era stato rimosso dal sito "
        "di proposito. È opera di TradingSportivo, non nostra.")

    for pagina in sorted(_STATIC.glob("*.html")):
        testo = pagina.read_text(encoding="utf-8")
        assert "guida-xtrader.pdf" not in testo, (
            "%s linka di nuovo il manuale XTrader, che non è più ospitato: "
            "il link darebbe 404" % pagina.name)

    # e nemmeno i dizionari devono contenere una CTA verso un file che non c'è
    testo_i18n = _I18N.read_text(encoding="utf-8")
    assert "guida-xtrader.pdf" not in testo_i18n, (
        "i18n.js nomina ancora il PDF rimosso")


def test_pagina_documentazione_rimanda_al_manuale_del_produttore():
    """Tolto il PDF, la pagina deve comunque dire **dove** sta il manuale.

    Senza, un utente che cerca «come si usa XTrader» non ha più nessun rimando — e la
    sezione resterebbe un titolo senza contenuto utile. La citazione dell'autore resta
    perché il manuale è opera sua e va attribuito, anche se non lo ospitiamo più.
    """
    html = _read("documentazione.html")
    assert "TradingSportivo" in html, "persa l'attribuzione all'autore del manuale"


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


def test_il_pdf_del_manuale_non_e_piu_servito():
    """La rotta statica non deve più consegnare il manuale: chi ha il vecchio link
    riceve 404, che è il comportamento voluto e non un guasto."""
    resp = _client().get("/static/docs/guida-xtrader.pdf")
    assert resp.status_code == 404, (
        "il sito serve ancora il manuale XTrader su /static/docs/guida-xtrader.pdf "
        "(status %s)" % resp.status_code)
