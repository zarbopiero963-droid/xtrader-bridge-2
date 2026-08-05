"""Finestra di gestione dell'anagrafica Provider.

Permette di **vedere**, **aggiungere** e **rimuovere** i nomi Provider salvati
(`config.json` → chiave `providers`), usati nel Parser Personalizzato (colonna
`Provider`, menu a tendina). Finora l'anagrafica si poteva solo *aggiungere* dal
builder ("➕ Provider"); qui c'è anche la **rimozione** e una vista d'insieme,
senza dover aprire il builder.

Tutta la logica sta in `provider_store` (funzioni pure, testate in CI): qui ci
sono SOLO i widget e la persistenza (`config_store.save_config`). Come per la
finestra Sorgenti, ogni azione persiste subito e chiama `on_saved(new_cfg)`, così
la GUI principale aggiorna la config in memoria e un successivo "Salva Config" /
"Avvia" non riscrive il file perdendo i provider (stesso pattern anti-stale).

Testi UI localizzati via `i18n.tr` (#343 slice 4c): l'italiano è il riferimento,
la lingua attiva è quella scelta all'avvio; i messaggi con variabili passano dal
template tradotto (`.format(...)`), così la chiave di catalogo resta stabile.

NB: questo modulo non è testato in CI (richiede un display). La logica che usa è
coperta da `tests/unit/test_provider_store.py`. Verifica manuale su Windows.
"""

import customtkinter as ctk

from . import config_store, custom_parser, gui_utils, i18n, provider_store, ui_cards, ui_theme


class ProviderPanel(ctk.CTkFrame):
    """Pannello dell'anagrafica Provider — incassabile sia in una finestra standalone
    (`ProviderWindow`) sia come scheda della finestra "🧰 Strumenti".

    `on_saved(new_cfg)`: callback opzionale chiamata dopo ogni salvataggio
    riuscito, così la GUI principale aggiorna la propria config in memoria."""

    def __init__(self, master=None, on_saved=None, is_running=None):
        super().__init__(master)
        self._on_saved = on_saved
        # #176: sonda «bridge ATTIVO» per l'avviso post-salvataggio (avvisa, non blocca).
        self._is_running = is_running
        self._build_ui()
        self._reload()

    def refresh(self, cfg=None):
        """Ricarica la lista dei provider.

        Usato quando la config cambia da FUORI questo pannello (es. l'applicazione di
        un profilo nella stessa finestra "🧰 Strumenti" può sostituire la lista
        `providers`): senza, il pannello mostrerebbe nomi stantii (Codex).

        `cfg`: config VIVA da usare al posto del disco (P3-7 #76) — dopo un profilo
        applicato ma NON persistito il disco ha ancora lo stato pre-profilo e rileggerlo
        rimetterebbe in anteprima i provider vecchi. `None` = ricarica dal disco
        (comportamento storico per gli altri chiamanti)."""
        self._reload(cfg)

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text=i18n.tr("📇  Anagrafica Provider"),
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self, text=i18n.tr("Nomi Provider riutilizzabili nel Parser Personalizzato "
                               "(colonna Provider). Valgono per tutti i parser."),
            font=ctk.CTkFont(size=11), text_color="gray", wraplength=480,
            anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        # Riga di inserimento: nome + Aggiungi.
        add = ctk.CTkFrame(self, fg_color="transparent")
        add.pack(fill="x", padx=12, pady=(0, 6))
        self._name_entry = ctk.CTkEntry(add, placeholder_text=i18n.tr("Nome del nuovo Provider"))
        self._name_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._name_entry.bind("<Return>", lambda _e: self._add())
        ctk.CTkButton(add, text=i18n.tr("➕  Aggiungi"), width=120, fg_color=ui_theme.SUCCESS,
                      hover_color=ui_theme.SUCCESS_HOV, command=self._add).pack(side="left")

        # #182 restyle: l'elenco vive in una card (bordo + raggio dei token), come lo sketch.
        self._rows_frame = ctk.CTkScrollableFrame(
            self, height=360, label_text=i18n.tr("Provider salvati"),
            **ui_cards.card_style())
        ui_cards.tune_scrolling(self._rows_frame)   # scroll fluido (regola 2: ogni scrollable)
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=6)

        self._status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                    text_color="gray", wraplength=480, anchor="w", justify="left")
        self._status.pack(fill="x", padx=12, pady=(0, 10))

    # ── stato corrente ─────────────────────────────────────────────────────
    def _load_names(self, cfg=None) -> list:
        """Nomi provider salvati (best-effort: config illeggibile → lista vuota).
        `cfg` fornita = fonte viva (P3-7 #76); `None` = disco."""
        if cfg is None:
            try:
                cfg = config_store.load_config(config_store.CONFIG_FILE)
            except Exception:                   # noqa: BLE001 — fallback sicuro
                return []
        return provider_store.provider_names(cfg)

    def _provider_usage(self):
        """`{provider: [parser che lo usano]}` in sola LETTURA, oppure **`None`** se i parser
        non sono leggibili (#182 PR E).

        ⚠️ La distinzione fra `{}` e `None` è di **sicurezza**, non di stile (rilievo GPT-5.5
        sulla PR #230). Con la cartella dei parser illeggibile, restituire `{}` avrebbe fatto
        scrivere **«— non usato» su OGNI riga**: cioè la rassicurazione «puoi rimuoverlo» proprio
        quando il controllo NON è stato fatto. Un marcatore mancante è accettabile; un marcatore
        che afferma il falso accanto a un pulsante distruttivo no.

        `{}` = ho guardato, nessun parser fissa quel provider. `None` = non ho potuto guardare."""
        try:
            return custom_parser.provider_usage() or {}
        except Exception:            # noqa: BLE001 — parser illeggibili: stato IGNOTO, mai un falso «non usato»
            return None

    @staticmethod
    def _quanti_usano(uso: dict, name: str) -> int:
        """Quanti parser fissano `name`, confrontando come `provider_store` (senza spazi ai
        bordi, case-insensitive): un parser che scrive «Bet365 » dipende dalla voce «Bet365»,
        e dirlo «non usato» sarebbe un falso rassicurante proprio prima di una rimozione."""
        n = str(name or "").strip().casefold()
        return sum(len(p) for salvato, p in (uso or {}).items()
                   if str(salvato).strip().casefold() == n)

    def _reload(self, cfg=None):
        """Ridisegna la lista dei provider (da `cfg` viva se fornita, altrimenti da disco).

        Ogni riga porta un marcatore d'uso (#182 PR E): «🧩 N parser» oppure «— non usato».
        A differenza dei dizionari, qui lo zero si SCRIVE: un provider non usato è la
        condizione che rende la rimozione sicura, ed è l'informazione che serve proprio
        mentre si guarda il pulsante «🗑 Rimuovi» accanto."""
        for child in self._rows_frame.winfo_children():
            child.destroy()
        names = self._load_names(cfg)
        if not names:
            ctk.CTkLabel(self._rows_frame, text=i18n.tr("Nessun provider salvato."),
                         text_color="gray").pack(anchor="w", padx=6, pady=4)
            return
        uso = self._provider_usage()
        for name in names:
            row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=name, anchor="w").pack(side="left", fill="x",
                                                          expand=True, padx=6)
            # ORDINE DI PACK — il pulsante PRIMA del marcatore. Con `side="right"` Tk mette il
            # primo impacchettato all'estrema destra, quindi impacchettando prima il marcatore
            # sarebbe finito DOPO il pulsante: «nome … [🗑 Rimuovi] [🧩 2 parser]» invece di
            # «nome … [🧩 2 parser] [🗑 Rimuovi]» (rilevato da GPT-5.5 e Fable sulla PR #230).
            ctk.CTkButton(row, text=i18n.tr("🗑  Rimuovi"), width=110, fg_color=ui_theme.DANGER,
                          hover_color=ui_theme.DANGER_HOV,
                          command=lambda n=name: self._remove(n)).pack(side="right", padx=3)
            # #182 restyle: il marcatore diventa badge-pillola (ui_cards). Testi INVARIATI.
            if uso is None:
                testo, kind = i18n.tr("⚠ uso ignoto"), "danger"
            else:
                quanti = self._quanti_usano(uso, name)
                testo = (i18n.tr("🧩 {n} parser").format(n=quanti) if quanti
                         else i18n.tr("— non usato"))
                kind = "ok" if quanti else "warn"
            ui_cards.badge(ctk, row, testo, kind=kind, side="right", padx=6)

    # ── azioni (persistono subito, come il builder) ─────────────────────────
    def _persist(self, cfg: dict, ok_msg: str, fail_msg: str):
        """Salva `cfg`, sincronizza la GUI principale (on_saved) e ridisegna.

        Mostra l'esito REALE della scrittura su disco: un salvataggio fallito non
        deve apparire come riuscito (i provider andrebbero persi al riavvio)."""
        saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
        if ok and callable(self._on_saved):
            self._on_saved(saved)
        self._reload()
        self._status.configure(
            text=gui_utils.with_running_notice(ok_msg if ok else fail_msg, self._is_running),
            text_color=ui_theme.STATUS_OK if ok else ui_theme.STATUS_ERR)

    def _add(self):
        """Aggiunge il nome digitato all'anagrafica (dedup case-insensitive)."""
        name = (self._name_entry.get() or "").strip()
        if not name:
            self._status.configure(text=i18n.tr("⛔ Nome vuoto: provider non aggiunto."),
                                   text_color=ui_theme.STATUS_ERR)
            return
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception as exc:                 # noqa: BLE001 — config illeggibile -> messaggio nel pannello e nessuna aggiunta, mai crash della finestra
            self._status.configure(
                text=i18n.tr("❌ Config illeggibile: {exc}").format(exc=exc),
                text_color=ui_theme.STATUS_ERR)
            return
        if name.casefold() in {n.casefold() for n in provider_store.provider_names(cfg)}:
            self._status.configure(
                text=i18n.tr("ℹ️ «{name}» è già nell'anagrafica.").format(name=name),
                text_color="gray")
            return
        cfg = provider_store.add_provider(cfg, name)
        self._name_entry.delete(0, "end")
        self._persist(
            cfg,
            ok_msg=i18n.tr("➕ Provider «{name}» salvato.").format(name=name),
            fail_msg=i18n.tr(
                "❌ Salvataggio FALLITO: «{name}» non salvato (andrebbe perso al riavvio). "
                "Controlla permessi/spazio del file config.").format(name=name))

    def _remove(self, name: str):
        """Rimuove `name` dall'anagrafica (confronto case-insensitive)."""
        # AC-M12 audit #114: rimozione DISTRUTTIVA di un provider — mai a un solo click,
        # come nomi noti/profili/mapping (pattern P3-27). Conferma fail-closed: dialog
        # rotto/headless → NON confermato, la rimozione non parte.
        # #182 PR E: dire QUANTI parser dipendono da questo provider, non solo che è permanente.
        # Il pannello Mapping lo fa già prima di eliminare un profilo in uso
        # (`parsers_using_mapping_profile`); qui mancava, ed è la stessa domanda — «cosa rompo?» —
        # posta nel momento in cui conta. Rimuovere il provider NON tocca i parser: continuano a
        # scrivere quel valore nel CSV, ma la voce sparisce dalla tendina e alla prossima modifica
        # di quel parser non è più ri-selezionabile. Best-effort: parser illeggibili → nessun
        # elenco, la conferma resta quella di prima invece di bloccare la rimozione.
        verificato = True
        try:
            usato_da = custom_parser.parsers_using_provider(name)
        except Exception:                        # noqa: BLE001 — anagrafica gestibile anche senza parser leggibili
            usato_da, verificato = [], False
        domanda = i18n.tr("Rimuovere il provider «{name}»?\nÈ permanente: i messaggi da quella "
                          "sorgente non verranno più riconosciuti finché non lo reinserisci."
                          ).format(name=name)
        if not verificato:
            # Silenzio = l'utente deduce «non lo usa nessuno». Dirlo esplicitamente: il controllo
            # non è stato fatto, la decisione resta sua ma informata (rilievo GPT-5.5 #230).
            domanda += "\n\n" + i18n.tr(
                "⚠️ Non è stato possibile leggere i parser salvati: non so dirti se qualcuno usa "
                "questo provider.")
        if usato_da:
            domanda += "\n\n" + i18n.tr(
                "⚠️ Usato da {count} parser: {elenco}.\nRestano funzionanti — scrivono comunque "
                "questo valore nel CSV — ma il nome non sarà più selezionabile quando li modifichi."
            ).format(count=len(usato_da), elenco=", ".join(usato_da))
        if not gui_utils.ask_confirm(i18n.tr("Rimuovi provider"), domanda):
            self._status.configure(text=i18n.tr("Rimozione annullata."),
                                   text_color=ui_theme.STATUS_WARN)
            return
        try:
            cfg = config_store.load_config(config_store.CONFIG_FILE)
        except Exception as exc:                 # noqa: BLE001 — config illeggibile -> messaggio nel pannello e nessuna rimozione, mai crash della finestra
            self._status.configure(
                text=i18n.tr("❌ Config illeggibile: {exc}").format(exc=exc),
                text_color=ui_theme.STATUS_ERR)
            return
        cfg = provider_store.remove_provider(cfg, name)
        self._persist(
            cfg,
            ok_msg=i18n.tr("🗑 Provider «{name}» rimosso.").format(name=name),
            fail_msg=i18n.tr(
                "❌ Salvataggio FALLITO: «{name}» non rimosso (ricomparirebbe al riavvio). "
                "Controlla permessi/spazio del file config.").format(name=name))


class ProviderWindow(ctk.CTkToplevel):
    """Finestra standalone che ospita `ProviderPanel` a tutta finestra.

    Mantenuta per compatibilità (apertura come finestra separata); la stessa
    `ProviderPanel` vive anche come scheda della finestra "🧰 Strumenti"."""

    def __init__(self, master=None, on_saved=None):
        super().__init__(master)
        self.title(i18n.tr("Anagrafica Provider"))
        gui_utils.fit_to_screen(self, 520, 520, 460, 420)
        ProviderPanel(self, on_saved=on_saved).pack(fill="both", expand=True)
