"""Test hard del WIRING dell'event journal nel runtime (#230).

Esercita i METODI REALI di `App` (headless, harness di `conftest.py`) e verifica che gli
eventi safety-critical finiscano nel ledger append-only: `SIGNAL_RECEIVED`/
`SIGNAL_VALIDATED`/`CSV_WRITTEN` (in `_process`), `XTRADER_CONFIRMED`/`XTRADER_REJECTED`
(in `_process_confirmation`), `CRASH_RECOVERY_CSV_CLEARED`/`CSV_CLEARED` (in
`_clear_stale_csv`). Verifica anche il contratto **best-effort**: senza path il journal è
no-op e un errore di `append_event` NON blocca il trading (il CSV viene comunque scritto).
"""

import csv

from xtrader_bridge import event_journal, log_privacy, safety_guard, signal_dedupe, signal_queue


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

    assert _types(jpath) == ["SIGNAL_RECEIVED", "SIGNAL_PARSED", "SIGNAL_VALIDATED", "CSV_WRITTEN"]
    ev = event_journal.read_events(jpath)
    # chat REDATTA nel diario durevole (Codex P2): impronta stabile, mai l'id reale "1".
    assert ev[0]["data"]["chat"] == log_privacy.redact_chat_id("1")
    assert ev[0]["data"]["chat"].startswith("chat:sha256:")
    assert ev[0]["data"]["chat"] != "1"
    # SIGNAL_PARSED: parser girato, segnale piazzabile (CodeRabbit: pipeline completa).
    assert ev[1]["data"]["placeable"] is True and ev[1]["data"]["source"] == "custom"
    assert ev[3]["data"]["rows"] == 1 and ev[3]["data"]["source"] == "custom"


def test_process_discarded_journals_received_e_parsed(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q, tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    jpath = _make(a, tmp_path)
    _patch_resolve_discard(monkeypatch, app_mod)

    app_mod.App._process(a, "spazzatura", {"csv_path": path, "dry_run": False}, chat_id="1")

    # scartato: il parser è girato (SIGNAL_PARSED, placeable=false) ma NON validato/scritto
    # (CodeRabbit: «parser eseguito ma scartato» ≠ «mai ricevuto»).
    assert _types(jpath) == ["SIGNAL_RECEIVED", "SIGNAL_PARSED"]
    assert event_journal.read_events(jpath)[1]["data"]["placeable"] is False


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


def test_confirmation_ultimo_segnale_journals_csv_cleared(make_app, app_mod, tmp_path):
    # Codex P2 (#233): se la conferma rimuove l'ULTIMO segnale attivo, il CSV torna a solo
    # header → deve loggare CSV_CLEARED (reason="confirmation"), DOPO XTRADER_CONFIRMED.
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    jpath = _make(a, tmp_path)
    a._csv_had_active_row = True   # #234: il segnale era stato scritto (CSV_WRITTEN) prima

    app_mod.App._process_confirmation(
        a, "Inter v Milan Esito finale Inter piazzata", {"csv_path": path})

    t = _types(jpath)
    assert "XTRADER_CONFIRMED" in t and "CSV_CLEARED" in t
    assert t.index("CSV_CLEARED") > t.index("XTRADER_CONFIRMED")
    assert event_journal.read_events(jpath)[-1]["data"]["reason"] == "confirmation"


def test_confirmation_non_ultimo_segnale_non_logga_clear(make_app, app_mod, tmp_path):
    # Guard: se resta un altro segnale attivo dopo la conferma, il CSV NON è svuotato →
    # niente CSV_CLEARED.
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"), _row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    jpath = _make(a, tmp_path)

    app_mod.App._process_confirmation(
        a, "Inter v Milan Esito finale Inter piazzata", {"csv_path": path})

    t = _types(jpath)
    assert "XTRADER_CONFIRMED" in t
    assert "CSV_CLEARED" not in t   # resta Roma v Lazio attiva


# ── _stop ────────────────────────────────────────────────────────────────────

def test_stop_sessione_attiva_journals_stop(make_app, app_mod, tmp_path):
    # STOP di una sessione ATTIVA → registrato (pendant del START).
    a = make_app(running=True, csv_path=None)
    a._async_stop_event = None
    jpath = _make(a, tmp_path)

    app_mod.App._stop(a)

    assert "STOP" in _types(jpath)


def test_stop_senza_sessione_non_journals_stop(make_app, app_mod, tmp_path):
    # Codex P2 (#233): `_on_close()` chiama `_stop()` anche a bridge mai avviato/già fermo →
    # nessuno STOP senza START (sequenza impossibile nel diario forense).
    a = make_app(running=False, csv_path=None)
    a._async_stop_event = None
    jpath = _make(a, tmp_path)

    app_mod.App._stop(a)

    assert "STOP" not in _types(jpath)


# ── _clear_stale_csv ─────────────────────────────────────────────────────────

def _stale_csv(path):
    from xtrader_bridge import csv_writer
    csv_writer.write_rows([{"EventName": "Vecchio v Segnale", "BetType": "PUNTA"}], path)


def test_clear_stale_startup_journals_crash_recovery(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    _stale_csv(path)
    a = make_app(config={"csv_path": path})
    jpath = _make(a, tmp_path)
    # #234: all'avvio __init__ rileva lo stato reale del CSV; qui c'è una riga stantia → flag True.
    a._csv_had_active_row = csv_writer.has_active_row(path)

    app_mod.App._clear_stale_csv(a, "all'avvio")

    assert _types(jpath) == ["CRASH_RECOVERY_CSV_CLEARED"]


def test_clear_stale_csv_mismatch_emerso_nel_log_del_bridge(make_app, app_mod, tmp_path):
    # #105 P2 (Codex): un file esistente NON-bridge (header diverso) non viene toccato (anti
    # data-loss) MA la diagnosi deve EMERGERE nel log del bridge — visibile a schermo e nel file
    # `bridge-*.log`, anche in un EXE --windowed dove lo stderr del logging.warning non c'è.
    p = tmp_path / "documento_utente.csv"
    p.write_text("colonnaA,colonnaB\nv1,v2\n", encoding="utf-8")
    a = make_app(config={"csv_path": str(p)})

    app_mod.App._clear_stale_csv(a, "all'avvio")

    assert any("non è un CSV del bridge" in m and "⚠️" in m for m in a.logs)  # diagnosi a log
    assert p.read_text(encoding="utf-8").startswith("colonnaA")               # file intatto
    assert "v1,v2" in p.read_text(encoding="utf-8")                           # contenuto preservato


def test_clear_stale_stop_journals_csv_cleared(make_app, app_mod, tmp_path):
    path = str(tmp_path / "segnali.csv")
    _stale_csv(path)
    a = make_app()
    jpath = _make(a, tmp_path)
    a._csv_had_active_row = True   # #234: la sessione aveva scritto una riga prima dello stop

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


def test_expire_clears_last_row_journals_csv_cleared(make_app, app_mod, monkeypatch, tmp_path):
    # Codex P2 (#233): se l'ULTIMA riga attiva scade (clear-delay), `_expire_tick` riporta il
    # CSV a solo header → deve loggare CSV_CLEARED, altrimenti il diario mostra un CSV_WRITTEN
    # senza il corrispondente clear ("cosa ha fatto" incompleto).
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)                  # scade a now=10
    a = make_app(csv_path=path, queue=q)
    jpath = _make(a, tmp_path)
    a._csv_had_active_row = True   # #234: il segnale era stato scritto prima della scadenza
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)   # oltre la scadenza

    app_mod.App._expire_tick(a, path)

    assert "CSV_CLEARED" in _types(jpath)


def test_expire_non_svuota_se_restano_righe_non_logga_clear(make_app, app_mod, monkeypatch, tmp_path):
    # Guard: se scade UNA riga ma ne resta un'altra attiva, il CSV NON è "svuotato" → niente
    # CSV_CLEARED (il clear è solo quando l'ultima riga sparisce).
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)                  # scade a now=10
    q.add(_row("Roma v Lazio"), now=995)                 # scade a now=1005 (ancora attiva a 1000)
    a = make_app(csv_path=path, queue=q)
    jpath = _make(a, tmp_path)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)

    app_mod.App._expire_tick(a, path)

    assert "CSV_CLEARED" not in _types(jpath)


# ── _manual_clear ────────────────────────────────────────────────────────────

def test_manual_clear_journals_csv_cleared(make_app, app_mod, tmp_path):
    # Codex P2 (#233): «Svuota CSV ora» riporta il CSV a solo header e rimuove le righe
    # attive → deve loggare CSV_CLEARED, altrimenti il diario mostra un CSV_WRITTEN senza il
    # clear manuale corrispondente (finché non arriva uno STOP/scadenza più tardi).
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q, running=True)
    jpath = _make(a, tmp_path)
    a._csv_had_active_row = True   # #234: il segnale era stato scritto prima dello svuotamento

    app_mod.App._manual_clear(a)

    assert "CSV_CLEARED" in _types(jpath)
    assert event_journal.read_events(jpath)[-1]["data"]["reason"] == "manual"


def test_manual_clear_write_failure_non_logga_clear(make_app, app_mod, monkeypatch, tmp_path):
    # Guard: se lo svuotamento fallisce (I/O), il CSV NON è stato ripulito → niente
    # CSV_CLEARED (il diario non deve affermare un clear mai avvenuto).
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"))
    a = make_app(csv_path=path, queue=q, running=True)
    jpath = _make(a, tmp_path)

    def _boom(_p):
        raise OSError("CSV lockato da XTrader (simulato)")

    monkeypatch.setattr(app_mod, "init_csv", _boom)

    app_mod.App._manual_clear(a)

    assert "CSV_CLEARED" not in _types(jpath)


# ── #234: fedeltà del diario (transizione reale riga→solo-header) ─────────────

def test_clear_stale_startup_header_only_no_false_recovery(make_app, app_mod, tmp_path):
    # #234 A: avvio pulito con CSV GIÀ a solo header → `clear_stale_csv` riscrive idempotente ma
    # nessuna riga è stata rimossa → NIENTE falso `CRASH_RECOVERY_CSV_CLEARED` nel diario.
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(path)                                 # CSV del bridge a SOLO header
    a = make_app(config={"csv_path": path})
    jpath = _make(a, tmp_path)
    a._csv_had_active_row = csv_writer.has_active_row(path)   # False: nessuna riga dati

    app_mod.App._clear_stale_csv(a, "all'avvio")

    assert _types(jpath) == []                                # nessun recovery spurio


def test_clear_helper_emette_solo_su_transizione_reale(make_app, app_mod, tmp_path):
    # #234 B (meccanismo): `_journal_csv_cleared_if_had_row` emette il clear SOLO se il CSV aveva una
    # riga (flag True), poi azzera il flag. È il meccanismo che copre il clear via `init_csv` di START
    # (e di ogni altro punto): `_start` è GUI/thread-coupled e non istanziabile headless, ma il suo
    # contributo nuovo è proprio questa chiamata all'helper.
    a = make_app()
    jpath = _make(a, tmp_path)

    a._csv_had_active_row = False
    app_mod.App._journal_csv_cleared_if_had_row(a, "CSV_CLEARED", reason="start")
    assert _types(jpath) == []                                # CSV già a solo header → niente clear

    a._csv_had_active_row = True
    app_mod.App._journal_csv_cleared_if_had_row(a, "CSV_CLEARED", reason="start")
    assert _types(jpath) == ["CSV_CLEARED"]                   # transizione reale → clear loggato
    assert a._csv_had_active_row is False                     # flag azzerato dopo l'emissione


def _raise_oserror(*_a, **_k):
    raise OSError("CSV lockato da XTrader (simulato)")


def test_confirmation_write_failure_logga_outcome_e_retry_pulisce(make_app, app_mod, monkeypatch, tmp_path):
    # #234 C: se la riscrittura post-conferma fallisce, l'outcome `XTRADER_*` va comunque registrato
    # (non perso nel retry); il CSV ha ancora la riga (flag resta True) e sarà il retry (`_expire_tick`)
    # a riportarlo a solo header e a loggare il clear.
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q, running=True)
    jpath = _make(a, tmp_path)
    a._csv_had_active_row = True

    # 1) la riscrittura post-conferma fallisce
    monkeypatch.setattr(app_mod, "write_rows", _raise_oserror)
    app_mod.App._process_confirmation(
        a, "Inter v Milan Esito finale Inter piazzata", {"csv_path": path})
    t1 = _types(jpath)
    assert "XTRADER_CONFIRMED" in t1            # outcome registrato NONOSTANTE il write fallito
    assert "CSV_CLEARED" not in t1              # il CSV ha ancora la riga (write fallita)
    assert a._csv_had_active_row is True

    # 2) il retry (scadenza) riesce → CSV tornato a solo header → clear loggato
    monkeypatch.setattr(app_mod, "write_rows", csv_writer.write_rows)
    app_mod.App._expire_tick(a, path)
    assert "CSV_CLEARED" in _types(jpath)


def test_expire_write_failure_poi_retry_logga_clear(make_app, app_mod, monkeypatch, tmp_path):
    # #234 D: se la scrittura durante la scadenza fallisce dopo aver rimosso l'ultima riga dalla coda,
    # nel retry `expired` è vuoto ma il CSV viene riportato a solo header → il clear va comunque loggato
    # (il vecchio gate `if expired:` lo perdeva).
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q, running=True)
    jpath = _make(a, tmp_path)
    a._csv_had_active_row = True
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)   # oltre la scadenza

    # 1) scadenza con write fallito: la coda rimuove lo scaduto ma il CSV resta indietro
    monkeypatch.setattr(app_mod, "write_rows", _raise_oserror)
    app_mod.App._expire_tick(a, path)
    assert "CSV_CLEARED" not in _types(jpath)   # write fallita: nessun clear ancora
    assert a._csv_had_active_row is True

    # 2) retry: `expired` ora è vuoto (già rimosso) ma il CSV viene riportato a solo header
    monkeypatch.setattr(app_mod, "write_rows", csv_writer.write_rows)
    app_mod.App._expire_tick(a, path)
    assert "CSV_CLEARED" in _types(jpath)
