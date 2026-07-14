# Roadmap tecnica — XTrader Signal Bridge

> Documento master. Trasforma i problemi di `archive/known_issues.md` in una sequenza di
> PR piccole, testabili e sicure. Ogni PR ha: obiettivo, task, **test hard**,
> **micro-audit**, **audit di controllo totale**.

> ⚠️ **Rimozione «Betfair Sync» (aggiornamento).** La funzione **Betfair Sync** — login a
> Betfair, client catalogo, motore di sync e auto-sync, storage credenziali, redazione log dei
> segreti e la scheda GUI «🔵 Betfair Sync» — **è stata rimossa**. Il bridge non contatta più
> Betfair, non fa login e non costruisce più il dizionario automaticamente. **Sopravvive** solo
> il **dizionario locale** (`betfair_dictionary.db`) come substrato read-only, ora **popolato a
> mano** dall'utente coi propri campi personalizzati, insieme ai suoi lettori (viewer, mapping
> guidato, nomi squadra, resolver ID). Nel **CSV live** l'arricchimento ID è **staccato**
> (`id_resolver=None`, seam pronto e riattivabile). Rimosse anche le chiavi di config
> `betfair_auto_sync`/`_hour`/`betfair_sync_sports` e il path di stato auto-sync. Le voci PR-P*
> qui sotto che descrivono login/sync/auto-sync restano come **storico**, non come stato attuale.

## Regole di processo (valgono per OGNI PR)

1. Si lavora **solo** sul branch della PR, mai su `main`.
2. **Una PR per volta**, scope stretto, niente refactor non richiesti.
3. Niente segreti nel repo: `config.json` reale, token Telegram, chat ID reali,
   `.env`, CSV generati, log, EXE/ZIP → vietati (vedi `.gitignore`).
4. Per ogni PR: `python -m py_compile main.py` + `pytest` (da PR-02 in poi) devono
   passare; il bridge deve restare avviabile; il CSV resta conforme al contratto.
5. **Check completion gate**: prima di considerare una PR chiudibile bisogna
   aspettare che **tutti** i check GitHub siano finiti (Actions, statusCheckRollup,
   Codacy/DeepSource/CodeRabbit se presenti). Stati `PENDING/QUEUED/IN_PROGRESS/...`
   = non finiti.
6. **Notifica al proprietario**: quando tutti i check sono **verdi** e la PR è
   *mergeable*, l'agente segnala lo stato con:

   ```
   CHECKS_GREEN — PR mergeable. Merge MANUALE del proprietario.
   ```

   L'agente **non** esegue mai il merge, **non** abilita auto-merge, **non** dichiara
   `READY_TO_MERGE`. Il merge resta sempre manuale.
7. Ogni PR deve contenere nel body il **micro-audit** scritto.

## Definition of Done (per PR)

Una PR è chiudibile **solo** se: test passano · README non promette cose non
implementate · il bridge si avvia · CSV conforme al contratto · errori loggati ·
nessun token/dato sensibile nei log · build non rotta · micro-audit scritto nel body ·
tutti i check verdi.

---

## CI / Check per categoria (GitHub Actions)

I check si attivano su **ogni pull request** (non solo su `main`), così una PR che
rompe contratto/logica si vede **prima** del merge. Workflow per **categoria di
rischio** (non uno per singolo file di test):

| Workflow | Trigger | Cosa fa |
|---|---|---|
| `pr-checks.yml` | PR · push main · manuale | job **ubuntu (1×)** separati: `compile`, `contract`, `unit`, `safety`, `integration`, `smoke`, `lint` |
| `windows-tests.yml` | push main/master · label di collaudo · manuale | **Windows (2×)**: intera suite non manuale su `windows-latest`. NON a ogni push/PR (risparmio minuti); parte quando una label `ci-full`/`final-fable-review`/`final-fugu-review` è **presente** sulla PR e, finché resta, **ri-gira a ogni push** (`synchronize`) → collauda sempre il head reale · anche su `workflow_dispatch` |
| `merge-simulation.yml` | label di collaudo · manuale | fonde `main` nel branch PR (no merge reale) → `compileall` + `pytest`; rileva conflitti. Parte con una label `ci-full`/`final-*` presente e ri-gira a ogni push finché resta; **non** su PR senza label |
| `merge-simulation-hard.yml` | manuale · schedulata (notte) | Windows: merge + suite completa + `safety`/`integration` + build EXE + controllo file vietati |
| `forbidden-files.yml` | PR · push main · manuale | blocca `.env`/`config.json`/`*.exe`/`*.zip`/`*.log` e CSV (eccetto `data/dizionario_xtrader.csv`) |
| `build.yaml` | tag `v*` · manuale | job `build` = EXE Windows + artifact; job `build-linux` (#36) = binario **Linux** PyInstaller onefile + artifact `.tar.gz` (`ubuntu-latest`, additivo, build Windows invariata); install dal **lock Linux con hash** se presente, altrimenti legacy; **solo** su tag `v*` (release) o `workflow_dispatch`. AppImage = follow-up #36 PR-B |
| `generate-lockfile.yaml` | PR sui `.in`/lock · manuale | genera `requirements-build.lock` (hash) su **Windows**; consegna via Job Summary; gate anti-stantio + validazione in venv pulito |
| `generate-linux-lockfile.yaml` | PR sui `.in`/lock Linux · manuale | speculare, su **Linux** (#36): genera `requirements-build-linux.lock` (hash) per il job `build-linux`; consegna via Job Summary; gate anti-stantio + validazione |

Il check `contract` (`tests/unit/test_csv_contract.py`) è la barriera che diventa
rossa se cambiano: header/ordine/numero colonne, encoding `utf-8-sig`, `QUOTE_ALL`,
`BetType` (PUNTA/BANCA), `Points` vuoto, `Handicap` 0, o se rientrano `Stake`/`Timestamp`.

> **Branch protection (consigliata, da impostare lato GitHub dal proprietario):**
> rendere *required* i job ubuntu che girano a **ogni PR** — `compile`, `contract`, `unit`,
> `safety`, `integration` — più `forbidden-files` e `commit-gate`. **`windows-tests` e
> `merge-simulation` NON girano su una PR senza label di collaudo** (solo con `ci-full`/`final-*`
> presente, o su dispatch, per risparmiare minuti Windows 2×): non renderli *required* su ogni PR,
> altrimenti una PR senza label resta bloccata in attesa del check. Il gate finale
> (`final-fable-review`/`final-fugu-review`, lanciato comunque pre-merge) li fa scattare; e
> **finché la label resta, ri-girano a ogni push** (`synchronize`) → il collaudo Windows/merge è
> sempre sull'ultimo commit, non su uno snapshot stantio. `merge-simulation-hard` resta manuale/notturna.

### Commit gate (ad ogni commit/push) e profili

Le invarianti principali devono girare **ad ogni commit**, non solo in PR. Il
workflow `commit-gate.yml` (su **ogni push**, qualsiasi branch) esegue:

```bash
python -m py_compile main.py
python -m pytest -q -m "not slow and not manual and not e2e"
```

così un push fallisce se: `main.py` non compila, i test falliscono, il contratto
CSV cambia per errore, un segnale invalido può arrivare al CSV, una chat non
autorizzata può scrivere, un duplicato/stale-clear può corrompere il CSV, o
finiscono segreti/artefatti nel repo (`tests/safety/test_no_secrets_committed.py`).

**Marcatori pytest** (in `pytest.ini`) applicati **automaticamente** per cartella
(`tests/<categoria>/`) via `tests/conftest.py`:
`unit` · `integration` · `safety` · `smoke` · `e2e` · `slow` · `manual`.

**Profili:**

| Profilo | Quando | Selettore |
|---|---|---|
| commit | ogni push | `pytest -m "not slow and not manual and not e2e"` (unit+safety+smoke+integration veloci) |
| pr | ogni PR | `pytest -m "not manual"` (tutta la suite offline **ubuntu**, esclusi i live/manuali). `windows-tests`/`merge-simulation` solo con label di collaudo (`ci-full`/`final-*`) presente — poi a ogni push finché resta — o su dispatch |
| release | pre-release / PR-20 | `pytest -m "not manual"` + `tests/e2e` + stress + build EXE (merge-simulation-hard) |

I test pesanti (stress/chaos/e2e completo/recovery) restano su PR/release; tutto
ciò che può causare una **riga CSV sbagliata o duplicata** sta nel gate di ogni commit.

---

## Contratto CSV XTrader (riferimento per tutte le PR)

> Fonte di verità: **`docs/xtrader_csv_contract.md`** (aggiornato in PR-01 sui CSV di
> esempio reali del team XTrader). Header reale a **14 colonne**:

```text
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points
```

- `Stake` e `Timestamp` **non** sono colonne CSV (vedi `archive/known_issues.md`).
- `BetType` ∈ {`PUNTA` (back), `BANCA` (lay)}. `Points` **vuoto** di default.
  `Handicap` = `0`. `Price`/`MinPrice`/`MaxPrice` possono essere vuoti.
- Encoding `utf-8-sig` (BOM) + `quoting=QUOTE_ALL`.
- Modalità riconoscimento: `ID_ONLY` | `NAME_ONLY` | `BOTH`.

> **Nota:** il contratto a 12 colonne / `BACK`/`LAY` / `Points="1"` citato in versioni
> precedenti di questo documento è **superato** da quello reale qui sopra.

---

## Mappa problema → PR

| Problema (known_issues) | PR che lo chiude |
|---|---|
| #7 .gitignore | PR-00 |
| #4 formato CSV, #14 README, #12 Stake/Min/Max | PR-01 |
| #13 test automatici | PR-02 (+ ogni PR) |
| #9 TELEGRAM_OK | PR-03, PR-11 |
| #6 scrittura atomica, #2 race | PR-05, PR-16 |
| #1 validazione | PR-01, PR-06, PR-10 |
| #3 parser | PR-09 |
| #5 dedup/timestamp | PR-15 |
| #8 chat_id, #11 errori silenziati | PR-11, PR-12, PR-14 |
| #10 validazione GUI | PR-13 |
| #15 build EXE | PR-18 |

---

# PHASE 0 — Base solida e contratto XTrader

## PR-00 — phase-0/repo-baseline-audit
**Obiettivo:** congelare lo stato attuale prima di modificare codice.
**Tecnico:** `docs/audit/archive/current_state.md`, `docs/audit/archive/known_issues.md`,
`docs/audit/roadmap.md`, `.gitignore`.
**Task:** documentare struttura, file, problemi (reali vs README), stato prototipo;
aggiungere `.gitignore` di sicurezza; non toccare la logica del bridge.
**Test hard:** `python -m py_compile main.py` PASS; `git status --short` pulito prima
della PR; README non rimosso; nessun comportamento runtime cambiato.
**Micro-audit:** la PR contiene solo documentazione + `.gitignore`; `main.py`,
workflow e `requirements.txt` **non** nel diff.
**Audit totale:** progetto eseguibile come prima; roadmap scritta; rischi documentati.

## PR-01 — phase-0/xtrader-csv-contract
**Obiettivo:** definire il formato CSV ufficiale per XTrader.
**Tecnico:** header reale a 14 colonne `Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points`;
niente `Stake`/`Timestamp`; `BetType` = `PUNTA`/`BANCA`; `Points` vuoto; `Handicap` `0`;
`utf-8-sig` + `QUOTE_ALL`. `docs/xtrader_csv_contract.md`.
**Task:** aggiornare README col formato reale; creare il contratto; allineare
`CSV_HEADER`; rimuovere l'esempio README con Stake/Timestamp; specificare ID_ONLY/
NAME_ONLY/BOTH.
**Test hard:** header == contratto (14 col, order-sensitive); `BetType` mappa BACK→PUNTA,
LAY→BANCA e blocca valori sconosciuti; `Points` vuoto; `Handicap` `0`; `Price`/`MinPrice`/
`MaxPrice` ammettono vuoto; CSV con solo header valido; `QUOTE_ALL` + BOM.
**Micro-audit:** README, contratto e `CSV_HEADER` dicono la stessa cosa.
**Audit totale:** CSV leggibile da XTrader; README non promette colonne non supportate.

## PR-02 — phase-0/test-suite-baseline
**Obiettivo:** test automatici minimi prima di toccare parser/CSV.
**Tecnico:** `tests/test_csv_contract.py`, `tests/test_parser_basic.py`,
`tests/test_config_basic.py`, `pytest.ini`, `requirements-dev.txt` (pytest).
**Task:** test import `main`; test `CSV_HEADER`; parse messaggio valido minimo; parse
messaggio non valido; il workflow CI esegue i test **prima** del build.
**Test hard:** `python -m pytest -v`; `python -m py_compile main.py`; CI rossa se i test
falliscono.
**Micro-audit:** i test girano senza GUI e senza token reale.
**Audit totale:** da qui nessuna PR passa senza test.

---

# PHASE 1 — Separazione codice e stabilità

## PR-03 — phase-1/core-refactor
**Obiettivo:** separare logica e GUI.
**Tecnico:** `src/xtrader_bridge/{models,parser,csv_writer,config_store,telegram_listener,app}.py`;
`main.py` = solo entrypoint.
**Test hard:** parser/csv_writer/config_store testabili senza GUI; `main.py` compila;
EXE buildabile.
**Micro-audit:** `main.py` piccolo; il parser non importa `customtkinter`.
**Audit totale:** architettura testabile, nessuna funzione rimossa.

## PR-04 — phase-1/config-persistent-appdata
**Obiettivo:** config robusta in `%APPDATA%\XTraderBridge\`.
**Tecnico:** `config.json`, `logs/`, `history/` sotto AppData; `config_version`; migrazione
del vecchio config; backup del config corrotto.
**Test hard:** chiudo/riapro → config resta; sposto EXE → config resta; config corrotta →
backup + default; campo mancante → default.
**Micro-audit:** nessun token nei log; `config.json` non resta accanto all'EXE.
**Audit totale:** impostazioni stabili dopo reinstallazione.

## PR-05 — phase-1/atomic-csv-writer
**Obiettivo:** scrittura CSV atomica (no file parziali per XTrader).
**Tecnico:** scrivi `.tmp` → flush → fsync → rename atomico; `write_atomic()`,
`clear_keep_header()`; retry 3x; `QUOTE_ALL`; encoding configurabile.
**Test hard:** CSV mai senza header; accenti; quota `2,10`; 5 segnali consecutivi;
nessun `.tmp` residuo; errore permessi → log chiaro, no crash.
**Micro-audit:** mai `open('w')` diretto sul CSV finale; mai svuotare l'header.
**Audit totale:** XTrader legge sempre un CSV coerente. **(chiude #2, #6)**

---

# PHASE 2 — Compatibilità XTrader

## PR-06 — phase-2/recognition-modes
**Obiettivo:** scegliere il metodo di riconoscimento.
**Tecnico:** enum `ID_ONLY`/`NAME_ONLY`/`BOTH` in config; validazione pre-scrittura.
**Test hard:** ID_ONLY senza MarketId → errore; NAME_ONLY senza EventName/SelectionName →
errore; BOTH con dati completi → CSV scritto; ogni scarto loggato col motivo.
**Micro-audit:** nessun segnale incompleto in CSV.
**Audit totale:** supporto ai due metodi XTrader.

## PR-07 — phase-2/markettype-catalog-it
**Obiettivo:** catalogo MarketType italiano.
**Tecnico:** `data/market_types_it.json` (`label_it`, `sport`, `enabled`); loader +
validazione + ricerca per codice/label.
**Test hard:** esistono OVER_UNDER_25, BOTH_TEAMS_TO_SCORE, CORRECT_SCORE, DOUBLE_CHANCE,
DRAW_NO_BET; MarketType sconosciuto → errore controllato.
**Micro-audit:** nessun codice duplicato.
**Audit totale:** dizionario MarketType presente.

## PR-08 — phase-2/selectionname-mapping-it
**Obiettivo:** dizionario SelectionName italiano.
**Tecnico:** `data/selection_mapping_it.json` (alias → market_type + market_name +
selection_name).
**Test hard:** OVER 2.5 → OVER_UNDER_25/Over 2,5 gol; GG → BTTS/Sì; NG → BTTS/No;
1/X/2 con `Inter v Milan` → Inter/Pareggio/Milan.
**Micro-audit:** ogni alias produce MarketType+SelectionName; nomi fissi in italiano.
**Audit totale:** segnali → nomi compatibili fonte XTrader italiana.

---

# PHASE 3 — Parser

## PR-09 — phase-3/parser-pbet-robust
**Obiettivo:** parser P.Bet affidabile (emoji + testo).
**Tecnico:** estrae EventName, home/away, quota (virgola/punto), tipo segnale, live/pre,
score, minuto, BACK/LAY; restituisce `ParsedSignal`.
**Test hard:** con emoji → completo; senza emoji → completo; `2,10`/`2.10` → normalizzata;
OVER 2.5 e GG mappati; senza squadre/quota → errore controllato.
**Micro-audit:** il parser non scrive CSV, restituisce solo dati.
**Audit totale:** parsing affidabile su esempi reali e simulati. **(chiude #3)**

## PR-10 — phase-3/signal-validation-engine
**Obiettivo:** validare prima di scrivere CSV.
**Tecnico:** `validator.py` con stati VALID / INVALID_MISSING_EVENT /
INVALID_MISSING_PRICE / INVALID_UNKNOWN_MARKET / INVALID_UNKNOWN_SELECTION /
INVALID_BETTYPE / DUPLICATE.
**Test hard:** BetType ≠ PUNTA/BANCA → invalido; Price non numerico → invalido; MarketType
assente → invalido; SelectionName mancante → invalido; EventName mancante (NAME_ONLY) →
invalido; `Points` vuoto **resta vuoto** (è il default del contratto, NON va normalizzato a "1").
**Micro-audit:** nessun segnale invalido arriva al CSV.
**Audit totale:** CSV solo con segnali coerenti. **(chiude #1)**

---

# PHASE 3-bis — Parser Personalizzato (Custom Parser)

> **Pivot deciso dal proprietario:** un costruttore di parser configurabile dalla
> GUI **supera** il parser hardcoded (PR-09). L'utente definisce *come* estrarre
> ogni colonna del contratto CSV da un messaggio Telegram, senza modificare il
> codice. Il parser hardcoded resta come fallback/legacy.
>
> **Principi (validi per tutta la fase):**
> - Ogni regola ha **"Inizia dopo" (`start_after`)** e **"Finisce prima di"
>   (`end_before`)**: testo libero (anche emoji/simboli) che delimita il valore.
> - Campi **obbligatori vs opzionali**: opzionale vuoto → colonna CSV vuota (NON
>   blocca); obbligatorio vuoto → parser **"Non pronto"** → nessuna riga CSV.
> - Il **dizionario** (`data/dizionario_xtrader.csv`) diventa una **value-map
>   selezionabile** da menu a tendina dentro il costruttore.
> - Persistenza **per-parser** in `data/parsers/<nome>.json` (in `.gitignore`:
>   sono configurazione utente, non si committano).
> - La regola **somma-gol → Over (somma).5** diventa una **trasformazione
>   configurabile** (CP-05), NON è hardcoded.
> - Le colonne ammesse come `target` sono **esattamente** quelle del contratto a
>   14 colonne (fonte unica: `csv_writer.CSV_HEADER`).

## CP-01 — custom-parser/data-model ✅ (consegnato)
**Obiettivo:** modello dati + persistenza del Parser Personalizzato.
**Tecnico:** `xtrader_bridge/custom_parser.py` — `FieldRule` (target, start_after,
end_before, fixed_value, value_map, required) e `CustomParserDef` (name,
description, version, rules); (de)serializzazione JSON; `validate_parser_def`;
`skeleton()`; save/load in `data/parsers/<nome>.json`. `.gitignore`: `data/parsers/`.
**Test hard:** `tests/unit/test_custom_parser_model.py` — round-trip dict/JSON,
validazione (nome vuoto, target sconosciuto/duplicato, `fixed_value`+estrazione,
versione, nessuna regola), skeleton valido, save/load tmp, filename anti-traversal.
**Micro-audit:** nessun runtime/GUI/contratto toccato; `target` ⊆ `CSV_HEADER`.
**Audit totale:** base dati pronta; nessun rischio CSV/Telegram/doppia-scommessa.

## CP-02 — custom-parser/extraction-engine ✅ (consegnato)
**Obiettivo:** applicare le regole di un `CustomParserDef` a un messaggio.
**Tecnico:** `xtrader_bridge/custom_parser_engine.py` — `extract_value(text, rule)`
(fixed/`start_after`/`end_before`, fine-riga su `end_before` vuoto, match
case-sensitive per emoji/simboli) e `apply_parser(defn, text) → ExtractionResult`
(`ready`, `values`, `missing_required`); `ExtractionResult.as_csv_row()` produce
la riga a 14 colonne. NON risolve value-map (CP-03), NON trasforma (CP-05), NON
scrive CSV (CP-04), NON tocca la GUI (CP-06).
**Test hard:** `tests/unit/test_custom_parser_engine.py` — estrazione
fixed/start/end/emoji/multiriga/non-trovato/rifilatura; gate "Non pronto" sugli
obbligatori vuoti; opzionale vuoto non blocca; riga a 14 colonne; testo vuoto.
**Micro-audit:** nessun runtime/GUI/contratto toccato; `as_csv_row` ⊆ `CSV_HEADER`.
**Audit totale:** estrazione configurabile pronta; valore grezzo (no value-map).

## CP-03 — custom-parser/value-map ✅ (consegnato)
**Obiettivo:** tradurre il valore grezzo estratto nel valore esatto XTrader.
**Tecnico:** `xtrader_bridge/value_maps.py` — built-in `bettype` (BACK/LAY +
sinonimi → PUNTA/BANCA), `value_map_from_pairs` (lookup normalizzato, alias
ambigui scartati), `dizionario_value_maps` (mappe `markettype`/`marketname`/
`selectionname` dal dizionario, chiavate sia sugli alias interni sia sugli
**shorthand Telegram** via `mapping.SYNONYMS` — "GG"/"OVER 2.5" risolvono;
valori placeholder `{HOME_TEAM}` esclusi; lato scommessa solo non ambiguo),
`registry(include_dizionario=)`,
`resolve(value, map_name, reg)`. `apply_parser` (CP-02) ora applica la value-map
della regola. Sicuro: mappa sconosciuta / valore non mappato → vuoto → "Non
pronto" (mai un lato/selezione tradotto a caso).
**Test hard:** `tests/unit/test_value_maps.py` — bettype sinonimi/sconosciuto;
costruzione da coppie + ambiguità scartata; mappe da dizionario (fake + reale);
integrazione `apply_parser` (bettype tradotto, lato sconosciuto → "Non pronto",
selezione dal dizionario).
**Micro-audit:** nessun runtime/GUI/contratto toccato; nessun pass-through di
valori non riconosciuti.
**Audit totale:** traduzione alias → valore XTrader pronta e safe.

## CP-04 — custom-parser/validated-row ✅ (consegnato)
**Obiettivo:** dal Parser Personalizzato a una riga CSV validata, pronta alla
scrittura (senza scriverla: l'aggancio ad `app` è CP-09).
**Tecnico:** `xtrader_bridge/custom_pipeline.py` — `build_validated_row(defn,
text, *, value_maps_registry, mode, require_price)` applica `apply_parser`
(CP-02/03), impone i default del contratto (`Handicap`="0", `Points`=""), poi
`validator.validate` (PR-10). Due gate: parser "Non pronto" (`NOT_READY`) +
validator (modalità + `Price`>1.0 + `BetType` PUNTA/BANCA). `PipelineResult`
con `.placeable`; `is_placeable()` scorciatoia.
**Test hard:** `tests/unit/test_custom_pipeline.py` — riga valida piazzabile
(14 col, BetType tradotto, Handicap default); NOT_READY; INVALID_PRICE (1.00);
INVALID_BETTYPE (lato sconosciuto); INVALID_MISSING_FIELDS (MarketType per
NAME_ONLY); `require_price=False` bypassa; `is_placeable`.
**Micro-audit:** nessuna scrittura CSV; `app`/GUI/contratto invariati.
**Audit totale:** segnale custom validato col contratto prima della scrittura.

## CP-05 — custom-parser/transforms ✅ (consegnato)
**Obiettivo:** derivare un valore calcolato da quello estratto (es. somma-gol →
linea Over), configurabile per regola.
**Tecnico:** `xtrader_bridge/transforms.py` — registro di trasformazioni;
built-in `score_to_over` (punteggio "6-0"/"6:0" → "Over 6,5"); `apply`,
`has_transform`, `available_transforms`. `FieldRule.transform` (CP-01); il motore
applica, nell'ordine, **estrazione → trasformazione → value-map**. Sicuro:
trasformazione sconosciuta o input non interpretabile → vuoto (→ "Non pronto").
`validate_parser_def` rifiuta nomi di trasformazione sconosciuti.
**Test hard:** `tests/unit/test_transforms.py` — score_to_over (vari punteggi /
input non validi / sconosciuta); round-trip `transform`; validate nota/ignota;
integrazione `apply_parser` (punteggio → "Over 6,5"; input non valido → "Non pronto").
**Micro-audit:** nessuna scrittura CSV/GUI; fail-closed; contratto invariato.
**Audit totale:** linea Over calcolata dalla somma gol, senza hardcoding nel parser.

## CP-06 — custom-parser/builder-gui ✅ (consegnato)
**Obiettivo:** costruttore del Parser Personalizzato dalla GUI.
**Tecnico:** **controller puro** `xtrader_bridge/parser_builder.py`
(`ParserBuilder`: opzioni a tendina target/transform/value-map/modalità, gestione
regole add/update/remove/move, validazione, save/load, **test-live** via
`custom_pipeline`) — interamente testato in CI. **Vista sottile**
`xtrader_bridge/custom_parser_gui.py` (customtkinter `CTkToplevel`): per-regola
"Inizia dopo"/"Finisce prima di"/valore fisso/trasformazione/value-map/obbligatorio,
aggiungi/rimuovi, salva, prova messaggio. Pulsante "🧩 Parser Personalizzato" in
`app.App`.
**Test hard:** `tests/unit/test_parser_builder.py` (controller: opzioni, regole,
validazione, save/load tmp, test-live piazzabile/non-pronto, copia difensiva);
`py_compile` su app/gui; smoke import GUI con `importorskip(customtkinter)`.
**GUI non avviata in questo ambiente (headless): verifica manuale su Windows.**
**Micro-audit:** logica nel controller testato; i widget non scrivono CSV e non
toccano il contratto; bridge avviabile invariato.
**Audit totale:** l'utente costruisce/prova un parser dalla GUI; merge manuale.

## CP-07 — custom-parser/parser-manager ✅ (consegnato)
**Obiettivo:** decidere quale Parser Personalizzato è attivo, con override per chat.
**Tecnico:** `xtrader_bridge/parser_manager.py` — funzioni pure su config:
`active_parser_name`, `parser_by_chat`, `resolve_parser_name(cfg, chat_id)`
(override per chat → attivo globale → ""), `set_active`/`set_for_chat`
(immutabili), `available_parser_names`, `load_active(cfg, chat_id, dir)` (→
`CustomParserDef` o None = parser hardcoded). Config: `active_parser` (""),
`parser_by_chat` ({}) in DEFAULTS; `app._save_config` li preserva.
**Test hard:** `tests/unit/test_parser_manager.py` — default, risoluzione
globale/override-chat, set immutabili, elenco nomi, load none/mancante/ok/override.
**Micro-audit:** nessuna scrittura CSV; runtime live non ancora agganciato (CP-09);
nessun campo GUI dedicato (selezione UI in CP-09/affinamento).
**Audit totale:** base per attivare un parser per chat; merge manuale.

## CP-08 — custom-parser/import-export ✅ (consegnato)
**Obiettivo:** condividere i parser come file + un parser d'esempio funzionante.
**Tecnico:** `xtrader_bridge/parser_io.py` — `export_parser(defn, dest)` (valida
poi scrive il JSON), `import_parser(src, dir)` (legge/valida/salva via
`save_parser`, fail su corrotto/invalido), `example_parser()` + `fixture_message()`
(parser realistico Match/Esito/Quota/Lato con value-map dizionario+bettype).
**Test hard:** `tests/unit/test_parser_io.py` — export caricabile / rifiuto
invalido (niente file); import valido salva+ricaricabile / corrotto→ValueError /
invalido→ValueError senza salvare / round-trip; example_parser valido e che
produce una riga **piazzabile** end-to-end ("GG"→"Sì", "BACK"→PUNTA, 1,85→1.85).
**Micro-audit:** nessuna scrittura CSV; solo file parser; runtime invariato.
**Audit totale:** import/export sicuri + esempio che prova l'intera catena.

## CP-09 — custom-parser/live-routing ✅ (consegnato)
**Obiettivo:** il Parser Personalizzato attivo diventa il percorso di parsing
live; hardcoded come fallback.
**Tecnico:** `xtrader_bridge/signal_router.py` — `resolve_row(text, cfg, *,
parsers_dir)` → `RouteResult(row, status, source, detail, missing_required)`.
Se per la chat è attivo un parser (CP-07, `parser_manager.load_active`) è
**autoritativo**: produce la riga via `custom_pipeline.build_validated_row`; se
non piazzabile il segnale è scartato (niente ripiego sull'hardcoded). Se nessun
custom è attivo → parser hardcoded storico (`parse_message`→`build_csv_row`→
`validator`). `app._process` ora chiama il router (logica fuori dalla GUI).
**Test hard:** `tests/unit/test_signal_router.py` — fallback hardcoded;
scarto messaggio non valido; custom attivo piazzabile; custom "Non pronto" →
scarto senza fallback; custom inesistente → hardcoded; override per chat.
**GUI/runtime:** `app._process` rifattorizzato (py_compile + test del router);
**flusso live da verificare a mano su Windows**.
**Micro-audit:** custom autoritativo (no doppio parsing); contratto CSV/gate
invariati; nessun segnale scritto se non piazzabile.
**Audit totale:** il Parser Personalizzato guida davvero la scrittura CSV.

## CP-10 — custom-parser/ready ✅ (consegnato)
**Obiettivo:** `CUSTOM_PARSER_READY` — audit end-to-end + documentazione della
PHASE 3-bis (CP-01…CP-09 + tolleranza spazi nei delimitatori).
**Tecnico:** `docs/custom_parser.md` — guida al comportamento reale: regola
(`FieldRule`), estrazione con delimitatori tolleranti agli spazi, trasformazioni,
value-map (bettype + dizionario), gate di sicurezza ("Non pronto", validazione
contratto, gate di contenuto `NO_CONTENT_MATCH`, approvazione chat, parser
autoritativo), routing/override per chat, persistenza per-parser e import/export.
**Test hard:** `tests/integration/test_custom_parser_end_to_end.py` — catena
completa via `signal_router.resolve_row` con funzioni reali: parser d'esempio →
riga a 14 colonne (value-map dizionario+bettype, virgola→punto, default
contratto); tolleranza spazi nei delimitatori fino al router; `score_to_over`
end-to-end; gate "Non pronto" senza fallback; gate di contenuto su parser a soli
valori fissi; chat non approvata → hardcoded; override per-chat.
**Micro-audit:** solo documentazione + test (nessun runtime/GUI/contratto toccato).
**Audit totale:** PHASE 3-bis chiusa; Parser Personalizzato documentato e provato
end-to-end. GUI builder e flusso live restano da verificare a mano su Windows.

## CP-11 — custom-parser/builder-management-gui ✅ (consegnato)
**Obiettivo:** gestire i parser salvati dalla finestra builder, senza editare i
file JSON a mano (lista + nuovo / carica / duplica / elimina).
**Tecnico:** `custom_parser.delete_parser(name, dir_path)` (rimozione per nome,
anti path-traversal via `_safe_filename`, idempotente). Controller puro
`parser_builder.ParserBuilder`: `saved_parsers()` (lista `{name, path}` ordinata,
fallback al nome-file su JSON corrotto), `delete_saved()`, `duplicate_saved()`
(crea una copia **nuova**: rifiuta un nome già esistente, non sovrascrive).
Vista sottile `custom_parser_gui.py`: tendina "Parser salvati" + pulsanti
🆕/📂/📑/🗑 (la duplica chiede il nome con `CTkInputDialog`).
**Test hard:** `tests/unit/test_custom_parser_model.py` (delete per nome,
idempotenza, anti-traversal) e `tests/unit/test_parser_builder.py` (lista
ordinata, cartella assente/vuota, file corrotto, delete, duplica + collisione).
**Micro-audit:** nessun cambio a estrazione/validazione/contratto CSV/routing/chat.
**Audit totale:** la finestra builder ora crea, modifica **e gestisce** i parser;
l'attivazione resta in "📡 Chat sorgenti". GUI da verificare a mano su Windows.

---

# PHASE 4 — Telegram

## PR-11 — phase-4/telegram-listener-hardening
**Obiettivo:** listener più sicuro.
**Tecnico:** `drop_pending_updates=True`; filtro chat diretto; filtro pattern; errori non
silenziati; uso reale di `TELEGRAM_OK`.
**Test hard:** chat autorizzata → processato; non autorizzata → ignorato; messaggio vecchio
→ ignorato; token vuoto → errore chiaro; start/stop 5x → nessun crash.
**Micro-audit:** nessun messaggio processato senza chat autorizzata.
**Audit totale:** listener stabile. **(chiude #8 parziale, #9, #11 parziale)**

## PR-12 — phase-4/multi-chat-source-manager
**Obiettivo:** più chat/canali selezionabili.
**Tecnico:** `source_chats[]` in config (name, chat_id, enabled, provider, mode PRE/LIVE).
**Test hard:** chat PRE → Provider TG_PRE; LIVE → TG_LIVE; disattivata → ignorata; ID
duplicato → bloccato; due chat simultanee → nessun conflitto.
**Micro-audit:** chat ID duplicato bloccato; nome duplicato avvisato.
**Audit totale:** bridge multi-canale.

---

# PHASE 5 — GUI

## PR-13 — phase-5/settings-tabs-ui
**Obiettivo:** GUI a tab.
**Tecnico:** tab Dashboard/Telegram/Chat sorgenti/CSV XTrader/Riconoscimento/Mapping/
Validazione/Log/Avanzate; pulsanti Test CSV e Test Parser.
**Test hard:** cambio tab → valori non persi; salvo/riapro → valori presenti; CSV path
invalido → errore; timeout non numerico → errore; token vuoto → START disabilitato.
**Micro-audit:** ogni campo validato; nessun dato sensibile nei log.
**Audit totale:** configurazione completa dalla GUI. **(chiude #10)**

## PR-14 — phase-5/dashboard-logs-status
**Obiettivo:** stato chiaro del bridge.
**Tecnico:** dashboard (stato listener, ultimo messaggio/segnale/CSV/errore, contatori);
log persistente in AppData; filtri INFO/WARNING/ERROR/SIGNAL.
**Test hard:** errori parser/CSV visibili; segnale valido visibile; restart → log storico.
**Micro-audit:** token mai mostrato nei log.
**Audit totale:** l'utente capisce sempre cosa succede. **(chiude #11)**

---

# PHASE 6 — Deduplica e coda

## PR-15 — phase-6/signal-lifecycle-dedupe
**Obiettivo:** ciclo di vita del segnale.
**Tecnico:** stati RECEIVED→PARSED→VALIDATED→CSV_WRITTEN→WAITING_XTRADER→CONFIRMED/
TIMEOUT/FAILED/DUPLICATE; `signal_id`, `message_hash`; history giornaliera; limite/minuto.
**Test hard:** stesso messaggio 2x → duplicato; due segnali diversi stessa partita →
ammessi; 20/min → limite; restart → duplicati recenti riconosciuti.
**Micro-audit:** la deduplica interna non altera il CSV XTrader.
**Audit totale:** ridotto rischio doppie scommesse. **(chiude #5)**

## PR-16 — phase-6/csv-queue-active-signals
**Obiettivo:** più segnali attivi.
**Tecnico:** modalità `OVERWRITE_LAST`/`APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED`; timeout per
singolo segnale; header sempre mantenuto.
**Test hard:** 3 segnali ravvicinati → 3 righe; timeout segnale 1 → rimosso solo il 1;
header resta; confermato → rimosso/marcato.
**Micro-audit:** nessun segnale ravvicinato perso.
**Audit totale:** flusso multi-segnale. **(chiude #2 residuo)**

---

# PHASE 7 — Conferma XTrader

## PR-17 — phase-7/xtrader-confirmation-reader
**Obiettivo:** leggere le notifiche Telegram di XTrader e capire se il segnale è stato
piazzato.
**Tecnico:** `xtrader_notification_chat_id`, `confirmation_keywords`,
`confirmation_timeout`; match per SignalRef o fallback EventName+MarketName+SelectionName.
**Test hard:** conferma con SignalRef → CONFIRMED; senza SignalRef → fallback; nessun
messaggio entro timeout → TIMEOUT; messaggio errore → REJECTED; conferma di altro segnale →
non associare.
**Micro-audit:** la conferma non genera nuova scommessa; chat notifiche separata dalle
sorgenti.
**Audit totale:** il bridge sa se XTrader ha confermato.

---

# PHASE 8 — Build, release, sicurezza

## PR-18 — phase-8/windows-build-hardening
**Obiettivo:** build EXE stabile.
**Tecnico:** workflow: run tests → py_compile → build → upload artifact; versione app;
nome artifact + data build; allineare README su `build.yaml`.
**Test hard:** CI passa; artifact EXE presente; EXE si apre senza terminale nero; EXE salva
config in AppData; EXE scrive CSV nel path configurato.
**Micro-audit:** l'EXE non contiene token o config personali.
**Audit totale:** build distribuibile. **(chiude #15)**

## PR-19 — phase-8/security-safety-guardrails
**Obiettivo:** evitare uso rischioso.
**Tecnico:** `DRY_RUN`; warning real mode; START bloccato se config critica manca; limiti
segnali/minuto e /giorno; reset contatori.
**Test hard:** DRY_RUN non scrive CSV operativo; limite/minuto funziona; config incompleta
blocca START; warning reale visibile.
**Micro-audit:** nessun automatismo aggressivo; nessuna martingala; nessuna promessa di
profitto.
**Audit totale:** bridge più sicuro per test/simulazione.

---

# PHASE 9 — Audit finale

## PR-20 — phase-9/full-project-audit-release-candidate
**Obiettivo:** audit completo → release candidate.
**Tecnico:** `docs/audit/archive/final_audit.md`, `docs/audit/release_checklist.md`,
`docs/audit/xtrader_simulation_test.md`.
**Task:** audit di codice, README, CSV, parser, mapping, Telegram, config, build, coverage;
test manuale con XTrader in **simulazione**.
**Test hard:** `pytest -v` passa; build EXE passa; bridge riceve segnale test; CSV scritto;
XTrader legge il CSV; segnale verde; strategia simulazione lo usa; XTrader invia conferma
Telegram; bridge marca CONFIRMED.
**Micro-audit:** ogni PR precedente ha lasciato test; nessuna feature solo-README; README ==
comportamento reale.
**Audit totale:** CSV compatibile, parser affidabile, config persistente, multi-chat,
scrittura atomica, log chiari, niente token nei log, build EXE ok, test presenti,
simulazione XTrader superata.

---

## Ordine di esecuzione

```
PHASE 0  PR-00 baseline · PR-01 csv-contract · PR-02 test-suite
PHASE 1  PR-03 refactor · PR-04 config-appdata · PR-05 atomic-csv
PHASE 2  PR-06 recognition · PR-07 markettype · PR-08 selectionname
PHASE 3  PR-09 parser · PR-10 validation
PHASE 4  PR-11 listener · PR-12 multi-chat
PHASE 5  PR-13 settings-ui · PR-14 dashboard
PHASE 6  PR-15 dedupe · PR-16 csv-queue
PHASE 7  PR-17 confirmation
PHASE 8  PR-18 build · PR-19 guardrails
PHASE 9  PR-20 release-candidate
```

> Prima dell'uso reale: sempre XTrader in **Modalità Simulazione**, stake basso, limiti
> chiari, nessuna promessa di profitto. Il merge di ogni PR resta **manuale** del
> proprietario.

---

# AUDIT POST-RELEASE — Claude + Codex (dopo PR #61/#62/#63)

> Audit di controllo totale **read-only** eseguito dopo i merge della fase B
> (B1 #61 chat ascoltate, B2 #62 catalogo parser, B3 #63 declutter GUI).
> Unifica due audit indipendenti:
> - **Claude** — line-by-line dei ~24 moduli safety-critical (tutti quelli che
>   decidono scrittura CSV, filtro chat, dedup, persistenza, segreti, lifecycle).
> - **Codex** — audit read-only con focus su svuotamento CSV manuale, persistenza
>   config, path conferme XTrader, segreti, dipendenze.
>
> Verdetto generale: **codebase robusta e fortemente difensiva** (scritture atomiche,
> rollback completi, fail-safe su bool/NaN/inf, redazione token al sink unico).
> **Nessun bug duplica un segnale** (nessuna doppia scommessa per duplicazione). L'unico
> rischio di "scommessa indesiderata" è la **riga orfana** di A2 (un segnale stantio resta
> nel CSV operativo se si cambia il path da running): è tracciato come finding 🟠, non un
> rischio residuo accettato. Sui bug di parsing l'impatto **non è solo perdita**: **A3**
> perde un segnale, ma **A4** può scrivere una riga con **EventName errato** (riga sbagliata,
> non solo persa) e il percorso custom ha **A10** (bet fisso scritto su un messaggio
> non-segnale). Tutti tracciati sotto, da chiudere nelle PR-A3/PR-A5.

Legenda severità: 🔴 critico · 🟠 medio-alto/alto · 🟡 medio/basso.

## Tabella consolidata (verifica incrociata)

| # | Finding | Fonte | Verifica | Severità | Chiusa da |
|---|---|---|---|---|---|
| A1 | `xtrader_bridge/config_store.py` · `save_config()` **non atomico** (`open(path,'w')`) **e** riporta successo anche se la scrittura fallisce (la GUI logga sempre "Configurazione salvata") | Claude + Codex | ✅ Confermato | 🟠 Medio | PR-A1 |
| A2 | `xtrader_bridge/app.py` · `_manual_clear()` usa il path del **campo GUI**, non `_active_csv_path`: cambiando il path da running e premendo "Svuota CSV ora" resta una **riga orfana** nel CSV operativo reale | Codex | ✅ Confermato | 🟠 Medio | PR-A2 |
| A3 | `xtrader_bridge/parser.py` · `_extract_quota()`: `"Quota X,Y FT"` senza `Prematch:` → quota persa (segnale non scritto) | Claude | ✅ Confermato* | 🟠 Alto* | PR-A3 |
| A4 | `xtrader_bridge/parser.py` · `_find_teams()`: riga con `" v "` in testo libero (senza emoji) scambiata per squadre → **EventName errato scritto nel CSV** (riga sbagliata, non solo perdita: con prezzo/mercato validi `resolve_row()` ritorna VALID per l'evento sbagliato) | Claude + Codex | ✅ Confermato | 🟠 Medio | PR-A3 |
| A5 | `xtrader_bridge/transforms.py` · `_score_to_over()`: nessun cap sulla somma gol (`999-999` → `Over 1998,5`) | Claude | ✅ Confermato | 🟡 Basso | PR-A3 |
| A6 | Token Telegram persistito in `config.json` in chiaro | Claude + Codex | ✅ Fatto — **documentato** (README → Sicurezza: tradeoff, `.gitignore`, redazione log, revoca) | 🟡 Basso | PR-minors |
| A7 | Dipendenze runtime non pinnate (`requirements.txt` usa `>=`) | Codex + CodeRabbit | 🟡 Parziale — floor di **sicurezza/compatibilità**: `customtkinter>=5.2.2` (la 5.2.0 importa `distutils`, rotto su Python 3.12), `python-telegram-bot>=21.0` + `h11>=0.16.0` (la 20.0 trascinava `h11 0.14` vulnerabile, GHSA-vqfr-h8mv-ghfj). **Lock riproducibile completo** (pip-compile/constraints con hash) = follow-up (richiede rete + build Windows) | 🟡 Basso | PR-minors |
| A8 | `xtrader_bridge/mapping.py` · `_index()` e `xtrader_bridge/custom_pipeline.py` · `_default_registry()`: cache globale lazy non sotto lock (doppia costruzione possibile al primo uso concorrente) | Claude | ✅ **Fatto** — double-checked locking con `threading.Lock` su entrambe le cache (`_index` pubblica un dict locale a build finita); test di concorrenza dedicato (8 thread → 1 sola costruzione) | 🟡 Basso | PR-A4 (opz.) |
| A9 | `xtrader_bridge/app.py` · `_start()` imposta `_running=True` e mette la GUI in stato ATTIVO **prima** di `init_csv(csv_path)`, senza catturare `OSError`: con un path CSV non scrivibile/lockato l'avvio si interrompe ma la UI resta "attiva" fino allo STOP manuale (listener non partito) | Codex | ✅ Confermato | 🟠 Medio | PR-A2 |
| A10 | `xtrader_bridge/custom_parser_engine.py` · `matches_message()`: il gate di contenuto accetta **qualsiasi** regola di estrazione non-fissa, anche **opzionale** (non solo i campi-segnale obbligatori). Un parser coi campi scommessa **fissi** + una regola di estrazione opzionale "larga" produce una riga piazzabile su un messaggio **non-segnale** che attiva quella regola → **bet fisso scritto per un messaggio non pertinente** (scommessa spuria, in chat ammessa) | Codex | ✅ **Fatto** — `matches_message()` richiede ora un'estrazione non-fissa che sia **obbligatoria** (`required`) **oppure** su un **campo di riconoscimento rilevante per la modalità** (NAME_ONLY→nomi, ID_ONLY→ID, BOTH→entrambi); un'opzionale "larga" su campo non di riconoscimento non basta + test mirato | 🟠 Medio | PR-A5 |

> **Nota sui riferimenti**: i finding puntano a `file` · `funzione()` (simbolo **stabile**),
> non a numeri di riga, così la roadmap resta valida anche se il codice si sposta.

\* **A3** — il proprietario ha **confermato** che può arrivare `"Quota <quota> FT"` **senza**
`"Prematch:"`: oggi quella quota viene **persa** → severità **Alta**. Il fix (fallback
all'estrazione normale quando manca `Prematch:`, senza alterare il caso con `Prematch:`) è
necessario, con test per entrambi i casi.

## Refutati / non-finding (con motivazione — NESSUNA modifica)

| Finding Codex | Motivo del rifiuto |
|---|---|
| Path conferme (`_process_confirmation`): fare snapshot+restore della coda su write fallita, come `_process` | ❌ Lo snapshot+restore **re-inserirebbe la riga del segnale GIÀ confermato** (comportamento errato). Il design attuale è **corretto**: mantiene la rimozione e fa convergere il CSV via `_expire_tick` (retry `_WRITE_RETRY_DELAY`, ri-schedulato anche su fallimento ripetuto, `app.py:1199-1212`). Resta solo una finestra stantia **limitata nel caso tipico** (lock transitorio: il retry converge al primo tentativo riuscito), ma **senza durata garantita se XTrader tiene il CSV bloccato in modo persistente**: la riga confermata resta su disco finché il lock non si libera; anche la pulizia di STOP/riavvio è **best-effort sullo stesso file bloccato** (`_clear_stale_csv` cattura l'`OSError` e avvisa), quindi rimuove la riga solo quando la scrittura riesce, cioè a lock rilasciato. Stessa classe di rischio del path di scadenza già accettato, dichiarata qui onestamente (#242/PR#64). |
| `try/except ImportError` attorno agli import Telegram (`app.py:44-49`) | ❌ Idioma standard per **dipendenza opzionale**: la GUI deve poter partire senza `python-telegram-bot`, con errore chiaro al START tramite il flag `TELEGRAM_OK` (usato a `app.py:693`). Il `CLAUDE.md` del repo **non** lo vieta. Rimuoverlo romperebbe l'avvio GUI senza Telegram. Won't-fix con motivazione. |

## Moduli verificati PULITI (line-by-line, nessun bug)

`csv_writer` · `mapping` · `signal_dedupe` · `signal_gate` · `signal_router` · `signal_queue`
· `validator` · `live_guard` · `safety_guard` · `custom_pipeline`
· `confirmation_reader` · `source_manager` · `profile_store` · `parser_io` · `event_log`
· `diagnostics` · `recognition` · `value_maps` · `message_freshness` · `app.py`
(`_process`/rollback, `_stop`/`_on_close`, `_log` con redazione token, `_expire_tick`,
`_process_confirmation`).

**Eccezioni — NON clean:** in `app.py`, `_start` (A9: `init_csv` senza guard `OSError`) e
`_manual_clear` (A2: path del campo GUI); nel percorso custom, `custom_parser_engine` ·
`matches_message()` (A10: gate di contenuto troppo permissivo — accetta estrazioni
opzionali). Il resto di `custom_pipeline`/`custom_parser_engine` (estrazione, gate
NOT_READY/Provider/Handicap, ordine transform→value-map) resta verificato pulito.

**Non-finding chiusi durante l'audit:** token nel log persistente → già redatto al sink
`_log`; `SignalTracker.register` senza lock → sicuro (solo il thread listener lo chiama);
warning CodeRabbit "Docstring coverage" → advisory, non bloccante.

**Coverage leggera** (visti via chiamanti, non riga-per-riga): `dizionario`,
`settings_controller`, `settings_validation`, `source_editor`, `autostart`,
`reconnect_policy`, `dashboard_stats`, `log_view`, `parser_manager`, `custom_parser`; GUI
`custom_parser_gui`/`source_chats_gui`/`profiles_gui`. Nessun segnale d'allarme dai chiamanti.

## Sequenza PR di chiusura

```text
PR-A0  audit-roadmap          → questa sezione (documentazione)                 [questa PR]
PR-A1  config-atomic-save     → save_config atomico (tmp+fsync+os.replace) +    [FATTO]
                                 ritorna esito; GUI logga "salvata" solo se ok   (A1)
PR-A2  lifecycle-csv-safety   → _manual_clear usa _active_csv_path se running    [FATTO #66]
                                 (A2) + _start guarda init_csv/OSError senza
                                 lasciare la UI in stato ATTIVO (A9)
PR-A3  parser-hardening       → quota FT fallback (A3) + guard " v " (A4,        [FATTO #67]
                                 poi rimosso) + cap somma/lato gol (A5) + test
PR-min hardening-minori       → doc token plaintext (A6) + pin deps (A7)        [FATTO — questa PR]
                                 [A8 lock cache lazy: FATTO — double-checked locking]
PR-A5  custom-content-gate    → matches_message() richiede una regola di          [FATTO]
                                 estrazione non-fissa che sia OBBLIGATORIA oppure
                                 su campo di riconoscimento rilevante per la modalità:
                                 un parser a campi fissi non scrive su messaggi
                                 non-segnale (A10) + test mirato
```

Ogni PR-Ax: branch dedicato, Phase 0, patch stretta, micro-audit, test hard veritieri,
**una sola PR**, attesa fine check, triage review, merge **manuale** del proprietario.
Obiettivo: a fine sequenza, audit Claude **e** Codex completamente chiusi (DONE).

---

## Roadmap GUI a schede + Mapping squadre/mercati (giugno 2026)

Concordata con il proprietario. **Una PR alla volta**; dopo ogni merge si procede in
automatico con la successiva. Merge sempre **manuale** del proprietario. Verifica visiva
della GUI a carico del proprietario su Windows (l'ambiente CI è headless).

> **Stato:** FASE 1 **completata** — Tappa 1 (Provider+Profili), Tappa 2 (Chat sorgenti +
> rinomina Mapping con aree Calcio/Mercati) e Tappa 3 (Parser nella hub + unico pulsante
> "🧰 Strumenti") implementate e mergiate. Resta la **FASE 2** (mappatura mercati).
>
> **Follow-up (P2 UX, da Codex su #96) — refresh cross-scheda della hub: ✅ FATTO.** Al
> cambio scheda, `ToolsWindow` chiama `refresh_options()` sul pannello mostrato (se lo
> supporta), aggiornando **solo** le liste-opzioni derivate dal config **senza** scartare le
> modifiche in corso: `SourceChatsPanel.refresh_options()` aggiorna il dropdown "Parser" di
> ogni riga (parser appena creato subito visibile); `CustomParserPanel.refresh_options()`
> aggiorna provider del menu colonna Provider, `recognition_mode` per l'anteprima e le
> checkbox dei profili mapping (provider/profilo aggiunto altrove, o cambio profilo, riflessi
> subito). Non era un rischio CSV/scommessa.

### FASE 1 — consolidazione finestra "🧰 Strumenti" a schede
Pattern: il contenuto di ogni finestra-strumento diventa un **Pannello** (`CTkFrame`)
incassabile sia in una finestra standalone (compatibilità) sia come **scheda** della
finestra hub `tools_gui.ToolsWindow`. La hub è disaccoppiata: riceve `(titolo, factory)`.

- **Tappa 1 (questa PR)** — `ToolsWindow` + schede **Provider** (`ProviderPanel`) e
  **Profili** (`ProfilesPanel`); i pulsanti "Provider"/"Profili" aprono la hub sulla
  scheda giusta. Dizionario nomi / Chat sorgenti / Parser restano finestre separate (stato
  transitorio).
- **Tappa 2** — scheda **Chat sorgenti** + rinomina **"Dizionario nomi" → "Mapping"** con
  **due aree**: **Calcio** (nomi squadre **+ campionati**) e **Mercati** (area predisposta,
  vuota).
- **Tappa 3** — scheda **Parser Personalizzato**; poi un unico pulsante **🧰 Strumenti** al
  posto dei cinque.

### FASE 2 — mappatura mercati (sensibile: CSV → scommessa)
> **Design doc:** [`docs/audit/mercati_mapping_design.md`](mercati_mapping_design.md) — da
> approvare (domande aperte D1–D4) PRIMA di scrivere codice.
- **Design doc** del riconoscimento mercati **a frase**: modello dati, persistenza
  per-profilo, punto di intervento nel runtime (nel router, **prima** del CSV), **regola
  di precedenza** (regola-colonna del parser **vince** sul dizionario; il dizionario riempie
  solo se il parser non ha estratto il mercato) e **fail-safe** (nessun match ⇒ **nessun
  mercato inventato**, niente CSV ambiguo).
- **Store mercati** (funzioni pure + test), **GUI Mercati** (menù a tendina dal Catalogo
  XTrader, come nel Parser), **aggancio nel Parser** (selettore profilo-mercati accanto a
  quello squadre) + integrazione runtime con test hard.

Obiettivo: il Parser Personalizzato può "richiamare" sia il mapping squadre sia il mapping
mercati → riconoscimento più automatico, restando prevedibile e fail-safe.

## #108 — copertura test della GLUE runtime di `app.py` ✅ (test-only)
**Contesto:** l'audit #108 (read-only) segnalava che la logica pura safety-critical è
ben coperta, ma mancavano test automatici della **glue runtime** dentro `app.py`
(START/STOP, `_process`, `_process_confirmation`, `_expire_tick`, `_manual_clear`,
dispatch del listener): quella glue era dichiarata «non testabile in CI» perché
`app.py` importa `customtkinter`/`tkinter`/`telegram`, assenti nell'ambiente headless,
e veniva verificata solo a mano su Windows.

**Tecnico (test-only, nessuna modifica al codice di produzione):** harness headless in
`tests/integration/conftest.py` che installa STUB minimi di `customtkinter`/`tkinter`/
`telegram` in `sys.modules` (`ctk.CTk = object`) PRIMA di importare `app`, così `App` è
istanziabile via `object.__new__` senza avviare Tk; i sink GUI sono shadowati
(no-op/cattura) e i **metodi reali** di `App` vengono eseguiti. Si iniettano solo i
guasti (`write_rows`/`init_csv` che sollevano) e, per isolare la glue di scrittura dal
parser già coperto, `resolve_row`/`should_process`.

**Test hard:**
- `tests/integration/test_app_runtime_glue.py` — `_process` (scrittura ok / write-failure
  con rollback completo e segnale ritentabile / gate `_running` / duplicato che non
  riscrive ma persiste), `_process_confirmation` (conferma rimuove+riscrive / write-failure
  con retry breve `_WRITE_RETRY_DELAY` / gate `_running`), `_expire_tick` (rimuove scaduti e
  svuota / write-failure→retry / gate `_running`), `_manual_clear` (usa `_active_csv_path`
  non il campo GUI / I/O fallito non azzera la coda), `_stop` (svuota coda + CSV ATTIVO,
  non il path GUI cambiato);
- `tests/integration/test_listener_dispatch.py` — `_run_bot`/`_handle` con `ApplicationBuilder`
  finto: `start_polling(allowed_updates=["message","channel_post"], drop_pending_updates=True)`,
  chat ammessa → `_process`, chat notifiche → `_process_confirmation`, chat non ammessa →
  nulla, `channel_post` come `message`, messaggio vecchio → ignorato.

**Resta `MANUAL_ONLY`** (richiede ambiente reale, non automatizzabile in CI; checklist su
Windows): widget GUI reali (click START/STOP, salvataggio form, banner reale, tab, clear
manuale), build/avvio EXE PyInstaller, path `%APPDATA%`, file CSV lockato da XTrader reale,
Telegram live (token invalido, drop di rete, `retry_after`), import CSV in XTrader reale.
Vedi `docs/audit/release_checklist.md` e `docs/audit/xtrader_simulation_test.md`.

**Micro-audit:** nessun file di produzione modificato; nessun token/chat reale; CSV/contratto
invariati; gli stub si installano solo se i moduli reali sono assenti (su Windows i test
usano comunque `object.__new__` + sink shadowati, non aprono finestre). `pytest`: 1104 passed.

## #192 — semantica del commit MULTI-riga (routing per-riga + OVERWRITE + auto-raise)

**Contesto (review post-merge Codex/CodeRabbit su #281).** Un singolo messaggio Telegram può
generare **più righe CSV** (MultiMarket/MultiSelection). Il commit multi-riga
(`write_path.commit_signals`) e il suo instradamento da `app._process` hanno tre invarianti
interdipendenti, indirizzate insieme (kyc + kyh + cap) perché non separabili al confine
dedupe/coda:

- **Routing per-riga (kyc).** Un parser **multi** (`is_multi_row()` = modalità attiva **e** almeno
  una riga `enabled`) instrada SEMPRE da `commit_signals` con **deduplica per-riga**
  (`signal_dedupe.row_dedup_key`), anche quando ORA produce **una sola** riga piazzabile. Senza,
  se lo stesso messaggio in seguito ne genera di più, la riga già scritta (dedupata a
  hash-messaggio) sarebbe riscritta → doppia scommessa. Una modalità accesa **senza righe attive**
  ripiega sulla riga base e resta single-row (dedup legacy a hash-messaggio).
- **Blocco OVERWRITE_LAST = istruzione corrente con provenienza esatta (kyh + provenance).** Il
  blocco riscritto è: righe **nuove** (`WRITE`) del messaggio **più** le righe `DUPLICATE` che sono
  **ancora attive con la STESSA provenienza** (chiave dedup **memorizzata al piazzamento** su
  `ActiveSignal.dedup_key`, confrontata via `queue.active_keys` — **non** ricalcolata dal testo
  corrente combinato con righe di altri messaggi). Con i **valori del messaggio corrente**. Proprietà
  di sicurezza (Codex #281 P1/P2 su `2daeb3c`):
  - un'espansione `A→A+B` **non perde** `A` (kyh);
  - un duplicato **scaduto** dalla coda **non viene rivissuto** (rispetta il clear-timeout: lo
    svuotamento a timeout è dell'expire-tick, non di un reinvio);
  - due regole che risolvono alla **stessa riga** in un messaggio **non** la scrivono due volte
    (dedup intra-blocco);
  - il CSV è riscritto **solo** se il blocco **differisce, per contenuto, dalle righe attive**: un
    reinvio identico non tocca il file (XTrader non riconsuma) e su quel **no-op** i guardrail
    consumati da eventuali chiavi scadute (`clear_delay` > finestra dedup) sono **ripristinati** —
    così un non-write non intacca dedup/limiti né risulta `WRITE` a `_process`;
  - uno shrink `A+B→A` **rimuove** `B`; un blocco vuoto **non** svuota il CSV.
- **Auto-raise del tetto (cap, decisione del proprietario).** In `APPEND_ACTIVE`/
  `QUEUE_UNTIL_CONFIRMED` il tetto `max_active` **non spezza** il blocco di UN singolo messaggio:
  `queue.add(..., force=True)` accoda tutte le righe nuove dell'istruzione anche oltre il tetto,
  invece di scriverne alcune e troncare le altre in silenzio (partial-drop). Il tetto continua a
  limitare l'accumulo **tra messaggi distinti** (percorso single-row). **Tradeoff accettato dal
  proprietario:** in APPEND le righe attive possono superare `max_active` per un blocco multi
  intero; ogni riga scade comunque per timeout (nessun segnale immortale) e la modalità APPEND è
  un'opzione avanzata non-default (il default `OVERWRITE_LAST` tiene un solo blocco alla volta).

**kyW — riconciliazione cross-namespace della dedupe alla transizione di modalità (RISOLTO, PR
dedicata post-#281).** Le due dedupe usano namespace diversi — hash-messaggio (single-row) vs
chiave per-riga (multi) — quindi un cambio di modalità del parser a runtime (multi→single o
single→multi) poteva far sfuggire un duplicato → doppia scommessa. Il tentativo di shadow su #281
era stato revertato perché inquinava il rate-limit. **Fix definitivo:** `SignalTracker` distingue
ora voci **reali** (contano verso il limite/minuto) e **shadow** (solo dedup): il nuovo
`mark_seen(key)` registra un marcatore shadow che **non** consuma capacità/minuto, ed è no-op se la
chiave è già presente. Dopo una scrittura reale, `commit_signal` (single) ombreggia la **chiave
per-riga** della riga, e `commit_signals` (multi) ombreggia l'**hash-messaggio**: così un retry
dello stesso messaggio dopo un cambio di modalità è riconosciuto come `DUPLICATE`. Fail-closed
(al più restrittivo, mai una doppia scommessa). Lo stato serializza il flag reale/shadow
(retro-compatibile coi vecchi state a 2 elementi → reale). Test hard fail-first:
`tests/unit/test_signal_dedupe.py` (`test_mark_seen_blocca_duplicato_ma_non_conta_verso_il_rate_limit`,
`test_mark_seen_noop_se_gia_visto`, `test_mark_seen_shadow_sopravvive_al_riavvio`) e
`tests/unit/test_multirow_192.py` (`test_transizione_single_a_multi_blocca_riga_gia_scritta`,
`test_transizione_multi_a_single_blocca_messaggio_gia_processato`).

**kyX — audit/display della scrittura riuscita riflette la riga DAVVERO scritta (RISOLTO, PR
dedicata post-#287).** Nel ramo WRITE di `_process`, la presentazione «ultimo segnale» + log
segnale + audit «Messaggio→CSV» usava `row = rows_to_commit[0]` (la **prima riga candidata**). In un
commit **multi-riga** la prima riga può essere **soppressa** (duplicato scaduto/rate/daily) mentre
una riga successiva è scritta: `rows_to_commit[0]` puntava a una riga **non scritta** → audit
fuorviante (nessun impatto su CSV/coda/dedup — il file su disco era già corretto, solo la riga
*mostrata* era sbagliata). **Fix:** si sceglie `written_row = next((r for r in rows_to_commit if r in
commit.rows), row)` — la **prima riga del messaggio effettivamente presente tra le righe attive
scritte** (`commit.rows`), con fallback a `row`. Single-row e multi con **tutte** le righe scritte →
`written_row == row` (comportamento invariato). Il ramo NON-write (scarto/DRY_RUN, che non scrive il
CSV operativo) resta su `row`: è diagnostica del «riconosciuto», non dello «scritto». Test hard
fail-first: `tests/integration/test_app_runtime_glue.py`
(`test_process_multi_display_riflette_riga_scritta_non_soppressa`,
`test_process_multi_tutte_scritte_display_resta_prima_riga`).

**kyZ — base bloccata non deve fermare le righe multi che completano il campo (RISOLTO, PR dedicata
post-#289).** In `build_validated_rows`, un campo della **riga base** riempito però da ogni riga
multi (es. `SelectionName` obbligatorio in `NAME_ONLY`, fornito da ogni MultiSelection) bloccava la
base — `NOT_READY` (obbligatorio della regola) o `MARKET_MAPPING_MISSING` (mercato incompleto,
nessuna frase combacia) → `_BASE_BLOCKING` → ritorno `[base]` **prima** degli override → **zero
righe generate** a runtime. **Fix:** quando l'output multi è attivo e la base è bloccata per un
motivo **colmabile** (`_MULTI_RESOLVABLE` = `NOT_READY`/`MARKET_MAPPING_MISSING`), la base è
ri-valutata passando `multi_supplied` = le colonne che **ogni** riga generata riempie
(`_multi_supplied_cols`, intersezione su mercati+selezioni). I soli gate **strutturali** trattano
quelle colonne come presenti; la base passa così per mappatura nomi/mercati ed enrichment ID e ogni
riga derivata è validata singolarmente da `validator.validate` (fail-closed per riga). Invarianti di
sicurezza (Codex/CodeRabbit su #290):
- **P1** — si rilassano **solo** gli obbligatori mancanti che sono in `multi_supplied`; un
  obbligatorio **non** coperto (es. un `MarketName` richiesto che il validator non ri-controlla)
  resta `NOT_READY` → nessuna riga (un messaggio dichiarato incompleto **non** raggiunge il CSV);
- **market-mapping** — il fallback `_row_has_market` considera coperti i campi mercato forniti dal
  multi, evitando un falso `MARKET_MAPPING_MISSING`, ma resta fail-closed se il mercato **non** è
  coperto;
- gli **altri** stati (`INVALID_MISSING_PROVIDER`, `INVALID_HANDICAP`, `MAPPING_MISSING`) restano
  bloccanti (provider/handicap/evento mancante **non** è colmabile da una riga multi);
- il re-run copia i kwargs prima di iniettare `multi_supplied` (nessun `TypeError` da chiave doppia);
- **`multi_supplied` è interno**: qualsiasi valore passato dal chiamante viene **scartato** prima
  della prima valutazione (CodeRabbit Major) — solo le colonne calcolate dalle regole multi
  realmente attive rilassano i gate, mai colonne arbitrarie del chiamante;
- **Handicap per riga derivata** (Codex): un override `handicap` malformato non passa dal gate
  `INVALID_HANDICAP` della base (che vede l'Handicap base, default "0") e `validator.validate` non
  controlla l'Handicap → il formato è ora ri-verificato su **ogni riga derivata** in
  `_validated_multi_row` (fail-closed, vale anche nel percorso multi normale).

**ID per riga derivata (RISOLTO, follow-up post-#291).** Prima, in `ID_ONLY` con `id_resolver`, gli
ID non venivano risolti **per riga derivata** (la base risolve con selezione vuota e
`_apply_multi_rule` azzera gli ID al cambio selezione) → un MultiSelection in ID_ONLY non produceva
righe con ID. **Fix:** la risoluzione ID è estratta in `_resolve_ids_into` (additiva / fail-open /
NON distruttiva — riempie solo gli ID vuoti, scarta l'arricchimento su conflitto, non blocca su
errore) e applicata sia alla base sia a **ogni riga multi** in `_validated_multi_row`: così ogni
selezione ri-risolve gli ID per sé e un MultiSelection in ID_ONLY è ora piazzabile. Base single-row
bit-identica (stessa logica). Robustezza fail-open (CodeRabbit): un resolver che ritorna un valore
NON dict non fa crashare la pipeline (`isinstance(ids, dict)`). **Gate della base per i parser ID_ONLY
«da GUI» (Codex):** la GUI marca `MarketId`/`SelectionId` obbligatori; se lasciati vuoti per il
riempimento dal dizionario, la base sarebbe `NOT_READY` e la generazione non partirebbe. Quando c'è
un `id_resolver` + sport **e SOLO in `ID_ONLY`**, in `build_validated_rows` gli ID sono trattati come
«forniti» (`multi_supplied`) per il **solo** gate della base — ogni riga è comunque ri-validata dopo
la risoluzione (senza ID risolti → `INVALID` in ID_ONLY), quindi **fail-closed per riga** come kyZ;
senza resolver la base resta bloccata (nessuna scommessa senza ID). La restrizione a `ID_ONLY` è
deliberata (Codex): lì il validator ri-controlla `MarketId`/`SelectionId`, mentre in `NAME_ONLY`/`BOTH`
non li esige → rilassare un ID obbligatorio lascerebbe passare una riga senza ID dichiarata incompleta,
quindi lì l'ID obbligatorio resta bloccante. Per lo stesso motivo si rilassano **solo** `MarketId`/
`SelectionId` (ri-controllati), **non** `EventId` (Codex): un `EventId` obbligatorio resta bloccante se
il resolver non lo riempie. **Anteprima GUI:** `preview_rows` accetta un `id_resolver` opzionale
inoltrato al motore; senza, l'anteprima è **conservativa/fail-closed** per i parser ID_ONLY che
dipendono dal dizionario (vedi `docs/custom_parser.md` §5-bis). Test hard fail-first:
`tests/integration/test_dictionary_id_fallback.py`
(`test_multi_id_per_riga_ogni_selezione_ottiene_i_suoi_id`,
`test_multi_id_per_riga_risoluzione_mista_indipendente`,
`test_multi_id_per_riga_id_only_obbligatori_riempiti_dal_resolver`,
`test_multi_id_per_riga_id_only_obbligatori_senza_resolver_restano_bloccati`,
`test_multi_id_per_riga_resolver_non_dict_non_crasha`,
`test_multi_id_per_riga_fail_open_resolver_che_solleva`,
`test_multi_id_per_riga_senza_resolver_resta_a_nomi`). Test hard fail-first (kyZ):
`tests/unit/test_multirow_192.py`
(`test_kyz_base_not_ready_riempita_da_multiselection`, `test_kyz_altri_gate_base_restano_fail_closed`,
`test_kyz_mapping_applicata_su_righe_derivate_da_base_not_ready`,
`test_kyz_obbligatorio_non_coperto_dal_multi_resta_bloccante`,
`test_kyz_market_mapping_missing_risolto_dalle_selezioni`,
`test_kyz_multi_supplied_gia_in_kwargs_non_crasha`).

**kyb — round-trip del builder preserva i campi multi (VERIFICATO risolto; guard end-to-end
aggiunto post-#290).** Il sospetto «aprire/salvare/duplicare un parser multi lo riverte a
single-row» era **già risolto in #240**: `ParserBuilder.__init__` copia in profondità i campi multi
(`to_dict`→`from_dict`), `to_def` li inoltra tutti, `MultiRowRule.to_dict` = `asdict` (tutti i
campi) e `from_dict` è tollerante. Verificato su `main`. Mancava però un guard **end-to-end su
disco** per i campi per-riga **non esposti** dalla GUI (`min_price`/`max_price`/`points`/
`start_after`/`end_before`) — più `handicap` (esposto) e il flag `enabled` — che devono comunque
sopravvivere al ciclo apri→salva→ricarica: aggiunto
`tests/unit/test_parser_builder_multirow.py::test_kyb_full_disk_roundtrip_preserva_campi_multi_nascosti`
che esercita la catena reale `ParserBuilder → to_def → save_parser (JSON) → load_parser →
ParserBuilder → to_def` e fallisce se un anello scartasse i campi multi (dimostrato con un break
temporaneo di `to_def`). Nessuna modifica al codice di produzione (già corretto).

**Test hard:** `tests/unit/test_multirow_192.py`
(`test_overwrite_last_preserva_riga_attiva_su_espansione`,
`test_overwrite_last_non_rivive_duplicato_scaduto`,
`test_overwrite_last_due_regole_stessa_riga_non_duplica`,
`test_overwrite_last_noop_ripristina_guardrail`,
`test_overwrite_last_shrink_riscrive_e_segnala_write`,
`test_overwrite_last_reinvio_identico_non_riscrive`,
`test_commit_signals_cap_autoraise_scrive_tutto_il_blocco`,
`test_commit_signals_cap_pieno_autoraise_aggiunge_il_blocco`) e
`tests/unit/test_signal_queue.py` (`test_add_force_bypassa_il_tetto`,
`test_add_force_in_overwrite_last_resta_una_sola_riga`). Tutti fail-first sul codice precedente.

## #282 — nomi squadra PERMANENTI dalla sync Betfair (harvest, data layer) ✅ (PR 10)

**Obiettivo (deciso col proprietario).** Rendere i **nomi delle squadre** dei 4 sport
**permanenti**: raccolti durante la sync Betfair e conservati **per sempre**, così
restano disponibili per auto-completare la **mappatura nomi** (colonna `betfair`) anche
quando l'evento finisce.

**Rationale nomi vs ID (invariante di dominio).** Gli identificatori Betfair
(`MarketId`/`SelectionId`) sono **effimeri** by-design: si rigenerano a ogni sync e il
mark-and-sweep (`deactivate_unseen`) li marca `active=0` quando spariscono; il loro ciclo
di vita **non cambia**. I **nomi squadra** invece non scadono nel mondo reale → vanno
conservati. La PR separa nettamente le due cose:

- nuova tabella `betfair_known_teams` (chiave `sport` + `normalized_name`, colonne
  `display_name`/`first_seen_at`/`last_seen_at`), **senza colonna `active`**: non è in
  `_SCOPED`, quindi `deactivate_unseen` la **rifiuta** (`ValueError`) e non può mai
  disattivarla → permanenza **by-construction**;
- harvest dentro la stessa transazione della sync (`CatalogueSync._harvest_teams`): per
  ogni match «Home v Away» (due partecipanti) si fa `upsert_known_team` dei due nomi;
  eventi a un solo nome (torneo/outright) sono saltati; normalizzazione = la **stessa**
  della mappatura nomi (`dizionario.normalize`), così le chiavi combaciano;
- accumulo idempotente (sync ripetute non duplicano); `first_seen_at` fisso,
  `display_name`/`last_seen_at` seguono l'ultima grafia; sport salvato col **nome**
  canonico (reverse map `sports.sport_for_event_type_id`).

**Fuori scope PR 10:** aggancio GUI del menù/mappatura nomi e vista di ripulitura manuale
(→ PR 11 di #282). Contratto CSV **invariato**.

**Test hard (fail-first):** `tests/unit/test_betfair_local_db.py` (upsert/normalizzazione/
first-seen/permanenza-non-disattivabile), `tests/unit/test_betfair_catalogue_sync.py`
(harvest dopo sync, **no-deactivate** quando l'evento sparisce → ID `active=0` ma nomi
restanti, accumulo cross-sync, solo-match-a-due, isolamento per sport),
`tests/unit/test_sports.py` (`sport_for_event_type_id`).

## #282 — precompila la mappatura nomi coi nomi Betfair permanenti ✅ (PR 11)

**Obiettivo (deciso col proprietario).** Rendere **usabili** i nomi squadra permanenti
raccolti in PR 10: nell'area **⚽ Calcio** del Mapping, la colonna **Betfair** va
**precompilata coi nomi reali già iscritti** (nessun menu a tendina — i nomi sono scritti
direttamente nel campo, che resta editabile), così l'utente affianca solo l'**alias** del
canale nel campo Provider.

**Cosa fa.** Pulsante **«📥 Precompila da Betfair»** in `NameMappingPanel`
(`_prefill_betfair_names`): per ogni nome noto (`BetfairLocalDB.known_teams`) aggiunge una
riga con Betfair FISSO, Sport impostato, Tipo `team`, Provider vuoto. **Non distruttivo e
idempotente**: non tocca le righe esistenti, **salta** i duplicati (chiave `sport` + nome
**normalizzato** con `dizionario.normalize`, la stessa del resolver). **Fail-safe**: il
provider è iniettato da `App._known_betfair_teams` (best-effort → `[]` se il DB manca), quindi
senza sync il pulsante avvisa e non aggiunge nulla. **Il testo libero è preservato** (si può
sempre digitare un nome non ancora harvestato → nessuna regressione fail-closed).

**Fuori scope (PR dedicata):** la vista di **ripulitura manuale** (sfoglia per sport +
elimina nomi obsoleti) — richiederà un `delete_known_team` nel DB. #282 resta aperta.

**Test hard:** `tests/unit/test_name_mapping_gui_prefill.py` (append per-nome, dedup
normalizzato, stesso nome/altro-sport non-duplicato, no-profilo/no-provider/vuoto/provider-che-
solleva fail-safe, nome vuoto saltato) esercitando il metodo reale su `self` finto (widget/
provider simulati, nessun display).

## #282 — ripulitura manuale dei nomi squadra permanenti ✅ (PR 11-bis)

**Obiettivo.** I nomi raccolti in PR 10 sono permanenti (mai disattivati dal mark-and-sweep):
crescono nel tempo e possono restare nomi obsoleti/errati (squadre retrocesse/rinominate).
Serviva l'**unico** modo per toglierli: una vista di ripulitura manuale.

**Cosa fa.** Nuova scheda **«🧹 Nomi Betfair»** (`known_teams_gui.KnownTeamsPanel`) nell'hub
Strumenti: sfoglia i nomi per **sport** ed elimina uno per uno con **«🗑 Elimina»**. Backend:
`BetfairLocalDB.delete_known_team(sport, normalized_name)` (chiave esatta, scoping per
sport+nome, ritorna righe eliminate). Wiring via `App._delete_betfair_team` — **busy-guardato**
come la lettura (probe non bloccante + `DictionaryBusy`): un click durante una sync non congela
la GUI (mostra «⏳ …riprova»), best-effort (DB assente → `False`). Chiude #282.

**Non tocca** ID effimeri, CSV, né il flusso di piazzamento.

**Test hard:** `tests/unit/test_betfair_local_db.py` (delete per chiave esatta, no-op su nome
inesistente, nessun delete cross-sport); `tests/integration/test_known_teams_busy.py`
(`_delete_betfair_team`: lock libero → elimina, sync in corso → `DictionaryBusy` fail-fast e
niente eliminazione, DB assente → `False`); `tests/unit/test_known_teams_gui.py` (elenco,
filtro sport, eliminazione+ricarica, fail-fast sync, fail-safe senza provider/callback).


## #283 — valori PERMANENTI di mercato/selezione dalla sync Betfair (harvest, data layer) ✅ (PR 12)

**Obiettivo (deciso col proprietario).** Conservare **per sempre** i valori universali di
**MarketType / MarketName / SelectionName** dei 4 sport raccolti dalla sync, così restano
selezionabili nel Parser anche quando l'evento finisce e gli ID scadono. Decisione: **«diretto»,
nessuna mappatura** (i nomi Betfair IT sono già identici a XTrader), a differenza dei nomi
squadra #282 che restano con mappatura. Estende il modello «permanente» di #282 dai nomi squadra
(→ EventName) ai valori di mercato/selezione.

**Cosa fa.**
- nuova tabella permanente `betfair_known_market_terms` (chiave `sport` + `market_type` +
  `normalized_market` + `normalized_selection`; colonne `market_name`/`selection_name` +
  `first_seen_at`/`last_seen_at`). Il `market_type` è **parte della chiave** (due mercati con
  stesso nome ma tipo diverso non collidono, Fable/GPT #326); `_migrate_market_terms_pk`
  ricrea la tabella + copia i dati (`market_type` NULL → '') su un DB con la vecchia PK a 3
  colonne, così l'`ON CONFLICT` a 4 colonne non fallisce su installazioni preesistenti
  (Fable/Fugu/GLM/GPT #326). **Senza `active`** e **fuori da `_SCOPED`** → il mark-and-sweep
  non la tocca: permanenza by-construction. Ogni riga è la **tupla coerente**
  `(sport, market_type, market_name, selection_name)` (B3 residuo #259: coerenza nome
  mercato↔selezione; «selezione appartiene al mercato»). Metodi `upsert_market_term`,
  `known_market_types`/`known_market_names`/`known_selection_names(sport, market=None)`,
  `count_market_terms`.
- harvest nella stessa transazione della sync (`CatalogueSync._harvest_market_terms`, nel loop
  catalogue): riga **àncora** del mercato (MarketType+MarketName) per ogni mercato **con
  `market_name` valorizzato** (i mercati senza nome sono saltati), e — SOLO per i mercati a
  esiti **universali** — una riga per SelectionName.

**Allowlist safety-critical.** `_UNIVERSAL_SELECTION_MARKET_TYPES` / `_is_universal_selection_market`
(prefix `OVER_UNDER*` + `BOTH_TEAMS_TO_SCORE`/`ODD_OR_EVEN`): solo questi contribuiscono
SelectionName. I mercati **team-dipendenti** (`MATCH_ODDS`, `*_HANDICAP`, `CORRECT_SCORE`,
`DRAW_NO_BET`, `DOUBLE_CHANCE` — su Betfair i suoi runner sono «{Home} o Pareggio», non
«1X/12/X2»: escluso, Fable/Fugu #326, …) hanno esiti = nomi squadra/valori per-partita →
**nessuna selezione** (fissarne uno = riga CSV/scommessa sbagliata). Lista
**conservativa/fail-closed**, estendibile dal proprietario.

**Fuori scope PR 12:** tendine del Parser popolate da questi valori (→ **PR 13** di #283). Contratto
CSV **invariato**. `CORRECT_SCORE` a estrazione dinamica per-riga (FT + primo tempo) tracciato in
**#325**.

**Non tocca** ID effimeri (`MarketId`/`SelectionId`), CSV, parser runtime, né il flusso di
piazzamento: agisce solo sulla nuova tabella permanente.

**Test hard:** `tests/unit/test_betfair_local_db.py` (upsert àncora+selezione, dedup normalizzato,
`first_seen` fisso, distinti per sport, coerenza selezione↔mercato, permanenza — deactivate_unseen
la rifiuta, whitelist colonna); `tests/unit/test_betfair_catalogue_sync.py` (allowlist:
SelectionName solo dai mercati universali e **mai** i nomi squadra di MATCH_ODDS; MarketType/Name
per tutti; no-deactivate quando l'evento sparisce; sync ripetuta non duplica; isolamento per sport;
helper `_is_universal_selection_market`). Fail-first verificato via stash (14 test falliscono senza
il codice).


## #283 — tendine MarketType/MarketName/SelectionName nel Parser dai valori permanenti ✅ (PR 13)

**Obiettivo.** Rendere **selezionabili** nel Parser i valori permanenti harvestati in PR 12: nella
tabella regole, le righe MarketType/MarketName/SelectionName mostrano in «Valore fisso» una tendina
popolata dal dizionario Betfair, **filtrata per lo sport del parser**. Chiude #283 (con PR 12).

**Cosa fa.**
- `app.py` — `_known_market_terms(sport)` **busy-guardato** (probe non bloccante + `DictionaryBusy`,
  come `_known_betfair_teams`): ritorna `{market_types, market_names, selection_names}` filtrati per
  sport, best-effort (DB assente → liste vuote). Iniettato in `_make_parser`.
- `custom_parser_gui.py` — in `_add_row`, per `target in (MarketType, MarketName, SelectionName)`
  una **`CTkComboBox` EDITABILE** (non OptionMenu): suggerisce i valori sincronizzati ma il **testo
  libero resta digitabile** (un valore valido non ancora harvestato è inseribile → **nessuna
  regressione fail-closed**). `_fetch_market_terms`/`_refresh_term_combos` aggiornano i valori al
  **cambio sport** (`_on_sport_change`) e al rientro nell'hub (`refresh_options`), preservando la
  selezione corrente. Il valore è letto da `_sync_to_builder` via `.get()` sullo StringVar (come
  Provider).

**Scope.** La coerenza «selezione appartiene al mercato» resta garantita dal picker «Catalogo
XTrader» (tripla Mercato→Tipo→Selezione); le tendine per-riga offrono i valori per-sport **senza
cascading** Mercato→Selezione (fuori scope, deciso col proprietario). Non tocca contratto CSV,
parser runtime, ID effimeri.

**Test hard:** `tests/unit/test_custom_parser_gui_market_terms.py` (customtkinter stubbato con
StringVar/ComboBox finti ma ispezionabili: la riga term crea una tendina editabile coi valori del
provider per sport, testo libero preservato, refresh mantiene la selezione, sport passato/agnostico
→ None, provider assente/sync in corso → nessun suggerimento; una colonna non-term resta entry);
`tests/integration/test_known_teams_busy.py` (`_known_market_terms`: lock libero → valori per sport,
sync → `DictionaryBusy` fail-fast, DB assente/engine non costruibile → liste vuote). Fail-first via
stash (13 test falliscono senza il codice). Suite: **2011 passed, 10 skipped**.


## #284 — pulsante «📁 Sfoglia…» per CSV Path + salvataggio immediato ✅ (PR 14)

**Obiettivo (deciso col proprietario, opzione b).** Nel tab ⚙️ Generale, accanto al campo CSV
Path, un pulsante **«📁 Sfoglia…»** che apre il selettore file; alla scelta il percorso è scritto
nella casella **E salvato subito** in `config.json` (nessun click extra su «Salva Config»).

**Cosa fa.**
- `app.py` — `_browse_csv_path` (GUI): `filedialog.asksaveasfilename` (`.csv`, `initialdir`/
  `initialfile` dal percorso corrente); annullo → nessuna modifica. `_apply_and_save_csv_path(path)`
  (testabile): applica il percorso alla entry e persiste **subito** facendo **MERGE sul config
  vivo** (`self._config`) — NON rilegge il form, NON tocca gli altri campi safety-critical
  (dry_run/chat/sorgenti), NON esegue i gate di transizione REALE (un cambio file non deve
  promptare). **Non tocca `_active_csv_path`** (il CSV della sessione attiva resta quello di START).
  Pulsante «📁 Sfoglia…» aggiunto alla riga CSV Path della griglia (colonna 2).

**Sicurezza.** Scrive nella stessa entry che oggi si compila a mano (nessun rischio nuovo).
Contratto CSV, parser, Telegram invariati. Nessun path locale reale committato.

**Fix review (round 1).** Guardia token **PR-08c** (CodeRabbit 🟠 + Fugu): come TUTTI i save
NON-form, `_apply_and_save_csv_path` cattura `_had_incomplete_token_load()` PRIMA del save e chiama
`_resync_token_field(had)` DOPO — senza, un «Sfoglia…» col keyring illeggibile al load avrebbe fatto
cancellare il token al «Salva Config» seguente. `asksaveasfilename(confirmoverwrite=False)`
(CodeRabbit nit): scegliere un CSV esistente non è un «salva sopra» → niente prompt fuorviante (il
file non è toccato, si registra solo il percorso). Falsi positivi rebuttati in-thread: leak token in
chiaro (`save_config` instrada al keyring, come `_save_config`) e `result.status` su 2-tupla
(`SaveResult` è una 2-tupla con `.status`, stesso contratto di `_save_config`).

**Test hard:** `tests/integration/test_csv_path_browse.py` (`_apply_and_save_csv_path` via harness
headless + **vera `save_config`** su `CONFIG_FILE` temporaneo): selezione → entry + `csv_path`
salvati e reload conferma la persistenza **preservando gli altri campi** (chat_id/dry_run); path
vuoto/annullo → no-op (nessuna scrittura su disco); **`_active_csv_path` non toccato** a bridge
avviato; **guardia token PR-08c** (`_resync_token_field` chiamato col marker catturato); **ramo
fallimento disco** (ok=False → False + avviso «NON salvato», niente crash su `result.status`). Il
dialog Tk è GUI-only → smoke manuale. Fail-first via stash. Suite: **2016 passed, 10 skipped**.

**Docs:** `docs/design/design_handoff.md` (pulsante + comportamento salvataggio immediato),
`README.md` (nota «📁 Sfoglia…»).


## #285 — pulsanti «📁 Sfoglia…» per Certificato + Private key del Betfair Sync ✅ (PR 15)

**Obiettivo (deciso col proprietario).** Nel tab 🔵 Betfair Sync, un pulsante «📁 Sfoglia…» accanto
a **Certificato (.crt/.pem)** e **Private key (.key)**: `askopenfilename` (file **esistente**;
filtri `*.crt *.pem` / `*.key`), salvataggio **immediato** dei soli percorsi (opzione a).

**Cosa fa.** `betfair/sync_tab_gui.py` — costante `_BROWSE_FILETYPES`, due pulsanti col 2 nella
griglia credenziali, `_browse_path(key)` = askopenfilename → set entry → `self._save()`. Legge/salva
**solo il percorso**, mai il contenuto della chiave privata.

**⚠️ Safety (chiave del design).** `credential_store.save_credentials` **cancella i campi vuoti**:
un salvataggio path-only ingenuo (secret vuoti) cancellerebbe App Key/Password dal keyring.
`_browse_path` riusa quindi `_save()`, che **risolve i secret mascherati** nei valori reali PRIMA
di salvare (non vuoti → riscritti invariati, mai cancellati né lasciati come maschera). Login/sync
read-only invariati.

**Test hard:** `tests/unit/test_sync_tab_browse_paths.py` (customtkinter stubbato, `filedialog`
monkeypatchato): browse cert/key → entry aggiornata + `save_credentials` con **secret RISOLTI**
(non cancellati, non maschera) + nuovo percorso; annullo → no-op; **solo il percorso** (nessuna
`open()` del contenuto chiave). Dialog Tk GUI-only → smoke manuale. Fail-first via stash. Suite:
**2020 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE: pulsanti + salvataggio immediato path). README: **N/A** (cert/key
sono credenziali keyring, non chiavi di `config.json`).


## #286 — pulsante «📄 Crea CSV» (genera un CSV vuoto nel formato XTrader) ✅ (PR 16)

**Obiettivo (deciso col proprietario, opzione A).** Nel tab ⚙️ Generale, accanto a CSV Path, un
pulsante **«📄 Crea CSV»** che **genera** un CSV **a solo header** nel formato XTrader (dal codice,
`CSV_HEADER`/`init_csv`, mai un file committato/bundlato) nella cartella scelta e lo imposta come
`csv_path` (stesso salvataggio immediato di #284). Azione complementare a «Sfoglia…» (creare nuovo
vs selezionare esistente).

**Cosa fa.**
- `csv_writer.py` — predicato read-only `is_bridge_csv(path)` (`True` se il file esiste ed è un CSV
  del bridge, prima riga == `CSV_HEADER`; assente/vuoto/illeggibile/non-bridge → `False`) + funzione
  di creazione **atomica** `create_header_only_csv(path, *, force=False)`: fa il check dell'header
  esistente E la scrittura **sotto lo stesso `_write_lock`** → **niente TOCTOU** (come
  `clear_stale_csv` #184 H3). Esiti: `CSV_CREATE_DONE` (creato/rigenerato), `CSV_CREATE_REFUSED_
  FOREIGN` (file estraneo), `CSV_CREATE_REFUSED_ACTIVE` (CSV del bridge con un segnale attivo);
  `force=True` bypassa i refuse. Entrambe serializzate con `_write_lock`.
- `app.py` — `_create_and_save_csv(path, *, force=False)` (testabile): **guardia RUNTIME** — a
  bridge **avviato** sul CSV della sessione attiva (`_is_active_session_csv`, path normalizzato)
  rifiuta **anche con force** (STOP prima: non cancellare un segnale in volo / desync coda-expiry);
  poi `create_header_only_csv` (atomica) e, su `DONE`, riuso di `_apply_and_save_csv_path` (merge sul
  config vivo + guardia token PR-08c). `_browse_create_csv` (GUI): `asksaveasfilename` + conferma
  `askyesno` per file estraneo **o** CSV con segnale attivo, `showwarning` per la sessione avviata.
  Pulsante col. 3 della riga CSV Path.

**Sicurezza.** Il CSV è **generato dal codice** (nessun file committato/bundlato → gate
`forbidden-files`/`test_no_secrets_committed` invariati). Scrittura **atomica** senza file parziale;
**check+write sotto lo stesso lock** (no TOCTOU). Anti data-loss a tre livelli: file estraneo,
CSV con segnale attivo, e CSV della **sessione avviata** (bloccato). Contratto CSV/parser/Telegram
invariati; guardia token PR-08c preservata; nessun path locale reale committato.

**Review (Fable 5 + Fugu Ultra + CodeRabbit convergenti).** Due bloccanti REALI corretti: (1)
rigenerazione del CSV della sessione **avviata** cancellava un segnale non letto → guardia runtime
`_is_active_session_csv` (rifiuta anche con force) + refuse `CSV_CREATE_REFUSED_ACTIVE` per qualsiasi
CSV con riga attiva; (2) **TOCTOU** tra `is_bridge_csv` e `init_csv` → sostituiti da
`create_header_only_csv` che fa check+write sotto un solo `_write_lock`. Nitpick CodeRabbit
(estrarre un helper `_read_header_locked`): **skip motivato** — i quattro call site differiscono su
gestione `OSError` e comportamento post-lettura (`has_active_row`/`create_header_only_csv`
continuano a iterare lo stesso reader; `clear_stale_csv` propaga `OSError` e scrive sotto lo stesso
lock), un helper condiviso non calza e rischierebbe di regredire codice safety-critical già testato.
Finding CodeRabbit 🟠 (layout): la riga CSV Path con **due** pulsanti sforava la finestra a
larghezza **fissa** (720px, `resizable(False, True)`) tagliando «Crea CSV» → **corretto** stringendo
la casella `csv_path` (470→250px, solo quella riga) e i due pulsanti (110→100px) con padding ridotto:
la riga ora sta dentro la larghezza utile del tab. Le larghezze sono estratte in costanti di modulo
(`_WINDOW_WIDTH`, `_GEN_LABEL_WIDTH`, `_GEN_FIELD_ENTRY_WIDTH`, `_CSV_PATH_ENTRY_WIDTH`,
`_CSV_ROW_BTN_WIDTH`) e coperte da un **test di regressione layout**
(`tests/integration/test_gen_layout_budget.py`): la somma etichetta+casella+2 pulsanti (590px) deve
stare nel budget della finestra fissa, **derivato dai padding reali** (720 − 30 tab `padx` − 39
`padx` dei 4 widget = **651px**, non un numero magico — CodeRabbit #330), col padding interno della
tabview come margine ulteriore. Fail-first verificato: con la vecchia casella a 470px la riga a
810px sfora 651px. La verifica visiva DPI/font su Windows resta smoke manuale (layout GUI non
renderizzabile offline).

**Follow-up post-merge (#330 → PR dedicata):** su richiesta del proprietario e come suggerito da
GPT-5.5 + GLM 5.2 (non bloccante), i valori di `padx` della riga «⚙️ Generale» e della tabview sono
stati estratti in costanti di modulo (`_TABVIEW_PADX`, `_GEN_LABEL_PADX`, `_GEN_ENTRY_PADX`,
`_CSV_BROWSE_PADX`, `_CSV_CREATE_PADX`), usate SIA in `_build_ui` SIA nel test di budget layout →
**una sola fonte di verità**: il test deriva `tab_padding`/`row_padding` dalle stesse costanti che la
GUI usa per disegnare, eliminando il rischio di **drift** (numeri magici duplicati che divergono in
silenzio). Valori invariati (30/39 → budget 651px), fail-first verificato (senza le costanti →
`AttributeError`).

**Test hard:** `tests/unit/test_is_bridge_csv.py` (predicato + header **byte-esatto** BOM utf-8-sig +
QUOTE_ALL + CRLF); `tests/unit/test_create_header_only_csv.py` (esiti DONE/REFUSED_FOREIGN/
REFUSED_ACTIVE, bypass force, binario, path vuoto, cartella mancante creata);
`tests/integration/test_csv_create.py` (`_create_and_save_csv` via harness headless + vera
`save_config`/`init_csv`): nuovo → header byte-esatto + `csv_path` salvato preservando gli altri
campi; bridge header-only → rigenerato; **bridge con segnale attivo senza force → NON toccato**;
con force → rigenerato; **sessione avviata → rifiutata anche con force** (segnale intatto, altro
path invece permesso); file estraneo senza/con force; ramo OSError (avviso, no save); annullo/vuoto
→ no-op; guardia token PR-08c. Dialog Tk GUI-only → smoke manuale. Fail-first via stash. Suite:
**2046 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE: pulsante «📄 Crea CSV» + anti data-loss a tre livelli), README
(nota «Crea CSV»). Contratto CSV invariato (stesso `CSV_HEADER`/`init_csv`).


## #288 Delta 1 — toggle tema chiaro/scuro ✅ (PR 17)

**Obiettivo (#288 Delta 1).** L'app aveva **tema scuro fisso** (`set_appearance_mode("dark")` a
import-time). Aggiungere un **toggle chiaro/scuro** nell'header, con la preferenza persistita in
config (default `dark`, retrocompatibile) e riapplicata all'avvio.

**Cosa fa.**
- `config_store.py` — chiave `theme` in `DEFAULTS` (`"dark"`) + helper puro
  `normalize_theme(value)`: normalizza a `"dark"`/`"light"` (case/spazi-insensitive), qualsiasi
  valore mancante/non-stringa/sconosciuto → **fail-closed `"dark"`**. Usato SIA in `load_config`
  (validazione del campo) SIA nell'app → fonte unica di verità.
- `app.py` — dopo il load, `set_appearance_mode(normalize_theme(cfg["theme"]))`. Header: pulsante
  toggle (icona 🌙 scuro / ☀️ chiaro) + `_toggle_theme` (applica `set_appearance_mode`, PERSISTE con
  **merge sul config vivo + guardia token PR-08c** come gli altri save non-form, aggiorna l'icona) +
  `_update_theme_button`.

**Sicurezza.** Default e fail-closed a `dark` (nessuno stato UI indefinito). Nessun impatto su
contratto CSV, parser Telegram, Betfair; guardia token PR-08c preservata. I colori semantici
hardcoded restano invariati (leggibilità in tema chiaro = smoke manuale; rifinitura piena = Delta 3).

**Test hard (fail-first via stash):** `tests/unit/test_theme_config.py` (`normalize_theme`
dark/light/case/spazi/mancante/malformato/non-str → dark; `load_config` default/light/malformato/
assente); `tests/integration/test_theme_toggle.py` (`_toggle_theme` via harness headless + vera
`save_config`: dark→light e light→dark applicano `set_appearance_mode` + persistono + aggiornano
l'icona + preservano gli altri campi; tema malformato trattato come dark; **guardia token PR-08c**;
ramo save fallito → tema applicato all'UI ma avviso nel log). Rendering reale del tema chiaro =
smoke manuale su Windows. Suite: **2061 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE: tema commutabile, toggle nell'header, nota palette hardcoded +
Delta 3), README (nota toggle tema). Restano #288 Delta 2 (placeholder) e Delta 3 (restyle).


## #288 Delta 2 — segnaposto d'aiuto nei campi ✅ (PR 18)

**Obiettivo (#288 Delta 2).** I campi principali erano **vuoti** (nessun `placeholder_text`).
Aggiungere segnaposto d'aiuto (es. `es. -1001234567890` per Chat ID), **puramente additivi**.

**Cosa fa.**
- `app.py` — dict di modulo `_FIELD_PLACEHOLDERS` (bot_token/chat_id/csv_path/clear_delay/provider)
  applicato via `placeholder_text=` nella riga del tab «⚙️ Generale».
- `betfair/sync_tab_gui.py` — dict `_FIELD_PLACEHOLDERS` (app_key/username/password/cert_path/
  key_path) applicato ai campi credenziali.

**Sicurezza.** Il `placeholder_text` è **testo grigio a campo vuoto, NON un valore**: un campo
intatto resta `""` → nessun impatto su parsing/salvataggio/START. Sui campi **sensibili**
(`bot_token`/`app_key`/`password`) il segnaposto è **generico e istruttivo**, MAI un segreto
plausibile (è mostrato in chiaro anche sui campi mascherati). Nessun impatto su contratto CSV,
parser, Betfair.

**Test hard (fail-first via stash):** `tests/integration/test_placeholders.py` verifica i dizionari
REALI: tutti i segnaposto sono stringhe utili; sui campi sensibili è una **frase istruttiva** senza
alcun blob alfanumerico ≥12 char (che sembrerebbe un token/chiave/password); copertura dei campi
attesi; **contro-prova** che un segnaposto tipo-segreto fa fallire il check. Il rendering reale del
placeholder è GUI-only → smoke manuale. Suite: **2064 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE: segnaposto nei campi + nota sicurezza campi sensibili), README
(nota esempio-guida). Resta **#288 Delta 3** (restyle).


## #288 Delta 3 — palette semantica theme-aware (tema chiaro leggibile) ✅ (PR 19)

**Obiettivo (deciso col proprietario).** La #288 Delta 1 ha aggiunto il toggle tema chiaro/scuro ma
i colori di STATO erano **hardcoded per lo scuro** → poco leggibili in tema chiaro. Delta 3 (slice
«Palette + tema chiaro» scelto dal proprietario): rendere i colori semantici **theme-aware** e
leggibili in entrambi i temi, **senza** cambiare struttura/label né la semantica dei colori.

**Cosa fa.**
- `app.py` — costanti di palette `(light, dark)` (`_COLOR_HEADER_BG`, `_COLOR_HEADER_TITLE`,
  `_COLOR_STATUS_OFFLINE`, `_COLOR_STATUS_ACTIVE`, `_COLOR_STATUS_RECONNECT`, `_COLOR_ACTIVE_ROWS`,
  `_COLOR_WARNING`, `_COLOR_REAL_BANNER_BG`), applicate a: sfondo/titolo header, indicatore di stato
  (OFFLINE/ATTIVO/RICONNESSIONE, sia alla costruzione sia nei `configure` dinamici), righe attive,
  warning «nessuna chat», banner modalità reale. La variante **dark è quella storica** (invariata).

**Sicurezza.** Nessun cambio a struttura/label/flussi; la **semantica** dei colori è invariata
(rosso=errore/OFFLINE, verde=attivo, arancione=warning/riconnessione). Nessun impatto su CSV,
parser, Betfair, config. Fuori scope (follow-up estetico): pulsanti d'azione tinta-unita e colori
secondari `_set_last`.

**Test hard (fail-first via stash):** `tests/integration/test_palette.py` calcola il **contrasto
WCAG** di ogni colore semantico sul relativo sfondo in **entrambi** i temi e richiede ≥ 3.0 (rende
automatica la «leggibilità in tema chiaro» prima solo smoke-manuale); più: colori theme-aware con
hex validi e variante light≠dark; variante **dark invariata** rispetto allo storico. Il rendering
reale su Windows/DPI resta smoke manuale. Suite: **2067 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE: sezione Palette con colonna light/dark + nota theme-aware +
contrasto verificato in CI). Con questo #288 è completa (Delta 1/2/3) e può essere chiusa al merge.


## #293 (slice 1) — rinomina colonna «Provider» → «Come lo scrive il canale» ✅ (PR 20)

**Obiettivo (#293, primo slice scelto dal proprietario — il più sicuro).** Nel Dizionario nomi
squadra la colonna dell'alias del canale si chiamava «Provider», **collidendo** con l'anagrafica
«Provider» (etichetta della colonna CSV). Rinominata in **«Come lo scrive il canale»** per
eliminare l'ambiguità. È una **rinomina SOLO di etichetta**: nessun cambio funzionale.

**Cosa fa.**
- `name_mapping_gui.py` — costante `_CHANNEL_ALIAS_COLUMN = "Come lo scrive il canale"` usata come
  header di colonna (era `("Provider", 240)`); aggiornati docstring, testi d'aiuto e commenti che
  citavano «Provider» come nome del campo. La **chiave dati nello store resta `provider`**.

**Sicurezza.** Cambia SOLO l'etichetta visibile. Invariati: chiave dati `provider`
(`name_mapping_store`), colonna **CSV «Provider»** (anagrafica, `CSV_HEADER`), risoluzione
fail-closed delle mappature, contratto CSV, parser, Betfair. Nessun test **preesistente** dipende
dall'etichetta dell'header (i «Provider» negli altri test sono il **campo CSV/parser**
`target="Provider"`/`row["Provider"]`, non l'header GUI del Dizionario nomi); il nuovo test di
regressione asserisce invece **sul dato reale** dell'header (`_HEADER_COLUMNS`) che «Provider» non è
più un'intestazione di colonna.

**Test hard (fail-first via stash):** `tests/integration/test_channel_alias_rename.py` — round-trip
`set_entries`/`get_entries` preserva la chiave dati `provider`; `CSV_HEADER` contiene ancora
`Provider` (anagrafica invariata); `_CHANNEL_ALIAS_COLUMN == "Come lo scrive il canale"`; guardia
anti-ripristino sul **dato** dell'header (`_HEADER_COLUMNS`: contiene la nuova etichetta, NON
«Provider»). Rendering GUI = smoke manuale. Suite: **2072 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE §7.5: colonna rinominata + nota chiave dati `provider` invariata).
Prossimi slice #293: mappature nel Parser → Riepilogo → 4 gruppi → densità parser.


## #293 (slice 2) — «🔗 Traduzioni attive per questo parser» con indicatore ✓/— ✅ (PR 21)

**Obiettivo (#293, slice scelto dal proprietario).** Il Parser aveva già le checkbox dei profili di
mappatura **Nomi** e **Mercati** + i pulsanti «apri Dizionario», ma come righe sciolte. #293 le
raggruppa in un **riquadro «🔗 Traduzioni attive per questo parser»** con un **indicatore di stato
✓/—** per tipo (`✓ N attive` verde / `— nessuna` grigio). **Nessun cambio funzionale.**

**Cosa fa.**
- `custom_parser_gui.py` — le due sezioni mappatura (nomi/mercati) sono spostate dentro un
  `CTkFrame` etichettato «🔗 Traduzioni attive per questo parser». Aggiunti `self._nm_status_lbl` /
  `self._mm_status_lbl`. Helper puro `_translations_status_text(count)` (`✓ N attive`/`— nessuna`; conta solo i profili
  **risolti** — un fantasma `⚠` selezionato non è una traduzione attiva, Fable #336)
  + `_set_translation_status`/`_update_translations_status` (colori theme-aware `(light, dark)`).
  Le checkbox profili ora hanno `command=self._update_translations_status` (aggiorna al toggle); il
  reload aggiorna l'indicatore. Sotto-etichette rinominate «Nomi squadra»/«Mercati» (sotto il
  titolo del riquadro).

**Sicurezza.** Solo presentazione: **stessa** logica di selezione profili (`_selected_profiles`/
`_selected_market_profiles`, ordine preservato), stesso blocco `⚠`/`_unresolved_*`, stesso
fail-closed delle mappature, **MultiMarket/MultiSelection** e contratto CSV **invariati**. Nessun
impatto su parser runtime/Betfair.

**Test hard (fail-first via stash):** `tests/integration/test_parser_translations_status.py` —
`_translations_status_text` (0/negativo→«— nessuna», 1→«✓ 1 attiva», N→«✓ N attive»);
`_update_translations_status` su un pannello finto (ctk stubbato): nomi attive/mercati no + colori
ON/OFF, entrambe con conteggio, e ramo **difensivo** (etichette non ancora costruite → nessun
crash). Rendering GUI reale = smoke manuale. Suite: **2076 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE §7.1: riquadro «Traduzioni attive» + indicatore ✓/—). Prossimi
slice #293: Riepilogo → 4 gruppi → densità parser.


## #293 (slice 3) — schermata «📋 Riepilogo configurazione» (sola lettura) ✅ (PR 22)

**Obiettivo (#293, slice scelto dal proprietario).** Colpo d'occhio su ciò che il bridge farà
davvero, senza saltare tra Generale/Betfair/Chat sorgenti/Parser/Mapping: **modalità**
Simulazione/REALE, **stato Betfair** (dizionario sincronizzato + login), e **per ogni canale** →
parser → traduzioni attive → **«Pronto?»**. Pannello **additivo, sola lettura**: nessuna modifica a
CSV/parser/config/filtro chat. Posizionamento incrementale scelto col proprietario: **pannello
nell'hub 🧰 Strumenti** (il riordino «4 gruppi» è uno slice successivo).

**Cosa fa.**
- `config_summary.py` (NUOVO, modulo **puro**): `summarize_config(cfg, *, betfair_synced,
  betfair_logged_in, parsers_dir)` → `ConfigSummary` (dataclass) con modalità, flag Betfair e una
  `ChannelSummary` per canale (parser risolto/caricabile, traduzioni risolte vs fantasma `⚠`,
  `ready`+`reason`). Riusa gli **stessi predicati del runtime** (`signal_router.allowed_chats`,
  `parser_manager.resolve_parser_name`/`load_active`, `safety_guard.is_dry_run`,
  `name/market_mapping_store.profile_names`) così il riepilogo non diverge dal comportamento reale.
- `config_summary_gui.py` (NUOVO): `ConfigSummaryPanel` sola-lettura + helper puri di
  testo/colore (`mode_label`/`betfair_label`/`translations_label`/`readiness_label`/…). Si
  ri-legge al cambio scheda (`refresh_options`).
- `app.py`: factory `_make_summary` + voce `("📋 Riepilogo", _make_summary)` nell'hub Strumenti;
  `_config_summary_snapshot()` (config viva + conteggio dizionario Betfair/login **best-effort**,
  fail-soft a False).

**«Pronto?» severo (scelta del proprietario, fail-closed).** `✅ Pronto` solo se: chat_id presente
+ sorgente attiva + parser che **si carica ed è valido** + **tutte** le mappature selezionate
risolte. Un profilo fantasma `⚠` non conta come traduzione attiva → non pronto. Motivi espliciti:
«Manca chat_id» / «Sorgente disattivata» / «Nessun parser assegnato» / «Parser non caricabile: …»
/ «Traduzione mancante: …».

**Test hard (fail-first via mutazione):** `tests/unit/test_config_summary.py` (12) — modalità
reale/sim/default, passthrough Betfair, canale pronto, disattivato, senza parser, senza chat_id,
parser non caricabile, traduzioni risolte, fantasma nomi/mercati nel motivo, canale da
`parser_by_chat` senza sorgente, ordine+conteggi, immutabilità (sola lettura). Mutazione
(disattivo la guardia fantasma) → i test fantasma FALLISCONO (regressione bloccata), poi ripristino.
`tests/integration/test_config_summary_gui.py` (7) — helper puri testo/colore con `customtkinter`
stubbato. Allowlist blind-except aggiornata (app.py 35→37 + `config_summary_gui.py` 1, motivati).
Rendering GUI reale = smoke manuale. Suite: **2101 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE §5 mappa hub + §7.10 pannello Riepilogo). Prossimi slice #293:
4 gruppi di flusso → densità parser.

**Fix di review (stesso PR).** Fable #337: lo snapshot leggeva `count_active` sul DB Betfair nel
thread GUI → prima `is_syncing`, poi (CodeRabbit #337, più robusto/race-free) il probe non
bloccante `db.acquire_read(blocking=False)`/`release_read()` come `_known_betfair_teams` — durante
una sync si salta la lettura (best-effort «non sincronizzato»), mai freeze. CodeRabbit #337:
`_config_summary_snapshot` ora legge la config **viva** `self._config` (autoritativa dopo un save
fallito), non il disco. Nitpick CodeRabbit: estratte in helper puri `ready_count_label` /
`no_channels_label`, e `parser_label` mostra `⚠` per un parser non caricabile. Test aggiornati
(snapshot: probe non bloccante + config viva + DB None; helper GUI). Suite: **2111 passed, 10 skipped**.


## #293 (slice 4) — hub Strumenti raggruppato per flusso in 4 gruppi ①..④ (PR 23)

**Obiettivo (#293, slice scelto dal proprietario).** Riorganizzare i 10 strumenti dell'hub 🧰 per
**«cosa vuoi fare»** invece che alla rinfusa: 4 gruppi ① Sorgenti · ② Lettura messaggi · ③ Betfair
· ④ Impostazioni. **Approccio incrementale scelto col proprietario:** tab **piatte riordinate** con
**prefisso di gruppo ①..④** (niente tab annidate in questo slice); collocazione degli strumenti
extra: 🗺️ Mapping → ②, 📒 Diario + 🧹 Nomi Betfair → ③.

**Cosa fa.**
- `tools_gui.py` — nuova IA **pura** come fonte unica: `TOOL_GROUPS` (gruppi → strumenti, in
  ordine), `TOOL_TITLES` (etichetta base per strumento), `build_tool_panels(factories)` che
  assembla la lista ordinata `(titolo, factory)` col prefisso di gruppo (es. «① 📡 Chat sorgenti»)
  e fa **fail-fast** (`KeyError`) se manca la factory di uno strumento (nessuna scheda persa).
- `app.py _open_tools` — la lista schede è ora costruita da `build_tool_panels({...})` con le
  **stesse factory/callback di prima** (solo ordine + prefisso del titolo cambiano). Nessun altro
  comportamento toccato.

**Ordine risultante:** ① 📡 Chat sorgenti · ① 📇 Provider · ② 🧩 Parser · ② 🗺️ Mapping ·
③ 🔵 Betfair Sync · ③ 📖 Dizionario Betfair · ③ 📒 Diario · ③ 🧹 Nomi Betfair · ④ 📁 Profili ·
④ 📋 Riepilogo.

**Sicurezza/invarianti.** Solo riorganizzazione GUI: nessun cambio a CSV, parser, filtro chat,
config, backend Telegram/Betfair; nessun click in più (tab piatte); wiring `refresh_options`/
`select_tab`/isolamento per-scheda invariato (nessun chiamante apre l'hub per titolo specifico).

**Test hard (fail-first via mutazione):** `tests/integration/test_tools_groups.py` (5) — ordine e
prefissi esatti delle 10 schede, tutte le factory instradate (nessuno strumento perso/duplicato),
coerenza prefisso↔gruppo, i 4 gruppi coprono esattamente tutti gli strumenti una volta sola,
fail-fast su factory mancante. Mutazione (scambio ordine in un gruppo) → i test ordine/instradamento
FALLISCONO, poi ripristino. Rendering GUI reale = smoke manuale. Suite: **2116 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE §5 mappa hub raggruppata ①..④). Prossimo slice #293: densità
parser (colonne essenziali di default, «Avanzate» per Trasformazione/Value-map).


## #293 (slice 5, ULTIMO) — «densità parser»: colonne avanzate dietro toggle «Avanzate» (PR 24)

**Obiettivo (#293, ultimo slice — chiude l'issue).** La tabella regole del Parser mostrava sempre
tutte e 8 le colonne, densa e intimidatoria. Ora di **default** mostra solo le colonne
**essenziali** (Colonna · Inizia dopo · Finisce prima · Valore fisso · Obblig.); le due colonne
**avanzate** (Trasformazione, Value-map) compaiono solo attivando il toggle **«⚙️ Avanzate»**.

**Cosa fa.**
- `custom_parser_gui.py` — costante unica `_RULE_COLUMNS` `(label, larghezza, avanzata?)` +
  helper **puro** `_visible_rule_columns(show_advanced)` (colonne da mostrare); `_populate_rules_header`
  costruisce l'intestazione da esso. Nuovo `self._show_advanced` (default `False`) + checkbox
  «⚙️ Avanzate (Trasformazione · Value-map)» con callback `_on_toggle_advanced` (sync builder →
  ricostruisce intestazione + righe).
- `_add_row` — i `StringVar` `transform`/`value_map` sono creati **SEMPRE** (così `_sync_to_builder`
  conserva `rule.transform`/`rule.value_map` anche a colonne nascoste: **nessuna perdita di dati**);
  i due `CTkOptionMenu` si mostrano solo in modalità «Avanzate».

**Sicurezza/invarianti.** Solo presentazione GUI: nessun cambio a parsing, contratto CSV (14
colonne), filtro chat, Betfair. `custom_parser_engine` legge ancora `rule.transform`/`value_map`
invariati. Sezione **Output multi-riga #192 non toccata** (non ha colonne Trasformazione/Value-map).

**Test hard (fail-first via mutazione):** `tests/unit/test_parser_density.py` (5) — `_visible_rule_columns`
nasconde esattamente le 2 avanzate di default e le mostra tutte con «Avanzate»; `_add_row` (ctk
stubbato) crea i `StringVar` transform/value_map **col valore del rule anche a colonne nascoste**
(dato preservato), ramo difensivo senza `_show_advanced`. Mutazione 1 (flag ignorato) → test densità
FALLISCE; mutazione 2 (StringVar solo se avanzate) → test preservazione FALLISCE con KeyError. Poi
ripristino. Rendering GUI reale = smoke manuale. Suite: **2123 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE §7.1: toggle «Avanzate» + griglia essenziale di default; §7 conteggio
pannelli 9→10). Con questo slice il **piano incrementale a 5 slice** di #293 è fatto (rinomina →
mappature nel parser → Riepilogo → 4 gruppi → densità); restava l'item 4 del concept (chip
«Traduzioni» in Chat sorgenti), fatto in slice 6 qui sotto.


## #293 (slice 6) — chip «Traduzioni» per canale in Chat sorgenti; #293 COMPLETA (PR 25)

**Obiettivo (#293, item 4 del concept — scelto dal proprietario dopo le 5 slice del piano).** Nel
pannello **Chat sorgenti** ogni canale ora mostra un **chip «Traduzioni»** che dice a colpo d'occhio
se il parser di quella chat ha mappature **risolte** attive (**`Nomi ✓ · Mercati ✓`** verde /
**`—`** grigio). Completa l'intero concept approvato di #293.

**Cosa fa.**
- `config_summary.py` — nuovo helper **puro** riusabile `parser_translation_flags(cfg, parser_name,
  *, parsers_dir)` → `(nomi_attive, mercati_attive)` booleani (parser vuoto/non caricabile →
  `(False, False)`, fail-closed; stessa nozione di «risolto» del Riepilogo).
- `source_chats_gui.py` — colonna **«Traduzioni»** in intestazione + `_translations_chip_text`
  (puro) + `_update_row_chip` (parser della riga = override o, se «(predefinito)», il globale). Il
  chip si aggiorna al cambio del menu Parser (`command=`) e in `refresh_options` (nuove mappature/
  parser da altre schede); snapshot `self._cfg` aggiornato in `__init__`/`refresh`/`refresh_options`.

**Sicurezza/invarianti.** Solo indicatore read-only: nessun cambio a `_save`, alla logica sentinella
del parser, a `parser_by_chat`, al contratto CSV, al filtro chat o a Betfair. Nessuna nuova
eccezione ampia (`parser_translation_flags` è fail-safe).

**Test hard (fail-first via mutazione):** `tests/unit/test_config_summary.py` (+1) —
`parser_translation_flags` nomi/mercati/entrambi/fantasma(→False)/nessun-parser/file-assente;
`tests/integration/test_source_chats_translations.py` (1) — `_translations_chip_text` (ctk stubbato).
Mutazione (conta i profili fantasma) → il caso «Ghost» FALLISCE, poi ripristino. Rendering GUI reale =
smoke manuale. Suite: **2126 passed, 10 skipped**.

**Docs:** design_handoff.md (GATE §7.2: colonna «Traduzioni» in Chat sorgenti). **#293 è ora COMPLETA
in tutti i 6 item del concept.** Prossimo su #301 (ordine scelto dal proprietario): issue #325 (Correct
Score dinamico) → poi Nuitka (Fase 6).


## #325 (slice 1, backend) — estrazione per-riga DINAMICA dei risultati esatti (Correct Score FT + 1º tempo)

**Obiettivo (#325, feature nuova; scope backend-first scelto dal proprietario).** Un messaggio che
elenca più risultati esatti (es. «1-0, 2-1, 3-0») + una regola **MultiSelection dinamica** →
**una riga CSV per risultato**, estratti dal messaggio (non più solo selezioni fisse
preconfigurate). Vale sia per **Correct Score full-time** (`CORRECT_SCORE`) sia per il **primo
tempo** (`HALF_TIME_SCORE`) — entrambi esclusi dall'harvest #283, quindi le selezioni DEVONO venire
da qui.

**Cosa fa.**
- `custom_parser_engine.extract_scores(text, start_after, end_before)` (NUOVO, puro): dalla regione
  fra i delimitatori estrae la lista dei punteggi «N - N», **normalizzati** al formato del dizionario
  («1-0»/«1:0»/«01 - 0» → «1 - 0»), **deduplicati** nell'ordine del messaggio. Separatore fra i
  risultati irrilevante (riconoscimento per forma via `findall`). Senza delimitatori → scandisce
  tutto il testo.
- `custom_pipeline`: `_is_dynamic_selection(rule)` (detection **stretta**: `selection_name` vuoto +
  `start_after`/`end_before`), `_selection_rows` (fissa → 1 riga; dinamica → 1 riga per punteggio via
  `extract_scores`, ognuna dal solito `_validated_multi_row` → azzeramento+ri-risoluzione ID +
  validazione per-riga fail-closed), e fix `_multi_supplied_cols`/`_rule_supplies` (una regola
  dinamica «fornisce» `SelectionName` via estrazione, così una base `NOT_READY` su un SelectionName
  obbligatorio viene rilassata — trappola #192 evitata). `build_validated_rows` non ritorna mai `[]`
  (una lista vuota → un esito `NOT_READY` non piazzabile, così `resolve_row` non crasha).
- Docstring `MultiRowRule` aggiornata (l'estrazione per-riga non è più «futura»).

**Sicurezza/invarianti.** Nessun cambio al contratto CSV (14 colonne — solo più righe), al filtro
chat, a Betfair. Retro-compatibilità: MultiSelection **fisso** e single-row invariati (detection
stretta). Deduplica punteggi = nessuna doppia scommessa per lo stesso risultato. ID coerenti per
riga (azzerati quando cambia la selezione, poi ri-risolti). Fail-closed per-riga.

**Test hard (fail-first via mutazione):** `tests/unit/test_dynamic_scores_325.py` (13) —
`extract_scores` (lista/normalizzazione/separatori robusti/dedup/regione delimitata/vuota);
pipeline (N righe FT + 1º tempo, un solo risultato, token malformato ignorato, lista vuota → nessuna
riga piazzabile senza crash, ID azzerati per riga, base NOT_READY su SelectionName obbligatorio
rilassata dal dinamico, retro-compat fisso). Mutazioni: detection sempre-False → test N-righe
FALLISCE; rimozione del supply dinamico di SelectionName → test base-NOT_READY FALLISCE. 102 test
multirow/pipeline/engine preesistenti verdi. Suite: **2141 passed, 10 skipped**.

**Docs:** `docs/custom_parser.md` §5-bis (estrazione per-riga dinamica) + docstring `MultiRowRule`.
Design handoff = **N/A** (slice backend, nessun cambio GUI; i campi «Inizia dopo/Finisce prima» sulla
tabella MultiSelection arrivano nella **slice 2 GUI**). Prossimo: #325 slice 2 (GUI) → poi Nuitka.

## #342 — separatore decimale del CSV per lingua (IT/EN/ES) — BREAKING, fondazione multilingua #343

**Problema (confermato dal supporto XTrader).** XTrader **ITA** (versione attuale) legge i decimali
di quote/points con la **virgola**; il bridge scriveva sempre il **punto** (`_decimal_sep_to_point`)
su `Price`/`MinPrice`/`MaxPrice`, e `Points`/`Handicap` non erano normalizzati affatto.

**Fix (#342).** Config `csv_language` (`IT`/`EN`/`ES`, default **IT**, coercion fail-closed pattern
«theme»); localizzazione **solo al confine di scrittura** (`csv_writer.write_rows` →
`_localize_row`): interno **canonico col punto** (validatori/dedup/pipeline invariati), file con la
**virgola** per `IT`/`ES` e **punto** per `EN`, su TUTTE le colonne decimali (`Price`, `MinPrice`,
`MaxPrice`, `Points`, `Handicap` — decisione owner). Solo un numero puro (`SIGNED_DECIMAL`
fullmatch) viene localizzato; malformati/testo invariati (fail-closed); colonne testuali
(«Over 2.5 Goals») mai toccate. Sync del writer in `load_config`/`save_config` (startup, Salva,
profili — nessun altro wiring). **BREAKING**: chi usa la versione inglese imposta
`"csv_language": "EN"`. ES = convenzione spagnola, da confermare col supporto (mappa a una riga).
È la **prima slice/fondazione config** dell'epica multilingua **#343** (selettore lingua all'avvio,
BetType per-lingua, UI localizzata, dizionario per-locale user-built, EN/ES solo NAME_ONLY).

## #311-1.1 — single-instance lock (prima PR della coda GUI decisa dall'owner)

Anti **doppia istanza = anti doppia scommessa**: due processi bridge hanno
tracker/limiter/coda separati in RAM (i lock interni sono intra-processo). Nuovo modulo
foglia `instance_lock.py`: **Windows = mutex named** via ctypes (`Local\XTraderBridge` —
namespace di sessione: copre il doppio avvio sullo stesso desktop senza il privilegio
SeCreateGlobal; il kernel lo rilascia da solo alla terminazione del processo, anche su crash → nessun
lock orfano); **POSIX (dev/CI) = lockfile `flock`** con le stesse proprietà, che rende la
logica testabile offline. Acquisizione = **prima istruzione** di `App.__init__` (pin
strutturale nei test): seconda istanza → messagebox «già in esecuzione» + `SystemExit`,
nessun listener/CSV. Release in `_on_close` + atexit; **idempotente col flag `released`**
(una release stantia non può sbloccare il lock della nuova istanza su fd riusato).
**Fail-open consapevole** sul solo errore imprevisto di creazione (bridge inavviabile >
caso limite; warning nei log); il rifiuto resta certo su «lock già posseduto».
Ordine coda GUI post-#345 (decisione owner, commento in #311): 1.1 → 1.3 → PR-cestino
micro-GUI → 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → #343 GUI; poi Nuitka e il resto.

## #311-1.3 — START bloccato senza Parser Personalizzato attivo (coda GUI, PR 2)

Il parser hardcoded P.Bet è disattivato nel live (CP-09b): senza alcun Parser
Personalizzato il listener partiva «ATTIVO» ma ignorava ogni segnale, con un solo avviso
⚠ non bloccante — l'operatore credeva che il bridge lavorasse. Ora il check
`signal_router.has_active_parser_config` in `_start` è **BLOCCANTE** (❌ + `return`),
coerente con gli altri fail-fast (token/csv_path/chat/sorgenti): messaggio con
l'istruzione esplicita («Configura almeno un Parser Personalizzato prima di avviare,
scheda 🧩 Parser»). Guardia strutturale fail-first in test_app_runtime_glue (il blocco
deve loggare ❌ e fare `return`; mutazione senza `return` → test fallisce); la logica
pura resta coperta dagli unit di `signal_router`. Copre anche l'auto-start (passa da
`_start`). Docs: README (box in «Parser Personalizzato») + design handoff §9.4.

## #325 (slice 2, GUI) — campi «Inizia dopo/Finisce prima» sulle righe MultiSelection

Chiude #325: i delimitatori dell'estrazione dinamica (slice 1 backend) sono ora configurabili
dalla GUI. `_MULTI_SELECTION_FIELDS` = `_MULTI_FIELDS` + i due campi delimitatore, esposti **solo
sulle righe SELEZIONE** (sui MERCATI sarebbero la misconfigurazione da cui il gate #341 difende:
lì restano campi nascosti preservati, Codex P1). `_add_multi_row_widget`/`_multi_rule_from_refs`
parametrizzati con `refs["_fields"]`; i delimitatori **non** vengono strippati al salvataggio
(stesso contratto della griglia base: «\n» è un delimitatore legittimo). Hint 💡 statico sotto la
lista selezioni spiega la combinazione dinamica. Design handoff aggiornato (§ Output multi-riga).
Prossimo: Nuitka (Fase 6); epica #343 in attesa delle risposte del supporto XTrader.

## #3 slice 2 — BetType multilingua (BACK/LAY/PUNTA/BANCA) — sbloccata

Il supporto Betting Toolkit/XTrader ha **confermato** (issue #3): come `BetType` valgono
**indifferentemente `BACK`, `LAY`, `PUNTA`, `BANCA` su tutte le versioni**; i termini spagnoli
(`FAVOR`/`CONTRA`) **non** sono ancora previsti (prossimi aggiornamenti). La struttura CSV, i codici
`MarketType` e i nomi-colonna sono **identici** per tutte le lingue; il separatore decimale è
«indifferente» (già coperto da #342). Le differenze vere restano sui **nomi** per il matching, che
dipendono da **lingua della fonte + exchange Betfair** (slice 5, ancora aperta: dizionario per-locale
user-built + indicazione della lingua della fonte).

**Fix (slice 2).** `validator._VALID_BETTYPES` esteso ai quattro lati (`PUNTA/BANCA/BACK/LAY`) +
`validator.canonical_bettype()` (BACK→PUNTA, LAY→BANCA); `custom_pipeline._normalize_to_contract`
canonicalizza il BetType al confine del contratto → **l'output CSV resta canonico `PUNTA`/`BANCA`**
(universale). Fail-closed invariato: `FAVOR`/`CONTRA`/garbage/vuoto → `INVALID_BETTYPE` (mai indovinare
il lato). Nessun cambiamento al `csv_writer` legacy (già mappava BACK→PUNTA) né agli header.

**Test hard:** i 4 lati validi (case-insensitive); `canonical_bettype` mappa al lato italiano; ES/garbage
rifiutati (fail-closed); pipeline con BetType grezzo `BACK`→output `PUNTA`, `LAY`→`BANCA`, `FAVOR`→non
piazzabile; diagnostica coerente (BACK/LAY ok, FAVOR marcato). Slice 5 (nomi per-locale) resta la
prossima, dipendente dalle disuniformità Betfair citate dal supporto.

## PR-cestino micro-GUI (coda GUI, PR 3) — avvisi per-riga + anteprima coi decimali per lingua

Tre micro-fix GUI accumulati dalle review di #341/#344 (nessun cambio runtime):

1. **Avviso «delimitatori ignorati con Selezione fissa»** — una riga MultiSelection attiva con
   Selezione impostata e delimitatori valorizzati è ambigua: il runtime usa il valore fisso e
   ignora i delimitatori. Il banner ⚠ ora lo dice, per riga (1-based).
2. **Avviso «estrazione dinamica inattiva su mercato non-punteggio»** — Selezione vuota +
   delimitatori ma mercato effettivo fuori da `_DYNAMIC_SCORE_MARKETS` (gate #341): la riga resta
   FISSA ereditando la Selezione base. Emesso **solo a mercato staticamente noto** (override
   della riga, o MarketType base `fixed_value` puro senza mappatura mercati/transform/value-map:
   `_static_base_market_type` → `None` = ignoto = silenzio, mai falsi allarmi). Il set dei
   mercati-punteggio è **importato** dal runtime (`custom_pipeline`), non copiato (anti-drift,
   test dedicato). Logica in `ParserBuilder._dynamic_selection_warnings` (pura, CI).
3. **Anteprima «Prova messaggio» coi decimali nel formato `csv_language`** (#342): summary righe
   anteprima + verdetto «✅ Pronto · …» passano da `csv_writer.localize_row` (nuovo wrapper
   pubblico di `_localize_row`, stessa fonte del write-path) — IT/ES virgola, EN punto.
   `PreviewRow.row` resta **canonico col punto** (è il dato, non la vista).

Glue GUI: banner avvisi aggiornato anche su `<FocusOut>` dei campi riga multi, sulla checkbox
«Attiva» (`command=`) e in `_test` dopo `_sync_to_builder`. Test: 16 nuovi (avvisi su tutti i
rami incl. fail-safe ignoto/mappatura/riga disattivata/delimitatore blank; localizzazione IT/EN
con fixture di ripristino lingua; bind GUI esercitati con stub registranti; pin strutturale su
`_test`), mutation-verified. Docs: custom_parser.md §5-bis + design handoff (banner + anteprima).

## #311 §3.1 — «Modalità Collaudo» esplicita (coda GUI, PR 4)

Tri-stato NOMINATO sopra `dry_run`: **SIMULAZIONE** (non scrive) / **COLLAUDO** (scrive
il CSV, banner ambra permanente «XTrader deve essere in simulazione», conferma sì/no) /
**REALE** (frase di conferma + banner rosso). Nuovo modulo puro `bridge_mode.py`;
`dry_run` resta l'UNICA fonte del write-path (`is_dry_run` invariato ovunque): la
modalità è derivata fail-closed (`mode_from_cfg`: incoerenza → Simulazione; legacy
`dry_run:false` senza `bridge_mode` → Reale, nessun declassamento). Gate **mode-aware**
(`requires_real_confirmation`): chiude il buco COLLAUDO→REALE invisibile al check su
dry_run (entrambi False); annullo → ritorno al modo PRECEDENTE. Config: chiave
`bridge_mode` con coercion self-heal; settings_controller deriva `dry_run` dal form
(retro-compat form legacy). Test: 24 nuovi (unit puri + glue gate reale con dialog
stub + pin banner), 4 mutazioni KILLED (gate storico, annullo→sim, mode fail-open,
banner rosso su criterio dry_run). Review round 1: banner ROSSO reso **mode-aware**
(`real_banner_active`, Fugu: con quello storico una sessione COLLAUDO mostrava «REALE
ATTIVA» sopprimendo l'ambra) + coerenza immediata `bridge_mode` sul form legacy (Fable).

## #311 §3.2 — Parser tester su messaggi reali (coda GUI, PR 5)

Bottone «🧪🧪 Prova più messaggi (separati da ---)» nella scheda Parser: N messaggi reali
in un colpo, per ciascuno verdetto ✅/⛔ col motivo esatto (STESSO `test_verdict` del
singolo, anti-drift testato per uguaglianza) + anteprima righe CSV. Logica pura nel
controller (`split_messages`: separatore esplicito riga `---`, niente euristiche;
`batch_report`: tetto fail-safe 50 con `skipped` segnalato). Read-only puro. Test: 7
nuovi (split/tetto/misto/anti-drift + glue sul vero `_test_batch` con stub),
mutazioni KILLED (split in-line, tetto rimosso).

## #311 §3.3 — Health check a semafori (coda GUI, PR 6)

Scheda «🚦 Salute»: i 7 semafori dell'issue (Telegram · ultimo messaggio · parser ·
ultimo segnale col motivo · CSV scrivibile · conferme XTrader · modalità) da
`health_check.evaluate` (modulo PURO: dato assente = mai verde; modalità con semantica
di rischio dei banner §3.1). Sonda `csv_writable` non invasiva (solo `os.access`, mai
open → nessun lock contro XTrader). Nuovo campo «Ultima conferma XTrader» in
`_LAST_FIELDS` (alimentato da CONFERMATO/RIFIUTATO in `_handle_confirmation`).
Refresh sugli hook esistenti (`_set_last`, START/STOP) + pulsante «🔄 Aggiorna».
Test: 11 unit puri + 3 glue; 4 mutazioni KILLED. Review round 1 (Fable): refresh
reso interamente BEST-EFFORT (mai rompere `_set_last`/monitoraggio primario; hook
spostato DOPO le label e aggiunto a `_update_real_mode_banner` = save/profilo/
START/STOP, nota GPT) e sonda CSV **tri-stato** con giallo onesto su Windows a file
esistente (os.access ignora ACL/lock NTFS: mai verde non verificabile).
Follow-up post-merge (Fugu, fix PR dedicata): giallo onesto esteso al ramo «file da
creare» su Windows (stesse ACL sulla cartella) + `platform` iniettabile nella sonda
(GLM: il monkeypatch del globale os.name rompeva la failure-repr di pytest).

## #311 §3.4 — Wizard di prima configurazione (coda GUI, PR 7)

Toplevel modale a 5 step: token+getMe · chat+messaggio di prova (getUpdates one-shot
SENZA offset: non consuma update del listener) · parser su messaggio reale (riusa il
tester #350) · csv_path + scrittura di prova (sonda #351 + create_header_only_csv:
riga attiva protetta, file estraneo rifiutato) · checklist finale informativa. Logica
PURA in `wizard.py` con sonde INIETTABILI (mai Telegram live nei test); token mai
negli esiti (mutazione anti-leak KILLED); il wizard non attiva MAI il reale e il
salvataggio finale passa da `_save_config` (gate #349 inclusi). Vista sottile
`wizard_gui.py` (sonde in thread + esito via after; gate «Avanti» per step,
mutazione KILLED). Test: 13 unit puri + 4 glue.

## #311 §3.5 — DPI awareness + clamp larghezza fit_to_screen (coda GUI, PR 8)

Nuovo modulo puro `dpi_awareness.py`: `enable_dpi_awareness(platform/windll
INIETTABILI)` imposta la DPI awareness del processo PRIMA della root Tk
(`shcore.SetProcessDpiAwareness(2)`, lo STESSO valore per-monitor di customtkinter:
mai in conflitto; fallback `user32.SetProcessDPIAware`; su non-Windows UNSUPPORTED)
— fail-open per contratto: mai un raise, un fallimento DPI non blocca l'avvio;
gli HRESULT sono VERIFICATI (ctypes non solleva: S_OK/E_ACCESSDENIED=già aware →
successo, altri → fallback; BOOL di user32 controllato — CodeRabbit #355) e
l'esito finisce nel log di modulo per diagnostica Windows.
`gui_utils`: estratta la pura `clamp_to_screen` e `fit_to_screen` ora clampa anche
la LARGHEZZA (pavimento al minsize del chiamante): le finestre larghe
(Strumenti/dizionario 1140px) restano visibili su schermi 1024. Firma pubblica
invariata, chiamanti non toccati. Test: 9 unit deterministici headless
(windll/finestra fake), mutazioni I–L KILLED.

## #343 slice 3 — Selettore lingua al primo avvio (coda GUI, PR 9)

Nuovo modulo puro `language_select.py`: `normalize_app_language` (IT/EN/ES o "" =
mai scelta — MAI fallback IT silenzioso: un valore sporco riapre il selettore),
`needs_language_selection`, `apply_language` (copia della config con `app_language`
+ `csv_language` ALLINEATE; codice non supportato → None fail-closed), etichette e
hint verbatim (supporto §5: lingua fonte XTrader = lingua bridge). Config:
`app_language` in DEFAULTS ("") con coercion fail-closed. GUI: Toplevel modale al
primo avvio (300ms dopo la principale), 3 bottoni bandiera; chiusura senza scelta =
comportamento storico IT, si ripropone. `_language_chosen` salva atomico via
`save_config` (propaga la lingua CSV runtime #342). Review round 1 (Fable/Fugu/GLM):
csv_language PERSONALIZZATA preservata sull'upgrade (mai overwrite a sorpresa del
separatore su XTrader vecchi), selettore RIMANDATO con auto-start attivo (mai grab
modale sopra un avvio non presidiato), log onesto su save fallito (niente falso
successo; round 2 Fable: config viva NON adottata su ok=False e writer CSV
riportato alla lingua precedente — mai sessione e disco divergenti; round 3
CodeRabbit/GPT/Fugu: guardia token PR-08c — marker letto prima del save,
_resync_token_field + _register_secret_token dopo — e rollback writer al valore
EFFETTIVO pre-save catturato con get_csv_language, mai None su config legacy). Docs ammorbidite («ITA richiedeva la virgola; update decimali-intelligenti
accetta entrambi», risposta supporto #343). Test: 7 unit puri + coercion + 6 glue,
mutazioni O–U KILLED.

## #343 slice 4a — UI localizzata: infrastruttura i18n + finestra principale (coda GUI, PR 10)

Nuovo modulo puro `i18n.py` stile gettext: chiavi = stringhe ITALIANE verbatim della
GUI (niente key sintetiche), `tr(testo)` → traduzione nella lingua attiva o il testo
stesso (fail-safe: mai vuoto/KeyError), `set_language` fail-safe (sporco/vuoto → IT),
stato di modulo sotto lock. Attivata da `app_language` PRIMA di `_build_ui`; cambio
lingua → al riavvio (log del selettore aggiornato). Scope: etichette STATICHE della
finestra principale (9 tab, 17 bottoni, campi form, 3 label, 11 etichette delle
impostazioni avanzate e 7 contatori Dashboard — CodeRabbit #357: i contenuti dei
tab tradotti non restano in italiano) in EN/ES. ESCLUSI e
motivati: stati «⬤ ATTIVO/…» (il semaforo Salute fa text-parsing dello stato →
prima serve uno stato canonico, slice dedicato), banner, log, finestre secondarie.
Test hard: default/fallback/traduzioni, ANTI-DRIFT (ogni chiave catalogo deve
esistere verbatim in app.py) e anti-revert (le label catalogate devono passare da
i18n.tr nel sorgente); mutazioni AA–AD KILLED.

## #343 slice 4b — Stato canonico del listener + «⬤» localizzato (coda GUI, PR 11)

Il semaforo 🚦 Salute leggeva il TESTO di `_status_lbl` (substring «ATTIVO»): con la
label localizzata si sarebbe rotto in EN/ES. Ora: `_listener_state` (fonte unica,
`health_check.LISTENER_*`, default di classe OFFLINE) impostato dal punto unico
`_set_listener_state(state, color)` nei 4 siti (START, STOP, riconnessione,
riconnesso); `_refresh_health_inner` legge il canonico via `__dict__` (rimosso il
blind-except sul cget: allowlist app.py 46→45, ratchet stretto); la label è SOLO
display localizzato («⬤  ACTIVE»/«⬤  ACTIVO», «⬤  RECONNECTING…»/«⬤  RECONEXIÓN…»,
OFFLINE universale via fallback). `health_check.evaluate` invariato (il canonico È
il substring). Harness del glue Salute aggiornato al nuovo contratto. Test: 3 glue
(canonico+display, semaforo riceve il canonico con label EN — fail-first sul vecchio
cget —, verde end-to-end in EN), mutazioni AH–AI KILLED.

## #343 slice 4c — Localizzazione finestre secondarie, parte 1: Anagrafica Provider (coda GUI, PR 12)

Prima finestra secondaria localizzata (`provider_gui.py`): titolo, header, bottoni,
placeholder, testo lista vuota E i messaggi di stato dinamici. I messaggi con
variabili passano dal template tradotto + `.format(...)` (chiave di catalogo = il
template con `{name}`/`{exc}`), così la finestra resta coerente (niente UI mista
EN-statico/IT-dinamico come segnalato su #357). Catalogo i18n esteso EN+ES;
anti-drift del catalogo ora estratto via AST (unisce i literal concatenati multi-linea
→ le chiavi lunghe delle finestre secondarie sono confrontabili). Nuovo test di
PARITÀ segnaposto: una traduzione che perde `{name}` fa fallire la suite (eviterebbe
un KeyError a runtime). Accorpati i 2 nitpick trivial di CodeRabbit #358: label OFFLINE
iniziale dalla fonte unica `_LISTENER_TEXTS` (niente duplicazione/drift), commento
«vestigiale» su `_status_lbl` nell'harness del glue Salute. Mutazioni AJ–AL KILLED
(chiave stantia, placeholder perso, wrap rimosso). Pattern pronto per replicare sulle
altre finestre nei prossimi slice.

## #343 slice 4d — Localizzazione finestre secondarie, parte 2: Profili impostazioni (coda GUI, PR 13)

Seconda finestra secondaria localizzata (`profiles_gui.py`) col pattern provato in 4c:
titolo, header, placeholder, bottoni (💾/↺/🗑), testi lista vuota/errore E i messaggi
di stato dinamici (template tradotto + `.format(name=…/exc=…)`, inclusi i campi con
conversione `!r`). Catalogo i18n EN+ES esteso (18 chiavi); anti-drift AST esteso a
`profiles_gui.py`. FUORI SCOPE dichiarato: i messaggi `❌ {exc}` che mostrano solo
l'eccezione bubblata dal modulo puro `profile_store` (testo di dominio, localizzazione
in uno slice a parte). Nuovo `test_profiles_i18n_343.py` (wrapping reale, copertura
EN/ES, parità segnaposto incl. `!r`, round-trip). Mutazioni AN–AP KILLED. Chat sorgenti
(finestra del filtro chat, safety-critical) tenuta separata per il prossimo slice.

## #343 slice 4e — Localizzazione finestre secondarie, parte 3: Chat sorgenti (chrome) (coda GUI, PR 14)

Terza finestra secondaria (`source_chats_gui.py`), la più delicata: è la finestra del
FILTRO CHAT (safety-critical). Localizzata SOLO la chrome di display: titolo, hint,
intestazioni colonne (i titoli via `i18n.tr` alla costruzione della tupla → l'anti-drift
AST li riconosce come costanti), bottoni, messaggi di stato GUI-composti («✅ Salvate {n}
sorgenti…», «❌ Salvataggio su disco FALLITO…», «Niente salvato…»). ESPLICITAMENTE FUORI
SCOPE (docstring + test dedicato che lo enforce): la sentinella `_NO_PARSER_BASE =
"(predefinito)"` (usata in confronti di UGUAGLIANZA in `_effective_parser_name`/`_save`,
NON semplice testo), l'helper puro `_translations_chip_text` (asserito verbatim in
`test_source_chats_translations.py`/`test_config_summary_gui.py`, vocabolario condiviso), e
gli errori/warning di dominio da `editor.apply()`. Nuovo `test_source_chats_i18n_343.py`
include un test che VERIFICA la non-localizzazione della sentinella/chip (guardia
anti-regressione). Mutazioni AQ (chiave stantia) e AR (sentinella localizzata → safety-test
fallisce) KILLED. Suite 2347 passed.

## #343 slice 4f — Localizzazione finestre secondarie, parte 4: Diario (coda GUI, PR 15)

Quarta finestra secondaria (`journal_view_gui.py`, sola lettura). Localizzata la chrome
(titolo, filtri, bottoni — «🔄 Aggiorna» riusa la chiave già a catalogo —, intestazioni
colonne, template conteggio/errore). Novità rispetto agli slice precedenti: due
valori-filtro sono DISPLAY *e* CHIAVI («(tutti i tipi)» confrontato in `_selected_types`;
«Tutti» in `_LAST_*` via int()→None). Gestiti localizzandoli alla COSTRUZIONE
(`self._all_types`/`self._last_choices`, dopo la scelta lingua) e confrontando col valore
tradotto — non come costanti di modulo (fissate all'import). Test di coerenza lingua↔
confronto in `test_journal_view_gui.py` (harness GUI): in EN/ES il sentinel tradotto →
nessun filtro. La finestra Strumenti (hub) è stata SCARTATA come target: i suoi
`TOOL_TITLES` sono chiavi di matching (`_resolve_tab_title`/`initial`) e contratti IA nei
test — localizzarli è un cambiamento cross-cutting a parte. Mutazioni AS (chiave stantia)
e AT (confronto sulla costante IT invece del valore tradotto → test coerenza fallisce)
KILLED. Suite 2353 passed.

## Fase 6 slice 1 — `resource_path()` Nuitka-aware per gli asset impacchettati (fondazione EXE Nuitka)

Prima slice della Fase 6 (passaggio dell'EXE ufficiale da PyInstaller a Nuitka): **hardening**
del punto unico che risolve gli asset read-only impacchettati (`data/dizionario_xtrader.csv`),
NON un bugfix — sotto Nuitka il path funzionava già oggi. Estratto da `dizionario._data_dir()`
un helper riusabile `resource_path(relative)` (CORE CHANGE: `xtrader_bridge/dizionario.py`), che
copre esplicitamente le tre forme di distribuzione con **ordine dei rami deliberato (Nuitka PRIMA
di `sys.frozen`)**:

- **Nuitka** (`--standalone`/`--onefile`): rilevato col modo RACCOMANDATO dai doc ufficiali
  Nuitka, l'attributo di modulo `__compiled__` — NON `sys.frozen`, che **Nuitka non imposta di
  proposito** (Nuitka User Manual, verificato: «Nuitka does *not* set sys.frozen … because it
  usually triggers inferior code»). Risolve via `__file__` (genitore del package), IDENTICO al
  sorgente (i dati `--include-data-dir` stanno relativi al programma in standalone, o spacchettati
  nella temp dir accanto ai moduli in onefile).
- **PyInstaller**: `sys._MEIPASS` (ramo gated su `sys.frozen`, fallback difensivo a
  `dirname(sys.executable)` se un freezer setta `frozen` senza `_MEIPASS`).
- **Sorgente**: `__file__`.

**Gating su `__compiled__` PRIMA di `sys.frozen` = difesa-in-profondità** (finding review Fable
#365, false positive sulla premessa ma azionato per robustezza): se un domani qualcosa impostasse
`sys.frozen` su un binario Nuitka, NON si cade nel ramo PyInstaller — in onefile
`dirname(executable)` punterebbe accanto all'EXE reale, dove i dati spacchettati NON sono
(→ dizionario non trovato → CSV senza lookup alias). Comportamento **byte-identico** per
sorgente/PyInstaller; `_data_dir()` ora delega a `resource_path("data")` (nessuna logica di path
duplicata). Test hard nuovi in `test_dizionario.py` (sorgente / PyInstaller `_MEIPASS` / Nuitka
`__compiled__`-non-frozen che IGNORA un `_MEIPASS` stray / Nuitka **con** `sys.frozen` impostato
che usa comunque `__file__` / fallback senza `_MEIPASS` / delega di `_data_dir`), verificati
fail-first con 4 mutazioni (gate `frozen` rimosso, fallback difensivo rimosso, `_data_dir` che
non delega, gate `__compiled__` rimosso→frozen-first) tutte KILLED. Suite 2368 passed. Il
workflow di build Nuitka vero e proprio + lockfile + smoke EXE Windows restano slice successive
della Fase 6.

## Fase 6 slice 2 — build EXE Nuitka di anteprima (ADDITIVA) + estensione gate di sicurezza

Introduce la build **Nuitka** SENZA rimuovere PyInstaller: scelta owner «additiva» (opzione A)
per non perdere la build di release funzionante finché il binario Nuitka non è validato su
Windows reale. Nuovo workflow `build-nuitka.yaml` (**solo `workflow_dispatch`**, niente tag,
niente Release → nessuna collisione con la release PyInstaller): `python -m nuitka --standalone
--onefile --assume-yes-for-downloads --enable-plugin=tk-inter --include-package-data=customtkinter
--include-data-files=data/dizionario_xtrader.csv=data/dizionario_xtrader.csv
--windows-console-mode=disable --output-filename=XTrader-Signal-Bridge.exe --output-dir=dist
main.py`; test bloccanti PRIMA della build; artifact `…-Nuitka-Windows-v<ver>-<data>` col solito
`XTrader-Signal-Bridge.exe`. Install legacy (`requirements-dev.txt` + `nuitka` + `httpx`): il
lock attuale è PyInstaller-only, il lock Nuitka `--require-hashes` arriva a parte.

Il gate di sicurezza `tests/safety/test_build_exe_safety.py` è **esteso** per coprire ANCHE la
forma Nuitka con la stessa filosofia **fail-closed** di PyInstaller: detector canonico Nuitka
(diretto `nuitka` **e** modulo `python -m nuitka`, entrambi canonici per Nuitka; wrapper
cmd/pwsh/sh rilevati e rifiutati), allowlist opzioni Nuitka, valori ristretti (plugin `tk-inter`,
package-data `customtkinter`, console `disable`, EXE personale in `dist/`), bundle SOLO il
dizionario via `--include-data-files` (niente `--include-data-dir`), nessun argomento dinamico,
build isolata nel suo step, test-prima-della-build, artifact = 1 solo EXE e nessuna Release. 16
nuovi test (incl. detector unit-test e regressioni maligne); 4 mutazioni sul workflow reale
(`--include-package` fuori allowlist, EXE «Admin», `--include-data-dir`, build senza test-prima)
tutte KILLED. Suite **2384 passed**. NB (lezione #363): i controlli del gate sono substring, quindi
i COMMENTI del workflow non possono contenere i token vietati (`continue-on-error`, «Admin EXE»).

**Docs:** README «Build EXE Nuitka (anteprima, in valutazione)» con lo smoke test manuale
consigliato per l'owner. Design handoff = **N/A** (nessun cambio GUI). CORE CHANGE = **nessuno**
(non tocca `xtrader_bridge/**` né `data/**`: solo workflow + test di sicurezza). Prossimo dopo la
validazione manuale su Windows: lockfile Nuitka riproducibile, poi ritiro di PyInstaller.

**Hardening da review (#366).** Fable 5 + Fugu Ultra (review finali) hanno segnalato in modo
convergente il rischio **supply-chain** dell'install non pinnato su un EXE che l'owner *esegue*:
mitigato senza attendere la slice lockfile — **Nuitka pinnato** (`nuitka==4.1.3`, stessa versione
che l'install non pinnato avrebbe preso oggi → zero cambio di comportamento, ma niente drift),
**`--msvc=latest`** per usare l'MSVC **preinstallato** su windows-latest (Nuitka non scarica più
il compilatore C: chiusa la superficie principale segnalata da Fugu), e rimosso l'install
esplicito ridondante di `httpx` (transitiva di python-telegram-bot). Il `--require-hashes`
completo resta la slice lockfile successiva (generata su Windows). CodeRabbit (2 Major): il gate
`test_nuitka_valori_opzioni_in_allowlist` ora **esige la PRESENZA** delle opzioni obbligatorie
(non solo il valore se presenti) e `test_nuitka_artifact_un_solo_exe_niente_release` ha il
guardrail no-Release **ampliato** (action `*/release*`, `gh release create/upload`, `files:`
inline **e** blocco `|`). 3 mutazioni aggiuntive (opzione obbligatoria omessa, `gh release
create`, action di release + `files: |`) tutte KILLED. Suite **2384 passed**.

### Fallback anti-quota del lock (#367)

Durante l'handshake del lock su #367 il check *Generate Windows Lockfile* falliva NON per il
git-diff stantio atteso ma allo step `upload-artifact` con *"Artifact storage quota has been
hit"* (backlog EXE che riempie la quota storage account-level; il conteggio GitHub si ricalcola
ogni 6-12h, quindi resta bloccato a lungo anche dopo una *Pulizia artifact* con `max_age_days=0`).
Il lock si generava correttamente, ma non era scaricabile → handshake bloccato. Fix: nuovo step
in `generate-lockfile.yaml` che scrive il `requirements-build.lock` generato nel **Job Summary**
della run (`GITHUB_STEP_SUMMARY`), PRIMA dell'upload e dei gate — così il lock (solo versioni +
hash, nessun segreto) è **copiabile dalla pagina della run** senza dipendere dall'artifact/quota,
e la rigenerazione diventa immune al muro-quota. Nessun cambio di permessi (`contents: read`),
niente auto-commit.

**Escalation opt. C (decisione owner):** siccome l'`upload-artifact` girava PRIMA dei gate reali
(anti-stantio + validazione), la sua fallita per quota teneva ROSSO il check anche con un lock
corretto (i gate non arrivavano nemmeno a girare). Rimosso del tutto l'`upload-artifact` dal
lock-workflow: il lock si consegna **solo** via Summary (quota-immune), e il check
`generate-windows-lockfile` diventa verde/rosso **solo** in base alla correttezza del lock
(git-diff + `--require-hashes`). Gli EXE (workflow `build.yaml`/`build-nuitka.yaml`) mantengono i
loro artifact: C tocca solo la consegna del **lock**. Test
`test_lockfile_consegnato_via_job_summary_quota_immune` (dump via `cat`/fence + **nessun**
`upload-artifact` nel lock-workflow); mutazione (cat→Get-Content) KILLED. README «Come
(ri)generare il lockfile» aggiornato (Summary invece di artifact). Suite **2388 passed**.

## Fase 6 slice 3 — lockfile Nuitka `--require-hashes` (chiusura residuo supply-chain)

Chiude il residuo supply-chain segnalato da Fable 5 + Fugu Ultra su #366: la build Nuitka non
installa più (a regime) da PyPI non bloccato, ma dal **lock riproducibile con hash**. Scelta:
**lock UNIFICATO** — `nuitka` aggiunto a `requirements-build.in` accanto a `pyinstaller`/`httpx`,
così un solo `requirements-build.lock` (generato su Windows+py3.11 da *Generate Windows Lockfile*)
copre entrambe le build; ogni workflow installa il set completo, l'altro tool resta inerte.

`build-nuitka.yaml` diventa **self-healing** (stessa logica di `build.yaml` + un check in più):
installa `--require-hashes -r requirements-build.lock` **solo se il lock contiene già `nuitka==`**
(rigenerato dopo l'aggiunta al `.in`); altrimenti ripiega sull'install legacy con **nuitka
pinnato** (`nuitka==4.1.3`), così la build resta funzionante finché il lock non è pronto.

**Handshake owner obbligatorio (per progetto, non un difetto):** aggiungere `nuitka` al `.in`
rende STANTIO il lock committato → il check *Generate Windows Lockfile* (trigger PR su
`requirements-build.in`) **fallisce** con `git diff --exit-code` finché l'owner non rigenera il
lock su Windows e lo ricommitte. La run — anche quella fallita in PR — **carica il lock corretto
come artifact** (upload PRIMA del gate anti-stantio, by design), che l'owner scarica e committa
sul branch della PR → verde → merge (manuale). Fino ad allora `build-nuitka.yaml` resta sul
fallback pinnato (nessuna rottura).

Test hard nuovi (2): `test_nuitka_nel_lock_source` (nuitka in `requirements-build.in`) e
`test_nuitka_install_usa_lock_con_hash_quando_disponibile` (ramo `--require-hashes` gated sul
lock-con-nuitka + fallback pinnato) — fail-first, 2 mutazioni (nuitka tolto dal `.in`; ramo
`--require-hashes` rimosso) KILLED. Suite **2386 passed**. CORE CHANGE = **nessuno** (solo
`requirements-build.in` + workflow + test + docs; nulla sotto `xtrader_bridge/**`/`data/**`).
Design handoff = **N/A** (nessun cambio GUI). Prossimo dopo la validazione Windows dell'owner:
**ritiro di PyInstaller** (Nuitka diventa la build di release).

## #311-1.2 — `drop_pending_updates` solo alla prima connessione RIUSCITA (recupero backlog su riconnessione)

Chiude il buco operativo #311-1.2: `App._run_bot` passava `drop_pending_updates=True` a OGNI
(ri)connessione del supervisor → un segnale arrivato durante un blip di rete di pochi secondi
era scartato per sempre, senza log. Ora un flag di sessione `first_connection` (nonlocal in
`_async_run`) rende `drop_pending_updates=True` **solo fino alla prima connessione RIUSCITA
della sessione**: il flag si abbassa a `False` **DOPO** un `start_polling` andato a buon fine —
non prima. Così, se la 1ª connessione **fallisce**, il flag resta `True` e il primo poll
riuscito **scarta comunque** il backlog pre-START (invariante anti-arretrati mai saltata);
solo una riconnessione **dopo una connessione già riuscita** (blip di rete a bridge già
connesso) usa `False`, così i messaggi dell'outage vengono **recuperati** (riga di log
«🔄 Riconnesso…»). Questo recepisce il blocker convergente di GPT-5.5/Fable 5/Fugu Ultra sul
#369: col flip fatto **prima** di `start_polling` (flip-per-giro), una 1ª connessione fallita
avrebbe già abbassato il flag e il primo poll riuscito NON avrebbe più scartato il backlog
pre-START → rischio di processare una scommessa accodata prima di START. L'anti-arretrati resta
comunque al filtro `max_signal_age`/`is_stale` (`telegram_dispatch.decide`, invariato e già
testato): un arretrato troppo vecchio è comunque scartato all'arrivo. **CORE CHANGE**
(`xtrader_bridge/app.py`, `_run_bot`/`_async_run`): da ri-sincronizzare nel cloud.

Test hard (in `test_reconnect_110.py`, sulla cornice reale del supervisor):
`test_drop_pending_updates_resta_true_se_la_prima_connessione_fallisce` (Test A —
fail→riconnessione: `drop_pending_updates=True` su ENTRAMBI i giri, l'invariante non salta) e
`test_drop_pending_updates_false_su_riconnessione_dopo_connessione_riuscita` (Test B —
connessione riuscita → `updater.stop` solleva → riconnessione stesso epoch: 1° giro `True`,
riconnessione `False`, recupera l'outage backlog); `test_first_connection_si_resetta_a_ogni_nuovo_START`
(Test C, review GLM 5.2 — due sessioni consecutive epoch 1/2: ogni nuovo START riparte da
`first_connection=True` e riscarta il backlog pre-START). `_Updater` fake esteso per catturare
i kwargs e per far sollevare `stop` dopo il successo. Fail-first: la mutazione «flip PRIMA di
`start_polling`» KILLED (Test A: la riconnessione passa `False` → assert `is True` fallisce);
la mutazione «flag promosso a stato d'istanza» KILLED (Test C: la 2ª sessione partirebbe da
`False`). STOP-durante-backoff e no-doppio-poller invariati (test #110/7 e lifecycle intatti).

Ridelivery anti-doppia-scommessa (review Fable 5 / Fugu Ultra): con `drop_pending_updates=False`
sulle riconnessioni, Telegram può rideliverare (at-least-once) un update già processato ma non
ancora ack-ato prima del blip. Il messaggio è FRESCO (`max_signal_age` non lo scarta): la
protezione è la **deduplica per contenuto** del `SignalTracker` (hash-messaggio, finestra
persistente 300s), valutata sotto `_queue_lock` in `write_path.commit_signal` PRIMA di ogni
scrittura CSV — indipendente da `update_id`. Coperto da `test_app_runtime_glue.py::
test_process_ridelivery_stesso_messaggio_non_scrive_due_volte` (stesso testo consegnato 2×: la 2ª
è DUPLICATE → `write_rows` chiamata una sola volta, CSV con UNA riga; mutazione «dedup azzerata»
KILLED), oltre alla copertura pre-esistente (`test_signal_dedupe`/`test_write_path`). Freschezza su
`channel_post`: `_handle` estrae la data da `update.message or update.channel_post` in modo
uniforme → `telegram_dispatch.decide`/`is_stale` la applica anche ai post di canale.

Suite **2391 passed, 11 skipped**. Docs: README «Cosa succede se cade la connessione?» aggiornato
(prima connessione riuscita scarta / riconnessione dopo successo recupera). Design handoff =
**N/A** (nessun cambio a schermate/tab/controlli/stati/indicatori: RICONNESSIONE→ATTIVO
invariato; aggiunta solo una riga di log informativa, non un elemento che il handoff descrive).

## #371 — clamp del `max_age` freschezza alla finestra di deduplica (hardening anti-doppia-scommessa)

Chiude il finding della final review **Fable 5** su #369 (deferito per decisione owner a PR dedicata,
tracciato in Issue #371). Con `drop_pending_updates=False` sulle riconnessioni (#311-1.2), Telegram
può **rideliverare** (at-least-once) un update già processato ma non ancora ack-ato prima del blip.
La protezione a valle è la deduplica per **contenuto** del `SignalTracker` (finestra `dedupe_window`,
default **300s**). Il filtro freschezza ammetteva però un messaggio fino a
`effective_max_age = min(max_signal_age, clear_delay)`, **senza** legame con la finestra dedup: con
config **non-default** (età effettiva > 300s) e un outage > finestra dedup, un update rideliverato era
ancora "fresco" (`is_stale` = False) ma **non più deduplicato** (hash scaduto) → seconda scrittura CSV
→ possibile **doppia scommessa**.

Fix (patch stretta): nuova funzione pura `message_freshness.capped_max_age(max_signal_age, clear_delay,
dedupe_window)` che clampa il `max_age` **attivo** ANCHE alla finestra dedup (fail-closed: un messaggio
troppo vecchio per essere protetto dalla dedup è trattato come **stantio**, scartato). Non ri-attiva un
filtro disattivato dall'utente (`max_age <= 0`), e con finestra dedup malformata/`<=0`/`None` non clampa.
`effective_max_age` resta **invariato**. `App._handle` usa ora `capped_max_age(...)` passando
`getattr(self._tracker, "dedupe_window", None)`. Con i **default** (eff 120s < 300s) il clamp **non
morde**: nessun cambiamento osservabile. **CORE CHANGE** (`xtrader_bridge/message_freshness.py` +
`xtrader_bridge/app.py::_handle`): da ri-sincronizzare nel cloud.

Test hard (`tests/unit/test_message_freshness.py`): `test_capped_max_age_clampa_alla_finestra_dedup`,
`test_capped_max_age_default_non_morde`, `test_capped_max_age_filtro_disattivato_resta_disattivato`,
`test_capped_max_age_finestra_dedup_invalida_nessun_clamp`, e l'integrazione fail-first
`test_capped_max_age_ridelivery_reconnect_e_stale` (config eff 600s + dedup 300s → un update a 350s è
STANTIO col clamp; mutation-guard: senza clamp sarebbe "fresco"). Mutazione «nessun clamp» → **KILLED**.
Suite **2396 passed, 11 skipped**. Docs: README (nota su `max_signal_age`) aggiornata. Design handoff =
**N/A** (nessun cambio a GUI/UX: modifica interna al filtro freschezza, nessun elemento del handoff).

## #371 (parte PTB) — conferma esplicita della connessione (`get_me`) prima del flip di `first_connection`

Chiude il secondo finding della final review **Fugu Ultra** su #369 (deferito e tracciato in #371,
hardening approvato dall'owner). Il modello di riconnessione del supervisor si basava sul fatto che
`Updater.start_polling()` **sollevi** al fallimento della prima connessione; ma in PTB v20/21
`start_polling` può **ritornare senza una connessione reale** (bootstrap fire-and-forget, `NetworkError`
di regime ritentati in background). In quel caso `first_connection` scenderebbe a `False` **senza** aver
scartato il backlog pre-START, e una riconnessione successiva userebbe `drop_pending_updates=False`
recuperando arretrati pre-avvio → possibile **doppia scommessa**.

Fix (patch stretta, `_async_run`): il flip `first_connection = False` è ora gated su una **conferma
esplicita** `await app.bot.get_me()` (round-trip reale a Telegram) subito dopo il primo `start_polling`.
Se la connessione non è reale, `get_me` **solleva** → l'eccezione propaga → il supervisor riconnette con
`first_connection` **ancora True** → `drop_pending` resta True (backlog pre-START comunque scartato).
La conferma parte **solo alla prima connessione della sessione** (`if first_connection:`), quindi le
riconnessioni non ripetono la chiamata. L'invariante anti-arretrati regge ora **a prescindere** dalla
semantica di `start_polling`, senza dipendere dal collaudo runtime. La `get_me` usa **timeout espliciti
di PTB** (`_CONNECT_CONFIRM_TIMEOUT = 15s`, review CodeRabbit): una conferma appesa scade sollevando
`telegram.error.TimedOut` — classificato TRANSITORIO da `reconnect_policy` → riconnessione — invece di
bloccare uno STOP indefinitamente; si usano i kwargs di PTB e NON `asyncio.wait_for` (che solleverebbe
`asyncio.TimeoutError`, non-telegram → classificato permanente → STOP indesiderato). **CORE CHANGE**
(`xtrader_bridge/app.py::_run_bot/_async_run`): da ri-sincronizzare nel cloud.

Test hard (`tests/integration/test_reconnect_110.py`):
`test_start_polling_ritorna_senza_connettere_non_abbassa_il_flag` (fire-and-forget + `get_me` che
solleva → riconnessione, `drop_pending=True` su entrambi i giri, teardown pulito, timeout bounded) e
`test_get_me_timedout_e_transitorio_riconnette_non_stop` (review Fugu Ultra/GLM/GPT — usa la
classificazione REALE `is_transient_error`, senza stubbare `should_reconnect`: un `TimedOut` da `get_me`
→ riconnessione, non STOP). `_TgApp` fake esteso con `bot.get_me` (default successo → A/B/C invariati).
Mutation-guard: rimuovendo il gate `get_me` → `len(apps)==1` KILLED; `get_me` senza timeout → assert
kwargs KILLED; `TimedOut` rimosso dai transitori → il test TimedOut KILLED. Suite **2401 passed,
11 skipped**.

Test hard (`tests/integration/test_reconnect_110.py`):
`test_start_polling_ritorna_senza_connettere_non_abbassa_il_flag` — `start_polling` NON solleva
(fire-and-forget) e `get_me` solleva alla 1ª connessione → riconnessione; `drop_pending_updates=True` su
ENTRAMBI i giri (il flag non è stato abbassato). `_TgApp` fake esteso con un `bot.get_me` (default
successo, così A/B/C e lifecycle restano invariati). Mutation-guard: rimuovendo il gate `get_me` la 1ª
connessione non-reale abbassa il flag e NON riconnette (nessun `get_me` che solleva) → `len(apps) == 1` →
**KILLED** (pulito, nessun hang). Suite **2400 passed, 11 skipped**. Docs: README «Cosa succede se cade la
connessione?» invariata (comportamento utente-osservabile non cambia; è robustezza interna). Design
handoff = **N/A** (nessun cambio GUI/UX). Resta all'owner l'eventuale collaudo runtime end-to-end, ma il
rischio è ora coperto da test offline.

## #311-2.3 — default `BOTH` con GATE su validazione dizionario (#311-2.2)

Slice #311-2.3 nella variante **gated** (decisione owner dopo il blocker Fugu Ultra su #374, chiusa
senza merge). Obiettivo di 2.3: rendere `BOTH` («ID se univoci, altrimenti nomi») il default consigliato
per le config nuove, così un miss del dizionario non scarta il segnale. Rischio bloccante (Fugu): `BOTH`
fa **accettare** un segnale sugli ID risolti dal dizionario Betfair; finché il dizionario non è validato
da un export XTrader reale (#311-2.2, righe `Fonte="Generato da schema"` ancora presenti), un match
**errato** scriverebbe `MarketId`/`SelectionId` sbagliati → in modalità REALE una scommessa sul
mercato/selezione errato.

Soluzione: **gate automatico**. `dizionario.is_validated()` (nuova, pura, fail-safe) è True sse il
dizionario ha almeno una riga e **ogni** riga ha `Fonte` nella **whitelist** `{"Export XTrader"}`
(fail-closed, review Fable 5/Fugu Ultra su #375: una blacklist del solo «Generato da schema» avrebbe
lasciato passare righe con `Fonte` vuota/assente/typo → `BOTH` su dati ignoti). Il fail-safe di
`_default_recognition_mode` ritorna `NAME_ONLY` **esplicito** in entrambi i rami (non `DEFAULT_MODE`, così
non può fail-aprire se un domani `DEFAULT_MODE` divergesse — review Fugu). Persistenza (nota Fable #2,
accettata dall'owner): il gate decide il default alla **creazione** della config; una config nata `BOTH`
resta `BOTH` anche se il dizionario venisse in seguito degradato — è un valore salvato esplicito, e un
re-check a runtime scavalcherebbe la scelta dell'utente; il conflict-check di `_resolve_ids_into` resta
comunque a valle. `config_store.load_config`,
**solo per una config NUOVA** (nessun file preesistente), imposta `recognition_mode` via
`_default_recognition_mode()` = `BOTH` sse `is_validated()` altrimenti `NAME_ONLY`. Il valore statico
`DEFAULTS["recognition_mode"]` resta `NAME_ONLY` (base per config legacy/parziali/corrotte); l'invariante
A10 (malformato → `NAME_ONLY`) è preservata. **Oggi** il dizionario reale ha 39 righe «Generato da schema»
→ `is_validated()` False → nuove config nascono `NAME_ONLY`: **comportamento invariato, il gate è un
no-op**. Quando #2.2 promuoverà tutte le righe a «Export XTrader», il gate aprirà `BOTH` **da solo**,
senza altre modifiche di codice. **CORE CHANGE** (`xtrader_bridge/dizionario.py`: `is_validated`;
`xtrader_bridge/config_store.py`: `_default_recognition_mode` + gate in `load_config`): da ri-sincronizzare
nel cloud.

Test hard (`tests/unit/test_config_basic.py`): `test_dizionario_is_validated_whitelist_fail_closed`
(whitelist: Fonte vuota/assente/typo → non validato — blocker Fable/Fugu/GPT chiuso),
`test_dizionario_is_validated_file_assente_fail_safe` (dizionario illeggibile → False, review GLM),
`test_dizionario_reale_oggi_non_validato` (il dizionario del repo NON è validato oggi),
`test_default_recognition_mode_gate` (BOTH↔validato, fail-safe → NAME_ONLY),
`test_config_nuova_gate_both_solo_a_dizionario_validato` (config nuova: NAME_ONLY oggi, BOTH a dizionario
validato — **mutazione «gate disattivato» KILLED**), `test_config_esistente_non_toccata_dal_gate` (config
esistente/legacy invariata). Allowlist blind-except aggiornata (`dizionario.py`, `config_store.py`).
Suite **2406 passed, 11 skipped**. Docs: README (nota gate) e `docs/xtrader_csv_contract.md`. Design
handoff = **N/A** (dropdown «🎯 Modalità riconoscimento» e opzioni invariati; cambia solo l'opzione
preselezionata per una config nuova, e solo dopo la validazione del dizionario). 2.3 «piena» (BOTH attivo)
resta legata a #2.2, che dipende dal collaudo reale (T19) dell'owner.

---

## #318-L2-1 — validazione numerica ASCII-only (fail-open cifre non-ASCII) — FATTO (PR #377)

Finding adversariale #318 (L2-1, MEDIUM, fail-OPEN). `numbers_re.DECIMAL`/`SIGNED_DECIMAL` — fonte unica
dei decimali usata da `validator`/`custom_pipeline`/`csv_writer`/`parser` — usava `\d`, che in Python
matcha **tutte** le cifre Unicode. Poiché `float("١٩") == 19.0`, un `Price`/`Handicap`/`Points`/`Min`/
`MaxPrice` scritto con cifre non-ASCII (arabo «١٩», devanagari «१९», fullwidth «１９») superava la
validazione ed entrava nel CSV letto da XTrader — **raggiungibile da un vero messaggio Telegram** via
parser custom. **Fix** (`\d`→`[0-9]` nella fonte unica; `SIGNED_DECIMAL` ora composto da `DECIMAL`
anti-drift): fail-closed propagato a tutti i consumer. **CORE CHANGE** (`xtrader_bridge/numbers_re.py`):
ri-sincronizzare nel cloud. Test hard: `test_numbers_re` (frammento + `_HANDICAP_RE`), `test_validator`
(Price/Points/Min/MaxPrice), end-to-end `test_custom_parser_end_to_end` (Telegram→parser→router, quota
araba → non piazzabile) — mutation-guard KILLED su `\d`. Docs: `docs/xtrader_csv_contract.md`. Suite 2411
passed.

---

## #318-L1-1 — `OverflowError` non catturato in `validators` (crash su int enorme) — FATTO

Finding adversariale #318 (L1-1, LOW/MED). `validators.require_positive_int`/`require_finite_now`
catturavano solo `(TypeError, ValueError)` attorno a `float(value)`. Un **int troppo grande per un
float** (es. `10**400` da un `config.json`/`daily_state.json` corrotto o manomesso) fa sollevare a
`float()` un **`OverflowError`** — che è sottoclasse di `ArithmeticError`, **non** di `ValueError` —
quindi propagava e **crashava** il chiamante (`DailyLimiter`/`SignalTracker`) dopo la UI «ATTIVO».
**Fix** (patch stretta): aggiunto `OverflowError` al catch in entrambe le funzioni → l'int enorme è
trattato come input **malformato** (`ValueError` controllato), coerente col pattern già usato in
`message_freshness.py`/`csv_writer.py`. Nessun cambio per gli input validi. **CORE CHANGE**
(`xtrader_bridge/validators.py`): ri-sincronizzare nel cloud. Test hard (`test_validators.py`):
`10**400` → `ValueError` su `require_positive_int` e `require_finite_now`, con **mutation-guard**
(sul vecchio codice propagavano `OverflowError`, che `pytest.raises(ValueError)` non cattura → test
rosso) + sanity `float(10**400)` → `OverflowError`. Suite **2433 passed**. Docs: README **N/A** (fix
interno, nessun comportamento user-visible o API documentata cambia). Design handoff **N/A** (nessun
elemento GUI/UX). Restano da triare gli altri finding #318 (L1-2/L1-3, L1-4, L2-2) — vedi Issue #376 §B.

---

## #318-L1-2 / L1-3 — isinstance guard su risposta Betfair malformata — FATTO

Finding adversariali #318 (L1-2 + L1-3, LOW, stesso file `betfair/catalogue_client.py`, stessa classe:
`.get(...)` su un valore non-dict → `AttributeError` che crasherebbe il thread di sync Betfair su una
risposta API malformata/anomala). Entrambi **fail-closed/contenuti** (il sync degrada a `FAILED` con
rollback, 0 righe scritte, nessun leak/DoS), ma il parser dichiarava una tolleranza ai campi che non
aveva. **Triage 2026-07-08: entrambi ancora presenti** (nessun fix pregresso).

- **L1-2** (`parse_market_catalogue`): un `runner` non-dict (`r.get(...)`) — e, stessa classe nella
  stessa funzione, un `description`/`event` **stringa/lista** truthy — alzavano `AttributeError`; un
  `runners` **non list/tuple** (es. `123`) alzava `TypeError` su `for` (review Fugu). Fix: `runner`
  non-dict → **saltato**; `description`/`event` non-dict → **coerciti a `{}`**; `runners` non list/tuple
  → **nessun runner**.
- **L1-3** (`_jsonrpc_result`): `(err.get("data") or {}).get("APINGException")` crashava se `data`/
  `APINGException` erano str/list. Fix: **isinstance guard** su `data_field` e `aping` → un errore con
  forma anomala resta classificato (`BetfairApiError`), solo senza il dettaglio `errorCode`; un `error`
  non-dict usa un **placeholder costante** (`<malformed>`) nel messaggio (review CodeRabbit/GPT/Fable:
  nessun contenuto remoto non attendibile nei log, anche troncato — anti log-injection).

**Patch stretta** (`betfair/catalogue_client.py`): nessun cambio per input validi. **CORE CHANGE** →
ri-sincronizzare nel cloud. Test hard (`test_betfair_catalogue_sync.py`): runner/description/event
non-dict → nessun crash, output coerente (`market_type`/`event.name` `None`, solo il runner valido);
`error.data`/`APINGException` str/list → `RuntimeError`/`BetfairApiError` (non `AttributeError`) —
**mutation-guard** (sul vecchio codice `pytest.raises(RuntimeError)` non catturava l'`AttributeError`).
Suite **2435 passed**. Docs: README **N/A** (fix interno Betfair, nessun comportamento user-visible);
design handoff **N/A**. Restano #318 **L1-4** (parser ReDoS) e **L2-2** (`_is_placeholder`).

---

## #318-L1-4 — ReDoS regex parser + #318-L2-2 — `_is_placeholder` permissivo — FATTO (2026-07-09)

Ultimi due finding adversariali #318, chiusi in un'unica PR stretta (stesso tema sicurezza,
scope minimo). Entrambi **fuori dal percorso live** o comunque a impatto contenuto.

- **L1-4** (`parser.py`, ReDoS): `_META_TAIL` e `_TRAILING_EMOJI` hanno backtracking **QUADRATICO**
  su input ostile (misurato: ~40KB → **11.7s**; caso `90+2` a 40KB → 11.7s). Usate dal parser
  **hardcoded** (`_clean_team_side`, ramo signal_type di `parse_message`), disattivato nel live
  (CP-09b) e comunque limitato dal cap Telegram ~4KB, ma latente DoS. **Fix: cap di lunghezza
  al call-site** (`_MAX_META_INPUT = 256`) — un «lato» squadra o un alias signal_type reali sono
  corti (< ~60 char); oltre soglia l'input non è legittimo. Con input ≤ cap il costo resta
  O(cap²) = trascurabile → **nessun ReDoS a prescindere dalla regex**. Le regex **NON** sono
  toccate: i quantificatori possessivi (Python 3.11) erano stati provati ma **cambiano cosa
  combacia** (l'originale si affida al backtracking per partizionare code tipo «90+2 FT» — un
  test regrediva) → tenuto il solo cap, a rischio zero.
  - **Estensione round-2 (review finale Fable 5):** sul ramo signal_type di `parse_message`
    erano quadratiche **anche** la **search di riga** `P\.Bet\.\s+(.+?)(?:…|$)` (misurato: riga
    ~40KB di whitespace → **~9s**, il contributo maggiore) e **`_STATUS_TAIL.sub`** (~5.8s), che
    giravano su input **non cappato**. **Fix: un unico guard di lunghezza sulla riga `P.Bet.`**
    (`len(line) <= _MAX_META_INPUT` prima della search) — dentro il cap `alias ≤ cap`, quindi
    `_STATUS_TAIL`/`_TRAILING_EMOJI` restano O(cap²). Comportamento **identico** per gli alias
    reali (corti: `GG LIVE`→`GG`, `Over 2.5 pre`→`Over 2.5`, emoji finale rimossa); oltre il cap
    nessun `signal_type` piazzabile (**fail-closed**). `parse_message` su input patologico: da
    ~8.9s → **~1.4ms**.
- **L2-2** (`value_maps.py`): `_is_placeholder` usava `"{" in v **and** "}" in v` → un placeholder
  **parziale/troncato** («{HOME_TEAM» senza `}`) NON era riconosciuto e sarebbe finito nella
  value-map come valore reale. **Fix: `and` → `or`** (fail-closed: i valori betting reali non
  contengono mai graffe, quindi UNA sola graffa = placeholder non sostituito → escluso).

**Patch stretta** (`parser.py` cap + 2 call-site; `value_maps.py` una condizione): nessun cambio
per input validi (suite parser/value_maps invariata, 565 test). Test hard
(`test_security_318_l1l2.py`): cap deterministico (over-cap → `None`), **bound temporale**
anti-ReDoS su input patologico ~50KB (era 11.7s → ora <5ms), correttezza casi reali invariata,
`_is_placeholder` sui parziali, value-map esclude il placeholder parziale. Suite **2535 passed**.
Docs: README **N/A** (fix interni, nessun comportamento user-visible/CSV/GUI); design handoff
**N/A**. Con questi due, i finding #318 **triati sono tutti chiusi**.

---

## Collaudo reale Betfair (2026-07-08) — problemi emersi + piano a fasi

Dal primo collaudo reale del proprietario (login + sync Betfair reale: 4 sport, 285 eventi, 3246
mercati, 12523 selezioni) sono emersi tre problemi nel **Dizionario Betfair** / mapping, con una
**radice comune** su due di essi:

- **P1 — separatori nome evento (Casa/Trasferta vuote + squadre non raccolte).** `split_participants`
  gestiva solo `" v "`/`" vs "`/`" @ "`. Gli eventi basket usano `" - "` («Atlanta Hawks - San Antonio
  Spurs») → `participant_2` vuoto → colonne Casa/Trasferta vuote nel viewer **e** `_harvest_teams` non
  salvava le squadre in `betfair_known_teams` (tab «Nomi Betfair noti» aveva solo i doppi di tennis).
- **P2 — viewer che si BLOCCA (freeze "Non risponde") + colonne disallineate.** Il
  `DictionaryViewerPanel` disegna ogni cella come widget CustomTkinter (~88.000 widget per le 12.523
  selezioni) su `CTkScrollableFrame`, sul thread GUI → minuti di freeze; le label a larghezza fissa
  sbordano coi nomi lunghi → colonne "sconcentrate".
- **P3 — mapping guidato ad albero (feature).** Richiesta owner: selettore Sport → Competizione →
  Squadre (dai dati Betfair) → associa al nome usato dal canale Telegram → salva. Sostituisce
  l'inserimento manuale in «Mapping / Dizionario nomi squadra».

**Piano a fasi (owner-approvato, priorità assoluta: "non deve bloccarsi"):**

### Fase 1 — separatori `split_participants` — FATTO

`_PARTICIPANT_SEPARATORS = (" vs ", " v ", " @ ", " - ")` (lista estendibile), provati in ordine; tutti
CON spazi (un trattino attaccato `Real-Madrid` non spezza). Il `" - "` (più ambiguo) è provato per
ultimo; nomi errati eventuali sono ripulibili dal tab «Nomi Betfair noti». `split_participants` è
informativo (mapping/viewer), non incide su CSV/scommessa. **Effetto:** dopo un **nuovo sync**,
Casa/Trasferta si popolano e le squadre basket/calcio entrano in `betfair_known_teams`. **CORE change**
(`xtrader_bridge/betfair/catalogue_client.py`) → ri-sincronizzare nel cloud. Test hard
(`test_split_participants`): basket `" - "`/`" @ "` → split (mutation-guard vs vecchio codice), tennis
doppio `A/B v C/D`, trattino attaccato non spezzato, `" vs "` prioritario su `" v "`. Suite **2435
passed**. README/design handoff **N/A** (logica interna; il rendering GUI è la Fase 2). Verifica owner:
livello «Eventi» (285 righe, non si blocca) dopo un nuovo sync.

### Fase 2 — viewer non-bloccante + colonne allineate — FATTO

Sostituito `CTkScrollableFrame`+label-per-cella con una tabella **nativa `ttk.Treeview`**
(virtualizzata: renderizza solo le righe visibili) + scrollbar + header e **larghezza per-colonna**
→ niente più freeze e colonne allineate. Aggiunto un **cap di `500` righe renderizzate** (`_ROW_CAP`)
applicato dal **controller DOPO tutti i filtri** (`view(..., limit=)`; NON una `LIMIT` SQL, che
taglierebbe prima dei filtri → risultati errati): la vista restituisce `shown` (righe filtrate prima
del cap) e `truncated`, e la riga conteggi invita a restringere con Sport/Cerca quando tronca.

**Scelta deliberata: niente threading/background.** Il freeze era **100% rendering** (costruzione di
~88.000 widget CTk sul thread Tk); la query pura (`fetchall` + filtri) è O(n) veloce. Virtualizzazione
+ cap eliminano il freeze senza introdurre marshalling Tk cross-thread e race di teardown (patch più
piccola e sicura, coerente con la REGOLA D'ORO). Il debouncer ricerca e il suo teardown (`destroy`)
restano invariati.

**Fix di review (stesso PR, un solo push):** aggiunta **scrollbar orizzontale** al Treeview
(CodeRabbit Major: i livelli larghi — Eventi ha 8 colonne × 150px — sbordavano e le colonne di destra
Casa/Trasferta/Attivo restavano irraggiungibili; usato `grid` per posizionare le due scrollbar); cap
reso difensivo `limit > 0` (nit GLM: un cap `0`/negativo non deve svuotare la tabella → vale «nessun
cap»).

Test hard (`test_betfair_dictionary_viewer.py`): `limit` tronca ma NON i conteggi (mutation-guard vs
vecchio codice che tornava tutte le righe), `limit=None`/`limit>totale`/`limit≤0` = nessun cap, cap
applicato DOPO `active_only` e DOPO la ricerca, `view_if_free` propaga `limit`. Suite completa verde. Aggiornato
allowlist blind-except (`dictionary_viewer_gui.py`: 1→2, per lo stile Treeview best-effort). Design
handoff §7.7 aggiornato. **Verifica manuale owner (richiede display, non in CI):** aprire Strumenti →
Dizionario, cambiare Livello su Mercati/Selezioni e premere 🔄 Aggiorna → la finestra **non** si blocca
più, le colonne sono allineate, e sopra la tabella compare l'avviso di troncamento a 500.

### Fase 3 — mapping guidato ad albero — FATTO

Nuova sotto-scheda **«🌳 Mapping guidato»** in Strumenti → Mapping (`guided_mapping_gui.py`), affiancata
a «⚽ Calcio» e «🎯 Mercati» (non-distruttivo). Flusso: **Sport → Competizione** (tendine dai dati
Betfair sincronizzati) → **Squadre** della competizione (unione `participant_1`/`participant_2` degli
eventi per `competition_id`, dedup) → accanto a ogni squadra l'**alias del canale** → **Salva** nel
**profilo `name_mappings`** scelto (merge, non sovrascrive; `entity_type=team`).

Decisioni owner-approvate: (1) **nuova sotto-scheda dedicata**; (2) squadre **dagli eventi della
competizione** (vero albero per-competizione; appaiono solo squadre con eventi sincronizzati);
(3) **profilo scelto dall'utente** (merge). Chiarimento: la **competizione è solo navigazione**, non
entra nella riga di mapping (il parser non filtra per competizione), quindi nessun cambio di schema
`name_mappings`.

Logica **pura e testata** in `betfair/guided_mapping.py`:
- `competitions_for_sport(db, sport)` — competizioni **attive** dello sport (scope `event_type_id`,
  dedup, ordinate);
- `teams_for_competition(db, competition_id)` — squadre uniche (union participant, vuoti scartati,
  include eventi disattivati per il roster storico);
- `merge_team_aliases(existing, sport, {squadra: alias})` — fonde le righe-squadra nel profilo
  **aggiornando** (no duplicati), **rimuovendo** su alias vuoto e **lasciando intatte** le altre righe
  (altri sport, mercati, righe manuali); match case/space-insensitive;
- `existing_aliases_for_teams(...)` — pre-compilazione degli alias già salvati (per-sport), così
  ri-salvare una competizione non azzera i mapping di squadre condivise con altre competizioni.

GUI (non testata in CI, richiede display): riuso store/persistenza esistenti
(`name_mapping_store.set_entries` + `config_store.save_config` + pattern anti-stale `on_saved`),
letture Betfair **fail-fast** su sync in corso (`DictionaryBusy`, come il viewer), **cap di rendering
500** squadre + filtro (come Fase 2) per non bloccare su competizioni popolose. Provider busy-guarded
in `app.py`: `_betfair_competitions` / `_betfair_teams_for_competition`.

Test hard (`test_betfair_guided_mapping.py`, 15): scope competizioni per sport, solo-attive+ordine,
union squadre/dedup/vuoti/eventi-disattivati, merge (add/update/remove/intatte/case-insensitive),
pre-compilazione. Suite completa verde. Allowlist blind-except aggiornata (`app.py` 45→47, nuovo
`guided_mapping_gui.py`=3). Smoke-import: `guided_mapping_gui` fra i moduli GUI (skip headless).
Design handoff §7.5 aggiornato. **Verifica manuale owner (display):** Strumenti → Mapping → 🌳 Mapping
guidato → scegli profilo, Sport, Competizione → scrivi alias → Salva; poi verifica nel parser che i
nomi vengano tradotti.

---

## #311-3.5 — Minori (una PR alla volta, dopo ogni merge del proprietario)

Coda approvata dei minori 3.5, nell'ordine (dal più sicuro al più delicato). Ogni voce = PR singola con
Phase 0 + micro-audit + test hard veritieri; merge sempre manuale.

| Ordine | Item | Stato | Note |
|---|---|---|---|
| 1ª | **pytest-timeout** | ✅ FATTO | non-core, rischio zero |
| 2ª | **archivio docs** | ✅ FATTO | 9 file storici → `docs/audit/archive/`; link aggiornati |
| 3ª | **ruff/mypy CI** | ✅ FATTO (questa PR) | **soft-warning** (scelta owner): non blocca |
| 4ª | **clock-skew dedupe** | ✅ FATTO | core; policy owner: clamp futuro ≤ 60s, scarta oltre |
| 5ª | **retry-budget CSV** | ✅ FATTO | core; backoff esponenziale 0.05→cap 0.4s + jitter, budget ≤1.5s, N=10 |
| 6ª | **daily-limit ora locale** | ✅ FATTO | core; reset a mezzanotte locale (`time.localtime`), DST del SO |
| ⏸️ | firma EXE | in sospeso | attesa certificato (acquisto/gratuito) |

### 3.5-a pytest-timeout — FATTO

`pytest-timeout>=2.1` aggiunto a `requirements-dev.txt`; `pytest.ini` imposta `timeout = 120` e
`timeout_method = thread` (cross-platform, Windows incluso). Un test che si impianta (loop/deadlock)
viene ucciso con stack trace invece di appendere la CI. 120 s è ~44× il test più lento (~2.7 s) →
nessun falso positivo. Configurato via **opzione ini** (non `addopts`): senza il plugin l'opzione è
ignorata, nessun errore «unrecognized arguments». Test hard `tests/unit/test_pytest_timeout_config.py`:
plugin installato, `pytest.ini` configurato, e sub-pytest con `timeout=1` nell'ini che **uccide davvero**
un test che dorme 5 s (prova del meccanismo, non solo del flag). Non-core, nessun impatto su CSV/Telegram/
config/design. Design handoff = N/A.

### 3.5-b archivio docs — FATTO

Spostati in `docs/audit/archive/` (via `git mv`, history preservata) i 9 doc storici/conclusi:
`roadmap1`, `blocco1_personale_roadmap`, `blocco_finalissima_184_roadmap`, `remediation_104_105`,
`resilience_109_matrix`, `resilience_110_matrix`, `final_audit`, `current_state`, `known_issues`.
Restano **vivi** in `docs/audit/`: `roadmap.md` (attiva), `xtrader_simulation_test.md` (collaudo
T1–T20), `release_checklist.md`, `mercati_mapping_design.md`. Tutti i riferimenti interni ai file
spostati sono stati aggiornati a `docs/audit/archive/…` (inclusi un commento in
`xtrader_bridge/betfair/__init__.py` e uno in `tests/integration/test_resilience_109.py`);
`archive/README.md` indicizza l'archivio. **CORE CHANGE** (tocca `xtrader_bridge/betfair/__init__.py`,
solo un path in commento): da ri-sincronizzare nel cloud. Nessun contenuto perso, solo riorganizzato.

### 3.5-c ruff/mypy CI — FATTO (soft-warning)

Scelta owner: **soft-warning** (non bloccante), per adozione graduale su un codebase esistente
senza cleanup di massa. Aggiunto un job `lint` in `.github/workflows/pr-checks.yml` con
`continue-on-error` **per-step**: **ruff** (`--output-format=github` → annotazioni inline) su
`xtrader_bridge`/`tests`/`main.py` e **mypy** sui soli **moduli puri** (`numbers_re`, `recognition`,
`validator`, `message_freshness`, `reconnect_policy` — oggi già puliti: baseline type-checked). Gli
strumenti stanno in **`requirements-lint.txt`** (separato, FUORI dal lock di build EXE: non lo
gonfia né richiede il regen). Config in **`pyproject.toml`** (`[tool.ruff]` select di default, no
E501; `[tool.mypy]` `ignore_missing_imports`). Oggi ruff segnala ~32 problemi informativi (import/
var inutilizzati), **non corretti** (era il cleanup grande evitato dalla scelta soft).

Il gate di sicurezza **#297** (`test_pytest_fail_closed_nei_workflow`) vietava `continue-on-error`
in QUALSIASI workflow (anti fail-open dei test): **emendato consapevolmente** (come il gate stesso
prevedeva) per ammettere `continue-on-error` **solo** su step di lint (ruff/mypy) e mantenerlo
**vietato** su qualunque step `pytest`/build (`pyinstaller`/`nuitka`/`compileall`/`py_compile`) —
il legame direttiva→step è per indentazione, così un commento a livello job non inganna il gate.
Mutation-guard verificato: `continue-on-error` su uno step pytest fa ancora fallire il gate. Test
hard: `tests/unit/test_lint_config.py` (config presente, soft, tool fuori dal lock). Non-core.

### 3.5-d clock-skew dedupe — FATTO

**Problema.** `message_freshness.is_stale` decideva la freschezza con `(now - msg_epoch) > max_age`:
un messaggio con `msg.date` **nel futuro** rispetto al clock locale dava sempre un delta negativo →
`is_stale` = False → **mai stantio** (comportamento documentato ma non protetto). Rischio reale: con
il **clock locale indietro** (NTP non sincronizzato, VM/BIOS) un backlog **vecchio** rifetchato dopo
un outage ha `msg.date` "nel futuro" e passerebbe come **fresco** → scritto/ripiazzato nel CSV
(segnale stantio ripiazzato, rischio doppia scommessa). La deduplica (`SignalTracker`) NON è toccata:
timestampa le voci con `time.time()` locale, non con `msg.date`, quindi il timestamp Telegram entra
**solo** in `is_stale` (il clock-skew della dedupe — salti dell'orologio locale — è già coperto da #184).

**Policy (owner).** Clamp con tolleranza **`max_skew` = 60s** (orologi ragionevolmente sincronizzati,
NTP): un messaggio futuro **entro 60s** è clampato ad "adesso" (resta fresco); **oltre 60s** è
implausibile → **stantio (fail-closed)**. Confine **inclusivo** (skew == 60 → fresco), coerente con
`max_age`.

**Fix (patch stretta, `message_freshness.py`).** Nuova costante `DEFAULT_MAX_CLOCK_SKEW = 60` e
parametro `max_skew` (default 60) su `is_stale`; nel ramo `msg_epoch > now` si ritorna
`(msg_epoch - now) > max_skew`. `max_skew` coerciuto con `_coerce_positive_finite`
(bool/malformato/NaN/inf/`<=0` → default, così una config rotta non spegne la protezione). **Nessun
chiamante toccato**: `telegram_dispatch.decide`/`app` usano il default 60. Un filtro anti-stale
disattivato dall'utente (`max_age <= 0`) resta tale (non si applica neppure il reject-skew).

**Test hard** (`tests/unit/test_message_freshness.py`): futuro ≤60 (incl. confine) → fresco; futuro
>60 (61/300/99999s) → stantio (**mutation-guard**: falliva sul vecchio codice); `max_skew` esplicito
e confine; `max_skew` malformato → default 60; filtro disattivato → futuro resta non stantio; costante
esposta = 60. Suite **2425 passed, 11 skipped**. **CORE change** (`xtrader_bridge/message_freshness.py`)
→ da ri-sincronizzare nel cloud. Design handoff = **N/A** (logica pura interna, nessun elemento GUI/UX).

### 3.5-e retry-budget CSV — FATTO

**Problema.** `csv_writer._replace_with_retry` (il rename atomico finale della scrittura/svuotamento
CSV, ritentato quando XTrader tiene il file bloccato in lettura su Windows) usava un backoff **fisso
0.1s** × 10 tentativi (budget ~1s, audit C3). Passo fisso: o troppe iterazioni identiche, o poca
elasticità se il lock durava un filo di più.

**Policy (owner).** Backoff **esponenziale** `0.05·2^i` con **jitter ±10%** e **cap 0.4s** per
attesa, **budget totale ≤1.5s**, tetto **N=10** tentativi. Il retry gira sul percorso live tenendo
`_write_lock`: il **budget** è il vincolo DOMINANTE (oltre ~1.5s ci si arrende → l'errore propaga →
rollback fail-safe nel chiamante → retry event-driven a valle), così il live non resta bloccato.

**Fix (patch stretta, `csv_writer.py`).** Costanti `_REPLACE_ATTEMPTS=10`, `_REPLACE_BASE_DELAY=0.05`,
`_REPLACE_MAX_DELAY=0.4`, `_REPLACE_BUDGET=1.5`, `_REPLACE_JITTER_FRAC=0.1`. `_replace_with_retry`
calcola `base·2^i`, applica il jitter, **clampa al cap** (il jitter non può sforare il cap) e poi al
**residuo di budget**; a budget esaurito propaga. `sleep`/`rng` iniettabili (default
`time.sleep`/`random.random`) per test deterministici; il budget si misura sui delay **nominali**
accumulati (riproducibile). La **classificazione** transitorio/permanente (`_is_retryable_replace_error`,
winerror 5/32/33 vs strutturali) resta **INVARIATA**: un errore permanente propaga al 1° tentativo.

**Test hard** (`tests/safety/test_csv_atomic.py`): sequenza esponenziale `[0.05,0.10,0.20,0.40,…]`
(**mutation-guard**: col vecchio passo fisso sarebbe `[0.1,0.1,…]`); cap ≤0.4; somma ≤1.5; budget
tronca prima del tetto N (anche con `attempts=1000`); jitter entro ±10% e sempre ≤cap; errore
strutturale escala subito (nessuna attesa). 6 test preesistenti adattati (`delay=0` → `sleep` no-op).
Suite **2429 passed, 11 skipped**. **CORE change** (`xtrader_bridge/csv_writer.py`) → da
ri-sincronizzare nel cloud. Docs: README **N/A** (la nota #105 H2 descrive il comportamento
user-visible — retry automatico/escalation/recupero — invariato; il backoff è un dettaglio interno).
Design handoff = **N/A** (nessun elemento GUI/UX).

### 3.5-f daily-limit ora locale — FATTO

**Problema.** Il tetto giornaliero (`DailyLimiter`, `max_per_day`) resettava il conteggio a
**mezzanotte UTC** (`safety_guard._day_key` usava `time.gmtime`), scelto in origine per evitare
salti di fuso/DST. Per un utente in Italia (UTC+1/+2) la "mezzanotte" del limite cadeva
all'01:00/02:00 locale, non alla sua mezzanotte reale.

**Policy (owner).** **(A)** ora locale del **sistema operativo** (`time.localtime`), **DST
automatico del SO**. Nessuna nuova opzione config/GUI, nessuna dipendenza aggiuntiva (l'app
desktop gira nel fuso dell'utente).

**Fix (patch stretta, `safety_guard.py`).** `_day_key` usa `time.localtime` invece di
`time.gmtime` — **unico** punto UTC-dipendente. Tutte le invarianti fail-closed di `_roll`/
`allow`/`remaining`/`restore_state` restano **invariate**: operano sul confronto della **chiave
data** `YYYY-MM-DD`, che è cronologicamente monotona nel tempo reale anche col DST (un cambio ora
avviene a notte fonda **entro lo stesso giorno** di calendario, non ne crea uno nuovo). `_is_valid_day`
(`strptime`) è già fuso-indipendente e non cambia.

**DST.** Delegato al SO: non richiede codice dedicato perché il rollover confronta **date**, non
ore. Non è testabile in modo deterministico offline cross-platform (Windows non ha il DB IANA e
`time.tzset` è Unix-only) → coperto da **smoke manuale** (cambiare l'orologio di Windows a cavallo
del cambio ora legale e verificare che il reset resti a mezzanotte locale) e dalla robustezza
per-data documentata.

**Test hard** (`tests/unit/test_safety_guard.py`): fixture autouse che forza `localtime=gmtime`
per rendere DETERMINISTICI i test a date assolute a prescindere dal `TZ` del runner; nuovi test con
fuso **UTC+2 simulato**: `_day_key` segue la mezzanotte LOCALE (**mutation-guard** vs `gmtime`), il
limiter resetta al giorno locale, e le invarianti **fail-closed** (salto orologio all'indietro non
riapre il tetto) valgono anche con fuso locale. Suite **2432 passed, 11 skipped**. **CORE change**
(`xtrader_bridge/safety_guard.py`) → da ri-sincronizzare nel cloud. Docs: README (`max_per_day`
«ora locale») aggiornato. Design handoff = **N/A** (nessun elemento GUI/UX; il comportamento del
tetto è logica interna, la label/soglia in GUI non cambia).

## #3 slice 5a — Foundation «lingua della fonte» (`source_language`) per il riconoscimento a nomi

**Contesto (epica multilingua #3).** Il supporto Betting Toolkit ha confermato che, col
riconoscimento **a NOMI**, i nomi di evento/mercato/selezione **dipendono dalla lingua** del
palinsesto della fonte (e, più a fondo, dall'exchange Betfair). Questa slice è la **fondazione**
(come `csv_language`/#342 lo fu per il selettore #343): introduce solo il *plumbing* della
lingua-fonte. **Nessun cambio al matching**: il filtro per-lingua sui profili nomi è la slice 5b.

**Tecnico.**
- Nuova chiave config globale `source_language` (default `""` = non dichiarata → agnostica,
  comportamento storico). Coercizione difensiva in `config_store._migrate` via
  `recognition.normalize_source_language` (IT/EN/ES o `""`, fail-closed come `app_language`:
  valore sporco → `""`, mai un IT silenzioso).
- Override **per-parser**: nuovo campo `CustomParserDef.source_language` (default `""` = eredita
  il globale). Serializzato in `to_dict`/`from_dict`, retro-compatibile (campo assente → `""`).
- `recognition.py` (modulo-gate puro, senza import): `SOURCE_LANGUAGES` (duplicato di
  `csv_writer.CSV_LANGUAGES`, con test anti-drift), `normalize_source_language`, e
  `effective_source_language(cfg, defn)` che risolve override-per-parser → globale → `""`
  (specchio di come `recognition_mode` combina globale + override). `defn` è **duck-typed**
  (nessun import di `custom_parser`: sarebbe un ciclo). **Consumato dalla slice 5b.**

**Sicurezza.** Fail-closed: una lingua-fonte mai scelta non viene mai finta (`""` = agnostica),
così il matching non si restringe a sorpresa (mai invertire/scartare un segnale per una lingua
inventata). Nessun impatto su CSV/Telegram/dedup. Contratto CSV invariato. Merge **manuale**.

**Test hard** (`tests/unit/test_source_language_5a.py`): `SOURCE_LANGUAGES` == `CSV_LANGUAGES`
(anti-drift); `normalize_source_language` su valide/sporche/tipi errati → fail-closed;
`effective_source_language` override>globale>vuoto e fail-closed su sporco (anche cfg non-dict);
round-trip `CustomParserDef` + retro-compat (campo assente/malformato → `""`); `DEFAULTS` e
`_migrate` normalizzano la chiave; override per-parser con **tipo non-stringa** → fail-closed
(GLM #22); **round-trip reale su disco** di `config.json` senza `source_language` che preserva
le altre chiavi (GPT #22). Suite **2359 passed, 11 skipped**. **CORE change**
(`recognition.py`, `custom_parser.py`, `config_store.py`) → da ri-sincronizzare nel cloud. Docs:
README (chiave `source_language`) + `docs/custom_parser.md` (campo per-parser) aggiornati. Design
handoff = **N/A** (nessun elemento GUI/UX in 5a: solo config/plumbing; il campo GUI per la
lingua-fonte arriverà con la slice che lo espone).

## #3 slice 5b (parte 1 — store) — Filtro LINGUA-fonte nel dizionario nomi

**Contesto (epica multilingua #3).** Col riconoscimento a NOMI i nomi dipendono dalla lingua
della fonte (conferma supporto). La 5a ha introdotto la fondazione `source_language` (globale +
override per-parser + `recognition.effective_source_language`). Questa slice porta il consumo al
livello **store** del dizionario nomi, come **terza dimensione di scope** accanto a
`sport`/`entity_type`.

**Tecnico (`name_mapping_store.py`).**
- Nuovo campo per-riga `language` (`IT`/`EN`/`ES`, chiave config `language`; **vuoto = agnostico**,
  retro-compatibile con le righe salvate prima). Normalizzato via `recognition.normalize_source_language`.
- Fail-closed: un `language` non-vuoto e non riconosciuto (typo) → riga **scartata** (come
  `sport`/`entity_type`), con avviso in `malformed_entry_warnings`; mai allargata a «tutte le lingue».
- `_scoped_entry_groups` guadagna `want_language`: elegge solo righe della lingua esatta o
  agnostiche, con **priorità alla lingua esatta** (tier). Rank `(entity, lingua, sport)`: senza
  filtro-lingua il rank-lingua è costante → **ordinamento legacy invariato**.
- `resolve_team`/`resolve_event_name` guadagnano il parametro `language` (default `None` = nessun
  filtro = comportamento storico), inoltrato a `_scoped_entry_groups`.
- **Retro-compatibilità chiave:** un dizionario tutto-agnostico (i setup esistenti) continua a
  risolvere anche con la lingua-fonte impostata (tier agnostico sempre eleggibile).

**Ancora aperto (prossima slice).** Il **cablaggio nella pipeline** (`custom_pipeline`/
`signal_router`/`parser_builder`) che calcola `effective_source_language(cfg, defn)` e la passa a
`resolve_*` su **entrambi** i seam live+preview (invariante di parità), e la **colonna GUI «Lingua»**
nel Dizionario nomi (con aggiornamento `design_handoff`). In QUESTA slice il filtro è impostabile
solo via `config.json` (nessun cambio di comportamento runtime finché la pipeline non passa la lingua).

**Safety.** Contratto CSV invariato; nessun impatto su Telegram/dedup/BetType; fail-closed su
lingua sbagliata/typo (mai un evento tradotto a caso → mai scommessa sbagliata). Merge **manuale**.

**Test hard** (`tests/unit/test_name_mapping.py`): normalizzazione + agnostico di default; typo
lingua fail-closed (riga scartata + avviso GUI); priorità lingua esatta > agnostica (anche su
agnostica salvata prima); dizionario tutto-agnostico + lingua impostata risolve ancora
(retro-compat); `language` None/""/ignota = nessun filtro; propagazione a `resolve_event_name`;
additività lingua × sport × tipo; **tie-break lingua > sport** nel rank (CodeRabbit #23, lock del
comportamento di selezione safety-relevant). Suite **2368 passed, 11 skipped**. **CORE change**
(`name_mapping_store.py`) → da ri-sincronizzare nel cloud. Docs: `docs/custom_parser.md` aggiornato.
README = **N/A** (nessun cambio utente/flusso in questa slice: campo config-only non ancora consumato
dalla pipeline). Design handoff = **N/A** (nessun elemento GUI in questa slice; la colonna «Lingua»
arriva con la slice del cablaggio+GUI).

## #3 slice 5b (parte 2 — wiring) — La pipeline consuma la lingua-fonte (parità live+preview)

**Contesto.** La 5a ha introdotto `source_language` (globale + override per-parser +
`recognition.effective_source_language`); la 5b «store» ha aggiunto il filtro-lingua nel
dizionario nomi (`resolve_team`/`resolve_event_name` con parametro `language`). Questa slice
**cabla** i due pezzi: la pipeline calcola la lingua-fonte effettiva e la passa al filtro, così
impostare la lingua-fonte **filtra davvero** il matching a runtime.

**Tecnico (cambio additivo, default `source_language=""` → nessun cambio di comportamento).**
- **`custom_pipeline.build_validated_row`**: nuovo kwarg `source_language`, inoltrato a
  `name_mapping_store.resolve_event_name(..., language=source_language)`. `build_validated_rows`
  lo propaga via `**kwargs` (base + retry + righe multi ereditano l'EventName già tradotto).
- **`signal_router._resolve_one` (LIVE)**: calcola `recognition.effective_source_language(cfg, defn)`
  e lo passa a `build_validated_rows`.
- **`parser_builder`** (ANTEPRIMA): `test_message`/`preview_rows`/`batch_report`/`_single_report`
  guadagnano `source_language`, inoltrato al motore; **`parser_diagnostics.diagnose`** idem (il
  verdetto «Pronto» resta allineato al live).
- **`custom_parser_gui`**: nuovo helper `_resolve_source_language(defn)` (stessa
  `effective_source_language` sulla config su disco) passato a test/diagnose/preview/batch.

**Invariante di parità (il cuore della slice).** Live e anteprima calcolano la lingua-fonte con
la **stessa** funzione (`effective_source_language`) sugli **stessi** input (cfg + defn), quindi
«Pronto in anteprima = scritto in live» resta vero anche col filtro-lingua attivo. Coperto da un
test dedicato.

**Safety.** Contratto CSV invariato; fail-closed su lingua sbagliata preservato (5b store);
retro-compat: dizionari agnostici risolvono ancora con lingua-fonte impostata. Merge **manuale**.

**Test hard** (`tests/integration/test_source_language_wiring_5b.py`, +6): filtro lingua in
`build_validated_row`; `resolve_row` (live) usa il dizionario della lingua-fonte globale;
override per-parser vince nel live; **parità live/preview** su EN/IT/"" (stesso EventName);
retro-compat dizionario agnostico; `""` = comportamento legacy; **`source_language` globale
malformata → fail-safe (nessun filtro, non «nessun match»)** su live+pipeline (GLM #24);
**percorso MULTI-RIGA**: la lingua-fonte si propaga a TUTTE le righe MultiSelection generate
(EventName mappato sulla base ereditato dalle derivate — Fable #24). Allowlist
blind-except `custom_parser_gui.py` 10→11 (nuovo resolver lingua fail-safe da config, motivato). Suite
**2376 passed, 11 skipped**. **CORE change** (`custom_pipeline.py`, `signal_router.py`,
`parser_builder.py`, `parser_diagnostics.py`, `custom_parser_gui.py`) → da ri-sincronizzare nel
cloud. Docs: README (`source_language` ora attiva) + `docs/custom_parser.md` aggiornati.
Design handoff = **N/A**: nessun elemento GUI **visibile** cambia (l'anteprima ora calcola la
lingua come il live, ma non compaiono nuovi widget/label/flussi); la **colonna GUI «Lingua»** —
con relativo aggiornamento handoff — è la slice successiva.

**Ancora aperto:** colonna GUI «Lingua» nel Dizionario nomi (design_handoff); poi 5c (colonna
`Lingua` del dizionario canonico) e 5d (Betfair per-exchange). *(nota storica: qui in origine
«La #3 si chiude solo a slice 5 completa» — impreciso: la slice 5 chiude solo il meccanismo
per-lingua; la #3 resta aperta per la slice 4 UI, vedi sezione 5d.)*

## #3 slice 5b (parte 3 — GUI) — Colonna «Lingua» nel Dizionario nomi

**Contesto.** La 5b «store» ha aggiunto il campo per-riga `language` al dizionario nomi e la 5b
«wiring» l'ha reso attivo a runtime (live+preview). Questa slice espone il campo nella **GUI** così
la lingua per riga si imposta con una tendina invece di editare `config.json`.

**Tecnico (`name_mapping_gui.py`).** Nuova colonna **«Lingua»** nella tabella del Dizionario nomi
squadra, speculare a **Sport**/**Tipo**:
- header `_HEADER_COLUMNS` esteso con `("Lingua", 130)`;
- tendina per riga con valori `[«(tutte le lingue)», IT, EN, ES]` (`recognition.SOURCE_LANGUAGES`);
- sentinella `_LANGUAGE_ALL` + helper `_language_to_label`/`_label_to_language` (agnostica «(tutte
  le lingue)» ↔ chiave dati `""`), come `_SPORT_ALL`/`_ENTITY_ALL`;
- `_append_row_widget` accetta `language=""`, `_collect_rows` emette la chiave `language`, il load
  delle righe passa `e.get("language","")`. Il precompila-da-Betfair lascia la lingua agnostica.
- Persistenza invariata: `name_mapping_store.set_entries`/`_clean_entry` normalizzano e fanno
  fail-closed sui typo (già dalla 5b store).

**Safety.** Solo vista/editing: nessuna modifica al matching o al contratto CSV; default agnostico
(nessun cambio di comportamento per i dizionari esistenti). Merge **manuale**.

**Test hard** (`tests/unit/test_name_mapping_gui_language.py`, +6, headless con stub `customtkinter`):
helper lingua round-trip + agnostica; header contiene «Lingua» senza rimuovere le colonne esistenti;
`_collect_rows` emette `language` (valorizzata resta, «(tutte le lingue)» → `""`) col contratto store
invariato; **il vero `_reload_rows` carica la `language` salvata** in `_append_row_widget` (regressione
sul `e.get("language","")` bloccata); **il vero `_append_row_widget` costruisce la tendina Lingua con
esattamente `[«(tutte le lingue)», IT, EN, ES]`** e la inizializza alla lingua passata (default →
agnostica) — usando un fake `customtkinter` più ricco (CodeRabbit/GLM #25); **resilienza**: una lingua
sconosciuta/stantia (`"FR"`, dato storico) è **preservata** (var + `_collect_rows`), non persa in
silenzio — la validità la impone lo store al salvataggio (CodeRabbit #25). La resa visuale resta uno
**smoke manuale** (apri 🗺️ Mapping → Dizionario nomi, imposta una riga a EN, salva, riapri → la tendina
mostra EN; una riga «(tutte le lingue)» resta agnostica). Suite **2383 passed, 11 skipped**. **CORE change** (`name_mapping_gui.py`) → da
ri-sincronizzare nel cloud. Docs: README + `docs/custom_parser.md` + **`docs/design/design_handoff.md`**
(tabella Dizionario nomi con la colonna «Lingua» e il default prefill) aggiornati.

**Ancora aperto:** 5c (colonna `Lingua` del dizionario mercati) e 5d (Betfair per-exchange IT-vs-UK).
La **slice 5** si completa con 5c + 5d; la **#3** resta poi aperta per la slice 4 (UI: banner/log). *(nota
storica: questa riga in origine diceva «#3 si chiude solo a slice 5 completa» — impreciso, vedi 5d.)*

## #3 slice 5c — Colonna «Lingua» nel Dizionario MERCATI

**Contesto.** La 5b ha portato il filtro-lingua-fonte al Dizionario **nomi** (store + wiring
live/preview + colonna GUI). Questa slice estende lo **stesso** filtro al Dizionario **mercati**
(`market_mapping_store`): anche le frasi-mercato che il provider scrive dipendono dalla lingua
della fonte, quindi la voce mercato guadagna una dimensione `language` speculare a quella dei nomi.
Target confermato dal proprietario («Dizionario mercati», non un ipotetico «dizionario canonico»:
il termine della 5b non era definito nel codice).

**Tecnico (cambio additivo, default `language=""`/`source_language=""` → nessun cambio di
comportamento).**
- **`market_mapping_store.py`**: nuovo campo per-voce `language` in `_clean_entry` (chiave config
  `language`; **vuoto = agnostico**, retro-compatibile). Fail-closed sui typo tramite il predicato
  unico `_malformed_fields` (voce **scartata** se `language` non-vuota e non `IT`/`EN`/`ES`, mai
  allargata a «tutte le lingue»), con `malformed_entry_warnings` per l'avviso GUI/log. `resolve_market`
  guadagna il parametro `language=None` (default = nessun filtro = legacy): scarta le voci di
  un'ALTRA lingua (le agnostiche restano) e la voce della lingua **esatta** ha priorità sull'agnostica
  (tier), come il dizionario nomi. `wl=""` → set invariato → ambiguità/risultato identici al legacy.
- **`custom_pipeline.build_validated_row`**: la `source_language` già calcolata dal 5b wiring
  (identica su live e anteprima) è ora inoltrata anche a `resolve_market(..., language=source_language)`
  — **una riga**. Live (`signal_router._resolve_one`) e anteprima (`parser_builder`/`custom_parser_gui`)
  passano già la stessa lingua, quindi la **parità** è preservata senza nuovi seam.
- **`app.py` `_start`**: surface di `market_mapping_store.malformed_entry_warnings(cfg)` nel log eventi
  (mirror dei nomi), così l'operatore vede subito una voce disattivata da un typo di lingua.
- **`name_mapping_gui.MarketMappingPanel`** (GUI): nuova colonna **«Lingua»** nella tabella del
  Dizionario mercati (header estratto nella costante `_MARKET_HEADER_COLUMNS`, speculare a
  `_HEADER_COLUMNS`); tendina per riga `[«(tutte le lingue)», IT, EN, ES]` riusando gli helper
  `_LANGUAGE_ALL`/`_language_to_label`/`_label_to_language` già introdotti dal 5b; `_append_row_widget`
  accetta `language=""`, `_collect_rows` emette `language`, `_reload_rows` passa `e.get("language","")`.
  Un valore fuori lista (dato storico) è **preservato** come opzione extra (non perso in silenzio).

**Safety.** Contratto CSV invariato; nessun impatto su Telegram/dedup/BetType; fail-closed su
lingua sbagliata/typo (mai un mercato di lingua sbagliata → mai scommessa sbagliata); ambiguità
resta `MARKET_MAPPING_MISSING` (D2). Retro-compat: dizionari mercati agnostici risolvono identici
con o senza lingua-fonte. Merge **manuale**.

**Test hard.** `tests/unit/test_market_mapping.py` (+10 store): normalizzazione + agnostico default;
typo lingua fail-closed (voce scartata + `malformed_entry_warnings`); `resolve_market` con lingua
esatta > agnostica (tier, niente falsa ambiguità); lingua diversa scartata con agnostica di riserva;
solo-lingua-diversa → `none`; dizionario agnostico + lingua impostata risolve (retro-compat);
`language` None/""/ignota = nessun filtro; legacy ambiguo invariato senza filtro.
`tests/integration/test_market_source_language_wiring_5c.py` (+7): wiring diretto in
`build_validated_row`; live (`resolve_row`) usa la lingua-fonte globale; override per-parser vince;
**parità live/preview** su EN/IT/"" (incluso il caso fail-closed ambiguo); retro-compat agnostico;
fail-safe su `source_language` malformata (= nessun filtro, non filtro rotto).
`tests/unit/test_market_mapping_gui_language.py` (+6, headless con stub `customtkinter`, mirror dei
nomi): header contiene «Lingua» senza rimuovere le altre; `_collect_rows` emette `language`;
`_reload_rows` carica la lingua salvata; `_append_row_widget` costruisce la tendina esatta e la
inizializza (default agnostica); resilienza valore sconosciuto («FR») preservato. La resa visuale
resta uno **smoke manuale** (apri 🧰 Strumenti → 🗺️ Mapping → 🎯 Mercati, imposta una voce a `EN`,
salva, riapri → la tendina mostra `EN`; «(tutte le lingue)» resta agnostica). Suite **2405 passed,
11 skipped**. **CORE change** (`market_mapping_store.py`, `custom_pipeline.py`, `app.py`,
`name_mapping_gui.py`) → da ri-sincronizzare nel cloud. Docs: README + `docs/custom_parser.md` +
**`docs/design/design_handoff.md`** (tabella Dizionario mercati con la colonna «Lingua») aggiornati.

**Ancora aperto:** 5d (Betfair per-exchange IT-vs-UK) — chiuso qui sotto.

## #3 slice 5d — per-exchange Betfair: rationale del supporto + completamento slice 5

**Contesto (risposte del supporto Betting Toolkit/XTrader, ticket 06-07-2026).** La domanda
aperta di slice 5 era la disuniformità «per-exchange». Il supporto ha chiarito:

- Col riconoscimento a NOMI «è **indispensabile** indicare, oltre al modo di riconoscimento,
  anche la **lingua della propria fonte**»: i nomi «dipendono dalla lingua scelta in fase di
  lettura del palinsesto (**oltre che dall'exchange**, in quanto Betfair fa piccole differenze
  tra i nomi ad esempio dell'exchange italiano e quelli dell'exchange in inglese letti con
  lingua IT)».
- La traduzione nomi per un exchange «**va verificata puntualmente e non dipende da**» BT/XT,
  «ma da BF». Betfair inoltre usa **ID diversi** per evento/mercato/selezione tra gli exchange.
- Struttura CSV, header, **codici `MarketType`** e BetType (BACK/LAY/PUNTA/BANCA) sono
  **identici** tra versioni/lingue. Separatore decimale: ora **indifferente** (il programma
  «digerisce» sia punto sia virgola su tutti i campi decimali, Handicap incluso).

**Decisione (scope stretto, nessun cambio core).** Per QUESTO bridge — **Betfair Sync
rimosso**, dizionario **user-built a mano**, arricchimento ID live **staccato**
(`id_resolver=None`) — la disuniformità per-exchange è già coperta dal meccanismo di 5a-5c:
l'utente costruisce il dizionario nomi/mercati con i **nomi esatti** della propria
fonte/exchange, **taggati con la lingua-fonte** (colonna «Lingua»). **NON** si introduce un
asse «exchange» separato: sarebbe complessità morta su un sottosistema rimosso, non
auto-popolabile senza la sync, e ridondante (un deployment legge da un solo setup
fonte+exchange, i cui nomi finiscono già nel dizionario per-lingua). Gli **ID diversi
per-exchange non toccano il CSV live** perché l'arricchimento ID è staccato.

**Cosa consegna la slice.** Nessun codice runtime nuovo: si **blocca con un test la garanzia
end-to-end** che chiude l'epica #3 — un UNICO segnale, con UNA sola lingua-fonte, filtra
**coerentemente sia il dizionario NOMI** (`EventName`) **sia il dizionario MERCATI**
(`MarketType`/`SelectionName`). Prima c'erano test separati nomi (5b) e mercati (5c), ma
nessuno esercitava i **due dizionari insieme** sullo stesso segnale.

**Test hard** (`tests/integration/test_multilingua_end_to_end_5d.py`, +5): la stessa
lingua-fonte filtra nomi+mercati sul percorso diretto (`build_validated_row`) e live
(`resolve_row`); isolamento EN/IT (nessun incrocio nome-di-una-lingua con mercato-di-un'altra);
**parità live/preview** end-to-end su EN/IT/"" (incluso il fail-closed ambiguo con "");
agnostico "" → mercato ambiguo → `MARKET_MAPPING_MISSING` (nessun mercato inventato); BetType
`BACK`→`PUNTA` canonico invariato. Suite **2411 passed, 11 skipped**. **CORE change = nessuno**
(solo `tests/**` + docs; nulla sotto `xtrader_bridge/**`). Docs: README + `docs/custom_parser.md`
(nota per-exchange/per-lingua per l'utente). Design handoff = **N/A** (nessun elemento GUI nuovo:
le colonne «Lingua» erano già in 5b/5c). Nota fuori scope: il Q4 «separatore indifferente» rende
non-critica la localizzazione decimale di #342 — possibile semplificazione futura, non toccata qui.

**Slice 5 COMPLETA (dizionario per-locale).** Il meccanismo «lingua-fonte + dizionari
nomi/mercati per-lingua user-built», con parità live/preview e fail-closed sui typo, è
completo con 5a→5b→5c→5d.

**⚠️ L'epica #3 NON è ancora chiusa.** #3 è l'epica multilingua **intera** e comprende anche
la **slice 4 — localizzazione UI completa** («l'intera UI in quella lingua»). Sono ora
**localizzati** i **banner** REALE/COLLAUDO (slice 4 banner), la finestra **🧙 Wizard** (slice
4h) e la finestra **🗺️ Mapping** (Dizionario nomi + mercati, slice 4i — qui sotto). **Residuo
ancora in italiano** (fonte autorevole: `design_handoff.md` § localizzazione):
- i **messaggi di log** dell'app (diagnostici): ~105 righe `self._log(...)` in
  `xtrader_bridge/app.py` non passano ancora da i18n `tr()`;
- la finestra **🧰 Strumenti (hub)** (`tools_gui`, rimandata: titoli-scheda = chiavi di
  matching) — non usa ancora `i18n.tr`.

Perciò la Issue #3 **resta aperta** finché anche questi non sono localizzati (slice successive,
raggruppate per area — decisione owner: banner prima, resto a slice). *(Nota: una versione
precedente scriveva erroneamente «#3 CHIUSA» — era riferito alla sola slice 5, non all'epica.)*

## #343 slice 4 — banner di modalità REALE/COLLAUDO localizzati (residuo banner della #3)

**Obiettivo.** Primo pezzo del residuo slice-4 (decisione owner: banner prima, i 105 log a
slice successive). Localizza i due **banner persistenti di sicurezza** — prima esclusi
(hardcoded IT): il **ROSSO** `real_mode.BANNER_TEXT` («⚠️ MODALITÀ REALE ATTIVA…») e l'**AMBRA**
`bridge_mode.COLLAUDO_BANNER_TEXT` («🔬 MODALITÀ COLLAUDO XTRADER…»).

**Cosa fa.** In `app.py` i due `configure(text=…)` passano ora da `i18n.tr(real_mode.BANNER_TEXT)`
e `i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT)`. Catalogo `i18n.py`: aggiunte le due chiavi con
traduzioni EN/ES (stringhe di SICUREZZA: severità preservata — emoji ⚠️/🔬, REAL/REALES,
TEST/PRUEBA). **Nessun cambio di logica**: la DECISIONE di mostrare il banner
(`real_mode.banner_active` / `bridge_mode.banners_for`, priorità rosso>ambra) è invariata; IT
resta il riferimento (fail-safe: lingua mai scelta → banner italiano storico).

**Test hard.** `tests/unit/test_i18n_343.py` (+3): default IT identità sui banner; traduzione
EN/ES verbatim + severità preservata (⚠️/🔬); wiring in app.py via `i18n.tr(...)`. L'anti-drift
lega ora le chiavi banner ai **valori reali** delle costanti (`_BANNER_TEXTS`), così un cambio
di `BANNER_TEXT`/`COLLAUDO_BANNER_TEXT` fa fallire il catalogo (mai traduzioni orfane).
`tests/integration/test_banner_i18n_343.py` (+4, headless via `object.__new__(App)` + stub
conftest, GPT #29): esercita `App._update_real_mode_banner` reale in EN/ES/IT e in simulazione,
verificando il testo EFFETTIVO passato al widget e la priorità rosso>ambra. Suite locale
(al commit): **2418 passed, 11 skipped** (l'esito autorevole è la CI del head PR, non questo
conteggio, che deriva dai test aggiunti). **CORE change** (`app.py`, `i18n.py`) →
ri-sincronizzare nel cloud. Docs: README + `design_handoff.md` (§ localizzazione: banner
spostati da «restano IT» a «localizzati»). Design handoff = **PASS** (aspetto UI di sicurezza
cambiato: aggiornato).

**Ancora aperto (per chiudere #3):** la localizzazione dei **~105 log** `self._log(...)` di
`app.py` **e** delle due finestre secondarie non ancora tradotte (🗺️ Mapping, 🧰 Strumenti
hub), in slice successive raggruppate per area.

## #343 slice 4h — Wizard di prima configurazione localizzato (residuo UI della #3)

**Obiettivo.** Prossimo pezzo del residuo slice-4 dopo i banner (scelta agente: la finestra
residua più **contenuta e sicura** — 259 righe, **0 rischi «valore=chiave»**, vs Mapping grande
e Strumenti hub esplicitamente rimandata). Localizza la **chrome** del Wizard (`wizard_gui.py`),
come già fatto per Provider/Profili/Chat sorgenti/Diario/Parser (4c-4g).

**Cosa fa.** In `wizard_gui.py` passano ora da `i18n.tr(...)`: il titolo finestra, i **5 titoli
step** (tupla `_TITLES`, resa via `i18n.tr(self._TITLES[step])`), i pulsanti nav (◀ Indietro /
Avanti ▶ / Fine ✔) e azione (🔌 getMe · 📡 Controlla ora · 🧪 Valuta messaggio · 🔎 Verifica
percorso · 📄 Scrivi CSV di prova), gli **hint** dei 5 step e i messaggi **GUI-composti** (⛔/✏️
di navigazione, ⏳ verifica, template errore imprevisto `{kind}`, «Nessun Parser attivo»).
Catalogo `i18n.py`: 24 chiavi × EN/ES (19 tr-constant + 5 titoli). **Escluso di proposito**
(resta IT, layer puro come le esclusioni 4e/4g): i `res.message` di **dominio** bubblati da
`wizard.py` (`check_token`/`check_chat`/`check_parser`/`check_csv`) — il wizard prepende solo
l'emoji universale ✅/⛔. **Nessun cambio di logica**: sonde, gate «Avanti» e invarianti di
sicurezza (il wizard NON attiva mai la modalità Reale) invariati.

**Test hard** (`tests/unit/test_wizard_i18n_343.py`, +5, pattern 4c): estrae via AST le
tr-constant + i literal `_TITLES`, richiede EN/ES per **ognuna** (nessuna UI mista), verifica i
segnaposto `{kind}` conservati e il round-trip `tr(template).format(...)`, più spot-check
verbatim. Anti-drift esteso (`test_i18n_343.py`): `wizard_gui` aggiunto ai tr-constant + sorgente
raw per i 5 titoli indiretti. Suite locale (al commit): **2423 passed, 11 skipped** (l'esito
autorevole è la CI del head PR). **CORE change** (`wizard_gui.py`, `i18n.py`) → ri-sincronizzare
nel cloud. Docs: README + `design_handoff.md` (§6.2-quater Wizard + § localizzazione). Design
handoff = **PASS** (finestra GUI localizzata: aggiornato).

**Ancora aperto (per chiudere #3):** ~105 log `self._log(...)` di `app.py` + finestre 🗺️ Mapping
e 🧰 Strumenti hub.

## #343 slice 4i — finestra Mapping (Dizionario nomi + mercati) localizzata (residuo UI della #3)

**Obiettivo.** Prossimo pezzo del residuo slice-4 (decisione owner: intera finestra Mapping in
un PR). Localizza la **chrome** di `name_mapping_gui.py` — entrambi i pannelli **🗺️ Dizionario
nomi** (`NameMappingPanel`) e **🎯 Dizionario mercati** (`MarketMappingPanel`), come per le
4c-4h.

**Perché intera finestra e non due slice.** I due pannelli **condividono codice quasi identico**
(gli stessi metodi `_load_cfg`/`_persist`/dialoghi profilo con **le stesse identiche stringhe di
stato**): uno split Nomi/Mercati lascerebbe righe identiche indistinguibili e produrrebbe UI
mista IT/EN nel pannello non ancora fatto (anti-pattern CodeRabbit #357). Le stringhe condivise
sono wrappate in entrambi i pannelli; catalogo con chiave unica.

**Cosa fa.** Passano ora da `i18n.tr(...)`: titoli finestra/pannello, sottotitoli, **etichette
colonna** (tuple `_HEADER_COLUMNS`/`_MARKET_HEADER_COLUMNS`, rese via `i18n.tr(text)` sulla
costante), pulsanti (Profilo/Nuovo/Rinomina/Elimina/Aggiungi riga/Precompila da Betfair/Salva
profilo), placeholder Entry mercato, e **tutti i messaggi di stato/dialogo GUI-composti** (creato/
rinominato/eliminato, save FALLITO, avvisi rinomina/delete con `MAPPING_MISSING`/
`MARKET_MAPPING_MISSING`, avvisi righe incomplete/senza delimitatori, ecc.), come template
`tr(...).format(...)`. Catalogo `i18n.py`: **60 chiavi nuove × EN/ES** (5 già a catalogo, riusate).

**Esclusioni documentate (restano IT — value-as-key / matching).** Le **sentinelle** delle
tendine (`_SPORT_ALL` «(tutti gli sport)», `_ENTITY_ALL`, `_LANGUAGE_ALL` «(tutte le lingue)»,
`_NO_PROFILE`) usate in confronti di uguaglianza; i **valori** delle tendine Sport/Tipo/Lingua e i
nomi Mercato/Selezione del **Catalogo** (chiavi/valori canonici); i **tab del container**
MappingPanel («⚽ Calcio»/«🎯 Mercati»/«🌳 Mapping guidato») — chiavi di matching e il pannello
🌳 **Mapping guidato** (`guided_mapping_gui.py`) è un modulo separato non ancora localizzato; il
dato interpolato in `{exc}` (dominio). **Nessun cambio di logica**: persistenza, gate, `_collect_rows`
e le invarianti (mai scommessa involontaria) invariate.

**Test hard** (`tests/unit/test_name_mapping_i18n_343.py`, +5, pattern 4c): estrae via AST le
tr-constant + i literal delle colonne, richiede EN/ES per **ognuna**, verifica i segnaposto
conservati e il round-trip `.format(...)`, e **asserisce le esclusioni** (sentinelle/tab NON
wrappati né a catalogo). Anti-drift esteso (`test_i18n_343.py`): `name_mapping_gui` nei tr-constant
+ sorgente raw per i literal colonna. Suite locale (al commit): **2428 passed, 11 skipped**
(l'esito autorevole è la CI del head PR). **CORE change** (`name_mapping_gui.py`, `i18n.py`) →
ri-sincronizzare nel cloud. Docs: README + `design_handoff.md` (§7.5 Mapping + § localizzazione).
Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** ~105 log `self._log(...)` di `app.py` + finestra 🧰 Strumenti
hub (`tools_gui`) + il pannello 🌳 Mapping guidato (`guided_mapping_gui`).

## #343 slice 4j — log di ciclo-vita del bridge (app.py) localizzati (residuo UI della #3)

**Obiettivo.** Primo gruppo del residuo dei **~105 `self._log(...)`** di `app.py` (decisione
owner: procedere a gruppi coerenti). Localizza il cluster **runtime lifecycle** — i log più
visibili all'utente: START, STOP, connessione, ascolto, scadenza segnale e svuotamento manuale
del CSV.

**Cosa fa.** Passano ora da `i18n.tr(...)` **8 righe** literal/f-string in `app.py`:
`🚀 Bridge avviato!`, `📄 CSV: {path}`, `⏱️  Auto-clear dopo: {seconds}s`,
`👂 In ascolto su Telegram...`, `🛑 Bridge fermato.`, `✅ Connesso a Telegram.`,
`⏱️  Scadenza segnale tra ~{seconds}s`, `🗑️  CSV svuotato manualmente` (le interpolazioni
diventano template `tr(...).format(...)`). Catalogo `i18n.py`: **8 chiavi nuove × EN/ES**
(«bridge»/«Telegram» verbatim, come nel resto del catalogo). `_log()` redige i segreti e
classifica il livello dal **marker emoji** iniziale (❌/⚠️/…): le traduzioni conservano il marker,
quindi il livello resta invariato in ogni lingua.

**Esclusioni documentate (restano IT — contenuto di dominio dai layer puri).** I log che
risalgono da funzioni pure NON sono wrappati né a catalogo: `bridge_mode.start_log_text(...)`,
`real_mode.enabled_message()`, `config_store.save_status_message(...)`, `outcome.*_log`,
`self._log(warning)`/`self._log(m)` e simili. **Nessun cambio di logica**: redazione segreti,
classificazione livello, invarianti CSV/coda/chat invariati.

**Test hard** (`tests/unit/test_app_log_i18n_343.py`, +5, pattern 4c): verifica il wrapping nel
sorgente (e che i vecchi literal/f-string non sopravvivano), la copertura EN/ES per ognuna delle
8 chiavi, la **conservazione dei segnaposto** `{path}`/`{seconds}`, il round-trip reale
`tr(...).format(...)` (marker emoji conservato) e **guardia sui log di dominio non wrappati**.
Anti-drift `test_i18n_343.py` resta verde (le 8 chiavi sono tr-constant verbatim in `app.py`).
Suite locale (al commit): **2433 passed, 11 skipped** (l'esito autorevole è la CI del head PR).
**CORE change** (`app.py`, `i18n.py`) → ri-sincronizzare nel cloud. Docs: README +
`design_handoff.md` (§ localizzazione log). Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~97 log `self._log(...)` di `app.py` (altri
gruppi: config/CSV, avvio/validazione, riconnessione, conferme XTrader, dominio-bubble che resta
IT) + finestra 🧰 Strumenti hub (`tools_gui`) + il pannello 🌳 Mapping guidato (`guided_mapping_gui`).

## #343 slice 4k — log CONFIG/CSV user-action (app.py) localizzati (residuo UI della #3)

**Obiettivo.** Secondo gruppo del residuo dei log `self._log(...)` di `app.py` (dopo il lifecycle
della 4j): le azioni utente su **configurazione e CSV** — salva config, toggle tema, salva/crea/
aggiorna il percorso CSV (pulsanti «💾 Salva Config», tema, «📁 Sfoglia…», «📄 Crea CSV»).

**Cosa fa.** Passano ora da `i18n.tr(...)` **13 chiavi** in `app.py`: «💾 Configurazione salvata»;
prefissi d'errore «❌ CSV Path selezionato ma NON salvato: » e «❌ Preferenza tema NON salvata: »;
«📄 CSV Path aggiornato e salvato: {path}»; «🎨 Tema: chiaro/scuro»; e l'intero set di messaggi
«Crea CSV» (bloccato-in-RUN, fallito `{path}`/`{exc}`, file estraneo `{path}`, segnale attivo
`{path}`, creato `{path}`, bloccato-avviato `{path}`, annullato-utente `{path}`). Le interpolazioni
`%s`/`f-string` diventano template `tr(...).format(...)`. Catalogo `i18n.py`: **13 chiavi × EN/ES**
(«Crea CSV» → «Create CSV»/«Crear CSV», coerente col bottone omonimo già a catalogo). Marker emoji
iniziale conservato → livello di log invariato.

**Esclusioni documentate (restano IT).** I **messaggi di stato del layer puro**
(`config_store.save_status_message(...)`): si wrappa **solo il PREFISSO**, lo stato resta IT
(stesso pattern degli error-prefix della slice Parser). Il dato interpolato `{exc}` è contenuto di
dominio. I **log di recovery/clear** con `{quando}` («all'avvio»/«allo stop»/…) e gli `on_mismatch`
di dominio (`f"⚠️ {m}"`) NON sono wrappati: richiedono una traduzione coordinata delle frasi
`{quando}` → **slice a parte**. Anche i **dialoghi modali** di «Crea CSV» (`messagebox`/
`filedialog`: titoli/conferme di sovrascrittura) restano IT: sono una superficie diversa dai log,
tracciata come residuo «dialoghi GUI». **Nessun cambio di logica**: persistenza config, guardie
CSV (runtime/foreign/active), gate REALE e invarianti (mai scommessa involontaria) invariate.

**Test hard** (`tests/unit/test_app_config_csv_i18n_343.py`, +7, pattern 4c/4j): estrae via AST le
costanti `tr` di `app.py` (unisce le costanti multi-riga concatenate dei messaggi «Crea CSV»),
verifica il wrapping e che i vecchi literal/`%s` non sopravvivano, la copertura EN/ES per ognuna
delle 13 chiavi, i **call-site `.format(...)`** dei log dinamici (mutation-guard su `{path}`/`{exc}`),
la conservazione dei segnaposto, il round-trip `.format(...)` e le **esclusioni** (dominio/`{quando}`
non wrappati). Anti-drift `test_i18n_343.py` esteso con `_APP_TR = _tr_constants("app.py")` (le
chiavi multi-riga concatenate non sono verbatim nel sorgente raw). Suite locale (al commit):
**2440 passed, 11 skipped** (l'esito autorevole è la CI del head PR). **CORE change** (`app.py`,
`i18n.py`) → ri-sincronizzare nel cloud. Docs: README + `design_handoff.md` (§ localizzazione log).
Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~84 log `self._log(...)` di `app.py` (avvio/
validazione START, riconnessione/backoff, conferme XTrader, recovery `{quando}`, dominio-bubble che
resta IT) + i **dialoghi modali** GUI + finestra 🧰 Strumenti hub (`tools_gui`) + il pannello
🌳 Mapping guidato (`guided_mapping_gui`).

## #343 slice 4l — log AVVIO/VALIDAZIONE START (app.py) localizzati (residuo UI della #3)

**Obiettivo.** Terzo gruppo del residuo dei log di `app.py` (dopo lifecycle 4j e config/CSV 4k):
i messaggi **safety-critical** che **bloccano/annullano lo START**, cioè quelli che spiegano
all'utente perché il bridge NON è partito.

**Cosa fa.** Passano ora da `i18n.tr(...)` **15 chiavi** in `_start`: python-telegram-bot assente;
Bot Token mancante; impostazioni avanzate non valide; nessuna chat configurata; nessun Parser
Personalizzato; «Sorgenti multi-chat: {err}»; «Avvio annullato: correggi le sorgenti»; auto-start
senza chat ATTIVA; nessuna chat ATTIVA (warning); conflitto Chat notifiche XTrader; auto-start
reale annullato; auto-start attivo; START reale annullato; «{problem} Avvio annullato»; CSV non
inizializzabile «({path}): {exc}». Le interpolazioni `%s`/f-string diventano template
`tr(...).format(...)`. Catalogo `i18n.py`: **15 chiavi × EN/ES** («bridge»/«Bot Token»/«listener»/
«Parser Personalizzato» verbatim). Marker emoji (❌/⚠️/⏸️/▶️) conservato → livello di log invariato.

**Esclusioni documentate (restano IT).** I log di **puro dominio** `f"❌ {err}"` (validation error da
`settings_validation`) e `f"⚠️ {warn}"` (avvisi da `source_manager`/`name_mapping_store`/
`market_mapping_store`) NON sono wrappati; i valori interpolati `{err}`/`{problem}`/`{exc}` sono
contenuto di dominio (invariati). I **dialoghi modali** `messagebox` di START in modalità reale
restano IT (residuo «dialoghi GUI»). **Nessun cambio di logica**: gate/fail-fast (token/chat/parser/
sorgenti/conflitto notifiche), conferma modalità reale, pre-flight e init CSV invariati.

**Test hard** (`tests/unit/test_app_start_i18n_343.py`, +6, pattern 4k): estrae via AST le costanti
`tr` di `app.py`, verifica il wrapping (e che i vecchi literal non sopravvivano), la copertura EN/ES
per le 15 chiavi, i **call-site `.format(...)`** dei log dinamici (mutation-guard `{err}`/`{problem}`/
`{path}`/`{exc}`), la conservazione dei segnaposto, il round-trip, il marker conservato (solo per le
chiavi con marker) e le **esclusioni** (`f"❌ {err}"`/`f"⚠️ {warn}"` non wrappati). Anti-drift
`test_i18n_343.py` resta verde (`_APP_TR` AST già introdotto in 4k). Suite locale (al commit):
**2447 passed, 11 skipped** (l'esito autorevole è la CI del head PR). **CORE change** (`app.py`,
`i18n.py`) → ri-sincronizzare nel cloud. Docs: README + `design_handoff.md` (§ localizzazione log).
Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~69 log `self._log(...)` di `app.py` (riconnessione/
backoff, conferme XTrader, recovery `{quando}`, dominio-bubble che resta IT) + i **dialoghi modali**
GUI + finestra 🧰 Strumenti hub (`tools_gui`) + il pannello 🌳 Mapping guidato (`guided_mapping_gui`).

## #343 slice 4m — log ESITO elaborazione messaggio/segnale (app.py) localizzati (residuo UI della #3)

**Obiettivo.** Quarto gruppo del residuo dei log di `app.py` (dopo lifecycle 4j, config/CSV 4k,
START 4l): i log runtime che spiegano **l'esito di un messaggio/segnale** durante l'ascolto — il
flusso attorno alle conferme XTrader (dispatch → scrittura CSV → conferma/scadenza).

**Cosa fa.** Passano ora da `i18n.tr(...)` **10 chiavi**: dispatch-ignore (messaggio troppo vecchio;
config live senza filtro chat; conflitto Chat-notifiche/sorgente; «Esito instradamento sconosciuto
({decision})»); scrittura CSV («Segnale scartato ({source}/{status}): {detail}»; «Scrittura CSV
fallita: {exc}…»; tracciabilità «Messaggio→CSV | msg: {msg} | riga: {row}»); conferma/scadenza
(«Aggiornamento CSV dopo conferma fallito: {exc}…»; «…alla scadenza fallito: {exc}…»; «{n} segnale/i
scaduto/i rimosso/i dal CSV»). Le interpolazioni f-string/concat diventano template
`tr(...).format(...)`. Catalogo `i18n.py`: **10 chiavi × EN/ES** («CSV»/«XTrader»/
`xtrader_notification_chat_id` verbatim). Marker (⏳/⚠️/❌/🧾/🗑️) conservato → livello invariato.

**Esclusioni documentate (restano IT).** Gli **esiti di DOMINIO** costruiti nei layer puri NON sono
wrappati: `outcome.signal_log`/`outcome.csv_log`/`outcome.log`, `multi_signal.blocked_message`,
`signal_outcome.confirmation_removed_log`/`confirmation_ignored_log` (i veri messaggi di ESITO
conferma «confermato/rifiutato/unmatched/unknown»), il traceback. I valori interpolati
`{source}`/`{status}`/`{detail}`/`{exc}`/`{decision}`/`{msg}`/`{row}`/`{n}` sono dominio. I log di
**riconnessione/backoff** (🔄 riconnesso, 🔌 connessione persa, ❌ errore non recuperabile) sono un
tema «connessione» a parte → **slice successiva**. **Nessun cambio di logica**: dispatch fail-closed,
scrittura CSV, coda/scadenza, rimozione su conferma e invarianti (mai scommessa involontaria)
invariate.

**Test hard** (`tests/unit/test_app_process_i18n_343.py`, +6, pattern 4l): estrae via AST le costanti
`tr`, verifica wrapping (+ assenza vecchi f-string), copertura EN/ES **con traduzione != IT** per le
10 chiavi, i **call-site `.format(...)`** dei log dinamici (mutation-guard `{decision}`/`{source}`/
`{status}`/`{detail}`/`{exc}`/`{msg}`/`{row}`/`{n}`), la conservazione dei segnaposto, il round-trip,
il marker conservato e le **esclusioni** (outcome.*_log/blocked_message/confirmation_* non wrappati).
Anti-drift `test_i18n_343.py` resta verde (`_APP_TR` AST). Suite locale (al commit): **2453 passed,
11 skipped** (l'esito autorevole è la CI del head PR). **CORE change** (`app.py`, `i18n.py`) →
ri-sincronizzare nel cloud. Docs: README + `design_handoff.md` (§ localizzazione log). Design
handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~59 log `self._log(...)` di `app.py` (riconnessione/
backoff, recovery `{quando}`, varie audit/diagnostica/retention/debug/lingua/multi-chat,
dominio-bubble che resta IT) + i **dialoghi modali** GUI + finestra 🧰 Strumenti hub (`tools_gui`) +
il pannello 🌳 Mapping guidato (`guided_mapping_gui`).

## #343 slice 4n — log RESILIENZA runtime (riconnessione + recovery CSV) localizzati (residuo UI della #3)

**Obiettivo.** Quinto gruppo del residuo dei log di `app.py` (dopo lifecycle 4j, config/CSV 4k,
START 4l, esito-elaborazione 4m): i log di **resilienza** del listener — riconnessione/backoff e
recovery del CSV — quelli che l'utente vede quando la connessione cade e si ripristina.

**Cosa fa.** Passano ora da `i18n.tr(...)` **5 chiavi**: «🔄 Riconnesso: … recuperati …»; «❌ Errore non
recuperabile del listener: {exc}. Bridge fermato.»; «🔌 Connessione persa ({error}): riconnessione tra
{delay}s (tentativo {attempt})…»; «🧹 CSV ripulito al retry dopo lo STOP: {path}»; «🧹 Rimossi {count}
file temporanei CSV orfani all'avvio.». Le interpolazioni f-string diventano template
`tr(...).format(...)` (il `{delay}` è pre-formattato `{d:.0f}` e passato come stringa). Catalogo
`i18n.py`: **5 chiavi × EN/ES** («listener»/«bridge»/«STOP»/«CSV» verbatim). Marker (🔄/❌/🔌/🧹)
conservato → livello invariato.

**Esclusioni documentate (restano IT — slice a parte).** I log di recovery `f"🧹 CSV riportato a solo
header {quando}: {path}"` e `f"⚠️ Impossibile ripulire il CSV {quando} ({exc}): …"` NON sono wrappati:
`{quando}` è **value-as-key** (in `_clear_stale_csv` è confrontato `== "all'avvio"` per scegliere
l'evento journal `CRASH_RECOVERY_CSV_CLEARED` vs `CSV_CLEARED`), quindi localizzarlo richiede uno
**split display↔chiave** — rimandato a una slice dedicata. I valori `{exc}`/`{error}`/`{path}`/`{count}`
sono dominio; il traceback e i domini-bubble restano IT. **Nessun cambio di logica**: policy di
reconnect/backoff (`reconnect_policy`), `_reconnect_wait`, recovery CSV e journal invariati.

**Test hard** (`tests/unit/test_app_resilience_i18n_343.py`, +6, pattern 4m): estrae via AST le
costanti `tr`, verifica wrapping (+ assenza vecchi f-string), copertura EN/ES **con traduzione != IT**
per le 5 chiavi, i **call-site `.format(...)`** dei log dinamici (mutation-guard `{exc}`/`{error}`/
`{delay}`/`{attempt}`/`{path}`/`{count}`), la conservazione dei segnaposto, il round-trip, il marker e
l'**esclusione `{quando}`** (recovery non wrappato). Anti-drift `test_i18n_343.py` resta verde
(`_APP_TR` AST). Suite locale (al commit): **2459 passed, 11 skipped** (l'esito autorevole è la CI del
head PR). **CORE change** (`app.py`, `i18n.py`) → ri-sincronizzare nel cloud. Docs: README +
`design_handoff.md` (§ localizzazione log). Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~54 log `self._log(...)` di `app.py` (recovery
`{quando}`, varie audit/diagnostica/retention/debug/lingua/multi-chat, dominio-bubble che resta IT) +
i **dialoghi modali** GUI + finestra 🧰 Strumenti hub (`tools_gui`) + il pannello 🌳 Mapping guidato
(`guided_mapping_gui`).

## #343 slice 4o — log LOG & DIAGNOSTICA (app.py) localizzati (residuo UI della #3)

**Obiettivo.** Sesto gruppo del residuo dei log di `app.py` (dopo lifecycle 4j, config/CSV 4k, START
4l, esito-elaborazione 4m, resilienza 4n): i log degli **strumenti Log & diagnostica** — apri cartella
log, export audit modalità reale, copia diagnostica, retention log, svuota log, toggle Debug.

**Cosa fa.** Passano ora da `i18n.tr(...)` **13 chiavi**: «📂 Cartella log: {path}» + errore apertura
{exc}; «🧾 Audit modalità reale esportato ({count} eventi): {path}» + errore export {exc}; «📋
Diagnostica copiata negli appunti.» + errore copia {exc}; retention (prefisso NON-salvata,
«{days} giorni · {count} rimossi», «conservo tutto», e la variante all'avvio «({days}g): {count}»);
«🧹 Log svuotati: {count} …»; «🐞 Modalità Debug log: {state}.» + prefisso Debug NON-salvata. Le
interpolazioni f-string diventano template `tr(...).format(...)`. Catalogo `i18n.py`: **13 chiavi ×
EN/ES** («Debug»/«ON»/«OFF» verbatim, stati tecnici). Marker (📂/❌/🧾/📋/🧹/🐞/⚠️) conservato →
livello invariato.

**Esclusioni documentate (restano IT).** I **suffissi di dominio** `config_store.save_status_message`
dei due log «NON salvata» (retention/debug): si wrappa **solo il prefisso**, lo stato specifico
(disco/keyring/config) resta IT (stesso pattern degli error-prefix delle slice precedenti). I valori
`{path}`/`{exc}`/`{count}`/`{days}` sono dominio; i log `_dbg(...)` (debug verboso di percorso) sono
fuori gruppo e restano IT. **Nessun cambio di logica**: retention/purge, toggle debug, export audit,
copia diagnostica e persistenza config invariati.

**Test hard** (`tests/unit/test_app_tools_i18n_343.py`, +6, pattern 4n): estrae via AST le costanti
`tr`, verifica wrapping (+ assenza vecchi f-string), copertura EN/ES **con traduzione != IT** per le 13
chiavi, i **call-site `.format(...)`** dei log dinamici (mutation-guard `{path}`/`{exc}`/`{count}`/
`{days}`/`{state}`), la conservazione dei segnaposto, il round-trip, il marker e l'**esclusione dei
suffissi di dominio** (regex robusta: prefisso wrappato, `save_status_message` fuori da `i18n.tr`).
Anti-drift `test_i18n_343.py` resta verde (`_APP_TR` AST). Suite locale (al commit): **2465 passed, 11
skipped** (l'esito autorevole è la CI del head PR). **CORE change** (`app.py`, `i18n.py`) →
ri-sincronizzare nel cloud. Docs: README + `design_handoff.md` (§ localizzazione log). Design handoff
= **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~41 log `self._log(...)` di `app.py` (recovery
`{quando}`, wizard/lingua, profilo/multi-chat/scheda, dominio-bubble che resta IT) + i **dialoghi
modali** GUI + finestra 🧰 Strumenti hub (`tools_gui`) + il pannello 🌳 Mapping guidato
(`guided_mapping_gui`).

## #343 slice 4p — log WIZARD + LINGUA-SELECTOR + PROFILO/SORGENTI (app.py) localizzati (residuo UI #3)

**Obiettivo.** Settimo gruppo del residuo dei log di `app.py` (dopo 4j–4o): i log delle azioni GUI di
**wizard**, **selettore lingua** (percorsi rimandato / salvataggio-fallito) e **applicazione profilo /
aggiornamento sorgenti**.

**Cosa fa.** Passano ora da `i18n.tr(...)` **8 chiavi**: «❌ Apertura wizard fallita: {exc}»; «🧙 Wizard
completato: configurazione salvata.»; «🌐 Selettore lingua rimandato: auto-start attivo …»; «⚠️ Lingua
scelta ({lang}) ma salvataggio config FALLITO …»; «⚠️ Scheda {tab} non aggiornata dal profilo …:
{exc}»; «📁 Profilo caricato e applicato (token invariato).»; «⚠️ Profilo applicato in memoria …, ma
NON persistito. » (prefisso); «📡 Sorgenti multi-chat aggiornate ({count}).». Catalogo `i18n.py`:
**8 chiavi × EN/ES** («wizard»→«asistente», «Profilo»→«Perfil», «Sorgenti»→«Fuentes», «Scheda»→
«Pestaña», coerenti col catalogo). Marker (❌/🧙/🌐/⚠️/📁/📡) conservato → livello invariato.

**Esclusioni documentate (restano IT — slice/contratto).** Il log di **SUCCESSO lingua**
«🌐 Lingua del bridge impostata: {lang}{extra} …» resta f-string IT non wrappata: ha un `{extra}`
**computato** (due sotto-stringhe) e una nota parenthetica ormai **stantia** («le altre finestre
arrivano con i prossimi slice» — molte già fatte), quindi richiede uno split del sotto-testo + una
decisione sul freshening della nota → **slice dedicata**. Il **suffisso di dominio**
`config_store.save_status_message` di «Profilo … NON persistito» resta IT (solo prefisso wrappato). Il
log **apertura-wizard-fallita** logga di proposito **solo `type(ex).__name__`** (mai il token, review
Fugu/GPT #354): preservato. I valori `{exc}`/`{lang}/{tab}/{count}` sono dominio. **Nessun cambio di
logica**: wizard finish/save, selettore lingua (`language_select.apply_language`, guardia token
PR-08c), persistenza profilo e refresh sorgenti invariati.

**Test hard** (`tests/unit/test_app_wizard_profile_i18n_343.py`, +6, pattern 4o): AST tr-constant,
copertura EN/ES **!= IT**, mutation-guard `.format` (`{exc}`/`{lang}`/`{tab}`/`{count}`), placeholder,
round-trip, marker, e **guardie di esclusione** (log SUCCESS lingua NON wrappato; suffisso dominio
fuori da `i18n.tr` via regex; wizard-fallito logga `type(ex).__name__`, non l'eccezione). Anti-drift
`test_i18n_343.py` resta verde (`_APP_TR` AST). Suite locale (al commit): **2471 passed, 11 skipped**.
**CORE change** (`app.py`, `i18n.py`) → ri-sincronizzare nel cloud. Docs: README + `design_handoff.md`
(§ localizzazione log). Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~33 log `self._log(...)` di `app.py` (recovery
`{quando}`, log SUCCESS lingua `{extra}`+nota, altri sparsi, dominio-bubble che resta IT) + i
**dialoghi modali** GUI + finestra 🧰 Strumenti hub (`tools_gui`) + il pannello 🌳 Mapping guidato
(`guided_mapping_gui`).

## #343 slice 4q — log GUARDRAIL RUNTIME (anti-duplicato / limite giornaliero / coda) localizzati (residuo UI #3)

**Obiettivo.** Ottavo gruppo del residuo dei log di `app.py` (dopo 4j–4p): i log di **stato dei
guardrail** emessi in `_init_guards`/`_save_guard_state` — anti-duplicato illeggibile, fallimento
persistenza dello stato anti-duplicato e del limite giornaliero, e l'informativo **modalità coda**.

**Cosa fa.** Passano ora da `i18n.tr(...)` **4 chiavi**: «⚠️ Stato anti-duplicato presente ma
illeggibile: protezione dopo riavvio non garantita.»; «🧮 Modalità coda: {mode}» (dinamica,
`.format(mode=guards.mode)`); «⚠️ Impossibile salvare lo stato anti-duplicato su disco: protezione
dopo riavvio degradata.»; «⚠️ Impossibile salvare lo stato del limite giornaliero su disco:
protezione anti-overtrading dopo riavvio degradata.». Catalogo `i18n.py`: **4 chiavi × EN/ES**.
Marker (⚠️/🧮) conservato → livello log invariato. Le tre chiavi multilinea sono letterali adiacenti
→ un singolo `ast.Constant`, trovato verbatim da `_APP_TR` (anti-drift).

**Esclusioni documentate (restano IT).** `self._log(warning)` nel loop `for warning in
guards.warnings` resta NON wrappato: è la **bolla di dominio** degli avvisi fail-safe prodotti dal
layer puro `runtime_state.build_guards` (non una chiave del catalogo). `{mode}` è valore di dominio
(nome modalità, display) — non usato come chiave/confronto. **Nessun cambio di logica**: dedupe,
limite giornaliero e coda invariati (pura presentazione).

**Test hard** (`tests/unit/test_app_guardrail_i18n_343.py`, pattern 4p): AST tr-constant (incluse le
multilinea), copertura EN/ES **!= IT**, mutation-guard `.format` (`{mode}`), placeholder, round-trip,
marker, e **guardia di esclusione** (`self._log(warning)` NON wrappato, niente `i18n.tr(warning)`).
Anti-drift `test_i18n_343.py` resta verde (`_APP_TR` AST). **CORE change** (`app.py`, `i18n.py`) →
ri-sincronizzare nel cloud. Docs: README + `design_handoff.md` (§ localizzazione log). Design handoff
= **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~29 log `self._log(...)` di `app.py` (recovery
`{quando}`, log SUCCESS lingua `{extra}`+nota, mode-toggle ANNULLATA, settings/timeout, altri sparsi,
dominio-bubble che resta IT) + i **dialoghi modali** GUI + finestra 🧰 Strumenti hub (`tools_gui`) + il
pannello 🌳 Mapping guidato (`guided_mapping_gui`).

## #343 slice 4r — log MODE-TRANSITION ANNULLATA (attivazione REALE/COLLAUDO/coda annullata) localizzati (residuo UI #3)

**Obiettivo.** Nono gruppo del residuo dei log di `app.py` (dopo 4j–4q): i log emessi in
`_gate_dangerous_transitions` quando l'utente **ANNULLA** la conferma di una transizione di modalità
pericolosa — attivazione **REALE**, attivazione **COLLAUDO**, coda **multi-segnale**.

**Cosa fa.** Passano ora da `i18n.tr(...)` **3 chiavi**: «↩️ Attivazione modalità REALE ANNULLATA:
torno a {old_mode}.» (dinamica, `.format(old_mode=old_mode)`); «↩️ Attivazione modalità COLLAUDO
ANNULLATA: torno a {old_mode}.» (dinamica); «↩️ Modalità coda multi-segnale ANNULLATA: resto a un
solo segnale attivo (OVERWRITE_LAST).». Catalogo `i18n.py`: **3 chiavi × EN/ES** — «REALE»→«REAL»,
«COLLAUDO»→«TEST» (EN) / «PRUEBA» (ES), coerenti coi banner di modalità (slice 4). Marker (↩️)
conservato → livello log invariato.

**Esclusioni documentate (restano IT).** Il log di **AUDIT** dell'attivazione REALE *confermata*
(`self._log("⚠️ " + real_mode.enabled_message())`) resta un messaggio di **dominio**: solo il prefisso
«⚠️ » è concatenato con `real_mode.enabled_message()`, che NON passa da `i18n.tr` (come per gli altri
suffissi di dominio). `{old_mode}` è un valore di dominio da `bridge_mode.mode_from_cfg`
(SIMULAZIONE/COLLAUDO/REALE) e resta invariato; `OVERWRITE_LAST` è un termine prodotto. **Nessun cambio
di logica**: gate di conferma, `apply_mode`, revert widget e coda invariati (pura presentazione).

**Test hard** (`tests/unit/test_app_mode_transition_i18n_343.py`, pattern 4q): AST tr-constant (incluse
le multilinea), mutation-guard `.format` (`{old_mode}`), copertura EN/ES **!= IT**, placeholder,
round-trip, marker, e **guardia di esclusione** (AUDIT `enabled_message` fuori da `i18n.tr`). Anti-drift
`test_i18n_343.py` resta verde (`_APP_TR` AST). **CORE change** (`app.py`, `i18n.py`) → ri-sincronizzare
nel cloud. Docs: README + `design_handoff.md` (§ localizzazione log). Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~26 log `self._log(...)` di `app.py` (recovery
`{quando}`, log SUCCESS lingua `{extra}`+nota, settings/timeout, dedupe-illeggibile warned, altri
sparsi, dominio-bubble che resta IT) + i **dialoghi modali** GUI + finestra 🧰 Strumenti hub
(`tools_gui`) + il pannello 🌳 Mapping guidato (`guided_mapping_gui`).

## #343 slice 4s — NOMI MODALITÀ di trading localizzati nei log (Issue #45, residuo UI #3)

**Obiettivo.** Chiude **Issue #45** (aperta durante la #44/4r su rilievo di GPT-5.5 + GLM 5.2): i due
log di annullo transizione (slice 4r) interpolano `{old_mode}` con un valore di dominio
(SIMULAZIONE/COLLAUDO/REALE) che restava in **italiano** anche in EN/ES, dando messaggi mistilingue
(«reverting to COLLAUDO»).

**Cosa fa.** Nuovo helper `App._mode_display_name(mode)` (**presentazione ONLY**): traduce il nome
modalità nella lingua UI via `i18n.tr("SIMULAZIONE"|"COLLAUDO"|"REALE")`, coerente coi banner di
modalità (REALE→REAL, COLLAUDO→TEST (EN)/PRUEBA (ES), SIMULAZIONE→SIMULATION (EN)/SIMULACIÓN (ES));
sconosciuto → valore raw (fail-safe). I due call-site di annullo passano ora
`self._mode_display_name(old_mode)` nel `.format(...)`. Catalogo `i18n.py`: **3 chiavi × EN/ES**. Le
chiavi sono usate come `i18n.tr("<literal>")` nell'helper → l'anti-drift le trova via `_APP_TR` (AST);
un `i18n.tr(variabile)` NON sarebbe stato rilevato.

**Invariante di sicurezza.** `_mode_display_name` NON muta MAI il valore di dominio usato dai gate
(`== REALE`, `apply_mode`, `mode_from_cfg`): traduce solo la resa testuale nel log. La **modalità coda**
(«🧮 Modalità coda: {mode}», slice 4q) NON rientra: `OVERWRITE_LAST`/`FIFO` sono termini tecnici, non
parole IT → il valore resta passato raw (verificato dal test di esclusione).

**Test hard** (`tests/unit/test_app_mode_names_i18n_343.py`): AST (helper presente + usa `i18n.tr`
literal, chiavi in `_APP_TR`, call-site usano `_mode_display_name`, niente `old_mode` raw), copertura
EN/ES **!= IT**, round-trip reale sul catalogo, guardia di esclusione modalità coda. Anti-drift
`test_i18n_343.py` verde (`_APP_TR` AST). Suite unit: **1921 passed, 1 skipped**. **CORE change**
(`app.py`, `i18n.py`) → ri-sincronizzare nel cloud. Docs: README + `design_handoff.md`. Design handoff
= **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~26 log `self._log(...)` di `app.py` (recovery
`{quando}`, log SUCCESS lingua `{extra}`+nota, settings/timeout, altri sparsi, dominio-bubble che resta
IT) + i **dialoghi modali** GUI + i pannelli GUI ancora in italiano (🧰 `tools_gui`, 🌳
`guided_mapping_gui`, `config_summary_gui`).

## #343 slice 4t — pannello «🧹 Nomi squadra noti» (known_teams_gui) localizzato (residuo UI #3)

**Obiettivo.** Primo pannello GUI localizzato del residuo (dopo i log di `app.py`): la scheda
**🧹 Nomi squadra** (ripulitura manuale dei nomi squadra permanenti del dizionario locale, `betfair_known_teams`).

**Cosa fa.** Passano da `i18n.tr(...)` **13 chiavi** UI: titolo/descrizione della scheda, label «Sport»,
bottoni «🔄 Aggiorna»/«🗑 Elimina», `label_text` «Nomi noti» e i 6 messaggi di stato (provider assente,
dizionario occupato, errore lettura `{exc}`, conteggio `{count}`, eliminazione non disponibile/fallita
`{exc}`/non riuscita). Catalogo `i18n.py`: **13 chiavi × EN/ES**. «Sport» resta identico in EN (parola
uguale). Anti-drift: `known_teams_gui.py` aggiunto a `_SECONDARY_TR` (le chiavi sono tutte
`i18n.tr("literal")`, descrizione multi-riga concatenata inclusa → AST le unisce).

**Esclusioni documentate (restano IT).** Il **sentinel** «(tutti gli sport)» (`_SPORT_ALL`) è un
**value-as-key**: usato nel confronto `s == _SPORT_ALL` in `_selected_sport` per distinguere «nessun
filtro» da uno sport reale → resta IT e **NON a catalogo** (localizzarlo romperebbe il confronto —
stessa regola delle sentinelle di `name_mapping_gui`, protetta dal test esistente
`test_esclusioni_value_as_key_non_wrappate`). I **nomi sport** (`sports.SPORTS`) e i **nomi squadra**
sono valori di dominio → invariati. **Nessun cambio di logica**: provider/delete/refresh/busy-guard
invariati (pura presentazione).

**Test hard** (`tests/unit/test_known_teams_i18n_343.py`): AST (tutte le label wrappate, dinamici
`{exc}`/`{count}` via `.format`, import i18n), copertura EN/ES **!= IT** (eccetto «Sport» identica in
EN), placeholder + marker, round-trip, e **guardia di esclusione value-as-key** (sentinel IT, non a
catalogo). I test headless esistenti (`test_known_teams_gui.py`) restano verdi (nessun cambio di
logica). Anti-drift `test_i18n_343.py` verde. Suite unit: **1928 passed, 1 skipped**. **CORE change**?
No — `known_teams_gui.py`/`i18n.py` non sono core-bridge, ma restano da ri-sincronizzare nel cloud.
Docs: README + `design_handoff.md`. Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~26 log `self._log(...)` di `app.py` (dominio-bubble/
value-as-key che restano IT + pochi candidati) + i **dialoghi modali** GUI + i pannelli GUI ancora in
italiano (🧰 `tools_gui`, 🌳 `guided_mapping_gui`, `config_summary_gui`).

## #343 slice 4u — pannello «📋 Riepilogo configurazione» (config_summary_gui) localizzato (residuo UI #3)

**Obiettivo.** Secondo pannello GUI localizzato del residuo (dopo 🧹 Nomi squadra): il **📋 Riepilogo
configurazione** (sola lettura) che mostra modalità Simulazione/REALE, stato del dizionario locale, e
per ogni canale → parser → traduzioni → «Pronto?».

**Cosa fa.** Passano da `i18n.tr(...)` **13 chiavi** rese dagli **helper puri di presentazione**
(testabili headless): riga modalità («🔴 MODALITÀ REALE»/«🧪 Simulazione (DRY_RUN)»), stato dizionario
(«Dizionario locale: presente/vuoto»), prefissi traduzioni «Nomi»/«Mercati», «✅ Pronto», segnaposto
«(canale senza chat_id)», «Canali pronti: {ready}/{total}», «Nessun canale configurato …», più i testi
inline del render («📋 Riepilogo configurazione», «Nessun dato di configurazione.», «⚠️ Impossibile
leggere la configurazione:\n{exc}»). Catalogo `i18n.py`: **13 chiavi × EN/ES**. Anti-drift:
`config_summary_gui.py` aggiunto a `_SECONDARY_TR` (tutte `i18n.tr("literal")`).

**Esclusioni documentate (restano IT).** La riga **«Parser: …»** (`parser_label`): «Parser» è un
**termine prodotto** e il resto sono **nomi parser di dominio** + simboli (⚠), niente di traducibile →
invariata. Il **MOTIVO** di «⚠ <motivo>» (`channel.reason`) è **testo di dominio** prodotto dal layer
puro `config_summary` → resta IT (solo «✅ Pronto» è tradotto). I **nomi canale/chat_id** sono valori di
dominio. **Nessun cambio di logica**: `summarize_config`/decisioni testo-colore invariate — pura
presentazione (in IT gli helper rendono identico all'attuale, garantito dai test esistenti).

**Test hard.** Estesi i test di presentazione reali `tests/integration/test_config_summary_gui.py`
(customtkinter stubbato, helper esercitati su `ConfigSummary`/`ChannelSummary` reali): i test IT
esistenti restano verdi (identità in IT) e **6 nuovi test EN/ES** verificano la resa localizzata
(modalità, dizionario su entrambi i rami, prefissi traduzioni, «Pronto»/conteggi/segnaposto/stato
vuoto, e le **stringhe inline di `_render`** — titolo, «nessun dato», errore config `{exc}` con
segnaposto conservato) **e le esclusioni** (riga Parser + motivo + nome canale restano IT). La resa dei
widget veri di `_render` richiede un display → documentato smoke test manuale nel test. Anti-drift
`test_i18n_343.py` verde. Suite unit+integration: **2253 passed, 1 skipped**. Docs: README +
`design_handoff.md`. Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~26 log `self._log(...)` di `app.py` (dominio-bubble/
value-as-key che restano IT + pochi candidati) + i **dialoghi modali** GUI + i pannelli GUI cross-cutting
ancora in italiano (🧰 `tools_gui` hub — titoli-scheda = chiavi di matching, 🌳 `guided_mapping_gui`).

## #343 slice 4v — «🌳 Mapping guidato» CHROME (guided_mapping_gui) localizzata (residuo UI #3)

**Obiettivo.** Terzo pannello GUI del residuo (dopo 🧹 Nomi squadra e 📋 Riepilogo): la **chrome
statica** del **🌳 Mapping guidato** (albero Sport → Competizione → Squadre → nome canale). Il pannello
è grande (~383 righe) → **spezzato in 2 slice**: 4v = chrome; **4w = messaggi di stato dinamici**.

**Cosa fa.** Passano da `i18n.tr(...)` **17 stringhe di chrome** (titolo, descrizione multi-riga,
label «Profilo/Sport/Competizione», filtro «Filtra squadre:» + placeholder + «Pulisci», intestazioni
colonne «Squadra Betfair»/«Come la chiama il canale», `label_text` «Squadre», bottoni «🆕 Nuovo»/«💾
Salva nel profilo», placeholder riga, empty-state, dialog «Nuovo profilo»/«Nome del nuovo profilo:»).
Catalogo `i18n.py`: **12 chiavi NUOVE × EN/ES** (le altre 5 — Profilo:/🆕 Nuovo/Sport:/Nome del nuovo
profilo:/Nuovo profilo — sono già a catalogo da pannelli precedenti; «Sport:» è ES-only, EN identità).
«Betfair» resta termine prodotto. Anti-drift: `guided_mapping_gui.py` aggiunto a `_SECONDARY_TR`.

**Esclusioni documentate (restano IT).** I **segnaposto value-as-key** «(nessun profilo)»
(`_NO_PROFILE`, confrontato `!= _NO_PROFILE` in `_on_profile_change`, già nella lista di
`test_esclusioni_value_as_key_non_wrappate`) e «(scegli lo sport)» (`_NO_COMP`, segnaposto «nessuna
competizione», assente da `_comp_by_label`) → non localizzati, non a catalogo. I **nomi
sport/competizione/squadra** sono valori di dominio. I **messaggi di stato dinamici** (con `{exc}`,
`{name}`, conteggi) sono **rimandati alla slice 4w**. **Nessun cambio di logica**:
provider/save/reload/filtro/debounce invariati (pura presentazione).

**Test hard** (`tests/unit/test_guided_mapping_i18n_343.py`): AST (chrome wrappata, vecchie stringhe
sparite), copertura EN/ES **!= IT** delle 12 chiavi nuove, **guardia value-as-key** (sentinel IT non a
catalogo), **scoping** (i messaggi di stato restano f-string IT — arrivano con 4w), round-trip. I test
logici esistenti (`test_betfair_guided_mapping.py`) restano verdi. Anti-drift `test_i18n_343.py` verde.
Suite unit+integration: **2258 passed, 1 skipped**. Docs: README + `design_handoff.md`. Design handoff
= **PASS**.

**Ancora aperto (per chiudere #3):** i **messaggi di stato dinamici** del 🌳 Mapping guidato (slice 4w)
+ i restanti ~26 log `self._log(...)` di `app.py` + i **dialoghi modali** GUI + l'hub 🧰 `tools_gui`
(cross-cutting: titoli-scheda = chiavi di matching).

## #343 slice 4w — «🌳 Mapping guidato» MESSAGGI DI STATO (guided_mapping_gui) localizzati (residuo UI #3)

**Obiettivo.** Completa la localizzazione del **🌳 Mapping guidato** (dopo la chrome della 4v): i
**messaggi di stato dinamici** del pannello (esiti di profilo/competizioni/squadre/salvataggio).

**Cosa fa.** Passano da `i18n.tr(...)` **13 messaggi di stato** (con template+`.format`): config
illeggibile `{exc}`, profilo non creato/esistente/creato `{name}`, salvataggio profilo fallito, nessuna
competizione `{sport}`/nessuna squadra, «{count} squadre…», cap-render «… mostrate {shown} di {total}…»,
nessun profilo selezionato/nessuna squadra da salvare, salvato `{profile}`/{written}/{total}, salvataggio
fallito `{profile}`. Catalogo `i18n.py`: **8 chiavi NUOVE × EN/ES** (competizioni/squadre/salvataggio
del guidato); le altre **5 sono RIUSATE** senza ri-aggiungerle per non duplicare la chiave — «⏳
Dizionario occupato…» (slice 4t) e i messaggi profilo-CRUD «ℹ️ Il profilo «{name}» esiste già.»/«❌
Config illeggibile: {exc}»/«⛔ Profilo non creato…»/«🆕 Profilo «{name}» creato.»/«❌ Salvataggio
FALLITO: «{name}» non creato.» (già a catalogo da `profiles_gui`). `guided_mapping_gui.py` è già in
`_SECONDARY_TR` (4v). **Fix duplicati (CodeRabbit #50):** rimossi 2 duplicati a **valore diverso**
preesistenti/introdotti — «ℹ️ Il profilo…» (EN «Profile…» vs «The profile…») e «📋 Diagnostica copiata
negli appunti.» (EN «…to clipboard» vs «…to the clipboard») — e aggiunta una **guardia AST anti-duplicati
a valore diverso** in `test_i18n_343.py` (protegge tutto il catalogo dalla stessa classe di regressione).

**Esclusioni (restano IT).** I **valori interpolati** nei segnaposto (`{exc}`, nome profilo `{name}/
{profile}`, nome sport `{sport}`, conteggi) sono dominio; i **segnaposto value-as-key** «(nessun
profilo)»/«(scegli lo sport)» restano IT (invariati dalla 4v). **Nessun cambio di logica**:
provider/save/reload/filtro/debounce invariati (solo il testo di stato è tradotto).

**Test hard** (`tests/unit/test_guided_mapping_i18n_343.py`, esteso): AST (status wrappati, nessun
f-string superstite), **mutation-guard `.format`** (tutti i segnaposto coperti), copertura EN/ES
**!= IT** + placeholder, round-trip. I test logici esistenti (`test_betfair_guided_mapping.py`) restano
verdi. Anti-drift `test_i18n_343.py` verde. Suite unit+integration: **2262 passed, 1 skipped** (incl.
la guardia anti-duplicati aggiunta nel fix review). Con la
4w il **🌳 Mapping guidato è completamente localizzato**. Docs: README + `design_handoff.md`. Design
handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~26 log `self._log(...)` di `app.py` (in gran parte
esclusioni permanenti) + i **dialoghi modali** GUI + l'hub 🧰 `tools_gui` (cross-cutting: titoli-scheda
= chiavi di matching).

## #343 slice 4x — hub «🧰 Strumenti» (tools_gui) localizzato (residuo UI #3)

**Obiettivo.** Localizzare l'ultimo pezzo cross-cutting della GUI: l'**hub «🧰 Strumenti»**, la
finestra a schede che raccoglie tutti gli strumenti del bridge. È la più delicata perché i titoli-scheda
sono anche **chiavi di matching** interne (`_resolve_tab_title`, `select_tab`): vanno tradotti senza
rompere la selezione della scheda.

**Cosa fa.** Passano da `i18n.tr(...)` a **build-time** (mai a livello di modulo, che congelerebbe la
lingua all'import): il **titolo finestra** (`ToolsWindow.__init__`, default `"🧰 Strumenti"` → `self.title(i18n.tr(title))`),
i **9 titoli-scheda** (etichetta base di `TOOL_TITLES`, resa in `build_tool_panels` come
`f"{prefix} {i18n.tr(TOOL_TITLES[key])}"`; il prefisso di gruppo ①..④ resta invariato) e la **label
d'errore per-scheda** (`i18n.tr("⚠️ Impossibile aprire questo strumento:\n{exc}").format(exc=exc)`).
`TOOL_TITLES` resta **IT canonico** (i suoi valori SONO le chiavi di catalogo). Catalogo `i18n.py`:
**11 chiavi NUOVE × EN/ES** (9 titoli + titolo finestra + label d'errore). Sicuro sul matching:
`_open_tools` chiama sempre `initial=None` (unico caller = pulsante «🧰 Strumenti»), e `_resolve_tab_title`
legge `self._panels` (le cui chiavi sono i titoli già localizzati) → **self-consistente** in ogni lingua.

**Esclusioni (restano IT).** «Provider»/«Parser» = **termini prodotto** (EN invariati; ES traduce solo
«Provider»→«Proveedor»). I `_name` dei gruppi in `TOOL_GROUPS` («Sorgenti»/«Lettura messaggi»/…) **non
sono mostrati** (solo IA interna) → non localizzati. Il valore interpolato `{exc}` è dominio.

**Test hard.** Nuovo `tests/unit/test_tools_hub_i18n_343.py`: AST (TOOL_TITLES ha solo literal IT →
niente `tr` a import-time; titolo/label wrappati a build-time; nessuna f-string superstite),
mutation-guard `.format(exc=...)` sulla label d'errore, copertura EN/ES (con eccezioni termini-prodotto
esplicite), round-trip. `tests/integration/test_tools_groups.py` esteso: `build_tool_panels` produce i
titoli **tradotti** in EN/ES (flusso reale con stub customtkinter) e `_resolve_tab_title` resta coerente
coi titoli localizzati; i test d'ordine IT esistenti restano verdi (fail-safe IT = identità), con fixture
di ripristino lingua. Anti-drift `test_i18n_343.py` esteso (`tools_gui.py` in `_SECONDARY_TR` per la
label-tr-constant + `_TOOLS_SRC` raw per i titoli resi via `i18n.tr(variable)`). Suite unit+integration:
**2521 passed, 11 skipped**. Docs: README + `design_handoff.md`. Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti ~26 log `self._log(...)` di `app.py` (in gran parte
esclusioni permanenti) + i **dialoghi modali** GUI. Con la 4x **tutte le finestre/pannelli GUI e l'hub
sono localizzati**: resta il residuo log di `app.py` e i modali.

## #343 slice 4y — dialoghi di CONFERMA MODALITÀ (app.py/multi_signal) localizzati (residuo UI #3)

**Obiettivo.** Localizzare i **dialoghi modali di conferma modalità** — i gate «frictionful» che
precedono la scrittura di scommesse: attivazione **REALE** (frase da digitare), **COLLAUDO** (sì/no),
**MULTI-segnale** (sì/no) e i **due gate autostart/START in modalità reale**.

**Cosa fa.** Passano da `i18n.tr(...)` **10 stringhe** (5 titoli + 5 corpi): i 5 titoli + il corpo REALE
+ i 2 corpi autostart/START sono `i18n.tr("literal")` in `app.py`; il corpo **COLLAUDO** è la costante
`bridge_mode.COLLAUDO_CONFIRM_TEXT` resa via `i18n.tr(bridge_mode.COLLAUDO_CONFIRM_TEXT)` (come i
banner); il corpo **MULTI-segnale** è localizzato **dentro `multi_signal.warning_text`** come
`i18n.tr("… {max_active} …").format(max_active=…)` (il modulo importa ora `i18n`). Catalogo `i18n.py`:
**10 chiavi NUOVE × EN/ES**.

**SAFETY (invariante centrale).** La **frase da digitare** per confermare la modalità reale resta
**`real_mode.CONFIRM_PHRASE` = «REALE»** in OGNI lingua: è interpolata come **valore**
(`.format(phrase=real_mode.CONFIRM_PHRASE)`), **mai** passata da `i18n.tr`, perché
`real_mode.confirmation_ok` la confronta letteralmente (`upper() == "REALE"`). Localizzarla romperebbe
il gate anti-scommessa. `real_mode.py`/`bridge_mode.py`/`real_mode.confirmation_ok` **non toccati**; il
`return bool(askyesno(...))` dei gate è invariato — cambia solo la lingua del testo. Severità/parole-
rischio preservate (ATTENZIONE→WARNING/ATENCIÓN, VERE→REAL/REALES, «MULTI» invariato). `{max_active}` è
il tetto (valore di dominio); `active_count_text`/`blocked_message` di `multi_signal` **fuori scope**
(non sono dialoghi di conferma).

**Test hard.** Nuovo `tests/unit/test_mode_confirm_dialogs_i18n_343.py`: AST (titoli/corpi wrappati in
`app.py`, COLLAUDO via `i18n.tr(costante)`, warning_text via tr-constant+`.format` in `multi_signal`),
copertura EN/ES **!= IT** + placeholder (`{phrase}`/`{max_active}`), **round-trip sulla FUNZIONE reale**
`multi_signal.warning_text(2/3/5)` in IT/EN/ES, e il **test SAFETY** che verifica che «REALE» resta
visibile nel dialog reale in ogni lingua e che `confirmation_ok("REALE")=True`/`("REAL")=False`. I test
esistenti `test_multi_signal.py`/`test_real_mode.py` restano verdi (IT identità). Anti-drift
`test_i18n_343.py` esteso (`bridge_mode.COLLAUDO_CONFIRM_TEXT` nel set costanti + tr-constant di
`multi_signal.py`). Suite unit+integration: **2528 passed, 11 skipped**. Docs: README + `design_handoff.md`
(§9 + fix nota «ancora IT» stantia). Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti log `self._log(...)` di `app.py` (in gran parte
esclusioni permanenti) + alcuni **avvisi/dialoghi GUI non di conferma-modalità** (warning salvataggio
CSV, showinfo audit, ecc.) + la nota SUCCESS del selettore lingua da attualizzare.

## #343 slice 4z — dialoghi GUI di AZIONE FILE (app.py) localizzati (residuo UI #3)

**Obiettivo.** Localizzare i **dialoghi modali di azione file** — la superficie «dialoghi GUI» distinta
dai log: selettori file e avvisi/conferme dei flussi «📁 Sfoglia CSV», «📄 Crea CSV» e «Esporta audit
modalità reale».

**Cosa fa.** Passano da `i18n.tr(...)` **13 stringhe** in `app.py`: 3 titoli `filedialog`
(Sfoglia/Crea CSV, Esporta audit) + 2 label `filetypes` («Tutti i file», «Testo»; «CSV» resta termine
prodotto) + `showwarning` «Bridge avviato» (titolo+corpo) + 2 `askyesno` di sovrascrittura
(file estraneo / segnale attivo — titolo+corpo, con `{path}` reso via `.format`, ex `%s`) +
`showinfo` «Audit modalità reale» (titolo+corpo). Catalogo `i18n.py`: **13 chiavi NUOVE × EN/ES**.
Tutte tr-constant di `app.py` → l'anti-drift le trova via `_APP_TR` (nessuna nuova sorgente).

**Esclusioni (restano IT).** Il dialog **«XTrader Bridge è già in esecuzione»** all'avvio: renderizza
**prima** di `i18n.set_language` (l'acquisizione del lock di istanza in `__init__` precede la scelta
lingua) → localizzarlo non avrebbe effetto; escluso e verificato dal test. `{path}` = percorso file
(valore di dominio). **Nessun cambio di logica**: selezione file, pattern `*.csv`, operazioni CSV e
guardie autoritative (`_create_and_save_csv`) invariati — solo il testo dei dialog è tradotto.

**Test hard.** Nuovo `tests/unit/test_file_action_dialogs_i18n_343.py`: AST (13 stringhe wrappate,
nessuna vecchia forma hardcoded/`%s` superstite), **mutation-guard `.format(path=...)`** sui 2 corpi
con `{path}`, copertura EN/ES **!= IT** + placeholder, round-trip reale, e il test che verifica
l'**esclusione** del dialog «già in esecuzione» (resta IT, non a catalogo). Anti-drift `test_i18n_343.py`
verde senza modifiche (tutte le chiavi in `_APP_TR`). Suite unit+integration: **2533 passed, 11 skipped**.
Docs: README + `design_handoff.md` (nota «Crea CSV» attualizzata da «resta IT» → «localizzato 4z»).
Design handoff = **PASS**.

**Ancora aperto (per chiudere #3):** i restanti log `self._log(...)` di `app.py` (in gran parte
esclusioni permanenti) + la nota SUCCESS del selettore lingua da attualizzare + i dialoghi/avvisi GUI
eventualmente residui.

## #343 slice 4aa — log SUCCESS del selettore lingua localizzato + nota attualizzata (residuo UI #3)

**Obiettivo.** Localizzare l'ultimo messaggio UI rimasto rimandato: il **log di successo del
cambio-lingua** (`App._language_chosen`, ramo `ok`), che la slice 4p aveva esplicitamente **rimandato**
(f-string IT non wrappata) perché aveva una sotto-stringa computata **e** una nota da attualizzare.

**Cosa fa.** Passa da `i18n.tr(...)` il template esterno + le **due varianti** della sotto-frase
`{extra}`: «CSV personalizzata preservata {kept}» / «CSV allineata». La variante «CSV preservata»
risolve `{kept}` col proprio `.format` **prima** di essere interpolata nel template esterno
(`.format(lang=…, extra=…)`) → nessuna graffa residua nel doppio format. Catalogo `i18n.py`: **3 chiavi
NUOVE × EN/ES**; tutte tr-constant di `app.py` → anti-drift via `_APP_TR`. **Nota attualizzata:** la
vecchia coda «(#343: finestra principale; le altre finestre arrivano con i prossimi slice)» era
**stantia** (dalle slice 4x/4y/4z tutte le finestre/dialoghi sono localizzati) → sostituita con
«riavvia il bridge per applicare la lingua all'**intera interfaccia**». Il log di **fallimento** era
già a catalogo (4p, invariato). `{lang}`/`{kept}` sono valori interpolati (codice lingua / lingua CSV).

**Test hard.** Nuovo `tests/unit/test_language_selector_success_i18n_343.py`: AST (3 stringhe wrappate),
**guardia anti-nota-stantia** (le frasi «le altre finestre arrivano»/«con i prossimi slice» NON devono
sopravvivere), mutation-guard `.format` (template esterno `lang`+`extra`; variante `kept`), copertura
EN/ES **!= IT** + placeholder, round-trip del messaggio COMPLETO per entrambe le varianti. Aggiornato il
test 4p `test_app_wizard_profile_i18n_343.py::test_esclusioni_defer_e_dominio` (l'asserzione «SUCCESS
lingua rimandato → f-string» diventa «ora wrappato in i18n.tr», come previsto dalla 4p). Suite
unit+integration: **2538 passed, 11 skipped**. Docs: README + `design_handoff.md` (§lingua §6.2-bis).
Design handoff = **PASS**.

**Stato #3.** Con la 4aa **tutta la UI localizzabile è coperta**: finestra principale, finestre/pannelli
secondari, wizard, hub Strumenti, banner, dialoghi di conferma modalità, dialoghi GUI di azione file,
e ora l'ultimo log di feedback UI. Ciò che resta IT è **per contratto** (dominio puro:
`save_status_message`, errori/warning di validazione/store `{err}`/`{warn}`/`{exc}`, parola-quando dei
recovery, log `_dbg`, e il dialog «già in esecuzione» pre-`set_language`). La **chiusura dell'epica #3**
resta una decisione del proprietario (merge sempre manuale).
