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

import inspect
import threading
import time


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

    def __init__(self, *, fail, on_success):
        self.updater = _Updater(self, fail=fail)
        self.on_success = on_success
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
        """Registra lo shutdown dell'app (teardown)."""
        self.shutdown_calls += 1


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
    # niente sleep reale: il backoff non è il focus di questo test (lo è in #110/7)
    waits = []
    a._reconnect_wait = lambda delay: waits.append(delay)

    apps = []

    def _make_tg(index):
        # 1ª app: polling fallisce; 2ª app: polling ok → ferma il supervisor.
        return _TgApp(fail=(index == 0),
                      on_success=lambda: setattr(a, "_running", False))

    _install_builder(monkeypatch, app_mod, apps, _make_tg)

    app_mod.App._run_bot(a, {"bot_token": "x"}, 3)

    assert len(apps) == 2                              # ha ritentato dopo l'errore
    tg1 = apps[0]
    assert tg1.updater.start_polling_calls == 1        # l'errore è arrivato DAL polling
    # teardown REALE del vecchio updater prima del retry (no doppio poller):
    assert tg1.updater.stop_calls >= 1
    assert tg1.stop_calls >= 1 and tg1.shutdown_calls >= 1
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
    a._stop_event = threading.Event()
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    # backoff lungo: senza STOP, `_reconnect_wait` (REALE) bloccherebbe 30s.
    monkeypatch.setattr(app_mod.reconnect_policy, "effective_delay", lambda *a_, **k: 30.0)

    apps = []
    # polling SEMPRE fallito → il supervisor resta nel ciclo di backoff.
    _install_builder(monkeypatch, app_mod, apps, lambda index: _TgApp(fail=True, on_success=lambda: None))

    # Gate dello STOP sull'INGRESSO EFFETTIVO nel wait reale (review Codex): si avvolge
    # il VERO `_reconnect_wait` con un segnale `entered` emesso un attimo prima di
    # chiamarlo, così lo stopper attende di essere DENTRO il wait reale prima di settare
    # `_stop_event`. Senza questo, il gate su `_reconnect_attempt>=1` (incrementato PRIMA
    # del wait) potrebbe far settare lo STOP prima dell'attesa: una sleep ininterrompibile
    # che controlla l'evento una sola volta passerebbe lo stesso.
    real_wait = app_mod.App._reconnect_wait
    entered = threading.Event()

    def _wrapped_wait(delay):
        entered.set()
        return real_wait(a, delay)       # attesa REALE: `self._stop_event.wait(delay)`

    a._reconnect_wait = _wrapped_wait

    stop_at = {}

    def _stopper():
        if entered.wait(5.0):            # attende l'ingresso nel wait REALE
            a._running = False
            stop_at["t"] = time.monotonic()
            a._stop_event.set()

    th = threading.Thread(target=_stopper)
    th.start()
    app_mod.App._run_bot(a, {"bot_token": "x"}, 4)
    returned_at = time.monotonic()
    th.join()

    assert entered.is_set()              # è davvero entrato nel `_reconnect_wait` reale
    assert "t" in stop_at                # lo STOP è scattato mentre era DENTRO il wait
    # latenza di sblocco misurata DALLO STOP: deve essere quasi immediata (≪ 30s di
    # backoff). Soglia stretta: un'attesa ininterrompibile farebbe fallire il test.
    assert returned_at - stop_at["t"] < 1.0


def test_boot_clear_stale_csv_precede_lo_scheduling_auto_start(app_mod):
    """#110/1: guardia di REGRESSIONE sull'ordine in `App.__init__` — la pulizia del CSV
    stantio all'avvio (`_clear_stale_csv("all'avvio")`) deve precedere lo scheduling
    dell'auto-start (`_maybe_auto_start`). `__init__` non è istanziabile headless (apre
    Tk), quindi si ispeziona il SORGENTE reale del metodo: se un domani qualcuno
    schedulasse l'auto-start prima del cleanup, una riga stantia potrebbe sopravvivere
    fino all'auto-start e questo test fallirebbe (la matrice non resterebbe verde a torto)."""
    src = inspect.getsource(app_mod.App.__init__)
    i_clear = src.find('_clear_stale_csv("all')
    i_auto = src.find("_maybe_auto_start")
    assert i_clear != -1, "chiamata _clear_stale_csv(\"all'avvio\") non trovata in __init__"
    assert i_auto != -1, "scheduling _maybe_auto_start non trovato in __init__"
    assert i_clear < i_auto, "il cleanup del CSV all'avvio deve precedere l'auto-start"
