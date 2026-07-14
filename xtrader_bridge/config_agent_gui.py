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

    def __init__(self, master, *, controller=None, config_loader=None, log=None):
        import customtkinter as ctk  # import locale: il modulo resta importabile headless (test)
        self._ctk = ctk
        self.master = master
        self._log = log
        self.controller = controller or ctl.AgentController(
            config_loader=config_loader, on_event=self._on_event)
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

    # -- eventi del controller (marshallati sul thread GUI) --
    def _on_event(self, kind, data):
        """Riceve un evento del controller (anche dal thread worker) e lo marshalla sul thread GUI."""
        try:
            self.master.after(0, lambda: self._handle_event(kind, data))
        except Exception:   # noqa: BLE001 — root Tk distrutta / assente (teardown): best-effort
            pass

    def _handle_event(self, kind, data):
        """Applica un evento del controller ai widget (sul thread GUI)."""
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
