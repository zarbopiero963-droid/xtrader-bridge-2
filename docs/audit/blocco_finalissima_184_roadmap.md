# Audit «blocco uno finalissima» (issue #184) — Roadmap di remediation

Mappa i finding dell'**audit totale** (issue #184) nelle PR di correzione. Decisione del
proprietario: implementare **TUTTI** i finding (HIGH+MEDIUM+LOW), **una PR per finding**,
branch dedicato off `main` aggiornato, **test hard di resilienza** (fail-first), micro-audit,
**merge sempre manuale**. Il dettaglio completo di ogni finding è nel corpo della issue #184.

- Convenzione branch: `claude/issue-184-<slug>`
- Titolo PR: `fix(#184 <ID>): ...`
- Babysitter: cron di sessione (se la sessione/container si ricicla, ricreare il cron
  ripartendo da questa tabella + i titoli delle PR `#184` già mergiate).

## Stato (aggiornare a ogni merge)

| ID | Slug | File principali | Stato |
|----|------|-----------------|-------|
| H1 | h1-login-thread | `app.py`, `betfair/sync_tab_gui.py` | merged (#187) |
| H2 | h2-fsync-dir | `atomic_io.py` | merged (#188) |
| H3 | h3-clear-toctou | `csv_writer.py` | merged (#189) |
| H4 | h4-dedupe-finite | `signal_dedupe.py` | merged (#190) |
| H5 | h5-stop-futures | `app.py` | merged (#191) |
| M1 | m1-migrate-strip | `config_store.py` | merged (#196) |
| M2 | m2-chat-strip | `signal_router.py` | merged (#197) |
| M3 | m3-partial-save | `config_store.py` | merged (#198) |
| M4 | m4-day-format | `safety_guard.py` | merged (#200) |
| M5 | m5-retry-errno | `csv_writer.py` | merged (#201) |
| M6 | m6-journal-atomic | `event_journal.py` | merged (#202) |
| M7 | m7-token-redact | `event_log.py` | merged (#203) |
| M8 | m8-privacy-prefix | `log_privacy.py` | merged (#204) |
| M9 | m9-market-types-get | `dizionario.py` | merged (#205) |
| M10 | m10-score-tail | `parser.py` | merged (#206) |
| M11 | m11-tls-context | `betfair/catalogue_client.py` | merged (#207) |
| M12 | m12-viewer-debounce | `betfair/dictionary_viewer_gui.py` | in PR |
| LOW | low-tracker-nonwrite | `write_path.py` (rollback guardrail su non-WRITE) | in PR |
| LOW | low-timer-lock | `app.py` (`_schedule_expiry` sotto lock) | in PR |
| LOW | low-bool-count | `safety_guard.py` (`isinstance` bool) | in PR |
| LOW | low-parser-emoji | `parser.py:215` (strip trailing emoji) | in PR |
| LOW | low-isodds-inf | `parser.py` (`_is_odds` `math.isfinite`) | in PR |
| LOW | low-pipeline-comma | `custom_pipeline.py` (replace virgola naive) | in PR |
| LOW | low-csvpath-validate | `config_store.py` (valida dir `csv_path` a START) | in PR |
| LOW | low-tmp-sweep | `atomic_io.py` (sweep `.tmp` orfani allo startup) | in PR |
| LOW | low-session-expiry | `betfair/session.py` (pulisce su errore scadenza) | in PR |
| LOW | low-autosync-release | `betfair/auto_sync.py` (`release()` in finally guardato) | in PR |
| LOW | low-localdb-timeout | `betfair/local_db.py` (`timeout=30`/PRAGMA) | da fare |
| LOW | low-syncruns-prune | `betfair/local_db.py` (prune `betfair_sync_runs`) | da fare |
| LOW | low-namemap-underfill | `name_mapping_gui.py` (under-fill posizionale) | da fare |
| LOW | low-diagnostics-ws | `diagnostics.py` (whitespace → `—`) | da fare |
| LOW | low-dedupe-skew | `signal_dedupe.py` (non pruneare entry con `t>now` + doc) | da fare |

## M1 — `_migrate` strippa i campi stringa noti (filtro chat non "sordo")

`config_store._migrate` ora toglie spazi/newline ai bordi delle chiavi stringa
dell'allowlist `_STRIP_STR_KEYS` (`chat_id`, `xtrader_notification_chat_id`, `provider`,
`recognition_mode`, `queue_mode`, `active_parser`). Un `chat_id` con whitespace (config
editata a mano / copia-incolla da Telegram) altrimenti non matcherebbe il confronto a
valle e renderebbe "sordo" il filtro single-chat (fail-closed: nessuna bet sbagliata, ma
il bridge smette di ascoltare). Esclusi di proposito: `bot_token` (segreto, gestito da
`token_store`/keyring) e `csv_path` (un path può contenere spazi; la validazione è un finding
separato). Normalizzazione di chiavi ESISTENTI: nessun cambio di contratto/colonne CSV.

## M2 — `is_chat_allowed` strip simmetrico sulla chat runtime

`signal_router.is_chat_allowed` confrontava la chat in ingresso grezza (`str(chat or "")`),
mentre `allowed_chats` strippa l'ID configurato: una chat con whitespace ai bordi non
matchava un'allow logicamente valida → segnale scartato (fail-closed, non un bypass). Ora
la chat runtime è `.strip()`-ata prima del confronto, in modo SIMMETRICO all'allowlist e
coerente con `is_notification_chat` (che già strippa entrambi i lati). Non è un over-admit:
il confronto resta esatto dopo lo strip (un id diverso resta NON ammesso) e `has_chat_filter`
è invariato. Complemento di M1 sul lato confronto in ingresso.

Lo stesso strip è applicato a `_chat_approved_for_custom` (review Codex P2): il gate live
`should_process` chiama ANCHE quell'approvazione custom, e se restasse grezza una chat con
padding sarebbe ammessa da `is_chat_allowed` ma poi scartata (IGNORE_NOT_RELEVANT), lasciando
il fix monco. Ora tutti i comparatori del chat runtime nel percorso live
(`is_chat_allowed`, `_chat_approved_for_custom`, `resolve_parser_name`, `is_notification_chat`)
normalizzano simmetricamente; fail-closed preservato e deny-list sorgenti rafforzata.

## M3 — partial-save non orfana il token keyring su config corrotto

Nel save PARZIALE (chiave `bot_token` assente) i campi del token venivano ripresi dal
`config.json` su disco; se il file era **corrotto** (`existing=None`) non venivano riportati e
la scrittura atomica cancellava `bot_token_storage` → token **orfano** nel keyring
(`load_config` non reidratava più, il bridge credeva di non avere token mentre il segreto
restava nel keyring). Fix **fail-closed** (rivisto dopo Codex P1): quando il re-read di un FILE
config esistente fallisce e il puntatore NON è già in memoria, si **aborta** il save senza
toccare disco né keyring (`ok=False`). NON si "recupera" il sentinel dal keyring: il keyring da
solo è **ambiguo** — un valore rimasto dopo un clear con `delete` fallito (sentinel `none`, ora
perso col file corrotto) verrebbe **resuscitato** come token attivo. Si re-linka SOLO con
evidenza IN MEMORIA (`bot_token_storage` nel cfg passato, es. `self._config` reidratato), che è
il ramo che preserva il sentinel dalla RAM. Così: niente orfano, niente resurrezione, e il
config corrotto resta intatto per il backup `.bak` di `load_config` + reinserimento utente.

> **Nota (Codex P2, pre-esistente, fuori dallo scope di M3):** nel flusso GUI reale
> `load_config()` fa il backup del file corrotto e ritorna `bot_token=""`; il save successivo
> prende il ramo CLEAR e **cancella** il token keyring valido. Stessa ambiguità di fondo
> (stato del token perso con la corruzione). **Decisione del proprietario: follow-up separato**
> — tracciato in **issue #199**, da affrontare in una PR dedicata con i suoi test hard (questo
> PR resta limitato al fix P1 fail-closed del ramo partial-save).

## M4 — `DailyLimiter`: `day` malformato non azzera il cap (anti-overtrading)

`restore_state` accettava qualsiasi stringa come `day`; uno stato corrotto con `day`
malformato + `count` alto faceva sì che al primo `allow` il `_roll` (vedendo `day` ≠ oggi)
**azzerasse** il conteggio → cap giornaliero pieno = **overtrading** (fail-open di un giorno).
Fix: `_roll` azzera SOLO se `_day` è una data **di calendario reale** in forma canonica
diversa da oggi (nuovo giorno reale); se è malformato/vuoto adotta il giorno corrente
**conservando** il conteggio (fail-closed). `restore_state` normalizza un `day` non valido a
`_UNKNOWN_DAY` (`""`) ma NON scarta il `count`. La validità è verificata da `_is_valid_day`
(Codex P1 / Sourcery): non basta il formato — una data **impossibile** come `2026-99-99`
supererebbe un controllo solo-regex e, differendo da oggi, farebbe azzerare il conteggio
(overtrading). `_is_valid_day` usa `time.strptime` (range mese/giorno) + confronto con la
forma canonica zero-padded di `_day_key` (`_fmt_day`, fonte unica). Il rollover quotidiano
normale (giorno valido diverso → reset) è invariato; al più si è più restrittivi oggi su uno
stato corrotto, mai più permissivi.

## M5 — `_replace_with_retry` ritenta solo gli errori transitori

`_replace_with_retry` catturava OGNI `OSError` e ritentava 10×0.1s (~1s) a prescindere dalla
causa: un errore strutturale (dir read-only/`EACCES`, `EISDIR`, `ENOENT`, cross-device)
sprecava ~1s per ogni segnale prima dell'escalation. Fix: `_is_retryable_replace_error`
distingue le contese TRANSITORIE (Windows sharing/lock violation `winerror` 32/33 **e**
ACCESS_DENIED `5` — il read-lock di XTrader surfacea tipicamente come ACCESS_DENIED, Codex
#201 P1) dagli errori STRUTTURALI, che ora si propagano subito. Su POSIX, dove il rename
atomico non ha contese di lock, l'`EACCES` resta permanente. Su POSIX/errore generico si
ritenta solo se l'`errno` non è nel denylist permanente
(`ENOENT`/`EISDIR`/`ENOTDIR`/`EXDEV`/`EROFS`/`EACCES`/`EPERM`/`ENAMETOOLONG`), così un errore
SENZA `errno` (lock simulato/edge) resta ritentabile mentre i permanenti escalano. Il budget
~1s per il vero lock di lettura di XTrader (audit C3) è invariato.

## M6 — `event_journal._append_line`: separatore + riga in una sola write

Su troncamento rilevato (ultima riga senza `\n`, es. crash a metà append) `_append_line`
scriveva il separatore `"\n"` e la riga in DUE `f.write` separati prima di `flush`/`fsync`:
un crash nel mezzo poteva lasciare solo il separatore senza l'evento (evento perso, non
corruttivo) e il docstring "atomicità della singola riga" sovrastimava la garanzia. Fix:
`prefix + line + "\n"` in UN SOLO `f.write`, che elimina la finestra a livello di PROCESSO
(o tutta la riga o niente, mai "separatore sì, evento no"). NON è atomicità a livello di disco
(un crash kernel→disco può lasciare una coda parziale, dipende da fs/hardware), ma quella è già
gestita: `read_events` salta la riga troncata e il prossimo append antepone un separatore.
Output invariato; cambia solo il numero di write (1 invece di 2 nel caso separatore).

## low-csvpath-validate — pre-flight del `csv_path` a START

A START `init_csv(csv_path)` falliva già su una **cartella mancante** (`FileNotFoundError` → avvio
annullato), ma con un messaggio generico. Aggiunto `config_store.csv_path_problem(path)` (PURO,
nessun I/O): segnala con un messaggio AZIONABILE un percorso vuoto, una cartella padre inesistente
(es. il default `C:\XTrader\` assente) o un path che è esso stesso una cartella; `""` se è
plausibilmente usabile. `_start` lo chiama PRIMA di `init_csv` e, se c'è un problema, logga
"❌ <problema> Avvio annullato." e non avvia. Gli errori di lock/permessi restano gestiti
dall'`except OSError` di `init_csv`. Test: unit puro su `csv_path_problem` (cartella mancante/vuoto/
è-cartella/ok, e non crea nulla). **Smoke test manuale** (GUI reale, non in CI): imposta un CSV path
con cartella inesistente e premi AVVIA → messaggio chiaro "La cartella del CSV non esiste: …",
nessun avvio; correggi il path → avvio regolare.

## low-pipeline-comma — separatore decimale del prezzo interpretato, non `replace` naive

`_normalize_to_contract` faceva `str(v).replace(",", ".")` sulle colonne quota: un prezzo con
separatore delle migliaia (`"1.234,56"`) diventava `"1.234.56"` (multi-dot) → il validatore lo
scartava (fail-closed, ma prezzo perso). Fix: nuovo `_decimal_sep_to_point` — se sono presenti SIA
`,` SIA `.`, l'ULTIMO è il separatore **decimale** e l'altro le **migliaia** (rimosso): `1.234,56`→
`1234.56`, `1,234.56`→`1234.56`. Con il solo `,` resta il decimale (`,`→`.`); le quote tipiche
(`1.85`, `1,85`) sono invariate → nessun rischio di reinterpretare un prezzo reale. Input non
numerico/garbage resta tale (rifiutato a valle). Test fail-first: `1.234,56` ora è VALID con
`Price=1234.56` (prima INVALID_PRICE); unit del helper sui formati comuni/europeo/US/garbage.

Refinement (Codex P1): il collasso dei separatori avviene SOLO se il raggruppamento migliaia è
VALIDO (`\d{1,3}(<sep>\d{3})+` + decimali = sole cifre). Un doppio separatore MALFORMATO (es.
`1.2,3`, gruppo non da 3 cifre) NON viene "aggiustato" a `12.3` (prezzo sbagliato ma valido nel CSV
scommessa): resta invariato → scartato (`INVALID_PRICE`, fail-closed). Docs di dominio aggiornate
(`docs/xtrader_csv_contract.md`, `docs/custom_parser.md`) come richiesto da AGENTS.md (Codex P1#2).

## low-tmp-sweep — sweep dei temporanei `.segnali_*.tmp` orfani allo startup

`atomic_write` rimuove il proprio temporaneo su qualsiasi eccezione **gestita**, ma un crash
DURO del processo (power-loss, kill) ESATTAMENTE tra `tempfile.mkstemp` e `os.replace` salta quel
cleanup: il file FINALE resta intatto (il rename non è ancora avvenuto), ma il `.segnali_*.tmp`
resta su disco e si accumula riavvio dopo riavvio. Fix: nuovo `atomic_io.sweep_orphan_temps(directory,
prefix, suffix=".tmp")` — **best-effort, non solleva mai**: rimuove SOLO i file il cui nome inizia con
`prefix` E finisce con `suffix` (il CSV reale/`config.json`, senza quel prefisso+suffisso, non sono mai
toccati); `prefix` vuoto è un no-op (mai spazzare per solo suffisso); cartella assente/non listabile →
0; una sottocartella omonima non viene rimossa; un singolo `os.remove` fallito (file in uso) viene
saltato. `csv_writer` espone `sweep_orphan_temps(path)` con la **fonte unica** del nome tmp del CSV
(`_CSV_TMP_PREFIX`/`_CSV_TMP_SUFFIX`, usata anche per scrivere, così non possono divergere). L'app la
chiama allo startup subito dopo `_clear_stale_csv("all'avvio")` (listener ancora spento → nessuna
scrittura in volo → ogni tmp combaciante è orfano), loggando solo se ne rimuove davvero. È pura igiene
del disco: il CSV finale era già intatto. Test fail-first: orfani rimossi / file non combacianti
(prefisso/suffisso diverso, CSV reale, sottocartella) intatti / no-op su prefisso vuoto e dir assente /
os.remove flaky saltato senza fermare lo sweep / orfano CSV reale rimosso senza toccare il CSV. **Smoke
manuale** (Windows reale, non in CI): killare il processo durante una scrittura CSV lascia un
`.segnali_*.tmp`; al riavvio dell'app sparisce e il CSV resta valido.

## low-autosync-release — `release()` del lock motore best-effort nel `finally`

In `AutoSyncScheduler._cycle`, il `finally` faceva `release()` del lock del motore **senza
guardia**, a differenza di `logout()` (già in `try/except`). Se `release()` sollevava (es.
un motore che rilancia, o un `RuntimeError` di stato lock), l'eccezione **propagava** dal
`finally` di `_cycle` fino al worker del tick GUI: mascherava il `SyncResult` già calcolato e
lasciava una run riuscita **NON registrata** (la stessa ora rieseguirebbe al tick/riavvio), col
rischio di lock motore bloccato (`is_syncing` permanentemente `True`). Fix: `release()` in
`try/except` best-effort come `logout()`; logout e release sono **indipendenti** (il fallimento
dell'uno non impedisce l'altro). Test fail-first: `release()` che solleva → `maybe_run` NON
propaga, ritorna il `SyncResult`, fa logout e **marca/persiste** la run; e `logout()` che solleva
non impedisce il `release`.

## low-session-expiry — pulizia della sessione Betfair sull'errore di scadenza

`BetfairSession` non aveva keep-alive né rilevamento scadenza: a token scaduto `is_logged_in`
restava `True` (GUI "connesso") ma ogni sync falliva — stato "fantasma" / UX stale. Fix in due
pezzi minimi:
- `betfair/session.py`: `SESSION_EXPIRED_ERROR_CODES` (`INVALID_SESSION_INFORMATION`,
  `INVALID_SESSION_TOKEN`, `NO_SESSION`, `SESSION_EXPIRED`) + helper puro
  `is_session_expired_error(code)` (case-insensitive, tollerante, `None`/parziale→`False`) +
  metodo `BetfairSession.clear_if_expired(code)` che slogga (RAM + de-registra dal redattore log)
  SOLO sui codici di scadenza e ritorna `True`/`False`.
- `betfair/catalogue_client.py`: nuovo `BetfairApiError(RuntimeError)` con `error_code` (il codice
  APING grezzo); `_jsonrpc_result` lo solleva al posto di `RuntimeError` puro (messaggio
  invariato, è-un `RuntimeError` → i catcher esistenti non cambiano). `CatalogueSync.sync` cattura
  `BetfairApiError`, chiama `session.clear_if_expired(ex.error_code)` e **ri-solleva**: solo i
  codici di scadenza sloggano; gli altri errori API e gli errori di rete NON toccano la sessione.

Niente bet, nessuna scrittura: il token resta solo-in-RAM, anzi viene PULITO prima. Test fail-first:
helper riconosce/ignora i codici; `clear_if_expired` slogga solo su scadenza e de-registra il
token; sync con `BetfairApiError` di scadenza → `is_logged_in=False` (e rollback, nessuna sync run);
sync con `TOO_MUCH_DATA` o `RuntimeError` di rete → sessione invariata; `_jsonrpc_result` espone
`error_code`. **Limite onesto** (non in CI): la scadenza a livello di trasporto HTTP (es. 401 sul
navigation menu GET) non è classificata qui — il segnale strutturato di Betfair per token scaduto è
l'`errorCode` APING della JSON-RPC, che è quello gestito; un 401 grezzo resta un errore generico.

## low-isodds-inf — `_is_odds` rifiuta i valori non finiti (`inf`/`nan`)

`_is_odds` faceva `float(value) > 1.0`: `float("inf") > 1.0` è `True`, quindi un valore non finito
sarebbe stato scambiato per una quota valida. Oggi è **latente** (il token quota è numerico `_NUM`,
non può essere `inf`), ma è una difesa in profondità a costo nullo. Fix: `math.isfinite(f) and f > 1.0`.
Test fail-first: `_is_odds("inf"/"-inf"/"nan"/…)` → `False`; quote reali invariate (`1.85`→True,
`1.0`/`0.5`→False).

## low-parser-emoji — rimuovi un'emoji in coda al `signal_type`

La cattura `P.Bet.\s+(.+?)(?:\s+[🔊✅🔇]|$)` esclude solo i marker noti `🔊✅🔇`; un'ALTRA emoji finale
(es. 🔥🚀⚽, o un marker senza spazio davanti) restava dentro l'alias del `signal_type`, che poi non
combaciava con la value-map → segnale **scartato** (fail-closed). Fix: dopo aver tolto i token di
stato (`_STATUS_TAIL`: LIVE/PRE), si rimuove anche una coda di emoji con `_TRAILING_EMOJI` (classe sui
blocchi emoji comuni + variation selector). Solo le emoji **finali** vengono tolte: i caratteri
interni dell'alias (lettere/cifre/`.`/`/`/spazi) restano intatti — niente over-strip. Test fail-first:
`"P.Bet. OVER 2.5 🔥"` → `OVER 2.5` (prima `OVER 2.5 🔥`), incluse combinazioni con LIVE e variation
selector; alias senza emoji invariati.

## low-bool-count — `DailyLimiter.restore_state` rifiuta un `count` booleano

`restore_state` validava il conteggio con `isinstance(count, int) and count >= 0`. Ma
`isinstance(True, int)` è `True`: un `daily_state.json` corrotto/manomesso con `"count": true`
(o `false`) sarebbe stato accettato come `1` (o `0`) invece di essere scartato come malformato.
Fix: aggiunto `and not isinstance(count, bool)` — un conteggio è un intero, non un booleano; un
bool → restore **fail-closed** (`False`, limiter invariato), come gli altri dati invalidi. Round-trip
normale invariato (`state()` produce sempre un `int` reale). Test fail-first: `count=True/False`
viene rifiutato e il limiter conserva lo stato valido precedente.

## low-timer-lock — replace/cancel del timer di scadenza atomico sotto lock

`_schedule_expiry` faceva `cancel` del timer precedente, poi creava un nuovo `threading.Timer`, lo
assegnava a `self._expire_timer` e lo avviava — **senza lock**. Due caller concorrenti (es. il
bot-thread via `_process`, un retry, o il thread GUI) potevano leggere lo stesso `_expire_timer`,
avviare entrambi un nuovo Timer e lasciarne uno **non referenziato** ma comunque avviato → fira lo
stesso (double-fire idempotente, ma è un leak di thread/timer). Fix: lock DEDICATO `_timer_lock`
che serializza il replace (cancel+create+assign+start atomico) e un punto unico
`_cancel_expiry_timer()` (cancel+azzeramento sotto lock) usato da STOP/chiusura/`_manual_clear`,
così un cancel non si interlaccia con un replace. Il lock è **mai annidato** nel `_queue_lock` (i
caller rilasciano il queue_lock prima; il callback del timer usa solo il queue_lock) → niente
deadlock. L'harness dei test (`conftest`) aggiunge `_timer_lock` come gli altri attributi di stato.

Test (fail-first, due thread reali con handoff a eventi): un interleaving cancel→assign lasciava
DUE timer vivi (avviati e mai cancellati); col lock ne resta esattamente UNO, e
`_cancel_expiry_timer` lo ferma (zero residui).

## low-tracker-nonwrite — i guardrail riflettono SOLO i WRITE reali

In `write_path.commit_signal`, `live_guard.evaluate` consumava stato dei guardrail anche per esiti
che NON scrivono: un segnale NEW veniva memorizzato nel `SignalTracker` (dedupe), e `DailyLimiter.
allow()` **incrementa** il contatore quando ammette. Quindi: `DRY_RUN` registrava l'hash **e**
consumava il tetto giornaliero reale (N segnali simulati con tetto N esaurivano la quota e poi
bloccavano i segnali reali); `DAILY_LIMITED` registrava l'hash che restava a sopprimere come
duplicato un re-send anche dopo il reset del giorno (bet persa). Fix: su `DAILY_LIMITED` e `DRY_RUN`
si fa **rollback** di tracker (+daily) allo snapshot pre-`evaluate`, lo stesso meccanismo già usato
per `blocked_by_cap`/write-failure. `DUPLICATE`/`RATE_LIMITED` non vengono toccati (`register` non
aveva aggiunto nulla). Invariante risultante: *lo stato dei guardrail (dedupe + tetto) riflette SOLO
i WRITE reali*. **Niente doppia scommessa**: un duplicato reale nasce comunque dall'hash di un WRITE
ed è ancora soppresso; un segnale mai scritto non blocca più una bet futura.

Refinement (Codex P2): il rollback è **per-esito**, non un `restore_state` cieco del daily.
`DAILY_LIMITED` → si annulla SOLO l'hash del tracker; il daily NON si tocca, perché `allow()` non
aveva consumato slot (solo, eventualmente, normalizzato il giorno corrente). Un `restore_state`
pieno avrebbe riportato un **giorno corrotto** (state file malformato → `_UNKNOWN_DAY`), che non si
resetta mai → bridge bloccato per sempre. `DRY_RUN` → si annulla l'hash e si **restituisce** la slot
giornaliera con il nuovo `DailyLimiter.release()` (decremento con floor 0) che MANTIENE il giorno
normalizzato, invece di ripristinare lo snapshot.

Test (fail-first): DRY_RUN non consuma il tetto giornaliero; DRY_RUN non avvelena il dedupe reale;
DAILY_LIMITED ritentabile dopo il reset del tetto; DAILY_LIMITED/DRY_RUN con giorno corrotto lo
**normalizzano** (non si bloccano); `release()` restituisce una slot mantenendo il giorno (floor 0);
+ guardia anti-regressione che un WRITE reale resta deduplicato (no doppia scommessa).

## M12 — viewer dizionario: debounce della ricerca (no query+rebuild per keystroke)

Nel pannello «Dizionario Betfair» ogni `<KeyRelease>` nella casella «Cerca» chiamava `_refresh()`,
che interroga il DB e **ricostruisce l'intera tabella** (centinaia di widget) → lag visibile con
dizionari grandi. Fix: estratto un `Debouncer` **puro e testabile** in `dictionary_viewer.py`
(coalescente: `trigger()` annulla il pending e riprogramma; `cancel_pending()` per le azioni
immediate), usato dalla GUI con `widget.after`/`after_cancel` (250 ms). La digitazione veloce
collassa in UNA sola query/rebuild a fine battitura; Invio, menu, checkbox e i pulsanti restano
refresh **immediati** (`_refresh_now` annulla un eventuale debounce pendente). Nessun cambio alla
logica di lettura (`DictionaryViewerController`), al DB o al contenuto mostrato.

Test (CI, headless): `Debouncer` con scheduler finto — coalescing di una raffica in una sola
azione, `cancel_pending`, riprogrammazione dopo lo scatto (fail-first: la classe non esisteva).
**Smoke test manuale** (GUI reale, non in CI): apri Strumenti → Dizionario Betfair; digita
rapidamente nella casella «Cerca» → la tabella si aggiorna UNA sola volta a fine digitazione (non a
ogni tasto); premi Invio → aggiornamento immediato; cambia Livello/Sport/«Solo attivi»/«🔄 Aggiorna»
→ aggiornamento immediato. Atteso: nessun lag percepibile su un dizionario grande. Resta non
verificato in automatico il rendering reale dei widget (richiede display).

Teardown (Codex P2): il pannello sovrascrive `destroy()` per chiamare `cancel_pending()` prima di
`super().destroy()`. Senza, se l'utente digita e chiude la finestra Strumenti entro i 250 ms, il
timer `after` scatterebbe contro un pannello già distrutto (Tcl background error sul normale
percorso di chiusura). Il meccanismo su cui si basa (`cancel_pending` impedisce l'azione) è coperto
dal test headless; la sovrascrittura di `destroy` NON è auto-testabile (il modulo GUI richiede
`customtkinter`+display, assenti in CI). **Smoke test manuale aggiuntivo**: digita in «Cerca» e
chiudi SUBITO la finestra Strumenti → nessun errore in console alla chiusura.

## M11 — `catalogue_client`: contesto TLS esplicito sulle chiamate read-only

`_http_post_json` e `_http_navigation` chiamavano `urlopen` SENZA `context=` esplicito, a differenza
di `auth_client` che costruisce `ssl.create_default_context()`. La verifica TLS di default è attiva
(quindi non era un leak attuale), ma un'impostazione di verifica IMPLICITA è sovrascrivibile da un futuro
override globale (`ssl._create_default_https_context`) che indebolirebbe in silenzio chiamate che
portano credenziali (`X-Authentication`/app key). Fix: nuovo helper `_tls_context()` =
`ssl.create_default_context()` (CERT_REQUIRED + check_hostname), passato esplicito a entrambe le
`urlopen`. Nessun cambio funzionale, nessun client-cert (queste sono read-only con session token, non
il cert-login). Test: due test catturano il `context` passato a `urlopen` e ne verificano
`verify_mode`/`check_hostname` (fail-first: prima era `None`).

## M10 — `parser`: punteggio in mezzo come separatore squadre sulle righe 🆚

Su una riga 🆚 col punteggio IN MEZZO (`Real Madrid 2 - 1 Barcelona`) il `_SCORE_TAIL`
(`\s+\d+\s*[-–:]\s*\d+(?:\s.*)?$`) divorava ` 2 - 1 Barcelona` lasciando solo `Real Madrid`:
nessun separatore → `_teams_from` ritornava `None` → squadre PERSE (fail-closed, ma è un formato
comune). Fix: aggiunto `_teams_from_score` (con `_SCORE_SEP`) come ULTIMO fallback nella sola
branch 🆚 (dopo `v/vs` e ` - `): il punteggio fa da separatore, home prima / away dopo. Ogni lato
passa per `_clean_team_side`, che rimuove la coda di metadati di tempo/stato col marcatore esplicito
(`46m`/`46'`/`90+2`/`HT`/`FT`/`LIVE`/`PRE`) e valida il resto come squadra reale (#184 M10, Codex
P1/P2): così `Real Madrid 2 - 1 Barcelona 46m` → `Real Madrid v Barcelona`, mentre `… 2 - 1 HT/FT/
LIVE` o `46m 2 - 1 …` falliscono chiusi (nessuna squadra). Una cifra NUDA non è metadato: i club a
cifra iniziale (`1. FC Köln`, `1860 Munich`) e i suffissi numerici (`Schalke 04`) sono preservati.
La coda quota/@/probabilità sulla stessa riga viene ripulita prima dello split. Vale SOLO per le
righe 🆚
(l'emoji conferma la coppia di squadre); in testo libero uno score in mezzo resta ambiguo e non
produce squadre (`Italy 2 - 1 Serie A` → vuoto). Nessun cambio su CSV/quota/score; la rimozione
del punteggio a fine riga (`Home v Away 6 - 0 46m`) resta invariata.

## M9 — `dizionario.market_types()` degrada con `.get()` invece di `KeyError`

`market_types(rows)` indicizzava diretto `row["MarketType_XTrader"]` mentre tutti i fratelli del
modulo (`market_catalog`, `selections_for_market`, …) usano `row.get(...) or ""`: una riga senza
quella colonna (dizionario non validato a monte, o un dict parziale) sollevava `KeyError` invece
di degradare. Fix: usa `.get(...)`, strippa il valore e **esclude** i vuoti (coerente con
`market_catalog`, che salta un `mt` vuoto). Sul dizionario reale l'output non cambia (ogni riga ha
un MarketType non vuoto): un test lo verifica confrontando con i MarketType di `market_catalog`.
Nessun impatto su CSV/parser/Telegram; nessun cambio di contratto del dizionario.

## M8 — `log_privacy.redact_message`: prefisso e payload passano da `redact_secrets`

La forma "privacy on" ritornava i primi `FIRSTLINE_CHARS` (40) char della prima riga **grezzi**,
senza `redact_secrets`: un token a inizio messaggio finiva in chiaro nel log nonostante la
privacy (era il path di leak più concreto dell'audit). Anche la forma `full=True` (payload di
debug) non era redatta. Fix: `redact_message` ora passa sia il payload completo sia la prima riga
per `event_log.redact_secrets`. La redazione avviene **prima** del troncamento, così un token a
cavallo del confine dei 40 char non trapela tagliato a metà. Hash sha256 e lunghezza restano sul
testo grezzo (lo sha256 è una via sola e serve solo a correlare messaggi identici; la lunghezza
non rivela contenuto). Difesa-in-profondità: i due call-site (`_dbg`→`_log`) già ripassano da
`redact_secrets`, ma ora la funzione mantiene il proprio contratto a prescindere dal chiamante.
Nessun cambio di formato/colonne CSV; copre anche i literal registrati non canonici (M7).

Refinement (Codex P2): redarre l'INTERA prima riga prima di tagliare trascinava nell'anteprima
testo che stava OLTRE il confine grezzo dei 40 char (un token lungo si accorcia a
`[REDACTED_TOKEN]` e fa salire contenuto privato che la privacy non doveva mostrare). Introdotto
`event_log.redact_preview(text, budget)`: rivela al più `budget` char GREZZI, mascherando per
intero un segreto che attraversa il confine (fixpoint sugli span dei segreti) ma SENZA mostrare
contenuto non-segreto oltre il budget. `log_privacy` usa `redact_preview(first, FIRSTLINE_CHARS)`;
l'ellissi resta legata al budget originale. Senza segreti è un semplice taglio a `budget` (il
troncamento originale è preservato).

## M7 — redazione token: per-literal del token registrato, non solo la regex

`event_log.redact_secrets` mascherava solo lo shape CANONICO del bot token Telegram
(`\d{6,}:[A-Za-z0-9_-]{20,}`): una forma NON standard (porzione segreta < 20 char,
URL-encoded coi `:`→`%3A`, spezzata su righe) le sfuggiva e il docstring "mai token in chiaro"
sovrastimava la garanzia. Fix: aggiunto un registro di segreti ESATTI (`register_secret`/
`unregister_secret`/`clear_secrets`, thread-safe, soglia minima 8 char) — mirror di
`betfair/log_safety` — e `redact_secrets` ora maschera per-literal i segreti registrati
(più lunghi prima) OLTRE alla regex. `app` registra il bot token VIVO a load e a save
(`_register_secret_token`), così è mascherato in qualunque forma finisca in un log
(`_log`/`_set_last`/`diagnostics`/`event_journal` passano tutti da `redact_secrets`). Limite
residuo documentato: un segreto MAI registrato e non canonico può ancora sfuggire.

Refinement (Sourcery): `_register_secret_token` è il punto UNICO di load/save e deregistra il
token precedente quando cambia o viene rimosso (traccia `self._registered_token`), così il
registro dei segreti non cresce all'infinito e un vecchio token non resta mascherato per sempre.

Refinement (Codex P1): `app` registra solo il token GREZZO; `redact_secrets` ora deriva le forme
del literal (`_secret_forms`: grezzo + URL-encoded, `:`→`%3A`), così anche la forma encoded che
finisce in un URL/HTTP dentro un'eccezione viene mascherata — senza dover registrare a mano la
forma encoded. Limite residuo: forme non previste (spezzata su righe, doppia codifica) possono
ancora sfuggire.

## Decisioni del proprietario (NON implementare senza conferma)

- **low-tracker-nonwrite** — **DECISO** (proprietario ha delegato la scelta): committare i
  guardrail **solo sul path WRITE**. Su `DAILY_LIMITED` e `DRY_RUN` si fa rollback di tracker+daily.
  Motivo decisivo: `DailyLimiter.allow()` **incrementa** il contatore, quindi in DRY_RUN la
  simulazione consumava il tetto giornaliero REALE (oltre ad avvelenare il dedupe); e un
  `DAILY_LIMITED` trattenuto restava soppresso come duplicato anche dopo il reset del giorno. La
  nuova invariante — *stato guardrail ⟺ WRITE reale* — fixa entrambi SENZA rischio di doppia
  scommessa (un duplicato reale nasce comunque da un WRITE). Vedi sezione «low-tracker-nonwrite».
- Ogni altro LOW marcato «decidere» nel corpo dell'issue.

## Regole non negoziabili

Mai su `main`, mai merge/auto-merge, mai indebolire le invarianti safety (CSV atomico
one-signal-at-a-time, rollback anti-doppia-scommessa, gate `chat_id` allowlist fail-closed,
dedupe persistente, epoch poller, niente bet Betfair, sessionToken solo in RAM, niente
segreti nei log). Check-completion-gate prima di dichiarare una PR pronta al merge.

## H2 — fsync della directory dopo `os.replace`

`atomic_io._fsync_dir(d)` viene chiamato dopo ogni `replace(tmp, path)` riuscito: rende
**durabile** anche la voce di directory creata dal rename. Senza, POSIX non garantisce che,
dopo un power-loss subito dopo il replace, il file non torni al contenuto precedente (CSV
stantio, stato dedupe/daily/config vecchio). È **best-effort e non solleva mai**: su Windows
(dir non apribile come fd) o su filesystem che rifiutano l'fsync di una directory è un no-op,
e — essendo chiamato DOPO un replace già riuscito — un suo errore non perde il file scritto.

## H5 — arresto listener con un solo percorso autorevole (no fire-and-forget)

`_stop` non sottomette più `updater.stop()`/`app.stop()` al loop con
`run_coroutine_threadsafe`. Quelle coroutine non venivano mai attese: il supervisor
(`_run_bot`), uscendo dal `while _is_current()` quando `_running` diventa False, chiude
l'event loop con `loop.close()`, che **scarta** le coroutine pendenti → rumore
"Event loop is closed", eccezioni mai recuperate e doppio stop dell'updater (l'arresto
vero avviene già IN-loop in `_async_run`: `await updater.stop(); app.stop(); app.shutdown()`).
Ora `_stop` segnala soltanto lo stop (`_running=False` + `_stop_event.set()`) e lascia
che lo **stesso** event loop esegua lo shutdown ordinato prima di `loop.close()`. Niente
finestra di doppia scommessa: `_running` già False impedisce ogni scrittura CSV nei ≤1s
prima dello stop in-loop (`_process` scrive solo se `_running`), e `_is_current()`/epoch
invalidano comunque la vecchia sessione (nessun doppio poller a un AVVIA successivo).
Questo rende anche `_on_close` più deterministico: il join del thread del bot non corre
più con coroutine fire-and-forget scartate da `loop.close()`.

**Hardening review Codex #191 (P1) — STOP→START rapido.** Togliere il fire-and-forget
da solo allargava la finestra di arresto: l'attesa in-loop era un `asyncio.sleep(1)` non
interrompibile, quindi il vecchio updater poteva restare attivo fino a ~1s mentre il
pulsante AVVIA era già riabilitato. Due correzioni complementari:

1. **Arresto prompt e interrompibile.** L'attesa in-loop ora è
   `await asyncio.wait_for(self._async_stop_event.wait(), timeout=1)`; `_stop`, dal thread
   GUI, sveglia subito quell'`asyncio.Event` con `loop.call_soon_threadsafe(evt.set)`. Lo
   shutdown resta atteso in-loop (nessuna coroutine scartata, obiettivo H5) ma senza la
   finestra di ~1s con il vecchio poller attivo.
2. **Gate fail-closed per epoch in `_handle`.** `_process` faceva gate solo su `_running`:
   dopo uno STOP→START rapido un update consegnato dal vecchio updater poteva passare
   (`_running` rimesso True dal nuovo START) e scrivere con la cfg della VECCHIA sessione
   (CSV/DRY_RUN/limiti) → rischio segnale doppio/stantio. Ora `_handle` ritorna subito se
   `not _is_current()` (running **e** stesso epoch), indipendente dal timing dell'arresto.

**Hardening review Codex #191 (P1, round 2) — shutdown legato alla sessione.** Lo shutdown
in-loop e quello d'errore usavano `self._tg_app`/`self._loop`/`self._async_stop_event`
(attributi CONDIVISI): in uno STOP→START rapido un nuovo START li rimpiazza prima che il
vecchio loop arrivi allo shutdown, così il vecchio `_async_run` fermava l'app NUOVA e
lasciava il proprio updater a fare polling (segnali persi / conflitto Telegram). Correzione:
ogni sessione tiene riferimenti LOCALI (`app`, `stop_evt`) e li usa per handler/avvio/attesa/
shutdown; `_safe_shutdown_tg(app, loop)` riceve l'app e il loop della propria sessione e azzera
`self._tg_app` solo se punta ancora alla propria app. `self._tg_app`/`self._async_stop_event`
restano solo come *handle* per i lettori esterni e per `_stop` (che sveglia la sessione
corrente), senza più dirottare il teardown di una sessione superata.

**Hardening review Codex #191 (P1, round 3) — epoch ricontrollato al punto di scrittura.**
Il gate epoch in `_handle` era solo all'INGRESSO del callback: tra quel check e la scrittura
in `_process`/`_process_confirmation`, un STOP→START sul thread GUI può avanzare l'epoch
(1→2) e rimettere `_running=True`, e quei metodi facevano gate solo su `_running` → il vecchio
callback scriveva/consumava stato con la cfg della VECCHIA sessione (TOCTOU). Correzione:
`_process`/`_process_confirmation` ricevono `epoch` da `_handle` e lo ricontrollano via
`_epoch_current(epoch)` (running **e** stesso `_listener_epoch`) sia all'ingresso sia **sotto
`_queue_lock`**, allo stesso punto della scrittura. Così uno STOP→START intervenuto a metà
non fa scrivere/confermare una sessione superata (il segnale resta in coda, ritentabile).
`epoch=None` per chiamanti legacy/test → comportamento invariato (solo `_running`).
