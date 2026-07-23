"""Test hard dello stato licenza per la UI (#140 PR 2): compute_status + severity + messaggi +
last_seen monotòno. Logica pura, con licenze reali firmate dalla keypair di TEST."""

from xtrader_bridge import license_status as ls
from xtrader_bridge.licensing import license as lic
from xtrader_bridge.licensing import ed25519

_TEST_SEED = bytes.fromhex("a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00")
_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_000_000_000
_DAY = 86_400


def _token(hw=_HW, exp=_NOW + 15 * _DAY, name="Mario Rossi"):
    return lic.build_license(_TEST_SEED, name, hw, _NOW, exp)


def test_placeholder_coerente():
    # la keypair di TEST corrisponde al placeholder → i token di test verificano col default
    assert ed25519.public_key(_TEST_SEED).hex() == lic.LICENSE_PUBLIC_KEY_HEX


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
