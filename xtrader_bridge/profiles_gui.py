"""A3: vista customtkinter (sottile) dei profili di impostazioni.

Tutta la logica sta nel modulo puro `profile_store` (testato in CI): qui ci sono SOLO
i widget. La finestra si apre da un pulsante nella GUI principale (`app.App`) e permette
di salvare la configurazione corrente come profilo con un nome, ricaricarne uno
(le impostazioni vengono applicate, il token Telegram resta intatto) ed eliminarli.

SICUREZZA: `profile_store` non scrive mai il `bot_token` in un profilo e
`apply_profile` preserva il token corrente al caricamento (vedi quel modulo).

NB: questo modulo non è testato in CI (richiede un display). La logica che usa è
coperta da `tests/unit/test_profile_store.py`. Verifica manuale su Windows.
"""

import customtkinter as ctk

from . import gui_utils, profile_store


class ProfilesWindow(ctk.CTkToplevel):
    """Finestra dei profili di impostazioni.

    `get_current_cfg()`: callback che ritorna la config viva (con token) da usare sia
    come base per il salvataggio sia per preservare il token al caricamento.
    `on_loaded(new_cfg)`: callback chiamata dopo un caricamento riuscito, così la GUI
    principale aggiorna la config in memoria e ripopola i campi del form.
    `on_saved(new_cfg)`: callback opzionale chiamata dopo il salvataggio (persistenza).
    `is_running()`: callback opzionale che dice se il bridge è ATTIVO; in quel caso il
    caricamento di un profilo è bloccato (vedi `_load`)."""

    def __init__(self, master=None, get_current_cfg=None, on_loaded=None, on_saved=None,
                 is_running=None):
        super().__init__(master)
        self.title("Profili impostazioni")
        gui_utils.fit_to_screen(self, 560, 520, 480, 420)
        self._get_current_cfg = get_current_cfg or (lambda: {})
        self._on_loaded = on_loaded
        self._on_saved = on_saved
        self._is_running = is_running or (lambda: False)
        self._build_ui()
        self._refresh_list()

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text="📁  Profili impostazioni",
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self, text="Salva la configurazione corrente come profilo con un nome e "
                       "ricaricala quando vuoi. Il token Telegram NON viene salvato nei "
                       "profili e resta invariato al caricamento.",
            font=ctk.CTkFont(size=11), text_color="gray", wraplength=520,
            anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        # Salva profilo corrente
        save_row = ctk.CTkFrame(self, fg_color="transparent")
        save_row.pack(fill="x", padx=12, pady=(0, 6))
        self._name = ctk.CTkEntry(save_row, width=320, placeholder_text="Nome profilo (es. Prematch)")
        self._name.pack(side="left", padx=(0, 6))
        ctk.CTkButton(save_row, text="💾  Salva profilo", width=160, fg_color="#2e7d32",
                      hover_color="#1b5e20", command=self._save).pack(side="left")

        ctk.CTkLabel(self, text="Profili salvati", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(6, 2))
        self._list_frame = ctk.CTkScrollableFrame(self, height=300)
        self._list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self._status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                    text_color="gray", wraplength=520, anchor="w", justify="left")
        self._status.pack(fill="x", padx=12, pady=(0, 10))

    def _refresh_list(self):
        for child in self._list_frame.winfo_children():
            child.destroy()
        names = profile_store.list_profiles()
        if not names:
            ctk.CTkLabel(self._list_frame, text="(nessun profilo salvato)",
                         text_color="gray").pack(anchor="w", padx=6, pady=6)
            return
        for nm in names:
            row = ctk.CTkFrame(self._list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=nm, anchor="w", width=300).pack(side="left", padx=4)
            ctk.CTkButton(row, text="↺ Carica", width=90, fg_color="#1565c0",
                          hover_color="#0d47a1",
                          command=lambda n=nm: self._load(n)).pack(side="left", padx=3)
            ctk.CTkButton(row, text="🗑 Elimina", width=90, fg_color="#c62828",
                          hover_color="#7f0000",
                          command=lambda n=nm: self._delete(n)).pack(side="left", padx=3)

    # ── azioni ─────────────────────────────────────────────────────────────
    def _save(self):
        name = self._name.get().strip()
        # Valida il nome PRIMA di persistere il form (Codex): un nome vuoto/non valido o
        # collidente verrebbe rifiutato da save_profile, ma get_current_cfg avrebbe già
        # committato impostazioni safety-critical (dry_run/csv_path/chat). Pre-check puro.
        try:
            profile_store.ensure_valid_new_name(name)
        except ValueError as exc:
            self._status.configure(text=f"❌ {exc}", text_color="#ef5350")
            return
        # get_current_cfg persiste il form e ritorna la config viva (con token); lo
        # chiamiamo UNA sola volta per evitare doppia persistenza/snapshot divergenti.
        cfg = self._get_current_cfg()
        try:
            # save_profile rimuove i segreti prima di scrivere il profilo.
            profile_store.save_profile(name, cfg)
        except ValueError as exc:
            self._status.configure(text=f"❌ {exc}", text_color="#ef5350")
            return
        except OSError as exc:
            # Persistenza fallita (permessi AppData, disco pieno, nome riservato su
            # Windows): mostra l'errore senza far crashare la callback Tk (Codex P2).
            self._status.configure(text=f"❌ Salvataggio profilo fallito: {exc}",
                                   text_color="#ef5350")
            return
        self._name.delete(0, "end")
        self._refresh_list()
        self._status.configure(text=f"✅ Profilo {name!r} salvato (senza token).",
                               text_color="#66bb6a")
        if self._on_saved:
            self._on_saved(cfg)

    def _load(self, name: str):
        # SICUREZZA (Codex P1): col bridge ATTIVO il thread live usa lo snapshot config
        # preso a START; applicare un profilo cambierebbe config/form senza toccare il
        # runtime → l'utente vedrebbe "applicato" mentre dry_run/chat/queue/csv_path
        # restano quelli vecchi. Blocca il caricamento finché il bridge gira.
        if self._is_running():
            self._status.configure(
                text="⚠️ Ferma il bridge (STOP) prima di caricare un profilo: "
                     "le impostazioni live cambiano solo al prossimo AVVIA.",
                text_color="#ffa726")
            return
        try:
            profile = profile_store.load_profile(name)
        except (ValueError, OSError) as exc:
            # OSError copre file mancante (FileNotFoundError) e illeggibile (ACL/lock):
            # mostra l'errore senza far crashare la callback Tk (Codex P2).
            self._status.configure(text=f"❌ {exc}", text_color="#ef5350")
            self._refresh_list()
            return
        # Fonde sul config vivo preservando il token corrente, poi notifica la GUI
        # principale (che salva su disco e ripopola i campi del form).
        merged = profile_store.apply_profile(self._get_current_cfg(), profile)
        if self._on_loaded:
            self._on_loaded(merged)
        self._status.configure(
            text=f"✅ Profilo {name!r} caricato e applicato (token invariato).",
            text_color="#66bb6a")

    def _delete(self, name: str):
        try:
            removed = profile_store.delete_profile(name)
        except OSError as exc:
            # Rimozione fallita (permessi, cartella read-only, lock Windows): mostra
            # l'errore senza far crashare la callback Tk (Codex P2).
            self._status.configure(text=f"❌ Eliminazione fallita: {exc}", text_color="#ef5350")
            return
        self._refresh_list()
        if removed:
            self._status.configure(text=f"🗑 Profilo {name!r} eliminato.", text_color="gray")
        else:
            self._status.configure(text=f"⚠️ Profilo {name!r} non trovato.", text_color="#ffa726")
