"""Test hard del WIRING dell'event journal nel runtime (#230).

Esercita i METODI REALI di `App` (headless, harness di `conftest.py`) e verifica che gli
eventi safety-critical finiscano nel ledger append-only: `SIGNAL_RECEIVED`/
`SIGNAL_VALIDATED`/`CSV_WRITTEN` (in `_process`), `XTRADER_CONFIRMED`/`XTRADER_REJECTED`
(in `_process_confirmation`), `CRASH_RECOVERY_CSV_CLEARED`/`CSV_CLEARED` (in
`_clear_stale_csv`). Verifica anche il contratto **best-effort**: senza path il journal è
no-op e un errore di `append_event` NON blocca il trading (il CSV viene comunque scritto).
"""

import csv

from xtrader_bridge import event_journal, safety_guard, signal_dedupe, signal_queue


def _row(name, selection=None, price="1,90"):
    sel = selection if selection is not None else name.split(" v ")[0]
    return {"EventName": name, "MarketName": "Esito finale",
            "SelectionName": sel, "Price": price, "BetType": "PUNTA"}


def _patch_resolve(monkeypatch, app_mod, *, row):
    rr = app_mod.signal_router.RouteResult(row=row, source="custom")
    monkeypatch.setattr(app_mod.signal_router, "resolve_row", lambda *a, **k: rr)


def _patch_resolve_discard(monkeypatch, app_mod):
    rr = app_mod.signal_router.RouteResult(row=None, status="INVALID", source="custom",
                                           missing_required=["Price"])
    monkeypatch.setattr(app_mod.signal_router, "resolve_row", lambda *a, **k: rr)


def _types(path):
    return [e["type"] for e in event_journal.read_events(path)]


def _make(a, tmp_path):
    a._journal_path = str(tmp_path / "event_journal.jsonl")
    return a._journal_path


# ── _process ─────────────────────────────────────────────────────────────────

def test_process_success_journaled(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q, tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    jpath = _make(a, tmp_path)
    _patch_resolve(monkeypatch, app_mod, row=_row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1")

    assert _types(jpath) == ["SIGNAL_RECEIVED", "SIGNAL_VALIDATED", "CSV_WRITTEN"]
    ev = event_journal.read_events(jpath)
    assert ev[0]["data"]["chat"] == "1"
    assert ev[2]["data"]["rows"] == 1 and ev[2]["data"]["source"] == "custom"


def test_process_discarded_journals_only_received(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q, tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    jpath = _make(a, tmp_path)
    _patch_resolve_discard(monkeypatch, app_mod)

    app_mod.App._process(a, "spazzatura", {"csv_path": path, "dry_run": False}, chat_id="1")

    # scartato: ricevuto ma NON validato/scritto
    assert _types(jpath) == ["SIGNAL_RECEIVED"]


# ── _process_confirmation ────────────────────────────────────────────────────

def _queue_with(*rows):
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    for i, r in enumerate(rows):
        q.add(r, now=1000 + i)
    return q


def test_confirmation_confirmed_journaled(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    jpath = _make(a, tmp_path)

    app_mod.App._process_confirmation(
        a, "Inter v Milan Esito finale Inter piazzata", {"csv_path": path})

    assert "XTRADER_CONFIRMED" in _types(jpath)
    assert "XTRADER_REJECTED" not in _types(jpath)


def test_confirmation_rejected_journaled(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    jpath = _make(a, tmp_path)

    app_mod.App._process_confirmation(
        a, "Inter v Milan Esito finale Inter rifiutata",
        {"csv_path": path, "rejection_keywords": ["rifiutata"]})

    assert "XTRADER_REJECTED" in _types(jpath)
    assert "XTRADER_CONFIRMED" not in _types(jpath)


# ── _clear_stale_csv ─────────────────────────────────────────────────────────

def _stale_csv(path):
    from xtrader_bridge import csv_writer
    csv_writer.write_rows([{"EventName": "Vecchio v Segnale", "BetType": "PUNTA"}], path)


def test_clear_stale_startup_journals_crash_recovery(make_app, app_mod, tmp_path):
    path = str(tmp_path / "segnali.csv")
    _stale_csv(path)
    a = make_app(config={"csv_path": path})
    jpath = _make(a, tmp_path)

    app_mod.App._clear_stale_csv(a, "all'avvio")

    assert _types(jpath) == ["CRASH_RECOVERY_CSV_CLEARED"]


def test_clear_stale_stop_journals_csv_cleared(make_app, app_mod, tmp_path):
    path = str(tmp_path / "segnali.csv")
    _stale_csv(path)
    a = make_app()
    jpath = _make(a, tmp_path)

    app_mod.App._clear_stale_csv(a, "allo stop", path=path)

    assert _types(jpath) == ["CSV_CLEARED"]


# ── best-effort: il journal non deve mai bloccare il trading ─────────────────

def test_journal_no_path_e_no_op(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q, tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    # NESSUN _journal_path impostato
    _patch_resolve(monkeypatch, app_mod, row=_row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1")

    # il CSV è scritto comunque, nessun file journal creato, nessuna eccezione
    assert not (tmp_path / "event_journal.jsonl").exists()
    with open(path, newline="", encoding="utf-8-sig") as f:
        assert [r["EventName"] for r in csv.DictReader(f)] == ["Inter v Milan"]


def test_journal_append_error_non_blocca_la_scrittura(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q, tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    _make(a, tmp_path)
    _patch_resolve(monkeypatch, app_mod, row=_row("Inter v Milan"))

    def _boom(*a_, **k_):
        raise OSError("journal su disco pieno (simulato)")

    monkeypatch.setattr(app_mod.event_journal, "append_event", _boom)

    # non deve sollevare: il journal è best-effort
    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1")

    # il trading prosegue: il CSV è scritto nonostante il journal fallisca
    with open(path, newline="", encoding="utf-8-sig") as f:
        assert [r["EventName"] for r in csv.DictReader(f)] == ["Inter v Milan"]
