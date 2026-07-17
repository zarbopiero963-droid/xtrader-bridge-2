"""P3-1 + P3-4 audit #76 — igiene di logging/osservabilità.

- **P3-1** (`app.py`): con debug attivo, `_process` loggava `IN (chat <chat_id RAW>)` —
  il chat_id (dato sensibile, regole Telegram safety del repo) finiva IN CHIARO nel log
  persistente sotto AppData, mentre il diario eventi lo redige. Fix: stessa impronta
  stabile del diario (`log_privacy.redact_chat_id` → `chat:sha256:<12hex>`): gli eventi
  restano correlabili tra log e diario, l'ID mai in chiaro.
- **P3-4** (`event_journal.py`): il diario ha TRE thread scriventi (GUI, listener
  Telegram, timer expiry) e `_append_line` è un check-then-write (sonda del newline
  finale + write) SENZA lock: due append concorrenti potevano interlacciarsi → riga
  JSONL corrotta/persa (solo forense, ma il diario esiste per essere affidabile).
  Fix: `_WRITE_LOCK` di modulo attorno all'intero append.

La race P3-4 pre-patch non è deterministica (dipende dallo scheduler): il fail-first
deterministico è sul vincolo STRUTTURALE (lock presente e usato); il comportamento è
validato da un hammer REALE multi-thread su file vero (tutti gli eventi leggibili,
nessuna riga invalida)."""

import json
import re
import threading
from pathlib import Path

from xtrader_bridge import event_journal

_ROOT = Path(__file__).resolve().parents[2]


# ── P3-1: chat_id redatto nel debug-log ──────────────────────────────────────────────

def test_debug_in_logga_il_chat_id_redatto():
    """La lambda del debug-IN deve bindare `c=log_privacy.redact_chat_id(chat_id)`,
    mai il chat_id raw (app.py non è importabile headless: sorgente pinnato su file,
    pattern consolidato del repo)."""
    src = (_ROOT / "xtrader_bridge" / "app.py").read_text(encoding="utf-8")
    i = src.index('self._dbg(f"IN (chat')
    blocco = src[max(0, i - 400):i]
    assert "c=log_privacy.redact_chat_id(chat_id)" in blocco, (
        "app.py: il debug-IN deve redarre il chat_id (finisce nel log persistente)")
    assert re.search(r"c=chat_id\b", blocco) is None, (
        "app.py: chat_id RAW ancora bindato nella lambda del debug-IN (P3-1 #76)")


def test_redazione_correlabile_col_diario():
    """Stessa impronta del diario: `chat:sha256:<12hex>`, stabile e mai l'ID in chiaro.
    E il caso `None`/vuoto (review Fable/Fugu/GLM #89: `_process` ha `chat_id=None` di
    default) NON solleva e ritorna `None` → la lambda mostra `?` via `c or '?'`,
    identico al comportamento pre-patch."""
    from xtrader_bridge import log_privacy
    out = log_privacy.redact_chat_id("-1001234567890")
    assert out == log_privacy.redact_chat_id(-1001234567890)   # int/str → stessa impronta
    assert re.fullmatch(r"chat:sha256:[0-9a-f]{12}", out)
    assert "1234567890" not in out
    assert log_privacy.redact_chat_id(None) is None            # mai raise, mai hash di "None"
    assert log_privacy.redact_chat_id("") is None
    assert log_privacy.redact_chat_id("   ") is None


# ── P3-4: append del diario serializzato ─────────────────────────────────────────────

def test_append_line_usa_il_lock_di_modulo():
    """Vincolo strutturale (fail-first deterministico: pre-patch il lock non esisteva):
    `_WRITE_LOCK` è un Lock di modulo e l'INTERO corpo di `_append_line` (sonda del
    newline inclusa: è la parte check-then-write della race) sta sotto il lock."""
    assert isinstance(event_journal._WRITE_LOCK, type(threading.Lock()))
    src = (_ROOT / "xtrader_bridge" / "event_journal.py").read_text(encoding="utf-8")
    body = src[src.index("def _append_line"):src.index("def append_event")]
    with_idx = body.index("with _WRITE_LOCK:")
    assert body.index("_ends_without_newline(path)") > with_idx, (
        "event_journal.py: la sonda del newline deve stare DENTRO il lock "
        "(è il check della race check-then-write)")
    assert body.index('open(path, "a"') > with_idx


def test_append_concorrenti_nessuna_riga_corrotta(tmp_path):
    """Hammer REALE: 4 thread × 50 append sullo stesso file → 200 eventi tutti
    leggibili, ognuno JSON valido, nessuna riga persa/interlacciata."""
    path = str(tmp_path / "journal.jsonl")
    threads = [threading.Thread(target=lambda i=i: [
        event_journal.append_event(path, "SIGNAL_RECEIVED", {"note": f"t{i}-{j}"})
        for j in range(50)]) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    raw_lines = [l for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(raw_lines) == 200, f"attese 200 righe, trovate {len(raw_lines)}"
    for line in raw_lines:
        json.loads(line)                       # ogni riga è JSON integro
    events = event_journal.read_events(path)
    assert len(events) == 200                  # nessun evento perso o saltato
    # unicità (GLM #89): 200 event_id distinti e tutti i 200 payload distinti presenti —
    # esclude che il conteggio passi con duplicati che mascherano eventi persi.
    assert len({e["id"] for e in events}) == 200
    assert {e["data"]["note"] for e in events} == {f"t{i}-{j}" for i in range(4)
                                                   for j in range(50)}


def test_append_dopo_coda_troncata_resta_serializzato(tmp_path):
    """Il ramo del SEPARATORE (coda troncata da crash) sotto concorrenza: la riga
    troncata resta isolata e i nuovi eventi sono tutti leggibili."""
    path = tmp_path / "journal.jsonl"
    path.write_text('{"troncata": tru', encoding="utf-8")   # crash a metà append
    threads = [threading.Thread(target=lambda: event_journal.append_event(
        str(path), "SIGNAL_RECEIVED", {"k": "v"})) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = event_journal.read_events(str(path))
    assert len(events) == 8                    # la coda troncata è isolata, 8 eventi validi
