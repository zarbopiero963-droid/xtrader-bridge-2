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
    from license_manager.gui import LicenseManagerApp
    finta = _AppFinta(directory)
    finta._evaluate_delete = LicenseManagerApp._evaluate_delete.__get__(finta)
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
