"""Avviso «bridge ATTIVO» sul salvataggio da GUI (issue #176).

Decisione del proprietario: **avvisare e lasciar procedere**, non bloccare. Questi test
esercitano la logica pura in `gui_utils` — niente Tk, niente display — perche' e' li' che
sta la decisione; il cablaggio nelle singole finestre e' verificato a parte.
"""

from xtrader_bridge import gui_utils


def test_avviso_solo_col_bridge_attivo():
    """Il caso base nelle due direzioni. La seconda meta' conta quanto la prima: un avviso
    che comparisse SEMPRE verrebbe ignorato sempre, e con lui quello vero."""
    attivo = gui_utils.running_edit_notice(lambda: True)
    assert attivo, "col bridge attivo l'avviso deve esserci"
    assert "AVVIA" in attivo, attivo          # dice COSA fare, non solo che c'e' un problema

    assert gui_utils.running_edit_notice(lambda: False) == ""


def test_e_fail_safe_su_una_sonda_difettosa():
    """Una sonda di stato rotta non deve ne' impedire il salvataggio ne' inventare un
    avviso. Tre modi di essere difettosa, tutti trattati come «bridge fermo»."""
    def esplode():
        raise RuntimeError("sonda rotta (simulata)")

    assert gui_utils.running_edit_notice(esplode) == ""
    assert gui_utils.running_edit_notice(None) == ""
    assert gui_utils.running_edit_notice("non chiamabile") == ""


def test_with_running_notice_ACCODA_e_non_sostituisce():
    """L'esito del salvataggio deve restare la prima cosa che si legge: l'avviso e' il
    contesto, non il messaggio. Se sostituisse, un salvataggio FALLITO col bridge attivo
    direbbe «salvata» — esattamente il contrario del vero."""
    esito = "✅ Profilo «Serie A» salvato."
    con = gui_utils.with_running_notice(esito, lambda: True)

    assert con.startswith(esito), con
    assert "Bridge ATTIVO" in con, con

    # bridge fermo: il messaggio passa INVARIATO, il sito di chiamata non sa nulla di stato
    assert gui_utils.with_running_notice(esito, lambda: False) == esito


def test_with_running_notice_regge_i_messaggi_vuoti():
    """Robustezza sui bordi: nessun separatore penzolante, nessun `None` stampato."""
    assert gui_utils.with_running_notice("", lambda: False) == ""
    assert gui_utils.with_running_notice(None, lambda: False) == ""
    solo_avviso = gui_utils.with_running_notice("", lambda: True)
    assert solo_avviso and not solo_avviso.startswith(" "), repr(solo_avviso)


def test_l_avviso_dice_QUANDO_ha_effetto_non_se_e_stato_salvato():
    """Il testo deve parlare di **quando la modifica ha effetto**, non di *se* e' stata
    salvata — perche' lo stesso avviso viene accodato sia all'esito riuscito sia a quello
    FALLITO (vedi il test qui sotto)."""
    testo = gui_utils.running_edit_notice(lambda: True)
    assert "prossimo" in testo.lower() and "avvia" in testo.lower(), testo


def test_l_avviso_NON_contraddice_un_salvataggio_FALLITO():
    """FAIL-FIRST — difetto reale trovato da Fugu Ultra sulla PR #177.

    Il primo testo diceva «la modifica e' salvata», e veniva accodato **anche** al messaggio
    di errore. Risultato:

        «❌ Salvataggio FALLITO: non salvato.  ⚠️ Bridge ATTIVO: la modifica e' salvata…»

    Una bugia operativa: l'utente legge «salvata» accanto a «FALLITO» e se ne va convinto di
    aver salvato. Il testo deve essere NEUTRO sull'esito, cosi' e' vero in entrambi i casi."""
    fallito = "❌ Salvataggio FALLITO: non salvato (andrebbe perso al riavvio)."
    composto = gui_utils.with_running_notice(fallito, lambda: True)

    assert composto.startswith(fallito), composto
    assert "salvata" not in composto[len(fallito):].lower(), (
        "l'avviso afferma che la modifica e' stata salvata accanto a un errore: " + composto)
