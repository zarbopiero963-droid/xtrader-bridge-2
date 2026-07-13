# Piano di chiusura definitiva — Issue #4, #5, #8, #13, #14, #15, #19

> Audit read-only eseguito il 2026-07-13 sul commit `f1748f9` (head di `main`).
> Evidenza test: `python -m pytest -q` → **2434 passed, 11 skipped** (~24 s) + `python -m py_compile main.py` PASS.
> Le 7 issue sono copie da `xtrader-bridge` (repo 1): gran parte del lavoro richiesto è **già presente
> in questo repo** (xtrader-bridge-2), che è nato come copia consolidata. Questo documento mappa,
> issue per issue, cosa è già fatto (con evidenza file:riga e test), cosa resta come lavoro codice
> (piano PR), cosa dipende solo dal proprietario.

Regole invariate: una sola PR aperta alla volta · merge SEMPRE manuale del proprietario ·
ogni PR con Phase 0 → patch stretta → micro-audit → test hard veritieri → check verdi →
label finali → verdetto.

---

## Sintesi esecutiva

| Issue | Stato reale nel codice | Come si chiude |
|---|---|---|
| **#8** Multi-riga (MultiMarket/MultiSelection) | ✅ **Tutto implementato e testato** | Commento di evidenza + chiusura (nessuna PR) |
| **#14** Sweep thread non risolti (86 PR vecchio repo) | ✅ Tutti i finding di sezione A risolti qui | Commento di evidenza + chiusura (nessuna PR) |
| **#5** Roadmap #376 (sicurezza #318 + coda 3.5 + collaudo Betfair) | ✅ Codice tutto fatto; sync Betfair rimosso | Chiusura, residui owner → nuova roadmap |
| **#13** Backlog ~24 PR (Fase 5 UI + Fase 6 Nuitka) | ✅ Fase 5 completa; Nuitka in anteprima | Chiusura, residuo Nuitka → nuova roadmap |
| **#15** Migliorie finali (#311) | ✅ Fasi 1 e 3 complete; Fase 0/2 = dati owner | Chiusura, residui owner → nuova roadmap |
| **#19** «Guarda» (stato roadmap) | Nota/domanda, non task | Creare **nuova issue roadmap pulita**, chiudere #19 |
| **#4** Football Americano + dizionario Rugby | ❌ **Unico vero lavoro codice residuo** | **PR-1** (+ eventuale PR-2 con dati owner) |

**Lavoro codice effettivo rimasto: solo issue #4.** Tutto il resto si chiude con evidenza
documentale + una nuova issue roadmap che raccolga i residui che dipendono dal proprietario.

---

## Issue #8 — «CSV multiriga più mercati e selezioni» → CHIUDIBILE SUBITO

Implementazione completa presente e coperta da test hard:

- Modello: `CustomParserDef.multi_market_enabled / multi_selection_enabled / multi_markets /
  multi_selections` (`xtrader_bridge/custom_parser.py:264-267`), round-trip config e
  retrocompatibilità (`:287-290`, `:404-407`).
- Pipeline a lista di righe: `custom_pipeline.build_validated_rows() -> list[PipelineResult]`
  (`custom_pipeline.py:568`), runtime `result.rows` / `all_rows()` (`write_path.py`,
  `app.py:2855-2863`).
- GUI: checkbox MultiMarket/MultiSelection + sezioni con «＋»/rimuovi
  (`custom_parser_gui.py:727-817`); preview «Prova messaggio» tabellare multi-riga
  (`custom_parser_gui.py:1403-1492`).
- Dedupe **per-riga**: `signal_dedupe.row_dedup_key` su
  `Provider,EventName,MarketType,SelectionName,BetType,Handicap` (`signal_dedupe.py:83-86`),
  applicata riga per riga in `write_path.py:257-289`.
- CSV multi-riga con header/ordine colonne invariati; entrambe le modalità coda
  (`APPEND_ACTIVE`, `QUEUE_UNTIL_CONFIRMED`) e `OVERWRITE_LAST` documentato
  (blocco intero mai spezzato, `docs/xtrader_csv_contract.md`).
- Test: `tests/unit/test_multirow_192.py` (MultiMarket 2 righe, MultiSelection 3 righe,
  dedupe per-riga, CSV multi-riga, preview N righe, both-active senza prodotto cartesiano,
  backward compatibility), `tests/unit/test_parser_builder_multirow.py`.

**Azione**: chiudere con commento di evidenza (elenco sopra). Nessuna PR.

## Issue #14 — Sweep thread non risolti → CHIUDIBILE SUBITO

Tutti i finding «sezione A» (gli unici azionabili) risultano risolti in questo repo:

| Finding (vecchio repo) | Stato qui | Evidenza |
|---|---|---|
| #249 P1 — ID fissi su percorso mapping senza match | ✅ | gate `matches_message` fisso-completo (`custom_parser_engine.py:273-282`), sottrazione MarketId/SelectionId con mapping attivo (`:280-281`), azzeramento ID stantii (`custom_pipeline.py:348,379,519`); test `test_custom_parser_engine.py:257,275` |
| #249 P2 — gate fixed-complete vs righe multi | ✅ | `_resolve_ids_into` + `_validated_multi_row` (`custom_pipeline.py:147-159,513-540`); test `test_multirow_192.py:592` |
| #203 P1 — token URL-encoded nei log | ✅ | `_secret_forms` con `quote(secret, safe="")` (`event_log.py:87-100`); test `test_event_log.py:153` |
| #203 P1 — token spezzato CRLF | ✅ | `_crlf_tolerant_re` (`event_log.py:103-113`); test `test_event_log.py:172`, `test_log_privacy.py:124` |
| #203 P1 — vecchio token de-registrato mentre il poller lo usa | ✅ | de-registrazione solo a listener fermo (`app.py:513-544`) |
| #239 P1/P2 — OVERWRITE_LAST vs `max_active` | ✅ by design | blocco di UN messaggio mai spezzato (decisione proprietario #192); test espliciti `test_multirow_192.py:905,929` |
| #182/#179 — filtro `entity_type` nel mapping live | ✅ | `PARTICIPANT_ENTITY_TYPES` (`name_mapping_store.py:90`) usato a runtime (`custom_pipeline.py:329-333`); test `test_name_mapping.py:514-591` |
| #297 P2 — detector build EXE (`python3 -m PyInstaller`, backquote, `@()`) | ✅ | `tests/safety/test_build_exe_safety.py:529-554` |

Le sezioni B/C erano «evidence-resolve» di **thread del vecchio repo**: quei thread non esistono
in xtrader-bridge-2, quindi non c'è nulla da risolvere qui.

**Azione**: chiudere con commento di evidenza (tabella sopra). Nessuna PR.

## Issue #5 — Roadmap #376 → CHIUDIBILE (residui owner → nuova roadmap)

- Sicurezza #318: **L1-4 ReDoS** ✅ chiuso con cap input `_MAX_META_INPUT=256`
  (`parser.py:96,226`; test `tests/unit/test_security_318_l1l2.py`). **L2-2
  `_is_placeholder`** ✅ corretto `and`→`or` (`value_maps.py:47-55`; test idem).
- Collaudo Betfair Fase 1 (separatori `split_participants`): **non più applicabile** — il
  Betfair Sync/harvest è stato rimosso da questo repo (PR «remove-betfair-sync»;
  `xtrader_bridge/betfair/__init__.py` lo documenta). Il parser P.Bet gestisce comunque
  ` v `/` vs `/` - ` (`parser.py:28-29,260-264`) ed è disattivato nel live (CP-09b).
- Fase 2 viewer non-bloccante ✅ (`betfair/dictionary_viewer_gui.py:110`, ttk.Treeview
  virtualizzato + probe `view_if_free`). Fase 3 mapping guidato ad albero ✅
  (`guided_mapping_gui.py`, `betfair/guided_mapping.py`).
- Restano SOLO voci owner: 3.5-g firma EXE (serve certificato), decisioni #192/#324.

**Azione**: chiudere con commento; i residui owner entrano nella nuova roadmap (vedi #19).

## Issue #13 — Backlog ~24 PR → CHIUDIBILE (residuo Nuitka → nuova roadmap)

Fasi 1–4 erano già chiuse nel vecchio repo. **Fase 5 (UI #288/#293): tutta presente qui**:
toggle tema 🌙/☀️ (`app.py:894`), placeholder/testi guida (`custom_parser_gui.py`),
riordino in 4 gruppi ①–④ (`tools_gui.py:25`), colonna «Come lo scrive il canale»
(`name_mapping_gui.py:45`; test `test_channel_alias_rename.py`), «🔗 Traduzioni attive per
questo parser» (`custom_parser_gui.py:588`), schermata Riepilogo (`config_summary_gui.py`).
MultiMarket/MultiSelection preservati (test multirow verdi).

**Fase 6 (Nuitka)**: `build-nuitka.yaml` esiste come build **anteprima additiva**;
l'adozione come build ufficiale richiede la **validazione manuale dell'EXE su Windows
reale** (solo owner). PyInstaller resta la release (`build.yaml`).

**Azione**: chiudere con commento di evidenza; «adozione Nuitka + smoke EXE» → nuova roadmap.

## Issue #15 — Migliorie finali (#311) → CHIUDIBILE (residui = solo dati/azioni owner)

Già implementato e testato in questo repo:

- **Fase 1 completa**: 1.1 single-instance lock (mutex Windows + flock POSIX,
  `instance_lock.py`, acquisito in `app.py:221` prima della GUI; test
  `tests/safety/test_instance_lock_311.py`) · 1.2 `drop_pending_updates` solo alla prima
  connessione confermata (`app.py:2510,2637-2649`) · 1.3 START bloccato senza parser attivo
  (`app.py:2216-2221`).
- **Fase 3 completa**: 3.1 tri-stato SIMULAZIONE/COLLAUDO/REALE (`bridge_mode.py`) ·
  3.2 parser tester batch su messaggi reali (`parser_builder.py` BatchMessageReport +
  GUI; test `test_parser_tester_311.py`) · 3.3 health check a 7 semafori
  (`health_check.py`) · 3.4 wizard prima configurazione 5 step (`wizard.py`/`wizard_gui.py`).
- **3.5 minori quasi tutti**: daily-limit su ora locale (`safety_guard.py:77-89`) · DPI
  awareness (`app.py:228`) · pytest-timeout (`pytest.ini`) · ruff+mypy in CI
  (`pr-checks.yml`, job lint) · archiviazione docs (`docs/audit/archive/`).
- §2.3: variante più sicura del richiesto — default `recognition_mode="NAME_ONLY"`
  (`config_store.py:144`) + gate fail-closed `dizionario.is_validated()` (whitelist
  `Fonte="export xtrader"`, `dizionario.py:74-77`) che tiene chiusi i percorsi a ID finché
  il dizionario non è confermato da export reale.

Restano SOLO attività del proprietario (non chiudibili da agente, nessuna PR possibile ora):

1. **P0 + Fase 0 (T1–T20)**: collaudo end-to-end su PC Windows reale con XTrader in
   simulazione (riferimento `docs/audit/xtrader_simulation_test.md`).
2. **2.1**: raccogliere 10–20 **notifiche di conferma XTrader reali** (T18) → poi PR fixture
   + eventuale adeguamento `confirmation_reader.py`.
3. **2.2**: **export reale del dizionario XTrader** (T19) → poi PR di validazione delle 39
   righe «Generato da schema» (oggi 42/81 «Export XTrader», 39 «Da verificare»).
4. **Firma EXE** (certificato da acquistare).

**Azione**: chiudere rimappando 1–4 nella nuova roadmap, oppure tenerla aperta come tracker
del collaudo — decisione owner (default consigliato: chiudere, la nuova roadmap è più pulita).

## Issue #19 — «Guarda» → si chiude creando la NUOVA ROADMAP

La domanda finale dell'issue («apro una issue aggiornata che rimpiazzi #376?») è esattamente
la chiusura giusta anche per #5/#13/#15. La nuova issue «📋 Roadmap residua» deve contenere:

- **Codice**: issue #4 (sport + dizionario, vedi PR-1/PR-2 sotto) · fixture conferme XTrader
  (dopo T18) · validazione dizionario (dopo T19) · eventuali Fase 4 GUI future (mercati
  guidati avanzati, guida primo avvio HTML/in-app, wizard «insegna col dito») **se** l'owner
  le conferma ancora volute.
- **Owner**: P0 fattibilità bot sul canale · collaudo Fase 0 T1–T20 · smoke EXE +
  validazione Nuitka · firma EXE (certificato) · decisioni #192/#324 (vecchio repo).

**Azione**: aprire la nuova issue, chiudere #19 (e #5/#13/#15) puntando ad essa.

---

## Piano PR (una alla volta, in ordine)

> ⛔ Prerequisito: la PR **#33** (i18n slice 4k) è aperta → nessuna nuova PR finché non è
> mergiata (regola «una sola PR aperta alla volta»).

### PR-1 — Issue #4a: sport «Football Americano» (piccola)
- `xtrader_bridge/sports.py`: aggiungere `"Football Americano": 6423` a `SPORTS_EVENT_TYPE`
  (**verificare 6423 contro la documentazione Betfair prima del merge**; con il Sync rimosso
  l'ID serve solo a scoping del dizionario locale/resolver, ma resta safety-critical).
- Verifica anti-drift multi-modulo: dropdown parser/mapping (`custom_parser_gui`,
  `name_mapping_gui`, `known_teams_gui`, `guided_mapping_gui`) derivano già da `sports.py`
  → test di coerenza che lo dimostri.
- Test hard: nuovo sport presente in tutti i consumer; `SPORT_UNSPECIFIED` invariato;
  nessuna riga piazzabile con mapping mancante (fail-closed invariato).
- Docs: README (sport supportati) + `docs/audit/roadmap.md`; design handoff solo se cambia
  una label visibile nei dropdown (probabile PASS con una riga).
- PR body: segnalare «CORE CHANGE» come chiesto dall'issue.

### PR-2 — Issue #4b: voci dizionario Rugby Union (+ Football Americano) (piccola)
- `data/dizionario_xtrader.csv`: voci market-terms/nomi per Rugby Union e Football Americano
  con `Fonte`/`Stato` **onesti** (senza export reale: `Generato da schema` / «Da verificare»,
  ID vuoti — come previsto dall'issue e da `docs/audit/mercati_mapping_design.md`).
- Il gate `is_validated()` resta fail-closed (già oggi False): nessun percorso a ID si apre.
- Test hard: parse del CSV con i nuovi sport; resolver fail-closed su voci non verificate;
  header/colonne invariati.
- **Alternativa consigliata all'owner**: se l'export XTrader reale (T19) arriva prima,
  accorpare PR-2 con la validazione 2.2 e inserire solo voci verificate.

### PR-3 (condizionata a T18) — fixture conferme XTrader reali
Aggiungere le notifiche reali anonimizzate in `tests/fixtures/`, adeguare
`confirmation_reader.py` se il formato osservato lo richiede (fail-safe invariato:
messaggio non riconosciuto non rimuove nulla), documentare il formato in `docs/`.

### PR-4 (condizionata a T19) — dizionario validato da export reale
Promuovere le righe confermate a `Fonte="Export XTrader"`, correggere/rimuovere le smentite,
sbloccando così `is_validated()` e i percorsi a ID (`BOTH`/`ID_ONLY`) in sicurezza.

### Chiusure senza PR (subito, in quest'ordine)
1. Nuova issue «📋 Roadmap residua» (contenuto in §Issue #19).
2. Chiusura #8 e #14 con commento di evidenza.
3. Chiusura #5, #13, #15 con commento di evidenza + link alla nuova roadmap.
4. Chiusura #19 con link alla nuova roadmap.
5. Chiusura #4 **solo dopo** il merge di PR-1 e PR-2 (o della variante PR-2+T19).
