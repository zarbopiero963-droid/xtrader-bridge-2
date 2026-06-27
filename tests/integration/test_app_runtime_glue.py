"""Test hard della GLUE runtime di `App` (issue #108 P1) — eseguono i METODI REALI.

Copre i punti che l'audit #108 segnalava come «runtime app.py glue: da rafforzare»
e prioritari (P1), prima testabili solo a mano su Windows:

- `_process`: scrittura riuscita (accoda + scrive), fallimento con ROLLBACK completo
  (segnale ritentabile), gate `_running` (STOP in corso → non scrive), duplicato che
  non riscrive ma persiste lo stato;
- `_process_confirmation`: conferma rimuove il segnale e riscrive il CSV; fallimento
  scrittura → segnale già rimosso + retry BREVE programmato; gate `_running` (no-op);
- `_expire_tick`: rimuove gli scaduti e svuota il CSV; fallimento → retry programmato;
  gate `_running` (non riscrive dopo lo STOP);
- `_manual_clear`: in esecuzione svuota il CSV ATTIVO della sessione, NON il path del
  campo GUI (anti riga orfana); fallimento I/O non azzera la coda;
- `_stop`: svuota coda + CSV ATTIVO della sessione (non il path GUI cambiato).

L'harness (`tests/integration/conftest.py`) istanzia `App` headless con collaboratori
REALI; qui si iniettano solo i guasti (`write_rows`/`init_csv` che sollevano) e, per
isolare la glue di scrittura dal parser (coperto altrove), un `resolve_row` che ritorna
un `RouteResult` reale.
"""

import csv

import pytest

from xtrader_bridge import safety_guard, signal_dedupe, signal_queue


# ── helper ────────────────────────────────────────────────────────────────────

def _row(name, selection=None, price="1,90"):
    # SelectionName realistica (squadra di casa) così il lettore conferme può associare
    # l'esito XTrader al segnale (EventName + Selection), come nei messaggi reali.
    sel = selection if selection is not None else name.split(" v ")[0]
    return {"EventName": name, "MarketName": "Esito finale",
            "SelectionName": sel, "Price": price, "BetType": "PUNTA"}


def _events_in_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r["EventName"] for r in csv.DictReader(f)]


def _patch_resolve(monkeypatch, app_mod, row):
    """Forza `signal_router.resolve_row` a un esito REALE (RouteResult): isola la glue
    di scrittura dal parser, già coperto da test dedicati."""
    rr = app_mod.signal_router.RouteResult(row=row)
    monkeypatch.setattr(app_mod.signal_router, "resolve_row", lambda *a, **k: rr)


def _spy_writer(monkeypatch, app_mod, *, fail=False):
    """Avvolge `app.write_rows` per CONTARE le scritture; con `fail=True` solleva sempre
    (CSV lockato), così la write atomica non tocca il file precedente."""
    from xtrader_bridge import csv_writer
    calls = {"n": 0}

    def _w(rows, path):
        calls["n"] += 1
        if fail:
            raise OSError("CSV lockato (simulato)")
        csv_writer.write_rows(rows, path)

    monkeypatch.setattr(app_mod, "write_rows", _w)
    return calls


# ── _process ───────────────────────────────────────────────────────────────────

def test_process_write_success_accoda_e_scrive(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1")

    assert _events_in_csv(path) == ["Inter v Milan"]          # CSV scritto (1 riga)
    assert [r["EventName"] for r in q.active_rows()] == ["Inter v Milan"]
    assert a.guard_saves                                      # stato guardrail persistito
    assert (path, None) in a.expiry_calls                     # scadenza programmata


def test_process_write_failure_rollback_e_ritentabile(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    a = make_app(csv_path=path, queue=q, tracker=tracker,
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))
    _spy_writer(monkeypatch, app_mod, fail=True)

    app_mod.App._process(a, "msg-x", {"csv_path": path, "dry_run": False}, chat_id="1")

    # Coda ripristinata: nessuna riga stantia attiva dopo una write fallita.
    assert q.active_rows() == []
    # Dedupe ripristinato: lo STESSO messaggio è ritentabile (non DUPLICATE).
    assert tracker.register("msg-x").status != signal_dedupe.DUPLICATE
    # La glue programma comunque la scadenza (i segnali ripristinati devono scadere).
    assert (path, None) in a.expiry_calls
    assert any("Scrittura CSV fallita" in m for m in a.logs)


def test_process_gate_running_false_non_scrive(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q, running=False,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1")

    assert spy["n"] == 0                      # STOP in corso: nessuna scrittura
    assert q.active_rows() == []


def test_process_gate_epoch_superato_non_scrive(make_app, app_mod, monkeypatch, tmp_path):
    """#191 P1 (round 3): un callback del VECCHIO updater non deve scrivere se la sessione
    listener è cambiata (STOP→START → epoch avanzato) anche con `_running=True`. Con
    `epoch=1` ma `_listener_epoch=2`, `_process` NON scrive (gate d'ingresso `_epoch_current`).

    Fail-first: sul vecchio codice `_process` ignorava l'epoch → scriveva (running True)."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    a._listener_epoch = 2                      # un nuovo START è già intervenuto
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1", epoch=1)

    assert spy["n"] == 0                       # sessione superata: nessuna scrittura
    assert q.active_rows() == []


def test_process_epoch_cambia_durante_il_processo_non_scrive(make_app, app_mod, monkeypatch, tmp_path):
    """#191 P1 (round 3) — TOCTOU sotto il lock: l'epoch coincide all'INGRESSO (passa il gate),
    poi un STOP→START avanza l'epoch PRIMA della scrittura. Il ricontrollo sotto `_queue_lock`
    deve impedire la scrittura con la cfg della vecchia sessione.

    Si simula il cambio epoch col primo `self.after` di `_process` (eseguito subito
    dall'harness, dopo il gate d'ingresso e prima del lock di scrittura).

    Fail-first: senza il ricontrollo sotto il lock, `_process` scrive (gate d'ingresso già
    passato con epoch=1)."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    a._listener_epoch = 1                      # coincide all'ingresso → il gate iniziale passa
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    # Un nuovo START avanza l'epoch DOPO il gate d'ingresso ma PRIMA del lock di scrittura:
    # lo si aggancia al primo `after` invocato da `_process` (bump "received"), che l'harness
    # esegue immediatamente. Si ripristina `after` subito dopo per non riavanzare ad ogni call.
    orig_after = a.after

    def _after_then_bump_epoch(delay=None, func=None, *x, **k):
        a._listener_epoch = 2                  # STOP→START intervenuto a metà processo
        a.after = orig_after
        return orig_after(delay, func, *x, **k)

    a.after = _after_then_bump_epoch

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1", epoch=1)

    assert spy["n"] == 0                       # ricontrollo sotto il lock: nessuna scrittura
    assert q.active_rows() == []               # coda non mutata (segnale resta ritentabile)


def test_process_duplicato_non_riscrive_ma_persiste(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))
    spy = _spy_writer(monkeypatch, app_mod, fail=False)

    cfg = {"csv_path": path, "dry_run": False}
    app_mod.App._process(a, "stesso", cfg, chat_id="1")
    app_mod.App._process(a, "stesso", cfg, chat_id="1")   # duplicato

    assert spy["n"] == 1                       # la seconda volta NON riscrive
    assert _events_in_csv(path) == ["Inter v Milan"]
    assert len(a.guard_saves) >= 2             # stato persistito anche sull'esito non-WRITE


# ── _process_confirmation ───────────────────────────────────────────────────────

def _queue_with(*rows):
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    for i, r in enumerate(rows):
        q.add(r, now=1000 + i)
    return q


def test_confirmation_conferma_rimuove_e_riscrive(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"), _row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)

    app_mod.App._process_confirmation(a, "Inter v Milan Esito finale Inter piazzata",
                                      {"csv_path": path})

    assert [r["EventName"] for r in q.active_rows()] == ["Roma v Lazio"]
    assert _events_in_csv(path) == ["Roma v Lazio"]
    assert a.expiry_calls and a.expiry_calls[-1][0] == path


def test_confirmation_write_failure_segnale_rimosso_e_retry_breve(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"), _row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    _spy_writer(monkeypatch, app_mod, fail=True)

    app_mod.App._process_confirmation(a, "Inter v Milan Esito finale Inter piazzata",
                                      {"csv_path": path})

    # Il segnale è già fuori dalla coda; il CSV (write fallita) resta indietro → retry BREVE.
    assert [r["EventName"] for r in q.active_rows()] == ["Roma v Lazio"]
    assert (path, app_mod._WRITE_RETRY_DELAY) in a.expiry_calls
    assert any("dopo conferma" in m for m in a.logs)


def test_confirmation_gate_running_false_e_no_op(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q, running=False)

    app_mod.App._process_confirmation(a, "Roma v Lazio Esito finale Roma piazzata",
                                      {"csv_path": path})

    assert len(q.active_rows()) == 1               # callback tardivo: coda non mutata
    assert _events_in_csv(path) == ["Roma v Lazio"]
    assert a.expiry_calls == []


def test_confirmation_gate_epoch_superato_e_no_op(make_app, app_mod, tmp_path):
    """#191 P1 (round 3): una conferma del VECCHIO updater non deve rimuovere/riscrivere se la
    sessione listener è cambiata (epoch avanzato) anche con `_running=True`. Con `epoch=1` ma
    `_listener_epoch=2`, `_process_confirmation` è no-op (coda e CSV intatti, segnale ritentabile).

    Fail-first: sul vecchio codice ignorava l'epoch → confermava e riscriveva (running True)."""
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    a._listener_epoch = 2                          # un nuovo START è già intervenuto

    app_mod.App._process_confirmation(a, "Roma v Lazio Esito finale Roma piazzata",
                                      {"csv_path": path}, epoch=1)

    assert len(q.active_rows()) == 1               # sessione superata: coda non mutata
    assert _events_in_csv(path) == ["Roma v Lazio"]
    assert a.expiry_calls == []


# ── _expire_tick ────────────────────────────────────────────────────────────────

def test_expire_tick_rimuove_scaduti_e_svuota_csv(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)            # scade a now=10
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)   # ben oltre la scadenza

    app_mod.App._expire_tick(a, path)

    assert q.is_empty()
    assert _events_in_csv(path) == []              # CSV riportato a solo header
    # coda vuota → nessuna riprogrammazione
    assert a.expiry_calls == []


def test_expire_tick_write_failure_schedula_retry(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)
    _spy_writer(monkeypatch, app_mod, fail=True)

    app_mod.App._expire_tick(a, path)

    assert (path, app_mod._WRITE_RETRY_DELAY) in a.expiry_calls
    assert any("scadenza" in m.lower() for m in a.logs)


def test_expire_tick_gate_running_false_non_riscrive(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q, running=False)
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)

    app_mod.App._expire_tick(a, path)

    assert spy["n"] == 0                            # STOP in corso: nessuna riscrittura
    assert _events_in_csv(path) == ["Inter v Milan"]   # CSV intatto


# ── _manual_clear ───────────────────────────────────────────────────────────────

def test_manual_clear_running_usa_active_path_non_gui(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    active = str(tmp_path / "attivo.csv")
    gui = str(tmp_path / "gui.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    csv_writer.write_rows([_row("Roma v Lazio")], gui)
    a = make_app(csv_path=active, queue=q, gui_csv=gui)   # GUI punta a un path DIVERSO

    app_mod.App._manual_clear(a)

    assert _events_in_csv(active) == []                  # svuotato il CSV ATTIVO
    assert _events_in_csv(gui) == ["Roma v Lazio"]       # il path GUI NON è toccato
    assert q.is_empty()


def test_manual_clear_write_failure_non_svuota_coda(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    active = str(tmp_path / "attivo.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    a = make_app(csv_path=active, queue=q)
    monkeypatch.setattr(app_mod, "init_csv",
                        lambda p: (_ for _ in ()).throw(OSError("lockato")))

    app_mod.App._manual_clear(a)

    assert len(q.active_rows()) == 1                      # I/O fallito: coda NON azzerata
    assert a.expiry_calls and a.expiry_calls[-1][0] == active   # riprogramma la pulizia
    assert any("Svuotamento CSV fallito" in m for m in a.logs)


# ── _stop ───────────────────────────────────────────────────────────────────────

def test_stop_svuota_coda_e_csv_attivo_non_gui(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    active = str(tmp_path / "attivo.csv")
    gui = str(tmp_path / "gui.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    csv_writer.write_rows([_row("Roma v Lazio")], gui)
    a = make_app(csv_path=active, queue=q, gui_csv=gui, capture_schedule=False)
    a._expire_timer = None

    app_mod.App._stop(a)

    assert q.is_empty()                                  # coda in memoria svuotata
    assert _events_in_csv(active) == []                  # CSV ATTIVO svuotato (solo header)
    assert _events_in_csv(gui) == ["Roma v Lazio"]       # path GUI cambiato NON toccato
    assert a._active_csv_path is None
    assert a._running is False


def test_stop_non_sottomette_coroutine_fire_and_forget_al_loop(
        make_app, app_mod, monkeypatch, tmp_path):
    """#184 H5: con una sessione viva (`_loop` + `_tg_app` presenti) `_stop` NON deve
    fare fire-and-forget di `updater.stop()`/`stop()` sul loop con
    `run_coroutine_threadsafe`. Quelle coroutine non vengono mai attese e `loop.close()`
    nel supervisor le scarta ("Event loop is closed", eccezioni silenziate, doppio stop
    dell'updater). Lo shutdown autorevole è IN-loop (`_async_run`, dopo che
    `_is_current()` diventa False). `_stop` deve solo segnalare lo stop
    (`_running=False`, `_stop_event`) e gestire coda/CSV.

    Fail-first: sul vecchio codice `submitted` conterrebbe 2 coroutine."""
    from unittest.mock import MagicMock
    from xtrader_bridge import csv_writer

    active = str(tmp_path / "attivo.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    a = make_app(csv_path=active, queue=q, capture_schedule=False)
    a._expire_timer = None
    # Sessione viva: loop non-None e app Telegram con updater.stop()/stop(). Sul VECCHIO
    # codice `_stop` qui sottometterebbe due coroutine fire-and-forget al loop.
    a._loop = object()
    a._tg_app = MagicMock()
    submitted = []
    monkeypatch.setattr(app_mod.asyncio, "run_coroutine_threadsafe",
                        lambda coro, loop: submitted.append(coro))

    app_mod.App._stop(a)

    assert submitted == []            # nessuna coroutine fire-and-forget (regressione H5)
    assert a._stop_event.is_set()     # ma lo stop È segnalato: il supervisor esce e chiude in-loop
    assert a._running is False
    assert q.is_empty()               # coda/CSV gestiti come sempre
    assert _events_in_csv(active) == []


def test_stop_sveglia_attesa_in_loop_via_call_soon_threadsafe(make_app, app_mod, tmp_path):
    """#184 H5 / Codex #191: con una sessione viva `_stop` sveglia SUBITO l'attesa in-loop di
    `_async_run` settando `_async_stop_event` tramite `call_soon_threadsafe` (dal thread GUI).
    Così l'updater viene fermato promptamente — niente finestra di ~1s in cui il vecchio poller
    resta attivo — restando un percorso atteso in-loop (no coroutine scartate da `loop.close`).

    Fail-first: sul vecchio codice `_stop` non tocca alcun evento in-loop (`scheduled` resta vuoto)."""
    from xtrader_bridge import csv_writer

    active = str(tmp_path / "attivo.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    a = make_app(csv_path=active, queue=q, capture_schedule=False)
    a._expire_timer = None

    scheduled = []

    class _FakeLoop:
        def call_soon_threadsafe(self, fn, *args):
            scheduled.append(fn)
            fn(*args)                 # il loop processa subito il callback (simulazione)

    class _Evt:
        def __init__(self):
            self._set = False

        def set(self):
            self._set = True

        def is_set(self):
            return self._set

    evt = _Evt()
    a._loop = _FakeLoop()
    a._async_stop_event = evt

    app_mod.App._stop(a)

    assert len(scheduled) == 1        # svegliato via call_soon_threadsafe (thread-safe dal GUI)
    assert evt.is_set()               # l'attesa in-loop di _async_run è stata svegliata
    assert a._running is False
