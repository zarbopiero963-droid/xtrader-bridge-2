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
| PR-P6  | Betfair Navigation + Catalogue Sync         | navigation menu + listMarketCatalogue, upsert read-only               | merged (#170) |
| PR-P7  | Sync Engine Manuale                         | motore unico sync manuale + riepilogo safe                            | merged (#171) |
| PR-P8  | Betfair Auto Sync Scheduler locale          | scheduler locale auto login→sync→auto logout                          | merged (#172) |
| PR-P9  | Parser Personalizzato Multi-sport / profilo | sport nel parser, fonte unica sport, campi core generici             | merged (#173) |
| PR-P10 | Name Mapping Multi-sport Locale             | sport per riga di mappatura, scoping in resolve_team                  | merged (#174) |
| PR-P11 | Dictionary Viewer Locale                    | viewer sola-lettura del dizionario Betfair (per livello + sport)     | merged (#175) |
| PR-P12 | Telegram → Parser → Mapping → CSV XTrader   | risoluzione ID dal dizionario + fallback nomi nel flusso live        | merged (#176) |
| PR-P13 | Build EXE Personale                         | gate di sicurezza build: solo EXE personale, nessun segreto/cert     | merged (#177) |

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

### PR-P7 — Sync Engine Manuale
- `sync_engine.py`: `SyncEngine` orchestra `CatalogueSync` aggiungendo le garanzie del
  «Sincronizza ora»: **verifica login attivo** (sessionToken in RAM), **lock non
  bloccante** che ritorna `BUSY` se una sync è già in corso (niente run sovrapposte),
  **fallimenti safe** (`SyncResult` con stato + errori senza segreti, niente crash) e
  **riepilogo safe** (sport, +eventi/+mercati/+selezioni come variazione dei record
  attivi, record disattivati). `SyncResult` con stati `OK`/`FAILED`/`BUSY`/
  `NOT_LOGGED_IN`. `CatalogueSync.sync` ora riporta anche `deactivated` nel summary.
- `catalogue_client.py`: `_resolve_transports` usa la Delayed App Key salvata se non
  passata (così l'engine si costruisce una volta e prende la chiave corrente).
- `app.py`: «Sincronizza ora» della tab Betfair è agganciato all'engine (una istanza
  per processo, con DB locale in AppData); l'esito va nel log redatto.

#### Smoke test manuale PR-P7 (Windows, login reale)
1. Dopo login, seleziona gli sport e premi «Sincronizza ora». Atteso: log con il
   riepilogo (eventi/mercati/selezioni/disattivati); nessuna chiamata betting.
2. Premi due volte «Sincronizza ora» in rapida successione: la seconda risulta
   «già in corso» (nessuna run sovrapposta). Niente duplicati nel dizionario.

### PR-P8 — Betfair Auto Sync Scheduler locale
- `auto_sync.py`: `should_run(now, ...)` (decisione **pura**: attiva + ora corrente ==
  HH + non già eseguita oggi a quell'ora + nessuna sync in corso → niente recupero
  delle sync perse; l'ora viene **normalizzata una volta** e riusata anche per la
  `run_key`, così un HH non numerico non crasha né sbaglia la dedupe-key) e
  `AutoSyncScheduler.maybe_run(now)` che esegue il ciclo **auto login → sync → auto
  logout** con dipendenze iniettate; prenota il lock del motore PRIMA del login
  (sync manuale in corso → `BUSY`, senza toccare la sessione condivisa); il **logout
  è eseguito solo se il login è riuscito** (`logged_in`), così un auto-login fallito
  non slogga una eventuale sessione manuale; non scatta due volte lo stesso
  giorno/orario (`last_run_key`, persistito); `normalize_hour` (0–23, default 23).
  Il riepilogo `on_summary` è **best-effort** (`_safe_summary`): se solleva non fa
  propagare l'errore da `_cycle`, così una run riuscita viene comunque registrata.
- `get_config()` ritorna solo config **leggera** `(enabled, hour, sports)`; le
  credenziali si leggono via `get_credentials()` **solo quando la run è dovuta**
  (dentro `_cycle`, dopo il gate), così il keyring non viene colpito a ogni tick.
- `config_store.py`: nuove chiavi `betfair_auto_sync` (default False, opt-in
  fail-closed via `as_bool_optin`), `betfair_auto_sync_hour` (default 23),
  `betfair_sync_sports`.
- `sync_tab_gui.py`: checkbox «Auto sincronizza dizionario» + orario HH + etichette
  Ultima/Prossima/Stato auto sync; le modifiche persistono in config. L'orario viene
  **riscritto normalizzato** nel campo dopo il salvataggio (ciò che si vede = ciò che
  è salvato); `refresh_autosync(..., sports=None)` rimette **tutti gli sport** (come
  `_build_ui`), così un profilo senza lista non lascia un sottoinsieme stantio.
- `app.py`: tick periodico (primo ~2s dopo l'avvio, poi ogni 60s, mentre il bridge è
  aperto) che costruisce lo scheduler una volta e chiama `maybe_run(now)` su un worker
  thread (la rete non blocca la GUI); sessione/auth/engine Betfair estratti in metodi
  condivisi lazy. I callback `on_summary`/`on_state_error` rientrano nella UI **solo se
  il bridge non si sta chiudendo** (flag `_closing`, `winfo_exists` sul main thread) e
  `_on_close` **cancella il tick pendente** (`after_cancel`), così nessun callback gira
  su una root distrutta. Il tick e `_get_config` leggono la **config LIVE in memoria**
  (`self._config`), non una rilettura da disco: dopo un save fallito lo scheduler usa ciò
  che l'utente ha impostato, non valori stantii (CodeRabbit). `is_bridge_open` è legato a
  `not self._closing` (fail-closed: un worker lanciato a ridosso della chiusura non parte).
  `maybe_run` normalizza l'ora una volta e la usa anche per la `run_key` di successo, così
  un `hour` non numerico non crasha DOPO una sync riuscita (CodeRabbit). Se la sessione
  condivisa è **già loggata** (login manuale idle), `_cycle` NON fa login/logout e riusa la
  sessione esistente: non slogga l'utente quando nessuna sync manuale è in corso (Codex).
  Cambiare/abilitare l'auto-sync fa un **kick immediato** del tick (cancellando quello
  pendente, chain unica), così abilitarla a cavallo dell'ora non perde la finestra; il
  callback parte dalla config **live** e sovrappone solo le chiavi auto-sync, senza
  riscrivere impostazioni in memoria con uno snapshot di disco stantio (Codex).

#### Smoke test manuale PR-P8 (Windows)
1. Attiva «Auto sincronizza dizionario», imposta l'orario all'ora corrente: entro un
   minuto parte auto login → sync → auto logout; il log mostra l'esito.
2. Disattiva la checkbox: non parte. Riapri il bridge dopo l'orario: non recupera.
3. Con una sync manuale in corso, l'auto-sync non parte (BUSY).
4. Login manuale attivo + auto-sync con cert mancante all'orario: l'auto-login
   fallisce ma la sessione manuale resta connessa (nessun logout indebito).
5. Digita `99` nel campo orario e applica: il campo mostra `23` (valore salvato).
6. Chiudi la finestra mentre un auto-sync è in corso: nessun errore Tcl/log su root
   distrutta (il tick è cancellato e i callback sono guardati da `_closing`).
Non verificato in automatico: il tempo reale del tick, la rete Betfair e la GUI Tk
reale (i punti 5–6 sono coperti da smoke manuale; la logica pura è in unit test).

### PR-P9 — Parser Personalizzato Multi-sport per profilo
- `sports.py` (**nuovo, fonte UNICA**): `SPORTS_EVENT_TYPE` (Calcio=1, Tennis=2,
  Basket=7522, Rugby Union=5), `SPORTS`, `SPORT_UNSPECIFIED`, `normalize_sport`
  (case-insensitive), `is_supported_sport`, `event_type_id_for_sport`. `betfair/
  catalogue_client.py` e `betfair/sync_tab_controller.py` ora **riusano** questa fonte
  (ri-export, API invariata): niente più drift della mappa sport fra i moduli.
- `custom_parser.py`: nuovo campo `CustomParserDef.sport` (uno fra `sports.SPORTS`
  oppure `""` = **non specificato/agnostico**, retro-compatibile coi parser pre-P9).
  Round-trip JSON (`to_dict`/`from_dict`/`to_json`), helper `event_type_id()`, e
  validazione: `""` ammesso, uno sport valorizzato deve essere supportato (un valore
  ignoto/manomesso è **bloccato**, non sceglie un event_type_id a caso). Lo sport NON
  cambia le colonne CSV (sempre generiche: Provider/EventId/EventName/MarketId/…); nelle
  PR successive restringerà la risoluzione ID Betfair all'`event_type_id` corretto.
- `parser_builder.py`: `sport` preservato nel round-trip (load+save/duplica non lo
  azzera), `set_sport` (canonicalizza, ignoto→agnostico), `sport_options`.
- `custom_parser_gui.py`: tendina **Sport** accanto a Modalità («(non specificato)» +
  i 4 sport); sincronizzata col builder in `_sync_to_builder`/`_reload_rows_from_builder`.
- Parser **per profilo**: invariato dall'esistente — i profili snapshottano `active_parser`
  e `parser_by_chat`, quindi cambiare profilo cambia già il parser attivo (e ora il suo sport).

#### Smoke test manuale PR-P9 (Windows / GUI)
1. Apri «🧩 Parser», scegli Sport = Tennis, salva: riaprendo/ricaricando il parser lo
   Sport resta Tennis (round-trip). Duplica: lo Sport è copiato.
2. Lascia Sport = «(non specificato)»: il parser resta agnostico (nessun blocco).
3. La logica (round-trip, validazione sport ignoto, builder, fonte unica) è coperta da
   unit test (`test_sports.py`, `test_parser_sport.py`); la sola resa dei widget Tk è
   verificata a mano.

### PR-P10 — Name Mapping Multi-sport Locale
- `name_mapping_store.py`: ogni riga di mappatura porta ora un campo **`sport`** opzionale
  (uno fra `sports.SPORTS` o `""` = agnostica). `_clean_entry` lo normalizza
  (case-insensitive; vuoto/ignoto → `""` agnostico, retro-compatibile). `resolve_team`
  e `resolve_event_name` accettano un parametro **`sport`**: con sport valorizzato
  considerano SOLO le righe di quello sport o agnostiche, con **priorità allo sport esatto**
  sulle agnostiche (helper `_iter_entries_for_sport`: prima le righe `sport==want`, poi le
  agnostiche come fallback), saltando le righe di un altro sport; sport assente/None/"" →
  nessun filtro (legacy). Così un override per-sport non viene scavalcato da una riga
  agnostica salvata prima (la GUI fa append). Fonte sport unica: `xtrader_bridge/sports.py`.
- `custom_pipeline.build_validated_row`: passa `defn.sport` a `resolve_event_name`, così
  la mappatura nomi runtime è ristretta allo sport del parser (un nome non viene tradotto
  con la voce di uno sport diverso → CSV corretto, fail-closed se non mappabile).
- `name_mapping_gui.py`: la tabella del profilo ha una colonna **Sport** per riga
  (tendina «(tutti gli sport)» + i 4 sport), letta/salvata in `_collect_rows`.
- Nessun cambio del formato di config `name_mappings` (resta `{profilo: [righe]}`): il
  campo `sport` è una chiave opzionale della riga → file pre-P10 restano validi e agnostici.

#### Smoke test manuale PR-P10 (GUI)
1. «🗺️ Mapping» → area Calcio: aggiungi una riga con Sport = Tennis, una con «(tutti gli
   sport)»; salva e riapri: lo Sport per riga è persistito.
2. La logica (normalizzazione sport, scoping resolve_team/resolve_event_name, pipeline per
   sport) è coperta da unit test (`test_name_mapping.py`); la sola resa Tk è manuale.

### PR-P11 — Dictionary Viewer Locale (sola lettura)
- `betfair/dictionary_viewer.py` (controller **puro**, sola lettura): `DictionaryViewerController`
  interroga il dizionario locale (`BetfairLocalDB`) per livello — `sports`/`competitions`/
  `events`/`markets`/`selections` — e ritorna una vista tabellare `{"columns","rows","total",
  "active"}` pronta per la GUI, con celle già formattate (`active` 0/1 → "sì"/"no"). Scoping per
  **sport** via `xtrader_bridge/sports.py` (event_type_id per sport/competizioni/eventi/mercati;
  per le selezioni, che non hanno event_type_id, via i `market_id` dello sport,
  `market_ids_for_sports`). Sport non valido/non specificato → nessun filtro. `counts(sport)`
  per il riepilogo, `view(level, sport, active_only, search=None, filters=None)` per la tabella.
  **Ricerca** (`search`, issue #178 §1): sottostringa case-insensitive sui campi testuali del
  livello — nomi partecipante/selezione/evento/mercato/competizione **e** gli ID — così copre sia
  "Ricerca partecipante/selezione" sia il filtro per ID. **Filtri drill-down** (`filters`, dict
  `{colonna: valore}` a corrispondenza esatta): competizione/evento/mercato, con chiavi non
  pertinenti al livello ignorate (fail-open). Ogni livello mostra ora la colonna **`Ultima sync`**
  (`last_seen_at`, 0/None → vuoto). `total`/`active` riflettono la query (scope+filtri+ricerca)
  prima di `active_only`. **Niente rete, niente scrittura DB, niente operazioni di scommessa**
  (solo `SELECT` via i metodi di lettura del DB).
- `betfair/dictionary_viewer_gui.py`: `DictionaryViewerPanel` (solo widget/wiring, non testato
  in CI): tendina Livello + tendina Sport + «Solo attivi» + casella **«Cerca»** (con «Pulisci»)
  + «🔄 Aggiorna»; tabella di **sole etichette** (nessuna Entry di scrittura). Un controller
  assente (DB non apribile) o un errore di lettura mostra un avviso, non crasha.
- `app.py`: nuova scheda «📖 Dizionario Betfair» nella finestra «🧰 Strumenti», che riusa il DB
  del motore Betfair (stessa istanza, sola lettura).

#### Smoke test manuale PR-P11 (GUI)
1. «📖 Dizionario Betfair»: scegli Livello = Eventi e Sport = Calcio → vedi solo gli eventi di
   calcio; «Solo attivi» nasconde i record disattivati; «Aggiorna» ricarica.
2. Digita nel campo «Cerca» un nome partecipante/selezione o un ID → la tabella si restringe alle
   righe che lo contengono; «Pulisci» azzera la ricerca. La colonna «Ultima sync» mostra il marker.
3. La logica (vista per livello, scoping per sport incl. selezioni via market_id, ricerca testuale,
   filtri drill-down, colonna last_seen_at, solo-attivi, conteggi, livello non valido) è coperta da
   unit test (`test_betfair_dictionary_viewer.py`); la sola resa Tk è manuale.

### PR-P12 — Telegram → Parser → Mapping → CSV XTrader (risoluzione ID + fallback nomi)
- `betfair/dictionary_resolver.py` (controller **puro**, sola lettura): `DictionaryResolver`
  cerca nel dizionario Betfair locale gli ID (`EventId`/`MarketId`/`SelectionId`) per la riga
  a nomi, **ristretti allo sport** del parser (event_type_id, `xtrader_bridge/sports.py`).
  `resolve_ids(sport, event_name, market_type, market_name, selection_name, handicap)` è
  **all-or-nothing e conservativo**: ritorna gli ID solo se l'intera catena evento→mercato→
  selezione è **univoca** (evento per nome o per partecipanti in qualunque ordine; mercato per
  market_type o, in mancanza, market_name; selezione per runner_name, disambiguata
  dall'handicap se omonima); qualunque assenza/ambiguità/record inattivo → `{}` (fallback nomi).
  Solo `SELECT`, nessuna rete, nessuna scrittura, nessuna operazione di scommessa.
- `custom_pipeline.build_validated_row(..., id_resolver=None)`: dopo le mappature a nomi e
  PRIMA della validazione, se è fornito un `id_resolver` e il parser ha uno sport, arricchisce
  la riga con gli ID risolti. È **additivo e fail-open**: niente match univoco o errore di
  lettura → la riga resta a nomi (fallback), il segnale NON viene bloccato.
- `signal_router.resolve_row(..., id_resolver=None)`: inoltra il risolutore al pipeline.
- `app.py`: `_betfair_id_resolver()` (best-effort) costruisce un `DictionaryResolver` sul DB
  del motore Betfair e lo passa a `resolve_row` nel flusso live (`_process`); se il dizionario
  non è disponibile → `None` → flusso a nomi (nessun blocco).
- Il flusso Telegram→parser→mapping→CSV era già cablato (PR-CP + PR-P9/P10): PR-P12 aggiunge
  SOLO l'identificazione precisa dal dizionario con fallback nomi, senza toccare il gate
  chat_id, dedup, max_signal_age, dry_run, scrittura CSV atomica o one-signal-at-a-time.

#### Test hard PR-P12
- `tests/unit/test_betfair_dictionary_resolver.py` (11): catena completa, match per nome/
  partecipanti, scoping sport, mercato/selezione per nome, ambiguità→{}, inattivi ignorati,
  handicap, sport assente/ignoto→{}.
- `tests/integration/test_dictionary_id_fallback.py` (6): pipeline arricchisce ID se trova;
  fallback nomi se non trova; resolver che solleva non blocca; parser agnostico non chiama il
  resolver; end-to-end `signal_router` con DB reale (ID riempiti) e con dizionario vuoto
  (fallback nomi, riga VALID).

#### Smoke manuale PR-P12
1. Con dizionario sincronizzato, invia un segnale il cui evento/mercato/selezione esistono:
   il CSV riporta EventId/MarketId/SelectionId valorizzati (oltre ai nomi).
2. Con evento non in dizionario: il CSV riporta solo i nomi (fallback), segnale non bloccato.
   La rete Telegram/XTrader live non è in CI.

### PR-P13 — Build EXE Personale
- La build Windows esisteva già (`.github/workflows/build.yaml`, PyInstaller `--onefile
  --windowed`, EXE singolo, bundle del solo `data/dizionario_xtrader.csv`, test prima della
  compilazione, upload artifact + release su tag). PR-P13 aggiunge il **gate di sicurezza**
  che blinda le regole non negoziabili dell'issue, verificabile in CI **senza** compilare
  (la build vera gira solo su Windows).
- `tests/safety/test_build_exe_safety.py`: **una sola** compilazione PyInstaller (nessun
  Admin/secondo EXE), nella forma canonica CLI `pyinstaller … main.py` (spec/modulo/API
  rifiutati, fail-closed); nessun `--add-data`/`--add-binary`/`--collect-*` con
  cert/chiavi/`.env`/`config.json`/DB/token (nel bundle è ammesso **solo** il dizionario
  ufficiale); i **test girano prima** della build; `data/` non contiene file sensibili;
  artifact/release pubblicano un singolo `.exe` da `dist/`. Completa i controlli già esistenti
  (`test_no_secrets_committed`, `test_secret_scan`, workflow `forbidden-files`).
- Config **locale esterna** (`config_store.config_dir()` → `%APPDATA%\XTraderBridge`), non
  inclusa nell'EXE; log safe (redaction PR-P2); `sessionToken` solo in RAM; **nessun
  certificato** incluso nel build.

#### Smoke test manuale PR-P13 (Windows — non in CI)
La compilazione e l'avvio dell'EXE NON sono eseguibili in questa CI Linux: **Build not run
in this environment.** Checklist manuale sull'EXE prodotto da `build.yaml` su Windows:
avvio senza crash; tab Betfair (login mock/reale, sync dizionario); Parser; Mapping; flusso
Telegram→CSV; Auto Sync. Verificare che l'EXE NON contenga `.env`/chiavi/certificati e che
la config sia letta da `%APPDATA%`.

## Definition of Done (blocco personale)

Il blocco è completo quando esiste l'EXE personale `XTrader-Signal-Bridge.exe` (nome
stabile prodotto da `build.yaml`; l'issue #86 lo chiama `XTraderBridge.exe` — stesso
artefatto, nome del file allineato a quello reale del workflow); non esistono Admin
EXE/Supabase/licenza/pagamento; Betfair Sync usa la Delayed Key ed è read-only; le
credenziali Betfair sono locali e cifrate; il sessionToken resta in RAM; il dizionario
è locale; sono supportati Calcio/Tennis/Basket/Rugby Union; vengono salvati
MarketId/SelectionId correnti; l'Auto Sync fa auto login → sync → auto logout; il
parser e il name mapping sono multi-sport; Telegram → Parser → Mapping → CSV funziona;
nessun dato Betfair esce dal PC; nessun backup/import/export Betfair; nessun segreto
finisce nei log.
