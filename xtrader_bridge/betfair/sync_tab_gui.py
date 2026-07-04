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

import os

import customtkinter as ctk

from .credential_store import BetfairCredentials
from .session import BetfairSession
from .auto_sync import normalize_hour
from .sync_tab_controller import SPORTS, BetfairSyncController, normalize_days_ahead

# #285: pulsante «📁 Sfoglia…» per i campi PERCORSO (certificato / private key). Solo file
# ESISTENTI (`askopenfilename`, non `asksaveasfilename`): i file cert/key li crea l'utente.
# Titolo + filtri per campo. Solo il PERCORSO viene letto/salvato, mai il contenuto della chiave.
_BROWSE_FILETYPES = {
    "cert_path": ("Scegli il certificato Betfair (.crt/.pem)",
                  [("Certificato", "*.crt *.pem"), ("Tutti i file", "*.*")]),
    "key_path": ("Scegli la private key Betfair (.key)",
                 [("Private key", "*.key"), ("Tutti i file", "*.*")]),
}


class BetfairSyncPanel(ctk.CTkFrame):
    """Pannello della tab Betfair Sync.

    `session`: la `BetfairSession` condivisa col bridge (token in RAM). `on_login` /
    `on_sync` sono callback opzionali agganciati nelle PR successive (auth/sync); se
    assenti, i pulsanti relativi restano comunque governati dal controller."""

    def __init__(self, master=None, session: BetfairSession = None,
                 on_login=None, on_sync=None, autosync=None, on_autosync_change=None,
                 on_invalidate=None):
        super().__init__(master)
        self.controller = BetfairSyncController(session=session)
        self._on_login = on_login
        self._on_sync = on_sync
        # Invalidazione del login in volo (logout/«Cancella credenziali»): così il
        # completamento di un login partito PRIMA non riporta la sessione a «connesso»
        # dopo l'azione utente (Codex su #184 H1).
        self._on_invalidate = on_invalidate
        self._autosync = autosync or {}
        self._on_autosync_change = on_autosync_change
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
            # Campi PERCORSO: pulsante «📁 Sfoglia…» (#285) che seleziona il file e salva
            # subito il percorso (invece di digitarlo a mano).
            if key in _BROWSE_FILETYPES:
                ctk.CTkButton(form, text="📁 Sfoglia…", width=100,
                              command=lambda k=key: self._browse_path(k)).grid(
                                  row=i, column=2, sticky="w", padx=8, pady=4)

        # Sport + giorni avanti.
        opts = ctk.CTkFrame(self)
        opts.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(opts, text="Sport").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        # Stato iniziale delle checkbox: dagli sport salvati (auto-sync) se presenti,
        # così riaprendo la tab NON si riselezionano tutti gli sport sovrascrivendo la
        # lista ristretta scelta dall'utente (Codex). Lista assente → tutti attivi.
        _saved_sports = self._autosync.get("sports")
        self._sport_vars = {}
        for j, sport in enumerate(SPORTS):
            checked = True if _saved_sports is None else (sport in _saved_sports)
            var = ctk.BooleanVar(value=checked)
            ctk.CTkCheckBox(opts, text=sport, variable=var,
                            command=self._autosync_changed).grid(
                row=0, column=1 + j, sticky="w", padx=6, pady=4)
            self._sport_vars[sport] = var
        ctk.CTkLabel(opts, text="Giorni avanti").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self._days_entry = ctk.CTkEntry(opts, width=60)
        self._days_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        # Auto Sync (issue #86 PR-P8): checkbox + orario HH; lo scheduling vero è
        # nell'app (tick mentre il bridge è aperto). Qui solo i controlli + stato.
        auto = ctk.CTkFrame(self)
        auto.pack(fill="x", padx=12, pady=6)
        self._autosync_var = ctk.BooleanVar(value=bool(self._autosync.get("enabled", False)))
        ctk.CTkCheckBox(auto, text="Auto sincronizza dizionario",
                        variable=self._autosync_var,
                        command=self._autosync_changed).grid(
            row=0, column=0, sticky="w", padx=8, pady=4)
        ctk.CTkLabel(auto, text="Orario (HH)").grid(row=0, column=1, sticky="e", padx=8, pady=4)
        self._autosync_hour = ctk.CTkEntry(auto, width=50)
        self._autosync_hour.insert(0, str(normalize_hour(self._autosync.get("hour", 23))))
        self._autosync_hour.grid(row=0, column=2, sticky="w", padx=6, pady=4)
        self._autosync_hour.bind("<FocusOut>", lambda _e: self._autosync_changed())
        self._last_auto_sync = ctk.CTkLabel(auto, text="Ultima auto sync: —")
        self._last_auto_sync.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=2)
        self._next_auto_sync = ctk.CTkLabel(auto, text="Prossima auto sync: —")
        self._next_auto_sync.grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=2)
        self._auto_sync_state = ctk.CTkLabel(auto, text="Stato auto sync: —")
        self._auto_sync_state.grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=2)

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
    def _browse_path(self, key):
        """«📁 Sfoglia…» per `cert_path`/`key_path` (#285): seleziona un file ESISTENTE e ne
        salva SUBITO il percorso.

        Riusa `_save()` — che RISOLVE i secret mascherati (App Key/Password) nei valori reali
        PRIMA di salvare: essenziale perché `credential_store.save_credentials` **cancella i
        campi vuoti**, quindi un salvataggio path-only ingenuo (secret vuoti) li perderebbe.
        Così solo il PERCORSO è nuovo; i segreti restano invariati (né toccati né smascherati).
        Legge/salva solo il percorso, **mai** il contenuto della chiave privata. Annullo →
        nessuna modifica. GUI-only (dialog Tk): la logica di salvataggio è in `_save`."""
        from tkinter import filedialog
        title, filetypes = _BROWSE_FILETYPES[key]
        entry = self._entries[key]
        current = str(entry.get() or "").strip()
        initialdir = os.path.dirname(current) if current else None
        initialfile = os.path.basename(current) if current else None
        dest = filedialog.askopenfilename(title=title, filetypes=filetypes,
                                          initialdir=initialdir, initialfile=initialfile)
        if not dest:
            return                           # dialog annullato: nessuna modifica
        entry.delete(0, "end")
        entry.insert(0, dest)
        self._save()                         # salva subito (anti-maschera già gestita in _save)

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

    def _autosync_changed(self):
        """Checkbox/orario/sport auto-sync cambiati: notifica l'app per persistere in
        config. Passa anche gli sport selezionati, così l'auto-sync usa quelli scelti
        (non la lista di default) — Codex."""
        if self._on_autosync_change:
            # Normalizza l'ora e riscrivila nel campo: se l'utente digita "99" salviamo
            # 23, e il campo deve mostrare 23 (non restare su "99") fino al prossimo
            # refresh, così ciò che si vede coincide con ciò che è salvato (CodeRabbit).
            hour = normalize_hour(self._autosync_hour.get())
            self._autosync_hour.delete(0, "end")
            self._autosync_hour.insert(0, str(hour))
            self._on_autosync_change(bool(self._autosync_var.get()), hour,
                                     self._selected_sports())

    def refresh_autosync(self, enabled, hour, sports):
        """Ricarica i controlli auto-sync da una config aggiornata (es. dopo aver
        applicato un profilo, così la tab non sovrascrive i valori del profilo con
        quelli stantii — Codex). Aggiorna anche le credenziali mascherate."""
        self._autosync_var.set(bool(enabled))
        self._autosync_hour.delete(0, "end")
        self._autosync_hour.insert(0, str(normalize_hour(hour)))
        # Lista assente (config/profilo senza `betfair_sync_sports`) = «tutti gli sport»,
        # coerente con `_build_ui` (Codex/CodeRabbit): altrimenti il pannello terrebbe il
        # sottoinsieme vecchio e il prossimo save lo riscriverebbe in config.
        for sport, var in self._sport_vars.items():
            var.set(True if sports is None else sport in sports)
        self._reload()
        self._refresh_buttons()

    def set_autosync_status(self, last=None, next_=None, state=None):
        """Aggiorna le etichette di stato auto-sync (chiamato dall'app dopo un run)."""
        if last is not None:
            self._last_auto_sync.configure(text=f"Ultima auto sync: {last}")
        if next_ is not None:
            self._next_auto_sync.configure(text=f"Prossima auto sync: {next_}")
        if state is not None:
            self._auto_sync_state.configure(text=f"Stato auto sync: {state}")

    def _selected_sports(self):
        """Gli sport con checkbox selezionata (per la sync)."""
        return [sport for sport, var in self._sport_vars.items() if var.get()]

    def _sync(self):
        if self._on_sync:
            self._on_sync(self._selected_sports())
        self._refresh_buttons()

    def _logout(self):
        # Invalida PRIMA dell'azione distruttiva: così un login in volo che finisce durante
        # il logout (o il keyring) non può ri-settare il token DOPO — l'epoch è già bumpato
        # e il completamento stantio viene scartato (Codex).
        if self._on_invalidate:
            self._on_invalidate()
        self.controller.logout()
        self._action_status.configure(text="")
        self._refresh_buttons()

    def _delete(self):
        # Invalida PRIMA del path distruttivo (anche se il keyring blocca/fallisce): l'intento
        # dell'utente è cancellare, quindi nessun login in volo deve lasciare la sessione attiva.
        if self._on_invalidate:
            self._on_invalidate()
        if self.controller.delete_saved_credentials():
            self._action_status.configure(text="🗑️ Credenziali cancellate.")
            self._reload()                  # solo dopo una cancellazione riuscita
        else:
            self._action_status.configure(
                text="⚠️ Cancellazione credenziali FALLITA (keyring non disponibile). "
                     "Le credenziali potrebbero essere ancora memorizzate.")
        self._refresh_buttons()
