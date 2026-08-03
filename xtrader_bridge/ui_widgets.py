"""Comportamenti condivisi dei widget GUI — fonte UNICA (#182).

`ui_theme` resta il modulo **puro** dei colori (nessun import tkinter, importabile headless).
Qui vive invece il poco **comportamento** che più pannelli devono condividere: oggi
l'attivazione da tastiera delle righe-elenco cliccabili.

Perché una fonte unica e non due copie: i pannelli che disegnano righe cliccabili sono già
due — 🧩 Parser (`custom_parser_gui`) e ⚽ Dizionario nomi (`name_mapping_gui`) — e ne
arriveranno altri con le PR C ed E della #182. Una correzione di accessibilità scritta in due
posti diventa due comportamenti divergenti al primo ritocco.
"""


def rendi_attivabile(widget, azione):
    """Rende una riga-elenco attivabile con il **mouse** e con la **tastiera**.

    `CTkFrame` e `CTkLabel` non ricevono il focus e non reagiscono a Invio/Spazio: una riga
    resa cliccabile con il solo `<Button-1>` è **irraggiungibile senza mouse**. È una
    regressione facile da introdurre passando da un `CTkOptionMenu` — che il focus lo prende —
    a un elenco disegnato a mano (rilievo CodeRabbit sulla PR #226).

    `azione` è il gestore già pronto: riceve l'evento (o nessun argomento) e ritorna
    ``"break"`` per fermare la propagazione riga↔etichetta.

    `takefocus` è best-effort: su un widget-spia dei test, o su un widget già distrutto
    durante un refresh, `configure` può sollevare — e non poter mettere una riga nel giro del
    Tab non deve impedire di **disegnarla**."""
    for evento in ("<Button-1>", "<Return>", "<space>"):
        widget.bind(evento, azione)
    try:
        widget.configure(takefocus=1)
    except Exception:        # noqa: BLE001 — widget-spia o distrutto: resta cliccabile col mouse
        pass
