"""Pannello «Dizionario Betfair» — SOLA LETTURA (issue #86 PR-P11).

Vista di consultazione del dizionario Betfair locale: l'utente sceglie un livello
(Sport/Competizioni/Eventi/Mercati/Selezioni) e un filtro sport, e vede le righe
sincronizzate sul PC. **Non** modifica nulla (nessuna Entry, nessun pulsante di
scrittura), non fa rete e non muta il DB: tutta la logica sta in
`DictionaryViewerController` (testata in CI). Questo modulo è solo widget/wiring e NON
è testato in CI (richiede un display): verifica manuale (vedi roadmap PR-P11).
"""

import customtkinter as ctk

from .. import sports
from .dictionary_viewer import LEVEL_LABELS, LEVELS, Debouncer

# Voce «tutti gli sport» del filtro (= nessun filtro).
_SPORT_ALL = "(tutti gli sport)"
# Larghezza uniforme di colonna (sola lettura: etichette).
_COL_WIDTH = 150
# Ritardo del debounce della casella «Cerca» (#184 M12): una raffica di keystroke collassa in una
# sola query DB + rebuild tabella a fine digitazione, evitando il lag con dizionari grandi.
_SEARCH_DEBOUNCE_MS = 250


class DictionaryViewerPanel(ctk.CTkFrame):
    """Pannello di sola consultazione del dizionario locale.

    `controller` è un `DictionaryViewerController` (sola lettura). Se assente (es. DB non
    apribile), il pannello mostra un avviso invece di una tabella vuota ambigua."""

    def __init__(self, master=None, controller=None):
        super().__init__(master)
        self.controller = controller
        self._level_label = ctk.StringVar(value=LEVEL_LABELS[LEVELS[0]])
        self._sport = ctk.StringVar(value=_SPORT_ALL)
        self._active_only = ctk.BooleanVar(value=False)
        self._search = ctk.StringVar(value="")
        # Debounce della ricerca (#184 M12): rimanda il refresh durante la digitazione veloce,
        # usando l'after/after_cancel del widget come scheduler.
        self._search_debouncer = Debouncer(
            _SEARCH_DEBOUNCE_MS, self._refresh, schedule=self.after, cancel=self.after_cancel)
        self._build_ui()
        self._refresh()

    def destroy(self):
        """Teardown (#184 M12, Codex P2): annulla un eventuale refresh in debounce PRIMA che i
        widget vengano distrutti. Senza, un timer `after` ancora pendente (l'utente digita e chiude
        la finestra Strumenti entro 250 ms) scatterebbe contro un pannello già distrutto, con un Tcl
        background error sul normale percorso di chiusura. Tkinter, distruggendo i widget, NON
        annulla gli `after` pendenti: vanno annullati a mano qui."""
        deb = getattr(self, "_search_debouncer", None)
        if deb is not None:
            deb.cancel_pending()
        super().destroy()

    # ── costruzione UI ────────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.CTkLabel(
            self, text="🔵  Dizionario Betfair (locale, sola lettura)",
            font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))

        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(bar, text="Livello").pack(side="left", padx=(8, 4))
        ctk.CTkOptionMenu(bar, variable=self._level_label, width=150,
                          values=[LEVEL_LABELS[lv] for lv in LEVELS],
                          command=lambda _v: self._refresh_now()).pack(side="left", padx=4)
        ctk.CTkLabel(bar, text="Sport").pack(side="left", padx=(12, 4))
        ctk.CTkOptionMenu(bar, variable=self._sport, width=160,
                          values=[_SPORT_ALL, *sports.SPORTS],
                          command=lambda _v: self._refresh_now()).pack(side="left", padx=4)
        ctk.CTkCheckBox(bar, text="Solo attivi", variable=self._active_only,
                        command=self._refresh_now).pack(side="left", padx=12)
        ctk.CTkButton(bar, text="🔄 Aggiorna", width=110,
                      command=self._refresh_now).pack(side="left", padx=4)

        # Riga di ricerca: testo cercato come sottostringa su tutte le colonne (nomi
        # partecipante/selezione/evento/mercato/competizione **e** gli ID), così la stessa
        # casella copre sia la "ricerca" sia il "filtro per id" del livello corrente.
        sbar = ctk.CTkFrame(self)
        sbar.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(sbar, text="Cerca").pack(side="left", padx=(8, 4))
        entry = ctk.CTkEntry(sbar, textvariable=self._search, width=260,
                             placeholder_text="partecipante, selezione, evento, ID…")
        entry.pack(side="left", padx=4)
        # Invio = refresh IMMEDIATO; ogni altra digitazione passa dal debounce (#184 M12).
        entry.bind("<Return>", lambda _e: self._refresh_now())
        entry.bind("<KeyRelease>", self._on_search_key)
        ctk.CTkButton(sbar, text="Pulisci", width=80,
                      command=self._clear_search).pack(side="left", padx=4)

        self._counts = ctk.CTkLabel(self, text="", anchor="w")
        self._counts.pack(fill="x", padx=14, pady=(0, 4))

        self._header = ctk.CTkFrame(self, fg_color="transparent")
        self._header.pack(fill="x", padx=12)
        self._rows_frame = ctk.CTkScrollableFrame(self, height=400,
                                                  label_text="Righe del dizionario")
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=6)

    # ── dati ──────────────────────────────────────────────────────────────────
    def _selected_level(self) -> str:
        label = self._level_label.get()
        for lv in LEVELS:
            if LEVEL_LABELS[lv] == label:
                return lv
        return LEVELS[0]

    def _selected_sport(self):
        s = self._sport.get()
        return "" if s == _SPORT_ALL else s

    def _clear_search(self):
        self._search.set("")
        self._refresh_now()

    def _on_search_key(self, event):
        """KeyRelease nella casella «Cerca»: rimanda il refresh col debounce (#184 M12). Invio è
        gestito a parte come refresh immediato, quindi qui lo si ignora (niente doppio refresh)."""
        if getattr(event, "keysym", "") in ("Return", "KP_Enter"):
            return
        self._search_debouncer.trigger()

    def _refresh_now(self):
        """Refresh IMMEDIATO per le azioni discrete (Invio, menu, checkbox, pulsanti): annulla un
        eventuale refresh in debounce così non parte una seconda query/rebuild subito dopo."""
        self._search_debouncer.cancel_pending()
        self._refresh()

    def _clear(self, frame):
        for w in frame.winfo_children():
            w.destroy()

    def _refresh(self):
        """Ricarica la tabella dal controller (sola lettura). Best-effort: un errore di
        lettura mostra un avviso invece di far crashare la finestra Strumenti."""
        self._clear(self._header)
        self._clear(self._rows_frame)
        if self.controller is None:
            self._counts.configure(
                text="⚠️ Dizionario non disponibile (DB locale non apribile).")
            return
        level = self._selected_level()
        try:
            data = self.controller.view(level, sport=self._selected_sport(),
                                        active_only=bool(self._active_only.get()),
                                        search=self._search.get())
        except Exception as exc:   # noqa: BLE001 — lettura best-effort, niente crash GUI
            self._counts.configure(text=f"⚠️ Errore lettura dizionario: {type(exc).__name__}")
            return
        self._counts.configure(
            text=f"{LEVEL_LABELS[level]}: {data['total']} totali, {data['active']} attivi "
                 f"(mostrate {len(data['rows'])} righe).")
        for col in data["columns"]:
            ctk.CTkLabel(self._header, text=col, width=_COL_WIDTH, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=3)
        for row in data["rows"]:
            rf = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
            rf.pack(fill="x", pady=1)
            for cell in row:
                ctk.CTkLabel(rf, text=cell, width=_COL_WIDTH, anchor="w").pack(side="left", padx=3)
