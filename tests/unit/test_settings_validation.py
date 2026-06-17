"""Test della validazione impostazioni (PR-13/#10): logica pura, niente GUI."""

from xtrader_bridge import settings_validation as sv


# ── parse_timeout ────────────────────────────────────────────────────────────

def test_timeout_valido():
    assert sv.parse_timeout("120") == (120, None)


def test_timeout_vuoto_usa_default():
    assert sv.parse_timeout("") == (sv.DEFAULT_TIMEOUT, None)
    assert sv.parse_timeout(None) == (sv.DEFAULT_TIMEOUT, None)
    assert sv.parse_timeout("  ", default=42) == (42, None)


def test_timeout_non_numerico_errore():
    value, err = sv.parse_timeout("abc")
    assert value is None
    assert "non valido" in err


def test_timeout_non_positivo_errore():
    assert sv.parse_timeout("0")[0] is None
    assert sv.parse_timeout("-5")[0] is None
    assert "maggiore di 0" in sv.parse_timeout("0")[1]


# ── validate_settings ────────────────────────────────────────────────────────

def test_settings_valide_nessun_errore():
    raw = {"bot_token": "T", "csv_path": r"C:\XTrader\segnali.csv", "clear_delay": "90"}
    assert sv.validate_settings(raw) == []


def test_csv_path_mancante_errore():
    raw = {"bot_token": "T", "csv_path": "  ", "clear_delay": "90"}
    errors = sv.validate_settings(raw)
    assert any("CSV Path" in e for e in errors)


def test_timeout_non_numerico_blocca():
    raw = {"bot_token": "T", "csv_path": "x.csv", "clear_delay": "tanto"}
    errors = sv.validate_settings(raw)
    assert any("Timeout" in e for e in errors)


def test_token_assente_non_e_errore_di_validazione():
    # Il token vuoto NON è un errore "rosso" del form: disabilita START (can_start),
    # ma validate_settings resta vuoto se il resto è valido.
    raw = {"bot_token": "", "csv_path": "x.csv", "clear_delay": "90"}
    assert sv.validate_settings(raw) == []


# ── can_start ────────────────────────────────────────────────────────────────

def test_can_start_ok():
    raw = {"bot_token": "T", "csv_path": "x.csv", "clear_delay": "90"}
    assert sv.can_start(raw) is True


def test_can_start_token_vuoto_disabilita():
    raw = {"bot_token": "", "csv_path": "x.csv", "clear_delay": "90"}
    assert sv.can_start(raw) is False


def test_can_start_csv_mancante_disabilita():
    raw = {"bot_token": "T", "csv_path": "", "clear_delay": "90"}
    assert sv.can_start(raw) is False


def test_can_start_timeout_invalido_disabilita():
    raw = {"bot_token": "T", "csv_path": "x.csv", "clear_delay": "boh"}
    assert sv.can_start(raw) is False
