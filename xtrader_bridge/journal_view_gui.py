"""Scheda «📒 Diario» — SOLA LETTURA (#236, riusa `journal_view`).

Vista GUI del diario eventi locale (`event_journal.jsonl`) dentro l'hub «🧰 Strumenti»:
mostra gli ultimi N eventi (`ts` leggibile, tipo, dati **già redatti**), con filtro per
tipo evento, «🔄 Aggiorna» e «📂 Apri cartella». Tutta la logica di lettura/filtro/
rendering vive in `journal_view` (pura, testata headless — `filter_events`/`table_rows`);
questo modulo è solo widget/wiring e NON è testato in CI (serve un display): la logica
esercitabile è testata a parte, il resto è verifica manuale (smoke, vedi test).

Invarianti (come la CLI #236):

- **Read-only**: riusa `event_journal.read_events`; non scrive né modifica MAI il ledger;
  tollerante alle righe malformate (già saltate da `read_events`).
- **Niente segreti**: gli eventi sono già redatti sul file (token + `chat_id` hashato); la
  vista li mostra **così come sono**, non de-redige nulla.
"""

import os
import subprocess
import sys

import customtkinter as ctk

from . import event_journal, journal_view

# Voce «tutti i tipi» del filtro (= nessun filtro per tipo).
_ALL_TYPES = "(tutti i tipi)"
# Scelte del filtro «Ultimi N»: quantità sensate per una lettura a colpo d'occhio; «Tutti»
# = nessun taglio (last=None).
_LAST_CHOICES = ["50", "100", "200", "500", "Tutti"]
_COL_TS_WIDTH = 150
_COL_TYPE_WIDTH = 190


class JournalPanel(ctk.CTkFrame):
    """Pannello di sola consultazione del diario eventi locale.

    `path` è il percorso del ledger (default: quello di runtime via `journal_view`)."""

    def __init__(self, master=None, path=None):
        super().__init__(master)
        self._path = path or journal_view.default_path()
        self._type = ctk.StringVar(value=_ALL_TYPES)
        self._last = ctk.StringVar(value="100")
        self._build_ui()
        self._refresh()

    # ── costruzione UI ────────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text="📒  Diario eventi (locale, sola lettura)",
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))

        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(bar, text="Tipo").pack(side="left", padx=(8, 4))
        ctk.CTkOptionMenu(bar, variable=self._type, width=200,
                          values=[_ALL_TYPES, *sorted(event_journal.EVENT_TYPES)],
                          command=lambda _v: self._refresh()).pack(side="left", padx=4)
        ctk.CTkLabel(bar, text="Ultimi").pack(side="left", padx=(12, 4))
        ctk.CTkOptionMenu(bar, variable=self._last, width=90, values=_LAST_CHOICES,
                          command=lambda _v: self._refresh()).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="🔄 Aggiorna", width=110,
                      command=self._refresh).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="📂 Apri cartella", width=140,
                      command=self._open_folder).pack(side="left", padx=4)

        self._counts = ctk.CTkLabel(self, text="", anchor="w")
        self._counts.pack(fill="x", padx=14, pady=(0, 4))

        self._header = ctk.CTkFrame(self, fg_color="transparent")
        self._header.pack(fill="x", padx=12)
        self._rows_frame = ctk.CTkScrollableFrame(self, height=400,
                                                  label_text="Eventi del diario")
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=6)

    # ── selezione filtri ────────────────────────────────────────────────────────
    def _selected_types(self):
        """Lista tipi per `filter_events` (o `None` = tutti)."""
        t = self._type.get()
        return None if t == _ALL_TYPES else [t]

    def _selected_last(self):
        """`last` per `filter_events`: intero dalla scelta, oppure `None` per «Tutti»/valore
        non numerico (nessun taglio)."""
        try:
            return int(self._last.get())
        except (TypeError, ValueError):
            return None

    def _clear(self, frame):
        for w in frame.winfo_children():
            w.destroy()

    # ── refresh ──────────────────────────────────────────────────────────────────
    def _refresh(self):
        """Ricarica la tabella dal ledger (sola lettura). Best-effort: un errore di lettura
        mostra un avviso invece di far crashare la finestra Strumenti. Riusa la logica pura
        di `journal_view` (filtro + celle già redatte)."""
        self._clear(self._header)
        self._clear(self._rows_frame)
        try:
            all_events = event_journal.read_events(self._path)
            events = journal_view.filter_events(
                all_events, types=self._selected_types(), last=self._selected_last())
        except Exception as exc:   # noqa: BLE001 — lettura best-effort, niente crash GUI
            self._counts.configure(text=f"⚠️ Errore lettura diario: {type(exc).__name__}")
            return
        self._counts.configure(
            text=f"Diario: {len(all_events)} eventi totali (mostrati {len(events)}).")
        for title, width in (("Quando", _COL_TS_WIDTH), ("Tipo", _COL_TYPE_WIDTH)):
            ctk.CTkLabel(self._header, text=title, width=width, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=3)
        ctk.CTkLabel(self._header, text="Dati (redatti)", anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=3)
        for ts, typ, data_str in journal_view.table_rows(events):
            rf = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
            rf.pack(fill="x", pady=1)
            ctk.CTkLabel(rf, text=ts, width=_COL_TS_WIDTH, anchor="w").pack(side="left", padx=3)
            ctk.CTkLabel(rf, text=typ, width=_COL_TYPE_WIDTH, anchor="w").pack(side="left", padx=3)
            ctk.CTkLabel(rf, text=data_str, anchor="w").pack(
                side="left", padx=3, fill="x", expand=True)

    def _open_folder(self):
        """Apre nel file manager la cartella che contiene il ledger (stesso pattern di
        «📂 Apri cartella log»). Best-effort: nessun crash GUI se l'apertura fallisce."""
        folder = os.path.dirname(self._path) or "."
        try:
            os.makedirs(folder, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(folder)            # noqa: S606 — apertura cartella utente
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:                       # noqa: BLE001 — best-effort, no crash GUI
            pass
