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

from . import recognition
from .parser_builder import ParserBuilder


class CustomParserWindow(ctk.CTkToplevel):
    """Finestra del costruttore. `on_message` opzionale non usato: l'anteprima
    è interna (test-live)."""

    def __init__(self, master=None, builder: ParserBuilder = None, provider: str = ""):
        super().__init__(master)
        self.title("Parser Personalizzato")
        self.geometry("1024x720")
        self.builder = builder or ParserBuilder()
        self._provider = provider
        self._rows = []  # widget refs per regola

        self._targets = self.builder.target_options()
        self._transforms = self.builder.transform_options()
        self._value_maps = self.builder.value_map_options(include_dizionario=True)
        self._modes = self.builder.mode_options()

        self._build_ui()
        self._reload_rows_from_builder()

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

        # test-live
        test = ctk.CTkFrame(self)
        test.pack(fill="both", expand=True, padx=10, pady=6)
        ctk.CTkLabel(test, text="Messaggio di prova:").pack(anchor="w", padx=6)
        self._msg_box = ctk.CTkTextbox(test, height=120)
        self._msg_box.pack(fill="both", expand=True, padx=6, pady=4)
        self._result = ctk.CTkLabel(test, text="", anchor="w", justify="left")
        self._result.pack(fill="x", padx=6, pady=4)

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
        self._result.configure(text=f"💾 Salvato in {path}")

    def _test(self):
        self._sync_to_builder()
        message = self._msg_box.get("1.0", "end").rstrip("\n")
        res = self.builder.test_message(message, provider=self._provider, mode=self._mode_var.get())
        if res.placeable:
            riga = ", ".join(f"{k}={v}" for k, v in res.row.items() if v != "")
            self._result.configure(text=f"✅ Pronto · {riga}")
        else:
            extra = f" · mancanti: {', '.join(res.missing_required)}" if res.missing_required else ""
            self._result.configure(text=f"⛔ Non pronto ({res.status}){extra}")
