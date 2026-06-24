"""Finestra hub "🧰 Strumenti": raccoglie gli strumenti del bridge in schede.

Parte della consolidazione GUI (roadmap, Tappa 1): invece di N finestre separate
aperte da N pulsanti, gli strumenti vivono come schede di un'unica finestra.

`ToolsWindow` è DISACCOPPIATA dai singoli strumenti: riceve una lista di
`(titolo_scheda, factory)`, dove `factory(parent)` costruisce il pannello dentro la
scheda. Così questa finestra non conosce le callback/gli store dei singoli strumenti
— li cabla chi la apre (la GUI principale, che ha la config viva). Aggiungere uno
strumento = aggiungere una voce alla lista, senza toccare questa classe.

NB: modulo GUI, non testato in CI (richiede un display). La logica dei singoli
strumenti è coperta dai rispettivi test unitari. Verifica manuale su Windows.
"""

import customtkinter as ctk

from . import gui_utils


class ToolsWindow(ctk.CTkToplevel):
    """Finestra a schede che ospita i pannelli-strumento.

    Args:
        master: finestra padre.
        panels: lista di `(titolo, factory)`; `factory(parent)` ritorna un widget
            (tipicamente un `CTkFrame`) da mostrare nella scheda.
        initial: titolo della scheda da selezionare all'apertura (opzionale).
        title: titolo della finestra.
    """

    def __init__(self, master=None, panels=None, initial=None, title="🧰 Strumenti"):
        super().__init__(master)
        self.title(title)
        gui_utils.fit_to_screen(self, 1040, 720, 780, 480)
        # `command`: a ogni cambio scheda si aggiornano le liste-opzioni del pannello
        # mostrato (vedi `_on_tab_change`), così le scelte derivate dal config restano
        # fresche senza riaprire la finestra (Codex).
        self._tabs = ctk.CTkTabview(self, command=self._on_tab_change)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self._panels = {}      # titolo scheda → pannello vivo (per refresh_options)
        for tab_title, factory in (panels or []):
            container = self._tabs.add(tab_title)
            try:
                panel = factory(container)
                panel.pack(fill="both", expand=True, padx=4, pady=4)
                self._panels[tab_title] = panel
            except Exception as exc:        # noqa: BLE001 — isolamento per-scheda
                # Un pannello che fallisce la COSTRUZIONE (es. cartella profili illeggibile
                # → OSError da list_profiles) non deve impedire l'apertura degli ALTRI
                # strumenti: prima della consolidazione erano finestre separate, quindi un
                # guasto non bloccava gli altri. Qui si preserva quell'isolamento mostrando
                # l'errore NELLA sua scheda e proseguendo con le altre (Codex).
                ctk.CTkLabel(
                    container,
                    text=f"⚠️ Impossibile aprire questo strumento:\n{exc}",
                    text_color="#ef5350", wraplength=600, justify="left",
                    anchor="w").pack(padx=12, pady=12, fill="x")
        self.select_tab(initial)

    def _on_tab_change(self):
        """Al cambio scheda, aggiorna le liste-opzioni del pannello mostrato se le supporta
        (`refresh_options`), così provider/parser/profili modificati in un'altra scheda si
        riflettono subito, senza scartare le modifiche in corso. Best-effort: un refresh
        fallito non rompe il cambio scheda (Codex)."""
        panel = self._panels.get(self._tabs.get())
        if panel is not None and hasattr(panel, "refresh_options"):
            try:
                panel.refresh_options()
            except Exception:               # noqa: BLE001 — refresh best-effort
                pass

    def select_tab(self, title):
        """Seleziona la scheda `title` (no-op se vuoto o titolo non valido).

        Usata sia all'apertura sia quando si riapre la hub già viva su un'altra scheda
        (vedi `App._open_tools`: una sola finestra hub, si cambia scheda)."""
        if not title:
            return
        try:
            self._tabs.set(title)
        except Exception:                   # noqa: BLE001 — titolo non valido: resta la scheda corrente
            pass
