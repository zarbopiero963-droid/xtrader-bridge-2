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


# ── #184 LOW: pulizia della sessione su errore di scadenza ────────────────────

@pytest.mark.parametrize("code", [
    "INVALID_SESSION_INFORMATION", "INVALID_SESSION_TOKEN", "NO_SESSION", "SESSION_EXPIRED",
    "invalid_session_information", "  No_Session  ",        # case/spazi tollerati
])
def test_is_session_expired_error_riconosce_i_codici_di_scadenza(code):
    assert session.is_session_expired_error(code) is True


@pytest.mark.parametrize("code", [
    "TOO_MUCH_DATA", "INVALID_APP_KEY", "", None, 0, "INVALID_SESSION",  # parziale ≠ scadenza
])
def test_is_session_expired_error_ignora_gli_altri(code):
    assert session.is_session_expired_error(code) is False


def test_clear_if_expired_slogga_solo_sui_codici_di_scadenza():
    s = session.BetfairSession()
    s.set_token("tok-vivo")
    # codice di scadenza → slogga (is_logged_in torna False) e ritorna True
    assert s.clear_if_expired("INVALID_SESSION_INFORMATION") is True
    assert s.is_logged_in is False
    assert s.token is None


def test_clear_if_expired_non_slogga_su_errore_generico():
    s = session.BetfairSession()
    s.set_token("tok-vivo")
    # un errore NON di scadenza non deve sloggare l'utente (resta connesso)
    assert s.clear_if_expired("TOO_MUCH_DATA") is False
    assert s.is_logged_in is True
    assert s.token == "tok-vivo"
    assert s.clear_if_expired(None) is False
    assert s.is_logged_in is True


def test_clear_if_expired_de_registra_il_token_dai_log():
    s = session.BetfairSession()
    s.set_token("tok-da-redigere-789")
    assert "tok-da-redigere-789" not in log_safety.redact("x tok-da-redigere-789")
    assert s.clear_if_expired("NO_SESSION") is True
    # dopo lo slog su scadenza il token non è più mascherato (sparito dalla RAM e dal registro)
    assert "tok-da-redigere-789" in log_safety.redact("x tok-da-redigere-789")
