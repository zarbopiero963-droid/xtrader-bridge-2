# Event journal (ledger eventi append-only) — issue #110 voce 20

Modulo `xtrader_bridge/event_journal.py`. Risponde alla domanda «cosa aveva fatto il
bridge?» dopo un crash/riavvio in modo **strutturato** e **affidabile**, a differenza
del log testuale `event_log` (pensato per l'utente nella GUI).

## Cos'è
Un **ledger append-only in formato JSONL**: una riga = un evento JSON
`{"id", "ts", "type", "data"}`. Lo storico è ordinato per inserimento e sopravvive a
chiusura/riavvio (file accanto al config, in AppData su Windows).

Path: `runtime_state.event_journal_path(config_dir())` → `<config_dir>/event_journal.jsonl`.

## Vocabolario eventi (`EVENT_TYPES`)
`START`, `STOP`, `SIGNAL_RECEIVED`, `SIGNAL_PARSED`, `SIGNAL_VALIDATED`, `CSV_WRITTEN`,
`CSV_CLEARED`, `XTRADER_CONFIRMED`, `XTRADER_REJECTED`, `RECONNECT`,
`CRASH_RECOVERY_CSV_CLEARED`.

Un `event_type` fuori da questo elenco → `ValueError` (**fail-closed**: un refuso non
finisce silenziosamente nel ledger).

## API
- `append_event(path, event_type, data=None, *, now=None, event_id=None) -> dict`
  costruisce l'evento (tipo validato, payload **redatto**, `now` finito) e lo **appende**
  come una riga JSON con `flush`+`os.fsync`. Ritorna l'evento scritto.
- `make_event(...)` come sopra ma senza scrivere (utile a comporre/testare).
- `read_events(path) -> list[dict]` rilegge il ledger in ordine; **tollerante**: file
  assente → `[]`; una riga finale **troncata** da un crash a metà append viene **saltata**.
- `clear(path) -> bool` svuota il ledger in modo **atomico** (manutenzione/retention).
- `prune_events(path, keep) -> int` mantiene solo gli **ultimi `keep`** eventi (riscrittura
  atomica tmp+`os.replace`), ritorna quanti ne ha rimossi. **Best-effort, non solleva mai**
  (errori di I/O o evento storico non codificabile → `0`); `keep<=0` è un **no-op** (per
  svuotare usa `clear`). Chiamato allo startup (`app.py`) per limitare la crescita del file.

## Invarianti (testati in `tests/unit/test_event_journal.py`)
- **Append-only ordinato**, id univoci, `ts` preservato.
- **Tipo fail-closed**; **`now` non finito** (NaN/inf/bool/non-numerico) rifiutato.
- **Redazione**: nessun token Telegram in chiaro (ricorsiva sui valori + sulla riga
  serializzata) — invariante «mai token nei log».
- **Una sola riga per evento** anche con contenuti multilinea (`json.dumps` escapa `\n`).
- **Crash a metà append**: la riga troncata non rompe il replay.
- **`clear` atomico** senza temporanei residui.

## Aggancio al runtime (#230)
Il ledger è **agganciato al runtime** in `app.py`, in modo **best-effort** (un errore del
journal non blocca mai il trading) tramite l'helper privato `App._journal(...)`:

| Punto in `app.py` | Eventi registrati |
|---|---|
| `__init__` | `prune_events(...)` allo startup (retention, prima di qualunque auto-start) |
| `_start` / `_stop` | `START` (con `dry_run`/`auto`) / `STOP` (solo se una sessione era attiva) |
| `_process` | `SIGNAL_RECEIVED` → `SIGNAL_PARSED` → `SIGNAL_VALIDATED` → `CSV_WRITTEN` (un segnale scartato si ferma a `SIGNAL_PARSED`, `placeable=false`) |
| `_process_confirmation` | `XTRADER_CONFIRMED` / `XTRADER_REJECTED` (+ `CSV_CLEARED` `reason="confirmation"` se era l'ultima riga) |
| `_clear_stale_csv` | `CRASH_RECOVERY_CSV_CLEARED` (all'avvio) / `CSV_CLEARED` (allo stop) |
| `_expire_tick` | `CSV_CLEARED` (`reason="expiry"`) quando l'ultima riga scade e il CSV torna a solo header |
| `_manual_clear` | `CSV_CLEARED` (`reason="manual"`) sullo svuotamento manuale riuscito («Svuota CSV ora») |
| `_run_bot` | `RECONNECT` a ogni tentativo di riconnessione |

Garanzie del wiring: **mai bloccante** (path assente → no-op; qualunque eccezione di
`append_event` è ingoiata), **redatto** (nessun token; il `chat_id` Telegram è registrato come
impronta `chat:sha256:<12 hex>` via `log_privacy.redact_chat_id`, mai l'ID reale — il diario è
un log durevole sotto AppData), **bounded** (`prune_events` allo startup). Ogni evento ha un
timestamp `ts` (epoch) e un `id` univoco, quindi l'ordine reale è ricostruibile ordinando per
`ts` anche se due append concorrenti finissero sfuori ordine sul file. Test:
`tests/unit/test_event_journal.py` (modulo + retention) e
`tests/integration/test_event_journal_wiring.py` (wiring sui metodi reali di `App`).
