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

import pytest


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

    def __init__(self, app, *, fail, stop_fail=False):
        self._app = app
        self._fail = fail
        self._stop_fail = stop_fail           # #311-1.2 Test B: `stop` solleva → riconnessione DOPO successo
        self.start_polling_calls = 0
        self.start_polling_kwargs = None      # #311-1.2: cattura i kwargs (drop_pending_updates)
        self.stop_calls = 0

    async def start_polling(self, **kwargs):
        """Simula il polling: alla 1ª connessione solleva un errore transitorio
        DAL POLLING; altrimenti segnala il successo (fa uscire il supervisor)."""
        self.start_polling_calls += 1
        self.start_polling_kwargs = kwargs    # registra ANCHE sul fallimento (per il #311-1.2)
        if self._fail:
            raise type("NetworkError", (Exception,), {})("polling giù (simulato)")
        self._app.on_success()

    async def stop(self):
        """Registra l'arresto dell'updater (chiamato dal vero `_safe_shutdown_tg`).
        Con `stop_fail`, solleva DOPO una connessione riuscita: modella un blip di
        rete a bridge già connesso, che fa propagare l'errore fuori da `_async_run`
        e innesca una riconnessione dello stesso epoch (#311-1.2 Test B)."""
        self.stop_calls += 1
        if self._stop_fail:
            raise type("NetworkError", (Exception,), {})("stop giù (simulato)")


def _transient_exc(name, msg="get_me giù: connessione non reale (simulato)"):
    """Eccezione transitoria FEDELE alla classificazione reale di `reconnect_policy`. Quando
    `python-telegram-bot` è installato (CI) `is_transient_error` usa `isinstance` sulle CLASSI
    REALI di `telegram.error`: quindi si solleva la classe REALE (`telegram.error.TimedOut`/
    `NetworkError`) se disponibile. Senza telegram (alcuni ambienti locali) si ricade su una classe
    dinamica con lo STESSO nome, che il fallback per nome di `is_transient_error` riconosce. Così il
    test è corretto in ENTRAMBI gli ambienti (bug CI: una classe dinamica NON è sottoclasse della
    `telegram.error.TimedOut` reale → non transitoria → STOP)."""
    try:
        import telegram.error as te            # noqa: PLC0415 — import locale voluto (dipende dall'ambiente)
        cls = getattr(te, name, None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            try:
                return cls(msg)
            except Exception:                  # noqa: BLE001 — firma costruttore diversa → senza messaggio
                return cls()
    except Exception:                          # noqa: BLE001 — telegram assente → classe dinamica per nome
        pass
    return type(name, (Exception,), {})(msg)


class _Bot:
    """Bot PTB finto: `get_me` è il round-trip di CONFERMA connessione (#371). Con
    `fail=True` solleva — modella `start_polling` che ritorna senza una connessione
    reale (bootstrap fire-and-forget), così l'invariante anti-arretrati non può
    dipendere solo dal fatto che `start_polling` sollevi (blocker Fugu #369)."""

    def __init__(self, *, fail=False, exc_name="NetworkError"):
        self._fail = fail
        self._exc_name = exc_name          # classe eccezione (reale telegram.error se disponibile)
        self.get_me_calls = 0
        self.get_me_kwargs = None          # cattura i timeout espliciti (review CodeRabbit)

    async def get_me(self, **kwargs):
        self.get_me_calls += 1
        self.get_me_kwargs = kwargs
        if self._fail:
            raise _transient_exc(self._exc_name)
        return {"id": 1, "is_bot": True}


class _TgApp:
    """App Telegram finta che registra initialize/start/stop/shutdown reali, così
    il test può verificare il CONTRATTO di teardown invece di uno stub no-op."""

    def __init__(self, *, fail, on_success, on_shutdown=None, stop_fail=False,
                 get_me_fail=False, get_me_exc="NetworkError"):
        self.updater = _Updater(self, fail=fail, stop_fail=stop_fail)
        self.bot = _Bot(fail=get_me_fail, exc_name=get_me_exc)   # #371: conferma connessione (get_me) prima del flip
        self.on_success = on_success
        self._on_shutdown = on_shutdown
        self.init_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.shutdown_calls = 0

    def add_handler(self, h):
        """Riceve il MessageHandler (qui irrilevante: nessun update viene iniettato)."""

    def add_error_handler(self, h):
        """AC-M1 #114: `_run_bot` registra ora un error handler PTB (qui irrilevante)."""

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


def test_drop_pending_updates_resta_true_se_la_prima_connessione_fallisce(make_app, app_mod, monkeypatch):
    """#311-1.2 Test A — invariante anti-arretrati: `first_connection` si abbassa a False
    SOLO DOPO un `start_polling` RIUSCITO. Se la PRIMA connessione FALLISCE (errore transitorio
    dal polling), il flag resta True e il primo poll RIUSCITO scarta comunque il backlog
    pre-START → `drop_pending_updates=True` su ENTRAMBI i giri.

    Questo blocca la regressione segnalata da GPT-5.5/Fable 5/Fugu Ultra sul #369: col flip
    fatto PRIMA di `start_polling` (flip-per-giro), la 1ª connessione fallita abbasserebbe già
    il flag e il primo poll riuscito NON scarterebbe più il backlog pre-START → una scommessa
    accodata prima di START potrebbe essere processata. Mutation-guard: quel bug fa passare
    `drop_pending_updates=False` al 2° giro e questo `is True` fallisce.

    Cornice: 1ª connessione fallisce → riconnessione riuscita. Si cattura `drop_pending_updates`
    di entrambi i giri."""
    a = make_app()
    a._running = True
    a._listener_epoch = 7
    a._reconnect_attempt = 0
    # ramo "transitorio → riconnetti" forzato (classificazione testata altrove)
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    a._reconnect_wait = lambda delay, stop_event=None: None                 # niente attesa reale: test rapido
    apps = []
    _install_builder(monkeypatch, app_mod, apps,
                     lambda index: _TgApp(fail=(index == 0),
                                          on_success=lambda: setattr(a, "_running", False)))

    app_mod.App._run_bot(a, {"bot_token": "x"}, 7)

    assert len(apps) == 2                                  # 1° giro (fallito) + 1 riconnessione
    # 1° giro: tenta di scartare il backlog pre-avvio (ma il polling fallisce)
    assert apps[0].updater.start_polling_kwargs["drop_pending_updates"] is True
    # riconnessione DOPO un 1° tentativo FALLITO: il primo poll RIUSCITO scarta comunque il
    # backlog pre-START — l'invariante anti-arretrati NON viene mai saltata
    assert apps[1].updater.start_polling_kwargs["drop_pending_updates"] is True
    # invariato: allowed_updates resta lo stesso su entrambi i giri
    assert apps[1].updater.start_polling_kwargs["allowed_updates"] == ["message", "channel_post"]


def test_drop_pending_updates_false_su_riconnessione_dopo_connessione_riuscita(make_app, app_mod, monkeypatch):
    """#311-1.2 Test B — recupero backlog dell'outage: dopo una PRIMA connessione RIUSCITA,
    una riconnessione dello stesso epoch (blip di rete a bridge già connesso) usa
    `drop_pending_updates=False`, così i messaggi arrivati DURANTE la disconnessione vengono
    recuperati e non buttati via. L'anti-arretrati resta al filtro `max_signal_age`
    (`is_stale` in `telegram_dispatch.decide`, testato in `test_telegram_dispatch.py`).

    Cornice: 1ª connessione RIUSCITA (flip a False) → poi `updater.stop` solleva, così l'errore
    propaga fuori da `_async_run` DOPO il successo e innesca la riconnessione dello stesso epoch.
    Il 1° giro NON ferma il supervisor (`on_success` sveglia solo l'attesa via
    `_async_stop_event`, senza abbassare `_running`); il 2° giro ferma il supervisor.
    Mutation-guard: un `drop_pending_updates=True` fisso farebbe fallire l'`is False` del 2° giro."""
    a = make_app()
    a._running = True
    a._listener_epoch = 9
    a._reconnect_attempt = 0
    # ramo "transitorio → riconnetti" forzato (classificazione testata altrove)
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    a._reconnect_wait = lambda delay, stop_event=None: None                 # niente attesa reale: test rapido
    apps = []

    def _make_tg(index):
        if index == 0:
            # 1ª connessione RIUSCITA: `on_success` sveglia SOLO l'attesa (senza fermare il
            # bridge), poi `updater.stop` solleva → l'errore propaga DOPO il successo →
            # riconnessione stesso epoch.
            return _TgApp(fail=False, stop_fail=True,
                          on_success=lambda: a._async_stop_event.set())
        # 2ª connessione RIUSCITA: ferma il supervisor (test termina).
        return _TgApp(fail=False, on_success=lambda: setattr(a, "_running", False))

    _install_builder(monkeypatch, app_mod, apps, _make_tg)

    app_mod.App._run_bot(a, {"bot_token": "x"}, 9)

    assert len(apps) == 2                                  # 1° giro (riuscito, poi stop fallito) + riconnessione
    # 1ª connessione della sessione → scarta il backlog pre-START
    assert apps[0].updater.start_polling_kwargs["drop_pending_updates"] is True
    # riconnessione DOPO una connessione riuscita → NON scartare: recupera l'outage backlog
    assert apps[1].updater.start_polling_kwargs["drop_pending_updates"] is False


def test_start_polling_ritorna_senza_connettere_non_abbassa_il_flag(make_app, app_mod, monkeypatch):
    """#371 (blocker Fugu #369): l'invariante anti-arretrati NON deve dipendere dal fatto che
    `start_polling` sollevi. In PTB `start_polling` può ritornare senza una connessione reale
    (bootstrap fire-and-forget). Il flip di `first_connection` è quindi gated su una CONFERMA
    esplicita `await app.bot.get_me()`: se la connessione non è reale `get_me` solleva →
    riconnessione con `first_connection` ANCORA True → `drop_pending_updates` resta True (il
    backlog pre-START viene comunque scartato, niente doppia scommessa).

    Cornice: `start_polling` NON solleva (fire-and-forget) e sveglia solo l'attesa; alla 1ª
    connessione `get_me` SOLLEVA (connessione non reale) → riconnessione; alla 2ª `get_me`
    riesce → conferma e flip. Si cattura `drop_pending_updates` di entrambi i giri.

    Mutation-guard: senza il gate `get_me` (flip subito dopo `start_polling`), la 1ª connessione
    non-reale abbasserebbe il flag e NON ci sarebbe riconnessione (nessun `get_me` che solleva) →
    un solo giro (`len(apps) == 1`) → l'assert `len == 2` fallisce."""
    a = make_app()
    a._running = True
    a._listener_epoch = 11
    a._reconnect_attempt = 0
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    a._reconnect_wait = lambda delay, stop_event=None: None                 # niente attesa reale: test rapido
    apps = []

    def _make_tg(index):
        # `start_polling` non solleva e sveglia SOLO l'attesa (non ferma il bridge), così se il
        # codice raggiungesse il wait-loop (ramo buggato) uscirebbe pulito invece di appendersi.
        # 1ª connessione: `get_me` SOLLEVA (non connesso) → riconnessione; 2ª: `get_me` riesce.
        return _TgApp(fail=False, get_me_fail=(index == 0),
                      on_success=lambda: a._async_stop_event.set())

    _install_builder(monkeypatch, app_mod, apps, _make_tg)

    app_mod.App._run_bot(a, {"bot_token": "x"}, 11)

    assert len(apps) == 2                                  # get_me fallito → ha riconnesso (2 giri)
    assert apps[0].bot.get_me_calls == 1                   # conferma tentata alla 1ª connessione
    # La conferma è BOUNDED (review CodeRabbit): timeout espliciti così una `get_me` appesa non
    # blocca uno STOP. Senza, una chiamata a Telegram irraggiungibile resterebbe indefinita.
    to = app_mod._CONNECT_CONFIRM_TIMEOUT              # valore concreto atteso (review CodeRabbit)
    assert apps[0].bot.get_me_kwargs.get("connect_timeout") == to
    assert apps[0].bot.get_me_kwargs.get("read_timeout") == to
    assert apps[0].bot.get_me_kwargs.get("pool_timeout") == to
    # 1ª connessione NON confermata → scarta il backlog pre-START
    assert apps[0].updater.start_polling_kwargs["drop_pending_updates"] is True
    # riconnessione dopo una 1ª connessione NON confermata → il flag è restato True: scarta ANCORA
    assert apps[1].updater.start_polling_kwargs["drop_pending_updates"] is True
    # Teardown pulito dopo il fallimento di `get_me` (GPT-5.5): l'updater/app della connessione
    # non confermata DEVE essere chiuso PRIMA del retry (no task zombie / doppio poller). Il vero
    # `_safe_shutdown_tg` chiama updater.stop + app.stop + app.shutdown sulla sessione fallita.
    assert apps[0].updater.stop_calls >= 1
    assert apps[0].stop_calls >= 1 and apps[0].shutdown_calls >= 1


def test_get_me_timedout_e_transitorio_riconnette_non_stop(make_app, app_mod, monkeypatch):
    """#371 (review Fugu Ultra / GLM 5.2 / GPT-5.5): la sicurezza del fix dipende dal fatto che un
    `TimedOut` da `get_me` (conferma connessione scaduta) sia classificato TRANSITORIO da
    `reconnect_policy.is_transient_error` → riconnessione, NON uno STOP permanente. Questo test NON
    stubba `should_reconnect`: usa la classificazione REALE, così se `TimedOut` non fosse transitorio
    il supervisor si fermerebbe (un solo giro) e l'assert fallirebbe.

    Cornice: `start_polling` non solleva (fire-and-forget); alla 1ª connessione `get_me` solleva
    un `TimedOut` — la classe REALE `telegram.error.TimedOut` se disponibile (così `isinstance` in CI
    la riconosce), altrimenti una classe dinamica omonima per il fallback per nome (vedi
    `_transient_exc`) → `is_transient_error` la riconosce transitoria → riconnessione con
    `first_connection` ancora True; alla 2ª `get_me` riesce → conferma e flip."""
    a = make_app()
    a._running = True
    a._listener_epoch = 13
    a._reconnect_attempt = 0
    # NIENTE monkeypatch di should_reconnect: si esercita la classificazione REALE di `TimedOut`.
    a._reconnect_wait = lambda delay, stop_event=None: None                 # niente attesa reale: test rapido
    apps = []

    def _make_tg(index):
        return _TgApp(fail=False, get_me_fail=(index == 0), get_me_exc="TimedOut",
                      on_success=lambda: a._async_stop_event.set())

    _install_builder(monkeypatch, app_mod, apps, _make_tg)

    app_mod.App._run_bot(a, {"bot_token": "x"}, 13)

    # Se `TimedOut` NON fosse transitorio, `should_reconnect` sarebbe False → STOP → len == 1.
    assert len(apps) == 2                                  # TimedOut classificato transitorio → riconnesso
    assert apps[0].updater.start_polling_kwargs["drop_pending_updates"] is True
    assert apps[1].updater.start_polling_kwargs["drop_pending_updates"] is True


def test_first_connection_si_resetta_a_ogni_nuovo_START(make_app, app_mod, monkeypatch):
    """#311-1.2 (review GLM 5.2): `first_connection` è LOCALE a `_run_bot`, quindi ogni nuovo
    START (nuovo epoch, nuova invocazione di `_run_bot`) riparte da `True` → la PRIMA
    connessione della NUOVA sessione scarta di nuovo il backlog pre-START. Senza questo reset,
    una sessione riavviata processerebbe gli arretrati accumulati mentre era ferma.

    Si eseguono DUE sessioni consecutive (epoch 1 poi epoch 2), ognuna con una connessione
    riuscita subito. Mutation-guard: se il flag fosse promosso a stato d'istanza (inizializzato
    una sola volta), la 2ª sessione partirebbe da `False` (flippato dalla 1ª) → l'assert `is
    True` del 2° START fallirebbe."""
    a = make_app()
    a._reconnect_wait = lambda delay, stop_event=None: None
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)

    def _run_una_sessione(epoch):
        apps = []
        _install_builder(monkeypatch, app_mod, apps,
                         lambda index: _TgApp(fail=False,
                                              on_success=lambda: setattr(a, "_running", False)))
        a._running = True
        a._listener_epoch = epoch
        a._reconnect_attempt = 0
        app_mod.App._run_bot(a, {"bot_token": "x"}, epoch)
        return apps

    # Sessione 1 (epoch 1): prima connessione → scarta il backlog pre-START.
    apps1 = _run_una_sessione(1)
    assert apps1[0].updater.start_polling_kwargs["drop_pending_updates"] is True
    # Sessione 2 (nuovo START, epoch 2): DEVE ripartire da first_connection=True e riscartare.
    apps2 = _run_una_sessione(2)
    assert apps2[0].updater.start_polling_kwargs["drop_pending_updates"] is True


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

    def _wait(delay, stop_event=None):
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
    a._reconnect_wait = lambda delay, stop_event=None: setattr(a, "_listener_epoch", 99)

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
    a._reconnect_wait = lambda delay, stop_event=None: None          # niente attesa reale: il test resta rapido

    apps = []
    _install_builder(monkeypatch, app_mod, apps,
                     lambda index: _TgApp(fail=(index == 0),
                                          on_success=lambda: setattr(a, "_running", False)))

    app_mod.App._run_bot(a, {"bot_token": "x"}, 3)

    assert len(apps) == 2                            # ha ritentato dopo l'errore transitorio
    types = [e["type"] for e in event_journal.read_events(a._journal_path)]
    assert "RECONNECT" in types                      # il tentativo di riconnessione è nel diario


# ── P3-ap2 audit #114: LOST-WAKE su STOP→START rapido durante il backoff ──────────────

def test_backoff_attende_l_evento_di_sessione_catturato_non_quello_riassegnato(
        make_app, app_mod, monkeypatch):
    """P3-ap2 #114 — il supervisor deve attendere il backoff sull'evento di stop CATTURATO
    all'avvio della PROPRIA sessione (`backoff_stop_event = self._stop_event`), NON su
    `self._stop_event` riletto ad ogni giro. In uno STOP→START rapido il nuovo `_start`
    RIASSEGNA `self._stop_event` a un evento fresco: se il backoff leggesse l'attributo vivo,
    il thread VECCHIO attenderebbe l'evento del SUCCESSORE (non settato dallo STOP che lo
    riguardava) → LOST-WAKE, appeso per tutto il delay.

    Fail-first deterministico: `_reconnect_wait` è stubbato per REGISTRARE l'evento ricevuto.
    Al 1º backoff si simula il nuovo START riassegnando `self._stop_event`; al 2º giro l'evento
    passato deve essere ANCORA quello di sessione (cattura locale). Se il call site regredisse a
    passare `self._stop_event`, il 2º giro vedrebbe l'evento fresco e l'assert fallirebbe."""
    a = make_app()
    a._running = True
    a._listener_epoch = 5
    a._reconnect_attempt = 0
    session_ev = threading.Event()
    a._stop_event = session_ev
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)
    monkeypatch.setattr(app_mod.reconnect_policy, "effective_delay", lambda *a_, **k: 0.0)

    seen = []

    def _capture_wait(delay, stop_event):
        seen.append(stop_event)
        if len(seen) == 1:
            # un START rapido riassegna l'attributo DOPO l'avvio della sessione vecchia
            a._stop_event = threading.Event()
        else:
            a._running = False        # esci dopo il 2º giro (evita loop infinito col delay 0)

    a._reconnect_wait = _capture_wait

    apps = []
    _install_builder(monkeypatch, app_mod, apps,
                     lambda index: _TgApp(fail=True, on_success=lambda: None))

    app_mod.App._run_bot(a, {"bot_token": "x"}, 5)

    assert len(seen) >= 2, "il backoff non è stato raggiunto due volte"
    assert seen[0] is session_ev, "il 1º backoff non ha atteso l'evento di sessione catturato"
    assert seen[1] is session_ev, (
        "LOST-WAKE (P3-ap2): dopo la riassegnazione di self._stop_event il backoff ha atteso "
        "l'evento del successore invece di quello catturato all'avvio della sessione")


def test_start_riassegna_stop_event_fresco_e_reconnect_wait_usa_il_parametro(app_mod):
    """P3-ap2 #114 (pin SORGENTE, pattern #311): la doppia invariante che evita il LOST-WAKE.
    1) `_start` deve RIASSEGNARE `self._stop_event = threading.Event()`, NON fare `.clear()`
       in place (un `.clear()` cancellerebbe il set dello STOP sull'evento ancora catturato dal
       thread vecchio); 2) `_reconnect_wait` deve attendere il PARAMETRO `stop_event`, mai
       `self._stop_event` (che un nuovo START può aver riassegnato).

    Il pin usa `inspect.getsource` sulle SINGOLE funzioni (review Sourcery): niente slicing del
    file intero, così un refactor cosmetico altrove non rende fragile il test."""
    import inspect

    run_bot_src = inspect.getsource(app_mod.App._run_bot)
    reconnect_src = inspect.getsource(app_mod.App._reconnect_wait)
    start_src = inspect.getsource(app_mod.App._start)

    # 1) `_run_bot` cattura l'evento in locale e lo passa al backoff
    assert "backoff_stop_event = self._stop_event" in run_bot_src, (
        "app.py/_run_bot: manca la cattura locale dell'evento di stop della sessione (P3-ap2)")
    assert "self._reconnect_wait(delay, backoff_stop_event)" in run_bot_src, (
        "app.py/_run_bot: il backoff deve passare l'evento CATTURATO a _reconnect_wait (P3-ap2)")

    # 2) `_reconnect_wait` attende il parametro, non self._stop_event
    assert "stop_event.wait(delay)" in reconnect_src, (
        "app.py/_reconnect_wait: deve attendere il parametro `stop_event` (P3-ap2)")
    assert "self._stop_event.wait" not in reconnect_src, (
        "app.py/_reconnect_wait: NON rileggere self._stop_event (lost-wake su START rapido)")

    # 3) `_start` riassegna un evento fresco, niente `.clear()` in place
    assert "self._stop_event = threading.Event()" in start_src, (
        "app.py/_start: la nuova sessione deve RIASSEGNARE self._stop_event (P3-ap2)")
    assert "self._stop_event.clear()" not in start_src, (
        "app.py/_start: NON usare .clear() in place (cancellerebbe il set dello STOP catturato "
        "dal thread vecchio → lost-wake) — riassegna un evento fresco (P3-ap2)")


# ── Reset del contatore di riconnessione allo START (audit #137, PR 3/4) ─────
#
# `_reconnect_attempt` si azzera solo in `__init__` e sul successo epoch-gated. Ne'
# `_start` ne' `_stop` lo toccano: dopo una sessione caduta piu' volte, un nuovo START
# eredita il contatore alto e il PRIMO intoppo aspetta il backoff massimo invece di
# quello iniziale.

@pytest.fixture
def sessione_pulita(app_mod):
    """Ripristina lo stato GLOBALE che `_start` lascia sporco.

    `_start` chiama `csv_writer.freeze_csv_language()` (riga ~3156) e il corrispondente
    `unfreeze` sta in `_stop`, che questi test non raggiungono mai: senza questo cleanup
    la lingua CSV resta CONGELATA per il resto della sessione pytest e fa cadere 10 test
    di altri file. Misurato: passavano da soli, rossi in suite completa — il modo in cui
    un test «verde» rompe qualcun altro."""
    prima = app_mod.csv_writer.get_csv_language()
    yield
    app_mod.csv_writer.unfreeze_csv_language()
    app_mod.csv_writer.set_csv_language(prima)


def _app_fino_al_nuovo_epoch(app_mod, tmp_path, *, reconnect_attempt):
    """`App` headless portata oltre i fail-fast di `_start` fino al bump dell'epoch.

    Config in DRY-RUN cosi' non scatta il dialogo di conferma modalita' reale."""
    import types
    a = object.__new__(app_mod.App)
    # Seam della REVOCA ONLINE, iniettati come «fuori scope» (#159). Da quando
    # `REVOCATION_LIST_URL` e' l'URL reale la revoca e' ATTIVA di default, quindi `_start`
    # richiede anche un gate revoca aperto e uscirebbe a monte. Qui si misura il backoff di riconnessione, non la
    # revoca: quella ha la sua suite dedicata (`test_license_lock_r3c.py`).
    a._revocation_enabled = lambda: False
    a._revocation_gate_ok = lambda: True
    cfg = {
        "chat_id": "-1001111111111",
        "active_parser": "P",
        "custom_parsers": {"P": {"rules": [{"target": "EventName", "required": True,
                                            "prefix": "Match:"}]}},
        "csv_path": str(tmp_path / "out.csv"),
        "dry_run": True,
    }
    # `_config` reale sull'istanza: oggi `_resync_token_field` e' stubbato e non lo
    # legge, ma un domani basterebbe togliere lo stub perche' l'harness si rompa in
    # modo oscuro (rilievo CodeRabbit #173).
    a._config = cfg
    a.logs = []
    a._log = a.logs.append
    a._dbg = lambda *x, **k: None
    a._journal = lambda *x, **k: None
    a._journal_csv_cleared_if_had_row = lambda *x, **k: None
    a._running = False
    a._closing = False
    a._ui_ready = True
    a._license_locked = None
    a._license_panel = types.SimpleNamespace(
        current_status=lambda: types.SimpleNamespace(valid=True, reason="", detail=""))
    a._cancel_pending_autostart = lambda: None
    a._resync_token_field = lambda *_a, **_k: None   # il vero accetta had_incomplete_load
    a._e_token = types.SimpleNamespace(get=lambda: "123456:" + "A" * 35)
    a._e_csv = types.SimpleNamespace(get=lambda: cfg["csv_path"])
    a._e_delay = types.SimpleNamespace(get=lambda: "90")
    a._save_config = lambda *_a, **_k: cfg           # il vero accetta persist=
    a._save_ok = True
    a._adv_errors = []
    a._csv_lock = app_mod.csv_lock_escalation.CsvLockEscalation()
    a._csv_dirty = False
    a._listener_epoch = 7
    a._reconnect_attempt = reconnect_attempt
    return a


def _start_fino_al_bump(app_mod, a):
    """Esegue `_start` e conferma di aver DAVVERO superato il bump dell'epoch.

    L'ancora e' l'epoch: se `_start` fosse uscito a monte per un fail-fast, l'epoch
    resterebbe invariato e il test fallirebbe con un messaggio chiaro invece di
    passare a vuoto asserendo su uno stato mai raggiunto."""
    prima = a._listener_epoch
    try:
        app_mod.App._start(a)
    except Exception:       # noqa: BLE001 — `_start` muore piu' avanti (nessun Telegram reale)
        pass
    assert a._listener_epoch == prima + 1, (
        f"_start non ha raggiunto il bump dell'epoch: {[m for m in a.logs if '❌' in m]}")


def test_start_azzera_il_contatore_di_riconnessione(app_mod, tmp_path, sessione_pulita):
    """Il difetto: una sessione caduta 8 volte lascia il contatore a 8. Il nuovo START
    lo eredita, e al primo fallimento `effective_delay(9)` da' il backoff MASSIMO (60s)
    invece di quello iniziale (2s) — 30 volte tanto, senza che nulla lo spieghi
    all'operatore. Il bridge risulta «avviato» ma resta fermo un minuto."""
    a = _app_fino_al_nuovo_epoch(app_mod, tmp_path, reconnect_attempt=8)
    _start_fino_al_bump(app_mod, a)

    assert a._reconnect_attempt == 0, (
        f"contatore stantio ({a._reconnect_attempt}): il primo intoppo della nuova "
        "sessione aspetterebbe il backoff massimo invece di ripartire da capo")


def test_il_contatore_azzerato_riporta_il_backoff_a_quello_iniziale(app_mod, tmp_path, sessione_pulita):
    """La CONSEGUENZA misurata, non solo il valore della variabile: dopo lo START il
    primo tentativo fallito deve costare il backoff iniziale.

    Senza questa asserzione il test sopra fisserebbe un numero senza dire perche'
    conta; qui si esercita `reconnect_policy.effective_delay` come lo chiama `_supervisor`
    (contatore gia' incrementato)."""
    from xtrader_bridge import reconnect_policy

    a = _app_fino_al_nuovo_epoch(app_mod, tmp_path, reconnect_attempt=8)
    stantio = reconnect_policy.effective_delay(a._reconnect_attempt + 1)

    _start_fino_al_bump(app_mod, a)
    fresco = reconnect_policy.effective_delay(a._reconnect_attempt + 1)

    assert stantio == reconnect_policy.DEFAULT_MAX_DELAY, stantio   # 60s: il massimo
    assert fresco == reconnect_policy.DEFAULT_BASE_DELAY, fresco    # 2s: da capo
    assert fresco < stantio


def test_ogni_START_riparte_da_capo_non_solo_il_primo(app_mod, tmp_path, sessione_pulita):
    """Il reset deve valere a OGNI ciclo START, non una volta sola.

    Si simula la sequenza reale: START, la sessione cade piu' volte (il supervisor alza
    il contatore), nuovo START. Anche il secondo deve ripartire da capo — un reset che
    valesse solo al primo avvio lascerebbe il difetto vivo dal secondo in poi, ed e' il
    modo in cui una correzione «funziona quando la provi una volta» e poi no."""
    a = _app_fino_al_nuovo_epoch(app_mod, tmp_path, reconnect_attempt=8)
    _start_fino_al_bump(app_mod, a)
    assert a._reconnect_attempt == 0, a._reconnect_attempt

    # la sessione perde la rete piu' volte: e' il supervisor a incrementare
    a._reconnect_attempt += 1
    a._reconnect_attempt += 1
    a._reconnect_attempt += 1
    assert a._reconnect_attempt == 3

    # secondo START (dopo uno STOP): deve azzerare di nuovo
    a._running = False
    _start_fino_al_bump(app_mod, a)
    assert a._reconnect_attempt == 0, (
        "il secondo START non ha azzerato: il reset e' legato al primo avvio invece "
        "che a ogni nuova sessione")


def test_un_supervisor_STANTIO_non_tocca_il_contatore_della_nuova_sessione(
        make_app, app_mod, monkeypatch):
    """Il dubbio sollevato da TUTTI E QUATTRO i reviewer sulla PR #173: il reset allo
    START serve a poco se un vecchio `_run_bot` puo' ancora incrementare
    `_reconnect_attempt`, che e' un campo CONDIVISO fra le sessioni.

    Qui si esercita esattamente quella sequenza: un supervisor gira con epoch 9, il
    polling fallisce, e prima che il supervisor decida se ritentare arriva un nuovo
    START (l'epoch corrente diventa 99 e il contatore viene azzerato come fa `_start`).

    L'incremento di `_reconnect_attempt` sta DOPO la guardia `if not _is_current():
    break`, quindi il supervisor stantio esce prima di toccarlo: il contatore della
    nuova sessione resta 0 e il primo intoppo costa il backoff INIZIALE.

    Senza la guardia questo test e' rosso — ed e' la prova che il reset non viene
    vanificato dalla sessione precedente."""
    a = make_app()
    a._running = True
    a._listener_epoch = 9
    a._reconnect_attempt = 4          # il vecchio supervisor aveva gia' accumulato
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect", lambda running, exc: True)

    # Seam esatto: `_safe_shutdown_tg` gira DOPO il fallimento del polling e PRIMA
    # della guardia `if not _is_current(): break`. E' la finestra in cui il nuovo START
    # deve poter arrivare perche' il test dimostri qualcosa.
    def _nuovo_start_durante_il_fallimento(session_app, loop):
        a._listener_epoch = 99        # cio' che fa `_start`: nuovo epoch...
        a._reconnect_attempt = 0      # ...e contatore azzerato
    a._safe_shutdown_tg = _nuovo_start_durante_il_fallimento

    apps = []
    _install_builder(monkeypatch, app_mod, apps,
                     lambda index: _TgApp(fail=True, on_success=lambda: None))

    app_mod.App._run_bot(a, {"bot_token": "x"}, 9)

    assert a._reconnect_attempt == 0, (
        f"il supervisor STANTIO ha portato il contatore a {a._reconnect_attempt}: "
        "la nuova sessione non ripartirebbe dal backoff iniziale")
    from xtrader_bridge import reconnect_policy
    assert reconnect_policy.effective_delay(a._reconnect_attempt + 1) == \
        reconnect_policy.DEFAULT_BASE_DELAY


# ── Contatore di backoff LOCALE alla sessione (issue #174) ───────────────────

def test_un_supervisor_stantio_nella_FINESTRA_non_falsa_il_backoff_nuovo(
        make_app, app_mod, monkeypatch):
    """Issue #174: la finestra di interleaving fra la guardia e l'incremento.

    La #173 ha chiuso il caso semplice — un supervisor con epoch superato esce alla guardia
    `if not _is_current(): break` prima di toccare il contatore. Ma fra QUELLA guardia e il
    `+= 1` resta una finestra: se il nuovo START arriva li' in mezzo, il vecchio supervisor
    ha gia' superato il controllo e incrementa comunque.

    La finestra e' riprodotta in modo DETERMINISTICO invece che sperando in un interleaving
    di thread: il seam e' `should_reconnect`, che gira esattamente fra la guardia e
    l'incremento. Da li' si simula cio' che fa `_start` (nuovo epoch + contatore azzerato).

    Col contatore CONDIVISO il vecchio supervisor lo riportava a 1 e la sessione nuova, al
    primo intoppo, aspettava piu' del backoff iniziale. Col contatore LOCALE non puo' piu':
    ogni `_run_bot` conta i propri tentativi, come gia' fa `first_connection`.

    Il supervisor esce comunque subito dopo (epoch superato al giro successivo del `while`),
    quindi il test non puo' avvitarsi: nessun rischio di loop infinito."""
    a = make_app()
    a._running = True
    a._listener_epoch = 9
    a._reconnect_attempt = 4          # il vecchio supervisor aveva gia' accumulato

    def _nuovo_start_DENTRO_la_finestra(running, exc):
        # gira DOPO `if not _is_current(): break` e PRIMA del `+= 1`: e' la finestra.
        a._listener_epoch = 99        # cio' che fa `_start`...
        a._reconnect_attempt = 0      # ...compreso il reset della #173
        return True                   # e il vecchio supervisor prosegue verso l'incremento
    monkeypatch.setattr(app_mod.reconnect_policy, "should_reconnect",
                        _nuovo_start_DENTRO_la_finestra)

    _install_builder(monkeypatch, app_mod, [],
                     lambda index: _TgApp(fail=True, on_success=lambda: None))
    a._reconnect_wait = lambda delay, stop_event=None: None

    # Si registra il tentativo con cui viene calcolato il ritardo: e' LI' che sta il danno.
    # Asserire solo sul contatore d'istanza lascerebbe passare un fix che tiene pulito lo
    # specchio ma continua a decidere il backoff su di esso (mutazione sopravvissuta al
    # primo giro).
    from xtrader_bridge import reconnect_policy
    vero = reconnect_policy.effective_delay
    tentativi_usati = []
    monkeypatch.setattr(app_mod.reconnect_policy, "effective_delay",
                        lambda tentativo, retry_after=None: (
                            tentativi_usati.append(tentativo) or vero(tentativo, retry_after)))

    app_mod.App._run_bot(a, {"bot_token": "x"}, 9)

    assert tentativi_usati == [1], (
        f"il backoff e' stato calcolato su {tentativi_usati} invece che sul PRIMO tentativo "
        "di questa sessione: la decisione non usa il contatore locale")
    assert a._reconnect_attempt == 0, (
        f"il supervisor STANTIO ha sporcato lo specchio della nuova sessione "
        f"({a._reconnect_attempt}): chi lo legge da fuori vedrebbe un valore non suo")
