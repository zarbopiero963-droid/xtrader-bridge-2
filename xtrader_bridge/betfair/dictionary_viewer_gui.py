"""Pannello «Dizionario Betfair» — SOLA LETTURA (issue #86 PR-P11).

Vista di consultazione del dizionario Betfair locale: l'utente sceglie un livello
(Sport/Competizioni/Eventi/Mercati/Selezioni) e un filtro sport, e vede le righe
sincronizzate sul PC. **Non** modifica nulla (nessuna Entry, nessun pulsante di
scrittura), non fa rete e non muta il DB: tutta la logica sta in
`DictionaryViewerController` (testata in CI). Questo modulo è solo widget/wiring e NON
è testato in CI (richiede un display): verifica manuale (vedi roadmap PR-P11).
"""

from tkinter import ttk

import customtkinter as ctk

from .. import sports
from .dictionary_viewer import LEVEL_LABELS, LEVELS, Debouncer, DictionaryBusy

# Voce «tutti gli sport» del filtro (= nessun filtro).
_SPORT_ALL = "(tutti gli sport)"
# Larghezza uniforme di colonna (sola lettura: etichette).
_COL_WIDTH = 150
# Ritardo del debounce della casella «Cerca» (#184 M12): una raffica di keystroke collassa in una
# sola query DB + rebuild tabella a fine digitazione, evitando il lag con dizionari grandi.
_SEARCH_DEBOUNCE_MS = 250
# Tetto di righe renderizzate (Fase 2 collaudo Betfair). Il vecchio viewer disegnava una griglia di
# widget CustomTkinter PER CELLA (~88.000 widget per le 12.523 selezioni) sul thread Tk → minuti di
# freeze ("Non risponde"). Ora la tabella è un `ttk.Treeview` nativo (virtualizzato: renderizza solo
# le righe visibili) e il cap limita comunque quante righe si inseriscono in un colpo, così Mercati e
# Selezioni non bloccano. Con più righe del cap, l'utente restringe con Sport/Cerca (la riga conteggi
# lo segnala). Il cap è applicato dal controller DOPO i filtri (vista corretta, non una LIMIT SQL).
_ROW_CAP = 500


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

        # Tabella nativa `ttk.Treeview` (Fase 2): virtualizzata (renderizza solo le righe visibili),
        # colonne con header e larghezza propria → niente freeze e niente disallineamento. Rimpiazza
        # la vecchia griglia di label in `CTkScrollableFrame`. `show="headings"` nasconde la colonna
        # ad albero fantasma (mostriamo solo le colonne dati).
        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=12, pady=6)
        self._tree = ttk.Treeview(table_frame, show="headings", height=18, selectmode="none")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._apply_tree_style()

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

    def _apply_tree_style(self):
        """Stile minimo del Treeview (best-effort): altezza riga leggibile e header in grassetto.
        Guardato: un fallimento di stile (tema ttk che ignora l'opzione) non deve rompere la tabella,
        che resta comunque funzionale coi colori nativi del tema."""
        try:
            style = ttk.Style(self)
            style.configure("Treeview", rowheight=24)
            style.configure("Treeview.Heading", font=(None, 10, "bold"))
        except Exception:   # noqa: BLE001 — lo stile è cosmetico, mai bloccante
            pass

    def _set_tree_columns(self, headers):
        """(Ri)configura le colonne del Treeview per il livello corrente. Gli identificatori sono
        posizionali (`c0`, `c1`, …) per non dipendere dal testo dell'header (spazi/simboli); il testo
        visibile resta l'intestazione italiana. Larghezza per-colonna → colonne allineate."""
        col_ids = [f"c{i}" for i in range(len(headers))]
        self._tree.configure(columns=col_ids)
        for cid, header in zip(col_ids, headers):
            self._tree.heading(cid, text=header)
            self._tree.column(cid, width=_COL_WIDTH, minwidth=60, anchor="w", stretch=False)

    def _clear_tree_rows(self):
        """Svuota le righe della tabella (le colonne restano). `delete(*children)` è O(righe) e non
        crea/distrugge widget per cella: è ciò che elimina il freeze rispetto alla vecchia griglia."""
        children = self._tree.get_children()
        if children:
            self._tree.delete(*children)

    def _refresh(self):
        """Ricarica la tabella dal controller (sola lettura). Best-effort: un errore di
        lettura mostra un avviso invece di far crashare la finestra Strumenti."""
        self._clear_tree_rows()
        if self.controller is None:
            self._counts.configure(
                text="⚠️ Dizionario non disponibile (DB locale non apribile).")
            return
        level = self._selected_level()
        try:
            # `view_if_free` fa FAIL-FAST se una sync Betfair tiene ora il lock del DB
            # (tenuto attraverso le chiamate di rete del catalogue): senza, la lettura sul
            # thread Tk bloccherebbe e freezerebbe la GUI fino a fine sync (Codex #175).
            # `limit=_ROW_CAP`: cap righe renderizzate (Fase 2) → niente freeze su Mercati/Selezioni.
            data = self.controller.view_if_free(level, sport=self._selected_sport(),
                                                active_only=bool(self._active_only.get()),
                                                search=self._search.get(), limit=_ROW_CAP)
        except DictionaryBusy:
            self._counts.configure(
                text="⏳ Dizionario in aggiornamento (sincronizzazione Betfair in corso): "
                     "premi 🔄 Aggiorna tra poco.")
            return
        except Exception as exc:   # noqa: BLE001 — lettura best-effort, niente crash GUI
            self._counts.configure(text=f"⚠️ Errore lettura dizionario: {type(exc).__name__}")
            return
        self._set_tree_columns(data["columns"])
        for row in data["rows"]:
            self._tree.insert("", "end", values=list(row))
        shown = data.get("shown", len(data["rows"]))
        msg = (f"{LEVEL_LABELS[level]}: {data['total']} totali, {data['active']} attivi "
               f"(mostrate {len(data['rows'])} di {shown} righe).")
        if data.get("truncated"):
            msg += (f"  ⚠️ Elenco troncato a {_ROW_CAP}: restringi con «Sport» o «Cerca» "
                    f"per vedere le righe che ti servono.")
        self._counts.configure(text=msg)
