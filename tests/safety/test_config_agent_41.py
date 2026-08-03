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
                          "list_guides", "read_guide", "test_message", "lookup_dictionary",
                          "explain_health", "why_discarded"}
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


def test_test_message_lingua_es_virgola_decimale(tmp_path):
    # GLM #70: copertura anche per ES (virgola, come IT).
    _parser_dir_con_esempio(tmp_path)
    reg = _tester_registry(tmp_path, _cfg_esempio(csv_language="ES"))
    data = json.loads(reg.dispatch("test_message", {"message": _parser_io.fixture_message()}).content)
    assert data["csv_context"]["decimal_separator"] == ","
    assert data["reports"][0]["rows"][0]["columns"]["Price"] == "1,85"


def test_test_message_separatori_senza_contenuto(tmp_path):
    # GLM #70: testo con soli separatori «---» → nessun messaggio, nessun report, nessun crash.
    _parser_dir_con_esempio(tmp_path)
    reg = _tester_registry(tmp_path, _cfg_esempio())
    data = json.loads(reg.dispatch("test_message", {"message": "---\n---\n   \n---"}).content)
    assert data["reports"] == []


def test_test_message_decimal_separator_usa_api_pubblica():
    # Fable/Fugu #70: il separatore viene dall'API PUBBLICA di csv_writer, non da un membro privato.
    assert ca.csv_writer.decimal_separator("IT") == ","
    assert ca.csv_writer.decimal_separator("ES") == ","
    assert ca.csv_writer.decimal_separator("EN") == "."
    assert ca.csv_writer.decimal_separator("") == ","        # fail-closed → IT
    assert ca.csv_writer.decimal_separator("xx") == ","      # sconosciuto → IT


def test_build_message_preview_failsafe_parser_malformato(tmp_path, monkeypatch):
    # Fugu #70: un parser attivo che fa sollevare la pipeline → messaggio guida, MAI un'eccezione.
    _parser_dir_con_esempio(tmp_path)

    class _Boom:
        name = "Boom"
        name_mapping_profiles = []
        market_mapping_profiles = []

        def batch_report(self, *a, **k):
            raise RuntimeError("parser rotto")

    # defn non-None (bypassa il ramo no_active_parser) e builder che esplode in batch_report.
    monkeypatch.setattr(ca.parser_manager, "load_primary_parser", lambda *a, **k: _Boom())
    monkeypatch.setattr(ca.parser_builder, "ParserBuilder", lambda defn: _Boom())
    data = ca.build_message_preview(_cfg_esempio(), "Match: Inter v Milan", parsers_dir=str(tmp_path))
    assert data["error"] == "internal"
    assert "malformato" in data["message"]
    assert "csv_context" in data          # contesto CSV comunque presente


def test_build_message_preview_def_legacy_senza_mapping_profiles(tmp_path):
    # CodeRabbit #70: una def LEGACY priva di *_mapping_profiles non deve dare AttributeError
    # (il builder normalizza via getattr). Deve produrre un report normale.
    _parser_dir_con_esempio(tmp_path)
    defn = _parser_io.example_parser()
    defn.name = "Esempio"
    # simula una def vecchia: rimuovi gli attributi di mapping profiles
    for attr in ("name_mapping_profiles", "market_mapping_profiles"):
        try:
            delattr(defn, attr)
        except AttributeError:
            pass
    import xtrader_bridge.config_agent as _ca

    def _fake_load_primary_parser(cfg, chat="", parsers_dir=None):
        return defn

    orig = _ca.parser_manager.load_primary_parser
    _ca.parser_manager.load_primary_parser = _fake_load_primary_parser
    try:
        data = _ca.build_message_preview(_cfg_esempio(), _parser_io.fixture_message(),
                                         parsers_dir=str(tmp_path))
    finally:
        _ca.parser_manager.load_primary_parser = orig
    assert "error" not in data            # nessun AttributeError → report normale
    assert data["reports"][0]["recognized"] is True


# ── #41 PR-9 Blocco C: 📖 lookup_dictionary (consulta dizionario, SOLA-LETTURA) ──

from xtrader_bridge import name_mapping_store as _nms   # noqa: E402
from xtrader_bridge import market_mapping_store as _mms  # noqa: E402


def _cfg_con_mapping():
    cfg = {}
    cfg = _nms.set_entries(cfg, "SerieA", [{"provider": "Juve", "betfair": "Juventus",
                                            "sport": "Calcio"}])
    cfg = _mms.set_entries(cfg, "Mercati", [{"phrase": "Multigol", "market_name": "Multigol 1-3",
                                             "selection_name": "1-3"}])
    return cfg


def test_lookup_dictionary_panoramica_senza_query():
    reg = ca.build_default_registry(config_loader=_cfg_con_mapping)
    res = reg.dispatch("lookup_dictionary", {}, allow_writes=False)
    assert res.refused is False
    data = json.loads(res.content)
    assert data["dizionario_available"] is True
    assert len(data["dizionario_markets"]) >= 1
    assert {"bettype"} <= set(data["value_maps"])
    assert data["name_mapping_profiles"] == [{"profile": "SerieA", "entries": 1}]
    assert data["market_mapping_profiles"] == [{"profile": "Mercati", "entries": 1}]


def test_lookup_dictionary_mercato_per_alias_telegram():
    reg = ca.build_default_registry(config_loader=lambda: {})
    data = json.loads(reg.dispatch("lookup_dictionary", {"query": "goal"}).content)
    assert data["dizionario_matches"], "atteso almeno un match nel dizionario per 'goal'"
    m = data["dizionario_matches"][0]
    # ogni match spiega COME è mappato: alias Telegram → valori XTrader
    assert set(m).issuperset({"market_type", "market_name", "selection_name",
                              "market_alias_telegram", "selection_alias_telegram", "bettype"})


def test_lookup_dictionary_squadra_nei_profili():
    reg = ca.build_default_registry(config_loader=_cfg_con_mapping)
    data = json.loads(reg.dispatch("lookup_dictionary", {"query": "juve"}).content)
    assert data["team_matches"] == [{"profile": "SerieA", "from": "Juve", "to_betfair": "Juventus",
                                     "sport": "Calcio", "entity_type": "", "language": ""}]


def test_lookup_dictionary_mercato_utente_e_value_map():
    reg = ca.build_default_registry(config_loader=_cfg_con_mapping)
    d1 = json.loads(reg.dispatch("lookup_dictionary", {"query": "multigol"}).content)
    assert d1["market_mapping_matches"][0]["market_name"] == "Multigol 1-3"
    # value-map bettype: alias "back" → PUNTA
    d2 = json.loads(reg.dispatch("lookup_dictionary", {"query": "back"}).content)
    assert {"value_map": "bettype", "alias": "back", "value": "PUNTA"} in d2["value_map_matches"]


def test_lookup_dictionary_termine_assente_nessun_match():
    reg = ca.build_default_registry(config_loader=lambda: {})
    data = json.loads(reg.dispatch("lookup_dictionary",
                                   {"query": "zzz_non_esiste_xyz"}).content)
    assert data["dizionario_matches"] == []
    assert data["team_matches"] == [] and data["market_mapping_matches"] == []
    assert data["value_map_matches"] == []


def test_lookup_dictionary_fail_safe_dizionario_mancante(monkeypatch):
    # Dizionario non incluso (es. EXE senza data/) → sezione marcata non disponibile, nessun crash;
    # i profili utente restano consultabili.
    def _boom(*a, **k):
        raise FileNotFoundError("dizionario assente")
    monkeypatch.setattr(ca.dizionario, "market_catalog", _boom)
    data = ca.build_dictionary_lookup(_cfg_con_mapping(), "juve")
    assert data["dizionario_available"] is False
    assert data["dizionario_matches"] == []
    assert data["team_matches"][0]["to_betfair"] == "Juventus"   # profili utente ancora ok
    ov = ca.build_dictionary_overview({})
    assert ov["dizionario_available"] is False and ov["dizionario_markets"] == []


def test_lookup_dictionary_e_read_only():
    reg = ca.build_default_registry(config_loader=lambda: {})
    assert "lookup_dictionary" in [s["name"] for s in reg.tool_specs()]     # offerto senza allow_writes
    assert reg.dispatch("lookup_dictionary", {"query": "goal"}, allow_writes=False).refused is False


def test_lookup_dictionary_non_espone_segreti():
    # Anche con token/chat in config, l'output del lookup non li contiene.
    cfg = dict(_cfg_con_mapping())
    cfg["bot_token"] = "123456:FAKE-AAAABBBBCCCCDDDDEEEEFFFFGGGG"
    cfg["chat_id"] = "-1008888888888"
    out = json.dumps(ca.build_dictionary_lookup(cfg, "juve"))
    assert "123456:FAKE" not in out and "-1008888888888" not in out


def test_lookup_dictionary_normalizza_case_e_spazi():
    # GLM/GPT #71: match case/space-insensitive (dizionario.normalize) — "  GOAL  " == "goal".
    reg = ca.build_default_registry(config_loader=lambda: {})
    a = json.loads(reg.dispatch("lookup_dictionary", {"query": "goal"}).content)["dizionario_matches"]
    b = json.loads(reg.dispatch("lookup_dictionary", {"query": "  GoAl  "}).content)["dizionario_matches"]
    assert a and a == b


def test_lookup_dictionary_truncated_overflow(monkeypatch):
    # GLM #71: quando i match superano MAX_DICT_MATCHES, la lista è capata e truncated=True.
    monkeypatch.setattr(ca, "MAX_DICT_MATCHES", 3)
    data = ca.build_dictionary_lookup({}, "goal")     # "goal" ha molti match nel dizionario
    assert len(data["dizionario_matches"]) == 3
    assert data["truncated"]["dizionario"] is True


def test_lookup_dictionary_truncated_chiave_sempre_presente(monkeypatch):
    # Fable #71: schema coerente — truncated["dizionario"] presente anche a dizionario ASSENTE.
    monkeypatch.setattr(ca.dizionario, "market_catalog",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    data = ca.build_dictionary_lookup({}, "goal")
    assert data["dizionario_available"] is False
    assert data["truncated"]["dizionario"] is False       # chiave presente, non omessa


# ── #41 PR-10 Blocco D: 🚦 explain_health + 🩺 why_discarded (diagnosi, SOLA-LETTURA) ──

from xtrader_bridge import event_journal as _ej   # noqa: E402
from xtrader_bridge.health_check import HealthItem as _HI, RED as _RED, GREEN as _GREEN  # noqa: E402


def test_explain_health_config_only_fallback():
    # Senza health_provider: valutazione da config + sonda CSV; ogni non-verde ha un advice.
    reg = ca.build_default_registry(config_loader=lambda: {"active_parser": "P1"})
    res = reg.dispatch("explain_health", {}, allow_writes=False)
    assert res.refused is False
    data = json.loads(res.content)
    assert data["live"] is False
    keys = {s["key"] for s in data["semafori"]}
    assert keys == {"telegram", "message", "parser", "signal", "csv", "confirmation", "mode"}
    for s in data["semafori"]:
        assert (s["advice"] != "") == (s["state"] != _GREEN)     # advice sse e solo se non-verde


def test_explain_health_usa_provider_live():
    # Con health_provider iniettato (stato dell'app) → live=True e riflette quei semafori.
    prov = lambda: [_HI("telegram", "Telegram", _RED, "OFFLINE — premi AVVIA")]
    reg = ca.build_default_registry(config_loader=lambda: {}, health_provider=prov)
    data = json.loads(reg.dispatch("explain_health", {}).content)
    assert data["live"] is True
    assert data["semafori"][0]["state"] == _RED
    assert data["semafori"][0]["advice"]        # RED → advice presente


def test_explain_health_provider_difettoso_ripiega():
    # Un provider dell'app che solleva → fail-safe: ripiega su config, live=False, mai crash.
    def _boom():
        raise RuntimeError("app rotta")
    reg = ca.build_default_registry(config_loader=lambda: {}, health_provider=_boom)
    data = json.loads(reg.dispatch("explain_health", {}).content)
    assert data["live"] is False and len(data["semafori"]) == 7


def test_why_discarded_ciclo_di_vita(tmp_path):
    p = str(tmp_path / "ej.jsonl")
    t = 1000.0
    for et in ("START", "SIGNAL_RECEIVED", "SIGNAL_PARSED"):   # ricevuto ma MAI scritto
        _ej.append_event(p, et, {}, now=t); t += 1
    reg = ca.build_default_registry(config_loader=lambda: {}, journal_path=p)
    data = json.loads(reg.dispatch("why_discarded", {}).content)
    assert data["journal_available"] is True
    s = data["summary"]
    assert s["last_signal_received"] is True
    assert s["last_signal_reached_csv"] is False        # non arrivato al CSV → utile per la diagnosi


def test_why_discarded_arrivato_al_csv(tmp_path):
    p = str(tmp_path / "ej.jsonl")
    t = 2000.0
    for et in ("SIGNAL_RECEIVED", "SIGNAL_PARSED", "SIGNAL_VALIDATED", "CSV_WRITTEN"):
        _ej.append_event(p, et, {}, now=t); t += 1
    data = ca.build_journal_report(journal_path=p)
    assert data["summary"]["last_signal_reached_csv"] is True


def test_why_discarded_fail_safe_diario_assente(tmp_path):
    reg = ca.build_default_registry(config_loader=lambda: {}, journal_path=str(tmp_path / "nope.jsonl"))
    data = json.loads(reg.dispatch("why_discarded", {}).content)
    assert data["journal_available"] is False and data["events"] == []


def test_why_discarded_limit_capato(tmp_path):
    p = str(tmp_path / "ej.jsonl")
    for i in range(ca.MAX_JOURNAL_EVENTS + 10):
        _ej.append_event(p, "SIGNAL_RECEIVED", {"i": i}, now=1000.0 + i)
    data = ca.build_journal_report(journal_path=p, limit=ca.MAX_JOURNAL_EVENTS)
    assert data["shown"] == ca.MAX_JOURNAL_EVENTS and data["total"] == ca.MAX_JOURNAL_EVENTS + 10


def test_diagnostic_tools_read_only():
    reg = ca.build_default_registry(config_loader=lambda: {})
    names = [s["name"] for s in reg.tool_specs()]           # offerti senza allow_writes
    assert "explain_health" in names and "why_discarded" in names
    assert reg.dispatch("explain_health", {}, allow_writes=False).refused is False
    assert reg.dispatch("why_discarded", {}, allow_writes=False).refused is False


def test_explain_health_non_espone_segreti(tmp_path):
    # Un last_error nei semafori non deve MAI contenere token in chiaro (il provider dà detail redatto,
    # ma verifichiamo che il tool non re-introduca segreti): usiamo un provider con detail innocuo.
    prov = lambda: [_HI("signal", "Ultimo segnale", "YELLOW",
                        "nessun segnale; ultimo errore: parser non ha riconosciuto")]
    reg = ca.build_default_registry(config_loader=lambda: {"bot_token": "123456:FAKE-XYZ"},
                                    health_provider=prov)
    out = reg.dispatch("explain_health", {}).content
    assert "123456:FAKE" not in out


def test_explain_health_provider_none_o_vuoto_ripiega(tmp_path):
    # GLM #72: un provider che ritorna None o [] è degenere → fallback config, live=False
    # (mai live=True su dati di fallback).
    for prov in (lambda: None, lambda: []):
        data = ca.build_health_report({"active_parser": "P1"}, health_provider=prov)
        assert data["live"] is False
        assert len(data["semafori"]) == 7


def test_explain_health_mode_usa_mode_from_cfg():
    # Fugu #72: nel fallback il semaforo Modalità usa bridge_mode.mode_from_cfg (come il pannello 🚦
    # e get_setup_status), non un get grezzo. Ne consegue la stessa semantica FAIL-CLOSED:
    from xtrader_bridge import bridge_mode
    # REALE coerente (dry_run False) → semaforo ROSSO.
    reale = ca.build_health_report({"bridge_mode": bridge_mode.REALE, "dry_run": False})
    assert next(s for s in reale["semafori"] if s["key"] == "mode")["state"] == ca.health_check.RED
    # REALE «sporco» senza dry_run=False → mode_from_cfg declassa a SIMULAZIONE (vince dry_run):
    # con il vecchio get grezzo sarebbe apparso ROSSO, mascherando il fail-closed.
    dirty = ca.build_health_report({"bridge_mode": bridge_mode.REALE})
    assert next(s for s in dirty["semafori"] if s["key"] == "mode")["state"] == ca.health_check.GREEN


def test_why_discarded_redige_segreti_nel_diario(tmp_path):
    # Fugu #72: prova la CATENA di redazione — un token nel payload del diario NON deve arrivare
    # al modello via why_discarded (event_journal redige in scrittura + il registry redige l'output).
    p = str(tmp_path / "ej.jsonl")
    token = "7654321:FAKE-BOT-TOKEN-AAAABBBBCCCCDDDDEEEE"
    _ej.append_event(p, "SIGNAL_RECEIVED", {"raw": f"segnale con {token} dentro"}, now=1000.0)
    # 1) già redatto su disco (event_journal)
    on_disk = json.dumps(_ej.read_events(p))
    assert token not in on_disk
    # 2) e comunque non esce da why_discarded (registry redige l'output come difesa finale)
    reg = ca.build_default_registry(config_loader=lambda: {}, journal_path=p)
    out = reg.dispatch("why_discarded", {}).content
    assert token not in out


# ── #214: la guida grande non arriva più amputata in silenzio ────────────────────────────────

_GUIDA_GRANDE = (
    "Preambolo che spiega di cosa parla la guida.\n\n"
    "## 1. Introduzione\n" + "a" * 200 + "\n\n"
    "## 2. Sezione intermedia\n" + "b" * 200 + "\n\n"
    "### 2.1 Sottosezione\n" + "c" * 200 + "\n\n"
    "## 3. Gate di sicurezza (perché non scrive righe sbagliate)\n" + "d" * 200 + "\n\n"
    "## 4. Coda\n" + "riempitivo\n" * 3000        # spinge il totale ben oltre il tetto
)


def _scrivi_guida_grande(tmp_path, testo=_GUIDA_GRANDE):
    tmp_path.joinpath("docs").mkdir(exist_ok=True)
    tmp_path.joinpath("docs", "custom_parser.md").write_text(testo, encoding="utf-8")
    return _guide_registry(tmp_path)


def test_guida_grande_nomina_TUTTE_le_sezioni_anche_oltre_il_taglio(tmp_path):
    """Il cuore della #214. Prima il tool restituiva i primi 12.000 caratteri e basta: le sezioni
    che cadevano oltre — fra cui «Gate di sicurezza», cioè proprio la parte su cui un utente fa le
    domande più delicate — erano invisibili, e il modello rispondeva lo stesso perché non sapeva
    che esistessero. Ora l'indice le nomina tutte."""
    reg = _scrivi_guida_grande(tmp_path)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato"}).content
    for titolo in ("1. Introduzione", "2. Sezione intermedia", "2.1 Sottosezione",
                   "3. Gate di sicurezza", "4. Coda"):
        assert titolo in out, f"sezione «{titolo}» non nominata nell'indice"
    assert "TROPPO GRANDE" in out
    assert "Preambolo che spiega" in out, "manca l'apertura della guida"
    assert len(out) <= ca.MAX_GUIDE_CHARS


def test_la_sezione_chiesta_arriva_davvero(tmp_path):
    """La contropartita dell'indice: se il modello chiede la sezione, deve riceverne il CONTENUTO,
    non un altro indice. Senza questo, l'indice sarebbe solo un modo più elegante di non rispondere."""
    reg = _scrivi_guida_grande(tmp_path)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "3. Gate di sicurezza"}).content
    assert "Gate di sicurezza" in out
    assert "d" * 200 in out, "il corpo della sezione non è stato restituito"
    assert "a" * 200 not in out, "ha restituito anche sezioni non richieste"


def test_chiedere_una_sezione_MADRE_include_le_figlie(tmp_path):
    """Una sezione arriva fino al titolo di livello pari o superiore. Chiedere «2. Sezione
    intermedia» deve dare anche la sua «2.1», che è come un lettore intende quella richiesta:
    fermarsi al primo sottotitolo restituirebbe un frammento — cioè il difetto che stiamo togliendo."""
    reg = _scrivi_guida_grande(tmp_path)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "2. Sezione intermedia"}).content
    assert "b" * 200 in out and "c" * 200 in out, "la sottosezione 2.1 è stata persa"
    assert "d" * 200 not in out, "ha sconfinato nella sezione 3"


def test_il_titolo_si_puo_citare_in_forma_abbreviata(tmp_path):
    """Il modello cita i titoli anche a memoria e accorciati. Un confronto esatto fallirebbe quasi
    sempre, e il fallimento sarebbe indistinguibile da «sezione inesistente» — cioè manderebbe
    l'assistente a dire all'utente che una pagina non c'è quando invece c'è."""
    reg = _scrivi_guida_grande(tmp_path)
    for citazione in ("gate di sicurezza", "Gate di sicurezza", "3. Gate di sicurezza",
                      "## 3. Gate di sicurezza"):
        out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                          "section": citazione}).content
        assert "d" * 200 in out, f"citazione {citazione!r} non ha trovato la sezione"


def test_sezione_inesistente_non_solleva_e_offre_l_indice(tmp_path):
    """Fail-safe: mai un'eccezione verso l'assistente, e la risposta dev'essere utile — l'indice,
    così il modello può correggere il tiro invece di arrendersi."""
    reg = _scrivi_guida_grande(tmp_path)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "sezione che non esiste"}).content
    assert "non trovata" in out
    assert "3. Gate di sicurezza" in out, "non ha offerto l'indice per riprovare"


def test_sezione_troppo_grande_lo_DICE_e_offre_le_sottosezioni(tmp_path):
    """Anche una sola sezione può eccedere il tetto (nel repo reale la più grande è 45.873
    caratteri). Il troncamento resta, ma non torna a essere cieco: si dichiara e indica dove
    stringere."""
    testo = ("## 1. Enorme\n" + "x" * (ca.MAX_GUIDE_CHARS + 5000) + "\n\n"
             "### 1.1 Prima parte\n" + "y" * 100 + "\n\n"
             "### 1.2 Seconda parte\n" + "z" * 100 + "\n")
    reg = _scrivi_guida_grande(tmp_path, testo)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "1. Enorme"}).content
    assert len(out) <= ca.MAX_GUIDE_CHARS
    assert "troppo lunga" in out
    assert "1.1 Prima parte" in out and "1.2 Seconda parte" in out


def test_guida_piccola_resta_INTERA(tmp_path):
    """Non-regressione: sotto il tetto non cambia nulla. Sarebbe un pessimo affare pagare la
    correzione con una round-trip in più su guide che stavano già bene."""
    _write_guides(tmp_path)
    reg = _guide_registry(tmp_path)
    out = reg.dispatch("read_guide", {"name": "panoramica"}).content
    assert out.strip() == "PANORAMICA DEL BRIDGE"
    assert "INDICE" not in out


def test_guida_grande_SENZA_titoli_torna_al_taglio_classico(tmp_path):
    """Se non ci sono titoli non c'è indice da dare e `section` non selezionerebbe nulla: si tronca
    come prima. La nota però dev'essere VERA — quella vecchia diceva «chiedi una sezione specifica»
    quando il tool non aveva alcun parametro per farlo."""
    reg = _scrivi_guida_grande(tmp_path, "X" * (ca.MAX_GUIDE_CHARS + 500))
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato"}).content
    assert len(out) <= ca.MAX_GUIDE_CHARS
    assert "troncata" in out and "non ha sezioni" in out


def test_read_guide_con_section_resta_SOLA_LETTURA(tmp_path):
    """La disciplina di estensione dell'assistente: il parametro nuovo non deve cambiare il
    permesso del tool né toccare il disco."""
    reg = _scrivi_guida_grande(tmp_path)

    def _istantanea():
        """Percorso → BYTE, non solo i nomi (rilievo CodeRabbit #217): confrontando l'elenco dei
        file, una riscrittura **sul posto** di una guida esistente sarebbe passata inosservata —
        ed è il modo più probabile in cui un tool di lettura potrebbe sporcare il disco."""
        return {str(p.relative_to(tmp_path)): p.read_bytes()
                for p in sorted(tmp_path.rglob("*")) if p.is_file()}

    prima = _istantanea()
    res = reg.dispatch("read_guide", {"name": "parser_personalizzato", "section": "4. Coda"},
                       allow_writes=False)
    assert res.refused is False
    assert _istantanea() == prima, "ha scritto o modificato un file sul disco"


def test_section_non_apre_una_strada_fuori_dall_allowlist(tmp_path):
    """`section` è un TITOLO, non un percorso: non deve poter diventare un modo per leggere file
    che l'allowlist non contempla. `name` resta l'unica chiave, e resta vincolato a GUIDES.

    La prima versione di questo test era **vacua** e non per la ragione che sembrava (bloccanti
    Fable 5 e Fugu Ultra #217, convergenti). Piantava l'esca in `tmp_path/segreto.md` e poi
    provava `../segreto.md`, che da `tmp_path` punta al **padre**: nessun tentativo colpiva il
    file piantato, quindi il test sarebbe passato anche con `section` usata come percorso —
    verificato per mutazione. Ora l'esca sta in **entrambi** i posti che un traversal
    raggiungerebbe, e ogni tentativo è costruito per centrarne uno.

    La radice delle guide è una **sottocartella** di `tmp_path`, così l'esca «fuori radice» resta
    comunque dentro la sandbox del test: scriverla in `tmp_path.parent` — il basetemp condiviso da
    tutti i test della sessione — poteva collidere fra run paralleli e lasciare residui su Windows
    (rilievo GPT-5.5 e Fable #217)."""
    radice = tmp_path / "guide"
    radice.mkdir()
    reg = _scrivi_guida_grande(radice)
    esca = "chiave-segreta-che-non-deve-uscire"
    radice.joinpath("segreto.md").write_text(esca, encoding="utf-8")        # dentro la radice
    tmp_path.joinpath("segreto_fuori.md").write_text(esca, encoding="utf-8")  # fuori radice, in sandbox
    tentativi = (
        "segreto.md",                       # relativo alla radice delle guide
        "./segreto.md",
        "docs/../segreto.md",               # traversal che rientra
        "../segreto_fuori.md",              # traversal che esce davvero dalla radice
        f"../{radice.name}/segreto.md",     # esce e rientra
        "/etc/passwd",                      # assoluto
    )
    for tentativo in tentativi:
        out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                          "section": tentativo}).content
        assert esca not in out, f"«{tentativo}» ha fatto uscire il contenuto del file"
        assert "root:" not in out, f"«{tentativo}» ha letto un file di sistema"
    # e `name` resta l'unica chiave dell'allowlist
    out = reg.dispatch("read_guide", {"name": "../segreto.md"}).content
    assert "non trovata" in out and esca not in out


def test_indice_delle_guide_reali_sotto_il_tetto():
    """Contratto sul repository VERO, non su file sintetici: nessuna guida dell'allowlist deve
    sforare il tetto, con o senza sezione. È la garanzia che il tool non gonfi il contesto."""
    tools = {t.name: t for t in ca.build_guide_tools()}
    for nome in sorted(ca.GUIDES):
        out = tools["read_guide"].handler({"name": nome})
        assert len(out) <= ca.MAX_GUIDE_CHARS, f"{nome}: {len(out)} caratteri"


def test_i_titoli_dentro_un_blocco_di_codice_NON_sono_sezioni(tmp_path):
    """Bloccante Fable 5 + Fugu Ultra #217, convergenti. Le guide contengono esempi di codice e di
    Markdown: una riga `## …` dentro ``` non è un titolo. Prenderla per tale creerebbe una sezione
    fasulla e sposterebbe il confine di quella vera — cioè restituirebbe all'assistente un pezzo
    di documentazione DIVERSO da quello chiesto, che è esattamente il difetto da cui nasce tutta
    questa modifica.

    Oggi nelle guide reali non ce ne sono (misurato): il bug è latente. Basterebbe una PR futura
    che documenta la sintassi Markdown perché comparisse, in silenzio."""
    testo = ("## 1. Vera\n" + "a" * 100 + "\n\n"
             "```markdown\n"
             "## 2. FINTA (esempio dentro il code fence)\n"
             "### 2.1 anche questa e' finta\n"
             "```\n\n"
             + "b" * 100 + "\n\n"
             "## 3. Vera anche questa\n" + "c" * 100 + "\n")
    reg = _scrivi_guida_grande(tmp_path, testo + "riempitivo\n" * 3000)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato"}).content
    assert "1. Vera" in out and "3. Vera anche questa" in out
    assert "FINTA" not in out, "un titolo dentro il code fence è finito nell'indice"
    assert "2.1 anche questa" not in out

    # e il confine della sezione vera non dev'essere stato spostato dal titolo fasullo
    sez = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "1. Vera"}).content
    assert "a" * 100 in sez and "b" * 100 in sez, "la sezione è stata troncata dal titolo fasullo"
    assert "c" * 100 not in sez, "ha sconfinato nella sezione 3"


def test_sezione_troncata_con_TANTE_sottosezioni_resta_sotto_il_tetto(tmp_path):
    """Bloccante Fable 5 + Fugu Ultra #217. L'elenco delle sotto-sezioni accodato a una sezione
    troppo lunga poteva crescere senza limite: `disponibili` diventava negativo e l'output valeva
    `intestazione + coda`, sforando il tetto che il tool esiste per rispettare. Misurato prima
    della correzione: **64.954 caratteri contro 12.000**.

    L'avviso di troncamento è la parte onesta e non deve sparire nel rientro: si accorcia
    l'elenco, dichiarando quante voci restano fuori."""
    sotto = "".join(
        f"### {i:03d} " + "titolo lungo per gonfiare l'elenco delle sotto-sezioni " * 4 + "\n"
        + "y" * 50 + "\n\n" for i in range(300))
    testo = "## 1. Madre\n" + "x" * (ca.MAX_GUIDE_CHARS + 3000) + "\n\n" + sotto
    reg = _scrivi_guida_grande(tmp_path, testo)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "1. Madre"}).content
    assert len(out) <= ca.MAX_GUIDE_CHARS, f"sfora il tetto: {len(out)} caratteri"
    assert "troppo lunga" in out, "l'avviso di troncamento è andato perso nel rientro"
    assert "e altre" in out, "non dice quante sotto-sezioni restano fuori"


def test_ogni_ramo_di_read_guide_rispetta_il_tetto(tmp_path):
    """Contratto trasversale: qualunque combinazione di guida e sezione, l'output non sfora. È la
    garanzia che il tool non gonfi il contesto — la ragione per cui il tetto esiste."""
    reg = _scrivi_guida_grande(tmp_path)
    casi = [{}, {"section": "1. Introduzione"}, {"section": "4. Coda"},
            {"section": "inesistente"}, {"section": ""}, {"section": "x" * 5000}]
    for extra in casi:
        out = reg.dispatch("read_guide", dict({"name": "parser_personalizzato"}, **extra)).content
        assert len(out) <= ca.MAX_GUIDE_CHARS, f"{extra}: {len(out)} caratteri"


def test_una_sezione_al_limite_NON_viene_tagliata_in_silenzio(tmp_path):
    """Rilievo Sourcery #217, ed è il più insidioso del giro: il clamp finale — la rete di
    sicurezza contro lo sforamento — poteva reintrodurre il difetto che questa PR toglie.

    Il confronto era sul solo `corpo`. Una sezione appena sotto il tetto lo superava una volta
    aggiunta l'intestazione, non entrava nel ramo «troppo lunga» (quindi nessun avviso) e veniva
    accorciata dal clamp: troncamento **silenzioso**, di nuovo. Ora il confronto include
    l'intestazione, quindi o la sezione arriva intera o il taglio si dichiara."""
    quasi = ca.MAX_GUIDE_CHARS - 60          # sotto il tetto da solo, sopra con l'intestazione
    testo = "## 1. Al limite\n" + "k" * quasi + "\n\n## 2. Altra\n" + "z" * 100 + "\n"
    reg = _scrivi_guida_grande(tmp_path, testo + "riempitivo\n" * 3000)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "1. Al limite"}).content
    assert len(out) <= ca.MAX_GUIDE_CHARS
    intera = ("k" * quasi) in out
    assert intera or "troppo lunga" in out, (
        "la sezione è stata accorciata SENZA dichiararlo: troncamento silenzioso")


def test_section_su_una_guida_senza_titoli_lo_dice_chiaramente(tmp_path):
    """Rilievo Sourcery #217. Con una guida priva di titoli, `section` non ha nulla da
    selezionare: rispondere «Sezioni disponibili:» seguito da un elenco vuoto manderebbe il
    modello a ritentare con un titolo che non esiste, in cerchio."""
    reg = _scrivi_guida_grande(tmp_path, "X" * (ca.MAX_GUIDE_CHARS + 500))
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "qualcosa"}).content
    assert "non ha sezioni indirizzabili" in out
    assert "Sezioni disponibili" not in out, "offre un elenco vuoto da cui scegliere"


def test_l_indice_non_dichiara_COMPLETO_quando_e_stato_tagliato(tmp_path):
    """Bloccante CodeRabbit #217, e nessun altro reviewer l'ha visto.

    Con abbastanza titoli l'INDICE stesso supera il tetto: il clamp finale ne tagliava la coda
    mentre l'intestazione continuava a dire «INDICE COMPLETO (N sezioni)». Misurato prima della
    correzione: **400 sezioni annunciate, 69 elencate**.

    È lo stesso difetto che questa PR esiste per togliere — una promessa di completezza su
    contenuto amputato — reintrodotto un livello più in su, e per giunta dalla rete di sicurezza
    messa a proteggere il tetto. Ora: o l'indice ci sta tutto e si dichiara completo, o si dice
    quante voci mancano."""
    testo = "Preambolo.\n\n" + "".join(
        f"## {i:04d} " + "titolo lungo che gonfia l'indice " * 5 + "\n" + "x" * 30 + "\n\n"
        for i in range(400))
    reg = _scrivi_guida_grande(tmp_path, testo)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato"}).content

    assert len(out) <= ca.MAX_GUIDE_CHARS
    elencate = out.count("\n- ")
    if "INDICE COMPLETO" in out:
        assert elencate == 400, (
            f"dichiara COMPLETO ma elenca {elencate} sezioni su 400: promessa di completezza "
            "su un elenco amputato")
    else:
        assert "INDICE PARZIALE" in out, "taglia l'indice senza dichiararlo"
        assert f"su {400}" in out or "400" in out, "non dice quante sezioni esistono davvero"
        assert elencate > 0, "non ha elencato nulla"


def test_indice_che_ci_sta_resta_dichiarato_COMPLETO(tmp_path):
    """Contropartita del test sopra: non si deve degradare a «PARZIALE» per prudenza quando
    l'indice ci sta davvero tutto — sarebbe un'altra dichiarazione falsa, all'incontrario."""
    reg = _scrivi_guida_grande(tmp_path)          # 5 sezioni, indice minuscolo
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato"}).content
    assert "INDICE COMPLETO" in out and "PARZIALE" not in out


def test_un_fence_NON_CHIUSO_non_deve_nascondere_le_sezioni_successive(tmp_path):
    """Regressione che avevo introdotto io correggendo i code fence (rilievo GPT-5.5 + Fable #217).

    Col vecchio interruttore `dentro_codice = not dentro_codice`, un fence rimasto aperto — cosa
    che capita in una guida scritta a mano — spegneva il riconoscimento fino in fondo al file e
    faceva sparire dall'indice **tutte** le sezioni successive. Misurato: 2 sezioni vere perse su 3.
    E sarebbe stato invisibile, perché il conteggio annunciato viene dallo stesso parse sbagliato.

    Nascondere titoli veri è peggio che mostrarne uno falso: nel dubbio si sbaglia nella direzione
    che lascia la guida raggiungibile. Un fence non chiuso a fine file quindi NON conta."""
    testo = ("## 1. Prima\nt\n\n"
             "```\nesempio mai chiuso\n\n"
             "## 2. Dopo il fence aperto\nt\n\n"
             "## 3. Anche questa\nt\n")
    titoli = [t for _l, t, _i, _f in ca.guide_sections(testo)]
    assert titoli == ["1. Prima", "2. Dopo il fence aperto", "3. Anche questa"], titoli


def test_fence_in_tutte_le_forme_markdown(tmp_path):
    """`~~~` è Markdown valido quanto i backtick: coprire solo i backtick lasciava passare un
    titolo finto (rilievo Fable #217, verificato eseguendo). Coperti anche il fence con linguaggio
    e quello indentato, che sono le forme usate davvero in queste guide."""
    casi = {
        "backtick":   "```",
        "linguaggio": "```python",
        "tilde":      "~~~",
        "indentato":  "  ```",
    }
    for nome, apertura in casi.items():
        chiusura = apertura.strip()[:3]
        testo = (f"## 1. Vera\nt\n\n{apertura}\n## FINTA {nome}\n{chiusura}\n\n## 2. Vera\nt\n")
        titoli = [t for _l, t, _i, _f in ca.guide_sections(testo)]
        assert not any("FINTA" in t for t in titoli), f"{nome}: titolo finto ammesso → {titoli}"
        assert titoli == ["1. Vera", "2. Vera"], f"{nome}: {titoli}"


def test_anche_l_indice_della_sezione_NON_TROVATA_dichiara_se_e_tagliato(tmp_path):
    """Bloccante Fugu #217, ed è il QUARTO sito della stessa classe: avevo cercato «promessa di
    completezza su contenuto tagliato» e ne avevo trovati tre, non quattro. Il ramo «sezione non
    trovata» costruiva l'indice intero e poi lo tagliava col clamp finale, in silenzio.

    Ora entrambi i rami passano da `render_index`, che è la fonte unica e restituisce anche se
    l'elenco è integro — così chi lo stampa non può annunciare una completezza non verificata."""
    testo = "Preambolo.\n\n" + "".join(
        f"## {i:04d} " + "titolo lungo che gonfia l'indice " * 5 + "\n" + "x" * 30 + "\n\n"
        for i in range(400))
    reg = _scrivi_guida_grande(tmp_path, testo)
    out = reg.dispatch("read_guide", {"name": "parser_personalizzato",
                                      "section": "una che non esiste"}).content
    assert len(out) <= ca.MAX_GUIDE_CHARS
    elencate = out.count("\n- ")
    if elencate < 400:
        assert "mostrate" in out, "ha tagliato l'elenco senza dichiararlo"
        assert "su 400" in out, "non dice quante sezioni esistono davvero"


def test_render_index_e_la_fonte_unica_dell_indice():
    """Regola 3. `render_index` dice sempre se l'elenco è integro: è quel booleano a impedire che
    un chiamante futuro annunci «completo» ciò che ha tagliato."""
    sezioni = [(2, f"Sezione {i:03d}", i, i + 1) for i in range(50)]
    testo, completo, mostrate = ca.render_index(sezioni, 10_000)
    assert completo is True and mostrate == 50 and testo.count("\n") == 49
    testo, completo, mostrate = ca.render_index(sezioni, 100)
    assert completo is False and 0 < mostrate < 50

    # Il conteggio su elenco VUOTO deve dire ZERO (rilievo GPT-5.5 + Fable #217): i chiamanti lo
    # ricavavano da `count("\n") + 1`, che su stringa vuota dà 1 — e annunciavano «mostrate 1 su
    # 400» mostrandone zero. Un conteggio è un fatto: lo restituisce chi lo conosce.
    testo, completo, mostrate = ca.render_index(sezioni, 0)
    assert completo is False and testo == "" and mostrate == 0


def test_elenco_vuoto_non_annuncia_MAI_di_averne_mostrata_una(tmp_path):
    """Rilievo GPT-5.5 + Fable #217, e per la sesta volta è la stessa classe: un messaggio che
    afferma una cosa falsa su ciò che ha mostrato.

    Con il budget esaurito l'elenco è vuoto, ma i chiamanti calcolavano le voci rese da
    `elenco.count("\\n") + 1` — che su stringa vuota dà **1**. Annunciavano «mostrate 1 su 400»
    mostrandone zero. Ora il conteggio arriva da `render_index`, che è l'unico a conoscerlo."""
    testo = "Preambolo.\n\n" + "".join(
        f"## {i:04d} " + "titolo molto lungo " * 30 + "\n" + "x" * 30 + "\n\n" for i in range(400))
    reg = _scrivi_guida_grande(tmp_path, testo)
    for richiesta in ({}, {"section": "una che non esiste"}):
        out = reg.dispatch("read_guide", dict({"name": "parser_personalizzato"}, **richiesta)).content
        elencate = out.count("\n- ")
        if "mostrate" in out:
            import re as _re
            dichiarate = int(_re.search(r"mostrate (\d+)", out).group(1))
            assert dichiarate == elencate, (
                f"dichiara {dichiarate} voci ma ne mostra {elencate}")


def test_fence_MISTI_non_creano_un_blocco_fantasma():
    """Rilievo Fable #217, ed è la classe peggiore: sezioni vere che spariscono.

    Accoppiando qualunque recinto con qualunque altro, un ``` dentro un blocco `~~~` — cioè un
    esempio Markdown annidato, esattamente ciò che queste guide contengono — chiudeva il blocco in
    anticipo, e il vero delimitatore finale ne apriva uno **fantasma** che nascondeva tutte le
    sezioni successive. Ora la chiusura deve combaciare per carattere e lunghezza (CommonMark)."""
    bt, tl = chr(96) * 3, "~" * 3
    testo = (f"## 1. Vera\nt\n\n"
             f"{tl}\nesempio annidato:\n{bt}\n## FINTA\n{bt}\n{tl}\n\n"
             f"## 2. Vera dopo il blocco\nt\n\n"
             f"## 3. Vera anche questa\nt\n")
    titoli = [t for _l, t, _i, _f in ca.guide_sections(testo)]
    assert titoli == ["1. Vera", "2. Vera dopo il blocco", "3. Vera anche questa"], titoli

    # Un ``` NON chiude un ~~~: il blocco resta aperto fino a fine file e quindi — per la regola
    # sui recinti non chiusi — non conta come blocco. Il compromesso è DELIBERATO e va scritto:
    # si preferisce ammettere un titolo fasullo piuttosto che nascondere sezioni vere, perché una
    # sezione in più nell'indice costa al modello una lettura a vuoto, mentre una in meno gli
    # nasconde documentazione senza che nessuno se ne accorga.
    testo2 = f"## 1. Vera\nt\n\n{tl}\n## FASULLA\n{bt}\n\n## 2. Vera\nt\n"
    titoli2 = [t for _l, t, _i, _f in ca.guide_sections(testo2)]
    assert "2. Vera" in titoli2, "un recinto non chiuso ha nascosto una sezione vera"
    assert "FASULLA" in titoli2, (
        "comportamento cambiato: se un giorno si preferisse nascondere il titolo fasullo, "
        "va deciso sapendo che si rischia di nascondere anche sezioni vere")
