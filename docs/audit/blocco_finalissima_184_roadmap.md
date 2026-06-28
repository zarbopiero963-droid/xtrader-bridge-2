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
| M4 | m4-day-format | `safety_guard.py` | in PR |
| M5 | m5-retry-errno | `csv_writer.py` | da fare |
| M6 | m6-journal-atomic | `event_journal.py` | da fare |
| M7 | m7-token-redact | `event_log.py` | da fare |
| M8 | m8-privacy-prefix | `log_privacy.py` | da fare |
| M9 | m9-market-types-get | `dizionario.py` | da fare |
| M10 | m10-score-tail | `parser.py` | da fare |
| M11 | m11-tls-context | `betfair/catalogue_client.py` | da fare |
| M12 | m12-viewer-debounce | `betfair/dictionary_viewer_gui.py` | da fare |
| LOW | low-timer-lock | `app.py` (`_schedule_expiry` sotto lock) | da fare |
| LOW | low-bool-count | `safety_guard.py` (`isinstance` bool) | da fare |
| LOW | low-parser-emoji | `parser.py:215` (strip trailing emoji) | da fare |
| LOW | low-isodds-inf | `parser.py` (`_is_odds` `math.isfinite`) | da fare |
| LOW | low-pipeline-comma | `custom_pipeline.py` (replace virgola naive) | da fare |
| LOW | low-csvpath-validate | `config_store.py` (valida dir `csv_path` a START) | da fare |
| LOW | low-tmp-sweep | `atomic_io.py` (sweep `.tmp` orfani allo startup) | da fare |
| LOW | low-session-expiry | `betfair/session.py` (pulisce su errore scadenza) | da fare |
| LOW | low-autosync-release | `betfair/auto_sync.py` (`release()` in finally guardato) | da fare |
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

## Decisioni del proprietario (NON implementare senza conferma)

- **low-tracker-nonwrite**: il tracker dedupe trattiene l'hash anche sui path **non-WRITE**
  (`DAILY_LIMITED`/`DRY_RUN`) senza rollback → un re-send identico nella finestra è soppresso
  (missed bet, fail-safe). **Intenzionale o committare il tracker solo sul path WRITE?**
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
