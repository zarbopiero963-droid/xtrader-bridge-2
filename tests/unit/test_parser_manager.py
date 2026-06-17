"""Test della gestione del Parser Personalizzato attivo (CP-07)."""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_manager as pm
from xtrader_bridge.config_store import DEFAULTS


def _save_parser(name, dir_path):
    defn = cp.CustomParserDef(name=name, rules=[cp.FieldRule(target="Price", required=True)])
    return cp.save_parser(defn, dir_path)


# ── default di config ──────────────────────────────────────────────────────

def test_defaults_hanno_le_chiavi():
    assert DEFAULTS["active_parser"] == ""
    assert DEFAULTS["parser_by_chat"] == {}


# ── risoluzione del nome ─────────────────────────────────────────────────────

def test_resolve_nessuno_di_default():
    assert pm.resolve_parser_name({}) == ""
    assert pm.resolve_parser_name({"active_parser": ""}) == ""


def test_resolve_attivo_globale():
    assert pm.resolve_parser_name({"active_parser": "Yangon"}) == "Yangon"
    assert pm.resolve_parser_name({"active_parser": "Yangon"}, chat_id="123") == "Yangon"


def test_resolve_override_per_chat():
    cfg = {"active_parser": "Globale", "parser_by_chat": {"123": "PerChat"}}
    assert pm.resolve_parser_name(cfg, chat_id="123") == "PerChat"   # override
    assert pm.resolve_parser_name(cfg, chat_id="999") == "Globale"   # nessun override → globale
    assert pm.resolve_parser_name(cfg) == "Globale"


# ── set_active / set_for_chat (immutabili) ──────────────────────────────────

def test_set_active_non_muta_originale():
    cfg = {"active_parser": ""}
    out = pm.set_active(cfg, "  Yangon  ")
    assert out["active_parser"] == "Yangon"
    assert cfg["active_parser"] == ""        # originale invariato


def test_set_for_chat_aggiunge_e_rimuove():
    cfg = {}
    out = pm.set_for_chat(cfg, "123", "PerChat")
    assert out["parser_by_chat"] == {"123": "PerChat"}
    cleared = pm.set_for_chat(out, "123", "")   # nome vuoto → rimuove
    assert cleared["parser_by_chat"] == {}


# ── elenco e caricamento ─────────────────────────────────────────────────────

def test_available_parser_names(tmp_path):
    _save_parser("Alfa", str(tmp_path))
    _save_parser("Beta", str(tmp_path))
    assert pm.available_parser_names(str(tmp_path)) == ["Alfa", "Beta"]


def test_load_active_none_se_non_selezionato(tmp_path):
    assert pm.load_active({}, dir_path=str(tmp_path)) is None


def test_load_active_none_se_file_mancante(tmp_path):
    assert pm.load_active({"active_parser": "NonEsiste"}, dir_path=str(tmp_path)) is None


def test_load_active_carica_il_parser(tmp_path):
    _save_parser("Yangon", str(tmp_path))
    defn = pm.load_active({"active_parser": "Yangon"}, dir_path=str(tmp_path))
    assert defn is not None and defn.name == "Yangon"


def test_load_active_override_per_chat(tmp_path):
    _save_parser("Globale", str(tmp_path))
    _save_parser("PerChat", str(tmp_path))
    cfg = {"active_parser": "Globale", "parser_by_chat": {"123": "PerChat"}}
    assert pm.load_active(cfg, chat_id="123", dir_path=str(tmp_path)).name == "PerChat"
    assert pm.load_active(cfg, chat_id="999", dir_path=str(tmp_path)).name == "Globale"
