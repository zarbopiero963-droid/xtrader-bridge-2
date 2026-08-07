"""Composizione visiva a CARD e BADGE — #182 restyle totale (decisione proprietario 2026-08-04).

Gli sketch approvati (artifact «Sketch completo») raggruppano ogni sezione in una card con
bordo, angoli arrotondati e titolo piccolo in grassetto, e marcano lo stato con badge-pillola
(«✓ attivo», «📡 2», «🧩 3 parser»). Le PR A/B/C/E hanno consegnato le funzioni dentro il
layout piatto storico: questo modulo fornisce la composizione, così ogni pannello la applica
in modo IDENTICO invece di reinventarla (fonte unica, regola 3).

Contratto (test-safe, come i pannelli reali):
- gli helper ricevono il modulo ``ctk`` come PRIMO argomento — mai importato qui a livello di
  modulo: i test headless stubbano ``customtkinter`` in ``sys.modules`` PRIMA di importare il
  pannello, e un import qui congelerebbe lo stub sbagliato (stesso pattern della lista profili
  condivisa in `name_mapping_gui`);
- ogni chiamata ai widget è difensiva: con i doppi dei test (classi vuote generate al volo)
  ``pack``/``configure`` possono non esistere → best-effort, mai un crash headless;
- SOLO presentazione: nessuno stato, nessuna logica, nessun accesso a config/CSV.

I colori vengono da `ui_theme` (fonte unica della palette): la semantica di sicurezza
(SUCCESS/DANGER/WARN) resta quella dei token, qui non si rimappa nulla.
"""

import sys
from . import ui_theme

# Tipi di badge → (colore testo/bordo, riempimento). ``None`` = trasparente (solo bordo).
# I nomi sono ROLI, non colori: chi chiama dichiara il significato, la palette resta qui.
_BADGE_KINDS = {
    "ok":     (ui_theme.STATUS_OK,   None),          # ✓ attivo · 🧩 N parser
    "muted":  (ui_theme.TEXT2,       ui_theme.SURFACE2),  # 📡 N · conteggi neutri
    "warn":   (ui_theme.STATUS_WARN, None),          # ⚠ solo riferito / fantasma
    "danger": (ui_theme.STATUS_ERR,  None),          # stati d'errore
}


def card_style(border=None) -> dict:
    """Kwargs di stile della CARD — la FONTE UNICA dei quattro token (rilievo CodeRabbit #236:
    `card()` esisteva ma i pannelli duplicavano i letterali in ~12 siti, cioè proprio la
    divergenza-futura che la regola 3 vieta). I pannelli fanno
    ``ctk.CTkFrame(parent, **ui_cards.card_style())`` — la costruzione resta NEL pannello
    (i test AST la ispezionano lì), lo stile vive qui.

    ``border``: colore bordo alternativo (es. `ui_theme.ACCENT` per le colonne-lista);
    None = il bordo standard `BORDER`."""
    return {
        "fg_color": ui_theme.SURFACE,
        "corner_radius": ui_theme.RADIUS_CARD,
        "border_width": 1,
        "border_color": border if border is not None else ui_theme.BORDER,
    }


def tune_scrolling(sf, step_px: int = 1) -> None:
    """Passo di scorrimento di una `CTkScrollableFrame`.

    ⚠️ **BUILD DI MISURA (#319, 2026-08-07): `step_px` è tornato a 1.** Non è la
    configurazione definitiva — serve a rispondere a una domanda precisa, e va
    rivista appena il proprietario ha guardato il risultato. Vedi «La misura» sotto.

    **Storia.** Segnalazione proprietario 2026-08-04: la griglia del Parser
    «scatta/trema» sotto rotellina su Windows. Rimedio di allora: `step_px=3`.
    Segnalazione proprietario 2026-08-07 (#319): scorrendo, il testo lascia una
    **scia di decine di copie** — nel fotogramma a 00:11 del video l'etichetta
    `MarketName` è scritta così tante volte da formare un blocco illeggibile.

    **Cosa fa davvero questa funzione — e cosa NON può fare.** Su Windows CTk
    scrolla `-int(event.delta / 6)` unità per scatto, cioè **20 unità, cablate**
    (`ctk_scrollable_frame.py::_mouse_wheel_all`). L'unica leva qui è la
    *dimensione* del quanto, non il loro *numero*: `step_px` decide di quanti pixel
    vale un'unità, e quindi **quanto è distanziata** una copia dalla successiva, non
    quante copie ci siano:

    - `step_px=1` → copie a 1px l'una dall'altra, adiacenti → **sfocatura**;
    - `step_px=3` → copie a 3px l'una dall'altra → **scia leggibile**.

    Quindi la correzione del 04/08 non ha creato il difetto: lo ha reso visibile,
    scambiando una sfocatura per una scia. Nessuno dei due valori lo risolve.

    ⚠️ **Cosa NON è accertato** (rilievo CodeRabbit sulla #320, fondato): quanti
    ridisegni Tk esegua davvero. `_mouse_wheel_all` emette **un solo** comando
    `yview("scroll", N, "units")` e Tk accorpa i ridisegni a idle — «20 unità» è il
    numero richiesto, non un conteggio di disegni. I fotogrammi mostrano molte copie,
    ma il loro numero non è stato misurato e non va dedotto dal divisore.

    **La misura.** Con `step_px=1` si torna al default CTk di Windows. Se il
    proprietario rivede il tremolio del 04/08 al posto della scia, l'ipotesi è
    confermata: il difetto è nella **ripulitura del canvas**, non nel passo — e il
    rimedio vero (prendere il controllo della rotellina per avere UN ridisegno per
    scatto) diventa mirato invece che a tentoni.

    **Solo su Windows** (rilievo GPT-5.5 sulla #320). Prima si applicava ovunque, ma
    CTk non scrolla lo stesso numero di unità per piattaforma:

    | piattaforma | unità per scatto | increment CTk | px per scatto |
    |---|---|---|---|
    | Windows | 20 (`-delta/6`) | 1 | 20 |
    | macOS   | `-delta` | 4/8 | dipende dal delta |
    | Linux   | **1** (`yview_scroll(±1)`) | **30** | **30** |

    Su Linux una rotellina vale **una sola unità**: lì l'increment *è* il passo. Quindi
    `tune_scrolling(3)` ha reso lo scorrimento **3 px per scatto** invece di 30 — dieci
    volte più lento — dal 04/08 a oggi, e la misura a 1 px lo avrebbe portato a 1 px.
    Nessuno se n'era accorto perché il bersaglio è Windows e su Linux gira solo la
    pipeline screenshot, che non scrolla: una regressione introdotta da una correzione
    pensata per un'altra piattaforma. L'accordatura vale solo dove il suo ragionamento
    vale; altrove si lascia il default di CTk.

    Usa `_parent_canvas` (non c'è API pubblica per gli increment): accesso protetto
    e best-effort — doppi headless senza canvas, o canvas già distrutto → no-op,
    lo scroll resta quello di default e la GUI vive."""
    if not sys.platform.startswith("win"):
        return
    try:
        sf._parent_canvas.configure(xscrollincrement=step_px, yscrollincrement=step_px)
    except Exception:  # noqa: BLE001 — accordatura best-effort: mai rompere la costruzione
        pass


def _best_effort(widget, method, *args, **kwargs):
    """Chiama ``widget.method(...)`` se esiste; i doppi dei test non hanno Tk dietro."""
    fn = getattr(widget, method, None)
    if not callable(fn):
        return None
    try:
        return fn(*args, **kwargs)
    except Exception:                # noqa: BLE001 — widget finto/distrutto: presentazione, mai crash
        return None


def collapse_when_empty(box) -> None:
    """Toglie l'altezza a un contenitore di righe che al momento non ne ha nessuna
    (segnalazione proprietario 2026-08-04: buchi verticali nella scheda «Parser»).

    Un `CTkFrame` senza figli chiede l'altezza di DEFAULT di CustomTkinter — 200px —
    anche se non contiene nulla; con dei figli è la propagazione del pack a decidere
    (una riga ≈ 32px). Misurato su CustomTkinter reale sotto Xvfb::

        vuoto            → 200px      vuoto con height=0 → 1px
        con una riga     →  32px      (la propagazione vince sull'opzione)

    Nell'app vera erano OTTO i contenitori così: da soli valevano più di uno schermo
    di scorrimento a vuoto. Va chiamata alla costruzione **e dopo ogni mutazione delle
    righe**: svuotare un contenitore non lo riabbassa da solo — l'altezza richiesta
    resta quella dell'ultimo contenuto finché non si rimette `height`.

    Nessun effetto quando le righe ci sono (la propagazione ignora l'opzione), e
    best-effort come il resto del modulo: doppi headless o widget già distrutti → no-op.

    **Fail-safe sull'ambiguità** (rilievo Claude Fable 5, #249): `_best_effort` ritorna
    ``None`` sia quando il metodo non esiste sia quando ha sollevato, e ``None`` NON
    significa «nessun figlio» — significa «non lo so». Trattarlo come vuoto porterebbe a
    ridimensionare un widget di cui non si sa nulla (tipicamente uno in distruzione).
    Quando l'informazione manca non si tocca niente: la lista vuota VERA resta l'unico
    caso che fa collassare.
    """
    figli = _best_effort(box, "winfo_children")
    if figli is None or figli:
        return
    _best_effort(box, "configure", height=0)


def card(ctk, parent, title="", *, pad=(10, 6), fill="x", expand=False):
    """Crea una CARD di sezione (frame con superficie, bordo e raggio dei token) e, se
    ``title`` non è vuoto, il titolo piccolo in grassetto in testa — la composizione delle
    sezioni negli sketch. Ritorna il frame: il chiamante ci impila dentro i suoi widget.

    Il titolo è un ``CTkLabel`` costruito QUI e non nei pannelli: è cornice, non contenuto —
    i test AST sui pannelli contano i bottoni/label di dominio, non la cornice."""
    frame = ctk.CTkFrame(parent, **card_style())
    _best_effort(frame, "pack", fill=fill, expand=expand, padx=pad[0], pady=pad[1])
    if title:
        try:
            font = ctk.CTkFont(size=12, weight="bold")
        except Exception:            # noqa: BLE001 — doppio di test senza CTkFont funzionante
            font = None
        kwargs = {"text": title, "anchor": "w", "text_color": ui_theme.TEXT2}
        if font is not None:
            kwargs["font"] = font
        label = ctk.CTkLabel(frame, **kwargs)
        _best_effort(label, "pack", anchor="w", padx=10, pady=(6, 0))
    return frame


def badge(ctk, parent, text, kind="muted", *, side="left", padx=3):
    """Crea un BADGE-pillola («✓ attivo», «📡 2», «⚠ solo riferito») e lo impacchetta.

    È un mini-frame bordato con dentro una label: l'approssimazione CustomTkinter della
    pillola web degli sketch (dichiarata e accettata: niente ombre/hover). Ritorna il frame."""
    color, fill = _BADGE_KINDS.get(kind, _BADGE_KINDS["muted"])
    shell = ctk.CTkFrame(parent, fg_color=(fill if fill is not None else "transparent"),
                         corner_radius=9, border_width=1, border_color=color)
    _best_effort(shell, "pack", side=side, padx=padx)
    try:
        font = ctk.CTkFont(size=10)
    except Exception:                # noqa: BLE001 — font ctk non costruibile (tk non pronto/headless) -> badge senza font, mai crash della vista
        font = None
    kwargs = {"text": text, "text_color": color}
    if font is not None:
        kwargs["font"] = font
    label = ctk.CTkLabel(shell, **kwargs)
    _best_effort(label, "pack", padx=6, pady=0)
    return shell


def hint(ctk, parent, text, *, pad=(10, 2)):
    """Riga di aiuto grigia e piccola sotto una sezione (lo stile «hint» degli sketch)."""
    try:
        font = ctk.CTkFont(size=11)
    except Exception:                # noqa: BLE001 — font ctk non costruibile (tk non pronto/headless) -> hint senza font, mai crash della vista
        font = None
    kwargs = {"text": text, "anchor": "w", "justify": "left",
              "text_color": ui_theme.TEXT3, "wraplength": 760}
    if font is not None:
        kwargs["font"] = font
    label = ctk.CTkLabel(parent, **kwargs)
    _best_effort(label, "pack", fill="x", padx=pad[0], pady=pad[1])
    return label
