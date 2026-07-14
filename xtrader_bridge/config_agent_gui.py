"""Tab «🤖 Assistente» (#41 PR-3) — VIEW tkinter dell'assistente di configurazione.

Come gli altri pannelli del repo: le decisioni di testo/stato/colore sono **helper puri** a livello
di modulo (testabili headless), mentre la costruzione dei widget è **verifica manuale** su Windows
(niente display in CI). La logica di ciclo di vita/thread è nel `config_agent_controller`
(testato); qui c'è solo la vista che vi delega e marshalla gli eventi sul thread GUI (`after`).
"""

from . import config_agent_controller as ctl
from . import event_log, i18n, token_store

# Palette semantica theme-aware `(chiaro, scuro)`, coerente col resto della GUI.
_COLOR_OK = ("#2e7d32", "#66bb6a")     # verde = attivo
_COLOR_ERR = ("#c62828", "#ef5350")    # rosso = errore
_COLOR_MUTED = "gray"                  # grigio = offline


# ── helper PURI (testati in CI) ─────────────────────────────────────────────────
def state_label(state) -> str:
    """Testo dell'indicatore di stato dell'assistente."""
    return {
        ctl.RUNNING: i18n.tr("🟢 Assistente ATTIVO"),
        ctl.ERROR: i18n.tr("🔴 Assistente in ERRORE"),
    }.get(state, i18n.tr("⚪ Assistente OFFLINE"))


def state_color(state):
    """Colore dell'indicatore: verde attivo, rosso errore, grigio offline."""
    return {ctl.RUNNING: _COLOR_OK, ctl.ERROR: _COLOR_ERR}.get(state, _COLOR_MUTED)


def input_enabled(state) -> bool:
    """L'input chat è utilizzabile SOLO quando l'assistente è ATTIVO."""
    return state == ctl.RUNNING


def transcript_line(role, text) -> str:
    """Una riga leggibile del trascritto: `🧑 Tu: …` / `🤖 Assistente: …`."""
    prefix = {"user": i18n.tr("🧑 Tu"), "assistant": i18n.tr("🤖 Assistente")}.get(role, role)
    return f"{prefix}: {text}"


def is_stale_event(data, current_epoch) -> bool:
    """`True` se l'evento appartiene a una sessione ormai chiusa (Stop/Enable nel frattempo) e va
    SCARTATO. Il controller emette `turn`/`warning` **fuori dal lock** (deadlock-free) e vi stampa
    l'`epoch`; qui, sul thread GUI, lo si confronta con l'epoch corrente del controller — così una
    risposta-fantasma tardiva non compare nella nuova sessione (rete di sicurezza consumer-side,
    #64). Gli eventi senza `epoch` (`state`/`history`/`rejected`/`worker_draining`) non sono mai
    stale. L'epoch è monotòno crescente: `current` è letto DOPO l'emit, quindi `current >= epoch`."""
    if not isinstance(data, dict) or "epoch" not in data:
        return False
    ev, cur = data.get("epoch"), current_epoch
    if not isinstance(ev, int) or not isinstance(cur, int):
        return False
    return ev != cur


def pending_text(data) -> str:
    """Testo del banner di conferma per una modifica config PROPOSTA dall'assistente (#41 PR-4).
    L'assistente **non** applica nulla da solo: la scrittura avviene solo se l'utente preme
    «✅ Applica». `data` è l'evento `pending` del controller (`key`/`old`/`new`)."""
    d = data or {}
    return i18n.tr("L'assistente propone: «{key}» da «{old}» a «{new}». Applicare?").format(
        key=d.get("key", ""), old=d.get("old", ""), new=d.get("new", ""))


def messages_to_transcript(messages) -> list:
    """Trasforma i messaggi (formato `ConfigAgent`) in righe di trascritto leggibili, mostrando SOLO
    il testo (i blocchi `tool_use`/`tool_result` sono dettagli interni, non parte della chat)."""
    lines = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
        else:
            text = ""
        if text.strip():
            lines.append(transcript_line(role, text.strip()))
    return lines


# ── VIEW (costruzione widget: verifica manuale) ─────────────────────────────────
class AssistantPanel:
    """Pannello della tab «🤖 Assistente». Costruisce i widget in `master` e delega al
    `controller`. Gli eventi del controller (che possono arrivare dal thread worker) sono
    marshallati sul thread GUI con `master.after(0, ...)`.

    Verifica manuale (nessun display in CI): vedi lo smoke test in `docs/internal/config_agent.md`.
    """

    def __init__(self, master, *, controller=None, config_loader=None, log=None,
                 health_provider=None, journal_path=None):
        import customtkinter as ctk  # import locale: il modulo resta importabile headless (test)
        self._ctk = ctk
        self.master = master
        self._log = log
        # `health_provider`/`journal_path` (#41 PR-10 Blocco D): inoltrati al controller così i tool
        # `explain_health`/`why_discarded` leggono lo stato LIVE dei semafori e il diario dell'app.
        self.controller = controller or ctl.AgentController(
            config_loader=config_loader, on_event=self._on_event,
            health_provider=health_provider, journal_path=journal_path)
        if controller is not None:
            # se il controller è iniettato, aggancia comunque gli eventi alla view
            self.controller._on_event = self._on_event
        self._build()
        self._refresh_state(self.controller.state, self.controller.last_error)

    # -- costruzione --
    def _build(self):
        """Costruisce i widget del pannello (campo API key, Abilita/Stop, trascritto, input)."""
        ctk = self._ctk
        outer = ctk.CTkFrame(self.master, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=8, pady=6)

        # Riga API key (mascherata) + salvataggio nel keyring.
        keyrow = ctk.CTkFrame(outer, fg_color="transparent")
        keyrow.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(keyrow, text=i18n.tr("API key Anthropic:")).pack(side="left", padx=(4, 4))
        self._key_var = ctk.StringVar(value="")
        ctk.CTkEntry(keyrow, textvariable=self._key_var, show="●", width=280,
                     placeholder_text=i18n.tr("incollala qui (salvata solo nel keyring)")).pack(
            side="left", padx=2)
        ctk.CTkButton(keyrow, text=i18n.tr("💾 Salva chiave"), width=120,
                      command=self._save_key).pack(side="left", padx=4)

        # Riga stato + Abilita/Stop.
        ctrlrow = ctk.CTkFrame(outer, fg_color="transparent")
        ctrlrow.pack(fill="x", pady=(0, 4))
        self._state_lbl = ctk.CTkLabel(ctrlrow, text=state_label(ctl.STOPPED),
                                       text_color=state_color(ctl.STOPPED))
        self._state_lbl.pack(side="left", padx=(4, 8))
        self._enable_btn = ctk.CTkButton(ctrlrow, text=i18n.tr("▶ Abilita"), width=110,
                                         command=self._enable)
        self._enable_btn.pack(side="left", padx=2)
        self._stop_btn = ctk.CTkButton(ctrlrow, text=i18n.tr("⏹ Stop"), width=90,
                                       command=self._stop)
        self._stop_btn.pack(side="left", padx=2)

        # Trascritto conversazione (sola lettura) + input.
        self._transcript = ctk.CTkTextbox(outer, height=180, wrap="word")
        self._transcript.pack(fill="both", expand=True, pady=(2, 4))
        self._transcript.configure(state="disabled")

        # Banner CONFERMA (nascosto di default): compare quando l'assistente PROPONE una modifica
        # config; SOLO il click su «✅ Applica» scrive (server-side gate, review #65). Viene
        # ri-`pack`-ato sopra la riga di input (`before=`) quando arriva una proposta.
        self._pending_bar = ctk.CTkFrame(outer, fg_color=("#fff3cd", "#4d3f00"))
        self._pending_lbl = ctk.CTkLabel(self._pending_bar, text="", wraplength=420, justify="left")
        self._pending_lbl.pack(side="left", padx=(6, 6), pady=4)
        ctk.CTkButton(self._pending_bar, text=i18n.tr("✅ Applica"), width=100,
                      command=self._apply_pending).pack(side="left", padx=2)
        ctk.CTkButton(self._pending_bar, text=i18n.tr("✖ Annulla"), width=90,
                      fg_color="gray", command=self._cancel_pending).pack(side="left", padx=2)
        # non fare pack ora: resta nascosto finché non arriva un evento `pending`.

        inrow = ctk.CTkFrame(outer, fg_color="transparent")
        inrow.pack(fill="x")
        self._input_var = ctk.StringVar(value="")
        self._input = ctk.CTkEntry(inrow, textvariable=self._input_var,
                                   placeholder_text=i18n.tr("scrivi un ordine di configurazione…"))
        self._input.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self._input.bind("<Return>", lambda _e: self._send())
        self._send_btn = ctk.CTkButton(inrow, text=i18n.tr("Invia"), width=90, command=self._send)
        self._send_btn.pack(side="left", padx=2)

    # -- azioni GUI --
    def _save_key(self):
        """Salva la API key nel keyring e la registra come segreto; svuota il campo."""
        key = self._key_var.get().strip()
        if not key:
            return
        if token_store.save_api_key(key):
            event_log.register_secret(key)   # mascherato nei log/cronologia
            self._key_var.set("")            # non lasciare la chiave nel campo
            self._append(i18n.tr("✓ Chiave salvata nel keyring."))
        else:
            self._append(i18n.tr("⚠️ Keyring non disponibile: chiave NON salvata."))

    def _enable(self):
        """Callback «Abilita»: avvia l'assistente."""
        self.controller.enable()

    def _stop(self):
        """Callback «Stop»: ferma l'assistente."""
        self.controller.stop()

    def _send(self):
        """Callback «Invia»: accoda il messaggio utente (se l'assistente è attivo)."""
        text = self._input_var.get().strip()
        if not text:
            return
        if self.controller.submit(text):
            self._append(transcript_line("user", text))
            self._input_var.set("")
        else:
            self._append(i18n.tr("⚠️ Abilita l'assistente prima di inviare messaggi."))

    def _apply_pending(self):
        """Callback «✅ Applica»: **l'utente** conferma la modifica proposta → la scrive (unico punto
        di scrittura config; il modello non può arrivarci)."""
        self.controller.apply_pending()

    def _cancel_pending(self):
        """Callback «✖ Annulla»: scarta la modifica proposta senza scrivere."""
        self.controller.cancel_pending()

    def _show_pending(self, data):
        """Mostra il banner di conferma con l'anteprima della modifica proposta."""
        self._pending_lbl.configure(text=pending_text(data))
        self._pending_bar.pack(fill="x", pady=(0, 4), before=self._input_bar())

    def _hide_pending(self):
        """Nasconde il banner di conferma (proposta applicata/annullata o sessione chiusa)."""
        try:
            self._pending_bar.pack_forget()
        except Exception:   # noqa: BLE001 — widget già distrutto (teardown): best-effort
            pass

    def _input_bar(self):
        """La riga di input (per posizionare il banner subito sopra)."""
        return self._input.master

    # -- eventi del controller (marshallati sul thread GUI) --
    def _on_event(self, kind, data):
        """Riceve un evento del controller (anche dal thread worker) e lo marshalla sul thread GUI."""
        try:
            self.master.after(0, lambda: self._handle_event(kind, data))
        except Exception:   # noqa: BLE001 — root Tk distrutta / assente (teardown): best-effort
            pass

    def _handle_event(self, kind, data):
        """Applica un evento del controller ai widget (sul thread GUI)."""
        # Rete di sicurezza consumer-side (#64): il controller emette `turn`/`warning`/`pending`
        # FUORI dal lock e vi stampa l'`epoch`; se nel frattempo la sessione è cambiata (Stop/Enable)
        # l'evento è di una sessione chiusa → scartato qui, così non compare una risposta-fantasma.
        if kind in ("turn", "warning", "pending") and is_stale_event(
                data, self.controller.current_epoch()):
            return
        if kind == "pending":
            self._show_pending(data)
            return
        if kind == "pending_cleared":
            # Sorgente di verità = la proposta CORRENTE del controller, letta qui sul thread GUI (non
            # ci si fida dell'ordine degli eventi): se nel frattempo è subentrata una proposta più
            # nuova la si (ri)mostra, altrimenti si nasconde il banner. Chiude la finestra di race tra
            # `pending_cleared` (emesso fuori lock, invariante anti-deadlock #64) e uno stage
            # concorrente — stessa filosofia di `is_stale_event` (GPT/Fable #65).
            cur = self.controller.pending()
            if cur:
                self._show_pending(cur)
            else:
                self._hide_pending()
            return
        if kind == "state":
            self._refresh_state(data.get("state"), data.get("error", ""))
        elif kind == "turn":
            txt = (data or {}).get("text", "")
            if txt:
                self._append(transcript_line("assistant", txt))
            if (data or {}).get("capped"):
                self._append(i18n.tr("⚠️ (l'assistente ha raggiunto il limite di passi per turno)"))
        elif kind == "history":
            # Ricarica la cronologia nel trascritto: prima SVUOTA (Fable #64), così un
            # Abilita→Stop→Abilita non duplica le righe già mostrate.
            self._clear_transcript()
            for line in messages_to_transcript((data or {}).get("messages", [])):
                self._append(line)
        elif kind == "rejected":
            self._append(i18n.tr("⚠️ Assistente non attivo."))
        elif kind == "warning" and (data or {}).get("reason") == "history_save_failed":
            self._append(i18n.tr("⚠️ Cronologia non salvata (disco/permessi)."))

    def _refresh_state(self, state, error=""):
        """Aggiorna indicatore di stato e abilitazione dell'input in base allo stato."""
        self._state_lbl.configure(text=state_label(state), text_color=state_color(state))
        enabled = input_enabled(state)
        self._input.configure(state="normal" if enabled else "disabled")
        self._send_btn.configure(state="normal" if enabled else "disabled")
        if state == ctl.ERROR and error:
            self._append(f"⚠️ {error}")

    def _clear_transcript(self):
        self._transcript.configure(state="normal")
        self._transcript.delete("1.0", "end")
        self._transcript.configure(state="disabled")

    def _append(self, line):
        self._transcript.configure(state="normal")
        self._transcript.insert("end", line + "\n")
        self._transcript.see("end")
        self._transcript.configure(state="disabled")
        if self._log is not None:
            try:
                self._log(event_log.redact_secrets(line))
            except Exception:   # noqa: BLE001 — logging best-effort
                pass

    def teardown(self):
        """Chiusura finestra: ferma il controller/worker (join). Chiamato da `app._on_close`."""
        self.controller.teardown()
