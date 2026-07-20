"""Test hard di resilienza (issue #109) sui gap NON ancora coperti, eseguiti sui
METODI REALI di `App` tramite l'harness headless (`tests/integration/conftest.py`).

Punti coperti qui:
- #109/12 — errore NON recuperabile del listener (es. token invalido) → `_stop`
  schedulato, nessun retry (niente poller zombie);
- #109/14 — epoch: un supervisor con epoch STALE (vecchio START) esce senza
  (ri)costruire un poller → niente doppio poller dopo un nuovo START;
- #109/16 — `_expire_tick` vs `_process` CONCORRENTI sotto `_queue_lock`: nessuna
  eccezione, CSV sempre valido (header intatto), nessuna corruzione;
- #109/25 — un'azione manuale (STOP/AVVIA) ANNULLA un auto-start pendente
  (`_cancel_pending_autostart`).

Gli altri punti #109 sono già coperti altrove (vedi `docs/audit/archive/resilience_109_matrix.md`).
"""

import csv
import threading

from xtrader_bridge import reconnect_policy, safety_guard, signal_dedupe, signal_queue


# ── fake PTB (telegram può non essere installato in CI headless) ───────────────

class _FakeUpdater:
    async def start_polling(self, **kwargs):
        pass

    async def stop(self):
        pass


class _FakeTgApp:
    def __init__(self, *, fail_init=False):
        self.updater = _FakeUpdater()
        self._fail_init = fail_init

    def add_handler(self, h):
        pass

    def add_error_handler(self, h):
        # AC-M1 #114: `_run_bot` registra ora un error handler PTB (qui irrilevante).
        pass

    async def initialize(self):
        if self._fail_init:
            # Errore PERMANENTE simulato (es. token invalido): non è un'eccezione
            # transitoria di rete → reconnect_policy NON deve ritentare.
            raise RuntimeError("token invalido (simulato)")

    async def start(self):
        pass

    async def stop(self):
        pass

    async def shutdown(self):
        pass


# ── #109/12: errore non recuperabile → _stop, nessun retry ────────────────────

def test_errore_non_recuperabile_ferma_senza_retry(make_app, app_mod, monkeypatch):
    a = make_app()
    a._running = True
    a._listener_epoch = 7
    stops = []
    a._stop = lambda: stops.append(True)
    builds = {"n": 0}

    def _factory():
        builds["n"] += 1

        class _B:
            def token(self, _t):
                return self

            def build(self):
                return _FakeTgApp(fail_init=True)
        return _B()

    monkeypatch.setattr(app_mod, "ApplicationBuilder", _factory)
    monkeypatch.setattr(app_mod, "MessageHandler", lambda *a_, **k: ("MH", a_, k))
    # Sanity: l'errore simulato è classificato come NON recuperabile dalla policy pura.
    assert reconnect_policy.should_reconnect(True, RuntimeError("token invalido (simulato)")) is False

    app_mod.App._run_bot(a, {"bot_token": "x"}, 7)

    assert stops == [True]          # _stop schedulato esattamente una volta
    assert builds["n"] == 1         # un solo tentativo: nessun retry su errore permanente


# ── #109/14: epoch stale → nessun secondo poller ──────────────────────────────

def test_epoch_stale_non_avvia_un_secondo_poller(make_app, app_mod, monkeypatch):
    a = make_app()
    a._running = True
    a._listener_epoch = 5          # epoch CORRENTE = 5
    builds = {"n": 0}

    def _factory():
        builds["n"] += 1

        class _B:
            def token(self, _t):
                return self

            def build(self):
                return _FakeTgApp()
        return _B()

    monkeypatch.setattr(app_mod, "ApplicationBuilder", _factory)

    # Un supervisor di un vecchio START (epoch 4) non è più corrente → deve uscire
    # SENZA costruire un poller (altrimenti due poller sulla stessa chat).
    app_mod.App._run_bot(a, {"bot_token": "x"}, 4)

    assert builds["n"] == 0


# ── #109/16: _expire_tick vs _process concorrenti sotto _queue_lock ───────────

def _row(name):
    return {"EventName": name, "MarketName": "Esito finale",
            "SelectionName": name.split(" v ")[0], "Price": "1,90", "BetType": "PUNTA"}


def test_expire_tick_vs_process_concorrenti_non_corrompono_csv(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(path)
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=0.001)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(dedupe_window=1, max_per_minute=100000),
                 daily=safety_guard.DailyLimiter(max_per_day=100000))
    # resolve_row reale isolato: ogni messaggio è piazzabile (varia per non duplicare).
    monkeypatch.setattr(app_mod.signal_router, "resolve_row",
                        lambda text, route, chat_id=None, **kw: app_mod.signal_router.RouteResult(row=_row(text)))

    errors = []

    def _producer():
        try:
            for i in range(300):
                app_mod.App._process(a, f"sig-{i}", {"csv_path": path, "dry_run": False}, chat_id="1")
        except Exception as ex:   # noqa: BLE001 — registra per assert, non nascondere
            errors.append(("process", repr(ex)))

    def _expirer():
        try:
            for _ in range(300):
                app_mod.App._expire_tick(a, path)
        except Exception as ex:   # noqa: BLE001
            errors.append(("expire", repr(ex)))

    t1, t2 = threading.Thread(target=_producer), threading.Thread(target=_expirer)
    t1.start(); t2.start(); t1.join(); t2.join()

    assert errors == []           # nessuna eccezione sotto contesa
    # CSV sempre valido: header esatto e 0/1 righe attive (OVERWRITE_LAST), niente corruzione.
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        body = [r for r in reader if r]
    assert header == list(csv_writer.CSV_HEADER)
    assert len(body) <= 1
    assert len(q.active_rows()) <= 1


# ── #109/25: azione manuale annulla l'auto-start pendente ─────────────────────

def test_cancel_pending_autostart_annulla_il_callback(make_app, app_mod):
    a = make_app()
    cancelled = []
    a.after_cancel = lambda cid: cancelled.append(cid)
    a._autostart_after_id = "AFTER-123"

    app_mod.App._cancel_pending_autostart(a)
    assert cancelled == ["AFTER-123"]      # callback ritardato annullato
    assert a._autostart_after_id is None   # niente auto-start residuo

    # Idempotente: senza pendente non richiama after_cancel.
    app_mod.App._cancel_pending_autostart(a)
    assert cancelled == ["AFTER-123"]
