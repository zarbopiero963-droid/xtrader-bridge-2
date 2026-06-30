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


def test_timeout_non_numerico_non_espone_il_valore():
    # Se l'utente incolla per sbaglio un bot token nel campo timeout, NON deve
    # finire nel messaggio d'errore (invariante: mai token nei log).
    token = "123456789:AAExampleSecretTokenValue_nonReale"
    value, err = sv.parse_timeout(token)
    assert value is None
    assert token not in err


def test_timeout_non_positivo_errore():
    assert sv.parse_timeout("0")[0] is None
    assert sv.parse_timeout("-5")[0] is None
    assert "maggiore di 0" in sv.parse_timeout("0")[1]


def test_timeout_non_positivo_non_espone_il_valore():
    # Un chat ID NEGATIVO Telegram (gruppi/canali, es. -1001234567890) incollato per
    # sbaglio nel campo timeout è numerico e <= 0: il messaggio NON deve contenerlo
    # (invariante: mai identificatori/segreti nei log) — Codex #27.
    chat_id = "-1001234567890"
    value, err = sv.parse_timeout(chat_id)
    assert value is None
    assert chat_id not in err
    # Anche un negativo "corto" non deve comparire (nessun valore grezzo nel messaggio).
    assert "-5" not in sv.parse_timeout("-5")[1]


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


def test_timeout_non_positivo_blocca():
    # validate_settings si appoggia a parse_timeout: anche un timeout <= 0 deve
    # essere un errore bloccante (un auto-clear a 0/negativo è pericoloso).
    for bad in ("0", "-5"):
        raw = {"bot_token": "T", "csv_path": "x.csv", "clear_delay": bad}
        errors = sv.validate_settings(raw)
        assert any("Timeout" in e for e in errors), bad


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


def test_can_start_timeout_non_positivo_disabilita():
    # Timeout numerico ma <= 0: parse_timeout lo rifiuta → can_start False.
    for bad in ("0", "-1"):
        raw = {"bot_token": "T", "csv_path": "x.csv", "clear_delay": bad}
        assert sv.can_start(raw) is False, bad
