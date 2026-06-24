"""CP-06: vista customtkinter (sottile) del costruttore di Parser Personalizzati.

Tutta la logica sta nel controller `parser_builder.ParserBuilder` (testato in CI);
qui ci sono SOLO i widget. La finestra si apre da un pulsante nella GUI principale
(`app.App`). Per regola: target, "Inizia dopo", "Finisce prima di", valore fisso,
trasformazione, value-map, obbligatorio. In più: aggiungi/rimuovi/sposta regola,
salva/carica, e **test-live** su un messaggio incollato.

NB: questo modulo non è testato in CI (richiede un display). La logica che usa è
coperta da `tests/unit/test_parser_builder.py`. Verifica manuale su Windows.
"""

import customtkinter as ctk

from . import config_store, gui_utils, name_mapping_store, parser_diagnostics, provider_store
from .parser_builder import ParserBuilder


class CustomParserPanel(ctk.CTkFrame):
    """Pannello del costruttore di Parser Personalizzati — incassabile in finestra
    standalone (`CustomParserWindow`) o come scheda "🧩 Parser" di "🧰 Strumenti".
    `on_message` opzionale non usato: l'anteprima è interna (test-live)."""

    # Etichetta-sentinella quando non c'è nessun parser salvato.
    _NONE_SAVED = "(nessuno)"
    # Voce della tendina Modalità per il sentinella "" (parser legacy = eredita la
    # modalità globale). Mostrarla evita di convertire "" in NAME_ONLY salvando (Codex).
    _MODE_INHERIT = "(eredita globale)"

    def _mode_to_label(self, mode: str) -> str:
        return self._MODE_INHERIT if not mode else mode

    def _label_to_mode(self, label: str) -> str:
        return "" if label == self._MODE_INHERIT else label

    # ── anagrafica Provider (PR-5) ─────────────────────────────────────────
    @staticmethod
    def _load_providers() -> list:
        """Nomi provider salvati (best-effort: una config illeggibile → lista vuota)."""
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception:                       # noqa: BLE001 — fallback sicuro
            return []
        return provider_store.provider_names(cfg)

    def _add_provider(self):
        """Chiede un nome, lo salva nell'anagrafica (config) e aggiorna le tendine
        Provider. Persistenza indipendente come per la finestra Sorgenti."""
        dialog = ctk.CTkInputDialog(text="Nome del nuovo Provider:", title="Provider")
        name = (dialog.get_input() or "").strip()
        if not name:
            self._result.configure(text="⛔ Provider non aggiunto (nome vuoto).")
            return
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
            cfg = provider_store.add_provider(cfg, name)
            saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
        except Exception as exc:                 # noqa: BLE001
            self._result.configure(text=f"❌ Errore salvataggio provider: {exc}")
            return
        # Sincronizza la config in memoria della GUI principale (no perdita provider).
        if ok and callable(self._on_saved):
            self._on_saved(saved)
        self._providers = provider_store.provider_names(saved if ok else cfg)
        self._sync_to_builder()                  # non perdere le modifiche correnti
        self._reload_rows_from_builder()         # ridisegna con la tendina aggiornata
        self._result.configure(
            text=f"➕ Provider «{name}» salvato." if ok
            else f"⚠️ Provider «{name}» aggiunto solo in memoria (salvataggio fallito).")

    # ── mappatura nomi squadra (profili) ───────────────────────────────────
    @staticmethod
    def _load_name_mapping_profiles() -> list:
        """Nomi dei profili di mappatura salvati (best-effort: config illeggibile → [])."""
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception:                       # noqa: BLE001 — fallback sicuro
            return []
        return name_mapping_store.profile_names(cfg)

    def _reload_profile_checks(self, use_builder=False):
        """Ridisegna le checkbox dei profili. La selezione spuntata viene da
        `builder.name_mapping_profiles` (su `use_builder`, es. caricamento di un parser)
        oppure dalle checkbox correnti (refresh dopo aver modificato il dizionario).

        Mostra i profili **esistenti** in config e, in più, i profili **selezionati ma non
        più esistenti** (rinominati/eliminati nel dizionario) come voci ⚠ **fantasma**:
        restano una checkbox così l'utente PUÒ togliere la spunta, e `_unresolved_selected`
        le intercetta per bloccare save/preview finché non sono risolte — niente
        riferimenti morti riscritti in silenzio né blocchi senza via d'uscita (Codex)."""
        if use_builder or not self._profile_checks:
            selected = list(self.builder.name_mapping_profiles)
        else:
            selected = self._selected_profiles()
        selected_set = set(selected)
        for child in self._profiles_box.winfo_children():
            child.destroy()
        self._profile_checks = {}
        existing = list(self._load_name_mapping_profiles())
        self._existing_profiles = set(existing)
        missing = [n for n in selected if n not in self._existing_profiles]
        names = existing + [n for n in missing if n not in existing]
        if not names:
            ctk.CTkLabel(self._profiles_box, text="(nessun profilo)",
                         text_color="gray").pack(side="left", padx=4)
            return
        for name in names:
            present = name in self._existing_profiles
            var = ctk.BooleanVar(value=name in selected_set)
            kw = {} if present else {"text_color": "#ffa726"}   # ⚠ profilo mancante
            ctk.CTkCheckBox(self._profiles_box, text=name if present else f"⚠ {name}",
                            variable=var, width=20, **kw).pack(side="left", padx=4)
            self._profile_checks[name] = var

    def _selected_profiles(self) -> list:
        """Profili spuntati, **preservando l'ordine** scelto nel parser: l'ordine dei
        profili è significativo (in `resolve_team` vince la prima corrispondenza), quindi
        i profili già presenti in `builder.name_mapping_profiles` mantengono la loro
        posizione; gli eventuali profili appena spuntati si aggiungono in coda (ordine di
        visualizzazione). Così aprire e ri-salvare un parser con profili ['B','A'] NON li
        riordina alfabeticamente cambiando la precedenza (Codex P1). I profili mancanti
        (⚠) selezionati restano inclusi: hanno una checkbox e `_unresolved_selected` li
        blocca finché non sono risolti."""
        checked = {name for name, var in self._profile_checks.items() if var.get()}
        ordered = [n for n in self.builder.name_mapping_profiles if n in checked]
        ordered += [n for n in self._profile_checks if n in checked and n not in ordered]
        return ordered

    def _unresolved_selected(self) -> list:
        """Profili selezionati che non corrispondono a un profilo ESISTENTE (voci ⚠
        fantasma). Finché ce ne sono spuntati, `_save`/`_test` si bloccano: una mappatura
        richiesta ma non risolvibile non deve diventare in silenzio «nessuna mappatura»."""
        return [n for n in self._selected_profiles() if n not in self._existing_profiles]

    @staticmethod
    def _resolve_mapping_profiles(defn):
        """Righe dei profili del parser risolte dalla config (per l'anteprima), o None
        se il parser non usa la mappatura. Best-effort: config illeggibile → lista vuota
        (mappatura richiesta ma irrisolvibile → l'anteprima farà fail-closed)."""
        if not defn.name_mapping_profiles:
            return None
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception:                       # noqa: BLE001 — fallback sicuro
            cfg = {}
        return name_mapping_store.entries_for_profiles(cfg, defn.name_mapping_profiles)

    def _open_name_mapping(self):
        """Apre il Dizionario nomi (finestra separata). Alla chiusura/salvataggio
        ricarica le checkbox dei profili così le nuove voci compaiono subito."""
        self._sync_to_builder()              # non perdere selezione/separatore correnti
        from .name_mapping_gui import NameMappingWindow

        def _on_saved(new_cfg):
            if callable(self._on_saved):
                self._on_saved(new_cfg)
            self._reload_profile_checks()

        win = NameMappingWindow(self, on_saved=_on_saved)
        win.focus()

    def __init__(self, master=None, builder: ParserBuilder = None, provider: str = "",
                 global_mode: str = "", on_saved=None):
        super().__init__(master)
        is_new = builder is None
        self.builder = builder or ParserBuilder()
        self._provider = provider
        # Callback opzionale: dopo aver salvato l'anagrafica Provider su config.json,
        # sincronizza la config in memoria della GUI principale (vedi `app`), così un
        # successivo Salva/Avvia non riscrive il file perdendo i provider (Codex).
        self._on_saved = on_saved
        # Modalità globale (config `recognition_mode`): usata SOLO per l'anteprima di un
        # parser legacy a eredità ("" ): così "Prova messaggio" combacia col runtime (Codex).
        self._global_mode = global_mode
        self._rows = []  # widget refs per regola
        self._saved_map = {}  # etichetta menu → path file parser

        self._transforms = self.builder.transform_options()
        self._value_maps = self.builder.value_map_options(include_dizionario=True)
        self._modes = self.builder.mode_options()
        self._providers = self._load_providers()   # anagrafica Provider (PR-5)

        # Parser NUOVO: applica l'auto-Obblig. della modalità di default UNA volta (per i
        # parser caricati invece si preservano i flag salvati: niente set_mode al reload).
        if is_new and self.builder.mode:
            self.builder.set_mode(self.builder.mode)
        self._build_ui()
        self._reload_rows_from_builder()
        self._refresh_saved()

    def refresh_options(self):
        """Aggiorna le LISTE-OPZIONI derivate dal config SENZA toccare il parser in
        costruzione (preserva le modifiche): provider del menu colonna Provider, modalità
        globale per l'anteprima, checkbox dei profili di mappatura (le spunte restano).

        Chiamato quando questa scheda torna attiva nella hub "🧰 Strumenti": un provider o
        un profilo aggiunto/rimosso in un'altra scheda, o un cambio profilo, si riflette
        subito senza riaprire Strumenti (Codex). Best-effort: config illeggibile → no-op."""
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception:               # noqa: BLE001 — config illeggibile: niente refresh
            return
        self._providers = provider_store.provider_names(cfg)
        self._global_mode = str(cfg.get("recognition_mode", "")).strip()
        # Anche il provider per l'anteprima: `_test()` passa `self._provider` a
        # test_message()/diagnose(); senza aggiornarlo, un parser con colonna Provider non
        # fissa verrebbe provato col provider VECCHIO dopo un cambio profilo (Codex).
        self._provider = str(cfg.get("provider", "")).strip()
        for refs in self._rows:
            menu = refs.get("provider_menu")
            if menu is not None:
                cur = refs["fixed_value"].get()
                vals = ["", *self._providers]
                if cur and cur not in vals:
                    vals.append(cur)        # preserva la selezione anche se rimossa dall'anagrafica
                menu.configure(values=vals)
        self._reload_profile_checks()       # ricarica i profili mapping dal disco (spunte preservate)

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        # TUTTA la finestra dentro UN solo contenitore scrollabile: il contenuto è alto
        # (griglia 14 colonne + area test + diagnostica) e prima, su schermi piccoli, la
        # parte bassa finiva fuori finestra senza modo di raggiungerla. Con lo scroll
        # esterno ogni sezione resta sempre raggiungibile. Le sezioni interne che prima
        # avevano uno scroll proprio (griglia regole, tabella diagnostica) diventano frame
        # semplici: lo scorrimento lo gestisce SOLO questo contenitore (niente scroll
        # verticali annidati, che si rubavano la rotellina a vicenda).
        outer = ctk.CTkScrollableFrame(self)
        outer.pack(fill="both", expand=True)
        self._outer = outer

        top = ctk.CTkFrame(outer, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(top, text="Nome parser:").pack(side="left", padx=6)
        self._name_var = ctk.StringVar(value=self.builder.name)
        ctk.CTkEntry(top, textvariable=self._name_var, width=240).pack(side="left", padx=6)
        ctk.CTkLabel(top, text="Modalità:").pack(side="left", padx=6)
        # Modalità DEL PARSER (per-parser): scegliendola, i campi di riconoscimento del
        # set diventano obbligatori da soli (set_mode → auto-Obblig.). La voce
        # "(eredita globale)" rappresenta "" (parser legacy): usa la modalità globale.
        self._mode_var = ctk.StringVar(value=self._mode_to_label(self.builder.mode))
        ctk.CTkOptionMenu(top, variable=self._mode_var,
                          values=[self._MODE_INHERIT, *self._modes], width=160,
                          command=self._on_mode_change).pack(side="left", padx=6)
        # Anagrafica Provider (PR-5): aggiungi un nome riusabile nella tendina della
        # colonna Provider (sotto). I provider salvati valgono per tutti i parser.
        ctk.CTkButton(top, text="➕ Provider", width=110,
                      command=self._add_provider).pack(side="left", padx=6)

        # gestione parser salvati: lista + nuovo / carica / duplica / elimina
        manage = ctk.CTkFrame(outer, fg_color="transparent")
        manage.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(manage, text="Parser salvati:").pack(side="left", padx=6)
        self._saved_var = ctk.StringVar(value=self._NONE_SAVED)
        self._saved_menu = ctk.CTkOptionMenu(
            manage, variable=self._saved_var, values=[self._NONE_SAVED], width=220)
        self._saved_menu.pack(side="left", padx=6)
        ctk.CTkButton(manage, text="🆕 Nuovo", width=90, command=self._new).pack(side="left", padx=3)
        ctk.CTkButton(manage, text="📂 Carica", width=90, command=self._load_selected).pack(side="left", padx=3)
        ctk.CTkButton(manage, text="📑 Duplica", width=90, command=self._duplicate_selected).pack(side="left", padx=3)
        ctk.CTkButton(manage, text="🗑 Elimina", width=90, fg_color="#7f0000",
                      command=self._delete_selected).pack(side="left", padx=3)

        # Catalogo XTrader (B2): scegli Mercato → Selezione (solo NON dinamici) e
        # inseriscili come regole FISSE, senza digitare i nomi canonici a mano.
        cat = ctk.CTkFrame(outer, fg_color="transparent")
        cat.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(cat, text="Catalogo XTrader:").pack(side="left", padx=6)
        self._markets = self.builder.market_options()
        self._cat_market = ctk.StringVar(value=self._markets[0] if self._markets else "")
        self._cat_market_menu = ctk.CTkOptionMenu(
            cat, variable=self._cat_market, values=self._markets or [""],
            width=240, command=self._on_market_change)
        self._cat_market_menu.pack(side="left", padx=4)
        self._cat_selection = ctk.StringVar(value="")
        self._cat_selection_menu = ctk.CTkOptionMenu(
            cat, variable=self._cat_selection, values=[""], width=240)
        self._cat_selection_menu.pack(side="left", padx=4)
        ctk.CTkButton(cat, text="➕ Inserisci regole fisse", width=180,
                      command=self._insert_fixed_market).pack(side="left", padx=4)
        self._refresh_selection_menu()   # popola le selezioni del mercato iniziale

        # Mappatura nomi squadra: separatore casa/trasferta del canale + profili
        # (checkbox multi-selezione) che traducono l'EventName provider → Betfair/XTrader.
        nm = ctk.CTkFrame(outer, fg_color="transparent")
        nm.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(nm, text="Mappatura nomi · separatore:").pack(side="left", padx=6)
        self._separator_var = ctk.StringVar(value=self.builder.team_separator)
        ctk.CTkEntry(nm, textvariable=self._separator_var, width=70,
                     placeholder_text="v").pack(side="left", padx=2)
        ctk.CTkButton(nm, text="🗺️ Dizionario nomi", width=160,
                      command=self._open_name_mapping).pack(side="left", padx=6)
        ctk.CTkLabel(nm, text="Profili:").pack(side="left", padx=(8, 2))
        self._profiles_box = ctk.CTkScrollableFrame(nm, height=42, orientation="horizontal")
        self._profiles_box.pack(side="left", fill="x", expand=True, padx=4)
        self._profile_checks = {}        # nome profilo → BooleanVar
        self._existing_profiles = set()  # profili realmente presenti in config (non ⚠)
        self._reload_profile_checks()

        # intestazione colonne
        head = ctk.CTkFrame(outer, fg_color="transparent")
        head.pack(fill="x", padx=10)
        for txt, w in (("Colonna", 150), ("Inizia dopo", 150), ("Finisce prima", 150),
                       ("Valore fisso", 130), ("Trasformazione", 150), ("Value-map", 150),
                       ("Obblig.", 60), ("", 70)):
            ctk.CTkLabel(head, text=txt, width=w, anchor="w").pack(side="left", padx=2)

        self._rows_frame = ctk.CTkFrame(outer, fg_color="transparent")
        self._rows_frame.pack(fill="x", padx=10, pady=6)

        actions = ctk.CTkFrame(outer, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(actions, text="💾 Salva", command=self._save).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="🧪 Prova messaggio", command=self._test).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="📋 Copia diagnostica", command=self._copy_diag).pack(side="left", padx=4)

        # test-live
        test = ctk.CTkFrame(outer, fg_color="transparent")
        test.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(test, text="Messaggio di prova:").pack(anchor="w", padx=6)
        self._msg_box = ctk.CTkTextbox(test, height=120)
        self._msg_box.pack(fill="x", padx=6, pady=4)
        self._result = ctk.CTkLabel(test, text="", anchor="w", justify="left")
        self._result.pack(fill="x", padx=6, pady=4)
        # Diagnostica per-campo (CP-08b): TABELLA — perché "Non pronto", colonna per colonna.
        ctk.CTkLabel(test, text="Diagnostica (una riga per colonna):").pack(anchor="w", padx=6)
        self._diag_table = ctk.CTkFrame(test, fg_color="transparent")
        self._diag_table.pack(fill="x", padx=6, pady=(0, 4))
        # Larghezze colonne della tabella diagnostica (px), in ordine.
        self._diag_cols = (("Colonna", 110), ("Stato", 64), ("Motivo", 280),
                           ("Inizia dopo", 120), ("Finisce prima", 120), ("Valore estratto", 170))
        self._last_report = ""   # testo per "Copia diagnostica"

    # ── righe regola ──────────────────────────────────────────────────────
    def _add_row(self, rule):
        """Una riga = UNA colonna del contratto (griglia fissa a 14, PR-4): la colonna
        è una Label fissa (non più una tendina), così l'ordine resta quello del contratto
        e non si possono creare doppioni o dimenticare colonne."""
        row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        refs = {"target": rule.target}     # colonna FISSA: stringa, non un widget
        ctk.CTkLabel(row, text=rule.target, width=150, anchor="w").pack(side="left", padx=2)
        refs["start_after"] = ctk.CTkEntry(row, width=150)
        refs["end_before"] = ctk.CTkEntry(row, width=150)
        refs["start_after"].insert(0, rule.start_after)
        refs["end_before"].insert(0, rule.end_before)
        refs["start_after"].pack(side="left", padx=2)
        refs["end_before"].pack(side="left", padx=2)
        # Valore fisso: per la colonna Provider è un MENU dall'anagrafica (PR-5), così si
        # sceglie un provider salvato invece di digitarlo; per le altre colonne è testo.
        # In entrambi i casi `_sync_to_builder` legge `.get()` (StringVar o Entry).
        if rule.target == "Provider":
            refs["fixed_value"] = ctk.StringVar(value=rule.fixed_value)
            vals = ["", *self._providers]
            if rule.fixed_value and rule.fixed_value not in vals:
                vals.append(rule.fixed_value)   # preserva un provider non (più) in anagrafica
            provider_menu = ctk.CTkOptionMenu(row, variable=refs["fixed_value"], width=130,
                                              values=vals)
            provider_menu.pack(side="left", padx=2)
            refs["provider_menu"] = provider_menu   # per refresh_options (hub)
        else:
            refs["fixed_value"] = ctk.CTkEntry(row, width=130)
            refs["fixed_value"].insert(0, rule.fixed_value)
            refs["fixed_value"].pack(side="left", padx=2)
        refs["transform"] = ctk.StringVar(value=rule.transform)
        ctk.CTkOptionMenu(row, variable=refs["transform"], values=self._transforms, width=150).pack(side="left", padx=2)
        refs["value_map"] = ctk.StringVar(value=rule.value_map)
        ctk.CTkOptionMenu(row, variable=refs["value_map"], values=self._value_maps, width=150).pack(side="left", padx=2)
        refs["required"] = ctk.BooleanVar(value=bool(rule.required))
        ctk.CTkCheckBox(row, text="", variable=refs["required"], width=40).pack(side="left", padx=2)
        refs["frame"] = row
        self._rows.append(refs)

    def _reload_rows_from_builder(self):
        for r in list(self._rows):
            r["frame"].destroy()
        self._rows = []
        # Griglia fissa: garantisce una riga per ognuna delle 14 colonne, in ordine.
        self.builder.ensure_all_columns()
        # NB: NON si chiama qui `set_mode` — il reload deve solo RENDERIZZARE i flag
        # correnti, preservando i required salvati a mano di un parser caricato (Codex).
        # L'auto-Obblig. si applica su azione esplicita (_on_mode_change) o su parser nuovo.
        self._mode_var.set(self._mode_to_label(self.builder.mode))
        # Mappatura nomi: ripristina separatore + checkbox profili dal builder.
        self._separator_var.set(self.builder.team_separator)
        self._reload_profile_checks(use_builder=True)
        for rule in self.builder.rules:
            self._add_row(rule)

    def _on_mode_change(self, _value=None):
        """Modalità cambiata dal menu. Se concreta → set_mode (auto-Obblig. add-only);
        se "(eredita globale)" → mode "" (nessuna auto-Obblig.: la decide il globale a
        runtime). Poi ricarica le righe."""
        self._sync_to_builder()
        mode = self._label_to_mode(self._mode_var.get())
        if mode:
            self.builder.set_mode(mode)
        else:
            self.builder.mode = ""
        self._reload_rows_from_builder()

    def _sync_to_builder(self):
        """Riporta i valori dei widget nel controller (colonne fisse + Modalità).
        La modalità è preservata com'è (incl. "" = eredita globale): non si normalizza,
        così aprire/salvare un parser legacy non lo converte a NAME_ONLY (Codex)."""
        self.builder.name = self._name_var.get().strip()
        self.builder.mode = self._label_to_mode(self._mode_var.get())
        # Mappatura nomi: separatore (testo libero) + profili spuntati.
        self.builder.team_separator = self._separator_var.get().strip()
        self.builder.name_mapping_profiles = self._selected_profiles()
        self.builder.rules = []
        for refs in self._rows:
            self.builder.add_rule(
                target=refs["target"],          # stringa fissa (Label)
                start_after=refs["start_after"].get(),
                end_before=refs["end_before"].get(),
                fixed_value=refs["fixed_value"].get(),
                transform=refs["transform"].get(),
                value_map=refs["value_map"].get(),
                required=bool(refs["required"].get()),
            )

    # ── azioni ────────────────────────────────────────────────────────────
    def _save(self):
        # Rinfresca le checkbox dal config: una modifica del dizionario fatta altrove
        # (es. rinomina dal pulsante della finestra principale) deve riflettersi qui,
        # così un profilo mancante diventa ⚠ e blocca il salvataggio invece di riscrivere
        # un riferimento morto nel parser (Codex).
        self._reload_profile_checks()
        self._sync_to_builder()
        unresolved = self._unresolved_selected()
        if unresolved:
            self._result.configure(
                text=f"⛔ Non salvato: profili di mappatura mancanti ({', '.join(unresolved)}). "
                     "Ricreali nel «Dizionario nomi» o togli la spunta prima di salvare.")
            return
        errors = self.builder.errors()
        if errors:
            self._result.configure(text="❌ Non salvato:\n- " + "\n- ".join(errors))
            return
        try:
            path = self.builder.save()
        except (OSError, ValueError) as exc:
            self._result.configure(text=f"❌ Errore salvataggio: {exc}")
            return
        self._refresh_saved()
        self._result.configure(text=f"💾 Salvato in {path}")

    # ── catalogo XTrader (B2) ───────────────────────────────────────────────
    def _on_market_change(self, _value=None):
        """Cambiato il mercato → rinfresca la tendina delle selezioni (solo fisse)."""
        self._refresh_selection_menu()

    def _refresh_selection_menu(self):
        market = self._cat_market.get()
        sels = self.builder.selection_options(market) if market else []
        self._cat_selection_menu.configure(values=sels or [""])
        self._cat_selection.set(sels[0] if sels else "")

    def _insert_fixed_market(self):
        """Inserisce Mercato+Selezione scelti come regole FISSE (MarketType/MarketName/
        SelectionName), preservando le altre regole già impostate nei widget."""
        market = self._cat_market.get()
        selection = self._cat_selection.get()
        self._sync_to_builder()          # cattura le regole correnti dai widget
        try:
            self.builder.set_fixed_market(market, selection)
        except ValueError as exc:
            self._result.configure(text=f"⛔ {exc}")
            return
        self._reload_rows_from_builder()
        self._result.configure(text=f"➕ Regole fisse inserite: {market} · {selection}")

    # ── gestione parser salvati (lista / nuovo / carica / duplica / elimina) ─
    def _refresh_saved(self):
        """Ricarica la tendina dei parser salvati dalla cartella utente."""
        items = ParserBuilder.saved_parsers()
        self._saved_map = {it["name"]: it["path"] for it in items}
        labels = list(self._saved_map) or [self._NONE_SAVED]
        self._saved_menu.configure(values=labels)
        # Mantieni la selezione se ancora valida, altrimenti vai sul primo.
        if self._saved_var.get() not in labels:
            self._saved_var.set(labels[0])

    def _selected_path(self):
        """Path del parser selezionato, o None se non c'è selezione valida."""
        return self._saved_map.get(self._saved_var.get())

    def _new(self):
        """Svuota il costruttore per un nuovo parser (non tocca i file salvati)."""
        self.builder = ParserBuilder()
        # Parser nuovo: applica l'auto-Obblig. della modalità di default una volta.
        if self.builder.mode:
            self.builder.set_mode(self.builder.mode)
        self._name_var.set("")
        self._reload_rows_from_builder()
        self._result.configure(text="🆕 Nuovo parser (non ancora salvato).")

    def _load_selected(self):
        path = self._selected_path()
        if not path:
            self._result.configure(text="⛔ Nessun parser selezionato.")
            return
        try:
            self.builder = ParserBuilder.load(path)
        except (OSError, ValueError) as exc:
            self._result.configure(text=f"❌ Errore caricamento: {exc}")
            return
        self._name_var.set(self.builder.name)
        self._reload_rows_from_builder()
        self._result.configure(text=f"📂 Caricato {self.builder.name!r}.")

    def _duplicate_selected(self):
        path = self._selected_path()
        if not path:
            self._result.configure(text="⛔ Nessun parser selezionato.")
            return
        src_name = self._saved_var.get()
        dialog = ctk.CTkInputDialog(
            text=f"Nuovo nome per la copia di {src_name!r}:", title="Duplica parser")
        new_name = (dialog.get_input() or "").strip()
        if not new_name:
            self._result.configure(text="⛔ Duplica annullata (nome vuoto).")
            return
        try:
            ParserBuilder.duplicate_saved(path, new_name)
        except (OSError, ValueError) as exc:
            self._result.configure(text=f"❌ Errore duplica: {exc}")
            return
        self._refresh_saved()
        self._saved_var.set(new_name if new_name in self._saved_map else self._saved_var.get())
        self._result.configure(text=f"📑 Duplicato in {new_name!r}.")

    def _delete_selected(self):
        name = self._saved_var.get()
        if name == self._NONE_SAVED or name not in self._saved_map:
            self._result.configure(text="⛔ Nessun parser selezionato.")
            return
        try:
            removed = ParserBuilder.delete_saved(name)
        except OSError as exc:
            # Permessi / filesystem: mostra un errore pulito invece di crashare il
            # callback (stesso pattern di _save/_load/_duplicate_selected).
            self._result.configure(text=f"❌ Errore eliminazione: {exc}")
            return
        self._refresh_saved()
        self._result.configure(
            text=f"🗑 Eliminato {name!r}." if removed else f"⛔ {name!r} non trovato.")

    def _test(self):
        self._reload_profile_checks()   # rifletti modifiche al dizionario fatte altrove (Codex)
        self._sync_to_builder()
        unresolved = self._unresolved_selected()
        if unresolved:
            # Mappatura richiesta ma con profili non risolvibili: non mostrare un'anteprima
            # fuorviante (col rischio di EventName grezzo). Blocca con spiegazione (Codex).
            self._result.configure(
                text=f"⛔ Non pronto: profili di mappatura mancanti ({', '.join(unresolved)}). "
                     "Ricreali nel «Dizionario nomi» o togli la spunta.")
            return
        message = self._msg_box.get("1.0", "end").rstrip("\n")
        # Modalità EFFETTIVA per l'anteprima: quella scelta; se "(eredita globale)" ("")
        # usa la modalità globale, così "Prova messaggio" combacia col runtime (Codex).
        mode = self._label_to_mode(self._mode_var.get()) or self._global_mode
        # Verdetto sintetico + diagnostica per-campo (CP-08b). Il verdetto usa la
        # diagnostica (`diag.placeable`/`diag.status`), che include ANCHE il gate di
        # contenuto: così "Prova messaggio" non dice "Pronto" per un parser che il
        # runtime scarterebbe come NO_CONTENT_MATCH (Codex).
        # Quota richiesta sì/no = riga Price del parser (unico comando). Lo stesso
        # valore guida sia il verdetto sintetico sia la diagnostica per-campo, così
        # "Prova messaggio" combacia col runtime.
        defn = self.builder.to_def()
        require_price = defn.price_required()
        # Mappatura nomi: risolvi i profili selezionati dalla config, così l'anteprima
        # traduce l'EventName come il runtime (e fa fail-closed se non mappabile) invece
        # di mostrare un falso "Pronto" col nome grezzo.
        name_mapping_profiles = self._resolve_mapping_profiles(defn)
        res = self.builder.test_message(message, provider=self._provider, mode=mode,
                                        require_price=require_price,
                                        name_mapping_profiles=name_mapping_profiles)
        diag = parser_diagnostics.diagnose(
            defn, message, provider=self._provider, mode=mode, require_price=require_price,
            name_mapping_profiles=name_mapping_profiles)
        if diag.placeable:
            riga = ", ".join(f"{k}={v}" for k, v in res.row.items() if v != "")
            self._result.configure(text=f"✅ Pronto · {riga}")
        else:
            extra = f" · mancanti: {', '.join(res.missing_required)}" if res.missing_required else ""
            self._result.configure(text=f"⛔ Non pronto ({diag.status}){extra}")
        self._last_report = parser_diagnostics.format_report(diag)
        self._render_diag_table(parser_diagnostics.diagnostic_table(diag, defn))

    def _render_diag_table(self, rows):
        """Disegna la tabella diagnostica da righe già pronte (logica in
        `parser_diagnostics.diagnostic_table`): qui solo widget."""
        for child in self._diag_table.winfo_children():
            child.destroy()

        def add_cells(values, *, header=False, color=None):
            row = ctk.CTkFrame(self._diag_table, fg_color="transparent")
            row.pack(fill="x", pady=1)
            font = ctk.CTkFont(size=11, weight="bold" if header else "normal")
            for (txt, (_, w)) in zip(values, self._diag_cols):
                ctk.CTkLabel(row, text=txt, width=w, anchor="w", justify="left",
                             wraplength=w - 6, font=font, text_color=color).pack(side="left", padx=2)

        add_cells([c for c, _ in self._diag_cols], header=True)
        for r in rows:
            target = r.target if (r.required or r.banner) else f"{r.target}  (opz)"
            add_cells([target, r.status, r.reason, r.start_after, r.end_before, r.extracted],
                      color=None if r.ok else "#ef5350")

    def _copy_diag(self):
        """Copia l'ultimo report di diagnostica negli appunti (per incollarlo)."""
        if not self._last_report:
            self._result.configure(text="⛔ Premi prima «Prova messaggio».")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._last_report)
        except Exception:                       # noqa: BLE001 — clipboard non disponibile
            self._result.configure(text="❌ Copia non riuscita (appunti non disponibili).")
            return
        self._result.configure(text="📋 Diagnostica copiata negli appunti.")


class CustomParserWindow(ctk.CTkToplevel):
    """Finestra standalone che ospita `CustomParserPanel` a tutta finestra.

    Mantenuta per compatibilità; la stessa `CustomParserPanel` vive anche come scheda
    "🧩 Parser" della finestra "🧰 Strumenti"."""

    def __init__(self, master=None, builder: ParserBuilder = None, provider: str = "",
                 global_mode: str = "", on_saved=None):
        super().__init__(master)
        self.title("Parser Personalizzato")
        gui_utils.fit_to_screen(self, 1024, 720, 760, 480)
        CustomParserPanel(self, builder=builder, provider=provider,
                          global_mode=global_mode, on_saved=on_saved).pack(
                              fill="both", expand=True)
