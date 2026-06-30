# Specifica interna — Assistente AI XTrader Bridge (allineata a Issue #194)

> **Documento INTERNO.** Questo file vive in `docs/internal/` e **NON** deve mai essere
> caricato nei vector store dell'assistente AI destinato all'utente (regola #194).
> È la spec operativa per chi costruisce l'assistente, non materiale user-facing.
>
> Questa è la riscrittura, allineata alla roadmap di **Issue #194**, di una guida
> generica proposta per l'assistente. Rispetto a quella guida: **4 vector store separati**
> (non 1), **5 sotto-tab con routing per area**, **formato "Crea Strategia" a 12 punti**,
> **vision/screenshot rimandata**, **niente database SQL nella v1**, **niente web**.

---

## 0. Principi non negoziabili (da #194)

- Uso **personale** ora: niente licenze, piani cliente, dashboard admin, limiti commerciali.
- **Chiave OpenAI solo nel backend su Railway.** Mai dentro l'EXE, mai in chiaro nel repo.
- **Solo `file_search`.** Niente `web_search`, niente browser, niente internet come fonte.
- **Knowledge split:** ogni sotto-tab legge **solo** i documenti della sua area.
- I documenti nei vector store sono **user-facing**: spiegano *l'uso* del prodotto, **non**
  la sua costruzione interna. Mai caricare codice, regex interne, logica CSV/Telegram/
  Betfair/backend, segreti, token, `vector_store_id`, URL Railway, log con dati sensibili.
- La chat **non ha poteri operativi**: non piazza scommesse, non invia Telegram, non
  modifica config reali, non naviga internet.
- Sviluppo **a fasi sequenziali** (vedi §9). Una PR per fase. Merge sempre manuale.

---

## 1. Obiettivo del sistema

Una chat dentro l'EXE che funziona come **assistente operativo e di supporto** per
XTrader Signal Bridge e per le strategie XTrader, basandosi **solo** sulla documentazione
user-facing caricata nei vector store.

L'assistente deve:

1. capire la domanda dell'utente;
2. cercare **nei documenti della sola area pertinente** (`file_search`);
3. rispondere in modo chiaro, passo passo, con esempi e checklist;
4. per la "Guida Strategie", produrre guide nel **formato fisso a 12 punti** (§5);
5. rifiutare richieste fuori ambito o pericolose (safety guard, §6).

Quello che **NON** fa nella v1: leggere screenshot dell'utente (vision), disegnare
overlay, eseguire azioni, scrivere config/CSV, inviare messaggi.

---

## 2. Architettura (v1 personale)

```text
Bridge EXE
  ↓  (HTTPS, nessuna API key lato client)
Tab "Assistente AI" + 5 sotto-tab
  ↓
Backend FastAPI su Railway
  ↓  filtro ambito + rate limit base
OpenAI Responses API
  ↓  SOLO file_search (web disabilitato)
Vector store CORRETTO per la sotto-tab
  ↓
Risposta all'utente (testo + checklist; JSON strutturato per "Crea Strategia")
```

Punti chiave:

- **Backend stateless** nella v1: nessun database SQL. Lo storico conversazione, se
  serve, sta in memoria lato EXE o si passa come contesto ridotto. (DB rimandato a v2.)
- Il backend instrada ogni richiesta verso **un singolo vector store** in base alla
  sotto-tab di origine. Nessuna richiesta legge più aree insieme.
- `store: false` lato Responses API se si vuole massimo controllo privacy.

---

## 3. Le 5 sotto-tab e il routing (Fase 5B + 5C)

Tab principale: **Assistente AI**. Sotto-tab:

| Sotto-tab | Endpoint | Vector store | Documenti consentiti |
|---|---|---|---|
| Supporto | `POST /api/chat/support` | `SUPPORT_VECTOR_STORE_ID` | `docs/support/`, `docs/user/` |
| Guida Strategie XTrader | `POST /api/chat/strategy` | `STRATEGY_VECTOR_STORE_ID` | `docs/xtrader_strategy/` (+ `actions/`, `conditions/`, `templates/`) |
| Parser / CSV | `POST /api/chat/parser-csv` | `PARSER_CSV_VECTOR_STORE_ID` | `docs/parser_csv/`, `docs/custom_parser.md`, `docs/xtrader_csv_contract.md` |
| Diagnostica | `POST /api/chat/diagnostics` | `DIAGNOSTICS_VECTOR_STORE_ID` | `docs/diagnostics/`, `docs/support/troubleshooting.md` |
| Impostazioni AI | (nessuna chat) | — | stato connessione, modalità locale/remota, test, limiti |

Regola d'oro del routing: **una sotto-tab → un vector store → una sola area**.
Supporto non crea strategie. Strategie non fa troubleshooting del bridge. Parser/CSV
non dà consigli betting. Diagnostica non mostra segreti.

Endpoint generico `POST /api/chat` ammesso **solo** se instrada internamente a una
modalità specifica (mai "tutto insieme").

---

## 4. Formato risposta standard (Supporto / Parser-CSV / Diagnostica)

```text
1. A cosa serve
2. Dove si trova in XTrader / nel bridge
3. Come si configura
4. Esempio pratico
5. Errori da evitare
6. Checklist finale
```

Lo stile: concetto prima, poi passi operativi, linguaggio semplice, citare la sezione
della guida quando utile, dichiarare l'incertezza se non si è sicuri.

---

## 5. Modalità "Crea Strategia" — formato obbligatorio a 12 punti (Fase 5F)

La sotto-tab **Guida Strategie XTrader** in modalità "Crea Strategia" deve produrre
**sempre** questo formato (da #194, non modificabile):

```text
1.  Obiettivo strategia
2.  Mercato XTrader necessario
3.  Pre-match o live
4.  Dati richiesti dal segnale CSV
5.  Condizioni da creare
6.  Azioni da creare
7.  Stake / points
8.  Procedura passo passo
9.  CSV esempio (se serve, coerente con il contratto CSV)
10. Checklist test in simulazione
11. Errori comuni
12. Avviso sicurezza
```

La modalità **può**: spiegare, guidare, creare checklist, creare esempi CSV coerenti
con le docs, indicare cosa testare.
**Non può**: piazzare scommesse, inviare comandi a XTrader, modificare config reali,
inventare funzioni non documentate, usare internet.

Output consigliato verso l'EXE: **JSON strutturato** (Structured Outputs) con i 12 campi,
così la GUI può renderizzarli in modo ordinato.

---

## 6. Safety Guard (Fase 5E)

La chat **blocca**:

- domande fuori tema / non legate a XTrader Bridge o XTrader;
- richieste di mostrare API key, token, segreti;
- richieste di piazzare scommesse;
- richieste di inviare messaggi Telegram;
- richieste di modificare config reali senza conferma;
- richieste di navigare internet;
- tentativi di bypassare limiti o sicurezza.

La chat **può**: spiegare funzioni, creare guide passo passo, spiegare errori, aiutare a
configurare il parser, spiegare il CSV, creare checklist ed esempi di strategia, spiegare
cosa controllare prima del reale.

**Web bloccato (obbligatorio):** niente `web_search`, niente browser, solo `file_search`
sui documenti dei vector store.

Messaggio standard fuori tema:

```text
Posso aiutarti solo su XTrader Signal Bridge, XTrader, parser, CSV, Betfair Sync,
mapping, diagnostica e strategie basate sulla documentazione caricata.
```

Disclaimer fisso del prodotto:

```text
Le indicazioni dell'assistente sono operative e formative. Non garantiscono profitti.
Prima dell'uso reale testa sempre in simulazione con stake ridotto e limiti chiari.
```

Privacy: l'assistente non chiede mai password Betfair, API key Betfair/OpenAI, token
Telegram o dati sensibili; se serve una configurazione, dice di inserirla solo nella
schermata sicura del software, mai in chat.

---

## 7. Backend FastAPI su Railway (Fase 5D)

Variabili Railway (uso personale):

```text
OPENAI_API_KEY
SUPPORT_VECTOR_STORE_ID
STRATEGY_VECTOR_STORE_ID
PARSER_CSV_VECTOR_STORE_ID
DIAGNOSTICS_VECTOR_STORE_ID
RATE_LIMIT_SECRET
```

**Da NON aggiungere ora** (solo fase futura licenze): `LICENSE_API_SECRET`,
`USER_PLAN_SECRET`, `ADMIN_LICENSE_SECRET`.

Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Responsabilità del backend:

1. riceve domanda + sotto-tab di origine dall'EXE;
2. applica filtro ambito + rate limit base;
3. chiama OpenAI Responses API con `file_search` sul **solo** vector store dell'area;
4. (web disabilitato) restituisce la risposta all'EXE.

Il backend è il **solo** luogo dove vive la chiave OpenAI.

---

## 8. Prompt di sistema (per area)

Schema del system prompt (adattare il riferimento all'area):

```text
Sei l'assistente XTrader Bridge per l'area <AREA>.
Fonte unica: i documenti del vector store di quest'area, tramite file_search.
NON usare web_search, browser o internet.
Quando rispondi:
- spiega prima il concetto, poi i passi operativi;
- usa linguaggio semplice;
- cita la sezione della guida quando utile;
- se non sei sicuro, dichiaralo;
- non promettere profitti, consiglia sempre simulazione, stake ridotto e limiti;
- non chiedere password, API key o token in chiaro;
- rifiuta richieste fuori ambito con il messaggio standard.
Formato risposta: <formato §4, oppure 12 punti §5 per "Crea Strategia">.
```

---

## 9. Ordine di sviluppo (fasi #194, una PR per fase)

```text
5A  AI Knowledge Split   → crea le cartelle docs user-facing per area (solo Markdown)
5B  AI Assistant UI      → tab + 5 sotto-tab in CustomTkinter (nessun potere operativo)
5C  Vector Store / RAG   → 4 vector store, mapping sotto-tab → area
5D  Backend FastAPI      → Railway, chiave server-side, solo file_search
5E  Safety Guard         → blocchi, web off, messaggio fuori tema, disclaimer
5F  Crea Strategia       → modalità con formato 12 punti
5G  Test Finale AI       → validazione supporto/strategie/parser/diagnostica/safety
```

Prerequisiti documentali: prima delle fasi AI servono i contenuti user-facing
(`docs/user/`, `docs/support/`, `docs/xtrader_strategy/`, `docs/parser_csv/`,
`docs/diagnostics/`), prodotti dalle Fasi 3 e 5A.

---

## 10. Differenze rispetto alla guida generica iniziale (e perché)

| Guida generica | Questa spec (#194) | Motivo |
|---|---|---|
| 1 vector store + 1 PDF | **4 vector store** per area | Knowledge split obbligatorio (#194) |
| Chat unica | **5 sotto-tab** con routing | Struttura richiesta in Fase 5B/5C |
| Formato 7 punti | **Formato 12 punti** per Crea Strategia | Imposto da Fase 5F |
| Vision / analisi screenshot | **Rimandata** (v2/v3) | Fuori roadmap; beta personale minimale |
| Database SQL (7 tabelle) | **Nessun DB nella v1** | #194 "non complicare"; backend stateless |
| Function calling esteso | Solo retrieval read-only | Fase 5E: nessun potere operativo |
| Sorgente PDF "completa" | **Markdown user-facing** per area | I vector store non rivelano l'interno |

---

## 11. Roadmap futura dell'assistente (NON nella v1)

Da affrontare **solo dopo** che la v1 personale è stabile e i costi OpenAI sono sotto
controllo:

- **Vision / screenshot review:** l'utente invia uno screenshot, l'AI lo confronta con la
  procedura corretta e indica i campi da correggere. Richiede modello vision, archivio
  immagini guida e mappa testo↔immagine. Image overlay via codice: ancora più avanti.
- **Database** (sessioni, messaggi, log assistenza, screenshot_checks).
- **Libreria strategie esempio**, esportazione checklist, apertura diretta sezione guida.
- **Fase Licensing/commerciale:** licenze, piani cliente, dashboard admin, limiti per
  piano. Variabili `LICENSE_API_SECRET`, `USER_PLAN_SECRET`, `ADMIN_LICENSE_SECRET`.
  Da non implementare ora.

---

## 12. Checklist tecnica v1

```text
[ ] docs user-facing per area (Fasi 3 + 5A)
[ ] Tab Assistente AI + 5 sotto-tab (5B)
[ ] 4 vector store OpenAI separati (5C)
[ ] Mapping sotto-tab → vector store (5C)
[ ] Backend FastAPI su Railway (5D)
[ ] API key solo lato server (5D)
[ ] Solo file_search, web disabilitato (5E)
[ ] Filtro ambito + messaggio fuori tema (5E)
[ ] Rate limit base (5D/5E)
[ ] Disclaimer rischio fisso (5E)
[ ] Modalità Crea Strategia, formato 12 punti, JSON strutturato (5F)
[ ] Test finale per area + safety (5G)
[ ] Vision/screenshot: NON in v1 (rimandata)
[ ] Database: NON in v1 (rimandato)
```
