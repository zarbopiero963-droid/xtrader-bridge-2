# Roadmap tecnica — XTrader Signal Bridge

> Documento master. Trasforma i problemi di `known_issues.md` in una sequenza di
> PR piccole, testabili e sicure. Ogni PR ha: obiettivo, task, **test hard**,
> **micro-audit**, **audit di controllo totale**.

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
| `pr-checks.yml` | PR · push main · manuale | job separati: `compile`, `contract`, `unit`, `safety`, `integration`, `smoke` |
| `merge-simulation.yml` | PR · manuale | fonde `main` nel branch PR (no merge reale) → `compileall` + `pytest`; rileva conflitti |
| `merge-simulation-hard.yml` | manuale · schedulata (notte) | Windows: merge + suite completa + `safety`/`integration` + build EXE + controllo file vietati |
| `forbidden-files.yml` | PR · push main · manuale | blocca `.env`/`config.json`/`*.exe`/`*.zip`/`*.log` e CSV (eccetto `data/dizionario_xtrader.csv`) |
| `build.yaml` | push main · tag `v*` · manuale | build EXE Windows + artifact; release solo su tag |

Il check `contract` (`tests/unit/test_csv_contract.py`) è la barriera che diventa
rossa se cambiano: header/ordine/numero colonne, encoding `utf-8-sig`, `QUOTE_ALL`,
`BetType` (PUNTA/BANCA), `Points` vuoto, `Handicap` 0, o se rientrano `Stake`/`Timestamp`.

> **Branch protection (consigliata, da impostare lato GitHub dal proprietario):**
> rendere *required* almeno `compile`, `contract`, `unit`, `safety`, `integration`,
> `merge-simulation`, `forbidden-files`, `commit-gate`. `merge-simulation-hard`
> resta manuale/notturna.

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
| pr | ogni PR | `pytest -m "not manual"` (tutta la suite offline, esclusi i live/manuali) + merge-simulation |
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

- `Stake` e `Timestamp` **non** sono colonne CSV (vedi `known_issues.md`).
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
**Tecnico:** `docs/audit/current_state.md`, `docs/audit/known_issues.md`,
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
**Tecnico:** `docs/audit/final_audit.md`, `docs/audit/release_checklist.md`,
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
successo). Docs ammorbidite («ITA richiedeva la virgola; update decimali-intelligenti
accetta entrambi», risposta supporto #343). Test: 7 unit puri + coercion + 6 glue,
mutazioni O–U KILLED.
