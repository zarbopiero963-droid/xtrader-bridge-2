"""Test hard #343 slice «selettore lingua»: logica pura + coercion config.

Tutto headless: `language_select` è puro; la coercion di `config_store` è esercitata
via `load_config` su file temporaneo."""

import json

from xtrader_bridge import config_store, language_select


# ── normalize / needs_language_selection ─────────────────────────────────────

def test_normalize_accetta_solo_lingue_supportate():
    assert language_select.normalize_app_language("IT") == "IT"
    assert language_select.normalize_app_language(" en ") == "EN"
    assert language_select.normalize_app_language("es") == "ES"
    # Fail-closed: MAI un fallback a IT silenzioso — vuoto = "mai scelta".
    assert language_select.normalize_app_language("") == ""
    assert language_select.normalize_app_language("FR") == ""
    assert language_select.normalize_app_language(None) == ""
    assert language_select.normalize_app_language(123) == ""


def test_needs_selection_solo_se_mai_scelta():
    assert language_select.needs_language_selection({}) is True
    assert language_select.needs_language_selection({"app_language": ""}) is True
    assert language_select.needs_language_selection({"app_language": "XX"}) is True
    assert language_select.needs_language_selection("non-dict") is True
    assert language_select.needs_language_selection({"app_language": "IT"}) is False
    assert language_select.needs_language_selection({"app_language": "es"}) is False


# ── apply_language ────────────────────────────────────────────────────────────

def test_apply_language_allinea_app_e_csv_senza_mutare_l_originale():
    cfg = {"app_language": "", "csv_language": "IT", "bot_token": "x"}
    out = language_select.apply_language(cfg, "en")
    assert out["app_language"] == "EN" and out["csv_language"] == "EN"
    assert out["bot_token"] == "x"                      # il resto della config è preservato
    assert cfg["app_language"] == "" and cfg["csv_language"] == "IT"   # originale INTATTO


def test_apply_language_codice_non_supportato_fail_closed():
    cfg = {"app_language": "", "csv_language": "IT"}
    assert language_select.apply_language(cfg, "FR") is None
    assert language_select.apply_language(cfg, "") is None
    assert language_select.apply_language(cfg, None) is None
    assert cfg == {"app_language": "", "csv_language": "IT"}   # nessuna modifica


def test_labels_e_costanti_gui():
    codes = [c for c, _ in language_select.LANGUAGE_LABELS]
    assert codes == ["IT", "EN", "ES"] == list(language_select.SUPPORTED)
    assert "lingua" in language_select.SOURCE_LANGUAGE_HINT.lower()
    assert language_select.TITLE.startswith("🌐")


# ── coercion config_store (fail-closed su valore sporco) ─────────────────────

def _load_with(tmp_path, **overrides):
    cfg = dict(config_store.DEFAULTS)
    cfg.pop("bot_token", None)
    cfg.update(overrides)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return config_store.load_config(str(p))


def test_config_app_language_default_vuota_e_coercion(tmp_path):
    assert config_store.DEFAULTS["app_language"] == ""      # default: mai scelta
    loaded = _load_with(tmp_path, app_language=" it ")
    assert loaded["app_language"] == "IT"                    # normalizzata
    loaded = _load_with(tmp_path, app_language="GARBAGE")
    assert loaded["app_language"] == ""                      # sporco → vuota (selettore riappare)
    loaded = _load_with(tmp_path)                            # config vecchia senza campo
    assert loaded["app_language"] == ""
