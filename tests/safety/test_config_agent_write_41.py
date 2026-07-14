"""Test hard veritieri — Issue #41 PR-4 (scrittura config GATED dell'assistente, review #65).

Il tool `set_config_value` **non scrive mai**: valida e **propone** (chiama `on_proposal`); la
scrittura vera è del controller, gated dalla conferma UMANA (vedi `test_config_agent_controller_41`).
Qui si coprono: allowlist/denylist (chiavi safety-critical rifiutate anche su ordine esplicito),
validazione stretta senza coercizione, `max_signal_age` non disattivabile, e — invariante di
sicurezza chiave della review #65 — **il tool non produce alcuna scrittura né effetto oltre la
proposta**. Nessuna rete.
"""

from xtrader_bridge import config_agent as ca


def _reg_with_sink():
    """Registry reale + un sink che REGISTRA le proposte (nessun disco, nessun save)."""
    proposals = []
    reg = ca.build_default_registry(
        config_loader=lambda: dict(_CFG),
        on_proposal=lambda key, new, old: proposals.append((key, new, old)))
    return reg, proposals


_CFG = {"theme": "dark", "app_language": "IT", "clear_delay": 90,
        "confirmation_timeout": 120, "max_signal_age": 120,
        "chat_id": "-1001234567890", "bridge_mode": "SIMULAZIONE", "dry_run": True,
        "csv_path": r"C:\XTrader\segnali.csv", "active_parser": "P1"}


# ── denylist: chiavi safety-critical mai proposte ───────────────────────────────

def test_chiavi_safety_critical_rifiutate_niente_proposta():
    reg, proposals = _reg_with_sink()
    for key, val in [("bot_token", "sekret"), ("chat_id", "-100999"),
                     ("bridge_mode", "REALE"), ("dry_run", False),
                     ("csv_path", r"C:\evil.csv"), ("csv_language", "EN"),
                     ("queue_mode", "APPEND_ACTIVE"), ("max_active_signals", 99),
                     ("auto_start_listener", True), ("active_parser", "X"),
                     ("debug_message_payload", True)]:
        res = reg.dispatch("set_config_value", {"key": key, "value": val}, allow_writes=True)
        assert res.refused is False                       # non è hard-block di NOME tool
        assert "SAFETY-CRITICAL" in res.content, key
    assert proposals == []                                # NESSUNA proposta per chiavi vietate


def test_chiave_sconosciuta_rifiutata_niente_proposta():
    reg, proposals = _reg_with_sink()
    res = reg.dispatch("set_config_value", {"key": "pippo", "value": "x"}, allow_writes=True)
    assert "non è modificabile" in res.content
    assert proposals == []


# ── validazione stretta (nessuna coercizione silenziosa) ────────────────────────

def test_valori_non_validi_rifiutati_niente_proposta():
    reg, proposals = _reg_with_sink()
    for key, bad in [("theme", "viola"), ("app_language", "FR"),
                     ("clear_delay", 2), ("clear_delay", 99999),
                     ("confirmation_timeout", "abc"), ("max_signal_age", 0)]:
        res = reg.dispatch("set_config_value", {"key": key, "value": bad}, allow_writes=True)
        assert "non valido" in res.content, (key, bad)
    assert proposals == []


def test_max_signal_age_non_disattivabile():
    # invariante anti-stantio: l'assistente non può proporre max_signal_age = 0 (filtro OFF).
    reg, proposals = _reg_with_sink()
    res = reg.dispatch("set_config_value", {"key": "max_signal_age", "value": 0}, allow_writes=True)
    assert "non valido" in res.content and proposals == []


# ── proposta valida: NON scrive, chiama on_proposal, forma canonica ─────────────

def test_valore_valido_propone_forma_canonica():
    reg, proposals = _reg_with_sink()
    res = reg.dispatch("set_config_value", {"key": "theme", "value": "Light"}, allow_writes=True)
    assert "PROPOSTA" in res.content
    assert proposals == [("theme", "light", "dark")]      # normalizzato, con vecchio valore


def test_valore_intero_valido_propone():
    reg, proposals = _reg_with_sink()
    reg.dispatch("set_config_value", {"key": "clear_delay", "value": 45}, allow_writes=True)
    assert proposals == [("clear_delay", 45, 90)]


def test_app_language_es_valido():
    reg, proposals = _reg_with_sink()
    reg.dispatch("set_config_value", {"key": "app_language", "value": "es"}, allow_writes=True)
    assert proposals == [("app_language", "ES", "IT")]


def test_nessuna_proposta_se_valore_uguale():
    reg, proposals = _reg_with_sink()
    res = reg.dispatch("set_config_value", {"key": "theme", "value": "dark"}, allow_writes=True)
    assert "Nessuna modifica" in res.content and proposals == []


def test_tool_non_scrive_mai_senza_sink():
    # senza `on_proposal` il tool resta innocuo: valida e risponde, nessun effetto collaterale.
    reg = ca.build_default_registry(config_loader=lambda: dict(_CFG))     # nessun sink
    res = reg.dispatch("set_config_value", {"key": "theme", "value": "light"}, allow_writes=True)
    assert "PROPOSTA" in res.content


# ── gate allow_writes + offerta al modello ──────────────────────────────────────

def test_set_config_value_gated_da_allow_writes():
    reg, proposals = _reg_with_sink()
    res = reg.dispatch("set_config_value", {"key": "theme", "value": "light"}, allow_writes=False)
    assert res.refused is True and res.reason == "write_disabled"
    assert proposals == []                                 # handler mai eseguito → niente proposta


def test_set_config_value_offerto_solo_con_writes():
    reg, _ = _reg_with_sink()
    assert "set_config_value" not in [s["name"] for s in reg.tool_specs()]
    assert "set_config_value" in [s["name"] for s in reg.tool_specs(include_writes=True)]


def test_schema_non_ha_piu_confirm():
    # review #65: la conferma NON è più un booleano del modello → il campo `confirm` è rimosso.
    reg, _ = _reg_with_sink()
    spec = [s for s in reg.tool_specs(include_writes=True) if s["name"] == "set_config_value"][0]
    assert "confirm" not in spec["input_schema"]["properties"]
