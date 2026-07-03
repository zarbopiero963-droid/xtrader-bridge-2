# CLAUDE.md

## REGOLA PRINCIPALE

Prima di lavorare su questo repository, leggi e segui `AGENTS.md`.

Questo repository è **XTrader Signal Bridge**, non Pickfair.

Qui il rischio principale non è un motore trading complesso, ma un bridge Telegram → CSV → XTrader: una modifica sbagliata può generare un CSV errato, duplicare un segnale, lasciare un vecchio segnale attivo o far processare chat Telegram non previste.

Il merge resta sempre manuale del repository owner.

---

## QUANDO USARE QUESTO FILE

Usa queste regole per qualsiasi task che:

- modifica `main.py`;
- modifica parser Telegram;
- modifica formato CSV;
- modifica scrittura/svuotamento CSV;
- modifica configurazione o salvataggio impostazioni;
- modifica token/chat Telegram;
- modifica GUI;
- modifica build Windows/EXE;
- richiede commit, push o PR;
- corregge review comments, check rossi, Codacy, DeepSource, CodeRabbit, Sourcery, Gitar o GitHub Actions.

Per domande, spiegazioni o analisi read-only non serve aprire PR.

---

## REGOLE NON NEGOZIABILI

- Non lavorare mai direttamente su `main`.
- Non fare mai merge.
- Non abilitare auto-merge.
- Non creare una seconda PR se esiste già una PR aperta non correlata.
- Non allargare lo scope.
- Non fare refactor generale se il task chiede una correzione specifica.
- Non committare `config.json` reale, token Telegram, chat ID reali, `.env`, CSV generati, log, cache, EXE o ZIP.
- Non stampare token Telegram nei log.
- Non trasformare il bridge in bot di puntata diretta, Betfair API client, browser automation o mouse/keyboard automation, salvo task esplicito del proprietario.
- Non modificare stake, quota, mercato, selezione, bet type, MarketId o SelectionId senza task esplicito.
- Non indebolire il filtro `chat_id`.
- Non lasciare vecchi segnali nel CSV.
- Non generare righe CSV parziali o ambigue.
- Non dichiarare `DONE` finale mentre i check GitHub sono ancora pending/running.
- Non risolvere review thread mentre i check sono ancora in corso.
- Non dichiarare test passati se non sono stati realmente eseguiti.
- Non creare test finti, decorativi o che non esercitano il codice reale.
- Ogni task che modifica codice DEVE generare automaticamente test hard veritieri nuovi o aggiornati che esercitino il comportamento reale del cambiamento — inclusi, quando pertinenti, gli scenari resilienza (crash/power-loss, riconnessione, concorrenza/race, teardown START/STOP, recovery CSV/dedupe/daily, write-failure con rollback): un cambiamento di codice senza test hard corrispondenti è un PR incompleto e NON può dichiarare `DONE`.
- Se una modifica tocca l'aspetto design/UI/UX, DEVI aggiornare `docs/design/design_handoff.md` nello stesso PR **prima** di dirmi che la PR è pronta/mergiabile (o dichiarare `N/A` con motivazione se non ha impatto sul design): un handoff stantio è un PR incompleto. Vedi «GATE DESIGN HANDOFF».
- Non dichiarare `READY_TO_MERGE`: il merge resta sempre manuale.

---

## ORDINE OPERATIVO OBBLIGATORIO

Per ogni task che modifica codice o PR, segui sempre questo ordine:

```text
1. clean branch preflight
2. Phase 0 read-only
3. patch plan
4. patch stretta
5. post-fix micro-audit
6. test hard veritieri locali
7. commit/push
8. aspetta fine di tutti i check GitHub
9. leggi check result + annotations
10. leggi PR comments
11. leggi review bodies
12. leggi inline comments
13. leggi unresolved threads
14. triage finding
15. eventuale nuova patch
16. nuova Phase 0 se serve
17. nuovo micro-audit
18. nuovi test hard veritieri
19. nuovo push
20. aspetta di nuovo fine check
21. final hard verify
22. report finale
```

Non puoi saltare:

- Phase 0;
- micro-audit;
- test hard veritieri;
- check completion gate;
- review/inline/thread triage;
- final hard verify.

---

## FINAL AI REVIEW BEFORE MERGE — CANCELLO LABEL

Due reviewer AI forti e costosi (Claude Fable 5, Fugu Ultra) **non** girano a
ogni push come GPT-5.5/GLM. Spendono (chiamano il modello) **solo** in due casi:

1. **automaticamente** su un push che tocca **file core del bridge** (`main.py`,
   `xtrader_bridge/**`, dipendenze `requirements*`/`pyproject.toml`/`poetry.lock`)
   — analizzano il push-range;
2. **oppure** quando l'agente aggiunge la label finale (gate pre-merge sull'**intera
   PR**):
   - `final-fable-review` → `PR Review Claude Fable 5`
   - `final-fugu-review` → `PR Review OpenRouter Fugu Ultra`

Su push che toccano **solo** workflow/CI, docs o test, i due job partono ma
**escono senza chiamare il modello** (costo zero); quei cambiamenti restano
comunque coperti dai reviewer automatici GPT-5.5/GLM. L'agente **non vede mai le
API key**: aggiunge solo la label; i secret restano nei GitHub Secrets e GitHub
Actions resta read-only sul codice.

La label resta il **gate finale pre-merge obbligatorio**: anche se una PR non ha
toccato file core (quindi i due forti non sono mai partiti da soli), prima di
dichiararla pronta l'agente **deve** far partire le review finali via label.

Fai partire le review finali **solo dopo** che: tutto il lavoro richiesto è
completo; i check/test locali sono stati tentati dove possibile; il branch è
stato pushato; la PR non è draft. Le due label vanno **rimosse e riaggiunte**
(GitHub non emette un nuovo evento `labeled` se la label è già presente):

```bash
PR_NUMBER="$(gh pr view --json number -q .number)"

gh pr edit "$PR_NUMBER" --remove-label final-fable-review || true
gh pr edit "$PR_NUMBER" --remove-label final-fugu-review || true

sleep 2

gh pr edit "$PR_NUMBER" \
  --add-label final-fable-review \
  --add-label final-fugu-review
```

Se in questo ambiente **non** hai `gh` (usi i tool MCP GitHub), l'equivalente è
rimuovere e riaggiungere le due label alla PR via API GitHub
(`issues/{n}/labels`). Le due label devono già esistere nel repo
(`final-fable-review`, `final-fugu-review`); crearle è un'azione una-tantum del
proprietario.

Poi **aspetta** i workflow `PR Review Claude Fable 5` e `PR Review OpenRouter
Fugu Ultra` (rientrano nel CHECK COMPLETION GATE e nella finestra di review). Se
una delle due review segnala bloccanti, security issue, rischi contratto CSV,
rischi Betfair, rischi workflow, rischi gestione segreti o `manual-review-required`,
**non** dichiarare la PR pronta e **non** proporre merge automatico: lascia la PR
aperta e scrivi chiaramente:

```text
AUTO-MERGE DISABILITATO: questa PR richiede merge manuale da parte di Piero.
```

Il merge resta **sempre manuale del proprietario**.

---

## CHECK COMPLETION GATE — OBBLIGATORIO

Prima del controllo finale della PR devi aspettare che tutti i check siano finiti.

Non puoi fare final review, evidence resolve, resolve thread, READY o DONE finale mentre ci sono check ancora in corso.

Devi controllare il current-head della PR e leggere:

- GitHub Actions;
- statusCheckRollup;
- commit statuses;
- Codacy;
- DeepSource;
- CodeRabbit/Sourcery/Gitar se presenti;
- workflow build/test/package.

Sono considerati NON finiti gli stati:

```text
PENDING
QUEUED
IN_PROGRESS
WAITING
REQUESTED
EXPECTED
UNKNOWN
null
empty
```

Se anche un solo check è ancora in corso, fermati e rispondi:

```text
CHECKS_PENDING

Reason:
- I check della PR non sono ancora tutti finiti.

Pending checks:
- <nome check>
```

Quando i check sono pending:

- non dichiarare DONE finale;
- non dichiarare READY;
- non dichiarare READY_TO_MERGE;
- non risolvere thread;
- non dire che i commenti sono coperti;
- non fare merge;
- non aprire un’altra PR;
- non fare patch casuali solo perché stai aspettando.

Dopo ogni push devi ripetere il ciclo:

```text
push → aspetta fine check → leggi risultati → leggi review/commenti/inline → triage → eventuale patch → micro-audit → test → push → aspetta di nuovo
```

Il controllo review/commenti/inline deve essere fatto **dopo** che i check sono finiti, perché alcuni bot pubblicano commenti o annotation solo a check completato.

Una PR non è pronta se i check sono ancora in corso, anche se `python -m py_compile main.py` passa localmente.

---

## FINESTRA DI REVIEW POST-COMMIT — 16 MIN GATE & SWEEP ULTIME 5 PR — OBBLIGATORIO

Motivo: i reviewer AI **non** pubblicano subito. Misurato sulle PR reali del repo, dopo
ogni push gli inline comment arrivano con ritardo: **Codex** tipicamente **+7–12 min**,
**CodeRabbit** **+1–10 min** (e spesso rate-limited di 39–50 min), **Sourcery** in pochi
secondi ma quasi sempre rate-limited. Se la PR viene mergiata troppo presto, quei commenti
(anche P1) **atterrano dopo il merge** e finiscono sepolti in una PR chiusa che nessuno
riguarda. Caso reale: PR #239 mergiata a +9 min, review Codex arrivata **+3 min dopo il
merge** con **2 P1 + 4 P2 mai indirizzati**.

Questa sezione vale per ogni PR. Il merge resta **sempre manuale del proprietario**: questo
gate **non** merga, non blocca il proprietario, e non sostituisce il check completion gate —
**si aggiunge dopo** di esso.

### Gate dei 16 minuti

Quando il lavoro è «pronto per merge» (check verdi + final hard verify locale fatto), **non**
puoi ancora dichiarare `DONE`/`READY` finale finché non sono passati **almeno 16 minuti
dall'ULTIMO push che ha aggiornato il head della PR** (usa l'orario di **push/aggiornamento
del head della PR**, **non** il timestamp del commit git locale: i bot reagiscono quando il
commit viene attaccato alla PR, che può essere molto più tardi di quando è stato creato in
locale). La finestra dei 16 minuti copre il ritardo **tipico** della review inline (Codex,
CodeRabbit non rate-limited).

Un reviewer **rate-limited** è una coda più lunga che i 16 minuti **non** coprono: CodeRabbit
può ritardare di 39–50 min (pubblica un avviso «review limit reached» con l'orario di prossima
disponibilità). Se a fine finestra un reviewer del current-head è ancora pending/rate-limited,
**non** dichiarare `DONE`: continua a sorvegliare (estendi l'attesa fino all'orario annunciato,
oppure passa il testimone al tracciamento post-merge qui sotto) finché quel reviewer non
pubblica o il suo ritardo non è trascorso. Lo sweep ultime 5 PR e la Issue post-merge sono la
rete di sicurezza.

Durante la finestra devi:

- mantenere **attiva la subscription** agli eventi della PR (`subscribe_pr_activity`) così
  intercetti i commenti AI man mano che arrivano;
- programmare un **self check-in** (es. `send_later`/`ScheduleWakeup`) alla scadenza della
  finestra per rileggere la PR;
- riportare lo stato `REVIEW_WINDOW_PENDING` con l'orario di chiusura della finestra, invece
  di `DONE`.

Fallback strumenti: il gate è essenzialmente **attendere e poi rileggere**, non uno strumento
specifico. `subscribe_pr_activity` + `send_later`/`ScheduleWakeup` sono il meccanismo
**preferito**. Se non sono disponibili (es. un runner con solo polling git/GitHub CLI/API),
soddisfa comunque il gate con il **polling**: rileggi check, review, **commenti di
conversazione della PR**, inline e thread non risolti a/dopo la chiusura della finestra via
CLI/API. La mancanza degli strumenti di wake-up
non autorizza mai un `DONE` anticipato e non blocca mai la PR: cambia solo *come* aspetti.

Regole:

- **ogni nuovo push sul head PR RESETTA il timer** a 16 minuti da quel push (i bot rivedono
  il nuovo head);
- non dichiarare `DONE`, `READY`, `READY_TO_MERGE`, non risolvere thread «a finestra aperta»
  prima di aver riletto la PR a fine finestra;
- non fare patch casuali solo perché stai aspettando.

### Persistenza anche se il proprietario merga in anticipo

Il proprietario può mergiare a mano in qualsiasi momento. **Il merge NON chiude la finestra
di review.** Devi comunque completare il watch dei 16 minuti su quella PR, **anche se ora è
mergiata/chiusa**, e a fine finestra rileggerla:

- inline comment / review bodies con `submitted_at` **successivo all'ultimo push**;
- thread **non risolti**;
- soprattutto i commenti con `submitted_at` **successivo al `merged_at`** (i «fantasmi
  post-merge»);
- annotazioni dei check, Codacy/DeepSource/CodeRabbit/Sourcery/Codex se presenti.

Esito a fine finestra:

- **nulla di non risolto** → chiudi: nessuna azione, dichiara lo stato finale.
- **rilevato qualcosa** → va **tracciato**: apri **SEMPRE una Issue GitHub** che registra
  ogni finding (numero PR, head SHA, file:riga, bot, severità P1/P2/nitpick, link al
  commento) così nulla si perde in una PR chiusa; e per i finding **reali/azionabili** apri
  una **nuova PR dedicata** col fix. La PR mergiata **non** si riusa e non ci si stacca sopra:
  la fix PR parte dall'ultimo `main`, cita la Issue, e segue tutto l'ordine operativo (Phase 0,
  micro-audit, test hard veritieri). Una sola Issue può aggregare più finding della stessa PR.

Questo **non** viola «una sola PR aperta alla volta»: la PR precedente è ormai
mergiata/chiusa, quindi la fix PR è la legittima continuazione, non una seconda PR parallela.

### Sweep delle ultime 5 PR chiuse+mergiate

Rete di sicurezza per ciò che fosse sfuggito prima che questa regola esistesse o mentre
nessun agente era attivo. **All'inizio di ogni task (dentro Phase 0) e prima del `DONE`
finale**, ispeziona le **ultime 5 PR chiuse e mergiate** e cerca finding AI non risolti o
post-merge mai indirizzati. Quello che trovi viene **registrato e deduplicato** in una Issue.
**L'apertura della fix PR è differita** se un altro task/PR è già attivo: vincono le regole
«un solo task attivo» / «una sola PR aperta», quindi lo sweep non apre mai una seconda PR
parallela né devia il task corrente. La fix PR per i finding dello sweep si apre **solo**
quando nessun altro PR/task è attivo; fino ad allora la Issue li trattiene.

Deduplica obbligatoria: **prima di aprire una Issue cerca le Issue esistenti** (aperte e
chiuse) per quel finding/PR e **non duplicare**; se esiste già, collega il commento alla
Issue esistente invece di crearne una nuova.

### Stato dedicato

```text
REVIEW_WINDOW_PENDING

PR:
- <numero / head SHA>

Ultimo push sul head PR:
- <SHA> @ <timestamp push/aggiornamento head PR>

Finestra chiude:
- <timestamp push sul head PR + 16 min>

Merge:
- MANUALE (non bloccato da questo gate)

Next allowed action:
- Alla scadenza: rileggere check, review bodies, inline, thread non risolti e
  commenti con submitted_at > merged_at; tracciare in Issue + fix PR se serve.
```

---

## MINI PHASE 0 OBBLIGATORIA

Prima di patchare un task che tocca parser, CSV, Telegram, config, GUI, build o PR, devi fare Phase 0 read-only.

Non modificare file durante Phase 0.

Formato obbligatorio:

```text
XTRADER_BRIDGE_PHASE_0

Task:
- <richiesta>

Detected mode:
- <New task / Current PR repair / Unknown>

Current branch:
- <branch>

File da ispezionare:
- <file>

Comportamento attuale:
- <cosa fa adesso>

Rischi:
- <CSV sbagliato / doppia scommessa / token leak / config persa / chat errata>

Patch stretta:
- <cosa modificare e cosa non modificare>

Test hard veritieri:
- <py_compile / pytest / test mirati / smoke manuale>

Stop conditions:
- <quando fermarsi>
```

Se manca evidenza, se il comportamento è ambiguo o se la modifica può aumentare il rischio di scommessa doppia, fermati con:

```text
NEEDS_MANUAL

Reason:
- Phase 0 could not determine safe scope.
```

---

## MICRO-AUDIT POST-FIX — OBBLIGATORIO

Dopo ogni patch e prima di test, commit, push, resolve thread o DONE finale, devi fare un micro-audit.

Non basta dire “ho modificato il file”. Devi controllare il diff.

Comandi consigliati:

```bash
git status --short
git diff --stat
git diff
```

Il micro-audit deve verificare:

- hai modificato solo i file richiesti dal task;
- non hai toccato file fuori scope;
- non hai aggiunto token Telegram reali;
- non hai aggiunto chat ID reali;
- non hai aggiunto `.env`;
- non hai committato `config.json` locale reale;
- non hai committato CSV generati;
- non hai committato log, cache, EXE, ZIP o artifact;
- non hai abilitato auto-merge;
- non hai introdotto betting diretto;
- non hai introdotto Betfair API;
- non hai introdotto automazione GUI/mouse/browser verso XTrader;
- non hai indebolito filtro `chat_id`;
- non hai rotto svuotamento CSV;
- non hai aumentato rischio doppia scommessa;
- non hai cambiato header CSV senza richiesta;
- non hai fatto refactor largo non richiesto;
- hai aggiornato le docs per il cambiamento (README/docs di dominio/docstring), o hai scritto perché non serviva;
- hai aggiornato `docs/design/design_handoff.md` se la modifica tocca l'aspetto design/UI/UX, o hai scritto perché non ha impatto sul design.

Formato obbligatorio:

```text
POST_FIX_MICRO_AUDIT

Scope:
- PASS / FAIL

Forbidden files:
- PASS / FAIL

Secrets:
- PASS / FAIL

CSV safety:
- PASS / FAIL

Telegram safety:
- PASS / FAIL

Config safety:
- PASS / FAIL

Duplicate-signal risk:
- PASS / FAIL

Manual merge preserved:
- PASS / FAIL

Docs updated:
- PASS / FAIL / N/A
  (PASS = docs aggiornate nello stesso PR · FAIL = codice modificato ma docs mancanti ·
   N/A = modifica puramente interna senza impatto documentale, con motivazione scritta)

Design handoff updated:
- PASS / FAIL / N/A
  (PASS = docs/design/design_handoff.md aggiornato nello stesso PR quando l'aspetto design è
   cambiato · FAIL = aspetto design cambiato ma handoff stantio · N/A = nessun impatto sul
   design, con motivazione scritta)

Result:
- PASS / FAIL

Notes:
- <prove>
```

Se il micro-audit fallisce:

```text
POST_FIX_AUDIT=FAIL

Reason:
- <motivo>

Action:
- no test
- no commit
- no push
- no resolve
- no DONE
```

Puoi continuare solo se:

```text
POST_FIX_AUDIT=PASS
```

---

## TEST HARD VERITIERI — OBBLIGATORIO

I test devono essere veri, mirati e verificabili.

Non puoi dire che un test è passato se non hai realmente eseguito il comando e visto esito positivo.

Vietato:

- inventare risultati;
- scrivere test che fanno solo `assert True`;
- scrivere test che non chiamano funzioni reali del progetto;
- dire “dovrebbe passare” come se fosse PASS;
- usare `|| true` per nascondere fallimenti;
- skippare test senza motivo scritto;
- dichiarare copertura se il test non copre davvero il comportamento;
- dire che GUI, Telegram live, Windows EXE o XTrader live sono testati se non lo sono.

Minimo per modifiche Python:

```bash
python -m py_compile main.py
```

Se esistono test:

```bash
python -m pytest -q
```

Se tocchi parser o CSV, aggiungi o aggiorna test mirati quando pratico.

### Test hard obbligatori per comportamento runtime safety-critical

Per ogni modifica che tocca esecuzione runtime, START/STOP, listener Telegram,
riconnessione/backoff, auto-start, scrittura/svuotamento CSV, coda segnali,
deduplica, limiti giornalieri, conferme XTrader, persistenza config, routing
parser, stato GUI o build Windows, l'agente deve aggiungere o aggiornare
automaticamente test seri, mirati e potenti prima di dichiarare il task completo.

I test devono esercitare funzioni/classi reali del progetto e coprire, dove
praticabile offline, i failure mode più pericolosi:

- blackout/crash: una riga CSV stantia lasciata su disco deve essere rimossa al
  successivo avvio dell'app prima che qualunque auto-start del listener possa
  scrivere di nuovo;
- perdita connessione: policy di reconnect/backoff, STOP durante backoff, nessun
  retry su errori permanenti, e messaggi Telegram più vecchi di `max_signal_age`
  non devono scrivere righe CSV;
- auto-start: default spento, valori malformati fail-closed, token/chat
  obbligatori, modalità reale con conferma esplicita, e START/STOP/chiusura
  manuali devono annullare un auto-start pendente;
- sicurezza CSV: scrittura atomica, nessun file parziale, nessun append
  incontrollato, scritture ripetute senza duplicati/stale, clear a solo header,
  errori di lock/permessi senza corrompere il CSV precedente;
- ciclo vita segnale: deduplica persistente dopo riavvio, rate limit rispettati,
  timeout coda che rimuove segnali scaduti, write failure con rollback di
  queue/dedupe/daily così il segnale resta ritentabile in sicurezza;
- conferme XTrader: confermato/rifiutato rimuove il segnale attivo da coda/CSV,
  notifiche unmatched/unknown non rimuovono nulla, fallimento scrittura CSV dopo
  conferma programma retry sicuro e non riscrive dopo STOP;
- persistenza config: config esistente intatta dopo save fallito, config corrotta
  messa in backup, default sicuri, nessun token/chat ID/path reale committato,
  compatibilità con `%APPDATA%`/cartella utente preservata;
- race runtime: fallimento START non lascia sessione/UI attiva, STOP pulisce il
  CSV attivo della sessione e non un path GUI cambiato, expiry/manual clear/process
  sono serializzati, nessun vecchio poller Telegram sopravvive a un nuovo epoch
  di START.

Se un rischio non è testabile automaticamente perché richiede Windows reale,
Telegram live, XTrader, GUI o riavvio hardware, l'agente deve comunque aggiungere
o aggiornare un test unitario/integration deterministico sulla logica pura e
documentare anche uno smoke test manuale con passi esatti, risultato atteso e
cosa resta non verificato. L'agente non deve dichiarare coperto un comportamento
se il test automatico o manuale non è stato realmente eseguito e riportato con
evidenza vera.

I test hard dovrebbero esercitare funzioni reali, per esempio:

- `parse_message()` con messaggio P.Bet. valido;
- `parse_message()` con input vuoto/non supportato;
- quota con virgola convertita in punto;
- `build_csv_row()` con dati parsati reali;
- `init_csv()` lascia solo header;
- `write_csv()` scrive header + una sola riga;
- scritture ripetute non appendono segnali vecchi;
- header CSV resta nell’ordine atteso;
- nessun token reale richiesto;
- nessuna chiamata live Telegram nei test unitari;
- nessun XTrader installato richiesto nei test unitari.

Formato obbligatorio:

```text
HARD_TEST_EVIDENCE

Commands run:
- <comando esatto>: PASS / FAIL

Exit codes:
- <comando>: <exit code>

What was actually tested:
- <comportamento reale>

What was not tested:
- <GUI / Telegram live / Windows EXE / XTrader live, con motivo>

Test quality:
- REAL / PARTIAL / MANUAL_ONLY

Notes:
- <prove>
```

Se non puoi eseguire test:

```text
TESTS_SKIPPED

Reason:
- <motivo esatto>

Risk:
- <cosa resta non verificato>

Required owner action:
- <comando manuale o ambiente necessario>
```

Se i test sono finti, non eseguiti o solo teorici, non dichiarare `DONE`.

---

## GENERAZIONE AUTOMATICA TEST HARD — OBBLIGATORIO

Per ogni task che aggiunge, modifica o rimuove codice, la creazione di test hard
veritieri NON è opzionale: è parte della patch. Non puoi dichiarare DONE se il
comportamento toccato non è coperto da un test reale, eseguito e visto passare.

Regole non negoziabili:
- Ogni funzione/ramo nuovo o modificato DEVE avere un test mirato che chiama il
  codice reale del progetto (niente assert True, niente mock-only, niente "dovrebbe
  passare", niente || true).
- Il test deve fallire se il bug torna (regressione bloccata), non solo "passare".
- Per ogni fix che nasce da un finding/review/bug, scrivi PRIMA il test che riproduce
  il problema (deve fallire sul vecchio codice), poi la patch che lo fa passare.

Quando il cambiamento tocca aree safety-critical, DEVI aggiungere anche i test hard
di resilienza pertinenti, scegliendo dalla matrice:
- CSV: scrittura atomica, header esatto, una sola riga attiva, svuotamento, nessun
  file parziale/append, rename fallita non corrompe, formula/control-char injection.
- Parser/custom parser: messaggio valido/vuoto/non supportato, quota virgola/punto,
  campi obbligatori mancanti → nessuna riga piazzabile, fuzz su delimitatori/quote.
- Dedupe/daily/queue: duplicato bloccato, rate/daily limit, rollback su write fallita,
  now non finito (NaN/inf) fail-closed, timeout per-segnale, restart riconosce duplicati.
- Runtime/app glue: _start senza chat-filter bloccato, _process write-failure rollback,
  STOP durante write non scrive, _manual_clear usa _active_csv_path, expire-tick retry.
- Resilienza/crash: crash/power-loss tra write e replace (file vecchio intatto),
  daily/dedupe/config atomici dopo kill, CSV stale ripulito all'avvio, reconnect con
  drop_pending_updates, STOP durante backoff, nessun doppio poller (epoch).

Limiti onesti: ciò che richiede ambiente live (GUI reale, Telegram live, Windows EXE,
XTrader reale, file lock Windows reale) va scritto come smoke/manual checklist precisa
e marcato `manual`, NON dichiarato come testato automaticamente.

Il POST_FIX_MICRO_AUDIT e il FINAL_HARD_VERIFY devono includere il controllo
"test hard creati/aggiornati per il cambiamento: PASS/FAIL". Se hai toccato il codice
e non hai toccato nessun test, fermati e verifica: o aggiungi il test, o scrivi la
nota tecnica precisa del perché non serviva (es. fix interno senza impatto su
comportamento/API osservabile).

---

## REVIEW COMMENTS / INLINE COMMENTS — OBBLIGATORIO

Quando lavori su una PR esistente, non limitarti ai check rossi.

Devi leggere e valutare:

- commenti normali della PR;
- corpi delle review;
- inline review comments;
- review threads;
- thread unresolved;
- thread outdated;
- annotazioni dei check;
- Codacy;
- DeepSource;
- CodeRabbit/Sourcery/Gitar se presenti;
- file modificati nella PR;
- current PR head SHA.

Non dire “nessun lavoro necessario” se esistono commenti review attivi, inline thread non risolti, check rossi o annotazioni current-head non analizzate.

Il controllo finale di review, inline comments e unresolved threads va fatto **solo dopo** che tutti i check current-head sono finiti.

### Triage obbligatorio

Classifica ogni finding come:

```text
PATCH_REQUIRED
TEST_REQUIRED
EVIDENCE_RESOLVE
SKIP_OUTDATED
SKIP_DUPLICATE
NEEDS_MANUAL
```

Regole:

- `PATCH_REQUIRED`: patch stretta.
- `TEST_REQUIRED`: aggiungi o aggiorna test mirato.
- `EVIDENCE_RESOLVE`: dimostra che è già risolto.
- `SKIP_OUTDATED`: spiega perché è vecchio.
- `SKIP_DUPLICATE`: collega al finding principale.
- `NEEDS_MANUAL`: se è ambiguo, rischioso o fuori scope.

### Inline comments

Per ogni inline comment:

1. Apri il file indicato.
2. Controlla la riga attuale.
3. Verifica se il commento vale ancora sul current head.
4. Se vale, fai la patch minima.
5. Se non vale più, prepara evidenza.
6. Se non puoi verificarlo, fermati con `NEEDS_MANUAL`.

### Evidence resolve

Non risolvere mai un commento “a sensazione”.

Prima di dire che è risolto devi avere:

- commit SHA;
- file modificato o ispezionato;
- test eseguito;
- risultato test;
- motivo tecnico.

Formato risposta thread consigliato:

```text
Fatto in commit <SHA>

Evidence:
- python -m py_compile main.py: PASS
- <test mirato>: PASS
- File: <path>
```

Se il commento è già coperto:

```text
Already covered / skipped

Reason:
- <outdated / duplicate / already fixed / outside scope>

Evidence:
- <comando test o file ispezionato>
```

### Test obbligatori sui fix review

Se il commento riguarda parser, CSV, Telegram, config, GUI, timeout, duplicati, build o sicurezza:

- esegui almeno `python -m py_compile main.py`;
- aggiungi/aggiorna test mirati se pratico;
- se test automatici non sono pratici, scrivi manual smoke test preciso;
- non dichiarare `DONE` senza evidenza.

### Resolve thread

Puoi marcare un thread come risolto solo se:

- tutti i check current-head sono finiti;
- è current-head;
- non è outdated;
- la patch è stata fatta o il problema è già coperto;
- i test/check rilevanti passano;
- hai permesso/API per risolverlo;
- non serve decisione del proprietario.

Se non puoi risolvere via API, rispondi nel thread con evidenza ma non dichiarare falsamente che è stato risolto.

Il merge resta sempre manuale.

---

## PRIORITÀ TECNICHE DEL REPOSITORY

Preserva sempre:

1. Telegram legge solo messaggi validi e solo dalle chat configurate.
2. Il parser non inventa dati mancanti.
3. Il CSV resta compatibile con XTrader.
4. Il CSV contiene solo il segnale attivo previsto.
5. Il CSV viene svuotato dopo il timeout configurato.
6. START/STOP e chiusura finestra non lasciano thread o polling incoerenti.
7. La configurazione viene salvata e ricaricata senza perdere dati.
8. Token e dati sensibili non finiscono nel repository.
9. Windows rimane il target principale.
10. Il merge rimane manuale.

---

## DOCUMENTAZIONE — AGGIORNAMENTO OBBLIGATORIO

Ogni volta che **aggiungi, modifichi o elimini** codice (funzione, classe, modulo,
comportamento, opzione di config, colonna CSV, regola del parser, value-map, modalità,
gate, GUI), **DEVI aggiornare la documentazione corrispondente nello stesso PR**. Le
docs non devono mai restare disallineate dal codice: una funzione nuova senza doc, o una
rimossa con la doc ancora presente, è un PR incompleto.

In pratica, nello stesso PR aggiorna, quando applicabile:

- **`README.md`** → cambiamenti visibili all'utente o al flusso principale;
- **`docs/custom_parser.md`** → cambiamenti al parser personalizzato;
- **`docs/xtrader_csv_contract.md`** → cambiamenti al contratto CSV, colonne, mapping o
  compatibilità XTrader (se è un breaking change, segnalalo nel PR body);
- **`docs/audit/roadmap.md`** → cambiamenti architetturali, roadmap, safety policy o debito
  tecnico rilevante;
- **`docs/design/design_handoff.md`** → qualsiasi modifica che tocca l'aspetto **GUI / UX /
  design** (schermate, tab, controlli/campi/pulsanti, stati o indicatori dinamici, flussi di
  conferma, palette colori, copy/microcopy della UI, information architecture o le invarianti
  di sicurezza che vincolano la UI). Vedi il **gate obbligatorio** dedicato qui sotto;
- **docstring o commenti tecnici** → per funzioni pubbliche, servizi o moduli non banali
  (nuova/rimossa funzione, classe o modulo: mantieni il docstring in testa e, finché non
  esiste il generatore — vedi sotto — descrivila nel doc di dominio pertinente);
- nuova/rimossa **chiave di config, colonna CSV, modalità di riconoscimento, gate** →
  aggiorna i doc relativi;
- **future guide utente con screenshot** → quando cambiano schermate, pulsanti, finestre o
  flussi UI (obbligatorie appena verranno introdotte le cartelle `docs/user/` e
  `docs/assets/screenshots/`, in una fase successiva).

Il `POST_FIX_MICRO_AUDIT` e il `FINAL_HARD_VERIFY` devono includere il controllo
**"docs aggiornate: PASS/FAIL/N/A"**, dove:

- **PASS** = documentazione aggiornata nello stesso PR;
- **FAIL** = codice modificato ma documentazione mancante;
- **N/A** = modifica puramente interna senza impatto documentale, **con motivazione scritta**.

Se hai toccato il codice e non hai toccato nessuna doc, fermati e verifica se serve
aggiornarne una; se davvero non serve (es. fix interno senza impatto su comportamento/API
documentata), dichiara `N/A` con il motivo. Non considerare completa una PR di codice senza
questo controllo documentale.

### GATE DESIGN HANDOFF — OBBLIGATORIO PRIMA DI PROPORRE IL MERGE

`docs/design/design_handoff.md` è la **fonte unica** consegnata a chi fa il design (UI/UX) e
**non deve mai restare disallineato** dall'app reale. Perciò:

- **Prima di dirmi che la PR è pronta / mergiabile (qualsiasi stato `DONE`/`READY`), DEVI
  prima aggiornare `docs/design/design_handoff.md` nello stesso PR ogni volta che la modifica
  tocca l'aspetto design** — cioè tutto ciò che il handoff descrive: schermate/finestre GUI,
  tab, controlli/campi/pulsanti, stati o indicatori dinamici (ATTIVO/OFFLINE/RICONNESSIONE,
  righe attive N/M, banner modalità reale, CSV bloccato), flussi di conferma / gate
  "frictionful", palette colori o la loro semantica di sicurezza, copy/microcopy della UI,
  information architecture, o le invarianti di sicurezza lato UI.
- L'aggiornamento del handoff deve essere **veritiero e coerente col codice** (label verbatim,
  stati/flussi corretti), esattamente come per il resto delle docs.
- Se la modifica è **puramente interna** e non tocca nulla di ciò che il handoff descrive,
  dichiara **N/A con motivazione scritta** (come per la regola docs generale). Mai saltare in
  silenzio.
- È un **gate, non un consiglio**: una PR che cambia l'aspetto design ma lascia il handoff
  stantio è **incompleta** e non può essere dichiarata pronta al merge. Il merge resta
  comunque **sempre manuale del proprietario**.

Il `POST_FIX_MICRO_AUDIT` e il `FINAL_HARD_VERIFY` devono includere anche il controllo
**"design handoff aggiornato: PASS/FAIL/N/A"** (PASS = handoff aggiornato nello stesso PR
quando l'aspetto design è cambiato · FAIL = aspetto design cambiato ma handoff stantio · N/A =
nessun impatto sul design, con motivazione scritta).

**Obiettivo futuro (non ancora attivo).** In una fase successiva saranno introdotte la
cartella **`docs/api/`** e una **function-reference auto-generata** dal codice (moduli →
classi → funzioni + firma + docstring) in formato **Markdown + JSONL**, utile sia per audit
sia come base per un futuro **assistente AI interno** (vector store OpenAI + screenshot).
Quando il generatore (`tools/gen_api_docs.py` o equivalente) e il relativo **gate CI**
esisteranno, **rigenerare le docs sarà parte obbligatoria** di ogni PR che tocca il codice
(il gate CI fallisce se sono disallineate). **Questa regola non richiede di implementare ora
generatori, gate CI o integrazioni OpenAI**: finché non esistono, vale la regola manuale qui
sopra.

---

## QUANDO TOCCHI IL PARSER TELEGRAM

Devi verificare almeno:

- messaggio valido P.Bet.;
- messaggio vuoto/non supportato;
- quota con virgola e con punto;
- squadre con formato `Home v Away`;
- assenza di quota;
- assenza di chat corretta;
- nessun CSV scritto se il segnale è pericolosamente incompleto.

Non inventare campionato, squadre, quota o mercato se non sono nel messaggio.

---

## QUANDO TOCCHI IL CSV

Devi verificare:

- header esatto;
- ordine colonne;
- compatibilità XTrader;
- una sola riga attiva quando il design è one-signal-at-a-time;
- svuotamento con solo header;
- nessun append incontrollato;
- nessun file corrotto se arrivano due segnali vicini;
- nessuna scrittura se il segnale non è valido.

Se cambi colonne o formato, scrivi chiaramente nel PR body che è una breaking change o che è retrocompatibile.

---

## QUANDO TOCCHI CONFIG / IMPOSTAZIONI

Devi verificare:

- configurazione esistente caricata correttamente;
- nuove impostazioni salvate;
- default sicuri;
- compatibilità con vecchio `config.json`;
- nessun token reale committato;
- nessun path locale hardcoded.

Se il task richiede persistenza anche dopo disinstallazione/reinstallazione, preferisci una cartella utente tipo `%APPDATA%` o `%LOCALAPPDATA%`, spiegando il motivo.

---

## QUANDO TOCCHI GUI

Devi verificare manualmente o descrivere il controllo:

- app avviabile;
- START funziona;
- STOP funziona;
- salvataggio config funziona;
- chiusura finestra ferma il bridge;
- log leggibile;
- nuove impostazioni non confondono l’utente.

Non rimuovere campi essenziali senza richiesta esplicita.

---

## QUANDO TOCCHI BUILD WINDOWS / EXE

Devi verificare:

- workflow YAML valido;
- dipendenze coerenti con `requirements.txt`;
- PyInstaller o build tool configurato correttamente;
- artifact prodotto con nome chiaro;
- nessun segreto incluso nell’EXE o negli artifact;
- build non fa push o merge automatico.

Se non hai eseguito la build reale, scrivi:

```text
Build not run in this environment.
```

Non dire che l’EXE è stato generato se non è vero.

---

## FINAL HARD VERIFY — OBBLIGATORIO

Prima di dire `DONE`, devi verificare:

```text
FINAL_HARD_VERIFY

Phase 0:
- PASS / FAIL

Post-fix micro-audit:
- PASS / FAIL

Hard truthful tests:
- PASS / FAIL / SKIPPED with reason

Hard tests created/updated for the change:
- PASS / FAIL / N/A con motivo

Docs updated for the change:
- PASS / FAIL / N/A con motivo

Design handoff updated for the change:
- PASS / FAIL / N/A con motivo

GitHub checks completed:
- YES / NO

GitHub checks result:
- PASS / FAIL / PENDING

PR comments checked:
- YES / NO

Review bodies checked:
- YES / NO

Inline comments checked:
- YES / NO

Unresolved threads checked:
- YES / NO

Review window (16 min dall'ultimo push sul head PR) rispettata:
- YES / NO / RUNNING (chiude a <timestamp>)

Last-5 PR post-merge sweep:
- YES / NO

Safety invariants:
- PASS / FAIL

Merge:
- MANUAL ONLY

Final status:
- DONE / PARTIAL / NOT DONE / CHECKS_PENDING / REVIEW_WINDOW_PENDING / NEEDS_MANUAL
```

Se anche uno solo di questi punti manca, non dichiarare `DONE`.

Usa:

```text
PARTIAL
```

oppure:

```text
CHECKS_PENDING
```

oppure:

```text
NEEDS_MANUAL
```

secondo il caso.

---

## BRANCH E PR

Nuovo task:

- crea branch dedicato;
- lavora solo sul branch;
- crea una sola PR;
- non fare merge.

Fix PR esistente:

- resta sul branch della PR;
- non creare nuova PR;
- pusha una sola fix mirata quando possibile;
- non fare merge.

Se push/PR non sono possibili:

```text
NEEDS_MANUAL_UPDATE_BRANCH
```

---

## FORMATO RISPOSTA FINALE

Per nuovo task o PR:

```text
DONE / PARTIAL / NOT DONE / CHECKS_PENDING / REVIEW_WINDOW_PENDING / NEEDS_MANUAL

Summary:
- <cosa è stato cambiato>

Branch:
- <branch>

PR:
- <url o numero>

Commit:
- <sha>

Safety:
- <impatto su CSV / Telegram / config / doppia scommessa>

Phase 0:
- PASS / FAIL

Post-fix micro-audit:
- PASS / FAIL

Hard truthful tests:
- <comando>: pass/fail/skipped con motivo

GitHub checks:
- complete/pass/fail/pending con motivo

Review comments handled:
- <thread/comment URL o summary>: fixed/skipped/needs manual con evidence

Files changed:
- <file>

Final hard verify:
- DONE / PARTIAL / NOT DONE / CHECKS_PENDING / REVIEW_WINDOW_PENDING / NEEDS_MANUAL

Notes:
- <limiti, test manuali, cose da sapere>
```

Per check ancora pending:

```text
CHECKS_PENDING

Reason:
- I check current-head della PR non sono ancora tutti finiti.

Current head:
- <SHA>

Pending checks:
- <check name>

Next allowed action:
- Aspettare la fine dei check, poi rileggere check, annotation, review bodies, commenti, inline comments e unresolved threads.
```

Per task bloccato:

```text
BLOCKED / NEEDS_MANUAL

Reason:
- <motivo>

Detected mode:
- <New task / Current PR repair / Unknown>

Current state:
- Branch: <branch o unknown>
- Open PR: <numero o unknown>

Required owner action:
- <azione richiesta>
```

---

## REGOLA D’ORO

Non cercare di “fare tutto”.

Per questo repository è meglio una patch piccola, chiara e sicura che una grande riscrittura.

Il bridge deve restare prevedibile:

```text
Telegram corretto → parsing corretto → CSV corretto → XTrader legge → CSV pulito.
```

Qualsiasi modifica che rompe questa catena deve essere bloccata o approvata esplicitamente dal proprietario.

Il merge resta sempre manuale.