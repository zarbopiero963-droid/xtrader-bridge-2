"""Test hard veritieri — Issue #41 PR-2 (persistenza cronologia con redazione segreti).

Invariante centrale: sul **disco** la cronologia è SEMPRE redatta — API key Anthropic, bot token e
chat ID non finiscono mai in chiaro nel file. Più: scrittura atomica (file sempre valido) e load
fail-safe (assente/corrotto → cronologia vuota). Nessuna rete, nessuna GUI.
"""

import json
import os

from xtrader_bridge import config_agent as ca
from xtrader_bridge import event_log


# Segreti realistici ma FINTI (nessuna chiave reale).
_BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVWxyz01"   # shape <id>:<20+ char>
_API_KEY = "sk-ant-api03-ABCDEFGHIJKLMNOP1234567890"     # shape sk-ant-...
_CHAT_ID = "-1001234567890"                              # chat ID lungo (Telegram supergroup)


def _hist_with_secrets():
    return ca.ConversationHistory([
        {"role": "user", "content": f"il mio token è {_BOT_TOKEN} e la chat {_CHAT_ID}"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "ok, procedo"},
            {"type": "tool_use", "id": "t1", "name": "set_api_key",
             "input": {"api_key": _API_KEY, "nota": f"chat {_CHAT_ID}"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": f"salvata {_API_KEY}"},
        ]},
    ])


def test_save_scrive_file_redatto(tmp_path):
    p = str(tmp_path / "assistant_history.json")
    _hist_with_secrets().save(path=p, extra_secrets=[_CHAT_ID])
    raw = open(p, encoding="utf-8").read()
    # NESSUN segreto in chiaro nel file scritto
    assert _BOT_TOKEN not in raw
    assert _API_KEY not in raw
    assert _CHAT_ID not in raw
    # ma la struttura/testo non-sensibile resta
    assert "procedo" in raw
    assert "[REDACTED_TOKEN]" in raw


def test_redazione_profonda_nested(tmp_path):
    # tool_use.input e tool_result.content annidati devono essere redatti (deep-walk).
    p = str(tmp_path / "h.json")
    _hist_with_secrets().save(path=p, extra_secrets=[_CHAT_ID])
    data = json.load(open(p, encoding="utf-8"))
    blob = json.dumps(data)
    assert _API_KEY not in blob and _BOT_TOKEN not in blob and _CHAT_ID not in blob
    # il tool_use.input esiste ancora come struttura (solo il valore è redatto)
    assistant = data["messages"][1]["content"]
    tool_use = next(b for b in assistant if b["type"] == "tool_use")
    assert tool_use["input"]["api_key"] == "[REDACTED_TOKEN]"


def test_round_trip_save_load(tmp_path):
    p = str(tmp_path / "h.json")
    ca.ConversationHistory([{"role": "user", "content": "ciao"}]).save(path=p)
    loaded = ca.ConversationHistory.load(path=p)
    assert loaded.messages == [{"role": "user", "content": "ciao"}]
    assert loaded.is_empty() is False


def test_load_file_assente_vuoto(tmp_path):
    loaded = ca.ConversationHistory.load(path=str(tmp_path / "non_esiste.json"))
    assert loaded.messages == [] and loaded.is_empty() is True


def test_load_file_corrotto_vuoto(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("{ questo non è json valido", encoding="utf-8")
    loaded = ca.ConversationHistory.load(path=str(p))
    assert loaded.messages == []


def test_load_forma_inattesa_vuoto(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"version": 1, "messages": "non-una-lista"}), encoding="utf-8")
    assert ca.ConversationHistory.load(path=str(p)).messages == []


def test_save_atomico_produce_json_valido(tmp_path):
    p = str(tmp_path / "h.json")
    ca.ConversationHistory([{"role": "user", "content": "x"}]).save(path=p)
    # file completo e parsabile (scrittura atomica: mai troncato)
    data = json.load(open(p, encoding="utf-8"))
    assert data["version"] == ca.HISTORY_SCHEMA_VERSION
    assert isinstance(data["messages"], list)


def test_redacted_messages_non_muta_l_originale():
    h = _hist_with_secrets()
    before = json.dumps(h.messages)
    _ = h.redacted_messages(extra_secrets=[_CHAT_ID])
    # la vista redatta NON deve alterare la cronologia in RAM (sessione mantiene il contesto)
    assert json.dumps(h.messages) == before
    assert _API_KEY in json.dumps(h.messages)   # in RAM il valore resta


def test_extra_secret_corto_non_registrato_ma_lungo_si(tmp_path):
    # Limite onesto: register_secret ignora < 8 char → un chat ID cortissimo non è mascherato per
    # literal; uno lungo sì. (I chat ID reali Telegram sono lunghi.)
    p = str(tmp_path / "h.json")
    ca.ConversationHistory([{"role": "user", "content": "chat 42 e chat -1009999888877"}]).save(
        path=p, extra_secrets=["42", "-1009999888877"])
    raw = open(p, encoding="utf-8").read()
    assert "-1009999888877" not in raw     # lungo → redatto
    assert "42" in raw                     # corto → non redatto (documentato)


def test_extra_secrets_non_muta_registro_globale():
    # BLOCCANTE Fable/Fugu #63: se il chat_id era GIÀ registrato dall'app, redacted_messages non
    # deve de-registrarlo dal registro globale (altrimenti finirebbe in chiaro in TUTTI i log).
    chat = "-1001234567890"
    event_log.register_secret(chat)          # simula la registrazione persistente dell'app
    try:
        h = ca.ConversationHistory([{"role": "user", "content": f"chat {chat}"}])
        _ = h.redacted_messages(extra_secrets=[chat])
        # dopo la redazione, il segreto dell'app è ANCORA registrato (nessuna de-registrazione)
        assert event_log.redact_secrets(f"eco {chat}") == "eco [REDACTED_TOKEN]"
    finally:
        event_log.unregister_secret(chat)


def test_scalare_numerico_segreto_redatto(tmp_path):
    # BLOCCANTE Fugu #63: un chat_id come INT in tool_use.input non deve finire in chiaro.
    chat_int = -1001234567890
    p = str(tmp_path / "h.json")
    ca.ConversationHistory([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "set_chat",
             "input": {"chat_id": chat_int, "keep": 42}}]}]).save(
        path=p, extra_secrets=[str(chat_int)])
    raw = open(p, encoding="utf-8").read()
    assert str(chat_int) not in raw          # l'int-segreto è redatto
    data = json.load(open(p, encoding="utf-8"))
    tu = data["messages"][0]["content"][0]
    assert tu["input"]["chat_id"] == "[REDACTED_TOKEN]"
    assert tu["input"]["keep"] == 42         # numero legittimo (non segreto) preservato come int


def test_bool_non_convertito():
    # `bool` è sottoclasse di int: non deve diventare stringa nella redazione.
    out = ca._deep_redact({"flag": True, "n": 0})
    assert out["flag"] is True and out["n"] == 0


def test_chiave_dict_segreta_redatta():
    # GLM/GPT #63: un segreto usato come CHIAVE di dict non resta in chiaro.
    tok = "999888777:ABCdefGHIjklMNOpqrstUVWx"    # shape bot token
    out = ca._deep_redact({tok: "valore"})
    assert tok not in json.dumps(out)
    assert "[REDACTED_TOKEN]" in json.dumps(out)


def test_load_scarta_elementi_malformati(tmp_path):
    # GPT #63: elementi non-dict o senza "role" (file editato a mano) vengono scartati.
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"version": 1, "messages": [
        {"role": "user", "content": "ok"},
        "stringa-non-valida",
        {"content": "senza role"},
        123,
    ]}), encoding="utf-8")
    loaded = ca.ConversationHistory.load(path=str(p))
    assert loaded.messages == [{"role": "user", "content": "ok"}]


def test_history_path_usa_config_dir(monkeypatch):
    from xtrader_bridge import config_store
    monkeypatch.setattr(config_store, "config_dir", lambda: "/tmp/xtb-cfg")
    assert ca.history_path() == os.path.join("/tmp/xtb-cfg", ca.HISTORY_FILENAME)


def test_redact_secrets_maschera_anthropic_key():
    # Il pattern sk-ant-... è redatto anche SENZA registrazione (euristica, #41 PR-2).
    out = event_log.redact_secrets(f"la chiave è {_API_KEY} fine")
    assert _API_KEY not in out and "[REDACTED_TOKEN]" in out
