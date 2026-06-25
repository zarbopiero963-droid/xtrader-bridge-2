"""Test hard della sezione critica del percorso di scrittura (`write_path.commit_signal`).

Esercita il CUORE anti-doppia-scommessa con collaboratori REALI (SignalQueue,
SignalTracker, DailyLimiter) e una `write_rows` iniettabile: scrittura riuscita,
fallimento con ROLLBACK completo (coda + dedup + daily), blocco dal tetto righe attive
con rollback dei guardrail (segnale ritentabile), esito non-WRITE (duplicato) che non
tocca la coda, e `tracker=None`.

NB: il lock è responsabilità del chiamante (`App._process`); qui si testa la logica
sotto-lock in isolamento, headless.
"""

from xtrader_bridge import (
    live_guard,
    safety_guard,
    signal_dedupe,
    signal_queue,
    write_path,
)

CFG_REAL = {"dry_run": False}        # scrittura operativa (non simulazione)


def _row(name):
    return {"EventName": name, "SelectionName": name, "Price": "1,90"}


def _ok_writer(sink):
    """write_rows che registra le righe scritte (scrittura riuscita)."""
    def _w(rows, path):
        sink.append([dict(r) for r in rows])
    return _w


def _boom_writer(exc=OSError("CSV locked")):
    """write_rows che fallisce sempre (file bloccato/permessi)."""
    def _w(rows, path):
        raise exc
    return _w


def _fresh(mode=signal_queue.OVERWRITE_LAST, max_active=0, max_per_day=10):
    tracker = signal_dedupe.SignalTracker()
    daily = safety_guard.DailyLimiter(max_per_day=max_per_day)
    queue = signal_queue.SignalQueue(mode=mode, max_active=max_active)
    return tracker, daily, queue


def test_write_riuscita_accoda_e_scrive():
    tracker, daily, queue = _fresh()
    written = []
    row = _row("A")
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.write_error is None
    assert res.blocked_by_cap is False
    assert res.rows == [row]
    assert written == [[row]]            # CSV scritto una volta con la riga
    assert queue.active_rows() == [row]  # segnale attivo in coda


def test_write_fallita_fa_rollback_completo_e_segnale_ritentabile():
    tracker, daily, queue = _fresh()
    row = _row("A")
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _boom_writer())
    # Esito: errore riportato, NON sollevato
    assert isinstance(res.write_error, OSError)
    assert res.decision == live_guard.WRITE
    # Coda ripristinata: la riga NON resta attiva (niente riga stantia se la write fallisce)
    assert queue.active_rows() == []
    # Dedup ripristinato: lo STESSO messaggio non è un duplicato → ritentabile come WRITE
    written = []
    res2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 101.0, _ok_writer(written))
    assert res2.decision == live_guard.WRITE   # non DUPLICATE: il dedup era stato annullato
    assert res2.write_error is None
    assert written == [[row]]


def test_blocco_da_tetto_scrive_correnti_e_fa_rollback_guardrail():
    # tetto 1: A occupa la riga, B (diverso) è oltre il tetto → bloccato.
    tracker, daily, queue = _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=1)
    rowA, rowB = _row("A"), _row("B")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", rowA, "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgB", rowB, "out.csv", 101.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.blocked_by_cap is True
    # Scrive le righe ATTIVE correnti (solo A): B non è accodato
    assert res.rows == [rowA]
    assert written == [[rowA]]
    assert [r["EventName"] for r in queue.active_rows()] == ["A"]
    # Guardrail rollback → B è RITENTABILE: registrarlo ora NON è un duplicato
    reg = tracker.register("msgB")
    assert reg.status != signal_dedupe.DUPLICATE


def test_duplicato_non_scrive_e_non_tocca_la_coda():
    tracker, daily, queue = _fresh()
    row = _row("A")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "dup", row, "out.csv", 100.0, _ok_writer([]))
    before = queue.active_rows()
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "dup", row, "out.csv", 101.0, _ok_writer(written))
    assert res.decision == live_guard.DUPLICATE
    assert res.blocked_by_cap is False
    assert res.rows == []
    assert written == []                 # nessuna scrittura tentata
    assert queue.active_rows() == before  # coda invariata


def test_dry_run_non_scrive():
    tracker, daily, queue = _fresh()
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, {"dry_run": True}, "msgA", _row("A"), "out.csv", 100.0,
        _ok_writer(written))
    assert res.decision == live_guard.DRY_RUN
    assert res.rows == []
    assert written == []
    assert queue.active_rows() == []     # in simulazione la coda non viene toccata


def test_tracker_none_scrive_come_write():
    # Nessun guardrail (tracker None) → decisione di default WRITE.
    _, _, queue = _fresh()
    written = []
    row = _row("A")
    res = write_path.commit_signal(
        None, None, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.write_error is None
    assert written == [[row]]
