"""Il Wizard validava il Chat ID con una COPIA a mano della regola, e la copia era divergente.

Trovato dal grep della classe durante la PR-Q (#294), che cercava `str.isdigit()` — e non è un
secondo caso di B17: è **Regola 3**. La regola canonica esiste già ed è
`source_manager.is_valid_chat_id` (`-?[0-9]+`), usata da `settings_controller`,
`validate_sources` e dall'assistente. Il Wizard se ne era scritta una propria:

    cid.lstrip("-").isdigit()

`str.isdigit()` è Unicode-aware, quindi le due **divergono su sei casi misurati**, sempre nello
stesso verso — il Wizard accetta ciò che il resto dell'app rifiuta:

    valore        is_valid_chat_id   regola del Wizard
    '١٢٣'         False              True
    '-١٢٣'        False              True
    '١٢٣456'      False              True
    '12٣'         False              True
    '１２３'        False              True
    '१२३'         False              True

**La conseguenza è una contraddizione fra diagnostiche**, non un varco di sicurezza. Il Wizard
direbbe «Chat ID valido, procedo»; poi `validate_sources` blocca la stessa sorgente con
*«chat_id non numerico … usa l'ID numerico Telegram»*. L'utente riceve due risposte opposte
sullo stesso valore, dallo stesso programma.

**Regola 5 — perimetro dichiarato.** Il filtro `chat_id` di runtime è area che l'audit ha
dichiarato sana e questa patch **non lo tocca**: cambia solo il controllo di FORMA del Wizard,
che precede la sonda a Telegram, e lo fa **rimuovendo una copia** invece di riscrivere una
regola. La regola resta una sola, e resta quella già collaudata.
"""

import pytest

from xtrader_bridge import source_manager, wizard

TOK = "123456789:" + "AB" * 18          # token finto, mai usato: la sonda è iniettata


def _sonda_muta(_token):
    """Sonda che risponde «ok, nessun update»: il test non deve mai toccare la rete."""
    return {"ok": True, "result": []}


# ── Il difetto: le due regole devono dare la STESSA risposta ───────────────────────────────

@pytest.mark.parametrize("cid", [
    "١٢٣",        # arabo-indiane
    "-١٢٣",       # con segno
    "١٢٣456",     # miste
    "12٣",        # miste, una sola cifra non-ASCII
    "１２３",       # fullwidth
    "१२३",        # devanagari
])
def test_il_wizard_non_accetta_un_chat_id_che_il_resto_dell_app_rifiuta(cid):
    """Il cuore: nessuna divergenza fra il controllo del Wizard e la regola canonica.

    Scritto come **confronto fra i due**, non come «il Wizard rifiuta X»: così resta valido se
    un domani la regola canonica cambiasse — è la coerenza a essere l'invariante, non il singolo
    valore.
    """
    assert source_manager.is_valid_chat_id(cid) is False       # premessa, misurata

    res = wizard.check_chat(TOK, cid, probe=_sonda_muta)

    # NON basta `res.ok is False`: con la sonda muta è falso comunque, perché nessun messaggio
    # arriva da quella chat. La prima stesura di questo test asseriva proprio quello ed era
    # VERDE prima della patch — passava per la ragione sbagliata. Ciò che conta è **quale**
    # controllo l'ha respinto, quindi si guarda il messaggio.
    assert res.ok is False
    assert "deve essere numerico" in res.message, (
        f"il Wizard accetta il formato di {cid!r} (respinto solo dalla sonda) mentre "
        f"validate_sources lo blocca: l'utente riceve due risposte opposte sullo stesso "
        f"valore. Messaggio ottenuto: {res.message!r}"
    )


@pytest.mark.parametrize("cid", ["-1001234567890", "123456789", "-42"])
def test_gli_id_veri_continuano_a_passare(cid):
    """La metà che impedisce di «correggere» rendendo il Wizard inutilizzabile: un ID Telegram
    reale — negativo per i canali, positivo per le chat dirette — deve passare come prima."""
    assert source_manager.is_valid_chat_id(cid) is True
    res = wizard.check_chat(TOK, cid, probe=_sonda_muta)
    # Non arriva a `ok=True` perché la sonda non trova messaggi da quella chat: ciò che conta è
    # che NON si fermi al controllo di formato, e lo si distingue dal messaggio.
    assert "deve essere numerico" not in res.message, (
        f"{cid!r} è un ID Telegram valido: non deve essere respinto dal controllo di formato"
    )


@pytest.mark.parametrize("cid", ["", "   ", "abc", "12.3", "+123", "12 3", "-", "@canale"])
def test_i_malformati_restano_respinti(cid):
    """Fail-closed intatto: ciò che veniva respinto prima viene respinto adesso, **e dallo
    stesso controllo** — non per caso dalla sonda."""
    res = wizard.check_chat(TOK, cid, probe=_sonda_muta)

    assert res.ok is False
    assert ("deve essere numerico" in res.message) or ("Inserisci il Chat ID" in res.message)


# ── Regola 3: una regola sola, non due che si somigliano ───────────────────────────────────

def test_il_wizard_delega_e_non_reimplementa():
    """La correzione giusta non è «riscrivere il controllo del Wizard in ASCII»: sarebbe una
    seconda copia corretta oggi e divergente domani — cioè lo stesso difetto un giro dopo.

    Il Wizard deve **delegare** alla regola che esiste. Il test guarda il sorgente perché ciò
    che si pretende è *da dove viene la regola*: due implementazioni corrette darebbero lo
    stesso risultato e un test comportamentale sarebbe verde su entrambe.
    """
    import ast
    import inspect

    albero = ast.parse(inspect.getsource(wizard.check_chat).lstrip())

    chiamate = {n.func.attr for n in ast.walk(albero)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

    assert "is_valid_chat_id" in chiamate, (
        "`check_chat` deve chiamare `source_manager.is_valid_chat_id`, non riscrivere la regola"
    )
    assert "isdigit" not in chiamate, (
        "`str.isdigit()` è Unicode-aware ed è la copia divergente da rimuovere"
    )
