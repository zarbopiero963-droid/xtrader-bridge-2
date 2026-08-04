"""«🗑 Elimina riga» nel Registro del License Manager.

Richiesta del proprietario (2026-08-04): poter togliere una riga dal registro — righe di prova,
emissioni sbagliate — senza dover editare `licenses.jsonl` a mano.

L'invariante che questo file difende sopra ogni altra: **eliminare una riga non riattiva un
revocato**. La revoca vive in `revoked.jsonl`, uno store separato da `licenses.jsonl`, e la lista
firmata che i bridge scaricano si costruisce da lì. Se un domani qualcuno «semplificasse» facendo
nascere la lista dal registro, questa funzione diventerebbe un modo silenzioso per rimettere
operativi tutti i clienti revocati — lo stesso guasto che la PR-C (#194) ha evitato per un soffio
canonicalizzando i serial. Qui è misurato, non ragionato.
"""

import json
import os

import pytest

from license_manager import registry


def _record(serial, nome="Mario Rossi", hw="HW1-AAAA"):
    return {"serial": serial, "name": nome, "hardware_id": hw,
            "issued": 1_700_000_000, "expiry": 1_800_000_000, "days": 30,
            "token": f"token-di-{serial}", "recorded_at": 1_700_000_000}


@pytest.fixture
def registro(tmp_path):
    """Cartella con tre licenze registrate."""
    d = str(tmp_path)
    for s in ("LIC-AAA", "LIC-BBB", "LIC-CCC"):
        registry.append_record(_record(s), directory=d)
    return d


def _serials(directory):
    return [r["serial"] for r in registry.read_records(directory=directory)]


# ── il comportamento base ────────────────────────────────────────────────────

def test_elimina_solo_la_riga_indicata(registro):
    rimossi = registry.remove_record("LIC-BBB", directory=registro)

    assert rimossi == 1
    assert _serials(registro) == ["LIC-AAA", "LIC-CCC"], "eliminata la riga sbagliata"


def test_serial_inesistente_non_riscrive_nulla(registro):
    """Un serial che non c'è non deve far riscrivere il file: niente scritture inutili su un
    percorso che, a differenza dell'append, tocca TUTTO il registro."""
    percorso = registry.registry_path(registro)
    prima = os.stat(percorso).st_mtime_ns, open(percorso, encoding="utf-8").read()

    assert registry.remove_record("LIC-NON-ESISTE", directory=registro) == 0

    dopo = os.stat(percorso).st_mtime_ns, open(percorso, encoding="utf-8").read()
    assert prima == dopo, "il registro è stato riscritto pur non avendo eliminato nulla"


def test_serial_vuoto_non_elimina_niente(registro):
    """Guardia elementare ma quella che conta: un campo lasciato vuoto nella GUI non deve
    diventare «elimina qualcosa»."""
    for vuoto in ("", "   ", None):
        assert registry.remove_record(vuoto, directory=registro) == 0
    assert len(_serials(registro)) == 3


def test_confronto_normalizzato_come_il_resto_del_registro(registro):
    """`normalize_serial` è la fonte unica del confronto: minuscole e spazi devono trovare
    comunque la riga, altrimenti l'utente copia un serial dalla tabella e «non succede nulla»."""
    assert registry.remove_record("  lic-aaa  ", directory=registro) == 1
    assert "LIC-AAA" not in _serials(registro)


# ── L'INVARIANTE: eliminare non riattiva ────────────────────────────────────

def test_eliminare_la_riga_di_un_revocato_NON_lo_riattiva(registro):
    """Il test più importante del file.

    Si revoca una licenza, si elimina la sua riga dal registro, e si pretende che la lista
    firmata destinata ai bridge contenga ANCORA quel serial. Se un domani la lista nascesse dal
    registro invece che dallo store revoche, questo test diventa rosso — prima che un cliente
    revocato torni operativo in silenzio.
    """
    registry.append_revocation(
        registry.revocation_record(_record("LIC-BBB"), now=1_700_000_100), directory=registro)

    revoche_prima = registry.read_revocations(directory=registro)
    assert registry.is_serial_revoked(revoche_prima, "LIC-BBB")

    registry.remove_record("LIC-BBB", directory=registro)

    revoche_dopo = registry.read_revocations(directory=registro)
    assert registry.is_serial_revoked(revoche_dopo, "LIC-BBB"), (
        "eliminare la riga ha tolto la revoca: un cliente revocato tornerebbe operativo")
    serial_pubblicati = {e.get("serial") for e in registry.revocation_entries(revoche_dopo)}
    assert "LIC-BBB" in serial_pubblicati, (
        "il serial revocato non è più nella lista firmata che i bridge scaricano")


def test_lo_store_revoche_non_viene_toccato_dal_file(registro):
    """Prova diretta sul file, non sull'API: `revoked.jsonl` dev'essere byte-per-byte identico."""
    registry.append_revocation(
        registry.revocation_record(_record("LIC-CCC"), now=1_700_000_100), directory=registro)
    percorso_revoche = registry.revoked_registry_path(registro)
    prima = open(percorso_revoche, "rb").read()

    registry.remove_record("LIC-CCC", directory=registro)

    assert open(percorso_revoche, "rb").read() == prima


# ── integrità del file riscritto ────────────────────────────────────────────

def test_il_registro_riscritto_resta_JSONL_valido(registro):
    """Ogni riga dev'essere un JSON completo con il newline finale: la riscrittura non deve
    lasciare il file in uno stato che `read_records` salta silenziosamente."""
    registry.remove_record("LIC-AAA", directory=registro)

    testo = open(registry.registry_path(registro), encoding="utf-8").read()
    assert testo.endswith("\n"), "manca il newline finale: il prossimo append si concatenerebbe"
    for riga in testo.splitlines():
        json.loads(riga)          # solleva se una riga è troncata/malformata

    registry.append_record(_record("LIC-DDD"), directory=registro)
    assert _serials(registro) == ["LIC-BBB", "LIC-CCC", "LIC-DDD"], (
        "dopo l'eliminazione un append successivo non si aggancia correttamente")


def test_i_campi_delle_righe_tenute_sono_intatti(registro):
    """Riscrivere il file non deve alterare ciò che resta — token incluso, che serve a
    «Ri-mostra token»."""
    atteso = registry.find_by_serial(registry.read_records(directory=registro), "LIC-CCC")

    registry.remove_record("LIC-AAA", directory=registro)

    assert registry.find_by_serial(registry.read_records(directory=registro), "LIC-CCC") == atteso


def test_elimina_tutte_le_occorrenze_di_un_serial_duplicato(tmp_path):
    """Il registro è append-only: lo stesso serial può comparire due volte (un ri-append dopo un
    ripristino di backup). «Elimina» deve toglierle tutte, o la riga resterebbe nell'elenco dopo
    che l'utente ha appena confermato di volerla eliminare."""
    d = str(tmp_path)
    registry.append_record(_record("LIC-DUP"), directory=d)
    registry.append_record(_record("LIC-DUP"), directory=d)
    registry.append_record(_record("LIC-ALTRO"), directory=d)

    assert registry.remove_record("LIC-DUP", directory=d) == 2
    assert _serials(d) == ["LIC-ALTRO"]


# ── il gate di conferma nella GUI ───────────────────────────────────────────
#
# Nasce da un errore commesso scrivendo questa funzionalità: la prima versione chiamava
# `_evaluate_delete` come «anteprima» per decidere se chiedere conferma — ma quella versione
# eliminava già, quindi la domanda arrivava a cancellazione avvenuta. Il gate ora vive DENTRO
# `_evaluate_delete`, così nessun chiamante può cancellare senza passarci.

class _AppFinta:
    """Il minimo per esercitare `_evaluate_delete` senza costruire la finestra Tk."""

    def __init__(self, directory):
        self._key_dir = directory

    _read_records = staticmethod(
        lambda directory=None: registry.read_records(directory=directory))
    _read_revocations = staticmethod(
        lambda directory=None: registry.read_revocations(directory=directory))
    _auto_backup_safe = staticmethod(lambda: None)


def _app(directory):
    """Aggancia i metodi REALI al doppio: `_evaluate_delete` e il seam che usa per leggere le
    revoche. Legarli entrambi (invece di reimplementare il secondo) è ciò che ha fatto diventare
    rosso questo file quando `_evaluate_delete` è passato a `_revoked_serials(strict=True)` —
    il test doveva accorgersene, e se ne è accorto."""
    from license_manager.gui import LicenseManagerApp
    finta = _AppFinta(directory)
    finta._evaluate_delete = LicenseManagerApp._evaluate_delete.__get__(finta)
    finta._revoked_serials = LicenseManagerApp._revoked_serials.__get__(finta)
    return finta


def test_senza_conferma_NON_elimina_e_chiede(registro):
    app = _app(registro)

    esito = app._evaluate_delete("LIC-AAA")

    assert esito["needs_confirm"] is True and esito["accepted"] is False
    assert _serials(registro) == ["LIC-AAA", "LIC-BBB", "LIC-CCC"], (
        "ha eliminato pur non avendo ricevuto conferma")


def test_con_conferma_elimina(registro):
    app = _app(registro)

    esito = app._evaluate_delete("LIC-AAA", conferma=True)

    assert esito["accepted"] is True
    assert "LIC-AAA" not in _serials(registro)


def test_la_richiesta_su_un_REVOCATO_dice_che_la_revoca_RESTA(registro):
    """Il messaggio deve dire due cose insieme: che non si riattiva, e che sparisce dalla vista.
    Solo la prima tranquillizzerebbe; solo la seconda spaventerebbe senza spiegare."""
    registry.append_revocation(
        registry.revocation_record(_record("LIC-BBB"), now=1_700_000_100), directory=registro)
    app = _app(registro)

    esito = app._evaluate_delete("LIC-BBB")

    assert esito["needs_confirm"] is True and esito.get("revoked") is True
    testo = esito["message"].upper()
    assert "NON LA RIATTIVA" in testo
    assert "NON LA VEDRAI" in testo


def test_serial_inesistente_non_chiede_conferma(registro):
    """Non si apre un dialogo di conferma per un'azione che non farebbe nulla."""
    esito = _app(registro)._evaluate_delete("LIC-FANTASMA")

    assert esito["needs_confirm"] is False and esito["accepted"] is False


# ── il riquadro del token vive FUORI dalle schede ───────────────────────────
#
# Segnalazione del proprietario (2026-08-04): «rinnovo, ma sul bridge serve la chiave lunga
# generata solo quando si crea l'utente, non c'è modo». La funzione c'era e funzionava — il
# token veniva scritto nel riquadro della scheda «Emetti» mentre il pulsante che lo genera sta
# nel «Registro», e l'app non cambiava scheda. Difetto di VISIBILITÀ, non di logica: la stessa
# forma della revoca invisibile (#235).

def test_il_riquadro_token_non_e_costruito_dentro_una_scheda():
    """Guardia sul sorgente: `_token_box` dev'essere creato in `_build_barra_token` (fuori dalle
    schede), non in `_build_scheda_emetti`.

    Sul sorgente e non a runtime perché è una proprietà di COSTRUZIONE: a finestra costruita un
    widget «dentro Emetti» e uno «fuori» hanno entrambi un master valido, e la differenza che
    conta — resta visibile cambiando scheda? — non si legge da un attributo.
    """
    import ast
    import inspect

    from license_manager import gui as gui_mod

    sorgente = inspect.getsource(gui_mod)
    albero = ast.parse(sorgente)
    creato_in = set()
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for interno in ast.walk(nodo):
            if (isinstance(interno, ast.Attribute) and interno.attr == "_token_box"
                    and isinstance(interno.ctx, ast.Store)):
                creato_in.add(nodo.name)

    assert "_build_barra_token" in creato_in, (
        "`_token_box` non è più costruito in `_build_barra_token`")
    assert "_build_scheda_emetti" not in creato_in, (
        "`_token_box` è tornato dentro la scheda Emetti: rinnovando dal Registro il token "
        "sarebbe di nuovo invisibile")


def test_i_messaggi_di_rinnovo_e_ri_mostra_dicono_DOVE_e_il_token():
    """Un messaggio che dice «inviala all'utente» senza dire dove sia la chiave è ciò che ha
    fatto concludere al proprietario che il rinnovo non funzionasse."""
    import inspect

    from license_manager import gui as gui_mod

    sorgente = inspect.getsource(gui_mod)
    assert sorgente.count("riquadro in fondo alla finestra") >= 2, (
        "i messaggi di emissione/rinnovo e ri-mostra devono indicare dove trovare il token")


# ── percorsi di FALLIMENTO ──────────────────────────────────────────────────
#
# Rilievi di CodeRabbit e Fugu Ultra sulla PR #246: la riscrittura atomica è la parte più
# rischiosa del codice nuovo, ed era coperta solo sui cammini felici.

def test_se_la_riscrittura_fallisce_il_registro_resta_INTATTO(registro, monkeypatch):
    """`os.replace` che fallisce (registro lockato da un'altra istanza su Windows) non deve
    lasciare né un file mezzo riscritto né il temporaneo in giro."""
    percorso = registry.registry_path(registro)
    with open(percorso, "rb") as f:
        prima = f.read()

    def replace_ko(*_a, **_k):
        raise OSError("registro lockato")

    monkeypatch.setattr(registry.os, "replace", replace_ko)

    with pytest.raises(OSError):
        registry.remove_record("LIC-BBB", directory=registro)

    with open(percorso, "rb") as f:
        assert f.read() == prima, "il registro è stato alterato da una riscrittura fallita"
    residui = [n for n in os.listdir(registro) if n.startswith(".registry_")]
    assert residui == [], f"temporaneo non rimosso: {residui}"


def test_una_riga_ILLEGGIBILE_di_un_altro_serial_non_viene_persa(registro):
    """Rilievo di Fable 5 e CodeRabbit, indipendenti.

    Il registro contiene l'**unica** copia del token di ogni licenza. Ricostruire il file dai soli
    record che `read_records` sa leggere avrebbe scartato per sempre le righe troncate — comprese
    quelle di serial che l'utente non ha chiesto di toccare, e che finché restano su disco sono
    ancora recuperabili a mano.
    """
    percorso = registry.registry_path(registro)
    with open(percorso, "a", encoding="utf-8") as f:
        f.write('{"serial": "LIC-TRONCA", "token": "meta-riga\n')   # JSON troncato di proposito

    registry.remove_record("LIC-AAA", directory=registro)

    testo = open(percorso, encoding="utf-8").read()
    assert "LIC-TRONCA" in testo, "la riga troncata di un ALTRO serial è stata distrutta"
    assert "LIC-AAA" not in testo, "la riga richiesta non è stata eliminata"


def test_revoche_ILLEGGIBILI_non_fanno_sparire_il_pulsante(registro):
    """Rilievo CodeRabbit: `_read_revocations` può sollevare (store lockato — frequente su
    Windows). Senza guardia l'eccezione usciva da `_evaluate_delete` e da `_on_delete`, che non ha
    handler: il pulsante non faceva **nulla, e senza messaggio**.

    E il testo non deve ricadere su «non revocata»: sarebbe una rassicurazione su uno stato che
    non è stato letto.
    """
    app = _app(registro)

    def leggi_ko(**_k):
        raise OSError("revoked.jsonl lockato")

    app._read_revocations = leggi_ko

    esito = app._evaluate_delete("LIC-AAA")      # non deve sollevare

    assert esito["needs_confirm"] is True
    assert esito["revoked"] is None, "«non lo so» non deve diventare «non revocata»"
    assert "non ho potuto leggere" in esito["message"].lower()
    assert _serials(registro) == ["LIC-AAA", "LIC-BBB", "LIC-CCC"], "ha eliminato senza conferma"


# ── i due bloccanti di Fugu Ultra ───────────────────────────────────────────

def test_i_byte_non_UTF8_di_un_ALTRO_serial_restano_IDENTICI(registro):
    """Rilievo bloccante di Fugu Ultra, riprodotto prima della correzione.

    La prima versione del filtro leggeva il file con `errors="replace"`: i byte non-UTF-8 di
    una riga di un ALTRO serial diventavano `U+FFFD` in lettura e venivano **riscritti così**.
    Misurato: `Nom\\xe8` → `Nom\\xef\\xbf\\xbd`. La correzione che doveva impedire la perdita di
    righe altrui le corrompeva in un altro modo — e il registro contiene l'unica copia del token.

    Il test precedente non lo prendeva perché usava JSON ASCII: la riga era «illeggibile» come
    JSON ma perfettamente decodificabile come UTF-8.
    """
    percorso = registry.registry_path(registro)
    riga_ostile = b'{"serial": "LIC-BYTE", "name": "Nom\xe8", "token": "t2"}\n'
    with open(percorso, "ab") as f:
        f.write(riga_ostile)

    registry.remove_record("LIC-AAA", directory=registro)

    with open(percorso, "rb") as f:
        dopo = f.read()
    assert riga_ostile.strip() in dopo, "i byte non-UTF-8 di un altro serial sono stati alterati"
    assert b"\xef\xbf\xbd" not in dopo, "sostituito con U+FFFD: corruzione permanente"
    assert b"LIC-AAA" not in dopo, "la riga richiesta non è stata eliminata"


def test_un_append_CONCORRENTE_fa_RIFIUTARE_invece_di_perdere_il_record(registro, monkeypatch):
    """Secondo bloccante di Fugu Ultra: `_WRITE_LOCK` serializza i thread, non i processi.

    Per un **append** due istanze si interlacciano al peggio; per una riscrittura dell'INTERO
    file un append concorrente andrebbe **perso del tutto** — un fallimento peggiore, introdotto
    da questa funzione. Qui si simula l'altra istanza che registra una licenza mentre
    l'eliminazione è in corso: deve **rifiutare**, non sovrascrivere.

    Non è un lock inter-processo (quello è la #185): è un controllo di versione. Perdere una
    licenza appena emessa in silenzio è il danno peggiore; rifiutare è rumoroso e reversibile.
    """
    vero_mkstemp = registry.tempfile.mkstemp

    def mkstemp_con_intruso(*a, **k):
        # L'«altra istanza» appende DOPO che remove_record ha già letto il file.
        # Si scrive il file DIRETTAMENTE e non via `append_record`: quest'ultima prenderebbe
        # lo stesso `_WRITE_LOCK` — non rientrante — che `remove_record` sta già tenendo, e il
        # test andrebbe in deadlock invece di simulare alcunché. Un altro PROCESSO quel lock
        # non ce l'ha: scrivere sul file è esattamente ciò che farebbe.
        with open(registry.registry_path(registro), "a", encoding="utf-8") as f:
            f.write(json.dumps(_record("LIC-INTRUSO")) + "\n")
        return vero_mkstemp(*a, **k)

    monkeypatch.setattr(registry.tempfile, "mkstemp", mkstemp_con_intruso)

    with pytest.raises(registry.ConcurrentModification):
        registry.remove_record("LIC-AAA", directory=registro)

    serial = _serials(registro)
    assert "LIC-INTRUSO" in serial, "il record dell'altra istanza è stato perso"
    assert "LIC-AAA" in serial, "eliminata pur avendo rifiutato l'operazione"
    residui = [n for n in os.listdir(registro) if n.startswith(".registry_")]
    assert residui == [], f"temporaneo non rimosso dopo il rifiuto: {residui}"


def test_la_GUI_riporta_il_rifiuto_invece_di_esplodere(registro, monkeypatch):
    """Regola 2-bis: ho introdotto un'eccezione nuova, quindi vado a vedere CHI chiama.

    `_evaluate_delete` catturava solo `OSError`, e `ConcurrentModification` è una `RuntimeError`:
    sarebbe sfuggita fino a `_on_delete`, che non ha handler → il pulsante non avrebbe fatto
    **nulla e senza messaggio**. Cioè avrei ricreato, con una classe diversa, il difetto che
    CodeRabbit aveva appena fatto correggere due commit fa.
    """
    def rifiuta(*_a, **_k):
        raise registry.ConcurrentModification("il registro è cambiato durante l'eliminazione")

    monkeypatch.setattr(registry, "remove_record", rifiuta)

    esito = _app(registro)._evaluate_delete("LIC-AAA", conferma=True)   # non deve sollevare

    assert esito["accepted"] is False
    assert "cambiato" in esito["message"]
    assert _serials(registro) == ["LIC-AAA", "LIC-BBB", "LIC-CCC"]
