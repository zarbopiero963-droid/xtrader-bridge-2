"""Test hard del listener Telegram (issue #108 P1 «Telegram listener mocked»).

L'audit #108 segnalava che NON c'era test automatico del listener reale/mocked dentro
`App._run_bot`: la closure `_handle` non era esercitata in CI, quindi non si verificava
che gli update Telegram fossero instradati con la stessa semantica della logica pura.

Qui si guida `App._run_bot` con un `ApplicationBuilder` FINTO (PTB non è installato in
CI): si cattura sia il MessageHandler registrato sia i kwargs di `start_polling`, poi si
invoca il VERO `_handle` con update finti e si verifica l'instradamento:

- `start_polling(allowed_updates=["message","channel_post"], drop_pending_updates=True)`
  — niente segnali vecchi a (ri)connessione, e i channel post sono ammessi;
- chat ammessa → `_process` (e NON `_process_confirmation`);
- chat notifiche XTrader → `_process_confirmation` (e NON `_process`);
- chat non ammessa → nessuna delle due;
- `channel_post` trattato come `message`;
- messaggio troppo vecchio (arretrato post-outage) → ignorato.

La SEMANTICA di `decide()` è coperta a parte (`test_telegram_dispatch.py`): qui si testa
che la GLUE del listener la usi e dispatci correttamente. `should_process` (che richiede
un parser su disco) è forzato a True solo per pilotare il ramo PROCESS.
"""

import asyncio
import time
import types

import pytest


# ── fake PTB minimale ────────────────────────────────────────────────────────

class _FakeUpdater:
    def __init__(self, on_poll):
        self.calls = {}
        self._on_poll = on_poll

    async def start_polling(self, **kwargs):
        self.calls["start_polling"] = kwargs
        self._on_poll()          # fa uscire SUBITO il while _is_current() (no sleep, no hang)

    async def stop(self):
        self.calls["stop"] = True


class _FakeTgApp:
    def __init__(self, on_poll):
        self.updater = _FakeUpdater(on_poll)
        self.handlers = []

    def add_handler(self, h):
        self.handlers.append(h)

    async def initialize(self):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    async def shutdown(self):
        pass


def _msg(chat_id, text, ts):
    return types.SimpleNamespace(
        chat_id=chat_id, text=text, caption=None,
        date=types.SimpleNamespace(timestamp=lambda: ts))


def _update(msg, *, channel=False):
    if channel:
        return types.SimpleNamespace(message=None, channel_post=msg)
    return types.SimpleNamespace(message=msg, channel_post=None)


def _drive_run_bot(make_app, app_mod, monkeypatch, config, session_cfg=None):
    """Esegue il VERO `_run_bot` con un builder finto; ritorna (app, fake_tg_app).

    `config` è la config VIVA (`self._config`, usata per instradamento/parsing); `session_cfg`
    è lo SNAPSHOT a START (2º arg di `_run_bot`, usato per ESECUZIONE: freschezza, coda, CSV).
    Di default lo snapshot porta solo il token (max_signal_age/clear_delay assenti → default)."""
    a = make_app(config=config)
    a._running = True
    a._listener_epoch = 1

    captured = {}

    def _on_poll():
        a._running = False       # subito dopo start_polling: _is_current() diventa False

    def _builder_factory():
        tg = _FakeTgApp(_on_poll)
        captured["tg"] = tg

        class _B:
            def token(self, _t):
                return self

            def build(self):
                return tg
        return _B()

    monkeypatch.setattr(app_mod, "ApplicationBuilder", _builder_factory)
    # Forza MessageHandler allo stub-tuple anche quando PTB è installato (es. job CI):
    # così il dispatch è deterministico e indipendente dalla versione di PTB (niente
    # dipendenza da attributi interni come `.callback`).
    monkeypatch.setattr(app_mod, "MessageHandler", lambda *a, **k: ("MessageHandler", a, k))
    # _handle dispatcha a questi: shadowati per CATTURARE l'instradamento (la logica di
    # _process/_process_confirmation è testata in test_app_runtime_glue.py).
    a._process = lambda *args, **kw: a.processed.append((args, kw))
    a._process_confirmation = lambda *args, **kw: a.confirmations.append((args, kw))

    app_mod.App._run_bot(a, session_cfg or {"bot_token": "x"}, 1)
    # `_on_poll` ha messo `_running=False` solo per far uscire `_run_bot` (no hang). Per
    # esercitare `_handle` nella condizione REALE — sessione attiva e CORRENTE (stesso epoch
    # con cui `_run_bot` è stato avviato) — si ripristina lo stato attivo. Senza, il gate
    # fail-closed `if not _is_current()` (Codex #191 P1) bloccherebbe ogni dispatch.
    a._running = True
    a._listener_epoch = 1
    return a, captured["tg"]


def _handle_of(tg):
    assert tg.handlers, "nessun handler registrato"
    h = tg.handlers[0]
    # Telegram ASSENTE (CI headless di default): MessageHandler è lo stub finto del
    # conftest, un tuple ("MessageHandler", (filters.ALL, _handle), {}).
    if isinstance(h, tuple):
        return h[1][1]
    # Telegram INSTALLATO (es. job CI con python-telegram-bot): MessageHandler è quello
    # vero di PTB, che conserva la callback in `.callback`.
    return h.callback


# ── test ─────────────────────────────────────────────────────────────────────

CFG = {"chat_id": "111", "xtrader_notification_chat_id": "999"}


def test_start_polling_scarta_arretrati_e_ammette_channel_post(make_app, app_mod, monkeypatch):
    _a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    kwargs = tg.updater.calls["start_polling"]
    assert kwargs["drop_pending_updates"] is True
    assert kwargs["allowed_updates"] == ["message", "channel_post"]


def test_chat_ammessa_instrada_a_process(make_app, app_mod, monkeypatch):
    # Forza should_process=True per pilotare il ramo PROCESS senza un parser su disco.
    monkeypatch.setattr(app_mod.signal_router, "should_process", lambda *a, **k: True)
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    handle = _handle_of(tg)

    asyncio.run(handle(_update(_msg("111", "P.Bet. segnale", time.time())), None))

    assert len(a.processed) == 1
    assert a.confirmations == []
    assert a.processed[0][1].get("chat_id") == "111"   # chat di origine inoltrata


def test_chat_notifiche_instrada_a_conferma(make_app, app_mod, monkeypatch):
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    handle = _handle_of(tg)

    asyncio.run(handle(_update(_msg("999", "Inter v Milan Inter piazzata", time.time())), None))

    assert len(a.confirmations) == 1
    assert a.processed == []


def test_chat_non_ammessa_non_instrada_nulla(make_app, app_mod, monkeypatch):
    # should_process REALE: una chat non configurata non è ammessa → niente PROCESS.
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    handle = _handle_of(tg)

    asyncio.run(handle(_update(_msg("222", "qualcosa", time.time())), None))

    assert a.processed == []
    assert a.confirmations == []


def test_channel_post_trattato_come_message(make_app, app_mod, monkeypatch):
    monkeypatch.setattr(app_mod.signal_router, "should_process", lambda *a, **k: True)
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    handle = _handle_of(tg)

    asyncio.run(handle(_update(_msg("111", "segnale via canale", time.time()), channel=True), None))

    assert len(a.processed) == 1                       # channel_post instradato come message


def test_messaggio_vecchio_ignorato(make_app, app_mod, monkeypatch):
    monkeypatch.setattr(app_mod.signal_router, "should_process", lambda *a, **k: True)
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    handle = _handle_of(tg)

    # ts molto nel passato → oltre max_signal_age → IGNORE_STALE.
    asyncio.run(handle(_update(_msg("111", "arretrato", time.time() - 10_000_000)), None))

    assert a.processed == []
    assert a.confirmations == []


# ── Codex #250: il clamp di freschezza usa il timeout della coda ATTIVA ──────────────

def test_clamp_freschezza_usa_confirmation_timeout_in_modalita_coda(
        make_app, app_mod, monkeypatch):
    """Codex #250: in QUEUE_UNTIL_CONFIRMED la vita della riga è `confirmation_timeout`
    (non `clear_delay`). Il clamp del filtro freschezza deve usare la STESSA sorgente di
    timeout della coda (`signal_queue.timeout_from_config`), altrimenti un messaggio più
    vecchio di `clear_delay` ma entro `confirmation_timeout` verrebbe scartato come stantio
    pur avendo ancora vita utile.

    Setup: confirmation_timeout=120 > clear_delay=90, max_signal_age=120, messaggio di 100s.
    - Nuovo codice (clamp a timeout_from_config=120): 100 < 120 → fresco → PROCESS.
    - Vecchio codice (clamp a clear_delay=90): 100 > 90 → IGNORE_STALE → niente PROCESS.
    """
    monkeypatch.setattr(app_mod.signal_router, "should_process", lambda *a, **k: True)
    # Freschezza/coda leggono lo SNAPSHOT a START (session_cfg), non la config viva.
    session_cfg = {
        "bot_token": "x",
        "queue_mode": app_mod.signal_queue.QUEUE_UNTIL_CONFIRMED,
        "confirmation_timeout": 120,
        "clear_delay": 90,
        "max_signal_age": 120,
    }
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG, session_cfg=session_cfg)
    handle = _handle_of(tg)

    # 100s nel passato: oltre clear_delay (90) ma entro confirmation_timeout (120).
    asyncio.run(handle(_update(_msg("111", "P.Bet. segnale", time.time() - 100)), None))

    assert len(a.processed) == 1       # entro la vita reale della riga → processato
    assert a.confirmations == []


def test_clamp_freschezza_oltre_confirmation_timeout_resta_stantio(
        make_app, app_mod, monkeypatch):
    """Contro-prova: un messaggio oltre ANCHE `confirmation_timeout` resta stantio.
    Senza questo, il test sopra passerebbe anche se il filtro freschezza fosse rotto/disattivo."""
    monkeypatch.setattr(app_mod.signal_router, "should_process", lambda *a, **k: True)
    session_cfg = {
        "bot_token": "x",
        "queue_mode": app_mod.signal_queue.QUEUE_UNTIL_CONFIRMED,
        "confirmation_timeout": 120,
        "clear_delay": 90,
        "max_signal_age": 120,
    }
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG, session_cfg=session_cfg)
    handle = _handle_of(tg)

    # 200s nel passato: oltre confirmation_timeout (120) → stantio.
    asyncio.run(handle(_update(_msg("111", "P.Bet. segnale", time.time() - 200)), None))

    assert a.processed == []
    assert a.confirmations == []


# ── Codex #191 P1: il vecchio updater NON deve scrivere dopo STOP / nuovo START ──────

def test_handle_superato_da_nuovo_epoch_non_instrada(make_app, app_mod, monkeypatch):
    """Codex #191 P1: dopo uno STOP→START rapido il vecchio updater può ancora consegnare
    un update a QUESTA `_handle` (epoch della VECCHIA sessione). Con `_running=True`
    (rimesso dal nuovo START) ma epoch CORRENTE diverso, `_handle` deve NON instradare:
    altrimenti scriverebbe con la cfg della vecchia sessione (segnale doppio/stantio).

    Fail-first: sul vecchio codice (gate solo su `_running` dentro `_process`, non su epoch
    in `_handle`) l'update verrebbe instradato a `_process`."""
    monkeypatch.setattr(app_mod.signal_router, "should_process", lambda *a, **k: True)
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    handle = _handle_of(tg)            # closure con epoch=1 (vecchia sessione)
    # Un nuovo START: sessione attiva (_running=True) ma epoch avanzato → la closure è superata.
    a._running = True
    a._listener_epoch = 2

    asyncio.run(handle(_update(_msg("111", "P.Bet. segnale", time.time())), None))

    assert a.processed == []           # gate epoch fail-closed: nessuna scrittura del vecchio poller
    assert a.confirmations == []


def test_handle_dopo_stop_non_instrada(make_app, app_mod, monkeypatch):
    """Variante: durante lo STOP (prima che l'updater sia fermato) `_running=False`.
    Anche una chat notifiche XTrader non deve essere instradata a conferma."""
    a, tg = _drive_run_bot(make_app, app_mod, monkeypatch, CFG)
    handle = _handle_of(tg)
    a._running = False                 # STOP in corso: la sessione non è più corrente

    asyncio.run(handle(_update(_msg("999", "Inter v Milan Inter piazzata", time.time())), None))

    assert a.processed == []
    assert a.confirmations == []


# ── Codex #191 P1 (round 2): lo shutdown deve fermare l'app DI QUESTA sessione ──────

class _RecApp:
    """App Telegram finta che REGISTRA l'ordine di teardown (updater.stop/stop/shutdown),
    così il test verifica QUALE app viene fermata in uno STOP→START concorrente."""

    def __init__(self, on_start_polling=None):
        self.stops = []
        self.handlers = []
        outer = self

        class _Upd:
            async def start_polling(self, **kw):
                if on_start_polling is not None:
                    on_start_polling()

            async def stop(self):
                outer.stops.append("updater_stop")

        self.updater = _Upd()

    def add_handler(self, h):
        self.handlers.append(h)

    async def initialize(self):
        pass

    async def start(self):
        pass

    async def stop(self):
        self.stops.append("stop")

    async def shutdown(self):
        self.stops.append("shutdown")


def test_shutdown_ferma_app_locale_non_quella_di_un_nuovo_start(make_app, app_mod, monkeypatch):
    """Codex #191 P1: in uno STOP→START rapido un nuovo START sovrascrive `self._tg_app`
    PRIMA che il vecchio loop arrivi allo shutdown. Il vecchio `_async_run` deve fermare la
    PROPRIA app (riferimento locale), NON quella nuova: altrimenti fermerebbe il nuovo updater
    e lascerebbe vivo il proprio poller (segnali persi / conflitto Telegram).

    Fail-first: sul vecchio codice lo shutdown usava `self._tg_app` → avrebbe fermato l'app
    NUOVA (`new_app.stops` popolato) e non la propria (`old_app.stops` vuoto)."""
    a = make_app(config=CFG)
    a._running = True
    a._listener_epoch = 1
    new_app = _RecApp()                # l'app che un START concorrente mette in self._tg_app

    def _simula_nuovo_start():
        a._running = False             # fa uscire il wait loop di QUESTA sessione
        a._tg_app = new_app            # un nuovo START ha già rimpiazzato l'handle condiviso

    old_app = _RecApp(on_start_polling=_simula_nuovo_start)

    def _builder():
        class _B:
            def token(self, _t):
                return self

            def build(self):
                return old_app
        return _B()

    monkeypatch.setattr(app_mod, "ApplicationBuilder", _builder)
    monkeypatch.setattr(app_mod, "MessageHandler", lambda *a_, **k: ("MH", a_, k))

    app_mod.App._run_bot(a, {"bot_token": "x"}, 1)

    assert old_app.stops == ["updater_stop", "stop", "shutdown"]   # ferma la PROPRIA app
    assert new_app.stops == []                                     # NON tocca l'app del nuovo START
