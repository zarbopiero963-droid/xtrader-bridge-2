# BetRelay Site

Sito vetrina + supporto di **BetRelay** (già XTrader Signal Bridge): homepage, demo interattiva,
FAQ, contatti e chatbot di supporto (solo sul bridge, sola lettura).

> Capitolato completo: issue «[SITO WEB] betrelay-site» (#229 del repo bridge,
> da trasferire qui).

## Lingue e famiglia Betting Toolkit

- Sito **trilingue IT / EN / ES** con **auto-riconoscimento** dalla lingua del browser
  (`navigator.language`: it→IT, es→ES, altro→EN) e **selettore manuale** IT|EN|ES nella
  nav (scelta ricordata in `localStorage`). Implementazione: `static/i18n.js`
  (dizionari + attributi `data-i18n`); l'italiano è il testo di default nel markup.
- Il sito presenta il bridge come compatibile con **tutta la famiglia**: XTrader
  (Italia) + BETTINGTOOLKIT.COM (World) + BETTINGTOOLKIT.ES (Spagna) +
  BETTINGTOOLKIT.LAT (America Latina) — sezione dedicata in homepage e knowledge
  base del chatbot aggiornata.
- Il **chatbot** riceve la lingua dell'interfaccia (`lang` in `/api/chat`) e risponde
  in quella lingua sia in modalità demo (risposte predefinite IT/EN/ES) sia in
  modalità live (istruzione nel system prompt; se l'utente scrive in un'altra lingua,
  segue quella).
- La **demo interattiva** (`/demo`) per ora è in italiano, con nota trilingue; la
  traduzione della demo è un lavoro successivo.

## Test in locale (Windows)

Requisiti: Python 3.11+ ([python.org](https://www.python.org/downloads/), spunta
"Add python.exe to PATH").

```bat
cd xtrader-bridge-site
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Apri **http://127.0.0.1:8000** — pagine: `/` (home), `/demo`, `/documentazione`, `/faq`,
`/contatti`, `/guida/bot-telegram`.

### Chatbot: due modalità

- **Senza API key (default):** modalità **demo** — risposte predefinite basate sulle
  FAQ, a costo zero. Perfetta per testare il sito in locale.
- **Con API key Anthropic:** risposte vere dal modello, vincolate alla knowledge
  base del bridge (`knowledge/bridge_kb.md`). Per provarla in locale:

```bat
set ANTHROPIC_API_KEY=sk-ant-...   &REM la tua chiave, MAI committarla
uvicorn main:app --reload
```

Verifica quale modalità è attiva: http://127.0.0.1:8000/api/health
(`"chatbot": "demo"` oppure `"live"`).

### Guardrail del chatbot (server-side)

- Risponde SOLO su XTrader Signal Bridge; fuori tema → rifiuto cortese + rimando a Contatti.
- Nessuna azione: solo Q&A su knowledge base fissa. Nessun tool, nessun web.
- Rate limit: 20 messaggi/ora per IP (variabile `CHAT_RATE_LIMIT`).
- Input limitato a 1000 caratteri; storia limitata a 6 turni.
- La API key vive SOLO in variabile d'ambiente (in produzione: Railway → Variables).

## Deploy su Railway

1. Crea il progetto Railway e collega questo repository.
2. **Settings → Root Directory = `website`.** Non è opzionale: il `Dockerfile` sta qui e le
   sue `COPY` sono relative a questa cartella. Buildando dalla radice del repository,
   `requirements.txt` non verrebbe trovato e il build fallirebbe.
3. In **Variables** imposta `ANTHROPIC_API_KEY` (e, se vuoi, `ANTHROPIC_MODEL`,
   `CHAT_RATE_LIMIT`). Railway inietta `PORT` da solo.
4. Genera il dominio pubblico (Settings → Networking → Generate Domain).
5. **Collauda il sito online**: `python3 tools/e2e/check_site.py --base-url https://<dominio>`
   apre le pagine con un browser vero e verifica rotte, demo, chatbot, footer e asset.

Sull'immagine: `.dockerignore` tiene fuori segreti, cache e ambienti locali (il `COPY . .`
altrimenti li includerebbe), il processo gira come utente **non privilegiato** e le dipendenze
sono **pinnate** in `requirements.txt`, così il deploy è riproducibile.

> ℹ️ L'immagine **non** è mai stata costruita in ambiente agente (Docker non disponibile lì):
> il primo `docker build` di Railway è anche la prima verifica reale di questo Dockerfile.

Senza `ANTHROPIC_API_KEY` il sito funziona comunque, col chatbot in modalità demo.

## Struttura

```text
main.py                  FastAPI: pagine statiche + POST /api/chat + /api/health
knowledge/bridge_kb.md   knowledge base del chatbot (dalle docs reali del bridge)
static/                  index.html · demo.html · documentazione.html · faq.html ·
                         contatti.html · guida-bot.html · style.css · chat.js · i18n.js
static/docs/             manuale PDF di XTrader (materiale di terzi — vedi sotto)
static/img/guida/        screenshot delle guide (valori d'esempio, mai dati reali)
Dockerfile               build per Railway / locale
```

## Materiale di terzi ospitato

`static/docs/guida-xtrader.pdf` è il **manuale ufficiale di XTrader**, opera di
**TradingSportivo**, ripubblicato **con la loro autorizzazione** (concessa al proprietario del
progetto). Regole:

- non è materiale nostro: **non va modificato né ridistribuito** altrove;
- la pagina `/documentazione` deve sempre mostrare **attribuzione**, **data della versione
  ospitata** e il rimando alla **guida online** — il manuale viene aggiornato nel tempo, la nostra
  copia no (test: `tests/unit/test_website_docs_page.py`);
- versione attuale: scaricata il **05/08/2026**, capitoli aggiornati fino al **12/06/2026**.
  Quando si sostituisce il file, aggiornare anche `docs.pdf.version` in `static/i18n.js` (IT nel
  markup, EN/ES nei dizionari).

Ogni pagina del sito porta il **disclaimer di non-affiliazione** nel footer
(`footer.independent`; su `demo.html`, che ha un footer proprio, in forma testuale). È verificato
da test: una pagina nuova senza disclaimer fa fallire la suite.

## Roadmap

L'elenco completo e aggiornato di cosa manca — con priorità, motivazioni e distinzione fra ciò
che può fare l'agente e ciò che richiede il proprietario — è in
[`docs/roadmap_sito.md`](../docs/roadmap_sito.md).

Le due cose che **bloccano la pubblicazione**: una **pagina privacy** (il chatbot invia i
messaggi degli utenti all'API Anthropic) e un richiamo a **gioco responsabile / 18+**, con la
verifica legale che ne consegue.

## Da fare prima di andare pubblici

- [x] Indirizzo di supporto reale in `static/contatti.html` (spezzato nel sorgente e
      ricomposto in JavaScript: la forma `nome@dominio` non compare nell'HTML servito,
      così i raccoglitori automatici non lo trovano). Test: `tests/unit/test_website_contatti.py`
- [ ] `/api/contact` con invio email dal backend, così l'indirizzo non passa più dal client
      dell'utente — con anti-abuso, visto che sarebbe un endpoint pubblico.
- [ ] Aggiornare la demo quando ci sono screenshot freschi dell'app.
- [ ] (Opzionale) Dominio personalizzato su Railway.
- [ ] Tradurre in EN/ES la guida `/guida/bot-telegram` (la pagina `/documentazione` lo è già).
- [ ] Scrivere la guida «Collegare BetRelay a XTrader» (card già presente in `/documentazione`,
      marcata «In preparazione»): serve prima la serie di screenshot reali di XTrader.
