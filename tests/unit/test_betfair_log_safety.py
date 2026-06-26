"""Test hard della redazione dei log Betfair (issue #86 PR-P2).

Esercita le funzioni reali di `xtrader_bridge.betfair.log_safety`: nessun header
sensibile, sessionToken o segreto registrato deve sopravvivere nel log.
"""

import logging

import pytest

from xtrader_bridge.betfair import log_safety


@pytest.fixture(autouse=True)
def _clean_registry():
    # Il registro dei segreti è globale: ripulirlo prima/dopo ogni test.
    log_safety.clear_secrets()
    yield
    log_safety.clear_secrets()


# ── redact: header sensibili e sessionToken ───────────────────────────────────

def test_redact_maschera_header_x_authentication_e_application():
    txt = "headers={'X-Authentication': 'ABC123sessione', 'X-Application': 'delayedKEY'}"
    out = log_safety.redact(txt)
    assert "ABC123sessione" not in out
    assert "delayedKEY" not in out
    assert out.count("[REDACTED]") == 2


def test_redact_maschera_session_token_in_json_e_querystring():
    assert "tok-xyz-987" not in log_safety.redact('{"sessionToken": "tok-xyz-987"}')
    assert "tok-xyz-987" not in log_safety.redact("?session_token=tok-xyz-987&x=1")


def test_redact_input_non_stringa_non_crasha():
    assert log_safety.redact(None) == ""
    assert log_safety.redact(12345) == "12345"


# ── registro segreti esatti ───────────────────────────────────────────────────

def test_segreto_registrato_viene_mascherato_ovunque():
    assert log_safety.register_secret("SuperSecretAppKey") is True
    out = log_safety.redact("login con app key SuperSecretAppKey ok")
    assert "SuperSecretAppKey" not in out
    assert "[REDACTED]" in out


def test_segreto_troppo_corto_o_vuoto_non_registrato():
    assert log_safety.register_secret("ab") is False     # < 4 char
    assert log_safety.register_secret("") is False
    assert log_safety.register_secret(None) is False
    # "ab" non viene mascherato (resta nel testo)
    assert "ab" in log_safety.redact("tavolo ab")


def test_unregister_segreto_smette_di_mascherare():
    log_safety.register_secret("tokenInRam")
    assert "tokenInRam" not in log_safety.redact("x tokenInRam y")
    log_safety.unregister_secret("tokenInRam")
    assert "tokenInRam" in log_safety.redact("x tokenInRam y")


# ── SecretRedactionFilter applicato a un record reale ─────────────────────────

def test_filter_redige_il_messaggio_finale_del_record():
    log_safety.register_secret("passw0rd-segreta")
    flt = log_safety.SecretRedactionFilter()
    rec = logging.LogRecord("n", logging.INFO, __file__, 1,
                            "login user=%s pw=%s", ("mario", "passw0rd-segreta"), None)
    assert flt.filter(rec) is True       # non scarta mai
    msg = rec.getMessage()
    assert "passw0rd-segreta" not in msg
    assert rec.args == ()                # args azzerati: nessuna re-interpolazione


def test_filter_maschera_header_anche_senza_registrazione():
    flt = log_safety.SecretRedactionFilter()
    rec = logging.LogRecord("n", logging.DEBUG, __file__, 1,
                            "X-Authentication: liveTokenValue", None, None)
    flt.filter(rec)
    assert "liveTokenValue" not in rec.getMessage()


# ── silenziamento librerie HTTP ───────────────────────────────────────────────

def test_quiet_http_libraries_alza_il_livello():
    # Prima abbasso a DEBUG per provare che vengono rialzati.
    for name in log_safety.NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)
    log_safety.quiet_http_libraries()
    for name in log_safety.NOISY_HTTP_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_install_global_redaction_idempotente_e_installa_filtro():
    root = logging.getLogger()
    before = [f for f in root.filters if isinstance(f, log_safety.SecretRedactionFilter)]
    for f in before:
        root.removeFilter(f)
    f1 = log_safety.install_global_log_redaction()
    f2 = log_safety.install_global_log_redaction()
    installed = [f for f in root.filters if isinstance(f, log_safety.SecretRedactionFilter)]
    assert len(installed) == 1          # idempotente: un solo filtro
    assert f1 is f2
    root.removeFilter(f1)               # cleanup: non lasciare stato globale
