"""Controller dell'assistente di configurazione (#41 PR-3) — logica di ciclo di vita, testabile.

Separa la **logica** (macchina a stati Abilita/Stop, invio messaggi, persistenza cronologia,
teardown del thread) dalla **view** tkinter (`config_agent_gui`), come il resto del repo. Tutto qui
è headless e offline-testabile: il client Anthropic è iniettabile (i test usano un finto), il
worker può essere pilotato in modo sincrono.

Sicurezza: `enable()` abilita SOLO la chat, **non** avvia il listener live né la modalità reale; le
azioni safety-critical restano bloccate dalle guardie di `config_agent` (hard block). La scrittura
config è abilitata GATED (`allow_writes=True`, #41 PR-4): l'assistente può impostare solo un piccolo
insieme di chiavi NON safety-critical (`set_config_value` — allowlist/denylist + conferma esplicita);
token, filtro chat, modalità/CSV, limiti scommesse e parser restano non scrivibili. La cronologia è
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
                 config_saver=None, history=None, parsers_dir=None, on_event=None, logger=None):
        self._config_loader = config_loader or config_store.load_config
        self._config_saver = config_saver or config_store.save_config
        self._parsers_dir = parsers_dir
        self._on_event = on_event
        self._logger = logger
        self._client = client
        self._client_factory = client_factory
        self.state = STOPPED
        self.last_error = ""
        # Modifica config PROPOSTA dall'assistente e in attesa di conferma UMANA (#41 PR-4, review
        # #65): il tool `set_config_value` non scrive mai — chiama `_stage_pending`; la scrittura
        # vera avviene SOLO da `apply_pending()` (pulsante «Applica» dell'utente, sul thread GUI).
        self._pending = None
        self._pending_lock = threading.Lock()
        # Epoch del turno CORRENTE per-thread (thread-local): il tool `set_config_value` gira dentro
        # `_handle_message` sul thread worker e chiama `_stage_pending`; leggendo qui l'epoch del suo
        # turno (non l'epoch vivo) una proposta di un worker STALE (post Stop/Enable) viene scartata
        # invece di comparire nella nuova sessione. Worker concorrenti hanno ciascuno il proprio.
        self._turn_ctx = threading.local()
        # Registry con i tool read-only (stato VIVO redatto) e i tool di scrittura config GATED
        # (#41 PR-4): questi ultimi sono offerti al modello solo con `allow_writes=True` (vedi enable)
        # e **non scrivono**: propongono soltanto (`on_proposal`), la conferma è umana via UI.
        self._registry = config_agent.build_default_registry(
            config_loader=self._config_loader, on_proposal=self._stage_pending,
            parsers_dir=parsers_dir, logger=logger)
        self._history = history if history is not None else config_agent.ConversationHistory([])
        self._agent = None
        self._worker = None
        # Serializza l'accesso alla cronologia. Principio (Fable/Fugu/GPT #64): NON si tiene mai il
        # lock **attraverso una callback** `on_event` (evita l'inversione di lock / deadlock). La
        # decisione «questo turno è valido» (check epoch + save) è atomica SOTTO il lock; l'`_emit`
        # avviene FUORI dal lock. Per non mostrare una risposta di una sessione ormai chiusa
        # (Stop/Enable avvenuto nel frattempo), ogni evento porta l'`epoch`: il **consumer** (la GUI,
        # a thread singolo) scarta gli eventi con epoch non corrente — race-free senza lock in emit.
        self._history_lock = threading.Lock()
        # Epoch di sessione (stesso pattern del listener in app.py): ogni `enable()`/`stop()` lo
        # incrementa. Un turno che era già in volo quando la sessione è cambiata risulta **stale** e
        # viene SCARTATO (niente save, niente risposta-fantasma dopo lo Stop — GPT/GLM #64).
        self._epoch = 0

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
        """Registra la API key come segreto: mascherata nei log/cronologia anche se il formato non
        combacia col pattern `sk-ant-` (Fugu #64). **NON** de-registra le chiavi precedenti
        (Fable/GPT #64): una chiave ruotata può restare valida e comparire in cronologia/log residui
        o nell'output di un worker stale → va tenuta redatta per la vita del processo. Il registro è
        un **set**: registrare la stessa chiave più volte è idempotente (nessun accumulo per la
        stessa chiave; chiavi diverse restano tutte redatte, che è l'esito sicuro)."""
        event_log.register_secret(key)

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
            # PR-4: la scrittura config GATED è ora abilitata (`allow_writes=True`). Restano attive
            # tutte le guardie: hard-block `FORBIDDEN_TOOLS`, allowlist/denylist delle chiavi
            # scrivibili in `set_config_value` (niente token/filtro chat/modalità/CSV/limiti/parser)
            # e il gate di conferma esplicita per ogni scrittura.
            self._agent = config_agent.ConfigAgent(self._registry, client, allow_writes=True)
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
        # Una sessione fermata non deve trattenere una proposta pendente (sarebbe di una sessione
        # chiusa): la si scarta e si notifica la GUI di nascondere il banner «Applica».
        with self._pending_lock:
            had_pending = self._pending is not None
            self._pending = None
        if had_pending:
            self._emit("pending_cleared", {"epoch": self._epoch})
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
          turno) il risultato è SCARTATO: niente `replace`, niente `save`, niente evento (nessuna
          risposta-fantasma né mutazione della NUOVA sessione — CodeRabbit/GPT/GLM/Fugu #64);
        - altrimenti aggiorna+salva la cronologia (redatta) SOTTO lock, poi emette `turn` (e
          l'eventuale `warning` di save fallito) **FUORI dal lock**.

        L'`_emit` avviene fuori dal lock perché `on_event` è una **callback**: tenerla sotto lock
        deadlocca se l'handler attende un altro thread che chiama `stop()`/`enable()`, o vi rientra
        (Fable/Fugu #64). Per non mostrare la risposta di una sessione già chiusa, ogni evento porta
        l'`epoch`: il consumer (GUI, thread singolo) scarta quelli non correnti — race-free senza
        lock in emit. Ritorna sempre `None`: il turno normale è emesso qui; il percorso d'errore del
        worker passa da `_on_worker_result` (anch'esso epoch-guardato)."""
        with self._history_lock:
            if epoch != self._epoch or self._agent is None:
                return None
            agent = self._agent
            base_messages = list(self._history.messages)
        # Pubblica l'epoch di QUESTO turno per il tool `set_config_value` (→ `_stage_pending`), così
        # una proposta è legata alla sessione che l'ha generata (thread-local: no race tra worker).
        self._turn_ctx.epoch = epoch
        try:
            turn = agent.run_turn(text, history=base_messages)   # lento: nessun lock tenuto
        finally:
            self._turn_ctx.epoch = None
        # Replace+save ATOMICI sotto lock rispetto all'epoch (niente TOCTOU sui DATI). Se la sessione
        # è cambiata (stop/re-enable durante il turno) si scarta TUTTO — nessun evento emesso.
        save_failed_exc = None
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
                save_failed_exc = type(exc).__name__
        # Emissione FUORI dal lock (deadlock-free anche se l'handler chiama stop()/enable() o attende
        # un altro thread). Ogni evento porta l'`epoch`: il consumer scarta quelli di sessioni chiuse.
        if save_failed_exc is not None:
            self._emit("warning", {"reason": "history_save_failed", "exc": save_failed_exc,
                                   "epoch": epoch})
        self._emit("turn", {"text": turn.text, "capped": turn.capped,
                            "messages": turn.messages, "epoch": epoch})
        return None

    def _on_worker_result(self, turn, epoch):
        """Il turno NORMALE è già emesso da `_handle_message` (che ritorna `None`); qui arriva solo
        il turno d'ERRORE del worker se l'handle solleva → mostrato SOLO se l'epoch è ancora corrente
        allo snapshot. Il check è sotto lock; l'`_emit` (callback) avviene FUORI dal lock, con
        l'`epoch` stampato così il consumer scarta un errore-fantasma emesso dopo un Stop tardivo."""
        if turn is None or not getattr(turn, "text", ""):
            return
        with self._history_lock:
            if epoch != self._epoch:
                return
            text, capped = turn.text, getattr(turn, "capped", False)
        self._emit("turn", {"text": text, "capped": capped, "messages": [], "epoch": epoch})

    def current_epoch(self) -> int:
        """Epoch di sessione corrente (lettura atomica sotto GIL). La GUI la legge al momento di
        applicare un evento per scartare i `turn`/`warning` di una sessione ormai chiusa
        (Stop/Enable nel frattempo) — la rete di sicurezza consumer-side dell'emit senza lock."""
        return self._epoch

    # ── modifica config PROPOSTA + conferma UMANA (#41 PR-4, review #65) ─────────
    def _stage_pending(self, key, new, old) -> None:
        """Chiamato dal tool `set_config_value` (thread worker) quando l'assistente PROPONE una
        modifica valida. NON scrive: registra la modifica pendente (legata all'`epoch` del turno) ed
        emette l'evento `pending` FUORI dal lock, così la GUI mostra il pulsante «Applica». Una nuova
        proposta sostituisce quella non ancora applicata. Una proposta di un turno **stale** (worker
        di una sessione già chiusa da Stop/Enable) viene **ignorata**: né staged né emessa."""
        epoch = getattr(self._turn_ctx, "epoch", None)
        if epoch is None:
            epoch = self._epoch                       # chiamata fuori da un turno (es. test): epoch vivo
        with self._pending_lock:
            if epoch != self._epoch:
                return                                # sessione chiusa → nessuna proposta-fantasma
            self._pending = {"key": key, "new": new, "old": old, "epoch": epoch}
        self._emit("pending", {"key": key, "new": new, "old": old, "epoch": epoch})

    def pending(self):
        """La modifica pendente corrente (dict o `None`) — lettura per la GUI/test."""
        with self._pending_lock:
            return dict(self._pending) if self._pending else None

    def apply_pending(self) -> bool:
        """**Applica** la modifica pendente — chiamato SOLO dall'utente (pulsante «Applica», thread
        GUI). È l'UNICO punto che scrive la config: il modello non può arrivarci. Ritorna `True` se
        scritta, `False` altrimenti (niente pending / sessione cambiata / config non valida / chiave
        cambiata sotto di noi / save fallito).

        Fail-safe e anti-TOCTOU (Fugu/Fable #65):
        - la config viene ri-letta qui (sul thread GUI, come «💾 Salva Config»); se il load **non** dà
          un dict valido e non vuoto si **abortisce** (mai un fallback a `{}`, che scriverebbe una
          config quasi vuota azzerando chat_id/csv_path/bridge_mode/limiti). Il pending resta (retry);
        - si scrive **solo** se il valore attuale della chiave coincide ancora con quello su cui si
          basava la proposta (`old`): un cambio CONCORRENTE della stessa chiave (es. GUI «Salva»)
          **non** viene sovrascritto — la proposta stantia è annullata con avviso;
        - si opera su una **copia** (niente mutazione del dict condiviso, niente mutazione parziale se
          il save fallisce) e si tocca solo la chiave proposta (le altre restano quelle fresche).
        La proposta è scartata se l'epoch è cambiato (Stop/Enable)."""
        with self._pending_lock:
            p = self._pending
            if p is None or p["epoch"] != self._epoch:
                self._pending = None
                return False
            key, new, old = p["key"], p["new"], p["old"]
        cfg = self._config_loader()
        # Fail-safe: senza una config valida NON si scrive (Fugu #65). Pending mantenuto → l'utente
        # può ritentare quando la config torna leggibile.
        if not isinstance(cfg, dict) or not cfg:
            self._emit("turn", {"text": "⚠️ Config non disponibile: modifica NON applicata, riprova.",
                                "capped": False, "messages": [], "epoch": self._epoch})
            return False
        # Anti-clobber della chiave PROPOSTA (Fugu #65): se è cambiata sotto di noi (modifica
        # concorrente), la proposta è stantia → annulla senza sovrascrivere.
        if cfg.get(key) != old:
            with self._pending_lock:
                self._pending = None
            self._emit("pending_cleared", {"epoch": self._epoch})
            self._emit("turn", {"text": f"⚠️ «{key}» è cambiato nel frattempo (ora "
                                f"«{cfg.get(key)}»): proposta annullata, rilanciala se serve.",
                                "capped": False, "messages": [], "epoch": self._epoch})
            return False
        new_cfg = dict(cfg)                  # copia: niente mutazione del dict condiviso né parziale
        new_cfg[key] = new                   # tocca SOLO la chiave proposta (le altre restano fresche)
        # Un errore del saver (o del loader) NON deve crashare il thread GUI: si tratta come save
        # fallito (ritorna `False`, messaggio d'errore, mai falso «Fatto» — GLM/Fable #65).
        try:
            ok, status = config_agent._save_outcome(self._config_saver(new_cfg))
        except Exception:   # noqa: BLE001 — save fallito/eccezione: fail-safe, il pending resta scartato
            ok, status = False, config_store.SAVE_DISK_ERROR
        with self._pending_lock:
            self._pending = None
        self._emit("pending_cleared", {"epoch": self._epoch})
        if ok:
            self._emit("turn", {"text": f"✓ «{key}» impostato a «{new}» (era «{old}»).",
                                "capped": False, "messages": [], "epoch": self._epoch})
        else:
            msg = config_store.save_status_message(status) if status else ""
            self._emit("turn", {"text": f"⚠️ Salvataggio non riuscito per «{key}»." +
                                (f" {msg}" if msg else ""),
                                "capped": False, "messages": [], "epoch": self._epoch})
        return ok

    def cancel_pending(self) -> None:
        """Annulla la modifica pendente senza applicarla (pulsante «Annulla», thread GUI)."""
        with self._pending_lock:
            had = self._pending is not None
            self._pending = None
        if had:
            self._emit("pending_cleared", {"epoch": self._epoch})


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
        `True` se il thread è terminato (o si sta auto-fermando, vedi sotto), `False` solo se dopo il
        timeout è ANCORA vivo per un turno **cross-thread** in volo (es. chiamata reale Anthropic). In
        quel caso il riferimento **non** viene azzerato (Fugu #64): `start()` non ne avvia un secondo
        sopra al superstite (no doppio worker); il thread è daemon e terminerà da solo processando la
        sentinella. Idempotente."""
        self._q.put(_STOP)
        t = self._thread
        if t is None:
            return True
        if t is threading.current_thread():
            # `stop()` invocato DALLO STESSO thread worker (handler sincrono che rientra): non si può
            # (né si deve) fare il join di sé (Fable #64: niente RuntimeError «cannot join current
            # thread»). La sentinella è già in coda e il loop uscirà appena la chiamata rientra →
            # il worker si sta AUTO-fermando: ritorna `True` così i call-site (es. `enable()`) non lo
            # leggono come «stop fallito» (Fugu #64: nessuna regressione sul valore di ritorno).
            return True
        if t.is_alive():
            t.join(timeout=timeout)
        if t.is_alive():
            return False              # ancora vivo: NON azzerare (evita doppio worker)
        self._thread = None
        return True
