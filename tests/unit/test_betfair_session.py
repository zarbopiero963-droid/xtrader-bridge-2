"""Test hard della sessione Betfair RAM-only (issue #86 PR-P2).

Il sessionToken vive solo in RAM, non viene mai esposto da repr/str ed è
registrato/de-registrato dal redattore globale dei log a set/clear.
"""

import pytest

from xtrader_bridge.betfair import log_safety, session


@pytest.fixture(autouse=True)
def _clean_registry():
    log_safety.clear_secrets()
    yield
    log_safety.clear_secrets()


def test_set_e_clear_token():
    s = session.BetfairSession()
    assert s.is_logged_in is False
    assert s.token is None
    s.set_token("sessione-abc-123")
    assert s.is_logged_in is True
    assert s.token == "sessione-abc-123"
    s.clear()
    assert s.is_logged_in is False
    assert s.token is None


def test_token_vuoto_equivale_a_non_loggati():
    s = session.BetfairSession()
    s.set_token("")
    assert s.is_logged_in is False
    s.set_token(None)
    assert s.is_logged_in is False


def test_repr_e_str_non_espongono_il_token():
    s = session.BetfairSession()
    s.set_token("segretissimo-token-999")
    assert "segretissimo-token-999" not in repr(s)
    assert "segretissimo-token-999" not in str(s)
    assert "logged_in=True" in repr(s)


def test_set_token_registra_per_redazione_clear_de_registra():
    s = session.BetfairSession()
    s.set_token("ram-only-token-xyz")
    # finché loggati, il token è mascherato nei log
    assert "ram-only-token-xyz" not in log_safety.redact("debug: ram-only-token-xyz")
    s.clear()
    # dopo il logout il token non è più registrato (è comunque sparito dalla RAM)
    assert "ram-only-token-xyz" in log_safety.redact("debug: ram-only-token-xyz")


def test_nessun_attributo_extra_oltre_lo_slot():
    # __slots__ impedisce di attaccare per errore il token ad altri attributi.
    s = session.BetfairSession()
    with pytest.raises(AttributeError):
        s.persisted = "x"
