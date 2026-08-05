#!/usr/bin/env python3
"""Collaudo end-to-end del sito BetRelay con un browser vero.

Guida Chromium (Playwright) contro un sito **già in piedi** — in locale o su Railway —
e verifica quello che i test unitari non possono vedere: che le pagine rispondano, che il
JavaScript non esploda, che i flussi delle due demo arrivino in fondo, che il footer di
non-affiliazione ci sia davvero *a schermo* e che il chatbot risponda.

    # locale (uvicorn già avviato in website/)
    python3 tools/e2e/check_site.py --base-url http://127.0.0.1:8000

    # produzione
    python3 tools/e2e/check_site.py --base-url https://betrelay.net --out /tmp/shots

Exit code 0 = tutto verde, 1 = almeno un controllo fallito. Ogni controllo stampa
PASS/FAIL con il dettaglio, così l'output è leggibile anche in CI.

⚠️ Questo script **non** tocca il bridge: naviga un sito e basta. Non invia dati reali,
non usa token, e in modalità demo il chatbot non consuma API.

Note sull'ambiente agente (proxy CCR):
- Chromium non legge `HTTPS_PROXY`: va passato con `--proxy-server`;
- la CA del proxy va nel trust NSS del browser
  (`certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n ccr-agent-proxy -i /root/.ccr/agent-proxy-ca.crt`);
- il ClientHello post-quantum di Chromium fa resettare la connessione dal proxy: si
  disattiva con `--disable-features=PostQuantumKyber` + `--ssl-version-max=tls1.2`.
  È una limitazione del tunnel, **non** si disattiva la verifica TLS.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urljoin, urlparse

try:
    # `Error` è la base di tutte le eccezioni di Playwright, TimeoutError compreso: basta
    # quella per raccogliere «la pagina non si è aperta» senza un except cieco.
    from playwright.sync_api import Error as ErrorePlaywright
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - dipende dall'ambiente
    sys.exit("Manca Playwright: pip install playwright")

# Rotte servite da website/main.py (_PAGES) + le due API.
PAGINE = [
    ("/", "Home"),
    ("/demo", "Demo BetRelay"),
    ("/demo/xtrader", "Demo XTrader"),
    ("/faq", "FAQ"),
    ("/contatti", "Contatti"),
    ("/guida/bot-telegram", "Guida bot"),
    ("/documentazione", "Documentazione"),
    ("/privacy", "Privacy"),
    ("/gioco-responsabile", "Gioco responsabile · 18+"),
]

# Disclaimer di non-affiliazione (docs/policy_lingue_sito.md §7). Il browser headless
# dichiara `navigator.language = en-US`, quindi le pagine trilingui si presentano in
# INGLESE se nessuna lingua è stata scelta: il controllo deve accettare tutte e tre le
# formulazioni, altrimenti fallisce su un footer che c'è ed è corretto.
DISCLAIMER_LINGUE = ("non è affiliato", "not affiliated", "afiliado")
DISCLAIMER_SOGGETTI = ("TradingSportivo", "XTrader", "Betting Toolkit")


def clausola_affiliazione(testo: str) -> str:
    """La sola prima frase del disclaimer, quella che dice «non siamo affiliati a…».

    Va isolata dalla seconda («i marchi appartengono ai rispettivi proprietari»): entrambe
    nominano gli stessi soggetti, quindi cercarli nell'intero footer non distinguerebbe un
    disclaimer completo da uno che si è dimenticato metà dei prodotti. È esattamente il buco
    che una prima versione di questo controllo aveva, e che una mutazione ha scoperto.
    Stessa logica di `tests/unit/test_website_disclaimer_lingue.py`.
    """
    piatto = " ".join(testo.split())
    for marcatore in DISCLAIMER_LINGUE:
        if marcatore in piatto:
            return piatto[piatto.index(marcatore):][:400].split(". ")[0]
    return ""


def disclaimer_ok(testo: str) -> bool:
    clausola = clausola_affiliazione(testo)
    return bool(clausola) and all(s in clausola for s in DISCLAIMER_SOGGETTI)


class Esito:
    """Raccoglitore di risultati: tiene l'ordine e decide l'exit code."""

    def __init__(self) -> None:
        self.righe: list[tuple[str, bool, str]] = []

    def add(self, nome: str, ok: bool, dettaglio: str = "") -> bool:
        self.righe.append((nome, ok, dettaglio))
        print("%s  %s%s" % ("PASS" if ok else "FAIL", nome, "  — " + dettaglio if dettaglio else ""))
        return ok

    @property
    def falliti(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.righe if not r[1]]


def _flags(base_url: str) -> list[str]:
    """Argomenti di lancio di Chromium, incluso il proxy dell'ambiente agente."""
    flags = ["--no-sandbox", "--disable-dev-shm-usage"]
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    host = urlparse(base_url).hostname or ""
    locale = host in ("127.0.0.1", "localhost", "::1")
    if proxy and not locale:
        flags += [
            "--proxy-server=" + proxy,
            "--proxy-bypass-list=127.0.0.1;localhost",
            # Il ClientHello post-quantum viene resettato dal proxy: vedi docstring.
            "--disable-features=PostQuantumKyber,EncryptedClientHello",
            "--ssl-version-max=tls1.2",
        ]
    return flags


def _apri(pagina, url: str, errori: list[str], timeout: int = 30000):
    del errori[:]
    return pagina.goto(url, wait_until="domcontentloaded", timeout=timeout)


def controlla_pagine(pagina, base: str, es: Esito, errori: list[str], out: str) -> None:
    for rotta, nome in PAGINE:
        url = urljoin(base, rotta)
        try:
            r = _apri(pagina, url, errori)
        except ErrorePlaywright as exc:
            # Una pagina che non si apre è un FAIL da riportare, non un crash del collaudo:
            # le altre rotte vanno provate lo stesso.
            es.add("rotta %s" % rotta, False, str(exc).splitlines()[0][:120])
            continue
        if r is None:
            # `goto` torna None quando la navigazione non produce una risposta principale
            # (about:blank, cambio di solo fragment). Qui non dovrebbe succedere, ma leggere
            # `r.status` alla cieca trasformerebbe un caso anomalo in una traceback che
            # nasconde tutti i controlli successivi.
            es.add("rotta %s (%s)" % (rotta, nome), False, "nessuna risposta principale")
            continue
        es.add("rotta %s (%s)" % (rotta, nome), r.status == 200, "HTTP %s" % r.status)

        titolo = pagina.title().strip()
        es.add("  titolo %s" % rotta, bool(titolo), titolo[:60])

        ok_disc = disclaimer_ok(pagina.inner_text("body"))
        es.add("  disclaimer non-affiliazione %s" % rotta, ok_disc,
               "" if ok_disc else "footer assente o clausola incompleta")

        pagina.wait_for_timeout(400)
        es.add("  nessun errore JS %s" % rotta, not errori, "; ".join(errori)[:160])

        if out:
            nome_file = (rotta.strip("/").replace("/", "-") or "home") + ".png"
            pagina.screenshot(path=os.path.join(out, nome_file), full_page=True)


def controlla_asset(pagina, base: str, es: Esito) -> None:
    """Immagini e script referenziati: un 404 qui è una pagina rotta che il DOM non segnala."""
    _apri(pagina, urljoin(base, "/"), [])
    sorgenti = pagina.eval_on_selector_all(
        "img[src], script[src], link[rel=stylesheet]",
        "els => els.map(e => e.src || e.href).filter(Boolean)",
    )
    rotti = []
    for src in dict.fromkeys(sorgenti):
        try:
            resp = pagina.request.get(src, timeout=20000)
            if resp.status >= 400:
                rotti.append("%s → %s" % (src.rsplit("/", 1)[-1], resp.status))
        except ErrorePlaywright as exc:
            # Idem: un asset irraggiungibile è il risultato del controllo, non un errore
            # del controllo.
            rotti.append("%s → %s" % (src.rsplit("/", 1)[-1], str(exc)[:40]))
    es.add("asset della home raggiungibili (%d)" % len(sorgenti), not rotti, "; ".join(rotti)[:160])


def controlla_endpoint(pagina, base: str, es: Esito) -> None:
    r = pagina.request.get(urljoin(base, "/api/health"), timeout=20000)
    es.add("/api/health", r.status == 200, r.text()[:80])

    r = pagina.request.get(urljoin(base, "/favicon.ico"), timeout=20000)
    es.add("/favicon.ico", r.status == 200, "HTTP %s" % r.status)

    r = pagina.request.get(urljoin(base, "/static/docs/guida-xtrader.pdf"), timeout=60000)
    ok = r.status == 200 and r.body()[:5] == b"%PDF-"
    es.add("PDF guida XTrader servito", ok, "HTTP %s, %d byte" % (r.status, len(r.body())))

    r = pagina.request.get(urljoin(base, "/rotta-che-non-esiste"), timeout=20000)
    es.add("rotta inesistente → 404", r.status == 404, "HTTP %s" % r.status)


def controlla_lingue(pagina, base: str, es: Esito) -> None:
    """Il selettore IT/EN/ES deve cambiare il testo e ricordarsi la scelta al reload."""
    _apri(pagina, urljoin(base, "/"), [])
    for lang in ("en", "es", "it"):
        sel = 'button[data-lang="%s"]' % lang
        if pagina.query_selector(sel) is None:
            es.add("selettore lingua %s" % lang.upper(), False, "pulsante assente")
            continue
        pagina.click(sel)
        pagina.wait_for_timeout(250)
        premuto = pagina.get_attribute(sel, "aria-pressed")
        es.add("selettore lingua %s" % lang.upper(), premuto == "true",
               "aria-pressed=%s" % premuto)

        # Il disclaimer è tradotto: in ogni lingua devono restare sia la formula di
        # non-affiliazione sia TUTTI i soggetti citati. Una traduzione dimezzata (è già
        # successo) passerebbe un controllo che cerca solo i nomi, perché nel footer
        # compaiono due volte.
        corpo = pagina.inner_text("footer")
        ok = disclaimer_ok(corpo)
        es.add("  disclaimer completo in %s" % lang.upper(), ok,
               "" if ok else clausola_affiliazione(corpo)[:90] or "clausola non trovata")

    pagina.click('button[data-lang="en"]')
    pagina.wait_for_timeout(200)
    pagina.reload(wait_until="domcontentloaded")
    pagina.wait_for_timeout(300)
    ok = pagina.get_attribute('button[data-lang="en"]', "aria-pressed") == "true"
    es.add("lingua ricordata dopo il reload", ok)
    pagina.click('button[data-lang="it"]')


def controlla_guida_bot(pagina, base: str, es: Esito) -> None:
    """La guida bot in inglese: tradotta davvero, ma con le etichette Telegram intatte.

    È la pagina che era pubblicata solo in italiano (Issue #287). Due cose vanno vere insieme,
    e sono in tensione fra loro: il testo deve cambiare lingua, e l'etichetta italiana che si
    vede nello screenshot **non** deve cambiare — altrimenti l'utente cerca a schermo un
    pulsante che non esiste (`docs/policy_lingue_sito.md` §3).
    """
    _apri(pagina, urljoin(base, "/guida/bot-telegram"), [])
    if pagina.query_selector('button[data-lang="en"]') is None:
        es.add("guida bot: selettore di lingua", False, "pulsante assente")
        return
    es.add("guida bot: selettore di lingua", True)

    titolo_it = pagina.inner_text("h1").strip()
    pagina.click('button[data-lang="en"]')
    pagina.wait_for_timeout(300)
    corpo = pagina.inner_text("main")
    titolo_en = pagina.inner_text("h1").strip()

    # Il valore atteso lo chiede al **dizionario vivo** della pagina (`window.SITE_T`, esposto
    # da i18n.js), invece di tenersi una copia della frase inglese: una copia si sfasa al primo
    # ritocco del copy e il collaudo diventa rosso senza che nulla sia rotto. Chiedendolo al
    # dizionario, il controllo resta forte — verifica che a schermo ci sia **esattamente** la
    # traduzione prevista — senza sapere nulla di come è scritta (rilievi GPT-5.5 sulla #289:
    # prima troppo fragile, poi troppo debole; questo non è né l'uno né l'altro).
    atteso = pagina.evaluate("() => window.SITE_T && window.SITE_T('guida.h1')")
    ok = bool(atteso) and titolo_en == atteso and titolo_en != titolo_it
    es.add("  guida bot: il titolo è la traduzione prevista dal dizionario", ok,
           "dizionario=%r  a schermo=%r" % ((atteso or "")[:40], titolo_en[:40]))
    es.add("  guida bot: dice che le schermate sono in italiano", "in Italian" in corpo)
    es.add("  guida bot: etichetta Telegram verbatim in inglese",
           "Amministratori" in corpo,
           "" if "Amministratori" in corpo else "l'etichetta è stata tradotta: il pulsante "
                                                "non si troverebbe a schermo")
    pagina.click('button[data-lang="it"]')
    pagina.wait_for_timeout(200)
    # Anche il ritorno va verificato: `apply()` ripristina l'italiano da `data-i18n-orig`, e se
    # quel ripristino si rompesse la pagina resterebbe inglese per un utente italiano. Cliccare
    # senza guardare l'esito è il modo classico di avere un controllo che non controlla niente
    # (rilievo CodeRabbit sulla #289).
    tornato = pagina.inner_text("h1").strip()
    es.add("  guida bot: torna in italiano", tornato == titolo_it,
           "atteso %r, a schermo %r" % (titolo_it[:40], tornato[:40]))


def controlla_demo_bridge(pagina, base: str, es: Esito, errori: list[str], out: str) -> None:
    """Percorso reale: esplora liberamente → AVVIA → segnale di prova."""
    _apri(pagina, urljoin(base, "/demo"), errori)
    pagina.click("#btnFree")
    pagina.wait_for_timeout(300)

    pagina.click("#btnStart")
    pagina.wait_for_timeout(600)
    stato = pagina.inner_text("#statusTxt")
    es.add("demo: AVVIA porta lo stato ad ATTIVO", "ATTIVO" in stato, stato.strip())
    es.add("demo: STOP si abilita", not pagina.is_disabled("#btnStop"))

    pagina.click("#btnSignal")
    pagina.wait_for_timeout(1500)
    ricevuti = pagina.inner_text("#cRic")
    es.add("demo: il segnale di prova viene contato", ricevuti.strip() not in ("", "0"),
           "ricevuti = %s" % ricevuti.strip())

    pagina.click("#btnStop")
    pagina.wait_for_timeout(400)
    stato = pagina.inner_text("#statusTxt")
    es.add("demo: STOP riporta OFFLINE", "OFFLINE" in stato, stato.strip())
    es.add("demo: nessun errore JS nel flusso", not errori, "; ".join(errori)[:160])
    if out:
        pagina.screenshot(path=os.path.join(out, "flusso-demo.png"), full_page=True)


def controlla_demo_xtrader(pagina, base: str, es: Esito, errori: list[str], out: str) -> None:
    """Percorso reale: crea fonte → segnale valido → segnale non valido → timeout."""
    _apri(pagina, urljoin(base, "/demo/xtrader"), errori)

    for win in ("filtro", "monitor", "segnali"):
        pagina.click('button[data-win="%s"]' % win)
        pagina.wait_for_timeout(200)
        sel = pagina.get_attribute('button[data-win="%s"]' % win, "aria-selected")
        es.add("demo XTrader: scheda «%s»" % win, sel == "true", "aria-selected=%s" % sel)

    pagina.click('button[data-win="segnali"]')
    pagina.click("#a1")
    pagina.wait_for_timeout(300)
    es.add("demo XTrader: si apre la dialog Fonte Segnali",
           "show" in (pagina.get_attribute("#ovl", "class") or ""))
    pagina.click("#dlgOk")
    pagina.wait_for_timeout(500)
    es.add("demo XTrader: la fonte compare in elenco",
           "BetRelay" in pagina.inner_text("#tbFonti"))

    pagina.click("#a2")
    pagina.wait_for_timeout(2200)
    righe_ok = pagina.eval_on_selector_all("#tbSegnali .dot.ok", "e => e.length")
    es.add("demo XTrader: il segnale valido appare verde", righe_ok >= 1, "%d righe ok" % righe_ok)

    pagina.click("#a3")
    pagina.wait_for_timeout(2200)
    righe_ko = pagina.eval_on_selector_all("#tbSegnali .dot.ko", "e => e.length")
    es.add("demo XTrader: il segnale non valido appare rosso", righe_ko >= 1,
           "%d righe ko" % righe_ko)

    spiegazione = pagina.inner_text("#why") if pagina.query_selector("#why") else ""
    es.add("demo XTrader: la spiegazione del perché è visibile", bool(spiegazione.strip()),
           spiegazione.strip()[:70])

    pagina.click("#a4")
    pagina.wait_for_timeout(2200)
    csv = pagina.inner_text("#csvBox")
    es.add("demo XTrader: allo scadere del timeout il CSV torna pulito",
           "Provider" in csv or "header" in csv.lower(), csv.strip()[:70])
    es.add("demo XTrader: nessun errore JS nel flusso", not errori, "; ".join(errori)[:160])
    if out:
        pagina.screenshot(path=os.path.join(out, "flusso-demo-xtrader.png"), full_page=True)


def controlla_chatbot(pagina, base: str, es: Esito) -> None:
    _apri(pagina, urljoin(base, "/"), [])
    if pagina.query_selector("#chat-fab") is None:
        es.add("chatbot: pulsante presente", False, "#chat-fab assente")
        return
    es.add("chatbot: pulsante presente", True)
    pagina.click("#chat-fab")
    pagina.wait_for_timeout(300)
    pagina.fill("#chat-input", "Come si crea il bot token?")
    prima = pagina.eval_on_selector_all("#chat-msgs > div", "e => e.length")
    pagina.click("#chat-send")
    for _ in range(40):
        pagina.wait_for_timeout(500)
        if pagina.eval_on_selector_all("#chat-msgs > div", "e => e.length") > prima + 1:
            break
    testo = pagina.inner_text("#chat-msgs")
    ok = "botfather" in testo.lower() or "token" in testo.lower()
    es.add("chatbot: risponde nel merito", ok, testo.strip().splitlines()[-1][:80] if testo else "")
    modo = pagina.inner_text("#chat-mode") if pagina.query_selector("#chat-mode") else ""
    print("      (modalità chatbot: %s)" % (modo.strip() or "non dichiarata"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Collaudo end-to-end del sito BetRelay")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="", help="cartella dove salvare gli screenshot")
    ap.add_argument("--skip-chat", action="store_true", help="salta il chatbot (evita costi API)")
    ap.add_argument("--chromium", default="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    args = ap.parse_args()

    base = args.base_url.rstrip("/") + "/"
    if args.out:
        os.makedirs(args.out, exist_ok=True)

    print("Collaudo di %s\n" % base)
    inizio = time.time()
    es = Esito()
    errori: list[str] = []

    with sync_playwright() as p:
        avvio = {"args": _flags(base)}
        if os.path.exists(args.chromium):
            avvio["executable_path"] = args.chromium
        browser = p.chromium.launch(**avvio)
        # `locale="it-IT"`: senza questo il browser headless si dichiara en-US e le pagine
        # trilingui si presentano in inglese, quindi il testo scritto nel markup (italiano)
        # non verrebbe mai messo alla prova. Le altre due lingue le esercita
        # `controlla_lingue()` usando il selettore.
        pagina = browser.new_page(viewport={"width": 1366, "height": 900}, locale="it-IT")
        pagina.on("pageerror", lambda e: errori.append(str(e)[:120]))
        pagina.on("console", lambda m: errori.append(m.text[:120]) if m.type == "error" else None)

        sezioni = [
            ("pagine", lambda: controlla_pagine(pagina, base, es, errori, args.out)),
            ("endpoint", lambda: controlla_endpoint(pagina, base, es)),
            ("asset", lambda: controlla_asset(pagina, base, es)),
            ("lingue", lambda: controlla_lingue(pagina, base, es)),
            ("guida bot", lambda: controlla_guida_bot(pagina, base, es)),
            ("demo BetRelay", lambda: controlla_demo_bridge(pagina, base, es, errori, args.out)),
            ("demo XTrader", lambda: controlla_demo_xtrader(pagina, base, es, errori, args.out)),
        ]
        if not args.skip_chat:
            sezioni.append(("chatbot", lambda: controlla_chatbot(pagina, base, es)))

        for nome, sezione in sezioni:
            try:
                sezione()
            except ErrorePlaywright as exc:
                # Se il sito è irraggiungibile o una sezione si pianta, le altre vanno provate
                # lo stesso e il riepilogo finale deve comunque uscire: un collaudo che termina
                # con una traceback non dice quanti controlli erano passati prima.
                es.add("sezione «%s» interrotta" % nome, False, str(exc).splitlines()[0][:120])

        browser.close()

    tot, ko = len(es.righe), len(es.falliti)
    print("\n%d controlli in %.1fs — %d PASS, %d FAIL" % (tot, time.time() - inizio, tot - ko, ko))
    if ko:
        print("\nFalliti:")
        for nome, _, dettaglio in es.falliti:
            print("  - %s%s" % (nome, ": " + dettaglio if dettaglio else ""))
    return 1 if ko else 0


if __name__ == "__main__":
    sys.exit(main())
