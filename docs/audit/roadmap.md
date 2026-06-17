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

## CP-09..CP-10 (pianificate, da affinare con il proprietario)
- **CP-09** — il Parser Personalizzato diventa il percorso principale; hardcoded
  come fallback.
- **CP-10** — `CUSTOM_PARSER_READY`: audit completo, test hard, documentazione.

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
