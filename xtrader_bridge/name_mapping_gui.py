"""Finestra di gestione del Dizionario nomi squadra (profili di mappatura).

Permette di **creare/rinominare/eliminare** profili di mappatura e di **modificarne
la tabella** ``Country | Betfair/XTrader | Come lo scrive il canale`` (entrambe le colonne nome a
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

import copy

import customtkinter as ctk

from . import (
    config_store,
    custom_parser,
    dizionario,
    gui_utils,
    i18n,
    market_mapping_store,
    name_mapping_store,
    recognition,
    sports,
)

# Etichetta della tendina Sport per la riga agnostica ("" = vale per tutti gli sport).
_SPORT_ALL = "(tutti gli sport)"
# Etichetta della tendina Tipo entità per la riga agnostica ("" = qualsiasi tipo).
_ENTITY_ALL = "(qualsiasi tipo)"
# Etichetta della tendina Lingua-fonte per la riga agnostica ("" = vale per tutte le lingue).
_LANGUAGE_ALL = "(tutte le lingue)"

# Etichetta VISIBILE della colonna «alias del canale» nel Dizionario nomi squadra (#293):
# rinominata da «Provider» a «Come lo scrive il canale» per eliminare la collisione con
# l'anagrafica «Provider» (etichetta della colonna CSV). SOLO l'etichetta cambia: la chiave dati
# nello store resta `provider` e la colonna CSV «Provider» è invariata.
_CHANNEL_ALIAS_COLUMN = "Come lo scrive il canale"

# Colonne (etichetta, larghezza px) dell'intestazione tabella del Dizionario nomi squadra.
# Fonte unica usata da `_build_ui` E dal test di regressione (`test_channel_alias_rename.py`),
# così la verifica dell'etichetta è sul DATO reale dell'header, non su una grep del sorgente.
_HEADER_COLUMNS = (("Country (opz.)", 180), ("Betfair / XTrader", 240),
                   (_CHANNEL_ALIAS_COLUMN, 240), ("Sport", 150), ("Tipo", 150),
                   ("Lingua", 130))

# Colonne (etichetta, larghezza px) dell'intestazione tabella del Dizionario MERCATI. Fonte
# unica usata da `MarketMappingPanel._build_ui` E dal test di regressione, come `_HEADER_COLUMNS`
# per i nomi: la verifica dell'etichetta «Lingua» (epica #3 slice 5c) è sul DATO reale
# dell'header, non su una grep del sorgente.
_MARKET_HEADER_COLUMNS = (("Inizia dopo", 120), ("Finisce prima", 120), ("Testo mercato", 140),
                          ("Mercato (catalogo)", 200), ("Selezione (catalogo)", 200),
                          ("Lingua", 130))


def _sport_to_label(sport: str) -> str:
    return _SPORT_ALL if not sport else sport


def _label_to_sport(label: str) -> str:
    return "" if label == _SPORT_ALL else label


def _entity_to_label(entity_type: str) -> str:
    return _ENTITY_ALL if not entity_type else entity_type


def _label_to_entity(label: str) -> str:
    return "" if label == _ENTITY_ALL else label


def _language_to_label(language: str) -> str:
    return _LANGUAGE_ALL if not language else language


def _label_to_language(label: str) -> str:
    return "" if label == _LANGUAGE_ALL else label


class NameMappingPanel(ctk.CTkFrame):
    """Pannello del Dizionario nomi squadra (area "Calcio" del Mapping) — incassabile
    in finestra standalone (`NameMappingWindow`) o come area della scheda "Mapping"
    della finestra "🧰 Strumenti".

    `on_saved(new_cfg)`: callback opzionale chiamata dopo ogni salvataggio riuscito,
    così la GUI principale aggiorna la propria config in memoria."""

    _NO_PROFILE = "(nessun profilo)"

    def __init__(self, master=None, on_saved=None, known_teams_provider=None):
        super().__init__(master)
        self._on_saved = on_saved
        # Fonte dei nomi squadra PERMANENTI del dizionario locale (#282 PR 11):
        # callable() → lista di dict {sport, display_name, ...}. Opzionale: se assente/None
        # il pulsante «Precompila» avvisa invece di precompilare (nessun crash, fail-safe).
        self._known_teams_provider = known_teams_provider
        self._current = None              # nome profilo selezionato
        self._row_widgets = []            # [{frame, country, betfair, provider}, ...]
        self._build_ui()
        self._reload_profiles(select_first=True)

    def refresh(self, cfg=None):
        """Ricarica profili e righe del dizionario nomi.

        Da chiamare quando la config cambia da FUORI (es. un profilo applicato nella
        stessa finestra "🧰 Strumenti"): senza, un Salva successivo riscriverebbe il
        dizionario nomi stantio sopra il profilo (Codex).

        `cfg`: config VIVA da usare al posto del disco (P3-7 #76) — con un profilo
        applicato ma NON persistito il disco è ancora pre-profilo. `None` = disco."""
        self._reload_profiles(select_first=True, cfg=cfg)

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text=i18n.tr("🗺️  Dizionario nomi squadra"),
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self, text=i18n.tr(
                "Traduce i nomi squadra così come li scrive il canale nel nome atteso da "
                "Betfair/XTrader. Seleziona i profili nel Parser Personalizzato."),
            font=ctk.CTkFont(size=11), text_color="gray", wraplength=720,
            anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        # Riga profili: selettore + nuovo / rinomina / elimina.
        prof = ctk.CTkFrame(self, fg_color="transparent")
        prof.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(prof, text=i18n.tr("Profilo:")).pack(side="left", padx=(6, 4))
        self._profile_var = ctk.StringVar(value=self._NO_PROFILE)
        self._profile_menu = ctk.CTkOptionMenu(
            prof, variable=self._profile_var, values=[self._NO_PROFILE], width=220,
            command=self._on_profile_change)
        self._profile_menu.pack(side="left", padx=4)
        ctk.CTkButton(prof, text=i18n.tr("🆕 Nuovo"), width=84, command=self._new_profile).pack(side="left", padx=3)
        ctk.CTkButton(prof, text=i18n.tr("✏️ Rinomina"), width=96, command=self._rename_profile).pack(side="left", padx=3)
        ctk.CTkButton(prof, text=i18n.tr("🗑 Elimina"), width=90, fg_color="#7f0000",
                      hover_color="#5a0000", command=self._delete_profile).pack(side="left", padx=3)

        # Intestazione tabella. Etichette colonna (costanti `_HEADER_COLUMNS`) tradotte alla
        # resa; la chiave dati e i test di regressione usano la costante IT invariata.
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(4, 0))
        for text, w in _HEADER_COLUMNS:
            ctk.CTkLabel(head, text=i18n.tr(text), width=w, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=3)

        self._rows_frame = ctk.CTkScrollableFrame(
            self, height=380, label_text=i18n.tr("Righe del profilo"))
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=6)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(actions, text=i18n.tr("➕ Aggiungi riga"), width=140,
                      command=self._add_row).pack(side="left", padx=3)
        # Precompila la colonna Betfair coi nomi squadra permanenti (#282 PR 11): riempie
        # le righe coi nomi reali già raccolti dalla sync, tu affianchi solo l'alias del
        # canale nella colonna «Come lo scrive il canale». Niente tendina: scritti direttamente.
        ctk.CTkButton(actions, text=i18n.tr("📥 Precompila da Betfair"), width=190, fg_color="#1565c0",
                      hover_color="#0d47a1", command=self._prefill_betfair_names).pack(side="left", padx=3)
        ctk.CTkButton(actions, text=i18n.tr("💾 Salva profilo"), width=140, fg_color="#2e7d32",
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
            self._status.configure(text=i18n.tr("❌ Config illeggibile: {exc}").format(exc=exc),
                                   text_color="#ef5350")
            return None

    def _reload_profiles(self, select=None, select_first=False, cfg=None):
        """Ricarica la tendina dei profili da config e seleziona quello indicato.
        `cfg` fornita = fonte viva (P3-7 #76), propagata anche alle righe; `None` = disco."""
        if cfg is None:
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
        self._reload_rows(cfg)

    def _reload_rows(self, cfg=None):
        """Ridisegna la tabella dalle righe salvate del profilo corrente
        (da `cfg` viva se fornita, altrimenti da disco)."""
        for child in self._rows_frame.winfo_children():
            child.destroy()
        self._row_widgets = []
        if not self._current:
            ctk.CTkLabel(self._rows_frame, text=i18n.tr("Nessun profilo. Crea un profilo con «Nuovo»."),
                         text_color="gray").pack(anchor="w", padx=6, pady=4)
            return
        if cfg is None:
            cfg = self._load_cfg()
        entries = name_mapping_store.get_entries(cfg, self._current) if cfg is not None else []
        for e in entries:
            self._append_row_widget(e.get("country", ""), e.get("betfair", ""),
                                    e.get("provider", ""), e.get("sport", ""),
                                    e.get("entity_type", ""), e.get("language", ""))
        if not entries:
            self._append_row_widget()                   # una riga vuota pronta da compilare

    def _append_row_widget(self, country="", betfair="", provider="", sport="",
                           entity_type="", language=""):
        """Aggiunge una riga di widget (3 Entry + tendina Sport + Tipo + Lingua + elimina)."""
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
        # Sport (PR-P10): «(tutti gli sport)» = riga agnostica; altrimenti restringe la
        # riga a uno sport. La tendina offre solo valori validi.
        sport_var = ctk.StringVar(value=_sport_to_label(sport))
        ctk.CTkOptionMenu(row, variable=sport_var, width=150,
                          values=[_SPORT_ALL, *sports.SPORTS]).pack(side="left", padx=3)
        # Tipo entità (PR-P10 / #178 §2): «(qualsiasi tipo)» = agnostico; altrimenti
        # restringe la riga a participant/team/player/competition/market/selection.
        entity_var = ctk.StringVar(value=_entity_to_label(entity_type))
        ctk.CTkOptionMenu(row, variable=entity_var, width=150,
                          values=[_ENTITY_ALL, *name_mapping_store.ENTITY_TYPES]
                          ).pack(side="left", padx=3)
        # Lingua-fonte (#3 slice 5b): «(tutte le lingue)» = riga agnostica; altrimenti restringe
        # la riga alla lingua del palinsesto (IT/EN/ES), prioritaria sull'agnostica nel matching.
        language_var = ctk.StringVar(value=_language_to_label(language))
        ctk.CTkOptionMenu(row, variable=language_var, width=130,
                          values=[_LANGUAGE_ALL, *recognition.SOURCE_LANGUAGES]
                          ).pack(side="left", padx=3)
        refs = {"frame": row, "country": e_country, "betfair": e_betfair,
                "provider": e_provider, "sport": sport_var, "entity_type": entity_var,
                "language": language_var}
        ctk.CTkButton(row, text="🗑", width=36, fg_color="#c62828", hover_color="#7f0000",
                      command=lambda r=refs: self._delete_row(r)).pack(side="left", padx=3)
        self._row_widgets.append(refs)

    def _collect_rows(self) -> list:
        """Righe correnti dai widget come dict {country, betfair, provider, sport,
        entity_type, language} (la pulizia delle righe vuote la fa
        `name_mapping_store.set_entries`)."""
        return [
            {"country": r["country"].get(), "betfair": r["betfair"].get(),
             "provider": r["provider"].get(), "sport": _label_to_sport(r["sport"].get()),
             "entity_type": _label_to_entity(r["entity_type"].get()),
             "language": _label_to_language(r["language"].get())}
            for r in self._row_widgets
        ]

    # ── azioni righe ─────────────────────────────────────────────────────────
    def _add_row(self):
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Crea prima un profilo con «Nuovo»."),
                                   text_color="#ef5350")
            return
        # Riga vuota da compilare: nessun argomento posizionale (tutti i campi ai
        # default vuoti), come la riga iniziale in `_render`. Evita l'under-fill
        # posizionale fragile `("", "", "")` su una firma a 5 parametri (#184 LOW):
        # un riordino della firma non sposterebbe più i tre "" sui campi sbagliati.
        self._append_row_widget()

    def _delete_row(self, refs):
        refs["frame"].destroy()
        self._row_widgets = [r for r in self._row_widgets if r is not refs]

    def _prefill_betfair_names(self):
        """Precompila la colonna Betfair con TUTTI i nomi squadra permanenti presenti nel
        dizionario locale (#282 PR 11). Aggiunge una riga per ogni nome noto con il **nome Betfair
        FISSO già scritto** (nessun menu a tendina), lo **Sport** impostato e il tipo `team`;
        la colonna **«Come lo scrive il canale»** resta vuota perché ci scrivi l'alias del canale.

        Idempotente e non distruttivo: NON tocca le righe esistenti e **salta** i nomi già
        presenti (stesso sport + nome normalizzato, con la stessa normalizzazione del
        resolver). Fail-safe: senza dizionario Betfair (o sync mai fatta) avvisa e non
        aggiunge nulla, invece di crashare. Le righe aggiunte vanno **salvate** con 💾."""
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Crea prima un profilo con «Nuovo»."),
                                   text_color="#ef5350")
            return
        provider = self._known_teams_provider
        if not callable(provider):
            self._status.configure(
                text=i18n.tr("⛔ Dizionario locale vuoto o non disponibile: popola prima il dizionario locale."),
                text_color="#ef5350")
            return
        # `DictionaryBusy`: un altro thread tiene ora il lock del DB → avviso «riprova»
        # invece di congelare la GUI (fail-fast, come il viewer dizionario, #175/#321).
        from .betfair.dictionary_viewer import DictionaryBusy
        try:
            teams = provider() or []
        except DictionaryBusy:
            self._status.configure(
                text=i18n.tr("⏳ Dizionario occupato: riprova tra poco."),
                text_color="#ffa726")
            return
        except Exception as exc:                 # noqa: BLE001 — best-effort, niente crash GUI
            self._status.configure(
                text=i18n.tr("❌ Nomi Betfair non leggibili: {kind}").format(kind=type(exc).__name__),
                text_color="#ef5350")
            return
        # Dedup vs righe già presenti: chiave (sport, nome Betfair normalizzato), così un
        # secondo «Precompila» non duplica e non calpesta gli alias già compilati.
        existing = {(_label_to_sport(r["sport"].get()), dizionario.normalize(r["betfair"].get()))
                    for r in self._row_widgets}
        added = skipped = 0
        for team in teams:
            name = str((team or {}).get("display_name") or "").strip()
            sport = str((team or {}).get("sport") or "").strip()
            if not name:
                continue
            key = (sport, dizionario.normalize(name))
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            # Betfair FISSO scritto nel campo; «Come lo scrive il canale» vuoto (lo compili tu); tipo `team`.
            self._append_row_widget(betfair=name, sport=sport, entity_type="team")
            added += 1
        if added:
            self._status.configure(
                text=i18n.tr("📥 Aggiunti {added} nomi Betfair (scrivi l'alias del canale in "
                             "«Come lo scrive il canale»); {skipped} già presenti. Poi salva con 💾.")
                .format(added=added, skipped=skipped), text_color="#66bb6a")
        else:
            self._status.configure(
                text=i18n.tr("ℹ️ Nessun nuovo nome da aggiungere: ")
                     + (i18n.tr("i {skipped} nomi noti sono già in tabella.").format(skipped=skipped)
                        if skipped else i18n.tr("il dizionario locale è vuoto — popolalo prima.")),
                text_color="gray")

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
            self._status.configure(text=i18n.tr("⛔ Nessun profilo selezionato."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        cfg = name_mapping_store.set_entries(cfg, self._current, self._collect_rows())
        n = len(name_mapping_store.get_entries(cfg, self._current))
        self._persist(
            cfg,
            ok_msg=i18n.tr("💾 Profilo «{name}» salvato ({n} righe valide).").format(
                name=self._current, n=n),
            fail_msg=i18n.tr("❌ Salvataggio FALLITO: «{name}» non salvato (andrebbe perso al "
                             "riavvio). Controlla permessi/spazio del file config.").format(
                name=self._current),
            select=self._current)

    def _on_profile_change(self, value):
        """Cambio profilo: salva prima quello corrente (evita di perdere le modifiche
        non salvate), poi carica il selezionato."""
        new = value if value != self._NO_PROFILE else None
        if new == self._current:
            return
        if self._current:                          # auto-salva il profilo che stai lasciando
            cfg = self._load_cfg()
            if cfg is None:
                # P3-26 #76: config illeggibile → l'auto-save NON può avvenire; proseguire
                # farebbe ricaricare le righe CANCELLANDO l'editing. ANNULLA lo switch
                # (stesso pattern del ramo save-fallito qui sotto): profilo corrente a
                # schermo, righe intatte, l'utente può riprovare.
                self._profile_var.set(self._current)
                self._status.configure(
                    text=i18n.tr("❌ Config illeggibile: cambio profilo annullato, modifiche "
                                 "mantenute a schermo."),
                    text_color="#ef5350")
                return
            if cfg is not None:
                cfg = name_mapping_store.set_entries(cfg, self._current, self._collect_rows())
                saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
                if not ok:
                    # Auto-save fallito: ANNULLA il cambio profilo invece di proseguire,
                    # altrimenti `_reload_rows` cancellerebbe le righe non salvate. Tieni
                    # il profilo corrente a schermo così l'utente può riprovare (Codex).
                    self._profile_var.set(self._current)
                    self._status.configure(
                        text=i18n.tr("❌ Salvataggio FALLITO: cambio profilo annullato, modifiche "
                                 "mantenute a schermo. Controlla permessi/spazio del file config."),
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
        dialog = ctk.CTkInputDialog(text=i18n.tr("Nome del nuovo profilo:"), title=i18n.tr("Nuovo profilo"))
        name = (dialog.get_input() or "").strip()
        if not name:
            self._status.configure(text=i18n.tr("⛔ Profilo non creato (nome vuoto)."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        if name in name_mapping_store.profile_names(cfg):
            self._status.configure(text=i18n.tr("ℹ️ Il profilo «{name}» esiste già.").format(name=name), text_color="gray")
            return
        # Salva prima le righe in editing del profilo corrente: passare a quello nuovo
        # non deve perdere le modifiche non ancora salvate (Codex).
        if self._current:
            cfg = name_mapping_store.set_entries(cfg, self._current, self._collect_rows())
        cfg = name_mapping_store.add_profile(cfg, name)
        self._persist(cfg,
                      ok_msg=i18n.tr("🆕 Profilo «{name}» creato.").format(name=name),
                      fail_msg=i18n.tr("❌ Salvataggio FALLITO: «{name}» non creato.").format(name=name),
                      select=name)

    def _rename_profile(self):
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Nessun profilo selezionato."), text_color="#ef5350")
            return
        dialog = ctk.CTkInputDialog(text=i18n.tr("Nuovo nome per «{name}»:").format(name=self._current), title=i18n.tr("Rinomina profilo"))
        new = (dialog.get_input() or "").strip()
        if not new:
            self._status.configure(text=i18n.tr("⛔ Rinomina annullata (nome vuoto)."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        if new in name_mapping_store.profile_names(cfg):
            self._status.configure(text=i18n.tr("ℹ️ Il profilo «{new}» esiste già.").format(new=new), text_color="gray")
            return
        old = self._current
        # Salva prima le modifiche correnti, poi rinomina (conserva le righe).
        cfg = name_mapping_store.set_entries(cfg, old, self._collect_rows())
        cfg = name_mapping_store.rename_profile(cfg, old, new)
        # Persisti PRIMA la config; solo se il salvataggio riesce riscrivi i riferimenti
        # nei parser salvati. Altrimenti, con un save config fallito, i parser punterebbero
        # a `new` mentre la config ha ancora `old` → MAPPING_MISSING (Codex).
        ok = self._persist(
            cfg,
            ok_msg=i18n.tr("✏️ Profilo rinominato «{old}» → «{new}».").format(old=old, new=new),
            fail_msg=i18n.tr("❌ Salvataggio FALLITO: rinomina non applicata."), select=new)
        if ok:
            # Aggiorna i riferimenti nei parser salvati che usano il vecchio nome, così non
            # restano a chiedere un profilo inesistente (→ MAPPING_MISSING silenzioso).
            try:
                updated, failed = custom_parser.rename_mapping_profile_in_files(old, new)
            except Exception as exc:             # noqa: BLE001 — il rename config resta valido
                # P3-32 #76: MAI il verde con stato IGNOTO — prima l'eccezione veniva
                # inghiottita (updated=failed=[]) e restava il messaggio di successo
                # mentre i parser salvati potevano puntare ancora al vecchio nome
                # (segnali scartati in silenzio, MAPPING_MISSING). Avviso onesto + stop.
                self._status.configure(
                    text=i18n.tr("⚠️ Profilo rinominato «{old}» → «{new}», ma la verifica dei "
                                 "parser salvati è FALLITA ({exc}): controlla a mano quali usano "
                                 "ancora «{old}» o quei segnali verranno scartati "
                                 "(MAPPING_MISSING).").format(old=old, new=new, exc=exc),
                    text_color="#ffa726")
                return
            if failed:
                # Alcuni parser non si sono potuti riscrivere: restano sul vecchio nome
                # mentre la config ha il nuovo → quei segnali andrebbero scartati. Avvisa.
                self._status.configure(
                    text=i18n.tr("⚠️ Profilo rinominato «{old}» → «{new}», ma {count} parser NON "
                                 "aggiornati ({names}): correggili a mano o quei segnali verranno "
                                 "scartati (MAPPING_MISSING).").format(
                        old=old, new=new, count=len(failed), names=', '.join(failed)),
                    text_color="#ffa726")
            elif updated:
                self._status.configure(
                    text=i18n.tr("✏️ Profilo rinominato «{old}» → «{new}» · {count} parser "
                                 "aggiornati.").format(old=old, new=new, count=len(updated)),
                    text_color="#66bb6a")

    def _delete_profile(self):
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Nessun profilo selezionato."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        name = self._current
        # P3-27 #76: eliminazione distruttiva senza undo — conferma fail-closed prima
        # di toccare la config (dialog rotto/headless → NON confermato).
        if not gui_utils.ask_confirm(
                i18n.tr("Elimina profilo"),
                i18n.tr("Eliminare il profilo «{name}» del dizionario nomi?\n"
                        "L'azione non è annullabile.").format(name=name)):
            self._status.configure(
                text=i18n.tr("Eliminazione annullata."), text_color="gray")
            return
        # Avvisa se il profilo è ancora usato da parser salvati: la cancellazione li
        # lascerebbe a chiedere un profilo inesistente → segnali scartati (MAPPING_MISSING,
        # fail-closed). Non lo rimuoviamo in silenzio dai parser (disattivare la mappatura
        # lascerebbe passare l'EventName grezzo): meglio avvisare e far decidere all'utente.
        try:
            affected = custom_parser.parsers_using_mapping_profile(name)
        except Exception:                        # noqa: BLE001 — l'avviso è best-effort
            affected = []
        cfg = name_mapping_store.delete_profile(cfg, name)
        # NON azzerare `_current` prima del salvataggio: su fallimento `_persist` non ricarica
        # e la UI mostrerebbe "nessun profilo" col profilo ancora su disco (desync, Sourcery).
        # Su successo è `_reload_profiles` a portarlo a None; su fallimento resta coerente.
        ok = self._persist(
            cfg,
            ok_msg=i18n.tr("🗑 Profilo «{name}» eliminato.").format(name=name),
            fail_msg=i18n.tr("❌ Salvataggio FALLITO: «{name}» non eliminato.").format(name=name))
        if ok and affected:
            self._status.configure(
                text=i18n.tr("⚠️ «{name}» eliminato, ma è ancora selezionato in {count} parser "
                             "({names}): quei segnali verranno scartati (MAPPING_MISSING) finché "
                             "non togli il profilo da quei parser.").format(
                    name=name, count=len(affected), names=', '.join(affected)),
                text_color="#ffa726")


class MarketMappingPanel(ctk.CTkFrame):
    """Pannello del Dizionario MERCATI (area "🎯 Mercati" del Mapping) — incassabile come
    area della scheda "Mapping" della finestra "🧰 Strumenti".

    Gestisce profili (`market_mapping_store`, config ``market_mappings``) di regole che
    leggono il mercato da una **posizione precisa** del messaggio: ogni riga è ``Inizia dopo
    | Finisce prima | Testo mercato | Mercato ▾ | Selezione ▾``. I delimitatori ritagliano il
    campo (come nel Parser); se vi compare il «Testo mercato» la voce imposta Mercato/Selezione
    scelti dai menù del **Catalogo XTrader** (la Selezione dipende dal Mercato), così il valore
    nel CSV è sempre **canonico**. I profili si selezionano poi nel Parser Personalizzato.

    Tutta la logica pura sta in `market_mapping_store`/`dizionario` (testate in CI); qui
    SOLO widget + persistenza (`config_store.save_config`). Non testato in CI (display).

    `on_saved(new_cfg)`: callback opzionale dopo ogni salvataggio riuscito (la GUI
    principale aggiorna la config in memoria — pattern anti-stale)."""

    _NO_PROFILE = "(nessun profilo)"

    def __init__(self, master=None, on_saved=None):
        super().__init__(master)
        self._on_saved = on_saved
        self._current = None
        self._row_widgets = []           # [{frame, phrase, market, market_menu, selection, selection_menu}, ...]
        # Mercati FISSI del Catalogo (esclusi i dinamici con placeholder squadra), come nel
        # Parser Personalizzato: sono gli unici valori-mercato sicuri da scrivere.
        self._markets = dizionario.market_names(fixed_only=True)
        self._build_ui()
        self._reload_profiles(select_first=True)

    def refresh(self, cfg=None):
        """Ricarica profili e righe dei mercati (anti-stale). `cfg` fornita = fonte viva
        (P3-7 #76: dopo un profilo NON persistito il disco è ancora pre-profilo); `None` = disco."""
        self._reload_profiles(select_first=True, cfg=cfg)

    @staticmethod
    def _selections_for(market: str) -> list:
        """SelectionName **non dinamici** del mercato dato (per la tendina Selezione)."""
        if not market:
            return []
        return [s["SelectionName"] for s in dizionario.selections_for_market(market)
                if not s.get("dynamic") and s.get("SelectionName")]

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text=i18n.tr("🎯  Dizionario mercati"),
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self, text=i18n.tr(
                "Legge il mercato da una posizione precisa del messaggio: «Inizia dopo» / "
                "«Finisce prima» (come nel Parser) ritagliano il campo, e se vi compare il "
                "«Testo mercato» imposta Mercato/Selezione dal Catalogo. Es.: Inizia dopo "
                "«Quota», Finisce prima «Prematch», Testo «0,5 HT». Seleziona i profili nel "
                "Parser Personalizzato."),
            font=ctk.CTkFont(size=11), text_color="gray", wraplength=720,
            anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        prof = ctk.CTkFrame(self, fg_color="transparent")
        prof.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(prof, text=i18n.tr("Profilo:")).pack(side="left", padx=(6, 4))
        self._profile_var = ctk.StringVar(value=self._NO_PROFILE)
        self._profile_menu = ctk.CTkOptionMenu(
            prof, variable=self._profile_var, values=[self._NO_PROFILE], width=220,
            command=self._on_profile_change)
        self._profile_menu.pack(side="left", padx=4)
        ctk.CTkButton(prof, text=i18n.tr("🆕 Nuovo"), width=84, command=self._new_profile).pack(side="left", padx=3)
        ctk.CTkButton(prof, text=i18n.tr("✏️ Rinomina"), width=96, command=self._rename_profile).pack(side="left", padx=3)
        ctk.CTkButton(prof, text=i18n.tr("🗑 Elimina"), width=90, fg_color="#7f0000",
                      hover_color="#5a0000", command=self._delete_profile).pack(side="left", padx=3)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(4, 0))
        for text, w in _MARKET_HEADER_COLUMNS:
            ctk.CTkLabel(head, text=i18n.tr(text), width=w, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=3)

        self._rows_frame = ctk.CTkScrollableFrame(
            self, height=360, label_text=i18n.tr("Righe del profilo"))
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=6)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(actions, text=i18n.tr("➕ Aggiungi riga"), width=140,
                      command=self._add_row).pack(side="left", padx=3)
        ctk.CTkButton(actions, text=i18n.tr("💾 Salva profilo"), width=140, fg_color="#2e7d32",
                      hover_color="#1b5e20", command=self._save).pack(side="left", padx=3)

        self._status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                    text_color="gray", wraplength=720, anchor="w", justify="left")
        self._status.pack(fill="x", padx=12, pady=(0, 10))

    # ── stato/config ─────────────────────────────────────────────────────────
    def _load_cfg(self):
        try:
            return config_store.load_config(config_store.CONFIG_FILE)
        except Exception as exc:                 # noqa: BLE001 — fallback con messaggio
            self._status.configure(text=i18n.tr("❌ Config illeggibile: {exc}").format(exc=exc),
                                   text_color="#ef5350")
            return None

    def _reload_profiles(self, select=None, select_first=False, cfg=None):
        # `cfg` fornita = fonte viva (P3-7 #76), propagata anche alle righe; `None` = disco.
        if cfg is None:
            cfg = self._load_cfg()
        names = market_mapping_store.profile_names(cfg) if cfg is not None else []
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
        self._reload_rows(cfg)

    def _reload_rows(self, cfg=None):
        for child in self._rows_frame.winfo_children():
            child.destroy()
        self._row_widgets = []
        if not self._current:
            ctk.CTkLabel(self._rows_frame, text=i18n.tr("Nessun profilo. Crea un profilo con «Nuovo»."),
                         text_color="gray").pack(anchor="w", padx=6, pady=4)
            return
        if cfg is None:
            cfg = self._load_cfg()
        entries = market_mapping_store.get_entries(cfg, self._current) if cfg is not None else []
        for e in entries:
            self._append_row_widget(e.get("start_after", ""), e.get("end_before", ""),
                                    e.get("phrase", ""), e.get("market_name", ""),
                                    e.get("selection_name", ""), e.get("language", ""))
        if not entries:
            self._append_row_widget("", "", "", "", "", "")

    def _append_row_widget(self, start_after="", end_before="", phrase="",
                           market="", selection="", language=""):
        """Aggiunge una riga: Inizia dopo + Finisce prima (Entry) + Testo mercato (Entry) +
        Mercato (menu catalogo) + Selezione (menu dipendente dal Mercato) + Lingua (menu) +
        elimina."""
        row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        e_start = ctk.CTkEntry(row, width=120, placeholder_text=i18n.tr("es. Quota"))
        e_start.insert(0, start_after)
        e_start.pack(side="left", padx=3)
        e_end = ctk.CTkEntry(row, width=120, placeholder_text=i18n.tr("es. Prematch"))
        e_end.insert(0, end_before)
        e_end.pack(side="left", padx=3)
        e_phrase = ctk.CTkEntry(row, width=140, placeholder_text=i18n.tr("es. 0,5 HT"))
        e_phrase.insert(0, phrase)
        e_phrase.pack(side="left", padx=3)

        # Mercato VUOTO di default su una riga nuova: l'utente deve sceglierlo esplicitamente.
        # Un mercato preselezionato a caso rischierebbe di salvare la frase sul mercato
        # SBAGLIATO (= scommessa sbagliata); una riga senza mercato è poi scartata da
        # `set_entries` (incompleta), quindi non si crea mai una mappatura involontaria (Sourcery).
        market_var = ctk.StringVar(value=market or "")
        market_menu = ctk.CTkOptionMenu(row, variable=market_var, width=200,
                                        values=["", *self._markets])
        market_menu.pack(side="left", padx=3)

        sels = self._selections_for(market_var.get())
        selection_var = ctk.StringVar(value=selection or (sels[0] if sels else ""))
        selection_menu = ctk.CTkOptionMenu(row, variable=selection_var, width=200,
                                           values=sels or [""])
        selection_menu.pack(side="left", padx=3)
        # Una selezione salvata ma non più nel mercato (catalogo cambiato): preservala come
        # opzione così non si perde silenziosamente scegliendo il primo valore.
        if selection and selection not in (sels or []):
            selection_menu.configure(values=[*(sels or []), selection])

        # Lingua-fonte per riga (epica #3 slice 5c), speculare al Dizionario nomi (5b):
        # «(tutte le lingue)» = agnostica (dato ""), oppure IT/EN/ES. Default agnostico.
        lang_values = [_LANGUAGE_ALL, *recognition.SOURCE_LANGUAGES]
        language_var = ctk.StringVar(value=_language_to_label(language))
        language_menu = ctk.CTkOptionMenu(row, variable=language_var, width=130,
                                          values=lang_values)
        # Un valore lingua salvato ma fuori lista (dato storico/corrotto, es. "FR"): preservalo
        # come opzione così non si perde in silenzio (la validità la impone lo store al salvataggio).
        if language and _language_to_label(language) not in lang_values:
            language_menu.configure(values=[*lang_values, _language_to_label(language)])
        language_menu.pack(side="left", padx=3)

        refs = {"frame": row, "start_after": e_start, "end_before": e_end, "phrase": e_phrase,
                "market": market_var, "market_menu": market_menu, "selection": selection_var,
                "selection_menu": selection_menu, "language": language_var}
        market_menu.configure(command=lambda _v, r=refs: self._on_row_market_change(r))
        ctk.CTkButton(row, text="🗑", width=36, fg_color="#c62828", hover_color="#7f0000",
                      command=lambda r=refs: self._delete_row(r)).pack(side="left", padx=3)
        self._row_widgets.append(refs)

    def _on_row_market_change(self, refs):
        """Mercato di una riga cambiato → ripopola la sua Selezione (solo non dinamiche) e
        seleziona la prima: la Selezione deve sempre appartenere al Mercato (coerenza)."""
        sels = self._selections_for(refs["market"].get())
        refs["selection_menu"].configure(values=sels or [""])
        refs["selection"].set(sels[0] if sels else "")

    def _collect_rows(self) -> list:
        """Righe correnti dai widget come voci ``{start_after, end_before, phrase,
        market_type, market_name, selection_name, language}``. ``market_type`` derivato dal
        Catalogo (D4); ``language`` è la lingua-fonte per riga (epica #3 slice 5c, «(tutte le
        lingue)» → ``""``); la pulizia delle righe incomplete (senza delimitatori/mercato) la
        fa `market_mapping_store.set_entries`."""
        out = []
        for r in self._row_widgets:
            market = r["market"].get()
            out.append({
                "start_after": r["start_after"].get(),
                "end_before": r["end_before"].get(),
                "phrase": r["phrase"].get(),
                "market_type": dizionario.market_type_for_name(market) or "",
                "market_name": market,
                "selection_name": r["selection"].get(),
                "language": _label_to_language(r["language"].get()),
            })
        return out

    # ── azioni righe ─────────────────────────────────────────────────────────
    def _add_row(self):
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Crea prima un profilo con «Nuovo»."),
                                   text_color="#ef5350")
            return
        self._append_row_widget("", "", "", "", "")

    def _delete_row(self, refs):
        refs["frame"].destroy()
        self._row_widgets = [r for r in self._row_widgets if r is not refs]

    # ── azioni profilo (persistono subito) ───────────────────────────────────
    def _persist(self, cfg: dict, ok_msg: str, fail_msg: str, select=None) -> bool:
        saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
        if ok:
            if callable(self._on_saved):
                self._on_saved(saved)
            self._reload_profiles(select=select)
        self._status.configure(text=ok_msg if ok else fail_msg,
                               text_color="#66bb6a" if ok else "#ef5350")
        return ok

    def _save(self):
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Nessun profilo selezionato."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        rows = self._collect_rows()
        cfg = market_mapping_store.set_entries(cfg, self._current, rows)
        saved = market_mapping_store.get_entries(cfg, self._current)
        n = len(saved)
        ok_msg = i18n.tr("💾 Profilo «{name}» salvato ({n} regole valide).").format(
            name=self._current, n=n)
        # Avvisa se righe NON vuote sono state scartate perché incomplete (serve Testo
        # mercato + Mercato + Selezione): non devono sparire in silenzio.
        nonempty = sum(1 for r in rows if any(str(r.get(k, "")).strip() for k in
                       ("start_after", "end_before", "phrase", "market_name", "selection_name")))
        if nonempty - n > 0:
            ok_msg += i18n.tr("  ⚠️ {count} riga/e ignorata/e perché incomplete: servono "
                              "Testo mercato, Mercato e Selezione.").format(count=nonempty - n)
        # Hint di migrazione: le voci SENZA delimitatori restano salvate (no perdita dati) ma
        # NON verranno applicate dal bridge finché non aggiungi Inizia/Finisce (CodeRabbit).
        senza_delim = sum(1 for e in saved
                          if not e.get("start_after", "").strip(" \t")
                          and not e.get("end_before", "").strip(" \t"))
        if senza_delim > 0:
            ok_msg += i18n.tr("  ⚠️ {count} regola/e SENZA delimitatori: salvata/e ma non "
                              "applicata/e finché non compili «Inizia dopo»/«Finisce prima».").format(
                                  count=senza_delim)
        self._persist(
            cfg,
            ok_msg=ok_msg,
            fail_msg=i18n.tr("❌ Salvataggio FALLITO: «{name}» non salvato (andrebbe perso al "
                             "riavvio). Controlla permessi/spazio del file config.").format(
                name=self._current),
            select=self._current)

    def _on_profile_change(self, value):
        new = value if value != self._NO_PROFILE else None
        if new == self._current:
            return
        if self._current:                          # auto-salva il profilo che stai lasciando
            cfg = self._load_cfg()
            if cfg is None:
                # P3-26 #76: config illeggibile → l'auto-save NON può avvenire; proseguire
                # farebbe ricaricare le righe CANCELLANDO l'editing. ANNULLA lo switch
                # (stesso pattern del ramo save-fallito qui sotto): profilo corrente a
                # schermo, righe intatte, l'utente può riprovare.
                self._profile_var.set(self._current)
                self._status.configure(
                    text=i18n.tr("❌ Config illeggibile: cambio profilo annullato, modifiche "
                                 "mantenute a schermo."),
                    text_color="#ef5350")
                return
            if cfg is not None:
                cfg = market_mapping_store.set_entries(cfg, self._current, self._collect_rows())
                saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
                if not ok:
                    self._profile_var.set(self._current)
                    self._status.configure(
                        text=i18n.tr("❌ Salvataggio FALLITO: cambio profilo annullato, modifiche "
                                 "mantenute a schermo. Controlla permessi/spazio del file config."),
                        text_color="#ef5350")
                    return
                if callable(self._on_saved):
                    self._on_saved(saved)
        self._current = new
        self._profile_var.set(new or self._NO_PROFILE)
        self._reload_rows()

    def _new_profile(self):
        dialog = ctk.CTkInputDialog(text=i18n.tr("Nome del nuovo profilo mercati:"), title=i18n.tr("Nuovo profilo"))
        name = (dialog.get_input() or "").strip()
        if not name:
            self._status.configure(text=i18n.tr("⛔ Profilo non creato (nome vuoto)."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        if name in market_mapping_store.profile_names(cfg):
            self._status.configure(text=i18n.tr("ℹ️ Il profilo «{name}» esiste già.").format(name=name), text_color="gray")
            return
        if self._current:
            cfg = market_mapping_store.set_entries(cfg, self._current, self._collect_rows())
        cfg = market_mapping_store.add_profile(cfg, name)
        self._persist(cfg,
                      ok_msg=i18n.tr("🆕 Profilo «{name}» creato.").format(name=name),
                      fail_msg=i18n.tr("❌ Salvataggio FALLITO: «{name}» non creato.").format(name=name),
                      select=name)

    def _rename_profile(self):
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Nessun profilo selezionato."), text_color="#ef5350")
            return
        dialog = ctk.CTkInputDialog(text=i18n.tr("Nuovo nome per «{name}»:").format(name=self._current), title=i18n.tr("Rinomina profilo"))
        new = (dialog.get_input() or "").strip()
        if not new:
            self._status.configure(text=i18n.tr("⛔ Rinomina annullata (nome vuoto)."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        if new in market_mapping_store.profile_names(cfg):
            self._status.configure(text=i18n.tr("ℹ️ Il profilo «{new}» esiste già.").format(new=new), text_color="gray")
            return
        old = self._current
        cfg = market_mapping_store.set_entries(cfg, old, self._collect_rows())
        cfg = market_mapping_store.rename_profile(cfg, old, new)
        ok = self._persist(
            cfg,
            ok_msg=i18n.tr("✏️ Profilo rinominato «{old}» → «{new}».").format(old=old, new=new),
            fail_msg=i18n.tr("❌ Salvataggio FALLITO: rinomina non applicata."), select=new)
        if ok:
            # Aggiorna i parser salvati che selezionano il vecchio nome, così non restano a
            # chiedere un profilo inesistente (→ MARKET_MAPPING_MISSING silenzioso).
            try:
                updated, failed = custom_parser.rename_market_mapping_profile_in_files(old, new)
            except Exception as exc:             # noqa: BLE001 — il rename config resta valido
                # P3-32 #76: come per il dizionario nomi — mai successo con stato ignoto.
                self._status.configure(
                    text=i18n.tr("⚠️ Profilo rinominato «{old}» → «{new}», ma la verifica dei "
                                 "parser salvati è FALLITA ({exc}): controlla a mano quali usano "
                                 "ancora «{old}» o quei segnali verranno scartati "
                                 "(MARKET_MAPPING_MISSING).").format(old=old, new=new, exc=exc),
                    text_color="#ffa726")
                return
            if failed:
                self._status.configure(
                    text=i18n.tr("⚠️ Profilo rinominato «{old}» → «{new}», ma {count} parser NON "
                                 "aggiornati ({names}): correggili a mano o quei segnali verranno "
                                 "scartati (MARKET_MAPPING_MISSING).").format(
                        old=old, new=new, count=len(failed), names=', '.join(failed)),
                    text_color="#ffa726")
            elif updated:
                self._status.configure(
                    text=i18n.tr("✏️ Profilo rinominato «{old}» → «{new}» · {count} parser "
                                 "aggiornati.").format(old=old, new=new, count=len(updated)),
                    text_color="#66bb6a")

    def _delete_profile(self):
        if not self._current:
            self._status.configure(text=i18n.tr("⛔ Nessun profilo selezionato."), text_color="#ef5350")
            return
        cfg = self._load_cfg()
        if cfg is None:
            return
        name = self._current
        # P3-27 #76: come per il dizionario nomi — conferma fail-closed prima di toccare
        # la config.
        if not gui_utils.ask_confirm(
                i18n.tr("Elimina profilo"),
                i18n.tr("Eliminare il profilo «{name}» del dizionario mercati?\n"
                        "L'azione non è annullabile.").format(name=name)):
            self._status.configure(
                text=i18n.tr("Eliminazione annullata."), text_color="gray")
            return
        try:
            affected = custom_parser.parsers_using_market_mapping_profile(name)
        except Exception:                        # noqa: BLE001 — l'avviso è best-effort
            affected = []
        cfg = market_mapping_store.delete_profile(cfg, name)
        # NON azzerare `_current` prima del salvataggio: se `_persist` fallisce non ricarica,
        # e la UI mostrerebbe "nessun profilo" mentre il profilo è ancora su disco (desync,
        # Sourcery). Su successo è `_reload_profiles` a portarlo a None (il profilo non c'è
        # più); su fallimento resta selezionato il profilo tuttora esistente (coerente).
        ok = self._persist(
            cfg,
            ok_msg=i18n.tr("🗑 Profilo «{name}» eliminato.").format(name=name),
            fail_msg=i18n.tr("❌ Salvataggio FALLITO: «{name}» non eliminato.").format(name=name))
        if ok and affected:
            self._status.configure(
                text=i18n.tr("⚠️ «{name}» eliminato, ma è ancora selezionato in {count} parser "
                             "({names}): quei segnali verranno scartati (MARKET_MAPPING_MISSING) "
                             "finché non togli il profilo da quei parser.").format(
                    name=name, count=len(affected), names=', '.join(affected)),
                text_color="#ffa726")


class MappingPanel(ctk.CTkFrame):
    """Scheda "Mapping" della finestra "🧰 Strumenti": raccoglie i dizionari di
    traduzione provider → XTrader in DUE aree (sotto-schede):

    - **⚽ Calcio**: nomi squadre/campionati (`NameMappingPanel`);
    - **🎯 Mercati**: traduzione frase-mercato → mercato/selezione XTrader
      (`MarketMappingPanel`, config ``market_mappings``);
    - **🌳 Mapping guidato**: albero Sport → Competizione → Squadre dai dati Betfair, con
      alias-canale per squadra (`GuidedMappingPanel`), che scrive negli stessi profili `name_mappings`.

    `on_saved(new_cfg)`: inoltrata a tutte le aree (i dizionari persistono su config).
    `competitions_provider`/`teams_provider`: letture Betfair (fail-fast su sync) per l'albero guidato."""

    def __init__(self, master=None, on_saved=None, known_teams_provider=None,
                 competitions_provider=None, teams_provider=None):
        super().__init__(master)
        self._tabs = ctk.CTkTabview(self)
        self._tabs.pack(fill="both", expand=True, padx=4, pady=4)

        calcio = self._tabs.add("⚽ Calcio")
        self._calcio = NameMappingPanel(calcio, on_saved=on_saved,
                                        known_teams_provider=known_teams_provider)
        self._calcio.pack(fill="both", expand=True)

        mercati = self._tabs.add("🎯 Mercati")
        self._mercati = MarketMappingPanel(mercati, on_saved=on_saved)
        self._mercati.pack(fill="both", expand=True)

        # Import locale per non appesantire l'avvio di chi non apre il Mapping.
        from .guided_mapping_gui import GuidedMappingPanel
        guidato = self._tabs.add("🌳 Mapping guidato")
        self._guidato = GuidedMappingPanel(
            guidato, competitions_provider=competitions_provider,
            teams_provider=teams_provider, on_saved=on_saved)
        self._guidato.pack(fill="both", expand=True)

    def refresh(self, cfg=None):
        """Ricarica tutte le aree (nomi, mercati, mapping guidato) — anti-stale: un profilo
        applicato altrove non deve restare stantio qui. `cfg` fornita = config VIVA inoltrata
        a tutte le aree (P3-7 #76: dopo un profilo applicato ma NON persistito il disco è
        ancora pre-profilo); `None` = ricarica dal disco (comportamento storico).

        Deepcopy PER AREA (review Fable/GPT #92): stesso invariante del chiamante in
        `app.py` — le tre sotto-aree non devono condividere dict annidati tra loro (oggi
        sono read-only, ma una futura mutazione locale non deve propagarsi alle sorelle)."""
        self._calcio.refresh(copy.deepcopy(cfg) if cfg is not None else None)
        self._mercati.refresh(copy.deepcopy(cfg) if cfg is not None else None)
        self._guidato.refresh(copy.deepcopy(cfg) if cfg is not None else None)


class NameMappingWindow(ctk.CTkToplevel):
    """Finestra standalone che ospita `NameMappingPanel` a tutta finestra.

    Mantenuta per compatibilità; la stessa `NameMappingPanel` vive anche come area
    "⚽ Calcio" della scheda "Mapping" (`MappingPanel`) in "🧰 Strumenti"."""

    def __init__(self, master=None, on_saved=None):
        super().__init__(master)
        self.title(i18n.tr("Dizionario nomi squadra"))
        # Larghezza per le colonne attuali (PR-P10 + #178 §2): la riga è
        # Country(180)+Betfair(240)+«Come lo scrive il canale»(240)+Sport(150)+Tipo(150)+elimina(36) ≈ 996 px
        # più il padding fra i widget; a 940 px Tipo/elimina venivano tagliati (no scroll
        # orizzontale) — Codex. Allargata di conseguenza, con minimo che non taglia.
        gui_utils.fit_to_screen(self, 1120, 620, 1040, 460)
        NameMappingPanel(self, on_saved=on_saved).pack(fill="both", expand=True)


class MarketMappingWindow(ctk.CTkToplevel):
    """Finestra standalone che ospita `MarketMappingPanel` a tutta finestra.

    Usata dal pulsante «🎯 Dizionario mercati» del Parser Personalizzato (parità col
    «🗺️ Dizionario nomi»); la stessa `MarketMappingPanel` vive anche come area "🎯 Mercati"
    della scheda "Mapping" (`MappingPanel`) in "🧰 Strumenti"."""

    def __init__(self, master=None, on_saved=None):
        super().__init__(master)
        self.title(i18n.tr("Dizionario mercati"))
        # Largo abbastanza per le 5 colonne (Inizia/Finisce/Testo/Mercato/Selezione) + 🗑,
        # così a dimensione di default nulla resta tagliato (Codex).
        gui_utils.fit_to_screen(self, 980, 640, 900, 460)
        MarketMappingPanel(self, on_saved=on_saved).pack(fill="both", expand=True)
