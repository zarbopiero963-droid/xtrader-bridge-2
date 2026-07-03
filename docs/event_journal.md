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
| `_start` | `CSV_CLEARED` (`reason="start"`) se l'`init_csv` di START rimuove una riga stantia sopravvissuta a un cleanup lockato, poi `START` (con `dry_run`/`auto`) |
| `_stop` | `STOP` (solo se una sessione era attiva) |
| `_process` | `SIGNAL_RECEIVED` → `SIGNAL_PARSED` → `SIGNAL_VALIDATED` → `CSV_WRITTEN` (un segnale scartato si ferma a `SIGNAL_PARSED`, `placeable=false`) |
| `_process_confirmation` | `XTRADER_CONFIRMED` / `XTRADER_REJECTED` (registrato anche se la riscrittura CSV fallisce: l'esito è già avvenuto) + `CSV_CLEARED` `reason="confirmation"` se era l'ultima riga |
| `_clear_stale_csv` | `CRASH_RECOVERY_CSV_CLEARED` (all'avvio) / `CSV_CLEARED` (allo stop) |
| `_expire_tick` | `CSV_CLEARED` (`reason="expiry"`) quando il CSV torna a solo header (anche su un retry post-write-failure) |
| `_manual_clear` | `CSV_CLEARED` (`reason="manual"`) sullo svuotamento manuale riuscito («Svuota CSV ora») |
| `_run_bot` | `RECONNECT` a ogni tentativo di riconnessione |

### Fedeltà dei clear: transizione reale riga→solo-header (#234)
Gli eventi di clear (`CSV_CLEARED` / `CRASH_RECOVERY_CSV_CLEARED`) sono emessi **solo sulla
transizione reale** «il CSV operativo aveva una riga attiva → ora è a solo header», non sulle
riscritture idempotenti. Il meccanismo è un flag `App._csv_had_active_row` (mirror diagnostico
dello stato su disco): impostato a `True` dopo ogni scrittura che lascia righe, e azzerato
emettendo il clear (`App._journal_csv_cleared_if_had_row`) quando il CSV torna a solo header.
Inizializzato all'avvio da `csv_writer.has_active_row(csv_path)`. Questo evita due falsi:
- **falso positivo:** nessun `CRASH_RECOVERY_CSV_CLEARED` ad ogni avvio pulito con un CSV già a
  solo header;
- **falso negativo:** il clear viene registrato anche quando è un **retry** post-write-failure
  (conferma/scadenza) o l'`init_csv` di **START** a riportare il CSV a solo header.

Garanzie del wiring: **mai bloccante** (path assente → no-op; qualunque eccezione di
`append_event` è ingoiata; il flag è aggiornato fuori dal `_queue_lock`, mai sull'hot-path),
**redatto** (nessun token; il `chat_id` Telegram è registrato come impronta `chat:sha256:<12 hex>`
via `log_privacy.redact_chat_id`, mai l'ID reale — il diario è un log durevole sotto AppData),
**bounded** (`prune_events` allo startup). Ogni evento ha un timestamp `ts` (epoch) e un `id`
univoco, quindi l'ordine reale è ricostruibile ordinando per `ts` anche se due append concorrenti
finissero sfuori ordine sul file. Test: `tests/unit/test_event_journal.py` (modulo + retention),
`tests/integration/test_event_journal_wiring.py` (wiring sui metodi reali di `App`) e
`tests/safety/test_csv_atomic.py` (`has_active_row`).

## Consultare il diario — CLI `journal_view` (#236)
Per leggere il ledger senza aprire il `.jsonl` a mano c'è una CLI **read-only**
(`xtrader_bridge/journal_view.py`): non scrive né modifica **mai** il diario, riusa
`event_journal.read_events` (tollerante alle righe troncate) e **non de-redige nulla**
(mostra i valori esattamente come sono sul file, già redatti).

```bash
python -m xtrader_bridge.journal_view                      # tutti gli eventi, ordinati per ts
python -m xtrader_bridge.journal_view --last 20            # solo gli ultimi 20
python -m xtrader_bridge.journal_view --type CSV_WRITTEN --type CSV_CLEARED   # per tipo (ripetibile)
python -m xtrader_bridge.journal_view --since 1751000000 --until 1751100000   # intervallo epoch
python -m xtrader_bridge.journal_view --json               # output JSON (per script/pipe)
python -m xtrader_bridge.journal_view --path /altro/journal.jsonl            # file alternativo
```

| Opzione | Effetto |
|---|---|
| `--path PATH` | Ledger da leggere (default: `runtime_state.event_journal_path(config_dir())`) |
| `--type TYPE` | Filtra per tipo evento; **ripetibile** (unione). Tipi: gli 11 di `EVENT_TYPES` |
| `--last N` | Solo gli ultimi N eventi dopo l'ordinamento per `ts` (`--last 0` = nessuno) |
| `--since TS` / `--until TS` | Intervallo epoch **inclusivo** su `ts` |
| `--json` | Output JSON indentato invece della tabella `ts leggibile · TYPE · data` |

Gli eventi sono sempre **ordinati per `ts`** (ordine forense reale, ricostruito anche se
due append concorrenti finissero fuori ordine sul file). Un file assente o illeggibile
produce output vuoto, non un errore. La logica pura (`filter_events`/`format_table`/
`format_json`/`render`) è separata dall'entrypoint ed è coperta da
`tests/unit/test_journal_view.py` (ordinamento, filtri, riga malformata saltata, file
assente, non-de-redazione + file non toccato, entrypoint `main`).

## Consultare il diario — scheda GUI «📒 Diario» (#236)
La stessa vista è disponibile senza terminale nella scheda **«📒 Diario»** dell'hub
**🧰 Strumenti** (`xtrader_bridge/journal_view_gui.py`, `JournalPanel`). Riusa la logica
pura della CLI (`journal_view.filter_events`/`table_rows`), quindi condivide le **stesse
invarianti**: read-only (nessuna scrittura sul ledger), niente de-redazione, ordinamento
per `ts`, tollerante alle righe malformate.

Controlli della scheda:

| Controllo | Effetto |
|---|---|
| **Tipo** (dropdown) | Filtra per tipo evento (`(tutti i tipi)` = nessun filtro); i tipi sono gli 11 di `EVENT_TYPES` |
| **Ultimi** (dropdown) | Ultimi N eventi dopo l'ordinamento per `ts` (`50/100/200/500` o `Tutti`) |
| **🔄 Aggiorna** | Rilegge il ledger da disco e ricostruisce la tabella |
| **📂 Apri cartella** | Apre nel file manager la cartella che contiene il ledger (best-effort) |

La riga conteggi mostra `Diario: N eventi totali (mostrati M).`; un file **assente o illeggibile**
dà `mostrati 0` senza errore (`read_events` è fail-safe: su `OSError` — file mancante o permessi —
ritorna lista vuota), mentre un errore di lettura **inatteso** (eccezione non-`OSError`) viene
mostrato come `⚠️ Errore lettura diario: <Tipo>`. Il modulo GUI non è testato in CI (serve un display): la logica
esercitabile (`_refresh` su un ledger reale, filtri, read-only + non-de-redazione, guardia
strutturale «nessuna scrittura») è coperta da `tests/unit/test_journal_view_gui.py`; il resto
è verifica manuale.

**Smoke test manuale (Windows/con display):** apri **🧰 Strumenti → 📒 Diario** →
la tabella mostra gli ultimi eventi (`ts` leggibile, tipo, dati redatti) → cambia **Tipo** e
**Ultimi** (la tabella e la riga conteggi si aggiornano) → premi **🔄 Aggiorna** dopo un nuovo
evento (compare) → premi **📂 Apri cartella** (si apre la cartella del ledger). Atteso: nessun
token in chiaro, il file `event_journal.jsonl` non cambia (read-only).
