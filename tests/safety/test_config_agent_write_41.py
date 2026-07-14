"""Test hard veritieri — Issue #41 PR-4 (scrittura config GATED dell'assistente).

Coprono le invarianti di sicurezza della scrittura: SOLO le chiavi non safety-critical sono
scrivibili (allowlist), le chiavi safety-critical sono RIFIUTATE anche su ordine esplicito
(denylist), i valori fuori dominio sono rifiutati SENZA coercizione silenziosa, la scrittura passa
per un gate di CONFERMA esplicita, e un save reale persiste la sola chiave richiesta preservando il
resto della config. Nessuna rete: si esercita il registry reale del progetto e `config_store` su
`tmp_path` (nessun keyring, nessun XTrader).
"""

import json
import os

from xtrader_bridge import config_agent as ca
from xtrader_bridge import config_store


def _reg(tmp_path, monkeypatch, cfg):
    """Registry reale con load/save su `tmp_path` (config.json isolato)."""
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")

    def _load():
        return config_store.load_config(path)

    def _save(c):
        return config_store.save_config(c, path)

    # scrivi una config di base sul disco isolato
    config_store.save_config(cfg, path)
    return ca.build_default_registry(config_loader=_load, config_saver=_save), path


_BASE = {"theme": "dark", "app_language": "IT", "clear_delay": 90,
         "confirmation_timeout": 120, "max_signal_age": 120,
         "chat_id": "-1001234567890", "csv_path": r"C:\XTrader\segnali.csv",
         "bridge_mode": "SIMULAZIONE", "dry_run": True, "active_parser": "P1"}


# ── denylist: chiavi safety-critical mai scrivibili ─────────────────────────────

def test_chiavi_safety_critical_rifiutate(tmp_path, monkeypatch):
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    for key, val in [("bot_token", "sekret"), ("chat_id", "-100999"),
                     ("bridge_mode", "REALE"), ("dry_run", False),
                     ("csv_path", r"C:\evil.csv"), ("csv_language", "EN"),
                     ("queue_mode", "APPEND_ACTIVE"), ("max_active_signals", 99),
                     ("auto_start_listener", True), ("active_parser", "X"),
                     ("debug_message_payload", True)]:
        res = reg.dispatch("set_config_value",
                           {"key": key, "value": val, "confirm": True}, allow_writes=True)
        assert res.refused is False           # non è un hard-block di NOME tool
        assert "SAFETY-CRITICAL" in res.content, key
    # nessuna di queste chiavi è stata modificata sul disco
    saved = config_store.load_config(path)
    assert saved["chat_id"] == "-1001234567890"
    assert saved["bridge_mode"] == "SIMULAZIONE" and saved["dry_run"] is True
    assert saved["active_parser"] == "P1"


def test_chiave_sconosciuta_rifiutata(tmp_path, monkeypatch):
    reg, _ = _reg(tmp_path, monkeypatch, dict(_BASE))
    res = reg.dispatch("set_config_value",
                       {"key": "pippo", "value": "x", "confirm": True}, allow_writes=True)
    assert "non è modificabile" in res.content


# ── validazione stretta (nessuna coercizione silenziosa) ────────────────────────

def test_valori_non_validi_rifiutati(tmp_path, monkeypatch):
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    for key, bad in [("theme", "viola"), ("app_language", "FR"),
                     ("clear_delay", 2), ("clear_delay", 99999),
                     ("confirmation_timeout", "abc"), ("max_signal_age", 0)]:
        res = reg.dispatch("set_config_value",
                           {"key": key, "value": bad, "confirm": True}, allow_writes=True)
        assert "non valido" in res.content, (key, bad)
    # disco invariato
    saved = config_store.load_config(path)
    assert saved["theme"] == "dark" and saved["app_language"] == "IT"
    assert saved["clear_delay"] == 90 and saved["max_signal_age"] == 120


def test_max_signal_age_non_disattivabile(tmp_path, monkeypatch):
    # invariante anti-stantio: l'assistente non può portare max_signal_age a 0 (filtro OFF).
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    res = reg.dispatch("set_config_value",
                       {"key": "max_signal_age", "value": 0, "confirm": True}, allow_writes=True)
    assert "non valido" in res.content
    assert config_store.load_config(path)["max_signal_age"] == 120


# ── gate di conferma ────────────────────────────────────────────────────────────

def test_senza_confirm_solo_anteprima_niente_scrittura(tmp_path, monkeypatch):
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    res = reg.dispatch("set_config_value",
                       {"key": "theme", "value": "light"}, allow_writes=True)   # niente confirm
    assert "CONFERMA RICHIESTA" in res.content
    assert config_store.load_config(path)["theme"] == "dark"       # NON scritto


def test_con_confirm_scrive_davvero(tmp_path, monkeypatch):
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    res = reg.dispatch("set_config_value",
                       {"key": "theme", "value": "Light", "confirm": True}, allow_writes=True)
    assert "Fatto" in res.content
    saved = config_store.load_config(path)
    assert saved["theme"] == "light"                              # forma canonica
    # il resto della config è PRESERVATO (round-trip completo, non un save di sola-chiave)
    assert saved["chat_id"] == "-1001234567890"
    assert saved["active_parser"] == "P1" and saved["clear_delay"] == 90
    # il file su disco è JSON valido e non contiene la chat in chiaro fuori posto
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    assert raw["theme"] == "light"


def test_valore_intero_valido_persistito(tmp_path, monkeypatch):
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    res = reg.dispatch("set_config_value",
                       {"key": "clear_delay", "value": 45, "confirm": True}, allow_writes=True)
    assert "Fatto" in res.content
    assert config_store.load_config(path)["clear_delay"] == 45


def test_nessuna_modifica_se_valore_uguale(tmp_path, monkeypatch):
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    res = reg.dispatch("set_config_value",
                       {"key": "theme", "value": "dark", "confirm": True}, allow_writes=True)
    assert "Nessuna modifica" in res.content


# ── gate allow_writes + offerta al modello ──────────────────────────────────────

def test_set_config_value_gated_da_allow_writes(tmp_path, monkeypatch):
    reg, path = _reg(tmp_path, monkeypatch, dict(_BASE))
    # allow_writes=False → rifiutato dal gate del registry, handler mai eseguito
    res = reg.dispatch("set_config_value",
                       {"key": "theme", "value": "light", "confirm": True}, allow_writes=False)
    assert res.refused is True and res.reason == "write_disabled"
    assert config_store.load_config(path)["theme"] == "dark"


def test_set_config_value_offerto_solo_con_writes(tmp_path, monkeypatch):
    reg, _ = _reg(tmp_path, monkeypatch, dict(_BASE))
    assert "set_config_value" not in [s["name"] for s in reg.tool_specs()]
    assert "set_config_value" in [s["name"] for s in reg.tool_specs(include_writes=True)]


def test_save_fallito_riporta_errore(tmp_path, monkeypatch):
    # un saver che fallisce (disco) → messaggio "NON riuscito", nessun falso "Fatto".
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    reg = ca.build_default_registry(
        config_loader=lambda: dict(_BASE),
        config_saver=lambda c: config_store.SaveResult(c, False, config_store.SAVE_DISK_ERROR))
    res = reg.dispatch("set_config_value",
                       {"key": "theme", "value": "light", "confirm": True}, allow_writes=True)
    assert "NON riuscito" in res.content
