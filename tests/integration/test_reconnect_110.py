"""Test hard del ciclo di vita del listener (issue #110) — METODI REALI di `App`.

#110 è un secondo "Codex resilience/crash-recovery test plan", in larga parte
sovrapposto a #109: quasi tutta la "lista finale" è già coperta da #160/#161/#162
(drop_pending_updates, stale update, epoch/no-doppio-poller, rollback _process,
confirmation write-failure, manual-clear active-path, gate _running, daily atomico).

Qui si chiudono i due gap automatizzabili rimasti sul supervisor `App._run_bot`,
esercitando i collaboratori REALI (niente stub dell'hook di teardown):
- #110/6 — un errore TRANSITORIO **durante il polling** (`updater.start_polling`)
  → il VERO `_safe_shutdown_tg` chiude il vecchio updater (`updater.stop`/`stop`/
  `shutdown`) e azzera `_tg_app` PRIMA del retry (niente doppio poller) → backoff →
  RITENTA → alla riconnessione riuscita `_reconnect_attempt` torna a 0;
- #110/7 — STOP che arriva mentre il supervisor è GIÀ nel backoff (dentro il vero
  `_reconnect_wait`) sblocca SUBITO l'attesa (niente sleep ininterrompibile).

La classificazione transitorio/permanente è testata a parte (`test_reconnect_policy.py`):
qui `should_reconnect` è forzato per pilotare DETERMINISTICAMENTE il ramo di retry,
indipendentemente da `python-telegram-bot` (presente o meno nell'ambiente).
"""

import threading
import time


class _SignalingEvent(threading.Event):
    """`threading.Event` che segnala `entered` DALL'INTERNO di `wait()` (prima riga),
    così un test può sapere che il wait reale ha COMINCIATO a bloccare prima di settare
    lo STOP — senza la finestra di race del "set appena prima di chiamare il wait"."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()

    def wait(self, timeout=None):
        self.entered.set()
        return super().wait(timeout)


class _Updater:
    """Updater PTB finto: registra le chiamate; `start_polling` fallisce (errore
    transitorio dal polling) o segnala la connessione riuscita."""

    def __init__(self, app, *, fail):
        self._app = app
        self._fail = fail
        self.start_polling_calls = 0
        self.stop_calls = 0

    async def start_polling(self, **kwargs):
        """Simula il polling: alla 1ª connessione solleva un errore transitorio
        DAL POLLING; altrimenti segnala il successo (fa uscire il supervisor)."""
        self.start_polling_calls += 1
        if self._fail:
            raise type("NetworkError", (Exception,), {})("polling giù (simulato)")
        self._app.on_success()

    async def stop(self):
        """Registra l'arresto dell'updater (chiamato dal vero `_safe_shutdown_tg`)."""
        self.stop_calls += 1


class _TgApp:
    """App Telegram finta che registra initialize/start/stop/shutdown reali, così
    il test può verificare il CONTRATTO di teardown invece di uno stub no-op."""

    def __init__(self, *, fail, on_success, on_shutdown=None):
        self.updater = _Updater(self, fail=fail)
        self.on_success = on_success
        self._on_shutdown = on_shutdown
        self.init_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.shutdown_calls = 0

    def add_handler(self, h):
        """Riceve il MessageHandler (qui irrilevante: nessun update viene iniettato)."""

    async def initialize(self):
        """Inizializzazione riuscita (l'errore #110/6 arriva dal polling, non da qui)."""
        self.init_calls += 1

    async def start(self):
        """Avvio dell'app riuscito."""
        self.start_calls += 1

    async def stop(self):
        """Registra lo stop dell'app (teardown)."""
        self.stop_calls += 1

    async def shutdown(self):
        """Registra lo shutdown dell'app (teardown) ed emette l'evento d'ordine."""
        self.shutdown_calls += 1
        if self._on_shutdown is not None:
            self._on_shutdown()


def _install_builder(monkeypatch, app_mod, apps, make_tg):
    """Sostituisce `ApplicationBuilder`/`MessageHandler` con finti deterministici;
    ogni `build()` crea una nuova `_TgApp` (via `make_tg`) e la registra in `apps`."""
    def _factory():
        tg = make_tg(len(apps))
        apps.append(tg)

        class _B:
            def token(self, _t):
                return self

            def build(self):
                return tg
        return _B()

    monkeypatch.setattr(app_mod, "ApplicationBuilder", _factory)
    monkeypatch.setattr(app_mod, "MessageHandler", lambda *a_, **k: ("MH", a_, k))


def test_reconnect_lifecycle_chiude_il_vecchio_updater_e_ritenta(make_app, app_mod, monkeypatch):
    """#110/6: errore transitorio DAL POLLING → il vero `_safe_shutdown_tg` chiude il
    vecchio updater (stop/stop/shutdown) PRIMA del retry, poi la riconnessione riuscita
    azzera `_reconnect_attempt`. `_safe_shutdown_tg` NON è stubbato: si verifica il
    contratto reale di teardown (niente doppio poller)."""
    a = make_app()
    a._running = True
    a._listener_epoch = 3
    a._reconnect_attempt = 0
    # ramo "transitorio → riconnetti" forzato (classificazione testata altrove)
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    # Cattura lo SNAPSHOT del teardown NEL MOMENTO in cui inizia il backoff (review Codex):
    # quando `_reconnect_wait` viene chiamato, il vecchio updater/app DEVE essere GIÀ stato
    # chiuso (updater.stop + app.stop + app.shutdown), altrimenti il vecchio poller resterebbe
    # vivo durante l'attesa. Verificare i contatori solo a fine run non lo garantirebbe.
    waits = []
    teardown_at_backoff = {}
    apps = []

    def _wait(delay):
        tg1 = apps[0]
        teardown_at_backoff["updater_stop"] = tg1.updater.stop_calls
        teardown_at_backoff["app_stop"] = tg1.stop_calls
        teardown_at_backoff["app_shutdown"] = tg1.shutdown_calls
        waits.append(delay)

    a._reconnect_wait = _wait

    def _make_tg(index):
        # 1ª app: polling fallisce; 2ª app: polling ok → ferma il supervisor.
        return _TgApp(fail=(index == 0),
                      on_success=lambda: setattr(a, "_running", False))

    _install_builder(monkeypatch, app_mod, apps, _make_tg)

    app_mod.App._run_bot(a, {"bot_token": "x"}, 3)

    assert len(apps) == 2                              # ha ritentato dopo l'errore
    tg1 = apps[0]
    assert tg1.updater.start_polling_calls == 1        # l'errore è arrivato DAL polling
    # AL MOMENTO del backoff il vecchio updater/app era GIÀ stato chiuso (no doppio poller
    # durante l'attesa): updater.stop + app.stop + app.shutdown già avvenuti PRIMA del wait.
    assert teardown_at_backoff == {"updater_stop": 1, "app_stop": 1, "app_shutdown": 1}
    assert a._tg_app is apps[1]                        # `_tg_app` rimpiazzato (vecchio azzerato)
    assert len(waits) == 1 and waits[0] > 0            # ha atteso il backoff una volta
    assert a._reconnect_attempt == 0                   # reset dopo la riconnessione riuscita


def test_stop_durante_backoff_vivo_interrompe_subito(make_app, app_mod, monkeypatch):
    """#110/7: con STOP che arriva mentre il supervisor è GIÀ nel backoff (dentro il
    vero `_reconnect_wait`), l'attesa si sblocca SUBITO. Il polling fallisce sempre
    (resta in retry) e il backoff è forzato a 30s: solo lo STOP può far terminare
    `_run_bot` in fretta → l'attesa è davvero interrompibile dentro il loop reale."""
    a = make_app()
    a._running = True
    a._listener_epoch = 4
    a._reconnect_attempt = 0
    # `_stop_event` che segnala `entered` DALL'INTERNO di `wait()` (review Codex): lo
    # stopper attende che la wait REALE abbia COMINCIATO a bloccare prima di settare lo
    # STOP, eliminando la finestra di race del "set appena prima del wait".
    a._stop_event = _SignalingEvent()
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    # backoff lungo: senza STOP, `_reconnect_wait` (REALE) bloccherebbe 30s.
    monkeypatch.setattr(app_mod.reconnect_policy, "effective_delay", lambda *a_, **k: 30.0)

    apps = []
    # polling SEMPRE fallito → il supervisor resta nel ciclo di backoff.
    _install_builder(monkeypatch, app_mod, apps, lambda index: _TgApp(fail=True, on_success=lambda: None))

    # NB: NON si stubba `_reconnect_wait` → si usa il VERO, che chiama
    # `self._stop_event.wait(delay)` (cioè `_SignalingEvent.wait`).
    # Il supervisor gira in un THREAD daemon con join LIMITATO (review Codex): se
    # `_reconnect_wait` regredisce e non entra/onora `_stop_event`, il test FALLISCE
    # entro pochi secondi invece di appendere la CI in un retry infinito.
    result = {}

    def _run():
        app_mod.App._run_bot(a, {"bot_token": "x"}, 4)
        result["returned_at"] = time.monotonic()

    bot = threading.Thread(target=_run, daemon=True)
    bot.start()

    entered_ok = a._stop_event.entered.wait(5.0)   # la wait reale ha cominciato a bloccare?
    # In OGNI caso sblocca il supervisor (no thread/CI appesi), poi misura/verifica.
    a._running = False
    stop_at = time.monotonic()
    a._stop_event.set()
    bot.join(5.0)

    assert entered_ok, "regressione: il supervisor non è entrato nel `_reconnect_wait` reale"
    assert not bot.is_alive(), "regressione: `_run_bot` non è terminato dopo lo STOP (backoff non interrompibile)"
    assert "returned_at" in result
    # latenza di sblocco misurata DALLO STOP: quasi immediata (≪ 30s di backoff).
    assert result["returned_at"] - stop_at < 1.0


def test_stop_reale_sveglia_il_backoff(make_app, app_mod):
    """#110/7 (complemento): il VERO `App._stop` imposta `_stop_event` (oltre a `_running=False`).
    Insieme a `test_stop_durante_backoff_vivo_interrompe_subito` (che prova che il wait reale si
    sblocca su `_stop_event`), questo blinda l'intera catena: se una regressione togliesse
    `_stop_event.set()` da `_stop`, la STOP della GUI resterebbe appesa fino a fine backoff e
    questo test fallirebbe. Eseguito sul metodo reale, senza loop/coda attivi."""
    a = make_app()                       # _loop=None, _tg_app=None, _queue=None, _active_csv_path=None
    a._running = True
    a._stop_event = threading.Event()

    app_mod.App._stop(a)

    assert a._stop_event.is_set()        # _stop sveglia un eventuale `_reconnect_wait`
    assert a._running is False
    assert a._active_csv_path is None


def test_maybe_auto_start_gating_non_parte_se_disabilitato_chiusura_o_running(make_app, app_mod):
    """#110/2 (glue runtime): il VERO `App._maybe_auto_start` NON chiama `_start` quando
    l'auto-start è disabilitato in config, o quando la finestra si sta chiudendo
    (`_closing`), o se il bridge è già `_running`. Esercita il gating reale del callback
    (consumato a ogni tick: `_autostart_after_id` torna None). NB: il gate fine token/chat
    vive dentro `_start` (fortemente accoppiato alla GUI) → vedi #110/2 PARTIAL + autostart unit."""
    a = make_app()
    started = []
    a._start = lambda auto=False: started.append(auto)

    # 1) config senza auto-start abilitato → non parte
    a._config = {}
    a._running = False
    a._closing = False
    a._autostart_after_id = "AFTER-1"
    app_mod.App._maybe_auto_start(a)
    assert started == []
    assert a._autostart_after_id is None      # callback consumato

    # 2) auto-start abilitato ma finestra in chiusura → non parte (gate `_closing`)
    a._config = {"auto_start_listener": True}
    a._closing = True
    app_mod.App._maybe_auto_start(a)
    assert started == []

    # 3) auto-start abilitato ma bridge già attivo → non parte (gate `_running`)
    a._closing = False
    a._running = True
    app_mod.App._maybe_auto_start(a)
    assert started == []


def test_epoch_cambiato_dopo_fallimento_non_ritenta(make_app, app_mod, monkeypatch):
    """#110/8/14: un nuovo START (epoch che CAMBIA) mentre un vecchio supervisor è in
    backoff dopo un fallimento del poller → il vecchio supervisor NON deve ritentare
    (niente doppio poller). Si guida `_run_bot` con epoch 9: il primo polling fallisce,
    poi durante il backoff l'epoch corrente diventa 99 (nuovo START) → `_is_current()` è
    falso e il supervisor esce senza costruire un secondo poller."""
    a = make_app()
    a._running = True
    a._listener_epoch = 9
    a._reconnect_attempt = 0
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)

    apps = []
    _install_builder(monkeypatch, app_mod, apps,
                     lambda index: _TgApp(fail=True, on_success=lambda: None))

    # Durante il backoff "arriva" un nuovo START: l'epoch corrente cambia rispetto a
    # quello (9) con cui gira questo supervisor.
    a._reconnect_wait = lambda delay: setattr(a, "_listener_epoch", 99)

    app_mod.App._run_bot(a, {"bot_token": "x"}, 9)

    assert len(apps) == 1                 # nessun secondo poller costruito dal vecchio supervisor
    assert a._listener_epoch == 99        # l'epoch è stato invalidato da un nuovo START


def test_reconnect_journals_reconnect_event(make_app, app_mod, monkeypatch, tmp_path):
    """#230 (CodeRabbit): ogni tentativo di riconnessione registra un evento `RECONNECT` nel
    diario. Riusa il lifecycle #110/6 (1º polling fallisce → backoff → 2º ok) sul vero
    `_run_bot` e verifica che il ledger contenga `RECONNECT` (best-effort, non blocca il
    supervisor: il teardown/retry avviene comunque)."""
    from xtrader_bridge import event_journal
    a = make_app()
    a._running = True
    a._listener_epoch = 3
    a._reconnect_attempt = 0
    a._journal_path = str(tmp_path / "event_journal.jsonl")
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    a._reconnect_wait = lambda delay: None          # niente attesa reale: il test resta rapido

    apps = []
    _install_builder(monkeypatch, app_mod, apps,
                     lambda index: _TgApp(fail=(index == 0),
                                          on_success=lambda: setattr(a, "_running", False)))

    app_mod.App._run_bot(a, {"bot_token": "x"}, 3)

    assert len(apps) == 2                            # ha ritentato dopo l'errore transitorio
    types = [e["type"] for e in event_journal.read_events(a._journal_path)]
    assert "RECONNECT" in types                      # il tentativo di riconnessione è nel diario
