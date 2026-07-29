"""Helper GUI condivisi tra le finestre del bridge.

Un solo posto per la logica "apri la finestra in modo che entri nello schermo",
così tutte le finestre (principale + builder/dizionario/profili/provider/chat)
si comportano allo stesso modo su schermi piccoli.
"""


def clamp_to_screen(width, height, min_width, min_height, screen_w, screen_h,
                    margin=80):
    """PURA (#311 §3.5): riduce ``width × height`` all'area schermo disponibile
    (``screen − margin`` su entrambi gli assi), con PAVIMENTO ai minimi dichiarati:
    il clamp non apre mai una finestra più piccola del suo ``minsize``.

    Returns:
        Tupla ``(width, height)`` clampata.
    """
    avail_w = max(min_width, screen_w - margin)
    avail_h = max(min_height, screen_h - margin)
    return min(width, avail_w), min(height, avail_h)


def fit_to_screen(window, width, height, min_width, min_height, margin=80):
    """Apre ``window`` a ``width × height`` ma CLAMPA larghezza E altezza all'area
    schermo disponibile (``screen − margin``, vedi ``clamp_to_screen``).

    Su schermi piccoli (portatili) una finestra più alta dello schermo finirebbe
    sotto la taskbar lasciando la parte bassa irraggiungibile, e una più larga
    (Strumenti/dizionario: fino a 1140px) uscirebbe di lato (#311 §3.5): clampando
    entrambe le dimensioni la finestra resta interamente visibile. Imposta anche
    ``minsize`` perché resti usabile quando viene ridotta; i minimi fanno da
    pavimento al clamp (mai sotto il layout minimo dichiarato dal chiamante).

    Args:
        window: la finestra (``CTk``/``CTkToplevel``) su cui agire.
        width: larghezza desiderata in px (verrà ridotta se non entra).
        height: altezza desiderata in px (verrà ridotta se non entra).
        min_width: larghezza minima consentita (``minsize``); pavimento del clamp.
        min_height: altezza minima consentita (``minsize``); pavimento del clamp.
        margin: px lasciati liberi ai bordi (taskbar, barra del titolo). Default 80.
    """
    try:
        screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
    except Exception:
        # winfo_screen* può fallire se la finestra non è ancora mappata: in tal
        # caso si usano le dimensioni richieste così come sono (nessun clamp).
        w, h = width, height
    else:
        w, h = clamp_to_screen(width, height, min_width, min_height,
                               screen_w, screen_h, margin)
    window.geometry(f"{w}x{h}")
    window.minsize(min_width, min_height)


def ask_confirm(title: str, text: str) -> bool:
    """Conferma sì/no MODALE e FAIL-CLOSED (P3-27/P3-28 #76): `True` solo se l'utente
    conferma esplicitamente. Punto unico per le azioni distruttive della GUI (eliminazioni,
    scarto di modifiche non salvate), stesso pattern di `App._confirm_collaudo_mode`:
    qualunque errore del dialog (headless, root distrutta, Tk in teardown) → `False`,
    cioè NON confermato — un'azione distruttiva non parte mai per un dialog rotto.
    Anche l'IMPORT sta nel try (review Fable #96): una build senza Tk deve dare
    `False`, non propagare ImportError al chiamante."""
    try:
        from tkinter import messagebox
        return bool(messagebox.askyesno(title, text))
    except Exception:   # noqa: BLE001 — dialog non disponibile: fail-closed, non confermare
        return False


def running_edit_notice(is_running) -> str:
    """Avviso da mostrare quando si SALVA una configurazione mentre il bridge è ATTIVO
    (issue #176, decisione del proprietario: **avvisare e lasciar procedere**, non bloccare).

    Ritorna il testo dell'avviso, oppure ``""`` se il bridge è fermo (o non si sa).

    Perché non blocca: la sessione live usa lo snapshot di config preso allo START, quindi
    salvare NON cambia il comportamento a caldo — non c'è nulla di incoerente da impedire.
    Quello che manca all'operatore è solo l'informazione: senza questo avviso modifica un
    parser o un dizionario con il bridge acceso e non ha nulla che gli ricordi che avrà
    effetto dal prossimo AVVIA. (`profiles_gui` invece BLOCCA di proposito: lì si applica un
    profilo INTERO, e vedere "applicato" mentre dry_run/chat/csv_path restano quelli vecchi
    sarebbe una bugia pericolosa — Codex P1. Sono due casi diversi, non un'incoerenza.)

    ``is_running`` è una callable iniettata dalla GUI principale. **Fail-safe**: se manca,
    non è chiamabile o solleva, si assume bridge fermo e si ritorna ``""`` — una sonda di
    stato difettosa non deve impedire un salvataggio né inventare un avviso."""
    from . import i18n
    try:
        attivo = bool(is_running()) if callable(is_running) else False
    except Exception:   # noqa: BLE001 — una sonda difettosa non deve rompere il salvataggio
        return ""
    if not attivo:
        return ""
    # NEUTRO sull'esito: lo stesso avviso viene accodato anche al messaggio di ERRORE, e
    # un testo che afferma «la modifica è salvata» accanto a «FALLITO» è una bugia
    # operativa — l'utente se ne andrebbe convinto di aver salvato (rilievo Fugu #177).
    return i18n.tr("⚠️ Bridge ATTIVO: le modifiche hanno effetto dal prossimo AVVIA.")


def with_running_notice(message: str, is_running) -> str:
    """`message` con l'avviso «bridge attivo» accodato, se il bridge gira.

    Accoda invece di sostituire: l'esito del salvataggio (riuscito/fallito) resta la prima
    cosa che l'operatore legge, l'avviso è il contesto. Con bridge fermo ritorna `message`
    invariato, quindi il sito di chiamata non deve sapere nulla dello stato."""
    avviso = running_edit_notice(is_running)
    testo = str(message or "")
    if not avviso:
        return testo
    return f"{testo}  {avviso}" if testo else avviso
