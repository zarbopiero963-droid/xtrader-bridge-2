"""Tab «Betfair Sync» del bridge (widget customtkinter) — issue #86 PR-P3.

SOLO widget e wiring: tutta la logica (abilitazione pulsanti, salva/cancella
credenziali, logout, normalizzazione campi) sta in `sync_tab_controller` ed è
testata in CI. Questo modulo NON è testato in CI (richiede un display): verifica
manuale su Windows (vedi checklist nel PR/roadmap).

Campi: Delayed App Key, Username/Password Betfair.it, percorsi Certificato (.crt/.pem)
e Private key (.key), selezione sport, «Giorni avanti», stato login/ultima sync/stato
sync. Pulsanti: Salva credenziali, Accedi, Sincronizza ora, Logout, Cancella
credenziali salvate. Le credenziali sono globali locali (keyring), non per profilo;
il sessionToken vive solo in RAM; nessuna chiamata betting (read-only).
"""

import customtkinter as ctk

from .credential_store import BetfairCredentials
from .session import BetfairSession
from .sync_tab_controller import SPORTS, BetfairSyncController, normalize_days_ahead


class BetfairSyncPanel(ctk.CTkFrame):
    """Pannello della tab Betfair Sync.

    `session`: la `BetfairSession` condivisa col bridge (token in RAM). `on_login` /
    `on_sync` sono callback opzionali agganciati nelle PR successive (auth/sync); se
    assenti, i pulsanti relativi restano comunque governati dal controller."""

    def __init__(self, master=None, session: BetfairSession = None,
                 on_login=None, on_sync=None):
        super().__init__(master)
        self.controller = BetfairSyncController(session=session)
        self._on_login = on_login
        self._on_sync = on_sync
        self._sync_in_progress = False
        self._build_ui()
        self._reload()
        self._refresh_buttons()

    # ── costruzione UI ────────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text="🔵  Betfair Sync (locale, read-only)",
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))

        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=12, pady=6)

        self._entries = {}
        rows = (
            ("app_key", "Delayed App Key", True),
            ("username", "Username Betfair.it", False),
            ("password", "Password Betfair.it", True),
            ("cert_path", "Certificato (.crt/.pem)", False),
            ("key_path", "Private key (.key)", False),
        )
        for i, (key, label, secret) in enumerate(rows):
            ctk.CTkLabel(form, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            entry = ctk.CTkEntry(form, width=320, show="•" if secret else "")
            entry.grid(row=i, column=1, sticky="we", padx=8, pady=4)
            entry.bind("<KeyRelease>", lambda _e: self._refresh_buttons())
            self._entries[key] = entry

        # Sport + giorni avanti.
        opts = ctk.CTkFrame(self)
        opts.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(opts, text="Sport").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self._sport_vars = {}
        for j, sport in enumerate(SPORTS):
            var = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(opts, text=sport, variable=var).grid(
                row=0, column=1 + j, sticky="w", padx=6, pady=4)
            self._sport_vars[sport] = var
        ctk.CTkLabel(opts, text="Giorni avanti").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self._days_entry = ctk.CTkEntry(opts, width=60)
        self._days_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        # Stato.
        status = ctk.CTkFrame(self)
        status.pack(fill="x", padx=12, pady=6)
        self._login_status = ctk.CTkLabel(status, text="Stato login: —")
        self._login_status.pack(anchor="w", padx=8, pady=2)
        self._last_sync = ctk.CTkLabel(status, text="Ultima sync: —")
        self._last_sync.pack(anchor="w", padx=8, pady=2)
        self._sync_status = ctk.CTkLabel(status, text="Stato sync: —")
        self._sync_status.pack(anchor="w", padx=8, pady=2)
        # Esito dell'ultima azione su credenziali (salva/cancella): un fallimento del
        # keyring NON deve sembrare un successo (Codex). Vuoto = nessun messaggio.
        self._action_status = ctk.CTkLabel(status, text="")
        self._action_status.pack(anchor="w", padx=8, pady=2)

        # Pulsanti.
        btns = ctk.CTkFrame(self)
        btns.pack(fill="x", padx=12, pady=(6, 12))
        self._buttons = {
            "save_credentials": ctk.CTkButton(btns, text="💾 Salva credenziali", command=self._save),
            "login": ctk.CTkButton(btns, text="🔑 Accedi", command=self._login),
            "sync_now": ctk.CTkButton(btns, text="🔄 Sincronizza ora", command=self._sync),
            "logout": ctk.CTkButton(btns, text="🚪 Logout", command=self._logout),
            "delete_credentials": ctk.CTkButton(btns, text="🗑️ Cancella credenziali salvate",
                                                command=self._delete),
        }
        for b in self._buttons.values():
            b.pack(side="left", padx=4)

    # ── dati form ↔ controller ────────────────────────────────────────────────
    def _form_credentials(self) -> BetfairCredentials:
        return BetfairCredentials(**{k: self._entries[k].get().strip()
                                     for k in self._entries})

    def _reload(self):
        """Popola i campi alla riapertura: i segreti restano mascherati, i percorsi
        file in chiaro (vedi `credential_store.masked`)."""
        view = self.controller.load_masked()
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            entry.insert(0, view.get(key, ""))
        self._days_entry.delete(0, "end")
        self._days_entry.insert(0, str(normalize_days_ahead(self._days_entry.get())))

    def _refresh_buttons(self):
        # Completezza valutata sulle credenziali REALI (i segreti mascherati ma
        # presenti contano come valorizzati), non sulla maschera mostrata.
        complete = self.controller.resolve_credentials(
            self._form_credentials()).is_complete()
        states = self.controller.button_states(
            credentials_complete=complete, sync_in_progress=self._sync_in_progress)
        for key, enabled in states.items():
            self._buttons[key].configure(state="normal" if enabled else "disabled")
        self._login_status.configure(
            text="Stato login: ✅ connesso" if self.controller.is_logged_in
            else "Stato login: — non connesso")

    # ── azioni ────────────────────────────────────────────────────────────────
    def _save(self):
        # Risolvi i campi mascherati nei valori reali PRIMA di salvare: un segreto non
        # ridigitato non deve sovrascrivere il keyring con la maschera (Codex).
        resolved = self.controller.resolve_credentials(self._form_credentials())
        if self.controller.save_credentials(resolved):
            self._action_status.configure(text="✅ Credenziali salvate.")
            self._reload()                  # solo dopo un salvataggio riuscito
        else:
            # Fallimento keyring: NON ricaricare (non perdere ciò che l'utente ha
            # digitato) e segnalare l'errore invece di farlo sembrare un successo.
            self._action_status.configure(
                text="⚠️ Salvataggio credenziali FALLITO (keyring non disponibile). "
                     "Riprova; i dati nel form non sono stati persi.")
        self._refresh_buttons()

    def _login(self):
        if self._on_login:
            # Passa le credenziali REALI risolte, mai la maschera.
            self._on_login(self.controller.resolve_credentials(self._form_credentials()))
        self._refresh_buttons()

    def _selected_sports(self):
        """Gli sport con checkbox selezionata (per la sync)."""
        return [sport for sport, var in self._sport_vars.items() if var.get()]

    def _sync(self):
        if self._on_sync:
            self._on_sync(self._selected_sports())
        self._refresh_buttons()

    def _logout(self):
        self.controller.logout()
        self._action_status.configure(text="")
        self._refresh_buttons()

    def _delete(self):
        if self.controller.delete_saved_credentials():
            self._action_status.configure(text="🗑️ Credenziali cancellate.")
            self._reload()                  # solo dopo una cancellazione riuscita
        else:
            self._action_status.configure(
                text="⚠️ Cancellazione credenziali FALLITA (keyring non disponibile). "
                     "Le credenziali potrebbero essere ancora memorizzate.")
        self._refresh_buttons()
