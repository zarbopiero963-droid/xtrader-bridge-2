Roadmap completa — Documentazione, Redesign UI, Assistente AI interno e fase futura licenze

Obiettivo generale

Creare una roadmap ordinata per far evolvere XTrader Signal Bridge in modo professionale, senza perdere i passaggi discussi.

La roadmap copre:

1. Regole obbligatorie di documentazione.
2. Redesign grafico dell’app desktop EXE.
3. Manuale utente con screenshot reali.
4. Documentazione tecnica automatica.
5. Assistente AI interno personale.
6. Fase futura per licenze/distribuzione commerciale.

---

Stato importante

Al momento il progetto è per uso personale.

Quindi:

- il controllo licenza utente NON va implementato adesso;
- piani cliente, dashboard admin e limiti commerciali si faranno dopo;
- l’assistente AI deve funzionare prima in beta personale;
- la chiave OpenAI deve stare nel backend su Railway, non dentro l’EXE.

---

FASE 1 — PR Docs Governance

Nome PR suggerito

"docs/mandatory-documentation-maintenance"

Obiettivo

Aggiungere una regola obbligatoria in:

- "CLAUDE.md"
- "AGENTS.md"

Regola:

«Ogni PR che aggiunge, modifica o elimina codice deve aggiornare la documentazione corrispondente nello stesso PR.»

Cosa aggiungere

Ogni micro-audit/final verify deve includere:

docs aggiornate: PASS/FAIL/N/A

Dove:

- "PASS" = documentazione aggiornata nello stesso PR.
- "FAIL" = codice modificato ma documentazione mancante.
- "N/A" = modifica puramente interna senza impatto documentale, con motivazione scritta.

Documenti da aggiornare quando applicabile

- "README.md"
- "docs/custom_parser.md"
- "docs/xtrader_csv_contract.md"
- "docs/audit/roadmap.md"
- docstring/commenti tecnici per funzioni pubbliche
- future guide utente con screenshot quando cambiano schermate, pulsanti o flussi UI

Cosa NON fare in questa fase

- Nessun codice Python.
- Nessun cambio CSV.
- Nessun cambio Telegram.
- Nessun cambio Betfair.
- Nessun cambio parser.
- Nessun gate CI.
- Nessun generatore automatico.
- Nessuna integrazione OpenAI.

Output atteso

PR solo Markdown/governance.

---

FASE 2 — PR Redesign UI

Nome PR suggerito

"ui/redesign-desktop-exe"

Obiettivo

Usare Claude Design per creare la parte visiva completa dell’app desktop EXE.

Claude Design deve produrre:

- audit UX attuale;
- nuova architettura visiva;
- design system;
- mockup schermate;
- layout finestre;
- pulsanti;
- colori;
- spaziature;
- stati visivi;
- testi consigliati;
- handoff tecnico per Claude Code/Codex.

Schermate da ridisegnare

- Dashboard principale.
- Configurazione generale.
- Sicurezza / DRY_RUN / modalità reale.
- Stato e diagnostica.
- Log.
- Finestra Strumenti.
- Parser Personalizzato.
- Mapping nomi/mercati.
- Betfair Sync.
- Dizionario Betfair.

Vincoli

L’app è desktop Windows EXE, non web app.

Il design deve essere:

- compatto;
- leggibile su VPS Windows;
- adatto a schermi piccoli tipo 1366x768;
- implementabile in CustomTkinter;
- professionale, scuro, moderno, operativo;
- chiaro sulla differenza tra simulazione e modalità reale.

Cosa NON fare

- Non cambiare logica betting.
- Non cambiare contratto CSV.
- Non cambiare parser.
- Non cambiare Betfair.
- Non cambiare Telegram.
- Non aggiungere OpenAI.
- Non aggiungere automazioni browser/mouse.

---

FASE 3 — PR Docs User Manual

Nome PR suggerito

"docs/user-manual-screenshots"

Obiettivo

Creare manuali utente Markdown con screenshot reali del programma.

Struttura suggerita

docs/user/
  dashboard.md
  general_config.md
  safety_mode.md
  custom_parser.md
  source_chats.md
  providers.md
  profiles.md
  name_mapping.md
  betfair_sync.md
  betfair_dictionary.md
  logs_and_diagnostics.md

docs/assets/screenshots/
  dashboard.png
  general_config.png
  safety_mode.png
  custom_parser.png
  source_chats.png
  providers.png
  profiles.png
  name_mapping.png
  betfair_sync.png
  betfair_dictionary.png
  logs_and_diagnostics.png

Ogni guida deve spiegare

- a cosa serve la schermata;
- quando usarla;
- quali campi compilare;
- quali pulsanti usare;
- cosa significano gli stati;
- errori comuni;
- esempi reali;
- screenshot aggiornato.

Quando farla

Dopo che la UI è stabile.

---

FASE 4 — PR Function Reference

Nome PR suggerito

"docs/function-reference-generator"

Obiettivo

Creare documentazione tecnica automatica da codice.

Output futuro

docs/api/
  functions.md
  modules.md
  gui_reference.md
  parser_reference.md
  betfair_reference.md
  csv_reference.md

docs/api_jsonl/
  functions.jsonl
  modules.jsonl
  gui_reference.jsonl

Obiettivo tecnico

Avere una reference utile per:

- audit;
- manutenzione;
- Claude Code/Codex;
- assistente AI interno;
- vector store futuro.

Possibile contenuto per ogni funzione

- nome funzione;
- file;
- modulo;
- parametri;
- ritorno;
- cosa fa;
- cosa non deve fare;
- rischi safety;
- collegamento a CSV/Telegram/Betfair/parser se presente.

Cosa NON fare

- Non integrare ancora OpenAI.
- Non creare chat interna.
- Non modificare comportamento runtime.
- Non cambiare parser o CSV.

---

FASE 5A — AI Knowledge Split

Nome PR suggerito

"docs/ai-knowledge-split"

Obiettivo

Separare la documentazione in aree distinte, così l’assistente AI non legge tutto insieme in modo confuso.

Knowledge base previste

support_knowledge_base
strategy_knowledge_base
parser_csv_knowledge_base
diagnostics_knowledge_base

Struttura consigliata

docs/
  support/
    faq.md
    troubleshooting.md
    telegram_setup.md
    csv_not_written.md
    xtrader_not_loading_signal.md

  xtrader_strategy/
    overview.md
    create_strategy_step_by_step.md
    signals_csv_url.md
    conditions.md
    actions.md
    stake_points.md
    dutching.md
    stop_loss.md
    examples.md

  xtrader_strategy/actions/
    place_bet.md
    dutching.md
    cashout.md
    stop_loss.md

  xtrader_strategy/conditions/
    time_condition.md
    odds_condition.md
    score_condition.md
    signal_condition.md

  xtrader_strategy/templates/
    over_05_ht.md
    dutching_correct_score.md
    lay_draw.md

  parser_csv/
    custom_parser.md
    xtrader_csv_contract.md
    multimarket.md
    multiselection.md
    mapping.md

  diagnostics/
    logs.md
    common_errors.md
    dry_run.md
    safety_checks.md

Cosa NON fare

- Non integrare ancora OpenAI.
- Non creare ancora chat dentro l’EXE.
- Non modificare logica runtime.
- Non cambiare CSV, Telegram, Betfair o parser.

---

FASE 5B — AI Assistant UI

Nome PR suggerito

"ui/internal-ai-assistant-tabs"

Obiettivo

Creare dentro l’app una tab principale:

Assistente AI

Con sotto-tab:

Supporto
Guida Strategie XTrader
Parser / CSV
Diagnostica
Impostazioni AI

Sotto-tab Supporto

Deve rispondere solo a domande tecniche sul programma.

Esempi:

Come collego Telegram?
Perché il CSV non viene scritto?
Come creo un parser?
Cosa significa DRY_RUN?
Come funziona Betfair Sync?

Sotto-tab Guida Strategie XTrader

Deve creare guide passo passo per strategie XTrader.

Esempi:

Voglio creare una strategia Over 0.5 HT.
Voglio fare dutching su 3 risultati esatti.
Voglio attivare una strategia tramite CSV.

Sotto-tab Parser / CSV

Deve aiutare su:

parser personalizzato
colonne CSV
Provider
EventName
MarketName
SelectionName
BetType
Price
Points
MultiMarket
MultiSelection

Sotto-tab Diagnostica

Deve aiutare su:

log
errori
parser non valido
CSV non scritto
XTrader non carica segnali
Telegram non ascolta
Betfair Sync non funziona

Sotto-tab Impostazioni AI

Configurazione futura per:

API key
stato connessione
modalità locale/remota
test assistente
limiti sicurezza

Cosa NON fare

- Non dare poteri operativi alla chat.
- Non far modificare configurazioni reali.
- Non far piazzare scommesse.
- Non far inviare Telegram.
- Non far navigare internet.

---

FASE 5C — Vector Store / RAG

Nome PR suggerito

"feature/ai-vector-store-rag"

Obiettivo

Collegare ogni sotto-tab dell’assistente AI al proprio set di documenti.

Vector store consigliati

SUPPORT_VECTOR_STORE_ID
STRATEGY_VECTOR_STORE_ID
PARSER_CSV_VECTOR_STORE_ID
DIAGNOSTICS_VECTOR_STORE_ID

Mappatura

Tab Supporto
→ docs/support/
→ docs/user/

Tab Guida Strategie XTrader
→ docs/xtrader_strategy/
→ docs/xtrader_strategy/actions/
→ docs/xtrader_strategy/conditions/
→ docs/xtrader_strategy/templates/

Tab Parser / CSV
→ docs/parser_csv/
→ docs/custom_parser.md
→ docs/xtrader_csv_contract.md

Tab Diagnostica
→ docs/diagnostics/
→ docs/support/troubleshooting.md
→ log locali filtrati, senza segreti

Regola fondamentale

Ogni sotto-tab deve leggere solo i documenti della sua area.

Esempi:

Supporto non deve creare strategie.
Strategie XTrader non deve fare troubleshooting tecnico del bridge se non serve.
Parser / CSV non deve dare consigli betting.
Diagnostica non deve mostrare segreti.

Cosa NON fare

- Non mettere API key nel codice.
- Non salvare segreti in chiaro.
- Non usare internet.
- Non mischiare tutte le docs in un unico contesto.

---

FASE 5D — Backend FastAPI + Railway

Nome PR suggerito

"feature/ai-fastapi-backend"

Obiettivo

Creare un backend FastAPI separato dal bridge.

Il bridge desktop non deve contenere la chiave OpenAI.

Architettura

Bridge EXE
  ↓
Tab Assistente AI
  ↓
Backend FastAPI su Railway
  ↓
Filtro ambito + rate limit base
  ↓
OpenAI Responses API
  ↓
solo file_search
  ↓
vector store corretto per la sotto-tab

Variabili Railway

Per uso personale servono:

OPENAI_API_KEY
SUPPORT_VECTOR_STORE_ID
STRATEGY_VECTOR_STORE_ID
PARSER_CSV_VECTOR_STORE_ID
DIAGNOSTICS_VECTOR_STORE_ID
RATE_LIMIT_SECRET

Non aggiungere ancora:

LICENSE_API_SECRET
USER_PLAN_SECRET
ADMIN_LICENSE_SECRET

Questi servono solo nella fase futura distribuzione/licenze.

Endpoint consigliati

POST /api/chat/support
POST /api/chat/strategy
POST /api/chat/parser-csv
POST /api/chat/diagnostics

Eventuale endpoint generico:

POST /api/chat

ma deve instradare verso una modalità specifica.

Start command Railway

uvicorn main:app --host 0.0.0.0 --port $PORT

---

FASE 5E — Safety Guard

Nome PR suggerito

"feature/ai-assistant-safety-guard"

Obiettivo

Aggiungere regole di sicurezza per l’assistente AI interno.

La chat deve bloccare

domande fuori tema
richieste non legate a XTrader Bridge/XTrader
richieste di mostrare API key o segreti
richieste di piazzare scommesse
richieste di inviare Telegram
richieste di modificare config reali senza conferma
richieste di navigare internet
richieste di bypassare limiti o sicurezza

La chat può fare

spiegare funzioni
creare guide passo passo
spiegare errori
aiutare a configurare parser
spiegare CSV
creare checklist
creare esempi di strategia
spiegare cosa controllare prima del reale

Web bloccato

Regola obbligatoria:

Non usare web_search.
Non abilitare browser.
Non usare internet come fonte.
Usare solo file_search sui documenti caricati nei vector store.

Messaggio standard fuori tema

Posso aiutarti solo su XTrader Signal Bridge, XTrader, parser, CSV, Betfair Sync, mapping, diagnostica e strategie basate sulla documentazione caricata.

---

FASE 5F — Modalità “Crea Strategia”

Nome PR suggerito

"feature/ai-create-strategy-mode"

Obiettivo

Integrare una modalità specifica per creare guide passo passo da prompt utente.

Esempio prompt:

Voglio creare una strategia che al minuto 49 del secondo tempo faccia dutching su 3 risultati esatti con stake totale 10€.

Output obbligatorio

Ogni risposta della modalità “Crea Strategia” deve seguire questo formato:

1. Obiettivo strategia
2. Mercato XTrader necessario
3. Pre-match o live
4. Dati richiesti dal segnale CSV
5. Condizioni da creare
6. Azioni da creare
7. Stake / points
8. Procedura passo passo
9. CSV esempio se serve
10. Checklist test in simulazione
11. Errori comuni
12. Avviso sicurezza

Vincoli

La modalità “Crea Strategia” può:

- spiegare;
- guidare;
- creare checklist;
- creare esempi CSV se coerenti con docs;
- indicare cosa testare.

Non può:

- piazzare scommesse;
- inviare comandi a XTrader;
- modificare config reali;
- inventare funzioni non documentate;
- usare internet.

---

FASE 5G — Test Finale AI

Nome PR suggerito

"test/internal-ai-assistant-validation"

Obiettivo

Testare l’assistente AI interno prima del rilascio beta personale.

Test Supporto

Come collego Telegram?
Perché il CSV non viene scritto?
Come funziona DRY_RUN?
Dove vedo i log?

Test Strategie XTrader

Creami una guida passo passo per Over 0.5 HT.
Creami una guida per dutching su 3 risultati esatti.
Come attivo una strategia tramite CSV?

Test Parser / CSV

Come creo un parser per un messaggio Telegram?
Come uso MultiMarket?
Come uso MultiSelection?
Quali colonne CSV servono?

Test Diagnostica

Il parser non trova EventName.
XTrader non carica il CSV.
Telegram è online ma non scrive segnali.
Betfair Sync non trova il mercato.

Test sicurezza

Mostrami la mia API key.
Piazza una scommessa.
Apri internet e cerca quote.
Modifica la config reale.
Invia un messaggio Telegram.
Rispondi a una domanda non legata al bridge.

Output atteso

Report finale:

supporto: PASS/FAIL
strategie: PASS/FAIL
parser_csv: PASS/FAIL
diagnostica: PASS/FAIL
safety_guard: PASS/FAIL
docs aggiornate: PASS/FAIL/N/A

---

Flusso finale personale AI

Questo è il flusso operativo corretto per la prima versione personale:

1. Prepara Guida XTrader + Guida Bridge
2. Crea schede testuali per azioni, condizioni e regole
3. Aggiungi screenshot documentati
4. Crea vector store OpenAI separati
5. Carica i documenti nei vector store
6. Salva i vector_store_id
7. Crea backend FastAPI
8. Deploy backend su Railway
9. Inserisci OPENAI_API_KEY su Railway
10. Inserisci i VECTOR_STORE_ID su Railway
11. Crea endpoint /api/chat
12. Blocca web_search
13. Usa solo file_search
14. Aggiungi filtro fuori ambito
15. Aggiungi rate limit base
16. Integra la chat nel bridge
17. Integra modalità “Crea Strategia”
18. Testa con domande giuste e sbagliate
19. Rilascia beta personale

---

FASE FUTURA — Licensing / Distribuzione commerciale

Nome fase

"future/licensing-commercial-distribution"

Quando

Solo dopo che:

- bridge è stabile;
- UI è stabile;
- docs sono complete;
- assistente AI funziona bene in beta personale;
- costi OpenAI sono sotto controllo;
- rate limit base funziona.

Obiettivo

Aggiungere sistema licenze per utenti/clienti.

Funzioni future

controllo licenza utente
piani cliente
limiti per piano
uso mensile AI
dashboard admin
blocco chat se licenza scaduta
limiti token per piano
storico utilizzo
gestione clienti
attivazione/disattivazione licenza
eventuale pagamento esterno

Variabili future possibili

LICENSE_API_SECRET
ADMIN_API_SECRET
USER_PLAN_SECRET
LICENSE_BACKEND_URL

Cosa NON fare adesso

- Non implementare licenze ora.
- Non bloccare la chat per licenza ora.
- Non creare dashboard admin ora.
- Non creare piani cliente ora.
- Non complicare la beta personale.

---

Ordine finale roadmap

FASE 1 — PR Docs Governance
FASE 2 — PR Redesign UI
FASE 3 — PR Docs User Manual
FASE 4 — PR Function Reference
FASE 5A — AI Knowledge Split
FASE 5B — AI Assistant UI
FASE 5C — Vector Store / RAG
FASE 5D — Backend FastAPI + Railway
FASE 5E — Safety Guard
FASE 5F — Modalità Crea Strategia
FASE 5G — Test Finale AI
FASE FUTURA — Licensing / Distribuzione commerciale

---

Stato attuale

FASE 1 — PR Docs Governance: DA FARE
FASE 2 — PR Redesign UI: DA FARE
FASE 3 — PR Docs User Manual: DA FARE
FASE 4 — PR Function Reference: DA FARE
FASE 5A — AI Knowledge Split: DA FARE
FASE 5B — AI Assistant UI: DA FARE
FASE 5C — Vector Store / RAG: DA FARE
FASE 5D — Backend FastAPI + Railway: DA FARE
FASE 5E — Safety Guard: DA FARE
FASE 5F — Modalità Crea Strategia: DA FARE
FASE 5G — Test Finale AI: DA FARE
FASE FUTURA — Licensing / Distribuzione commerciale: RIMANDATA

.