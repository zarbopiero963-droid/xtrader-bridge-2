"""Helper GUI condivisi tra le finestre del bridge.

Un solo posto per la logica "apri la finestra in modo che entri nello schermo",
così tutte le finestre (principale + builder/dizionario/profili/provider/chat)
si comportano allo stesso modo su schermi piccoli.
"""


def fit_to_screen(window, width, height, min_width, min_height, margin=80):
    """Apre ``window`` a ``width × height`` ma CLAMPA l'altezza all'area schermo
    disponibile (``screenheight − margin``).

    Su schermi piccoli (portatili) una finestra più alta dello schermo finirebbe
    sotto la taskbar lasciando la parte bassa irraggiungibile; clampando l'altezza la
    finestra resta interamente visibile. Imposta anche ``minsize`` perché resti usabile
    quando viene ridotta. La larghezza NON viene clampata: i layout del bridge sono
    tarati in larghezza e si preferisce uno scroll orizzontale eventuale a un wrap.

    Args:
        window: la finestra (``CTk``/``CTkToplevel``) su cui agire.
        width: larghezza desiderata in px.
        height: altezza desiderata in px (verrà ridotta se non entra).
        min_width: larghezza minima consentita (``minsize``).
        min_height: altezza minima consentita (``minsize``); fa anche da pavimento
            all'altezza clampata, così la finestra non si apre più piccola del minimo.
        margin: px lasciati liberi sotto/sopra (taskbar, barra del titolo). Default 80.
    """
    try:
        avail_h = max(min_height, window.winfo_screenheight() - margin)
    except Exception:
        # winfo_screenheight può fallire se la finestra non è ancora mappata: in tal
        # caso si usa l'altezza richiesta così com'è (nessun clamp).
        avail_h = height
    window.geometry(f"{width}x{min(height, avail_h)}")
    window.minsize(min_width, min_height)
