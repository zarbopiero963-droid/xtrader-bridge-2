"""Test del tema UI chiaro/scuro (#288 Delta 1) — logica pura in `config_store`.

`normalize_theme` è la fonte unica di verità (fail-closed a "dark"); `load_config` la applica
al campo `theme`. Esercita le funzioni REALI del progetto.
"""

import json

from xtrader_bridge import config_store
from xtrader_bridge.config_store import DEFAULTS, load_config, normalize_theme


def test_default_theme_e_dark():
    assert DEFAULTS["theme"] == "dark"


def test_normalize_theme_valori_validi():
    assert normalize_theme("dark") == "dark"
    assert normalize_theme("light") == "light"


def test_normalize_theme_case_e_spazi_insensitive():
    assert normalize_theme("LIGHT") == "light"
    assert normalize_theme("  Dark ") == "dark"


def test_normalize_theme_fail_closed_a_dark():
    # Mancante / non-stringa / valore sconosciuto → default sicuro "dark".
    for bad in ["", "  ", "blu", "x", None, 5, 0, {"a": 1}, ["light"], True]:
        assert normalize_theme(bad) == "dark", bad


def test_load_config_theme_light_preservato(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    assert load_config(str(p))["theme"] == "light"


def test_load_config_theme_malformato_diventa_dark(tmp_path):
    # Config editata a mano con un valore sporco → non lascia l'UI in stato indefinito.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"theme": "PURPLE"}), encoding="utf-8")
    assert load_config(str(p))["theme"] == "dark"


def test_load_config_theme_assente_eredita_dark(tmp_path):
    # Config VECCHIA senza il campo `theme` → default "dark" (retrocompatibile).
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"chat_id": "42"}), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg["theme"] == "dark"
    assert cfg["chat_id"] == "42"          # gli altri campi restano
