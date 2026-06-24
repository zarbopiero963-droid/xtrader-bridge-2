"""Finestra di gestione del Dizionario nomi squadra (profili di mappatura).

Permette di **creare/rinominare/eliminare** profili di mappatura e di **modificarne
la tabella** ``Country | Betfair/XTrader | Provider`` (entrambe le colonne nome a
campo libero), salvati in ``config.json`` → chiave ``name_mappings``. I profili poi
si selezionano (checkbox) nel Parser Personalizzato per tradurre l'``EventName`` del
canale nel nome atteso da XTrader.

Tutta la logica di persistenza/risoluzione sta in `name_mapping_store` (funzioni
pure, testate in CI): qui ci sono SOLO i widget e la persistenza
(`config_store.save_config`). Come per la finestra Provider/Sorgenti, ogni
salvataggio persiste subito e chiama `on_saved(new_cfg)`, così la GUI principale
aggiorna la config in memoria e un successivo "Salva Config"/"Avvia" non riscrive il
file perdendo le mappature (pattern anti-stale).

NB: questo modulo non è testato in CI (richiede un display). La logica che usa è
coperta da `tests/unit/test_name_mapping.py`. Verifica manuale su Windows.
"""

import customtkinter as ctk

from . import config_store, custom_parser, gui_utils, name_mapping_store


class NameMappingWindow(ctk.CTkToplevel):
    """Finestra del Dizionario nomi squadra.

    `on_saved(new_cfg)`: callback opzionale chiamata dopo ogni salvataggio riuscito,
    così la GUI principale aggiorna la propria config in memoria."""

    _NO_PROFILE = "(nessun profilo)"

    def __init__(self, master=None, on_saved=None):
        super().__init__(master)
        self.title("Dizionario nomi squadra")
        gui_utils.fit_to_screen(self, 760, 620, 680, 460)
        self._on_saved = on_saved
        self._current = None              # nome profilo selezionato
        self._row_widgets = []            # [{frame, country, betfair, provider}, ...]
        self._build_ui()
        self._reload_profiles(select_first=True)

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text="🗺️  Dizionario nomi squadra",
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self, text="Traduce i nomi squadra del canale (Provider) nel nome atteso da "
                       "Betfair/XTrader. Seleziona i profili nel Parser Personalizzato.",
            font=ctk.CTkFont(size=11), text_color="gray", wraplength=720,
            anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        # Riga profili: selettore + nuovo / rinomina / elimina.
        prof = ctk.CTkFrame(self, fg_color="transparent")
        prof.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(prof, text="Profilo:").pack(side="left", padx=(6, 4))
        self._profile_var = ctk.StringVar(value=self._NO_PROFILE)
        self._profile_menu = ctk.CTkOptionMenu(
            prof, variable=self._profile_var, values=[self._NO_PROFILE], width=220,
            command=self._on_profile_change)
        self._profile_menu.pack(side="left", padx=4)
        ctk.CTkButton(prof, text="🆕 Nuovo", width=84, command=self._new_profile).pack(side="left", padx=3)
        ctk.CTkButton(prof, text="✏️ Rinomina", width=96, command=self._rename_profile).pack(side="left", padx=3)
        ctk.CTkButton(prof, text="🗑 Elimina", width=90, fg_color="#7f0000",
                      hover_color="#5a0000", command=self._delete_profile).pack(side="left", padx=3)

        # Intestazione tabella.
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(4, 0))
        for text, w in (("Country (opz.)", 180), ("Betfair / XTrader", 240), ("Provider", 240)):
            ctk.CTkLabel(head, text=text, width=w, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=3)

        self._rows_frame = ctk.CTkScrollableFrame(self, height=380, label_text="Righe del profilo")
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=6)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(actions, text="➕ Aggiungi riga", width=140,
                      command=self._add_row).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="💾 Salva profilo", width=140, fg_color="#2e7d32",
                      hover_color="#1b5e20", command=self._save).pack(side="left", padx=3)

        self._status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                    text_color="gray", wraplength=720, anchor="w", justify="left")
        self._status.pack(fill="x", padx=12, pady=(0, 10))

    # ── stato/config ─────────────────────────────────────────────────────────
    def _load_cfg(self):
        """Config corrente da disco, o None se illeggibile (con messaggio d'errore)."""
        try:
            return config_store.load_config(config_store.CONFIG_FILE)
        except Exception as exc:                 # noqa: BLE001 — fallback con messaggio
            self._status.configure(text=f"❌ Config illeggibile: {exc}", text_color="#ef5350")
            return None

    def _reload_profiles(self, select=None, select_first=False):
        """Ricarica la tendina dei profili da config e seleziona quello indicato."""
        cfg = self._load_cfg()
        names = name_mapping_store.profile_names(cfg) if cfg is not None else []
        self._profile_menu.configure(values=names or [self._NO_PROFILE])
        if select and select in names:
            target = select
        elif self._current in names:
            target = self._current
        elif select_first and names:
            target = names[0]
        else:
            target = None
        self._current = target
        self._profile_var.set(target or self._NO_PROFILE)
        self._reload_rows()

    def _reload_rows(self):
        """Ridisegna la tabella dalle righe salvate del profilo corrente."""
        for child in self._rows_frame.winfo_children():
            child.destroy()
        self._row_widgets = []
        if not self._current:
            ctk.CTkLabel(self._rows_frame, text="Nessun profilo. Crea un profilo con «Nuovo».",
                         text_color="gray").pack(anchor="w", padx=6, pady=4)
            return
        cfg = self._load_cfg()
        entries = name_mapping_store.get_entries(cfg, self._current) if cfg is not None else []
        for e in entries:
            self._append_row_widget(e.get("country", ""), e.get("betfair", ""), e.get("provider", ""))
        if not entries:
            self._append_row_widget("", "", "")     # una riga vuota pronta da compilare

    def _append_row_widget(self, country="", betfair="", provider=""):
        """Aggiunge una riga di widget (3 Entry + elimina) alla tabella."""
        row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        e_country = ctk.CTkEntry(row, width=180)
        e_country.insert(0, country)
        e_country.pack(side="left", padx=3)
        e_betfair = ctk.CTkEntry(row, width=240)
        e_betfair.insert(0, betfair)
        e_betfair.pack(side="left", padx=3)
        e_provider = ctk.CTkEntry(row, width=240)
        e_provider.insert(0, provider)
        e_provider.pack(side="left", padx=3)
        refs = {"frame": row, "country": e_country, "betfair": e_betfair, "provider": e_provider}
        ctk.CTkButton(row, text="🗑", width=36, fg_color="#c62828", hover_color="#7f0000",
                      command=lambda r=refs: self._delete_row(r)).pack(side="left", padx=3)
        self._row_widgets.append(refs)

    def _collect_rows(self) -> list:
        """Righe correnti dai widget come dict {country, betfair, provider} (la pulizia
        delle righe vuote la fa `name_mapping_store.set_entries`)."""
        return [
            {"country": r["country"].get(), "betfair": r["betfair"].get(),
             "provider": r["provider"].get()}
            for r in self._row_widgets
        ]

    # ── azioni righe ─────────────────────────────────────────────────────────
    def _add_row(self):
        if not self._current:
            self._status.configure(text="⛔ Crea prima un profilo con «Nuovo».",
                                   text_color="#ef5350")
            return
        self._append_row_widget("", "", "")

    def _delete_row(self, refs):
        refs["frame"].destroy()
        self._row_widgets = [r for r in self._row_widgets if r is not refs]

    # ── azioni profilo (persistono subito) ───────────────────────────────────
    def _persist(self, cfg: dict, ok_msg: str, fail_msg: str, select=None) -> bool:
        """Salva `cfg`, sincronizza la GUI principale (on_saved) e ridisegna.

        Solo su **successo** si ricarica da disco: se il salvataggio fallisce (cartella
        in sola lettura, disco pieno, I/O transitorio) NON si rilegge il file, così le
        righe appena digitate restano a schermo e non vengono perse mentre il messaggio
        dice che non sono state salvate (Codex)."""
        saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
        if ok:
            if callable(self._on_saved):
                self._on_saved(saved)
            self._reload_profiles(select=select)
        self._status.configure(text=ok_msg if ok else fail_msg,
                               text_color="#66bb6a" if ok else "#ef5350")
        return ok

    def _save(self):
        """Salva la tabella corrente nel profilo selezionato."""
        if not self._current:
            self._status.configure(text="⛔ Nessun profilo selezionato.", text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        cfg = name_mapping_store.set_entries(cfg, self._current, self._collect_rows())
        n = len(name_mapping_store.get_entries(cfg, self._current))
        self._persist(
            cfg,
            ok_msg=f"💾 Profilo «{self._current}» salvato ({n} righe valide).",
            fail_msg=f"❌ Salvataggio FALLITO: «{self._current}» non salvato (andrebbe perso al riavvio). "
                     "Controlla permessi/spazio del file config.",
            select=self._current)

    def _on_profile_change(self, value):
        """Cambio profilo: salva prima quello corrente (evita di perdere le modifiche
        non salvate), poi carica il selezionato."""
        new = value if value != self._NO_PROFILE else None
        if new == self._current:
            return
        if self._current:                          # auto-salva il profilo che stai lasciando
            cfg = self._load_cfg()
            if cfg is not None:
                cfg = name_mapping_store.set_entries(cfg, self._current, self._collect_rows())
                saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
                if not ok:
                    # Auto-save fallito: ANNULLA il cambio profilo invece di proseguire,
                    # altrimenti `_reload_rows` cancellerebbe le righe non salvate. Tieni
                    # il profilo corrente a schermo così l'utente può riprovare (Codex).
                    self._profile_var.set(self._current)
                    self._status.configure(
                        text="❌ Salvataggio FALLITO: cambio profilo annullato, modifiche "
                             "mantenute a schermo. Controlla permessi/spazio del file config.",
                        text_color="#ef5350")
                    return
                # Propaga al parent anche l'auto-save (non solo i salvataggi espliciti),
                # altrimenti la GUI principale resta con un `self._config` stantio e un
                # successivo "Salva Config"/START potrebbe sovrascrivere le mappature
                # appena auto-salvate (Codex).
                if callable(self._on_saved):
                    self._on_saved(saved)
        self._current = new
        self._profile_var.set(new or self._NO_PROFILE)
        self._reload_rows()

    def _new_profile(self):
        dialog = ctk.CTkInputDialog(text="Nome del nuovo profilo:", title="Nuovo profilo")
        name = (dialog.get_input() or "").strip()
        if not name:
            self._status.configure(text="⛔ Profilo non creato (nome vuoto).", text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        if name in name_mapping_store.profile_names(cfg):
            self._status.configure(text=f"ℹ️ Il profilo «{name}» esiste già.", text_color="gray")
            return
        # Salva prima le righe in editing del profilo corrente: passare a quello nuovo
        # non deve perdere le modifiche non ancora salvate (Codex).
        if self._current:
            cfg = name_mapping_store.set_entries(cfg, self._current, self._collect_rows())
        cfg = name_mapping_store.add_profile(cfg, name)
        self._persist(cfg, ok_msg=f"🆕 Profilo «{name}» creato.",
                      fail_msg=f"❌ Salvataggio FALLITO: «{name}» non creato.", select=name)

    def _rename_profile(self):
        if not self._current:
            self._status.configure(text="⛔ Nessun profilo selezionato.", text_color="#ef5350")
            return
        dialog = ctk.CTkInputDialog(text=f"Nuovo nome per «{self._current}»:", title="Rinomina profilo")
        new = (dialog.get_input() or "").strip()
        if not new:
            self._status.configure(text="⛔ Rinomina annullata (nome vuoto).", text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        if new in name_mapping_store.profile_names(cfg):
            self._status.configure(text=f"ℹ️ Il profilo «{new}» esiste già.", text_color="gray")
            return
        old = self._current
        # Salva prima le modifiche correnti, poi rinomina (conserva le righe).
        cfg = name_mapping_store.set_entries(cfg, old, self._collect_rows())
        cfg = name_mapping_store.rename_profile(cfg, old, new)
        # Persisti PRIMA la config; solo se il salvataggio riesce riscrivi i riferimenti
        # nei parser salvati. Altrimenti, con un save config fallito, i parser punterebbero
        # a `new` mentre la config ha ancora `old` → MAPPING_MISSING (Codex).
        ok = self._persist(cfg, ok_msg=f"✏️ Profilo rinominato «{old}» → «{new}».",
                           fail_msg="❌ Salvataggio FALLITO: rinomina non applicata.", select=new)
        if ok:
            # Aggiorna i riferimenti nei parser salvati che usano il vecchio nome, così non
            # restano a chiedere un profilo inesistente (→ MAPPING_MISSING silenzioso).
            try:
                updated, failed = custom_parser.rename_mapping_profile_in_files(old, new)
            except Exception:                    # noqa: BLE001 — il rename del profilo resta valido
                updated, failed = [], []
            if failed:
                # Alcuni parser non si sono potuti riscrivere: restano sul vecchio nome
                # mentre la config ha il nuovo → quei segnali andrebbero scartati. Avvisa.
                self._status.configure(
                    text=f"⚠️ Profilo rinominato «{old}» → «{new}», ma {len(failed)} parser "
                         f"NON aggiornati ({', '.join(failed)}): correggili a mano o quei "
                         "segnali verranno scartati (MAPPING_MISSING).",
                    text_color="#ffa726")
            elif updated:
                self._status.configure(
                    text=f"✏️ Profilo rinominato «{old}» → «{new}» · {len(updated)} parser aggiornati.",
                    text_color="#66bb6a")

    def _delete_profile(self):
        if not self._current:
            self._status.configure(text="⛔ Nessun profilo selezionato.", text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        name = self._current
        # Avvisa se il profilo è ancora usato da parser salvati: la cancellazione li
        # lascerebbe a chiedere un profilo inesistente → segnali scartati (MAPPING_MISSING,
        # fail-closed). Non lo rimuoviamo in silenzio dai parser (disattivare la mappatura
        # lascerebbe passare l'EventName grezzo): meglio avvisare e far decidere all'utente.
        try:
            affected = custom_parser.parsers_using_mapping_profile(name)
        except Exception:                        # noqa: BLE001 — l'avviso è best-effort
            affected = []
        cfg = name_mapping_store.delete_profile(cfg, name)
        self._current = None
        ok = self._persist(cfg, ok_msg=f"🗑 Profilo «{name}» eliminato.",
                           fail_msg=f"❌ Salvataggio FALLITO: «{name}» non eliminato.")
        if ok and affected:
            self._status.configure(
                text=f"⚠️ «{name}» eliminato, ma è ancora selezionato in {len(affected)} parser "
                     f"({', '.join(affected)}): quei segnali verranno scartati (MAPPING_MISSING) "
                     "finché non togli il profilo da quei parser.",
                text_color="#ffa726")
