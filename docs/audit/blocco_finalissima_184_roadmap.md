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
| H3 | h3-clear-toctou | `csv_writer.py` | in PR |
| H4 | h4-dedupe-finite | `signal_dedupe.py` | da fare |
| H5 | h5-stop-futures | `app.py` | da fare |
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
