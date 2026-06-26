# BLOCCO 1 — USO PERSONALE — Roadmap (issue #86)

Questo documento mappa il piano di **issue #86** ("blocco 1 personale") nelle 13 PR
personali (PR-P1 → PR-P13). Ogni PR è **separata**, mirata e mergiata **manualmente**
dal proprietario; appena una PR viene mergiata si passa alla successiva.

## Obiettivo

Bridge per **uso personale**: Telegram → Parser → CSV/XTrader, con parser e name
mapping multi-sport e un sottosistema **Betfair Sync solo locale e read-only**.

## Regole assolute (valgono per TUTTE le PR del blocco)

- Betfair resta **100% locale**. Nessun dato Betfair esce dal PC/VPS.
- **Niente** Supabase, license key, Admin EXE, piani, pagamenti, dashboard clienti,
  cloud sync, backup/import/export Betfair.
- Il modulo Betfair è **solo read-only**. Operazioni **vietate**: `placeOrders`,
  `cancelOrders`, `replaceOrders`, `updateOrders` (vedi `xtrader_bridge/betfair/safety.py`).
- `sessionToken` **solo in RAM**, mai su disco. Mai loggare App Key, username,
  password, sessionToken, certificato, private key, headers, payload/response login.
- Nessun certificato incluso nel build.
- Il merge resta **sempre manuale** del proprietario.

## Scelta di struttura

Il repository usa un **package flat** `xtrader_bridge/` (60+ moduli) invece delle
cartelle top-level letterali del testo issue (`bridge_app/`, `betfair_sync/`,
`parser/`, `name_mapping/`, `xtrader_csv/`). Per coerenza con la convenzione
esistente, i nuovi moduli Betfair vivono nel **subpackage** `xtrader_bridge/betfair/`,
e parser / name mapping / CSV riusano i moduli già presenti
(`parser*.py`, `name_mapping_store.py`, `csv_writer.py`). Le regole di branch
richieste dall'issue sono già codificate in `AGENTS.md` / `CLAUDE.md` (mai su `main`,
crea branch se su `main`, continua se su branch non-main, una sola PR per scope) e
non vengono duplicate.

## Mappa PR

| PR     | Obiettivo                                   | Aree principali                                                        | Stato |
|--------|---------------------------------------------|-----------------------------------------------------------------------|-------|
| PR-P1  | Repository Foundation solo Bridge           | `betfair/` skeleton, guard read-only, hygiene test, questa roadmap     | merged (#165) |
| PR-P2  | Safe Logging + Secure Local Storage         | storage cifrato credenziali, sessionToken RAM-only, redaction filter   | merged (#166) |
| PR-P3  | Tab Betfair Sync locale (GUI)               | tab GUI credenziali/sport/giorni/stato, pulsanti                       | merged (#167) |
| PR-P4  | Betfair Auth Client Italia                  | login/logout cert + Delayed App Key, token in RAM                      | merged (#168) |
| PR-P5  | Database Locale Betfair Multi-sport         | tabelle locali sport/comp/event/market/selection/sync/mapping         | merged (#169) |
| PR-P6  | Betfair Navigation + Catalogue Sync         | navigation menu + listMarketCatalogue, upsert read-only               | in corso |
| PR-P7  | Sync Engine Manuale                         | motore unico sync manuale + riepilogo safe                            | TODO  |
| PR-P8  | Betfair Auto Sync Scheduler locale          | scheduler locale auto login→sync→auto logout                          | TODO  |
| PR-P9  | Parser Personalizzato Multi-sport / profilo | sport nel parser, campi core generici                                 | TODO  |
| PR-P10 | Name Mapping Multi-sport Locale             | tab mapping per sport/profilo, locale                                 | TODO  |
| PR-P11 | Dictionary Viewer Locale                    | viewer sola-lettura del dizionario Betfair                           | TODO  |
| PR-P12 | Telegram → Parser → Mapping → CSV XTrader   | integrazione flusso con fallback nomi                                 | TODO  |
| PR-P13 | Build EXE Personale                         | solo `XTraderBridge.exe`, nessun segreto/cert incluso                 | TODO  |

## Moduli implementati

### PR-P1 — `xtrader_bridge/betfair/`
- `safety.py`: guard read-only (`FORBIDDEN_BETTING_OPS`, `assert_read_only`,
  `is_forbidden_betting_op`, `ReadOnlyViolation`). Unico punto autorizzato a nominare
  le operazioni di scommessa vietate.

### PR-P2 — Safe Logging + Secure Local Storage
- `log_safety.py`: redazione dei log Betfair. `redact()` maschera header sensibili
  (`X-Authentication`, `X-Application`), `sessionToken`/`session_token` e qualsiasi
  segreto registrato via `register_secret()`/`unregister_secret()`.
  `SecretRedactionFilter` (logging.Filter) applica la redazione a ogni record;
  `quiet_http_libraries()` alza a WARNING i logger `requests`/`urllib3` (che a DEBUG
  riversano header/payload); `install_global_log_redaction()` installa il tutto.
- `session.py`: `BetfairSession` custodisce il `sessionToken` **solo in RAM** (mai su
  disco), non lo espone in `repr`/`str`, e lo registra/de-registra dai log a
  `set_token`/`clear`.
- `credential_store.py`: storage locale sicuro delle credenziali Betfair (Delayed App
  Key, username, password, percorsi cert/key) nel **keyring di sistema** (stesso
  pattern fail-safe di `token_store`). `masked()` mostra i segreti come `••••••` alla
  riapertura; i percorsi file restano in chiaro. Il `sessionToken` non è mai salvato.

### PR-P3 — Tab Betfair Sync locale (GUI)
- `sync_tab_controller.py`: logica pura della tab (testata in CI). `SPORTS`
  (Calcio/Tennis/Basket/Rugby Union), `normalize_days_ahead`/`normalize_sport`,
  `BetfairSyncController` con `button_states()` (login solo con credenziali complete;
  «Sincronizza» solo dopo login e senza sync in corso; logout/cancella governati
  dallo stato), `save/delete_credentials`, `logout` che **cancella solo la sessione**
  (non le credenziali), `load_masked`.
- `sync_tab_gui.py`: widget customtkinter `BetfairSyncPanel` (campi credenziali,
  sport, giorni avanti, stato login/ultima sync/stato sync, pulsanti). **Non testato
  in CI** (richiede display): la logica è nel controller; widget = verifica manuale.
  La tab è **registrata nella finestra «🧰 Strumenti»** (`App._open_tools`, scheda
  «🔵 Betfair Sync») con una `BetfairSession` unica per processo (token in RAM
  persistente tra aperture). I campi segreti mostrano `••••••` come sentinella: al
  Salva/Accedi il controller li **risolve** ai valori reali salvati
  (`resolve_credentials`), così un segreto non ridigitato non sovrascrive il keyring.
  Salva/Cancella **segnalano i fallimenti** del keyring senza ricaricare il form
  (un errore non sembra un successo).

#### Smoke test manuale PR-P3 (Windows, da eseguire dal proprietario)
1. Apri il bridge, vai alla tab «Betfair Sync». Atteso: campi vuoti, solo «Salva
   credenziali» attivo; «Accedi»/«Sincronizza»/«Logout»/«Cancella» disabilitati.
2. Inserisci App Key, username, password, percorsi cert/key → «Accedi» si abilita.
3. Premi «Salva credenziali», chiudi e riapri il bridge → i campi segreti appaiono
   mascherati (`••••••`), i percorsi file in chiaro.
4. (Dopo PR-P4) login → «Sincronizza ora» e «Logout» si abilitano.
5. «Logout» → torna «non connesso», ma le credenziali restano salvate.
6. «Cancella credenziali salvate» → campi vuoti, login disabilitato.
Risultato atteso: nessun token nei log, nessuna chiamata betting, nessun dato fuori dal PC.

### PR-P4 — Betfair Auth Client Italia
- `auth_client.py`: `BetfairAuthClient` esegue il login **non-interattivo** Betfair.it
  con certificato (`identitysso-cert.betfair.it/api/certlogin`) e Delayed App Key.
  Il `sessionToken` va **solo in RAM** (`BetfairSession`), mai su disco; `logout()`
  lo cancella. Errori **safe**: `LoginError`/`CertificateError` senza response grezza
  né segreti nel messaggio. Il login passa dal guard `safety.assert_read_only` (non è
  un'operazione di scommessa). La chiamata HTTP reale usa solo la **stdlib**
  (`urllib` + `ssl.load_cert_chain`, nessuna nuova dipendenza) ed è **iniettabile**
  (`transport=`) così i test girano offline. La tab «🔵 Betfair Sync» è agganciata
  al client (pulsante «Accedi» → `App._open_tools` → `BetfairAuthClient.login`).

#### Smoke test manuale PR-P4 (Windows, certificato vero)
1. Configura/salva credenziali Betfair (App Key delayed, username, password,
   cert .crt/.pem, key .key) nella tab Betfair Sync, poi «Accedi».
2. Atteso con credenziali valide: log "🔵 Login Betfair riuscito"; «Sincronizza»/
   «Logout» si abilitano. Con credenziali errate: log "❌ Login Betfair fallito: <status>".
3. «Logout» → stato "non connesso"; nessun token su disco, nessun token nei log.
Non verificato in automatico: la chiamata di rete reale e il certificato vero.

### PR-P5 — Database Locale Betfair Multi-sport
- `local_db.py`: `BetfairLocalDB` su **SQLite stdlib** (nessuna nuova dipendenza),
  path in AppData (`runtime_state.betfair_db_path`). Tabelle: `betfair_sports`,
  `betfair_competitions`, `betfair_events`, `betfair_markets`, `betfair_selections`,
  `betfair_local_name_mappings`, `betfair_sync_runs`. Chiavi corrette: sport=
  `event_type_id`, competizione=`competition_id`, evento=`event_id`, mercato=
  `market_id`, selezione=(`market_id`,`selection_id`,`handicap`), mapping=
  (`sport`,`normalized_name`). Gli `upsert_*` non duplicano (ON CONFLICT sulla chiave
  naturale, `active=1` + `last_seen_at`); `deactivate_unseen(table, seen_at, scope_value=)`
  marca `active=0` i record non rivisti nella sync (scope per sport/evento/mercato così
  sincronizzare un solo sport non disattiva gli altri). Solo locale: nessun cloud,
  nessun export/import; il file `.db` è in `.gitignore`.

### PR-P6 — Betfair Navigation + Catalogue Sync
- `catalogue_client.py`: scarica il navigation menu Betfair (read-only) filtrando gli
  sport del blocco (`SPORTS_EVENT_TYPE`: Calcio=1, Tennis=2, Basket=7522, Rugby Union=5),
  poi arricchisce con `listMarketCatalogue`. `parse_navigation` (cammino ricorsivo
  EVENT_TYPE→COMPETITION?→EVENT→MARKET, salta i sport non scelti), `parse_market_catalogue`
  (MarketId/SelectionId/runner/handicap/market type/event), `split_participants`
  («Home v Away»). `CatalogueSync.sync(sports)` upserta sport/competizioni/eventi
  (con participant_1/2)/mercati/selezioni nel `BetfairLocalDB` con un `new_sync_marker`
  unico, poi `deactivate_unseen` scoped per sport (e per mercato sulle selezioni):
  rieseguire non duplica e i record spariti diventano inattivi senza toccare gli altri
  sport. Ogni operazione passa dal guard `safety.assert_read_only` (nessuna scommessa);
  Delayed Key; transport HTTP iniettabili (test offline), default stdlib `urllib`.
- `local_db.py`: eventi estesi con `participant_1`/`participant_2` (+ migrazione
  idempotente `ALTER TABLE`); markets scopabili per `event_type_id`.

#### Smoke test manuale PR-P6 (Windows, login reale)
1. Dopo login (PR-P4), esegui un sync degli sport scelti. Atteso: il dizionario locale
   si popola di sport/competizioni/eventi/mercati/selezioni; nessuna chiamata betting.
2. Riesegui il sync: i conteggi restano stabili (nessun duplicato).
Non verificato in automatico: la chiamata di rete reale a navigation/catalogue.

## Definition of Done (blocco personale)

Il blocco è completo quando esiste `XTraderBridge.exe` personale; non esistono Admin
EXE/Supabase/licenza/pagamento; Betfair Sync usa la Delayed Key ed è read-only; le
credenziali Betfair sono locali e cifrate; il sessionToken resta in RAM; il dizionario
è locale; sono supportati Calcio/Tennis/Basket/Rugby Union; vengono salvati
MarketId/SelectionId correnti; l'Auto Sync fa auto login → sync → auto logout; il
parser e il name mapping sono multi-sport; Telegram → Parser → Mapping → CSV funziona;
nessun dato Betfair esce dal PC; nessun backup/import/export Betfair; nessun segreto
finisce nei log.
