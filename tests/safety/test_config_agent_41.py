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
    assert set(names) == {"get_config_state", "get_health", "list_parsers", "get_setup_status",
                          "list_guides", "read_guide", "test_message"}
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


# ── #41 PR-7 Blocco A: system prompt language-aware ──────────────────────────────

@pytest.mark.parametrize("app_language,needle", [
    ("IT", "italiano"),
    ("EN", "English"),
    ("ES", "español"),
])
def test_build_system_prompt_lingua(app_language, needle):
    # La clausola di risposta è nella lingua scelta all'avvio (IT/EN/ES).
    prompt = ca.build_system_prompt(app_language)
    assert needle in prompt
    # match case-insensitive: "it"/"es" minuscoli danno comunque la clausola giusta
    assert ca.build_system_prompt(app_language.lower()) == prompt
    # la base (conoscenza + regola segreti) è sempre presente
    assert "list_guides" in prompt and "REGOLA SUI SEGRETI" in prompt


@pytest.mark.parametrize("value", ["", "   ", "fr", "de", None, "xx", "IT-IT"])
def test_build_system_prompt_default_italiano_fail_closed(value):
    # Valore mancante/sconosciuto → italiano (default sicuro), mai crash né lingua a caso.
    assert ca.build_system_prompt(value).endswith(ca._LANG_REPLY_CLAUSE["IT"])


def test_build_system_prompt_regola_segreti_e_azioni_critiche():
    # La base ordina di NON chiedere/mostrare segreti e di spiegare (non eseguire) le azioni critiche.
    base = ca.build_system_prompt("IT")
    assert "non chiedere MAI" in base
    assert "modalità reale" in base and "listener live" in base
    assert "NON le esegui tu" in base


def test_default_registry_espone_lingua_al_controller():
    # `build_system_prompt` è la sola fonte del prompt: il default SYSTEM_PROMPT è la variante IT.
    assert ca.SYSTEM_PROMPT == ca.build_system_prompt("IT")


# ── #41 PR-7 Blocco A: tool di conoscenza list_guides / read_guide (sola lettura) ─

def _guide_registry(tmp_path):
    """Registry con `base_dir` iniettato su una radice-guide di test (niente file reali del repo)."""
    return ca.build_default_registry(config_loader=lambda: {}, base_dir=str(tmp_path))


def _write_guides(tmp_path):
    """Crea sul disco temporaneo alcune guide dell'allowlist con contenuto riconoscibile."""
    (tmp_path / "README.md").write_text("PANORAMICA DEL BRIDGE\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "custom_parser.md").write_text("REGOLE DEL PARSER\n", encoding="utf-8")


def test_list_guides_read_only_ed_elenca_allowlist(tmp_path):
    reg = _guide_registry(tmp_path)
    specs = {s["name"] for s in reg.tool_specs()}
    assert {"list_guides", "read_guide"} <= specs           # offerti senza allow_writes
    res = reg.dispatch("list_guides", {}, allow_writes=False)
    assert res.refused is False
    data = json.loads(res.content)
    listed = {g["name"] for g in data["guides"]}
    assert listed == set(ca.GUIDES)                         # elenca ESATTAMENTE l'allowlist
    for g in data["guides"]:
        assert g["about"]                                   # ogni voce ha una descrizione


def test_read_guide_ritorna_contenuto_da_base_dir(tmp_path):
    _write_guides(tmp_path)
    reg = _guide_registry(tmp_path)
    res = reg.dispatch("read_guide", {"name": "panoramica"}, allow_writes=False)
    assert res.refused is False
    assert "PANORAMICA DEL BRIDGE" in res.content
    assert "REGOLE DEL PARSER" in reg.dispatch("read_guide", {"name": "parser_personalizzato"}).content


def test_read_guide_nome_sconosciuto_rifiutato_no_path_traversal(tmp_path):
    # Fuori app: un segreto accanto alla radice-guide non deve MAI essere leggibile.
    (tmp_path / "config.json").write_text('{"bot_token": "SEGRETO123"}', encoding="utf-8")
    reg = _guide_registry(tmp_path)
    for evil in ["config.json", "../config.json", "/etc/passwd", "docs/../config.json", ""]:
        out = reg.dispatch("read_guide", {"name": evil}).content
        assert "SEGRETO123" not in out
        assert "non trovata" in out                         # solo i nomi in allowlist sono ammessi


def test_read_guide_file_mancante_failsafe(tmp_path):
    # Guida in allowlist ma file assente (es. docs non incluse nell'EXE) → messaggio, nessun crash.
    reg = _guide_registry(tmp_path)                         # tmp_path vuota: nessun file guida
    out = reg.dispatch("read_guide", {"name": "assistente"}).content
    assert "non disponibile" in out


def test_read_guide_troncatura(tmp_path):
    # Contenuto oltre il cap → troncato con nota (non gonfia il contesto).
    tmp_path.joinpath("README.md").write_text("X" * (ca.MAX_GUIDE_CHARS + 500), encoding="utf-8")
    reg = _guide_registry(tmp_path)
    out = reg.dispatch("read_guide", {"name": "panoramica"}).content
    assert len(out) <= ca.MAX_GUIDE_CHARS + 100
    assert "troncata" in out


def test_read_guide_e_list_guides_non_sono_write(tmp_path):
    # Sola lettura: dispatch senza allow_writes NON è rifiutato.
    reg = _guide_registry(tmp_path)
    assert reg.dispatch("list_guides", {}, allow_writes=False).refused is False
    assert reg.dispatch("read_guide", {"name": "panoramica"}, allow_writes=False).refused is False


def test_guide_allowlist_punta_a_file_reali_del_repo():
    # Verità del contratto: ogni path dell'allowlist esiste davvero nel repo (niente voci morte).
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for name, (rel_path, _desc) in ca.GUIDES.items():
        assert os.path.isfile(os.path.join(root, rel_path)), f"{name} → {rel_path} mancante"


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


# ── #41 PR-8 Blocco B: 🧪 test_message (tester SOLA-LETTURA) ─────────────────────

from xtrader_bridge import custom_parser as _cp   # noqa: E402
from xtrader_bridge import parser_io as _parser_io  # noqa: E402


def _parser_dir_con_esempio(tmp_path):
    """Salva il parser d'esempio reale del progetto in una parsers_dir di test."""
    defn = _parser_io.example_parser()
    defn.name = "Esempio"
    _cp.save_parser(defn, str(tmp_path))
    return str(tmp_path)


def _cfg_esempio(**extra):
    cfg = {"provider": "TG", "active_parser": "Esempio", "chat_id": "42",
           "recognition_mode": "NAME_ONLY", "csv_language": "IT"}
    cfg.update(extra)
    return cfg


def _tester_registry(tmp_path, cfg):
    return ca.build_default_registry(config_loader=lambda: dict(cfg), parsers_dir=str(tmp_path))


def test_test_message_riconosciuto_riga_csv(tmp_path):
    pd = _parser_dir_con_esempio(tmp_path)
    reg = _tester_registry(tmp_path, _cfg_esempio())
    res = reg.dispatch("test_message", {"message": _parser_io.fixture_message()}, allow_writes=False)
    assert res.refused is False
    data = json.loads(res.content)
    assert data["parser"] == "Esempio"
    rep = data["reports"][0]
    assert rep["recognized"] is True and rep["verdict"].startswith("✅")
    cols = rep["rows"][0]["columns"]
    # colonne del contratto XTrader, valori reali estratti/tradotti, decimale IT (virgola)
    assert list(cols.keys()) == ca.csv_writer.CSV_HEADER
    assert cols["EventName"] == "Inter v Milan"
    assert cols["BetType"] == "PUNTA"            # BACK → PUNTA via value-map
    assert cols["Price"] == "1,85"               # IT: virgola
    assert data["csv_context"]["decimal_separator"] == ","
    assert data["csv_context"]["csv_language"] == "IT"


def test_test_message_lingua_en_punto_decimale(tmp_path):
    _parser_dir_con_esempio(tmp_path)
    reg = _tester_registry(tmp_path, _cfg_esempio(csv_language="EN"))
    data = json.loads(reg.dispatch("test_message", {"message": _parser_io.fixture_message()}).content)
    assert data["csv_context"]["decimal_separator"] == "."
    assert data["reports"][0]["rows"][0]["columns"]["Price"] == "1.85"   # EN: punto


def test_test_message_non_riconosciuto_nessuna_riga_piazzabile(tmp_path):
    _parser_dir_con_esempio(tmp_path)
    reg = _tester_registry(tmp_path, _cfg_esempio())
    data = json.loads(reg.dispatch("test_message", {"message": "ciao come va, nessun segnale qui"}).content)
    # o nessun report, oppure un report NON riconosciuto (nessuna riga piazzabile): mai ✅
    reps = data.get("reports", [])
    if reps:
        assert reps[0]["recognized"] is False
        assert not any(r["placeable"] for r in reps[0]["rows"])


def test_test_message_nessun_parser_attivo(tmp_path):
    reg = _tester_registry(tmp_path, {"chat_id": "42"})   # nessun active_parser salvato
    data = json.loads(reg.dispatch("test_message", {"message": "Match: Inter v Milan"}).content)
    assert data["error"] == "no_active_parser"
    assert "message" in data and "parser" in data["message"].lower()   # messaggio guida presente


def test_test_message_vuoto(tmp_path):
    reg = _tester_registry(tmp_path, _cfg_esempio())
    assert json.loads(reg.dispatch("test_message", {"message": "   "}).content)["error"] == "empty"


def test_test_message_troppo_lungo(tmp_path):
    _parser_dir_con_esempio(tmp_path)
    reg = _tester_registry(tmp_path, _cfg_esempio())
    big = "x" * (ca.MAX_TESTER_CHARS + 1)
    assert json.loads(reg.dispatch("test_message", {"message": big}).content)["error"] == "too_long"


def test_test_message_multi_separatore(tmp_path):
    _parser_dir_con_esempio(tmp_path)
    reg = _tester_registry(tmp_path, _cfg_esempio())
    msg = _parser_io.fixture_message() + "\n---\n" + _parser_io.fixture_message()
    data = json.loads(reg.dispatch("test_message", {"message": msg}).content)
    assert len(data["reports"]) == 2
    assert all(r["recognized"] for r in data["reports"])


def test_test_message_e_read_only_non_scrive_csv(tmp_path):
    # Sola lettura: offerto senza allow_writes, dispatch non rifiutato, e NESSUN file CSV creato.
    _parser_dir_con_esempio(tmp_path)
    csv_path = tmp_path / "operativo.csv"
    reg = _tester_registry(tmp_path, _cfg_esempio(csv_path=str(csv_path)))
    assert "test_message" in [s["name"] for s in reg.tool_specs()]           # read-only, sempre offerto
    assert reg.dispatch("test_message", {"message": _parser_io.fixture_message()},
                        allow_writes=False).refused is False
    assert not csv_path.exists()        # il tester non ha creato/toccato il CSV operativo


def test_build_message_preview_non_espone_segreti(tmp_path):
    # L'output non deve contenere token/chat in chiaro anche se presenti in config.
    pd = _parser_dir_con_esempio(tmp_path)
    cfg = _cfg_esempio(bot_token="123456:FAKE-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH", chat_id="-1009999999999")
    out = json.dumps(ca.build_message_preview(cfg, _parser_io.fixture_message(),
                                              chat="-1009999999999", parsers_dir=pd))
    assert "123456:FAKE" not in out
    assert "-1009999999999" not in out
