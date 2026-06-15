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
- non hai fatto refactor largo non richiesto.

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

Safety invariants:
- PASS / FAIL

Merge:
- MANUAL ONLY

Final status:
- DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL
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
DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL

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
- DONE / PARTIAL / NOT DONE / CHECKS_PENDING / NEEDS_MANUAL

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