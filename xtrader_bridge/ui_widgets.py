"""Comportamenti condivisi dei widget GUI — fonte UNICA (#182).

`ui_theme` resta il modulo **puro** dei colori (nessun import tkinter, importabile headless).
Qui vive invece il poco **comportamento** che più pannelli devono condividere: oggi
l'attivazione da tastiera delle righe-elenco cliccabili.

Perché una fonte unica e non due copie: i pannelli che disegnano righe cliccabili sono già
due — 🧩 Parser (`custom_parser_gui`) e ⚽ Dizionario nomi (`name_mapping_gui`) — e ne
arriveranno altri con le PR C ed E della #182. Una correzione di accessibilità scritta in due
posti diventa due comportamenti divergenti al primo ritocco.
"""


def rendi_attivabile(widget, azione, *, focusabile=True):
    """Rende una riga-elenco attivabile con il **mouse** e con la **tastiera**.

    `CTkFrame` e `CTkLabel` non ricevono il focus e non reagiscono a Invio/Spazio: una riga
    resa cliccabile con il solo `<Button-1>` è **irraggiungibile senza mouse**. È una
    regressione facile da introdurre passando da un `CTkOptionMenu` — che il focus lo prende —
    a un elenco disegnato a mano (rilievo CodeRabbit sulla PR #226).

    `azione` è il gestore già pronto: riceve l'evento (o nessun argomento) e ritorna
    ``"break"`` per fermare la propagazione riga↔etichetta.

    **`focusabile=False` per i figli cliccabili.** Una riga è di solito un frame con dentro
    un'etichetta, e *entrambi* devono rispondere al mouse — ma se entrambi entrassero nel giro
    del Tab ogni riga varrebbe **due tab-stop**, e scorrere dieci profili da tastiera ne
    chiederebbe venti (rilievo Fable sulla PR #226: rumore di navigazione, non un bug
    funzionale — ma la navigazione da tastiera è esattamente ciò che questa funzione esiste per
    rendere usabile). Quindi: `focusabile=True` sul **contenitore**, `False` sui figli.

    `takefocus` è best-effort: su un widget-spia dei test, o su un widget già distrutto
    durante un refresh, `configure` può sollevare — e non poter mettere una riga nel giro del
    Tab non deve impedire di **disegnarla**."""
    eventi = ("<Button-1>", "<Return>", "<space>") if focusabile else ("<Button-1>",)
    for evento in eventi:
        widget.bind(evento, azione)
    try:
        # `takefocus=0` ESPLICITO sui figli: oggi `CTkLabel`/`CTkFrame` non prendono il focus
        # per default, ma affidarsi a quel default significa che un cambio di CustomTkinter (o
        # un widget diverso passato qui domani) rimetterebbe in silenzio il secondo tab-stop
        # (rilievo Fable sulla PR #226). L'invariante va scritta, non dedotta.
        widget.configure(takefocus=1 if focusabile else 0)
    except Exception:        # noqa: BLE001 — widget-spia o distrutto: resta cliccabile col mouse
        pass
