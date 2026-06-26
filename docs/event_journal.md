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

## Invarianti (testati in `tests/unit/test_event_journal.py`)
- **Append-only ordinato**, id univoci, `ts` preservato.
- **Tipo fail-closed**; **`now` non finito** (NaN/inf/bool/non-numerico) rifiutato.
- **Redazione**: nessun token Telegram in chiaro (ricorsiva sui valori + sulla riga
  serializzata) — invariante «mai token nei log».
- **Una sola riga per evento** anche con contenuti multilinea (`json.dumps` escapa `\n`).
- **Crash a metà append**: la riga troncata non rompe il replay.
- **`clear` atomico** senza temporanei residui.

## Stato (PR scope)
Questa PR introduce **solo il ledger puro e i suoi test**. L'**aggancio al runtime**
(chiamare `append_event` da `app._process` / `_process_confirmation` / `_run_bot` /
`_clear_stale_csv` ai punti CSV_WRITTEN / CSV_CLEARED / XTRADER_* / RECONNECT /
START/STOP / CRASH_RECOVERY_CSV_CLEARED) tocca la glue GUI di `app.py` ed è volutamente
lasciato a una **PR separata**, per tenere il cambiamento isolato e rivedibile. Finché
il wiring non c'è, il ledger esiste e funziona ma non viene ancora popolato dal runtime.
