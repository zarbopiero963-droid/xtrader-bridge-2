"""Event journal append-only (issue #110 voce 20 / G2): ledger transazionale degli
eventi safety-critical del bridge.

Serve a rispondere a «cosa aveva fatto?» dopo un crash/riavvio in modo affidabile:
ogni passo rilevante (START/STOP, segnale ricevuto/parsato/validato, CSV scritto/
svuotato, conferma/rifiuto XTrader, riconnessione, recovery del CSV all'avvio) può
essere registrato come un EVENTO con id univoco e timestamp. A differenza del log
testuale (`event_log`, pensato per l'utente), questo è un ledger **strutturato** e
**append-only**, pensato per ricostruzione/forense e per future integrazioni.

Proprietà:
- **Append-only JSONL**: una riga = un evento JSON (`{id, ts, type, data}`); l'ordine
  d'inserimento è preservato e lo storico sopravvive a chiusura/riavvio.
- **Atomicità della singola riga**: `write` + `flush` + `os.fsync` per ogni evento.
- **Fail-safe in lettura**: una riga finale TRONCATA da un crash a metà append non
  rompe il replay — `read_events` salta le righe malformate.
- **Redazione**: nessun token Telegram in chiaro (riusa `event_log.redact_secrets`),
  applicata sia ricorsivamente ai valori sia alla riga serializzata (difesa-in-profondità).
- **Fail-closed sul tipo**: un `event_type` non in `EVENT_TYPES` solleva `ValueError`
  (un refuso non finisce silenziosamente nel ledger).
- **Modulo puro**: nessuna dipendenza da GUI/Telegram/CSV runtime → testabile headless.

NB: l'AGGANCIO al runtime (chiamare `append_event` da `app._process`/`_run_bot`/…) è
volutamente fuori da questo modulo e da questa PR: qui c'è solo il ledger e i suoi
invarianti, testati. Il wiring (che tocca la glue GUI di `app.py`) sarà una PR separata.
"""

import json
import os
import time
import uuid

from . import atomic_io, event_log, validators

# Vocabolario degli eventi (G2). Fail-closed: un tipo non in elenco è rifiutato.
EVENT_TYPES = frozenset({
    "START",
    "STOP",
    "SIGNAL_RECEIVED",
    "SIGNAL_PARSED",
    "SIGNAL_VALIDATED",
    "CSV_WRITTEN",
    "CSV_CLEARED",
    "XTRADER_CONFIRMED",
    "XTRADER_REJECTED",
    "RECONNECT",
    "CRASH_RECOVERY_CSV_CLEARED",
})


def _redact(value):
    """Redazione RICORSIVA dei token nei valori stringa (dict/list inclusi), così un
    token finito per errore nel payload non viene mai scritto in chiaro."""
    if isinstance(value, str):
        return event_log.redact_secrets(value)
    if isinstance(value, dict):
        # Redatte anche le CHIAVI stringa: un token usato come chiave non deve restare
        # in chiaro né nell'evento ritornato né nella riga persistita (review Codex).
        return {(event_log.redact_secrets(k) if isinstance(k, str) else k): _redact(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def make_event(event_type, data=None, *, now=None, event_id=None) -> dict:
    """Costruisce (senza scrivere) un evento normalizzato `{id, ts, type, data}`.

    - `event_type` deve essere in `EVENT_TYPES`, altrimenti `ValueError` (fail-closed);
    - `now` (epoch) è validato finito come altrove (`validators.require_finite_now`):
      un timestamp NaN/inf/non-numerico è rifiutato, non scritto;
    - `event_id` è opzionale (default: `uuid4().hex`), iniettabile per i test;
    - `data` è copiato e **redatto** (mai token in chiaro)."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event type sconosciuto: {event_type!r}")
    ts = time.time() if now is None else validators.require_finite_now(now)
    eid = uuid.uuid4().hex if event_id is None else str(event_id)
    payload = _redact(dict(data or {}))
    return {"id": eid, "ts": float(ts), "type": event_type, "data": payload}


def _ends_without_newline(path: str) -> bool:
    """`True` se il file esiste, è non vuoto e NON termina con `\\n` (cioè l'ultima
    riga è troncata, es. da un crash a metà append)."""
    try:
        if os.path.getsize(path) == 0:
            return False
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"
    except OSError:
        return False


def _append_line(path: str, line: str) -> None:
    """Appende UNA riga al file (creando la cartella se serve) con `flush`+`fsync`.

    Se l'ultima riga esistente è TRONCATA (nessun `\\n` finale, es. crash a metà
    append), inserisce prima un `\\n` separatore: così la riga troncata resta isolata
    sulla sua riga (verrà saltata da `read_events`) e il NUOVO evento finisce su una
    riga pulita — senza questo, l'append si concatenerebbe alla riga parziale e anche
    il nuovo evento andrebbe perso (review Codex P1)."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    needs_separator = _ends_without_newline(path)
    with open(path, "a", encoding="utf-8") as f:
        if needs_separator:
            f.write("\n")
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def append_event(path: str, event_type, data=None, *, now=None, event_id=None) -> dict:
    """Costruisce l'evento (tipo validato, payload redatto) e lo APPENDE come una
    riga JSON al ledger `path`. Ritorna l'evento scritto.

    La serializzazione è su una sola riga (`json.dumps` con `\\n` escapato → niente
    righe spezzate da contenuti multilinea); la riga è ri-redatta come difesa finale
    (mai token in chiaro). Solleva `ValueError` su tipo/timestamp non validi; gli
    errori di I/O propagano (il chiamante runtime li gestirà best-effort, come per
    `event_log`)."""
    event = make_event(event_type, data, now=now, event_id=event_id)
    line = event_log.redact_secrets(json.dumps(event, ensure_ascii=False))
    _append_line(path, line)
    return event


def read_events(path: str) -> list:
    """Legge il ledger come lista di eventi (dict), nell'ordine d'inserimento.

    Tollerante e fail-safe: file assente → `[]`; righe vuote ignorate; una riga
    **malformata** (es. l'ultima troncata da un crash a metà append) viene **saltata**
    senza crashare, così il resto dello storico resta leggibile."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError:
        return []
    events = []
    for raw in raw_lines:
        text = raw.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue   # riga troncata/malformata: salta (append-only fail-safe)
        if isinstance(obj, dict):
            events.append(obj)
    return events


def clear(path: str) -> bool:
    """Svuota il ledger in modo ATOMICO (file vuoto), via `atomic_io.atomic_write_text`.
    Utile per manutenzione/retention senza lasciare un file a metà. `True` se riuscito,
    `False` su errore di I/O (best-effort, non solleva)."""
    try:
        atomic_io.atomic_write_text(path, "", prefix=".journal_", suffix=".tmp")
        return True
    except OSError:
        return False
