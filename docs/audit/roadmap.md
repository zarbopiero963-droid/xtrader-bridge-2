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
