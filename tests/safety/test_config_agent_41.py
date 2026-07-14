"""Test hard veritieri — Issue #41 PR-1 (scheletro assistente di configurazione).

Focalizzati sulle **invarianti di sicurezza** (hard block): l'agente non può eseguire azioni
vietate nemmeno su ordine esplicito, i segreti non lasciano mai la macchina in chiaro, la
scrittura config è gated, e il loop tool-use è protetto da un cap. Nessuna rete reale: il client
Anthropic è iniettato come oggetto finto.
"""

import json
import os

import pytest

from xtrader_bridge import config_agent as ca
from xtrader_bridge import event_log, token_store


# ── helper: client Anthropic FINTO (nessuna rete) ───────────────────────────────
class FakeClient:
    """Ritorna risposte SCRIPTATE nel formato normalizzato di ``ConfigAgent``."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create_message(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        return self.script.pop(0) if self.script else {"stop_reason": "end_turn", "content": []}


class AlwaysToolClient:
    """Client che chiama SEMPRE un tool (per testare il cap anti-loop)."""

    def __init__(self, name="get_health"):
        self.name = name
        self.n = 0

    def create_message(self, *, system, messages, tools):
        self.n += 1
        return {"stop_reason": "tool_use",
                "content": [{"type": "tool_use", "id": f"t{self.n}", "name": self.name, "input": {}}]}


def _tool_use(name, tool_id="t1", tool_input=None):
    return {"stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": tool_id, "name": name,
                         "input": tool_input or {}}]}


def _final(text):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


_CFG = {"active_parser": "P1", "chat_id": "-1001234567",
        "token": "FAKEBOTTOKEN0000", "provider": "TG",
        "csv_path": r"C:\XTrader\segnali.csv"}


def _registry(**kw):
    return ca.build_default_registry(config_loader=lambda: dict(_CFG), **kw)


# ── guardie hard-block ──────────────────────────────────────────────────────────

def test_forbidden_tool_dispatch_e_rifiutato():
    reg = _registry()
    for name in ("place_bet", "start_live_listener", "set_real_mode", "reveal_secret",
                 "web_fetch", "run_shell", "write_operational_csv", "weaken_chat_filter"):
        res = reg.dispatch(name, {})
        assert res.refused is True, name
        assert res.reason == "forbidden", name
    # ogni tentativo è registrato come RIFIUTATO nell'audit
    assert all(e["allowed"] is False for e in reg.audit_log)


def test_forbidden_tool_non_registrabile():
    # Difesa in profondità: un tool con nome nella denylist NON può nemmeno entrare nel registry.
    reg = ca.ToolRegistry()
    bad = ca.AgentTool("place_bet", "x", {"type": "object", "properties": {}},
                       ca.READ_ONLY, lambda _i: "eseguito!")
    with pytest.raises(ValueError):
        reg.register(bad)


def test_tool_sconosciuto_rifiutato():
    reg = _registry()
    res = reg.dispatch("tool_che_non_esiste", {})
    assert res.refused is True and res.reason == "unknown"


def test_scrittura_config_gated_on_off():
    called = {"n": 0}

    def _writer(_inp):
        called["n"] += 1
        return "scritto"

    reg = _registry()
    reg.register(ca.AgentTool("set_token", "scrive", {"type": "object", "properties": {}},
                              ca.WRITE_CONFIG, _writer))
    # allow_writes=False (default PR-1) → rifiutato, handler MAI chiamato
    res = reg.dispatch("set_token", {}, allow_writes=False)
    assert res.refused is True and res.reason == "write_disabled"
    assert called["n"] == 0
    # allow_writes=True → eseguito
    res2 = reg.dispatch("set_token", {}, allow_writes=True)
    assert res2.refused is False and called["n"] == 1


def test_tool_specs_espone_solo_read_only_in_pr1():
    reg = _registry()
    reg.register(ca.AgentTool("set_token", "scrive", {"type": "object", "properties": {}},
                              ca.WRITE_CONFIG, lambda _i: "x"))
    names = [s["name"] for s in reg.tool_specs()]                    # default: no writes
    assert "set_token" not in names
    assert set(names) == {"get_config_state", "get_health", "list_parsers", "get_setup_status"}
    assert "set_token" in [s["name"] for s in reg.tool_specs(include_writes=True)]


# ── redazione segreti ───────────────────────────────────────────────────────────

def test_get_config_state_non_espone_token_ne_chat():
    reg = _registry()
    res = reg.dispatch("get_config_state", {})
    assert res.refused is False
    assert "FAKEBOTTOKEN0000" not in res.content       # token mascherato ("***")
    assert "-1001234567" not in res.content        # chat ID redatto
    assert "active_parser" in res.content          # i campi non sensibili restano


def test_risultato_tool_passa_per_redact_secrets():
    # Un segreto REGISTRATO che finisse in un risultato di tool viene redatto prima di tornare
    # al modello (difesa: nessun leak verso l'API anche se un tool lo espone per errore).
    secret = "FAKE-SECRET-VALUE-xyz"
    event_log.register_secret(secret)
    try:
        reg = ca.ToolRegistry()
        reg.register(ca.AgentTool("leaky", "espone un segreto",
                                  {"type": "object", "properties": {}},
                                  ca.READ_ONLY, lambda _i: f"la chiave è {secret}"))
        res = reg.dispatch("leaky", {})
        assert secret not in res.content
        assert res.refused is False
    finally:
        event_log.unregister_secret(secret)


def test_audit_log_input_redatto():
    # #62 (GPT/Fable/Fugu/GLM): un segreto passato come PARAMETRO di tool non deve restare in
    # chiaro nell'audit_log (canale di leak in memoria / futura cronologia PR-2).
    secret = "FAKE-AUDIT-SECRET-123"
    event_log.register_secret(secret)
    try:
        reg = _registry()
        reg.dispatch("tool_sconosciuto", {"api_key": secret})   # anche su tool rifiutato
        entry = reg.audit_log[-1]
        assert secret not in str(entry["input"])
        # e su un tool eseguito
        reg.dispatch("get_health", {"nota": secret})
        assert all(secret not in str(e["input"]) for e in reg.audit_log)
    finally:
        event_log.unregister_secret(secret)


def test_logger_non_riceve_segreti():
    secret = "FAKE-LOGGER-SECRET-456"
    event_log.register_secret(secret)
    captured = []
    try:
        reg = ca.build_default_registry(config_loader=lambda: dict(_CFG),
                                        logger=captured.append)
        # il nome-tool (controllato dal modello) contiene un segreto → il log lo redige
        reg.dispatch(secret, {})
        assert captured and all(secret not in m for m in captured)
    finally:
        event_log.unregister_secret(secret)


def test_contenuto_rifiuto_redatto():
    secret = "FAKE-REFUSAL-SECRET-789"
    event_log.register_secret(secret)
    try:
        reg = _registry()
        res = reg.dispatch(secret, {})          # nome sconosciuto = il segreto stesso
        assert res.refused is True
        assert secret not in res.content         # il messaggio di rifiuto è redatto
    finally:
        event_log.unregister_secret(secret)


def test_audit_e_result_name_redatti():
    # #62 (GPT/Fable/Fugu): il NOME del tool è controllato dal modello e può contenere un segreto →
    # né audit_log["name"]/["reason"] né ToolResult.name devono conservarlo in chiaro.
    secret = "FAKE-NAME-SECRET-abc"
    event_log.register_secret(secret)
    try:
        reg = _registry()
        res = reg.dispatch(secret, {"x": secret})
        entry = reg.audit_log[-1]
        # nessun campo serializzabile dell'audit contiene il segreto
        assert secret not in str(entry["name"])
        assert secret not in str(entry["input"])
        assert secret not in str(entry["reason"])
        # né il risultato restituito
        assert secret not in res.name
        assert secret not in res.content
    finally:
        event_log.unregister_secret(secret)


# ── #41 PR-5: get_setup_status (checklist prima configurazione, sola lettura) ────

def test_get_setup_status_config_vuota():
    reg = ca.build_default_registry(config_loader=lambda: {})
    res = reg.dispatch("get_setup_status", {})
    assert res.refused is False
    data = json.loads(res.content)
    assert data["ready_to_start"] is False
    assert data["language_chosen"] is None
    # requisiti per CHIAVE (non per indice): niente configurato → tutti False
    assert data["requirements"] == {"bot_token": False, "chat": False,
                                     "parser_active": False, "csv_usable": False}
    # la modalità di default è Simulazione (informativa, non un requisito di START)
    assert data["mode_simulation"] is True


def test_get_setup_status_config_completa(tmp_path):
    # cartella esistente → CSV usabile; token/chat/parser presenti → pronto allo START.
    csv_path = os.path.join(str(tmp_path), "segnali.csv")
    cfg = {"bot_token": "FAKEBOTTOKEN0000", "chat_id": "-1001234567890",
           "active_parser": "P1", "csv_path": csv_path, "app_language": "IT",
           "bridge_mode": "SIMULAZIONE"}
    reg = ca.build_default_registry(config_loader=lambda: dict(cfg))
    res = reg.dispatch("get_setup_status", {})
    data = json.loads(res.content)
    assert data["ready_to_start"] is True
    assert all(data["requirements"].values())        # tutti e 4 i requisiti a posto
    assert data["language_chosen"] == "IT"
    # token/chat NON compaiono in chiaro nell'output (solo booleani + label)
    assert "FAKEBOTTOKEN0000" not in res.content
    assert "-1001234567890" not in res.content


def test_get_setup_status_parziale_non_pronto():
    # token+chat ma NESSUN parser attivo → non pronto (lo START richiede il parser). Segreti
    # realistici nei campi critici: non devono comparire in chiaro nell'output.
    cfg = {"bot_token": "123456:FAKE-AAAABBBBCCCCDDDD", "chat_id": "-1009998887776",
           "active_parser": "", "csv_path": "", "bridge_mode": "SIMULAZIONE"}
    reg = ca.build_default_registry(config_loader=lambda: dict(cfg))
    res = reg.dispatch("get_setup_status", {})
    data = json.loads(res.content)
    assert data["ready_to_start"] is False
    assert data["requirements"]["bot_token"] is True
    assert data["requirements"]["parser_active"] is False
    assert "123456:FAKE-AAAABBBBCCCCDDDD" not in res.content
    assert "-1009998887776" not in res.content


def test_get_setup_status_csv_dir_inesistente_non_pronto(tmp_path):
    # GLM/GPT #66: csv_path in una directory INESISTENTE → csv non usabile → non pronto.
    csv_path = os.path.join(str(tmp_path), "cartella_assente", "segnali.csv")
    cfg = {"bot_token": "t", "chat_id": "-100999", "active_parser": "P1", "csv_path": csv_path}
    reg = ca.build_default_registry(config_loader=lambda: dict(cfg))
    data = json.loads(reg.dispatch("get_setup_status", {}).content)
    assert data["requirements"]["csv_usable"] is False
    assert data["ready_to_start"] is False


def test_get_setup_status_non_crea_ne_tocca_il_csv(tmp_path):
    # Fable #66: il tool è READ_ONLY → la sonda `csv_writable` NON deve creare né modificare il file
    # CSV (mai `open`/write: solo `os.path`/`os.access`). Prova su path assente E su file esistente.
    csv_path = os.path.join(str(tmp_path), "segnali.csv")
    reg = ca.build_default_registry(
        config_loader=lambda: {"csv_path": csv_path, "active_parser": "P1"})
    data = json.loads(reg.dispatch("get_setup_status", {}).content)
    assert not os.path.exists(csv_path)              # la sonda NON ha creato il file
    assert data["requirements"]["csv_usable"] is True   # cartella scrivibile → usabile (POSIX)
    # file già esistente: il contenuto resta INTATTO dopo la sonda
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("HEADER-XTRADER\n")
    reg.dispatch("get_setup_status", {})
    with open(csv_path, encoding="utf-8") as fh:
        assert fh.read() == "HEADER-XTRADER\n"       # non toccato


def test_get_setup_status_source_chats_fallback():
    # GPT/GLM #66: `chat` usa `source_chats` come fallback di `chat_id`. Lista VUOTA → False
    # (bool([]) è False, coerente con wizard.final_checklist); lista con voci → True.
    vuota = ca.build_default_registry(config_loader=lambda: {"chat_id": "", "source_chats": []})
    assert json.loads(vuota.dispatch("get_setup_status", {}).content)["requirements"]["chat"] is False
    piena = ca.build_default_registry(
        config_loader=lambda: {"chat_id": "", "source_chats": [{"chat_id": "-1001234567890"}]})
    d = json.loads(piena.dispatch("get_setup_status", {}).content)
    assert d["requirements"]["chat"] is True
    assert "-1001234567890" not in json.dumps(d)      # nemmeno il chat_id di source_chats in chiaro


def test_get_setup_status_e_read_only_e_non_scrive():
    reg = ca.build_default_registry(config_loader=lambda: {})
    # offerto SEMPRE (read-only), anche senza allow_writes
    assert "get_setup_status" in [s["name"] for s in reg.tool_specs()]
    # non è un write-tool: dispatch senza allow_writes NON è rifiutato
    assert reg.dispatch("get_setup_status", {}, allow_writes=False).refused is False


def test_tool_specs_esclude_forbidden_anche_se_iniettato():
    # Difesa in profondità: anche bypassando `register` (che già lo vieta) e iniettando un tool
    # dal nome vietato direttamente in `_tools`, `tool_specs` non lo offre MAI al modello.
    reg = _registry()
    reg._tools["place_bet"] = ca.AgentTool(
        "place_bet", "x", {"type": "object", "properties": {}}, ca.WRITE_CONFIG, lambda _i: "!")
    offered = [s["name"] for s in reg.tool_specs(include_writes=True)]
    assert "place_bet" not in offered


def test_real_client_lazy_import_failsafe():
    # La costruzione NON importa `anthropic` (l'import del modulo non deve rompere l'avvio app).
    client = ca.RealAnthropicClient("fake-key")
    import importlib.util
    if importlib.util.find_spec("anthropic") is None:
        # Dipendenza assente → errore CHIARO solo all'uso reale, mai un ImportError all'import.
        with pytest.raises(RuntimeError):
            client.create_message(system="s", messages=[], tools=[])


def test_handler_che_solleva_non_crasha_l_agente():
    reg = ca.ToolRegistry()
    reg.register(ca.AgentTool("boom", "solleva", {"type": "object", "properties": {}},
                              ca.READ_ONLY, lambda _i: (_ for _ in ()).throw(RuntimeError("x"))))
    res = reg.dispatch("boom", {})
    assert res.refused is False            # non è un rifiuto di sicurezza
    assert "Errore" in res.content         # errore catturato e restituito come contenuto


# ── loop tool-use dell'agente (client finto) ────────────────────────────────────

def test_run_turn_esegue_tool_poi_risponde():
    reg = _registry()
    client = FakeClient([_tool_use("get_health"), _final("tutto ok")])
    agent = ca.ConfigAgent(reg, client)
    turn = agent.run_turn("come sto?")
    assert turn.text == "tutto ok"
    assert turn.capped is False
    assert len(turn.tool_results) == 1 and turn.tool_results[0].refused is False
    # il secondo giro ha ricevuto il tool_result nel contesto
    second_call_msgs = client.calls[1]["messages"]
    assert any(isinstance(m.get("content"), list)
               and any(b.get("type") == "tool_result" for b in m["content"])
               for m in second_call_msgs)


def test_run_turn_rifiuta_tool_vietato_ma_continua():
    reg = _registry()
    client = FakeClient([_tool_use("place_bet"), _final("non posso piazzare scommesse")])
    agent = ca.ConfigAgent(reg, client)
    turn = agent.run_turn("piazza la scommessa")
    assert turn.tool_results[0].refused is True
    assert turn.tool_results[0].reason == "forbidden"
    assert turn.text == "non posso piazzare scommesse"


def test_run_turn_cap_anti_loop():
    reg = _registry()
    agent = ca.ConfigAgent(reg, AlwaysToolClient("get_health"))
    turn = agent.run_turn("continua a chiamare tool")
    assert turn.capped is True
    assert len(turn.tool_results) == ca.MAX_TOOL_ITERATIONS


def test_run_turn_non_espone_tool_di_scrittura_al_modello():
    reg = _registry()
    reg.register(ca.AgentTool("set_token", "scrive", {"type": "object", "properties": {}},
                              ca.WRITE_CONFIG, lambda _i: "x"))
    client = FakeClient([_final("ciao")])
    agent = ca.ConfigAgent(reg, client)          # allow_writes=False di default
    agent.run_turn("ciao")
    offered = [s["name"] for s in client.calls[0]["tools"]]
    assert "set_token" not in offered


# ── token_store: API key Anthropic nel keyring (fail-safe) ──────────────────────
class _FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        self.store[(service, account)] = value

    def delete_password(self, service, account):
        if (service, account) not in self.store:
            raise KeyError("no entry")
        del self.store[(service, account)]


def test_api_key_roundtrip_su_keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    assert token_store.save_api_key("FAKE-API-KEY-abc") is True
    assert token_store.load_api_key() == "FAKE-API-KEY-abc"
    assert token_store.load_api_key_status() == ("FAKE-API-KEY-abc", True)
    # voce distinta dal bot token (account diverso)
    assert (token_store.SERVICE, token_store.API_KEY_ACCOUNT) in fake.store
    assert token_store.delete_api_key() is True
    assert token_store.load_api_key() is None


def test_api_key_failsafe_senza_backend(monkeypatch):
    monkeypatch.setattr(token_store, "_keyring", lambda: None)
    assert token_store.save_api_key("x") is False
    assert token_store.load_api_key() is None
    assert token_store.load_api_key_status() == (None, False)
    assert token_store.delete_api_key() is False


def test_save_api_key_vuota_non_salva(monkeypatch):
    monkeypatch.setattr(token_store, "_keyring", lambda: _FakeKeyring())
    assert token_store.save_api_key("") is False
