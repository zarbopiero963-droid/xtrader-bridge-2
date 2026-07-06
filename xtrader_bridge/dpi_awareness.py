"""#311 §3.5: DPI awareness esplicita su Windows, PRIMA di creare la root Tk.

Senza dichiararsi DPI-aware, su scaling 125–150% Windows fa il bitmap-stretch della
finestra (testo sfocato) e le misure Tk non corrispondono ai pixel reali.
customtkinter la attiva da solo, ma solo alla creazione della prima widget: qui la
si imposta in modo esplicito e deterministico all'avvio dell'app, con lo STESSO
valore che userebbe customtkinter (PROCESS_PER_MONITOR_DPI_AWARE) così le due
chiamate non confliggono mai (la seconda fallisce senza effetti: l'awareness di
processo si può impostare una sola volta, per design di Windows).

Fail-open per contratto: un fallimento DPI non deve MAI impedire l'avvio del bridge
(`enable_dpi_awareness` non solleva; ritorna un esito testuale per log/test).
Dipendenze iniettabili (`platform`, `windll`) per test deterministici su POSIX/CI.
"""

import os

# Esiti possibili (stringhe per log/test, non eccezioni).
SHCORE = "shcore"            # SetProcessDpiAwareness (Windows 8.1+) riuscita
USER32 = "user32"            # fallback SetProcessDPIAware (Windows Vista+) riuscita
UNSUPPORTED = "unsupported"  # non-Windows: niente da fare
FAILED = "failed"            # Windows ma entrambe le API non disponibili/fallite

_PER_MONITOR_DPI_AWARE = 2   # stesso valore usato da customtkinter: mai in conflitto


def enable_dpi_awareness(*, platform=None, windll=None) -> str:
    """Imposta la DPI awareness del processo (Windows). Ritorna l'esito, MAI raise.

    Args:
        platform: override di ``os.name`` nei test (``"nt"`` = Windows).
        windll: override di ``ctypes.windll`` nei test (oggetto con ``.shcore`` /
            ``.user32``); su POSIX ``ctypes.windll`` non esiste.
    """
    if platform is None:
        platform = os.name
    if platform != "nt":
        return UNSUPPORTED
    if windll is None:
        try:
            import ctypes
            windll = ctypes.windll
        except Exception:   # noqa: BLE001 — fail-open: senza windll niente DPI, mai bloccare l'avvio
            return FAILED
    try:
        windll.shcore.SetProcessDpiAwareness(_PER_MONITOR_DPI_AWARE)
        return SHCORE
    except Exception:   # noqa: BLE001 — shcore assente (Win < 8.1) o awareness già impostata: si prova il fallback
        pass
    try:
        windll.user32.SetProcessDPIAware()
        return USER32
    except Exception:   # noqa: BLE001 — fail-open: l'app parte comunque (solo resa più sfocata)
        return FAILED
