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

from . import (
    config_store,
    gui_utils,
    market_mapping_store,
    name_mapping_store,
    parser_diagnostics,
    provider_store,
    sports,
)
from .custom_parser import MultiRowRule
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
    # Voce della tendina Sport per il sentinella "" (parser agnostico, PR-P9).
    _SPORT_UNSPECIFIED = "(non specificato)"

    def _mode_to_label(self, mode: str) -> str:
        return self._MODE_INHERIT if not mode else mode

    def _label_to_mode(self, label: str) -> str:
        return "" if label == self._MODE_INHERIT else label

    def _sport_to_label(self, sport: str) -> str:
        return self._SPORT_UNSPECIFIED if not sport else sport

    def _label_to_sport(self, label: str) -> str:
        return "" if label == self._SPORT_UNSPECIFIED else label

    def _on_sport_change(self, _value=None):
        """Sport cambiato dal menu: aggiorna il builder (canonicalizzazione/fail-safe in
        `set_sport`). Non tocca le regole né l'obbligatorietà (lo sport non cambia le colonne)."""
        self.builder.set_sport(self._label_to_sport(self._sport_var.get()))

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

    # ── mappatura mercati (profili) ────────────────────────────────────────
    # Speculare alla mappatura nomi sopra, ma su `market_mapping_profiles` /
    # `market_mapping_store` (config `market_mappings`). Metodi PARALLELI dedicati (non un
    # refactor di quelli nomi) per non rischiare regressioni sul path nomi già collaudato.
    @staticmethod
    def _load_market_mapping_profiles() -> list:
        """Nomi dei profili mercati salvati (best-effort: config illeggibile → [])."""
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception:                       # noqa: BLE001 — fallback sicuro
            return []
        return market_mapping_store.profile_names(cfg)

    def _reload_market_profile_checks(self, use_builder=False):
        """Ridisegna le checkbox dei profili MERCATI. La selezione viene da
        `builder.market_mapping_profiles` (su `use_builder`) o dalle checkbox correnti.

        Come per i nomi, mostra i profili esistenti + i selezionati ma non più esistenti
        come voci ⚠ **fantasma**: restano una checkbox da togliere e `_unresolved_market_selected`
        le intercetta per bloccare save/preview, così un profilo mercati rinominato/eliminato
        non viene riscritto stantio nel parser (→ MARKET_MAPPING_MISSING, Codex P2)."""
        if use_builder or not self._market_profile_checks:
            selected = list(self.builder.market_mapping_profiles)
        else:
            selected = self._selected_market_profiles()
        selected_set = set(selected)
        for child in self._market_profiles_box.winfo_children():
            child.destroy()
        self._market_profile_checks = {}
        existing = list(self._load_market_mapping_profiles())
        self._existing_market_profiles = set(existing)
        missing = [n for n in selected if n not in self._existing_market_profiles]
        names = existing + [n for n in missing if n not in existing]
        if not names:
            ctk.CTkLabel(self._market_profiles_box, text="(nessun profilo)",
                         text_color="gray").pack(side="left", padx=4)
            return
        for name in names:
            present = name in self._existing_market_profiles
            var = ctk.BooleanVar(value=name in selected_set)
            kw = {} if present else {"text_color": "#ffa726"}   # ⚠ profilo mancante
            ctk.CTkCheckBox(self._market_profiles_box, text=name if present else f"⚠ {name}",
                            variable=var, width=20, **kw).pack(side="left", padx=4)
            self._market_profile_checks[name] = var

    def _selected_market_profiles(self) -> list:
        """Profili mercati spuntati, preservando l'ordine scelto nel parser (come i nomi):
        i profili già in `builder.market_mapping_profiles` mantengono la posizione, i nuovi
        si aggiungono in coda. I profili ⚠ mancanti selezionati restano inclusi (li blocca
        `_unresolved_market_selected`)."""
        checked = {name for name, var in self._market_profile_checks.items() if var.get()}
        ordered = [n for n in self.builder.market_mapping_profiles if n in checked]
        ordered += [n for n in self._market_profile_checks if n in checked and n not in ordered]
        return ordered

    def _unresolved_market_selected(self) -> list:
        """Profili mercati selezionati che non esistono più (voci ⚠ fantasma): finché ce ne
        sono spuntati, `_save`/`_test` si bloccano — una mappatura mercati richiesta ma non
        risolvibile non deve diventare in silenzio «nessuna mappatura»."""
        return [n for n in self._selected_market_profiles()
                if n not in self._existing_market_profiles]

    @staticmethod
    def _resolve_market_mapping_profiles(defn):
        """Voci dei profili mercati del parser risolte dalla config (per l'anteprima), o
        None se il parser non usa la mappatura mercati. Best-effort: config illeggibile →
        lista vuota.

        Semantica `None` vs `[]` (Sourcery): per i mercati la distinzione NON è significativa
        a valle. Il runtime (`custom_pipeline.build_validated_row`) attiva l'hook in base a
        `defn.market_mapping_profiles` (i NOMI dei profili scelti nel parser) e coalizza
        l'argomento con `market_mapping_profiles or []`: quindi `None` e `[]` producono lo
        stesso percorso (`resolve_market(text, [])` → stato "none"). Il fail-closed dei
        mercati è «nessuna frase combacia **e** nessun mercato dalle regole-colonna →
        `MARKET_MAPPING_MISSING`» (mode-aware), valido in entrambi i casi. È un'asimmetria
        VOLUTA rispetto ai nomi: i nomi DEVONO essere tradotti (config illeggibile ⇒
        `MAPPING_MISSING`, fail-closed), i mercati invece ripiegano sulla regola-colonna
        quando nessuna frase combacia (precedenza D1). `entries_for_profiles` ignora da sé i
        profili assenti, quindi una config illeggibile non scrive mai un mercato a caso."""
        if not defn.market_mapping_profiles:
            return None
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception:                       # noqa: BLE001 — fallback sicuro
            cfg = {}
        return market_mapping_store.entries_for_profiles(cfg, defn.market_mapping_profiles)

    def _open_market_mapping(self):
        """Apre il Dizionario mercati (finestra separata). Alla chiusura/salvataggio
        ricarica le checkbox dei profili mercati così le nuove voci compaiono subito."""
        self._sync_to_builder()              # non perdere selezione corrente
        from .name_mapping_gui import MarketMappingWindow

        def _on_saved(new_cfg):
            if callable(self._on_saved):
                self._on_saved(new_cfg)
            self._reload_market_profile_checks()

        win = MarketMappingWindow(self, on_saved=_on_saved)
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
        self._reload_market_profile_checks()  # idem per i profili mercati

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
        # Sport DEL PARSER (PR-P9): Calcio/Tennis/Basket/Rugby Union o "(non specificato)"
        # (= agnostico). Non cambia le colonne CSV; nelle PR successive restringe la
        # risoluzione degli ID Betfair all'event_type_id corretto.
        ctk.CTkLabel(top, text="Sport:").pack(side="left", padx=6)
        self._sport_var = ctk.StringVar(value=self._sport_to_label(self.builder.sport))
        ctk.CTkOptionMenu(top, variable=self._sport_var,
                          values=[self._sport_to_label(s) for s in self.builder.sport_options()],
                          width=150, command=self._on_sport_change).pack(side="left", padx=6)
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

        # Mappatura mercati a frase: profili (checkbox multi-selezione) che traducono una
        # frase-mercato del messaggio nel Mercato/Selezione XTrader (market_mapping_store).
        mm = ctk.CTkFrame(outer, fg_color="transparent")
        mm.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(mm, text="Mappatura mercati:").pack(side="left", padx=6)
        ctk.CTkButton(mm, text="🎯 Dizionario mercati", width=170,
                      command=self._open_market_mapping).pack(side="left", padx=6)
        ctk.CTkLabel(mm, text="Profili:").pack(side="left", padx=(8, 2))
        self._market_profiles_box = ctk.CTkScrollableFrame(mm, height=42, orientation="horizontal")
        self._market_profiles_box.pack(side="left", fill="x", expand=True, padx=4)
        self._market_profile_checks = {}        # nome profilo mercati → BooleanVar
        self._existing_market_profiles = set()  # profili mercati realmente in config (non ⚠)
        self._reload_market_profile_checks()

        # Output multi-riga (#192): un solo messaggio → più righe CSV. Due interruttori
        # indipendenti (MultiMarket = più mercati diversi della stessa partita; MultiSelection
        # = più selezioni dello stesso mercato) + righe dinamiche [+]/[Rimuovi]. Spento =
        # single-row come prima. La logica (round-trip, anteprima) sta nel controller, testata
        # in CI; qui SOLO i widget. Il banner sotto avvisa quando entrambi attivi (righe
        # separate, non cartesiane).
        self._build_multi_section(outer)

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
        # Anteprima multi-riga (#192): TABELLA con UNA riga per ogni riga CSV generata
        # (base, oppure le righe MultiMarket/MultiSelection), col verdetto per-riga. Resta
        # vuota finché non si preme «Prova messaggio».
        ctk.CTkLabel(test, text="Anteprima righe generate (#192):").pack(anchor="w", padx=6)
        self._preview_table = ctk.CTkFrame(test, fg_color="transparent")
        self._preview_table.pack(fill="x", padx=6, pady=(0, 4))
        # Larghezze colonne della tabella anteprima (px), in ordine.
        self._preview_cols = (("#", 30), ("Tipo", 90), ("Esito", 70),
                              ("Riga CSV (campi valorizzati)", 560))
        # Diagnostica per-campo (CP-08b): TABELLA — perché "Non pronto", colonna per colonna.
        ctk.CTkLabel(test, text="Diagnostica (una riga per colonna):").pack(anchor="w", padx=6)
        self._diag_table = ctk.CTkFrame(test, fg_color="transparent")
        self._diag_table.pack(fill="x", padx=6, pady=(0, 4))
        # Larghezze colonne della tabella diagnostica (px), in ordine.
        self._diag_cols = (("Colonna", 110), ("Stato", 64), ("Motivo", 280),
                           ("Inizia dopo", 120), ("Finisce prima", 120), ("Valore estratto", 170))
        self._last_report = ""   # testo per "Copia diagnostica"

    # ── output multi-riga (#192): MultiMarket / MultiSelection ──────────────
    # Campi editabili di UNA riga multi (attributo MultiRowRule → etichetta, larghezza px).
    # Un campo vuoto EREDITA dalla riga base; per MultiSelection di norma basta «Selezione».
    _MULTI_FIELDS = (
        ("market_type", "Tipo mercato", 150),
        ("market_name", "Mercato", 160),
        ("selection_name", "Selezione", 150),
        ("price", "Quota", 70),
        ("bet_type", "BetType", 90),
        ("handicap", "Handicap", 90),
    )

    def _build_multi_section(self, outer):
        """Sezione output multi-riga: due interruttori + due liste di righe dinamiche.
        Solo widget; lo stato vive nel `ParserBuilder` (round-trip/anteprima testati in CI)."""
        sec = ctk.CTkFrame(outer)
        sec.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(sec, text="Output multi-riga (un messaggio → più righe CSV)",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))

        # MultiMarket: più mercati diversi della stessa partita.
        mk = ctk.CTkFrame(sec, fg_color="transparent")
        mk.pack(fill="x", padx=8, pady=2)
        self._multi_market_var = ctk.BooleanVar(value=bool(self.builder.multi_market_enabled))
        ctk.CTkCheckBox(mk, text="MultiMarket (più mercati)", variable=self._multi_market_var,
                        command=self._on_multi_toggle).pack(side="left", padx=4)
        ctk.CTkButton(mk, text="➕ Aggiungi mercato", width=160,
                      command=self._add_multi_market_clicked).pack(side="left", padx=6)
        self._multi_markets_box = ctk.CTkFrame(sec, fg_color="transparent")
        self._multi_markets_box.pack(fill="x", padx=8, pady=(0, 4))
        self._multi_market_rows = []     # refs per riga MultiMarket

        # MultiSelection: più selezioni dello stesso mercato (eredita il mercato dalla base).
        ms = ctk.CTkFrame(sec, fg_color="transparent")
        ms.pack(fill="x", padx=8, pady=2)
        self._multi_selection_var = ctk.BooleanVar(value=bool(self.builder.multi_selection_enabled))
        ctk.CTkCheckBox(ms, text="MultiSelection (più selezioni)",
                        variable=self._multi_selection_var,
                        command=self._on_multi_toggle).pack(side="left", padx=4)
        ctk.CTkButton(ms, text="➕ Aggiungi selezione", width=160,
                      command=self._add_multi_selection_clicked).pack(side="left", padx=6)
        self._multi_selections_box = ctk.CTkFrame(sec, fg_color="transparent")
        self._multi_selections_box.pack(fill="x", padx=8, pady=(0, 4))
        self._multi_selection_rows = []  # refs per riga MultiSelection

        # Banner avvisi (es. entrambi attivi → righe separate, non cartesiane).
        self._multi_warn = ctk.CTkLabel(sec, text="", anchor="w", justify="left",
                                        text_color="#ffa726")
        self._multi_warn.pack(fill="x", padx=8, pady=(0, 6))

    def _add_multi_row_widget(self, container, refs_list, rule):
        """Disegna UNA riga multi editabile (campi `_MULTI_FIELDS` + abilitata + Rimuovi)."""
        row = ctk.CTkFrame(container, fg_color="transparent")
        row.pack(fill="x", pady=2)
        # Conserva la regola SORGENTE: i campi NON esposti nella GUI (start_after/end_before/
        # min_price/max_price/points) vanno PRESERVATI al salvataggio, altrimenti aprire+salvare
        # un parser azzererebbe in silenzio quei vincoli per-riga cambiando le righe CSV emesse
        # (Codex P1). `_multi_rule_from_refs` riparte da una copia di questa regola.
        refs = {"frame": row, "_rule": rule}
        for attr, label, w in self._MULTI_FIELDS:
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.pack(side="left", padx=2)
            ctk.CTkLabel(cell, text=label, width=w, anchor="w",
                         font=ctk.CTkFont(size=10)).pack(anchor="w")
            entry = ctk.CTkEntry(cell, width=w)
            entry.insert(0, getattr(rule, attr, "") or "")
            entry.pack()
            refs[attr] = entry
        refs["enabled"] = ctk.BooleanVar(value=bool(getattr(rule, "enabled", True)))
        ctk.CTkCheckBox(row, text="Attiva", variable=refs["enabled"], width=40).pack(
            side="left", padx=6)
        ctk.CTkButton(row, text="🗑 Rimuovi", width=90, fg_color="#7f0000",
                      command=lambda: self._remove_multi_row(refs_list, refs)).pack(
                          side="left", padx=4)
        refs_list.append(refs)

    def _remove_multi_row(self, refs_list, refs):
        """Toglie una riga multi (widget + ref) e aggiorna il banner avvisi."""
        try:
            refs_list.remove(refs)
        except ValueError:
            pass
        refs["frame"].destroy()
        self._refresh_multi_warnings()

    def _add_multi_market_clicked(self):
        """[+] mercato: spunta MultiMarket (se serve) e aggiunge una riga vuota."""
        self._multi_market_var.set(True)
        self._add_multi_row_widget(self._multi_markets_box, self._multi_market_rows,
                                   MultiRowRule())
        self._refresh_multi_warnings()

    def _add_multi_selection_clicked(self):
        """[+] selezione: spunta MultiSelection (se serve) e aggiunge una riga vuota."""
        self._multi_selection_var.set(True)
        self._add_multi_row_widget(self._multi_selections_box, self._multi_selection_rows,
                                   MultiRowRule())
        self._refresh_multi_warnings()

    def _on_multi_toggle(self):
        """Interruttore MultiMarket/MultiSelection cambiato: aggiorna solo il banner avvisi
        (lo stato si legge dai widget in `_sync_to_builder`)."""
        self._refresh_multi_warnings()

    def _reload_multi_from_builder(self):
        """Ridisegna interruttori + righe multi dal builder (caricamento parser/nuovo)."""
        self._multi_market_var.set(bool(self.builder.multi_market_enabled))
        self._multi_selection_var.set(bool(self.builder.multi_selection_enabled))
        for refs in list(self._multi_market_rows):
            refs["frame"].destroy()
        self._multi_market_rows = []
        for refs in list(self._multi_selection_rows):
            refs["frame"].destroy()
        self._multi_selection_rows = []
        for rule in self.builder.multi_markets:
            self._add_multi_row_widget(self._multi_markets_box, self._multi_market_rows, rule)
        for rule in self.builder.multi_selections:
            self._add_multi_row_widget(self._multi_selections_box, self._multi_selection_rows, rule)
        self._refresh_multi_warnings()

    def _sync_multi_to_builder(self):
        """Riporta interruttori + righe multi nei campi del builder (per save/anteprima)."""
        self.builder.multi_market_enabled = bool(self._multi_market_var.get())
        self.builder.multi_selection_enabled = bool(self._multi_selection_var.get())
        self.builder.multi_markets = [self._multi_rule_from_refs(r) for r in self._multi_market_rows]
        self.builder.multi_selections = [
            self._multi_rule_from_refs(r) for r in self._multi_selection_rows]

    def _multi_rule_from_refs(self, refs) -> "MultiRowRule":
        """Ricostruisce la `MultiRowRule` da una riga: parte dalla regola SORGENTE e applica
        SOLO gli override visibili (`_MULTI_FIELDS`) + Attiva, preservando i campi non esposti
        (logica in `ParserBuilder.merge_multi_rule_overrides`, testata in CI; Codex P1)."""
        overrides = {attr: refs[attr].get().strip() for attr, _, _ in self._MULTI_FIELDS}
        return ParserBuilder.merge_multi_rule_overrides(
            refs.get("_rule") or MultiRowRule(), overrides,
            enabled=bool(refs["enabled"].get()))

    def _refresh_multi_warnings(self):
        """Aggiorna il banner avvisi dal controller (sincronizza prima i widget)."""
        self._sync_multi_to_builder()
        warnings = self.builder.multi_warnings()
        self._multi_warn.configure(text=("\n".join(f"⚠ {w}" for w in warnings)) if warnings else "")

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
        # Sport (PR-P9): ripristina la tendina dal builder (incl. "" agnostico).
        self._sport_var.set(self._sport_to_label(self.builder.sport))
        # Mappatura nomi: ripristina separatore + checkbox profili dal builder.
        self._separator_var.set(self.builder.team_separator)
        self._reload_profile_checks(use_builder=True)
        # Mappatura mercati: checkbox profili mercati dal builder.
        self._reload_market_profile_checks(use_builder=True)
        # Output multi-riga (#192): interruttori + righe dal builder.
        self._reload_multi_from_builder()
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
        # Sport (PR-P9): canonicalizza un valore NOTO (case-insensitive) ma **preserva**
        # un valore ignoto (es. parser caricato con sport corrotto a mano) invece di
        # azzerarlo a "" qui: così `validate_parser_def` può emettere "Sport non valido"
        # (fail-closed) e il salvataggio è bloccato, invece di convertirlo in silenzio in
        # agnostico perdendo lo scope sport (Codex). La tendina offre solo valori validi,
        # quindi un valore ignoto può arrivare SOLO da un file manomesso.
        _sport_raw = self._label_to_sport(self._sport_var.get())
        self.builder.sport = sports.normalize_sport(_sport_raw) or _sport_raw
        # Mappatura nomi: separatore (testo libero) + profili spuntati.
        self.builder.team_separator = self._separator_var.get().strip()
        self.builder.name_mapping_profiles = self._selected_profiles()
        # Mappatura mercati: profili mercati spuntati.
        self.builder.market_mapping_profiles = self._selected_market_profiles()
        # Output multi-riga (#192): interruttori + righe MultiMarket/MultiSelection.
        self._sync_multi_to_builder()
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
        self._reload_market_profile_checks()   # idem per i profili mercati (Codex P2)
        self._sync_to_builder()
        unresolved = self._unresolved_selected()
        if unresolved:
            self._result.configure(
                text=f"⛔ Non salvato: profili di mappatura nomi mancanti ({', '.join(unresolved)}). "
                     "Ricreali nel «Dizionario nomi» o togli la spunta prima di salvare.")
            return
        unresolved_mkt = self._unresolved_market_selected()
        if unresolved_mkt:
            # Stesso fail-closed dei nomi: un profilo mercati rinominato/eliminato non deve
            # essere riscritto stantio nel parser (→ MARKET_MAPPING_MISSING a runtime, Codex P2).
            self._result.configure(
                text=f"⛔ Non salvato: profili di mappatura mercati mancanti ({', '.join(unresolved_mkt)}). "
                     "Ricreali nel «Dizionario mercati» o togli la spunta prima di salvare.")
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
        self._reload_market_profile_checks()
        self._sync_to_builder()
        unresolved = self._unresolved_selected()
        if unresolved:
            # Mappatura richiesta ma con profili non risolvibili: non mostrare un'anteprima
            # fuorviante (col rischio di EventName grezzo). Blocca con spiegazione (Codex).
            self._result.configure(
                text=f"⛔ Non pronto: profili di mappatura nomi mancanti ({', '.join(unresolved)}). "
                     "Ricreali nel «Dizionario nomi» o togli la spunta.")
            return
        unresolved_mkt = self._unresolved_market_selected()
        if unresolved_mkt:
            self._result.configure(
                text=f"⛔ Non pronto: profili di mappatura mercati mancanti ({', '.join(unresolved_mkt)}). "
                     "Ricreali nel «Dizionario mercati» o togli la spunta.")
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
        # Mappatura mercati: risolvi i profili mercati dalla config così l'anteprima imposta
        # Mercato/Selezione come il runtime (o fa fail-closed con MARKET_MAPPING_MISSING).
        market_mapping_profiles = self._resolve_market_mapping_profiles(defn)
        res = self.builder.test_message(message, provider=self._provider, mode=mode,
                                        require_price=require_price,
                                        name_mapping_profiles=name_mapping_profiles,
                                        market_mapping_profiles=market_mapping_profiles)
        diag = parser_diagnostics.diagnose(
            defn, message, provider=self._provider, mode=mode, require_price=require_price,
            name_mapping_profiles=name_mapping_profiles,
            market_mapping_profiles=market_mapping_profiles)
        # Anteprima multi-riga (#192): tutte le righe generate (base o MultiMarket/
        # MultiSelection), col verdetto per-riga. Stesso motore del runtime.
        preview = self.builder.preview_rows(
            message, provider=self._provider, mode=mode, require_price=require_price,
            name_mapping_profiles=name_mapping_profiles,
            market_mapping_profiles=market_mapping_profiles)
        # Verdetto sintetico. Con output multi-riga attivo si basa sulle RIGHE GENERATE
        # (non sulla sola base, che può mancare di MarketType/SelectionName di proposito),
        # così il titolo non contraddice la tabella (Codex P2). Single-row → verdetto diag.
        multi_active = any(p.kind != "base" for p in preview)
        if multi_active:
            self._result.configure(text=ParserBuilder.preview_summary(preview))
        elif diag.placeable:
            riga = ", ".join(f"{k}={v}" for k, v in res.row.items() if v != "")
            self._result.configure(text=f"✅ Pronto · {riga}")
        else:
            extra = f" · mancanti: {', '.join(res.missing_required)}" if res.missing_required else ""
            self._result.configure(text=f"⛔ Non pronto ({diag.status}){extra}")
        self._last_report = parser_diagnostics.format_report(diag)
        self._render_diag_table(parser_diagnostics.diagnostic_table(diag, defn))
        self._render_preview_table(preview)

    _MULTI_KIND_LABEL = {"base": "Base", "market": "Mercato", "selection": "Selezione"}

    def _render_preview_table(self, preview_rows):
        """Disegna la tabella anteprima multi-riga (#192) da `PreviewRow` già pronte
        (`ParserBuilder.preview_rows`, testata in CI): qui solo widget. Verde = riga
        piazzabile, rosso = scartata (col motivo `status`)."""
        for child in self._preview_table.winfo_children():
            child.destroy()

        def add_cells(values, *, header=False, color=None):
            row = ctk.CTkFrame(self._preview_table, fg_color="transparent")
            row.pack(fill="x", pady=1)
            font = ctk.CTkFont(size=11, weight="bold" if header else "normal")
            for (txt, (_, w)) in zip(values, self._preview_cols):
                ctk.CTkLabel(row, text=txt, width=w, anchor="w", justify="left",
                             wraplength=w - 6, font=font, text_color=color).pack(side="left", padx=2)

        add_cells([c for c, _ in self._preview_cols], header=True)
        if not preview_rows:
            add_cells(["", "", "", "(nessuna riga)"], color="gray")
            return
        for pr in preview_rows:
            kind = self._MULTI_KIND_LABEL.get(pr.kind, pr.kind)
            esito = "✅" if pr.placeable else f"⛔ {pr.status}"
            add_cells([str(pr.index + 1), kind, esito, pr.summary],
                      color=None if pr.placeable else "#ef5350")

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
