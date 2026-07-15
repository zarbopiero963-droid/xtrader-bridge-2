"""Test hard veritieri — Issue #76 P2-6 + P2-7 (audit 2026-07-15, assistente #41).

- **P2-6**: `_redact_config` mascherava `chat_id`/`xtrader_notification_chat_id`/
  `source_chats[].chat_id` ma NON i chat ID usati come CHIAVI dei dict `parser_by_chat` /
  `parser_list_by_chat` ({chat_id: parser}): con un override per-chat configurato,
  «mostrami la configurazione» inviava i chat ID reali in chiaro all'API Anthropic e li
  persisteva in `assistant_history.json`.
- **P2-7**: `build_message_preview` chiamava `batch_report` SENZA `mode=`: un parser
  LEGACY con `mode==""` veniva valutato in NAME_ONLY mentre il runtime
  (`signal_router._resolve_one`) eredita il `recognition_mode` globale — l'assistente
  poteva dire «Pronto» per un messaggio che il live in ID_ONLY scarta.
"""

import json

from xtrader_bridge import config_agent as ca
from xtrader_bridge import custom_parser as _cp
from xtrader_bridge import parser_io as _parser_io


# ── P2-6: chat ID come CHIAVI di parser_by_chat / parser_list_by_chat ────────────────────────

def test_redact_config_maschera_le_chiavi_di_parser_by_chat():
    cfg = {"parser_by_chat": {"-1001234567890": "P1"},
           "parser_list_by_chat": {"-1001234567890": ["P1", "P2"]}}
    out = ca._redact_config(cfg)
    dumped = json.dumps(out)
    assert "-1001234567890" not in dumped                       # ID mai in chiaro
    assert all(k.startswith("chat:sha256:") for k in out["parser_by_chat"])
    assert all(k.startswith("chat:sha256:") for k in out["parser_list_by_chat"])
    # I VALORI (nomi parser) non sono sensibili e restano leggibili.
    assert list(out["parser_by_chat"].values()) == ["P1"]
    assert list(out["parser_list_by_chat"].values()) == [["P1", "P2"]]


def test_redact_config_chiavi_redatte_correlabili_con_source_chats():
    # Stessa impronta stabile di redact_chat_id: la chiave redatta di parser_by_chat combacia
    # con il chat_id redatto della stessa chat in source_chats (correlazione senza rivelare).
    cfg = {"source_chats": [{"chat_id": "-100777", "name": "Canale"}],
           "parser_by_chat": {"-100777": "P1"}}
    out = ca._redact_config(cfg)
    assert list(out["parser_by_chat"].keys())[0] == out["source_chats"][0]["chat_id"]


def test_redact_config_parser_by_chat_malformato_resta_invariato():
    # Robustezza: un valore legacy non-dict non deve crashare la vista redatta.
    out = ca._redact_config({"parser_by_chat": "malformato", "parser_list_by_chat": 7})
    assert out["parser_by_chat"] == "malformato"
    assert out["parser_list_by_chat"] == 7


def test_redact_config_chiave_vuota_degrada_a_stringa_vuota():
    out = ca._redact_config({"parser_by_chat": {"": "P1"}})
    assert list(out["parser_by_chat"].keys()) == [""]           # mai None come chiave (JSON-safe)


def test_get_config_state_non_espone_i_chat_id_delle_chiavi(tmp_path):
    # End-to-end attraverso il TOOL: l'output di get_config_state (ciò che parte verso l'API
    # e finisce in cronologia) non contiene il chat ID reale usato come chiave.
    reg = ca.build_default_registry(
        config_loader=lambda: {"chat_id": "42",
                               "parser_by_chat": {"-1005556667778": "P1"},
                               "parser_list_by_chat": {"-1005556667778": ["P1"]}},
        parsers_dir=str(tmp_path))
    res = reg.dispatch("get_config_state", {})
    assert res.refused is False
    assert "-1005556667778" not in res.content
    assert "P1" in res.content                                  # il nome parser resta utile


# ── P2-7: parità preview↔runtime sulla modalità (parser legacy mode=="") ─────────────────────

def _parser_dir_legacy(tmp_path):
    """Parser d'esempio reale ma LEGACY: `mode=""` → il runtime eredita la modalità globale."""
    defn = _parser_io.example_parser()
    defn.name = "Legacy"
    defn.mode = ""
    _cp.save_parser(defn, str(tmp_path))
    return str(tmp_path)


def test_preview_parser_legacy_eredita_la_modalita_globale_id_only(tmp_path):
    # FAIL-FIRST P2-7: cfg globale ID_ONLY + parser legacy (mode="") + messaggio senza ID →
    # il runtime scarta (mancano MarketId/SelectionId); la preview deve dire lo STESSO.
    # Sul codice precedente batch_report riceveva mode=None → "" → NAME_ONLY → «Pronto».
    pd = _parser_dir_legacy(tmp_path)
    cfg = {"provider": "TG", "active_parser": "Legacy", "chat_id": "42",
           "recognition_mode": "ID_ONLY", "csv_language": "IT"}
    data = ca.build_message_preview(cfg, _parser_io.fixture_message(), parsers_dir=pd)
    rep = data["reports"][0]
    assert rep["recognized"] is False                           # parità col live: NON «Pronto»
    assert all(not r["placeable"] for r in rep["rows"])


def test_preview_mode_esplicito_del_parser_vince_sul_globale(tmp_path):
    # Il parser con mode ESPLICITO (NAME_ONLY) resta valutato nella SUA modalità anche con
    # globale ID_ONLY — stessa precedenza del runtime (defn.mode or cfg[...]).
    defn = _parser_io.example_parser()
    defn.name = "Esplicito"
    defn.mode = "NAME_ONLY"
    _cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "Esplicito", "chat_id": "42",
           "recognition_mode": "ID_ONLY", "csv_language": "IT"}
    data = ca.build_message_preview(cfg, _parser_io.fixture_message(), parsers_dir=str(tmp_path))
    assert data["reports"][0]["recognized"] is True


def test_preview_globale_assente_default_name_only(tmp_path):
    # Regressione: senza `recognition_mode` in config il default resta NAME_ONLY (fail-safe),
    # identico a prima del fix per le config esistenti.
    pd = _parser_dir_legacy(tmp_path)
    cfg = {"provider": "TG", "active_parser": "Legacy", "chat_id": "42", "csv_language": "IT"}
    data = ca.build_message_preview(cfg, _parser_io.fixture_message(), parsers_dir=pd)
    assert data["reports"][0]["recognized"] is True
