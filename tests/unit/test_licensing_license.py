"""Test hard della verifica licenza (#140 PR 1): firma + hardware + scadenza + anti-rollback.

Round-trip col generatore reale (`build_license`) e matrice completa dei fallimenti, tutti
**fail-closed**. La chiave usata è la keypair di **TEST** (seed noto).

Fino al 2026-07-31 quella pubblica ERA anche il default del modulo, quindi i round-trip
esercitavano il default del bridge senza dire nulla. Dal momento in cui il proprietario ha messo
la propria chiave **reale** (#12 PARTE 0) non è più così: la fixture autouse di questo file
dichiara esplicitamente che qui la chiave deployata è quella di test. Il default reale resta
sorvegliato da `test_flag_placeholder_coerente_con_la_chiave_di_test`, che legge le costanti
catturate all'import e quindi NON vede la sostituzione.
"""

import base64
import json
import os

import pytest

from xtrader_bridge.licensing import license as lic
from xtrader_bridge.licensing import ed25519
from xtrader_bridge.licensing.hwid import NO_HARDWARE_ID

# Seed di TEST (NON è la chiave reale del proprietario) → la sua pubblica è il placeholder
# committato in `license.LICENSE_PUBLIC_KEY_HEX`. Il round-trip usa la coppia coerente.
_TEST_SEED = bytes.fromhex("a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00")

# Costanti REALI del modulo, catturate all'IMPORT — cioè prima che la fixture autouse di questo
# file sostituisca la chiave deployata con quella di TEST. Servono alla guardia di coerenza
# chiave↔flag, che deve sorvegliare ciò che verrà distribuito, non ciò che i test simulano.
_CHIAVE_DEPLOYATA_REALE = lic.LICENSE_PUBLIC_KEY_HEX
_FLAG_PLACEHOLDER_REALE = lic.LICENSE_PUBLIC_KEY_IS_PLACEHOLDER

_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_000_000_000
_DAY = 86_400


def _valid_token(hw=_HW, iss=_NOW, exp=_NOW + 15 * _DAY, name="Mario Rossi", seed=_TEST_SEED):
    return lic.build_license(seed, name, hw, iss, exp)


# Dal 2026-07-31 il modulo porta la chiave pubblica REALE del proprietario (#12 PARTE 0). Questo
# file esercita la logica di licenza con una keypair di TEST, quindi qui la chiave "deployata"
# dev'essere quella di test: senza, si verificherebbero firme che nessun test di questo file può
# produrre. Un `pytestmark` invece di una fixture autouse ripetuta in ogni file (rilievo Sourcery):
# una riga sola, e il comportamento non può divergere fra i file.
pytestmark = pytest.mark.usefixtures("chiave_pubblica_di_test")


def test_la_fixture_deploya_davvero_la_pubblica_del_seed_di_test():
    # Prima del 2026-07-31 questa guardia verificava che il PLACEHOLDER del modulo combaciasse col
    # seed di test. Quel legame non esiste più: il modulo porta la chiave reale del proprietario.
    #
    # Il test resta, con lo scopo cambiato e dichiarato: verifica che il contesto di test abbia
    # davvero deployato la pubblica del seed di TEST. Senza, tutti i round-trip di questo file
    # fallirebbero con `INVALID_SIGNATURE` e la causa vera — «il `pytestmark` non ha agito» —
    # sarebbe sepolta sotto venti fallimenti identici.
    pub_di_test = ed25519.public_key(_TEST_SEED).hex()
    assert lic.LICENSE_PUBLIC_KEY_HEX == pub_di_test

    # Seconda asserzione (rilievo Sourcery): senza, la guardia diventerebbe cieca il giorno in cui
    # qualcuno riportasse per errore la chiave REALE al valore di test — passerebbe anche senza
    # alcuna sostituzione, cioè proprio nel caso peggiore.
    assert _CHIAVE_DEPLOYATA_REALE != pub_di_test, (
        "la chiave deployata REALE coincide con quella di TEST: il bridge accetterebbe licenze "
        "firmate col seed noto a chiunque legga i test")



def test_licenza_valida_round_trip():
    st = lic.verify_license(_valid_token(), _HW, now=_NOW)
    assert st.valid is True
    assert st.reason == lic.VALID
    assert st.name == "Mario Rossi"
    assert st.expiry == _NOW + 15 * _DAY
    assert st.days_left == 15


def test_giorni_rimasti_si_riducono_col_tempo():
    token = _valid_token(exp=_NOW + 10 * _DAY)
    st = lic.verify_license(token, _HW, now=_NOW + 3 * _DAY)
    assert st.valid is True
    assert st.days_left == 7


def test_hardware_sbagliato_rifiutato():
    st = lic.verify_license(_valid_token(hw="HW1-AAAA-BBBB-CCCC-DDDD"), _HW, now=_NOW)
    assert st.valid is False
    assert st.reason == lic.WRONG_HARDWARE


def test_licenza_scaduta_rifiutata():
    token = _valid_token(exp=_NOW + 5 * _DAY)
    st = lic.verify_license(token, _HW, now=_NOW + 6 * _DAY)
    assert st.valid is False
    assert st.reason == lic.EXPIRED
    assert st.days_left == 0


def test_scadenza_esatta_ancora_valida():
    token = _valid_token(exp=_NOW + 5 * _DAY)
    st = lic.verify_license(token, _HW, now=_NOW + 5 * _DAY)   # now == exp
    assert st.valid is True


def test_anti_rollback_orologio_indietro_rifiutato():
    token = _valid_token(exp=_NOW + 30 * _DAY)
    # last_seen molto avanti rispetto a now → orologio spostato indietro per estendere la licenza.
    st = lic.verify_license(token, _HW, now=_NOW, last_seen=_NOW + 20 * _DAY)
    assert st.valid is False
    assert st.reason == lic.CLOCK_ROLLBACK


def test_anti_rollback_tolleranza_piccolo_skew():
    token = _valid_token(exp=_NOW + 30 * _DAY)
    # now leggermente indietro rispetto a last_seen ma entro la tolleranza NTP → resta valida.
    st = lic.verify_license(token, _HW, now=_NOW, last_seen=_NOW + 3600)
    assert st.valid is True


def test_last_seen_none_non_attiva_anti_rollback():
    st = lic.verify_license(_valid_token(), _HW, now=_NOW, last_seen=None)
    assert st.valid is True


def test_firma_non_valida_seed_diverso():
    # Licenza firmata con un seed che NON corrisponde alla chiave pubblica del bridge.
    other = os.urandom(32)
    token = lic.build_license(other, "Tizio", _HW, _NOW, _NOW + 15 * _DAY)
    st = lic.verify_license(token, _HW, now=_NOW)
    assert st.valid is False
    assert st.reason == lic.INVALID_SIGNATURE


def test_payload_manomesso_rifiutato():
    token = _valid_token()
    payload_part, sig_part = token.split(".", 1)
    raw = bytearray(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))
    raw[10] ^= 0x01   # altera un byte del payload → la firma non combacia più
    tampered = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode() + "." + sig_part
    st = lic.verify_license(tampered, _HW, now=_NOW)
    assert st.valid is False
    assert st.reason in (lic.INVALID_SIGNATURE, lic.MALFORMED)


@pytest.mark.parametrize("token", ["", "senza-punto", "a.b", "!!!.???", "."])
def test_token_malformato_rifiutato(token):
    st = lic.verify_license(token, _HW, now=_NOW)
    assert st.valid is False
    assert st.reason == lic.MALFORMED


def test_versione_formato_sbagliata_rifiutata():
    # Payload validamente firmato ma con versione sconosciuta → MALFORMED (fail-closed).
    obj = {"v": 999, "name": "X", "hw": _HW, "iss": _NOW, "exp": _NOW + _DAY}
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    sig = ed25519.sign(_TEST_SEED, payload)
    token = (base64.urlsafe_b64encode(payload).rstrip(b"=").decode() + "."
             + base64.urlsafe_b64encode(sig).rstrip(b"=").decode())
    st = lic.verify_license(token, _HW, now=_NOW)
    assert st.valid is False
    assert st.reason == lic.MALFORMED


def test_macchina_non_identificabile_rifiutata():
    # Fail-closed (review Fable/Fugu #143): se l'HWID di QUESTA macchina è la sentinella
    # (nessuna sorgente), nessuna licenza è accettabile — nemmeno una firmata correttamente.
    token = _valid_token(hw=NO_HARDWARE_ID)
    st = lic.verify_license(token, NO_HARDWARE_ID, now=_NOW)
    assert st.valid is False
    assert st.reason == lic.WRONG_HARDWARE


def test_licenza_legata_a_impronta_nulla_rifiutata():
    # Anche se la macchina reale avesse un HWID valido, una licenza EMESSA per la sentinella non
    # deve mai combaciare (sarebbe universale).
    token = _valid_token(hw=NO_HARDWARE_ID)
    st = lic.verify_license(token, _HW, now=_NOW)
    assert st.valid is False
    assert st.reason == lic.WRONG_HARDWARE


def test_hw_vuoto_nel_payload_rifiutato():
    # Hardening (review Fable/Fugu #143): una licenza emessa per hw="" non deve mai combaciare,
    # nemmeno verificata contro hardware_id="" — `is_identifiable` chiude il caso vuoto.
    token = _valid_token(hw="")
    st = lic.verify_license(token, "", now=_NOW)
    assert st.valid is False
    assert st.reason == lic.WRONG_HARDWARE


def test_hardware_id_macchina_vuoto_rifiutato():
    # Anche se la licenza ha un hw valido, un `hardware_id` della macchina vuoto è non-identificabile.
    st = lic.verify_license(_valid_token(), "", now=_NOW)
    assert st.valid is False
    assert st.reason == lic.WRONG_HARDWARE


def test_flag_placeholder_coerente_con_la_chiave_di_test():
    # Guardia deliberata (review #143): finché la chiave è il placeholder di TEST, il flag è True.
    # Sostituendo la chiave con quella reale, il proprietario DEVE portarlo a False → questo test
    # lo costringe a un'azione consapevole (non uno swap silenzioso).
    #
    # Si legge la costante CATTURATA ALL'IMPORT, non `lic.LICENSE_PUBLIC_KEY_HEX`: la fixture
    # autouse di questo file sostituisce quel valore con la pubblica di TEST, e leggerlo qui
    # renderebbe la guardia cieca — direbbe sempre «è la chiave di test», che è il contrario di
    # ciò che deve sorvegliare. Dal 2026-07-31 il valore reale è la chiave del proprietario.
    is_test_key = (_CHIAVE_DEPLOYATA_REALE == ed25519.public_key(_TEST_SEED).hex())
    assert _FLAG_PLACEHOLDER_REALE is is_test_key


def test_build_license_struttura_token():
    # Copertura esplicita del generatore (gap segnalato da GLM): due parti base64url separate da
    # un punto, entrambe non vuote, e il round-trip verifica.
    token = lic.build_license(_TEST_SEED, "Anna Bianchi", _HW, _NOW, _NOW + _DAY)
    assert token.count(".") == 1
    part_payload, part_sig = token.split(".")
    assert part_payload and part_sig
    assert "=" not in token                      # base64url senza padding
    assert lic.verify_license(token, _HW, now=_NOW).valid is True


def test_chiave_pubblica_esplicita_override():
    # Verifica con una chiave pubblica passata esplicitamente (usata in futuro/nei test).
    seed = os.urandom(32)
    pub_hex = ed25519.public_key(seed).hex()
    token = lic.build_license(seed, "Y", _HW, _NOW, _NOW + _DAY)
    st = lic.verify_license(token, _HW, now=_NOW, public_key_hex=pub_hex)
    assert st.valid is True
