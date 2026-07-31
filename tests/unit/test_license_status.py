"""Test hard dello stato licenza per la UI (#140 PR 2): compute_status + severity + messaggi +
last_seen monotòno. Logica pura, con licenze reali firmate dalla keypair di TEST."""

import pytest
from tests.conftest import LICENSE_TEST_SEED_HEX
from xtrader_bridge import license_status as ls
from xtrader_bridge.licensing import license as lic
from xtrader_bridge.licensing import ed25519

# Seed di TEST, dalla fonte unica (regola 3, rilievo CodeRabbit #209): stesso valore da cui la
# fixture `chiave_pubblica_di_test` deriva la pubblica deployata qui.
_TEST_SEED = bytes.fromhex(LICENSE_TEST_SEED_HEX)
_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_000_000_000
_DAY = 86_400


def _token(hw=_HW, exp=_NOW + 15 * _DAY, name="Mario Rossi"):
    return lic.build_license(_TEST_SEED, name, hw, _NOW, exp)


# Dal 2026-07-31 il modulo porta la chiave pubblica REALE del proprietario (#12 PARTE 0). Questo
# file esercita la logica di licenza con una keypair di TEST, quindi qui la chiave "deployata"
# dev'essere quella di test: senza, si verificherebbero firme che nessun test di questo file può
# produrre. Un `pytestmark` invece di una fixture autouse ripetuta in ogni file (rilievo Sourcery):
# una riga sola, e il comportamento non può divergere fra i file.
pytestmark = pytest.mark.usefixtures("chiave_pubblica_di_test")


# Costante REALE catturata all'IMPORT, prima che il `pytestmark` sostituisca la chiave deployata.
_CHIAVE_DEPLOYATA_REALE = lic.LICENSE_PUBLIC_KEY_HEX


def test_il_contesto_di_test_deploya_la_pubblica_del_seed_di_test():
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



def test_nessun_token_e_not_present():
    st = ls.compute_status(None, _HW, _NOW)
    assert st.valid is False
    assert st.reason == ls.NOT_PRESENT
    assert ls.status_severity(st) == "warn"


def test_token_vuoto_e_not_present():
    assert ls.compute_status("", _HW, _NOW).reason == ls.NOT_PRESENT


def test_licenza_valida():
    st = ls.compute_status(_token(), _HW, _NOW)
    assert st.valid is True
    assert ls.status_severity(st) == "ok"
    msg = ls.status_message(st)
    assert "Mario Rossi" in msg and "15" in msg


def test_licenza_scaduta():
    st = ls.compute_status(_token(exp=_NOW + _DAY), _HW, _NOW + 2 * _DAY)
    assert st.valid is False
    assert st.reason == lic.EXPIRED
    assert ls.status_severity(st) == "error"


def test_hardware_diverso():
    st = ls.compute_status(_token(hw="HW1-AAAA-BBBB-CCCC-DDDD"), _HW, _NOW)
    assert st.reason == lic.WRONG_HARDWARE
    assert ls.status_severity(st) == "error"


def test_anti_rollback_propagato():
    st = ls.compute_status(_token(exp=_NOW + 30 * _DAY), _HW, _NOW, last_seen=_NOW + 20 * _DAY)
    assert st.reason == lic.CLOCK_ROLLBACK


def test_messaggio_per_ogni_reason_non_vuoto():
    for reason in (ls.NOT_PRESENT, lic.EXPIRED, lic.WRONG_HARDWARE,
                   lic.INVALID_SIGNATURE, lic.CLOCK_ROLLBACK, lic.MALFORMED):
        st = lic.LicenseStatus(valid=False, reason=reason, name=None,
                               issued=None, expiry=None, days_left=0)
        assert ls.status_message(st).strip()


def test_next_last_seen_monotono():
    assert ls.next_last_seen(None, 100) == 100          # assente → now
    assert ls.next_last_seen(50, 100) == 100            # prev < now → now
    assert ls.next_last_seen(200, 100) == 200           # prev > now → prev (non torna indietro)
    assert ls.next_last_seen("non-numero", 100) == 100  # malformato → now (fail-safe)
