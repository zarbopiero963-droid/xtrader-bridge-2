#!/usr/bin/env python3
"""Cattura screenshot di una schermata del 🧙 Wizard senza passare dai suoi gate.

Perché serve: il Wizard blocca «Avanti ▶» finché la verifica dello step non è ✅, e
quelle verifiche chiamano Telegram (`getMe`, `getUpdates`) con un token reale. In CI
o su una macchina di documentazione quel token non c'è, quindi gli step successivi al
primo sarebbero irraggiungibili cliccando.

Qui la vista REALE (`WizardWindow`) viene istanziata direttamente e portata allo step
richiesto — esattamente come fa un test — senza modificare l'app e senza simulare
alcunché: quello che si vede a schermo sono i widget e i testi veri.

Uso (serve un display; sotto Xvfb va benissimo)::

    Xvfb :99 -screen 0 1280x1024x24 &
    DISPLAY=:99 PYTHONPATH=. python3 tools/screenshots/wizard_shot.py --step 2
    # poi, da un'altra shell, mentre la finestra è aperta:
    DISPLAY=:99 import -window root /tmp/root.png     # imagemagick
    DISPLAY=:99 xdotool getwindowgeometry --shell $(xdotool search --name Wizard | head -1)

Vedi `tools/screenshots/README.md` per la ricetta completa (crop, tab, lingue).

Nessun dato reale: token e chat mostrati sono **fittizi** e coerenti con le guide.
"""

from __future__ import annotations

import argparse

import customtkinter as ctk

# L'app imposta il tema all'avvio: qui va rifatto, altrimenti la finestra esce in
# tema CHIARO e lo screenshot stona con il resto della documentazione.
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

from xtrader_bridge import i18n  # noqa: E402  (dopo il tema, come fa l'app)
from xtrader_bridge.wizard_gui import WizardWindow  # noqa: E402

# Valori d'esempio usati in TUTTE le guide: teniamoli allineati.
DEMO = {
    "bot_token": "123456789:AAExempio-Token-NON-Reale-0000",
    "chat_id": "-1001234567890",
    "csv_path": "C:\\BetRelay\\segnali.csv",
}

# Esiti mostrati sotto il corpo dello step (solo presentazione: nessuna sonda gira).
DEMO_RESULTS = {
    2: "✅ Messaggio ricevuto dalla chat -1001234567890",
    4: "✅ Percorso valido e scrivibile",
}
_OK = "#66bb6a"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", type=int, default=1, choices=(1, 2, 3, 4, 5),
                    help="step del wizard da mostrare (1..5)")
    ap.add_argument("--lang", default="it", choices=("it", "en", "es"),
                    help="lingua dell'interfaccia")
    ap.add_argument("--seconds", type=int, default=25,
                    help="per quanti secondi tenere aperta la finestra")
    args = ap.parse_args()

    i18n.set_language(args.lang)

    root = ctk.CTk()
    root.withdraw()
    win = WizardWindow(root, initial=dict(DEMO))
    win._step = args.step - 1          # la vista numera gli step da 0
    win._render()
    msg = DEMO_RESULTS.get(args.step)
    if msg:
        win._result_lbl.configure(text=msg, text_color=_OK)
    win.geometry("+0+0")               # angolo in alto a sinistra: crop prevedibile
    win.update_idletasks()
    win.update()
    root.after(args.seconds * 1000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
