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

from . import parser_diagnostics, recognition
from .parser_builder import ParserBuilder


class CustomParserWindow(ctk.CTkToplevel):
    """Finestra del costruttore. `on_message` opzionale non usato: l'anteprima
    è interna (test-live)."""

    # Etichetta-sentinella quando non c'è nessun parser salvato.
    _NONE_SAVED = "(nessuno)"

    def __init__(self, master=None, builder: ParserBuilder = None, provider: str = ""):
        super().__init__(master)
        self.title("Parser Personalizzato")
        self.geometry("1024x720")
        self.builder = builder or ParserBuilder()
        self._provider = provider
        self._rows = []  # widget refs per regola
        self._saved_map = {}  # etichetta menu → path file parser

        self._targets = self.builder.target_options()
        self._transforms = self.builder.transform_options()
        self._value_maps = self.builder.value_map_options(include_dizionario=True)
        self._modes = self.builder.mode_options()

        self._build_ui()
        self._reload_rows_from_builder()
        self._refresh_saved()

    # ── costruzione UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(top, text="Nome parser:").pack(side="left", padx=6)
        self._name_var = ctk.StringVar(value=self.builder.name)
        ctk.CTkEntry(top, textvariable=self._name_var, width=240).pack(side="left", padx=6)
        ctk.CTkLabel(top, text="Modalità:").pack(side="left", padx=6)
        # Default = modalità di default del riconoscimento (NAME_ONLY), non il
        # primo elemento di VALID_MODES (che è ID_ONLY).
        default_mode = recognition.DEFAULT_MODE if recognition.DEFAULT_MODE in self._modes \
            else (self._modes[0] if self._modes else recognition.DEFAULT_MODE)
        self._mode_var = ctk.StringVar(value=default_mode)
        ctk.CTkOptionMenu(top, variable=self._mode_var, values=self._modes, width=140).pack(side="left", padx=6)

        # gestione parser salvati: lista + nuovo / carica / duplica / elimina
        manage = ctk.CTkFrame(self)
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
        cat = ctk.CTkFrame(self)
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

        # intestazione colonne
        head = ctk.CTkFrame(self)
        head.pack(fill="x", padx=10)
        for txt, w in (("Colonna", 150), ("Inizia dopo", 150), ("Finisce prima", 150),
                       ("Valore fisso", 130), ("Trasformazione", 150), ("Value-map", 150),
                       ("Obblig.", 60), ("", 70)):
            ctk.CTkLabel(head, text=txt, width=w, anchor="w").pack(side="left", padx=2)

        self._rows_frame = ctk.CTkScrollableFrame(self, height=320)
        self._rows_frame.pack(fill="both", expand=True, padx=10, pady=6)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(actions, text="➕ Aggiungi regola", command=self._add_row).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="💾 Salva", command=self._save).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="🧪 Prova messaggio", command=self._test).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="📋 Copia diagnostica", command=self._copy_diag).pack(side="left", padx=4)

        # test-live
        test = ctk.CTkFrame(self)
        test.pack(fill="both", expand=True, padx=10, pady=6)
        ctk.CTkLabel(test, text="Messaggio di prova:").pack(anchor="w", padx=6)
        self._msg_box = ctk.CTkTextbox(test, height=120)
        self._msg_box.pack(fill="both", expand=True, padx=6, pady=4)
        self._result = ctk.CTkLabel(test, text="", anchor="w", justify="left")
        self._result.pack(fill="x", padx=6, pady=4)
        # Diagnostica per-campo (CP-08b): perché "Non pronto", colonna per colonna.
        ctk.CTkLabel(test, text="Diagnostica:").pack(anchor="w", padx=6)
        self._diag_box = ctk.CTkTextbox(test, height=160)
        self._diag_box.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self._last_report = ""   # testo per "Copia diagnostica"

    # ── righe regola ──────────────────────────────────────────────────────
    def _add_row(self, rule=None):
        row = ctk.CTkFrame(self._rows_frame)
        row.pack(fill="x", pady=2)
        refs = {}
        refs["target"] = ctk.StringVar(value=rule.target if rule else self._targets[0])
        ctk.CTkOptionMenu(row, variable=refs["target"], values=self._targets, width=150).pack(side="left", padx=2)
        refs["start_after"] = ctk.CTkEntry(row, width=150)
        refs["end_before"] = ctk.CTkEntry(row, width=150)
        refs["fixed_value"] = ctk.CTkEntry(row, width=130)
        if rule:
            refs["start_after"].insert(0, rule.start_after)
            refs["end_before"].insert(0, rule.end_before)
            refs["fixed_value"].insert(0, rule.fixed_value)
        refs["start_after"].pack(side="left", padx=2)
        refs["end_before"].pack(side="left", padx=2)
        refs["fixed_value"].pack(side="left", padx=2)
        refs["transform"] = ctk.StringVar(value=rule.transform if rule else "")
        ctk.CTkOptionMenu(row, variable=refs["transform"], values=self._transforms, width=150).pack(side="left", padx=2)
        refs["value_map"] = ctk.StringVar(value=rule.value_map if rule else "")
        ctk.CTkOptionMenu(row, variable=refs["value_map"], values=self._value_maps, width=150).pack(side="left", padx=2)
        refs["required"] = ctk.BooleanVar(value=bool(rule.required) if rule else False)
        ctk.CTkCheckBox(row, text="", variable=refs["required"], width=40).pack(side="left", padx=2)
        ctk.CTkButton(row, text="✕", width=60, fg_color="#7f0000",
                      command=lambda: self._remove_row(row)).pack(side="left", padx=2)
        refs["frame"] = row
        self._rows.append(refs)

    def _remove_row(self, row):
        self._rows = [r for r in self._rows if r["frame"] is not row]
        row.destroy()

    def _reload_rows_from_builder(self):
        for r in list(self._rows):
            r["frame"].destroy()
        self._rows = []
        for rule in self.builder.rules:
            self._add_row(rule)

    def _sync_to_builder(self):
        """Riporta i valori dei widget nel controller."""
        self.builder.name = self._name_var.get().strip()
        self.builder.rules = []
        for refs in self._rows:
            self.builder.add_rule(
                target=refs["target"].get(),
                start_after=refs["start_after"].get(),
                end_before=refs["end_before"].get(),
                fixed_value=refs["fixed_value"].get(),
                transform=refs["transform"].get(),
                value_map=refs["value_map"].get(),
                required=bool(refs["required"].get()),
            )

    # ── azioni ────────────────────────────────────────────────────────────
    def _save(self):
        self._sync_to_builder()
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
        self._sync_to_builder()
        message = self._msg_box.get("1.0", "end").rstrip("\n")
        mode = self._mode_var.get()
        # Verdetto sintetico (riga risultante) + diagnostica per-campo (CP-08b).
        res = self.builder.test_message(message, provider=self._provider, mode=mode)
        if res.placeable:
            riga = ", ".join(f"{k}={v}" for k, v in res.row.items() if v != "")
            self._result.configure(text=f"✅ Pronto · {riga}")
        else:
            extra = f" · mancanti: {', '.join(res.missing_required)}" if res.missing_required else ""
            self._result.configure(text=f"⛔ Non pronto ({res.status}){extra}")
        diag = parser_diagnostics.diagnose(
            self.builder.to_def(), message, provider=self._provider, mode=mode)
        self._last_report = parser_diagnostics.format_report(diag)
        self._diag_box.delete("1.0", "end")
        self._diag_box.insert("1.0", self._last_report)

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
