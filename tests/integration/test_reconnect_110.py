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
