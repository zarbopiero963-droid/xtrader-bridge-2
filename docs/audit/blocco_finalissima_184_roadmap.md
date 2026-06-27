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
| H5 | h5-stop-futures | `app.py` | in PR |
| M1 | m1-migrate-strip | `config_store.py` | da fare |
| M2 | m2-chat-strip | `signal_router.py` | da fare |
| M3 | m3-partial-save | `config_store.py` | da fare |
| M4 | m4-day-format | `safety_guard.py` | da fare |
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
