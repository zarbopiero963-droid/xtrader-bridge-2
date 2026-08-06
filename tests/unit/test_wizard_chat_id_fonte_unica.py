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

    **Perché legge sia `Attribute` sia `Name`** (rilievo GPT-5.5 sulla PR #295, misurato). La
    prima stesura raccoglieva solo `n.func.attr`, cioè le sole chiamate *qualificate*
    `source_manager.is_valid_chat_id(...)`. Ma `from .source_manager import is_valid_chat_id`
    seguito da `is_valid_chat_id(cid)` soddisfa **esattamente lo stesso invariante** — è la
    stessa unica regola — e produce un `ast.Name`: il test sarebbe andato ROSSO su un refactor
    legittimo. Un test strutturale deve vincolare *da dove viene la regola*, non lo stile di
    import con cui la si raggiunge; altrimenti il prossimo che tocca il file lo vede fallire
    senza aver rotto nulla, e la lezione che impara è che il test va aggirato.

    **Perché il nome della chiamata non basta** (secondo rilievo GPT-5.5 sulla #295, ed era
    giusto: il difetto l'aveva introdotto l'allargamento qui sopra). Accettare *qualunque*
    chiamata di nome `is_valid_chat_id` rende il test PERMISSIVO — un helper omonimo definito
    dentro `wizard.py` lo lascerebbe VERDE mentre viola esattamente l'invariante che difende.
    Un falso verde è peggio del falso rosso che si era corretti: il primo tace su un difetto,
    il secondo dà solo fastidio.

    Quindi il test non si ferma al nome: risolve il **simbolo effettivamente chiamato** e
    pretende che sia *lo stesso oggetto* di `source_manager.is_valid_chat_id`. È l'unico
    controllo che distingue «delega alla regola canonica» da «ha una funzione che si chiama
    come lei».
    """
    import ast
    import inspect

    # `unwrap`: se un domani `check_chat` venisse decorata, `getsource` leggerebbe il wrapper
    # invece del corpo vero, e il test tacerebbe. Secondo rilievo GPT-5.5, costo una riga.
    funzione = inspect.unwrap(wizard.check_chat)
    albero = ast.parse(inspect.getsource(funzione).lstrip())

    nomi_chiamati, sorgenti = set(), []
    for n in ast.walk(albero):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Attribute):        # source_manager.is_valid_chat_id(...)
            nomi_chiamati.add(n.func.attr)
            if n.func.attr == "is_valid_chat_id" and isinstance(n.func.value, ast.Name):
                sorgenti.append((n.func.value.id, n.func.attr))
        elif isinstance(n.func, ast.Name):           # is_valid_chat_id(...) importata a nome
            nomi_chiamati.add(n.func.id)
            if n.func.id == "is_valid_chat_id":
                sorgenti.append((None, n.func.id))

    assert "is_valid_chat_id" in nomi_chiamati, (
        "`check_chat` deve chiamare `is_valid_chat_id` di `source_manager` — qualificata o "
        "importata a nome, indifferente — invece di riscrivere la regola"
    )
    assert "isdigit" not in nomi_chiamati, (
        "`str.isdigit()` è Unicode-aware ed è la copia divergente da rimuovere"
    )

    # La parte che chiude il falso verde: il simbolo chiamato deve ESSERE quello canonico.
    atteso = source_manager.is_valid_chat_id
    for qualificatore, attributo in sorgenti:
        radice = wizard if qualificatore is None else getattr(wizard, qualificatore, None)
        assert radice is not None, (
            f"`check_chat` chiama `{qualificatore}.{attributo}` ma `wizard.{qualificatore}` "
            f"non esiste: la regola non arriva da nessuna fonte risolvibile"
        )
        risolto = getattr(radice, attributo, None)
        assert risolto is atteso, (
            f"`check_chat` chiama un `{attributo}` che NON è "
            f"`source_manager.is_valid_chat_id` (risolto: {risolto!r}). Una funzione che si "
            f"chiama come la regola canonica non è la regola canonica: è di nuovo una seconda "
            f"copia, cioè il difetto che questa PR rimuove."
        )
