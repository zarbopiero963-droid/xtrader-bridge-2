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


def disegna_elenco_profili(ctk, i18n, ui_theme, contenitore, names, *,
                           uso, conta_righe, on_click):
    """Disegna l'elenco profili di un pannello Mapping e ritorna ``{nome: riga}``.

    **Fonte unica** dei due elenchi profili (#182 PR B ⚽ nomi, PR C 🎯 mercati). I pannelli
    differiscono solo per *quale* store conta le righe e *quale* mappa d'uso leggono: tutto il
    resto — marcatori, profili fantasma, click, tastiera, un-solo-tab-stop — è identico. Tenerne
    due copie significherebbe due comportamenti divergenti al primo ritocco (regola 3: se la
    correzione va scritta in due posti, il posto giusto è zero).

    Per riga: il **nome**, «🧩 N» = quanti parser salvati usano quel profilo (omesso a zero —
    «🧩 0» sarebbe rumore, un profilo non ancora collegato è normale) e «· N righe».

    In **coda**, i profili **⚠ «solo riferiti»**: nomi che un parser richiede ma che nel
    dizionario non esistono più. A runtime i messaggi intercettati da quel parser producono
    `MAPPING_MISSING` e il segnale viene scartato — una chat può avere più parser, quindi il
    danno è circoscritto a quello. Si mostrano ma **non sono cliccabili**: non esistono, non c'è
    nulla da aprire.

    `ctk`/`i18n`/`ui_theme` sono iniettati invece che importati: questo modulo resta senza
    dipendenze GUI proprie e i test possono passare widget-spia senza toccare `sys.modules`.

    Args:
        contenitore: il frame scorrevole che ospita le righe (viene **svuotato**).
        names: nomi dei profili esistenti, nell'ordine di visualizzazione.
        uso: ``{profilo: [parser]}`` — già letto dal chiamante (una sola passata sui file).
        conta_righe: ``callable(nome) -> int``, quante righe di mappatura ha il profilo.
        on_click: ``callable(nome) -> handler`` che apre il profilo e ferma la propagazione.
    """
    for figlio in list(getattr(contenitore, "winfo_children", lambda: [])()):
        figlio.destroy()
    righe_per_nome = {}
    for nome in names:
        riga = ctk.CTkFrame(contenitore, fg_color="transparent")
        riga.pack(fill="x", pady=1)
        etichetta = ctk.CTkLabel(riga, text=nome, anchor="w")
        etichetta.pack(side="left", padx=(4, 6))
        quanti = len(uso.get(nome, []))
        if quanti:
            ctk.CTkLabel(riga, text=i18n.tr("🧩 {n}").format(n=quanti),
                         font=ctk.CTkFont(size=11), text_color="gray").pack(side="left", padx=3)
        ctk.CTkLabel(riga, text=i18n.tr("· {n} righe").format(n=conta_righe(nome)),
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left", padx=3)
        righe_per_nome[nome] = riga
        # Click SINGOLO = apri: cambiare profilo AUTO-SALVA quello che stai lasciando, quindi
        # non serve il doppio click del pannello Parser. Il gestore ritorna "break" per non far
        # risalire il click dall'etichetta al frame ed eseguire l'apertura due volte — e un
        # doppione qui non è innocuo, salverebbe due volte. Solo la RIGA entra nel giro del Tab.
        gestore = on_click(nome)
        rendi_attivabile(riga, gestore)
        rendi_attivabile(etichetta, gestore, focusabile=False)
    if not names:
        ctk.CTkLabel(contenitore, text=i18n.tr("Nessun profilo. Crea un profilo con «Nuovo»."),
                     text_color="gray", anchor="w").pack(anchor="w", padx=6, pady=4)
    for fantasma in sorted(set(uso) - set(names)):
        riga = ctk.CTkFrame(contenitore, fg_color="transparent")
        riga.pack(fill="x", pady=1)
        ctk.CTkLabel(riga, text=i18n.tr("⚠ {name} (solo riferito)").format(name=fantasma),
                     anchor="w", text_color=ui_theme.STATUS_WARN,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(4, 6))
        ctk.CTkLabel(riga, text=i18n.tr("🧩 {n}").format(n=len(uso.get(fantasma, []))),
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left", padx=3)
    return righe_per_nome


def evidenzia_profilo(righe, selezionato, colore_attivo):
    """Evidenzia la riga del profilo selezionato e spegne le altre.

    Fonte unica con `disegna_elenco_profili`: è agganciata al `trace_add` di `_profile_var` nei
    due pannelli, così ogni `.set(...)` esistente — **inclusi i rollback** di
    `_on_profile_change` quando la config è illeggibile o il salvataggio fallisce — riallinea
    l'elenco da solo, senza che quei rami debbano saperne nulla. È l'invariante che impedisce
    all'utente di credersi su un profilo mentre il codice è su un altro."""
    for nome, riga in (righe or {}).items():
        try:
            riga.configure(fg_color=(colore_attivo if nome == selezionato else "transparent"))
        except Exception:        # noqa: BLE001 — widget distrutto durante un refresh
            pass
