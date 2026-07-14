"""Controller dell'assistente di configurazione (#41 PR-3) — logica di ciclo di vita, testabile.

Separa la **logica** (macchina a stati Abilita/Stop, invio messaggi, persistenza cronologia,
teardown del thread) dalla **view** tkinter (`config_agent_gui`), come il resto del repo. Tutto qui
è headless e offline-testabile: il client Anthropic è iniettabile (i test usano un finto), il
worker può essere pilotato in modo sincrono.

Sicurezza: `enable()` abilita SOLO la chat, **non** avvia il listener live né la modalità reale; le
azioni safety-critical restano bloccate dalle guardie di `config_agent` (hard block). La scrittura
config resta disattivata (`allow_writes=False`, i tool di scrittura sono PR-4). La cronologia è
caricata a `enable()` e salvata **redatta** dopo ogni turno (`ConversationHistory`, PR-2).
"""

import queue
import threading

from . import config_agent, config_store, event_log, token_store

# Stati del controller.
STOPPED = "stopped"
RUNNING = "running"
ERROR = "error"

# Sentinella per fermare il loop del worker (teardown pulito).
_STOP = object()


class AgentController:
    """Ciclo di vita dell'assistente. NON tocca tkinter: emette eventi via `on_event(kind, data)`
    (la view li marshalla sul thread GUI). `client` è iniettabile; se assente, `enable()` costruisce
    un `RealAnthropicClient` dalla API key nel keyring (assente → stato ERROR, l'agente resta
    spento)."""

    def __init__(self, *, client=None, client_factory=None, config_loader=None,
                 history=None, parsers_dir=None, on_event=None, logger=None):
        self._config_loader = config_loader or config_store.load_config
        self._parsers_dir = parsers_dir
        self._on_event = on_event
        self._logger = logger
        self._client = client
        self._client_factory = client_factory
        self.state = STOPPED
        self.last_error = ""
        # Registry read-only che legge lo stato VIVO dell'app (config redatta, health, parser).
        self._registry = config_agent.build_default_registry(
            config_loader=self._config_loader, parsers_dir=parsers_dir, logger=logger)
        self._history = history if history is not None else config_agent.ConversationHistory([])
        self._agent = None
        self._worker = None
        # Serializza l'accesso alla cronologia: se un worker superstite (turno reale in timeout su
        # Stop) e un nuovo worker toccassero `_history` insieme, il lock evita la corruzione (Fugu #64).
        self._history_lock = threading.Lock()
        # Epoch di sessione (stesso pattern del listener in app.py): ogni `enable()`/`stop()` lo
        # incrementa. Un turno che era già in volo quando la sessione è cambiata risulta **stale** e
        # viene SCARTATO (niente save, niente risposta-fantasma dopo lo Stop — GPT/GLM #64).
        self._epoch = 0
        # Ultima API key registrata come segreto: alla ROTAZIONE (chiave diversa) si de-registra la
        # precedente, così il registro globale non accumula chiavi vecchie (GPT/GLM/Fugu #64).
        self._registered_key = ""

    # ── stato ──────────────────────────────────────────────────────────────────
    @property
    def history(self):
        """La `ConversationHistory` corrente (in RAM)."""
        return self._history

    def is_running(self) -> bool:
        """`True` se l'assistente è nello stato RUNNING (chat attiva)."""
        return self.state == RUNNING

    def _emit(self, kind, data=None):
        """Notifica un evento alla view (`on_event(kind, data)`), best-effort."""
        if self._on_event is not None:
            try:
                self._on_event(kind, data)
            except Exception:   # noqa: BLE001 — un handler della view non deve rompere il controller
                pass

    def _set_state(self, state, *, error=""):
        """Imposta lo stato e notifica la view con l'evento `state`."""
        self.state = state
        self.last_error = error
        self._emit("state", {"state": state, "error": error})

    # ── Abilita / Stop ──────────────────────────────────────────────────────────
    def _build_client(self):
        """Client iniettato, altrimenti dal factory, altrimenti `RealAnthropicClient` dalla API key
        nel keyring. Ritorna `None` se la chiave manca (→ ERROR)."""
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            return self._client_factory()
        api_key = token_store.load_api_key()
        if not api_key:
            return None
        self._register_key(api_key)
        return config_agent.RealAnthropicClient(api_key)

    def _register_key(self, key):
        """Registra la API key come segreto (Fugu #64): mascherata nei log/cronologia anche se il
        formato non combacia col pattern `sk-ant-`. Alla **rotazione** de-registra la chiave
        precedente, così il registro globale non accumula chiavi vecchie (GPT/GLM/Fugu #64)."""
        prev = self._registered_key
        if prev and prev != key:
            event_log.unregister_secret(prev)
        event_log.register_secret(key)
        self._registered_key = key

    def enable(self) -> bool:
        """Abilita l'assistente: carica la cronologia (persistente, redatta) e avvia il worker.
        Ritorna `True` se ora è RUNNING, `False` se è finito in ERROR (es. API key mancante).
        Idempotente: già RUNNING → no-op `True`."""
        if self.state == RUNNING:
            return True
        # Un worker precedente ancora in chiusura (turno reale Anthropic in volo allo Stop): NON
        # crearne un secondo (Fugu #64, race doppio worker). Si ri-tenta il join; se è ancora vivo
        # si rifiuta l'avvio con un avviso — il vecchio è daemon e uscirà da solo, l'utente riprova.
        if self._worker is not None and not self._worker.stop():
            self._emit("warning", {"reason": "worker_draining"})
            return False
        self._worker = None
        client = self._build_client()
        if client is None:
            self._set_state(ERROR, error="API key Anthropic mancante: impostala per avviare l'assistente.")
            return False
        # Nuova sessione sotto lock: incrementa l'epoch (invalida turni in volo di prima) e ricarica
        # la cronologia in modo atomico rispetto a un eventuale worker superstite (GLM #64).
        with self._history_lock:
            self._epoch += 1
            epoch = self._epoch
            self._history = config_agent.ConversationHistory.load()
            self._agent = config_agent.ConfigAgent(self._registry, client, allow_writes=False)
        # L'epoch è LEGATO al worker (closure): i turni di QUESTA sessione portano `epoch`; un worker
        # superstite di una sessione precedente porta un epoch diverso → i suoi risultati sono scartati
        # (niente scrittura/emit sulla NUOVA sessione — CodeRabbit/GPT/GLM/Fugu #64).
        self._worker = AgentWorker(
            lambda t: self._handle_message(t, epoch),
            on_result=lambda turn: self._on_worker_result(turn, epoch),
            thread_factory=threading.Thread)
        self._worker.start()
        self._set_state(RUNNING)
        self._emit("history", {"messages": self._history.messages})
        return True

    def stop(self) -> None:
        """Ferma l'assistente e il worker (teardown pulito, join con timeout). Idempotente.

        Incrementa l'epoch (i turni in volo diventano **stale** → scartati) e azzera `_agent` sotto
        lock. Se il worker termina, lo si scarta; se dopo il timeout è **ancora vivo** (turno reale
        in volo) se ne **tiene** il riferimento (Fugu #64): così un `enable()` immediato non crea un
        secondo thread sopra a quello superstite."""
        with self._history_lock:
            self._epoch += 1
            self._agent = None
        w = self._worker
        if w is not None and w.stop():
            self._worker = None
        if self.state != STOPPED:
            self._set_state(STOPPED)

    def teardown(self) -> None:
        """Chiusura finestra: alias di `stop()` per il wiring in `_on_close`."""
        self.stop()

    # ── invio messaggi ───────────────────────────────────────────────────────────
    def submit(self, user_text) -> bool:
        """Accoda un messaggio utente per l'elaborazione asincrona del worker. Ritorna `False`
        (rifiutato) se l'assistente non è RUNNING — guardia: niente elaborazione da spento."""
        text = str(user_text or "").strip()
        if not text:
            return False
        if self.state != RUNNING or self._worker is None:
            self._emit("rejected", {"reason": "not_running"})
            return False
        self._worker.submit(text)
        return True

    def _handle_message(self, text, epoch):
        """Elabora UN messaggio (chiamato dal worker), guardato dall'**epoch** LEGATO alla sessione
        che ha creato il worker:

        - se l'epoch è già stale (stop/re-enable prima ancora di partire) o `_agent` è `None` → no-op;
        - `run_turn` gira **fuori** dal lock (lento; opera su una COPIA dei messaggi, quindi un
          `replace` concorrente non lo corrompe);
        - al ritorno, **sotto lock**, se l'epoch è diventato stale (`stop()`/re-enable durante il
          turno) il risultato è SCARTATO: niente `replace`, niente `save`, niente evento `turn`
          (nessuna risposta-fantasma né mutazione della NUOVA sessione — CodeRabbit/GPT/GLM/Fugu #64);
        - altrimenti aggiorna+salva la cronologia (redatta) ed emette `turn`, tutto sotto lock.

        Ritorna sempre `None`: l'emissione del turno normale avviene qui (sotto la guardia epoch); il
        percorso d'errore del worker passa da `_on_worker_result` (anch'esso epoch-guardato)."""
        with self._history_lock:
            if epoch != self._epoch or self._agent is None:
                return None
            agent = self._agent
            base_messages = list(self._history.messages)
        turn = agent.run_turn(text, history=base_messages)   # lento: nessun lock tenuto
        with self._history_lock:
            if epoch != self._epoch:
                return None                                  # sessione cambiata → scarta
            self._history.replace(turn.messages)
            cfg = self._config_loader() or {}
            extra = [v for v in (cfg.get("chat_id", ""),
                                 cfg.get("xtrader_notification_chat_id", "")) if v]
            try:
                self._history.save(extra_secrets=extra)
            except Exception as exc:   # noqa: BLE001 — persistenza best-effort: MAI scartare il turno
                # Un errore di salvataggio (disco/permessi/serializzazione) non deve perdere la
                # risposta né rompere la conversazione (CodeRabbit #64: non solo OSError).
                self._emit("warning", {"reason": "history_save_failed",
                                       "exc": type(exc).__name__})
            self._emit("turn", {"text": turn.text, "capped": turn.capped,
                                "messages": turn.messages})
        return None

    def _on_worker_result(self, turn, epoch):
        # Il turno NORMALE è già emesso da `_handle_message` (sotto guardia epoch), che ritorna
        # `None`. Qui arriva solo il turno d'ERRORE prodotto dal worker se l'handle solleva → lo si
        # mostra SOLO se l'epoch è ancora corrente (niente errore-fantasma dopo lo Stop).
        if epoch != self._epoch:
            return
        if turn is not None and getattr(turn, "text", ""):
            self._emit("turn", {"text": turn.text, "capped": getattr(turn, "capped", False),
                                "messages": []})


class AgentWorker:
    """Worker a coda: un thread daemon consuma i messaggi e chiama `handle(text)`; il risultato è
    passato a `on_result`. `stop()` accoda una sentinella e fa il join (teardown pulito, nessun
    thread superstite). Testabile: `run_pending()` esegue il loop in modo SINCRONO su una coda
    pre-caricata, senza thread reali."""

    def __init__(self, handle, *, on_result=None, thread_factory=threading.Thread):
        self._handle = handle
        self._on_result = on_result
        self._thread_factory = thread_factory
        self._q = queue.Queue()
        self._thread = None

    def start(self) -> None:
        """Avvia il thread daemon del loop (no-op se già avviato)."""
        if self._thread is not None:
            return
        self._thread = self._thread_factory(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, text) -> None:
        """Accoda un item da elaborare."""
        self._q.put(text)

    def _process_one(self, item) -> bool:
        """Elabora UN item della coda. Ritorna `False` se era la sentinella di stop."""
        if item is _STOP:
            return False
        try:
            result = self._handle(item)
        except Exception as exc:   # noqa: BLE001 — un turno fallito non deve uccidere il worker
            if self._on_result is not None:
                self._on_result(config_agent.AgentTurn(
                    f"[errore interno: {type(exc).__name__}]", [], []))
            return True
        if self._on_result is not None:
            self._on_result(result)
        return True

    def _loop(self) -> None:
        """Loop del thread: consuma la coda finché non incontra la sentinella di stop."""
        while True:
            item = self._q.get()
            try:
                if not self._process_one(item):
                    return
            finally:
                self._q.task_done()

    def run_pending(self) -> None:
        """Esegue in modo SINCRONO gli item già in coda finché non svuota o incontra la sentinella
        (per i test: nessun thread reale)."""
        while not self._q.empty():
            item = self._q.get()
            try:
                if not self._process_one(item):
                    return
            finally:
                self._q.task_done()

    def is_alive(self) -> bool:
        """`True` se il thread del worker è avviato e ancora vivo."""
        return self._thread is not None and self._thread.is_alive()

    def stop(self, *, timeout=5.0) -> bool:
        """Ferma il worker: accoda la sentinella e fa il join del thread (se avviato). Ritorna
        `True` se il thread è terminato, `False` se dopo il timeout è ANCORA vivo (es. turno reale
        Anthropic in volo). In quel caso il riferimento al thread **non** viene azzerato (Fugu #64):
        così `start()` non ne avvia un secondo sopra a quello superstite (no doppio worker); il
        thread è daemon e terminerà da solo processando la sentinella al ritorno della chiamata.
        Idempotente."""
        self._q.put(_STOP)
        t = self._thread
        if t is None:
            return True
        if t.is_alive():
            t.join(timeout=timeout)
        if t.is_alive():
            return False              # ancora vivo: NON azzerare (evita doppio worker)
        self._thread = None
        return True
