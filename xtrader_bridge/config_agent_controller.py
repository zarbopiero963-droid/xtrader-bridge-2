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

from . import config_agent, config_store, token_store

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

    # ── stato ──────────────────────────────────────────────────────────────────
    @property
    def history(self):
        return self._history

    def is_running(self) -> bool:
        return self.state == RUNNING

    def _emit(self, kind, data=None):
        if self._on_event is not None:
            try:
                self._on_event(kind, data)
            except Exception:   # noqa: BLE001 — un handler della view non deve rompere il controller
                pass

    def _set_state(self, state, *, error=""):
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
        return config_agent.RealAnthropicClient(api_key)

    def enable(self) -> bool:
        """Abilita l'assistente: carica la cronologia (persistente, redatta) e avvia il worker.
        Ritorna `True` se ora è RUNNING, `False` se è finito in ERROR (es. API key mancante).
        Idempotente: già RUNNING → no-op `True`."""
        if self.state == RUNNING:
            return True
        client = self._build_client()
        if client is None:
            self._set_state(ERROR, error="API key Anthropic mancante: impostala per avviare l'assistente.")
            return False
        self._history = config_agent.ConversationHistory.load()
        self._agent = config_agent.ConfigAgent(self._registry, client, allow_writes=False)
        self._worker = AgentWorker(self._handle_message, on_result=self._on_worker_result,
                                   thread_factory=threading.Thread)
        self._worker.start()
        self._set_state(RUNNING)
        self._emit("history", {"messages": self._history.messages})
        return True

    def stop(self) -> None:
        """Ferma l'assistente e il worker (teardown pulito, join con timeout). Idempotente."""
        w, self._worker = self._worker, None
        if w is not None:
            w.stop()
        self._agent = None
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

    def _handle_message(self, text):
        """Elabora UN messaggio (chiamato dal worker): esegue il turno, aggiorna e SALVA la
        cronologia (redatta), e ritorna il `AgentTurn`. Sincrono e testabile."""
        turn = self._agent.run_turn(text, history=self._history.messages)
        self._history.replace(turn.messages)
        cfg = self._config_loader() or {}
        extra = [cfg.get("chat_id", ""), cfg.get("xtrader_notification_chat_id", "")]
        try:
            self._history.save(extra_secrets=extra)
        except OSError:
            # Persistenza best-effort: un disco pieno/permessi non deve rompere la conversazione.
            self._emit("warning", {"reason": "history_save_failed"})
        return turn

    def _on_worker_result(self, turn):
        self._emit("turn", {"text": getattr(turn, "text", ""),
                            "capped": getattr(turn, "capped", False),
                            "messages": getattr(turn, "messages", [])})


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
        if self._thread is not None:
            return
        self._thread = self._thread_factory(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, text) -> None:
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

    def stop(self, *, timeout=5.0) -> None:
        """Ferma il worker: accoda la sentinella e fa il join del thread (se avviato). Idempotente."""
        self._q.put(_STOP)
        t, self._thread = self._thread, None
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
