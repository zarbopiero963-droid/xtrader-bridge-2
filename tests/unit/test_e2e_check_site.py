"""Logica pura del collaudo end-to-end del sito (`tools/e2e/check_site.py`).

Il grosso di quello script è browser: non è eseguibile nella suite. Ma i pezzi che decidono
**se un controllo passa** sono funzioni normali, e proprio lì è già stato trovato un buco —
la prima versione considerava valido un disclaimer dimezzato, perché cercava i nomi dei
prodotti nell'intero footer, dove compaiono due volte. Quel buco è una regressione da bloccare:
un collaudo che dice PASS su un footer sbagliato è peggio di nessun collaudo.

Qui si verifica anche che i flag del browser siano quelli giusti per l'ambiente con proxy, e
che le rotte controllate coincidano con quelle davvero servite da `website/main.py`.
"""

import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "tools" / "e2e" / "check_site.py"


def _carica():
    """Importa lo script per path: non è un package, e non deve diventarlo."""
    _stub_playwright()
    spec = importlib.util.spec_from_file_location("check_site_e2e", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_playwright() -> None:
    """Registra un modulo `playwright` minimo quando non è installato.

    Lo script esce all'import senza Playwright, e una prima versione di questo file lo
    risolveva saltando l'INTERO modulo. Ma nella CI del bridge Playwright **non c'è**: il
    risultato era che i controlli di logica pura — fra cui la regressione del disclaimer
    dimezzato, l'unico difetto vero già trovato qui — non venivano eseguiti da nessuna parte.
    Un test che salta proprio dove dovrebbe proteggere non protegge niente.

    Nessuna finzione sul comportamento: si registra solo ciò che serve all'import
    (`Error`, `sync_playwright`), e nessun test qui apre un browser.
    """
    if "playwright" in sys.modules:
        return  # già installato, o già messo qui da una chiamata precedente
    try:
        if importlib.util.find_spec("playwright") is not None:
            return
    except ImportError:
        pass  # non importabile: si prosegue e si registra lo stub

    def _modulo(nome):
        # `spec` va valorizzato: un modulo in sys.modules con `__spec__ = None` fa sollevare
        # `ValueError` alla PROSSIMA `find_spec()`. È successo davvero in CI, ed è il motivo
        # per cui questo stub va provato in un ambiente senza Playwright, non qui dove c'è.
        m = types.ModuleType(nome)
        m.__spec__ = importlib.machinery.ModuleSpec(nome, loader=None)
        return m

    pacchetto = _modulo("playwright")
    api = _modulo("playwright.sync_api")
    api.Error = type("Error", (Exception,), {})
    api.sync_playwright = lambda: None
    pacchetto.sync_api = api
    sys.modules["playwright"] = pacchetto
    sys.modules["playwright.sync_api"] = api


# Footer reali, così come li rende il browser (testo appiattito, due frasi).
_IT = ("Progetto indipendente: BetRelay non è affiliato, associato, autorizzato né sponsorizzato "
       "da TradingSportivo (XTrader) né da Betting Toolkit (BETTINGTOOLKIT.COM / .ES / .LAT). "
       "XTrader, Betting Toolkit, Betfair, Telegram e i relativi marchi appartengono ai "
       "rispettivi proprietari e sono citati solo a scopo descrittivo, per indicare la "
       "compatibilità.")
_EN = ("Independent project: BetRelay is not affiliated with, associated with, authorised or "
       "sponsored by TradingSportivo (XTrader) or Betting Toolkit (BETTINGTOOLKIT.COM / .ES / "
       ".LAT). XTrader, Betting Toolkit, Betfair, Telegram and the related trademarks belong to "
       "their respective owners and are named for descriptive purposes only.")
_ES = ("Proyecto independiente: BetRelay no está afiliado, asociado, autorizado ni patrocinado "
       "por TradingSportivo (XTrader) ni por Betting Toolkit (BETTINGTOOLKIT.COM / .ES / .LAT). "
       "XTrader, Betting Toolkit, Betfair, Telegram y las marcas relacionadas pertenecen a sus "
       "respectivos propietarios.")


@pytest.mark.parametrize("footer", [_IT, _EN, _ES], ids=["it", "en", "es"])
def test_disclaimer_completo_passa_in_tutte_le_lingue(footer):
    """Il footer è tradotto: il controllo non deve dipendere dall'italiano, altrimenti il
    collaudo di un sito visto da un browser inglese fallisce su una pagina corretta."""
    assert _carica().disclaimer_ok(footer)


@pytest.mark.parametrize("footer", [_IT, _EN, _ES], ids=["it", "en", "es"])
def test_disclaimer_dimezzato_viene_bocciato(footer):
    """La regressione vera: si toglie «Betting Toolkit» dalla PRIMA frase lasciandolo nella
    seconda. Un controllo che guarda tutto il footer direbbe PASS — e il sito potrebbe
    pubblicare una clausola che non copre gli utenti Betting Toolkit."""
    prima, resto = footer.split(". ", 1)
    for pezzo in ("né da Betting Toolkit", "or Betting Toolkit", "ni por Betting Toolkit"):
        prima = prima.replace(pezzo, "")
    mutato = prima + ". " + resto
    assert "Betting Toolkit" in mutato, "la mutazione deve lasciare il nome nella seconda frase"
    assert not _carica().disclaimer_ok(mutato), "un disclaimer dimezzato è passato"


def test_footer_senza_disclaimer_viene_bocciato():
    mod = _carica()
    assert not mod.disclaimer_ok("© 2026 BetRelay — tutti i diritti riservati.")
    assert mod.clausola_affiliazione("© 2026 BetRelay") == ""


def test_la_clausola_si_ferma_alla_prima_frase():
    """Il taglio deve avvenire sul punto di fine frase e non sui punti interni di
    «BETTINGTOOLKIT.COM / .ES / .LAT», altrimenti la clausola risulterebbe troncata a metà
    e nessun disclaimer passerebbe più."""
    clausola = _carica().clausola_affiliazione(_IT)
    assert clausola.endswith(".LAT)"), clausola
    assert "marchi appartengono" not in clausola


def test_i_flag_del_browser_usano_il_proxy_solo_fuori_da_localhost(monkeypatch):
    """Chromium non legge HTTPS_PROXY: se il proxy non viene passato come flag, il collaudo
    del sito in produzione fallisce con ERR_CONNECTION_RESET su tutto. In locale, al
    contrario, passare il proxy fa uscire il traffico che dovrebbe restare in casa."""
    mod = _carica()
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:37807")

    remoto = mod._flags("https://betrelay.net")
    assert "--proxy-server=http://127.0.0.1:37807" in remoto
    # Il ClientHello post-quantum viene resettato dal tunnel: senza questi due flag il
    # browser non esce. È una limitazione del proxy, non un allentamento di TLS.
    assert any(f.startswith("--disable-features=") and "PostQuantumKyber" in f for f in remoto)
    assert "--ssl-version-max=tls1.2" in remoto

    locale = mod._flags("http://127.0.0.1:8000")
    assert not [f for f in locale if f.startswith("--proxy-server")]


def test_non_si_disattiva_mai_la_verifica_dei_certificati():
    """Il collaudo deve fallire su un certificato non valido, non ignorarlo: un sito in
    produzione con HTTPS rotto è esattamente ciò che serve scoprire."""
    testo = _SCRIPT.read_text(encoding="utf-8")
    for vietato in ("--ignore-certificate-errors", "ignore_https_errors"):
        assert vietato not in testo, "lo script disattiva la verifica TLS (%s)" % vietato


def test_gli_errori_del_browser_sono_catturati_stretti_non_alla_cieca():
    """Il collaudo deve reggere un sito irraggiungibile **senza** un `except Exception`.

    Servono entrambe le cose: catturare (una traceback non dice quanti controlli erano
    passati prima, e il riepilogo non uscirebbe) e catturare STRETTO — un handler cieco qui
    ingoierebbe anche i bug dello script stesso, facendo passare per «sito rotto» un errore
    nostro. Il gate `tests/safety/test_blind_except_allowlist.py` lo verifica a livello di
    repo; questo test lo àncora al file.
    """
    testo = _SCRIPT.read_text(encoding="utf-8")
    assert "except Exception" not in testo and "except:" not in testo
    assert testo.count("except ErrorePlaywright") >= 3, \
        "i rami che reggono un sito irraggiungibile sono spariti o sono stati allargati"


def test_le_rotte_controllate_sono_quelle_servite_dal_sito():
    """Se qualcuno aggiunge una pagina a `_PAGES` senza toccare il collaudo, quella pagina
    non verrebbe mai aperta da un browser: nessuno se ne accorgerebbe fino alla pubblicazione."""
    # Si legge il valore REALE di `_PAGES`, non il testo del file: tagliare il sorgente alla
    # prima `}` basta finché nessun valore contiene una graffa, e il giorno che ne contenesse
    # una il blocco finirebbe presto, `rotte_sito` si restringerebbe e l'assert passerebbe
    # avendo confrontato meno rotte del vero — un PASS proprio sulla regressione da bloccare.
    sorgente = (_ROOT / "website" / "main.py").read_text(encoding="utf-8")
    inizio = sorgente.index("_PAGES = {")
    fine = sorgente.index("}", inizio) + 1
    spazio = {}
    exec(compile(sorgente[inizio:fine], "<_PAGES>", "exec"), spazio)  # noqa: S102
    pages = spazio["_PAGES"]
    assert isinstance(pages, dict) and pages, "estrazione di _PAGES fallita: %r" % (pages,)

    rotte_sito = set(pages)
    rotte_collaudo = {r for r, _ in _carica().PAGINE}
    assert rotte_sito <= rotte_collaudo, "rotte servite ma mai collaudate: %s" % (
        sorted(rotte_sito - rotte_collaudo),)
    assert len(rotte_sito) == len(rotte_collaudo), (
        "il collaudo apre rotte che il sito non serve più: %s"
        % sorted(rotte_collaudo - rotte_sito))
