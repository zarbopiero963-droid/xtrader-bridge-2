"""P3-23 + P3-24 + P3-25 audit #76 — hardening dell'assistente di configurazione (#41).

- **P3-23**: gli `extra_secrets` della cronologia su disco coprivano solo `chat_id` e
  `xtrader_notification_chat_id`: gli ID delle sorgenti MULTI-CHAT (`source_chats`,
  anche disattivate) e le chiavi dei mapping parser (`parser_by_chat`/
  `parser_list_by_chat` — che SONO chat ID) restavano fuori → un ID citato in
  conversazione finiva persistito in chiaro.
- **P3-24**: `RealAnthropicClient` creava `anthropic.Anthropic(api_key=...)` SENZA
  timeout: il default SDK (~10 min) pinnava il worker su una chiamata morta, il
  `join(timeout=5)` del teardown falliva e l'assistente restava non riavviabile.
- **P3-25**: la cronologia veniva rispedita INTEGRALE al modello a ogni turno
  (costi crescenti → 400/413 permanente). Ora `run_turn` la capa (messaggi E byte)
  tagliando SOLO su un confine sicuro (mai coppie tool_use/tool_result spezzate);
  il cap si propaga al file via `history.replace(turn.messages)`.

Funzioni REALI; client/modulo `anthropic` finti dove serve (nessuna chiamata live)."""

import sys
import types

import pytest

from xtrader_bridge import config_agent
from xtrader_bridge.config_agent_controller import _history_extra_secrets


# ── P3-23: segreti extra della cronologia ────────────────────────────────────────────

def test_extra_secrets_include_sorgenti_e_mapping():
    """FAIL-FIRST: pre-patch la funzione non esisteva e la lista copriva solo
    chat_id + chat notifiche."""
    cfg = {"chat_id": "-100111",
           "xtrader_notification_chat_id": "-100222",
           "source_chats": [
               {"name": "A", "chat_id": "-100333", "enabled": True},
               {"name": "B", "chat_id": "-100444", "enabled": False},  # disattivata: resta segreta
           ],
           "parser_by_chat": {"-100555": "ParserX"},
           "parser_list_by_chat": {"-100666": ["P1", "P2"]}}

    extra = _history_extra_secrets(cfg)

    assert set(extra) == {"-100111", "-100222", "-100333", "-100444",
                          "-100555", "-100666"}


def test_extra_secrets_fail_safe_su_config_malformata():
    """Voci non-dict, sorgenti non-lista, chiavi vuote: ignorate senza eccezioni."""
    assert _history_extra_secrets(None) == []
    assert _history_extra_secrets({"source_chats": "non-una-lista",
                                   "parser_by_chat": ["non-un-dict"],
                                   "parser_list_by_chat": {"  ": ["P"]},
                                   "chat_id": ""}) == []
    assert _history_extra_secrets({"source_chats": [None, {"chat_id": "  "},
                                                    {"chat_id": "-10099"}]}) == ["-10099"]


def test_extra_secrets_formato_id_anche_corti_ma_niente_spazzatura():
    """Review Fable+Fugu convergenti (PR #107): NIENTE soglia di lunghezza — un
    user ID storico corto resta un segreto e va redatto (under-redaction = leak);
    si scarta solo la spazzatura NON numerica di una config manomessa (che come
    literal-sottostringa corromperebbe la cronologia). Top-level str/strip."""
    extra = _history_extra_secrets({"chat_id": "  -100123  ",
                                    "source_chats": [{"chat_id": "-1"},
                                                     {"chat_id": "abc"}],
                                    "parser_by_chat": {"42": "P", "boh?": "X"}})
    assert extra == ["-100123", "-1", "42"]                # corti VALIDI tenuti, junk fuori


def test_redazione_id_corto_a_confini_di_cifra():
    """La causa reale (Fable/Fugu): `redact_extra` mascherava i literal come
    SOTTOSTRINGHE — l'ID «-1» mangiava «-100», date e importi. Ora i literal
    NUMERICI matchano a confini di cifra: l'ID corto è redatto solo come token
    a sé, mai dentro numeri più lunghi; i literal non numerici (token) restano
    substring (devono matchare dentro URL/path)."""
    from xtrader_bridge import event_log

    out = event_log.redact_extra("saldo -100, quota 1.85, chat -1 ok", ["-1"])

    assert "-100" in out and "1.85" in out                 # numeri legittimi INTATTI
    assert "chat -1 ok" not in out                         # l'ID a sé è redatto
    # ID dentro un numero più lungo: mai redatto a metà
    assert event_log.redact_extra("id 100123", ["10012"]) == "id 100123"


def test_redazione_non_corrompe_i_decimali():
    """FAIL-FIRST (Fable, round 3): col solo confine-cifra, literal «42» in
    «quota 42.5» diventava «[REDACTED].5» — corruzione di importi/quote. Il
    confine esclude anche il separatore decimale ([.,] seguito da cifra) su
    entrambi i lati; l'ID come token a sé resta redatto."""
    from xtrader_bridge import event_log

    out = event_log.redact_extra("quota 42.5, prezzo 3.42, linea 1,42 — id 42 qui", ["42"])

    assert "42.5" in out and "3.42" in out and "1,42" in out   # decimali INTATTI
    assert "id 42 qui" not in out                              # il token a sé è redatto


# ── P3-24: timeout esplicito sul client Anthropic ────────────────────────────────────

def test_client_creato_con_timeout_esplicito(monkeypatch):
    """FAIL-FIRST: pre-patch `Anthropic(api_key=...)` senza timeout (default SDK
    ~10 min). Stub del modulo `anthropic` che cattura i kwargs reali."""
    catturati = {}

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            catturati.update(kwargs)

    monkeypatch.setitem(sys.modules, "anthropic",
                        types.SimpleNamespace(Anthropic=_FakeAnthropic))

    client = config_agent.RealAnthropicClient("sk-test")
    client._ensure()

    assert catturati.get("api_key") == "sk-test"
    assert catturati.get("timeout") == config_agent._API_TIMEOUT_S
    assert 10 <= config_agent._API_TIMEOUT_S <= 300       # finito e ragionevole


# ── P3-25: cap della cronologia ──────────────────────────────────────────────────────

def _turno_user(i):
    return {"role": "user", "content": f"domanda {i}"}


def _turno_assistant(i):
    return [{"role": "user", "content": f"domanda {i}"},
            {"role": "assistant", "content": [{"type": "text", "text": f"risposta {i}"}]}]


def test_cap_messaggi_taglia_la_coda_su_confine_sicuro():
    """FAIL-FIRST: pre-patch `run_turn` faceva `list(history)` integrale."""
    storia = []
    for i in range(100):                                   # 100 coppie = 200 messaggi
        storia.extend(_turno_assistant(i))

    capata = config_agent._cap_history(storia)

    assert len(capata) <= config_agent._MAX_HISTORY_MESSAGES
    assert capata[0]["role"] == "user"                     # confine sicuro
    assert isinstance(capata[0]["content"], str)
    assert capata[-1] == storia[-1]                        # la coda recente è preservata


def test_cap_byte_e_pairing_tool_intatto():
    """Il taglio non deve MAI far iniziare la storia da un tool_result orfano: dopo
    il budget byte la testa viene scartata fino al primo turno user testuale."""
    tool_pair = [
        {"role": "user", "content": "cerca"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1",
                                           "name": "lookup", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                      "content": "x" * 60_000}]},
        {"role": "assistant", "content": [{"type": "text", "text": "ecco"}]},
    ]
    storia = tool_pair * 6                                 # ~360KB: oltre il budget

    capata = config_agent._cap_history(storia)

    assert capata, "qualcosa deve restare"
    assert capata[0]["role"] == "user" and isinstance(capata[0]["content"], str)
    # nessun tool_result senza il suo tool_use nella storia capata
    ids_use = {b.get("id") for m in capata if isinstance(m.get("content"), list)
               for b in m["content"] if b.get("type") == "tool_use"}
    ids_res = {b.get("tool_use_id") for m in capata if isinstance(m.get("content"), list)
               for b in m["content"] if b.get("type") == "tool_result"}
    assert ids_res <= ids_use


def test_cap_storia_corta_invariata():
    """Regressione bloccata: sotto i tetti la cronologia passa identica."""
    storia = _turno_assistant(1) + _turno_assistant(2)
    assert config_agent._cap_history(storia) == storia
    assert config_agent._cap_history(None) == []
    assert config_agent._cap_history([{"role": "assistant", "content": []}]) == []


def test_run_turn_manda_al_modello_la_storia_capata():
    """Wiring: `run_turn` con 200 messaggi in ingresso manda al client una lista
    entro il cap (+1 per il messaggio corrente) e la ritorna in `turn.messages`
    (così `replace()` capa anche il file su disco)."""
    visti = {}

    class _FakeClient:
        def create_message(self, *, system, messages, tools):
            visti["n"] = len(messages)
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}]}

    class _FakeRegistry:
        def tool_specs(self, include_writes=False):
            return []

    storia = []
    for i in range(100):
        storia.extend(_turno_assistant(i))
    agent = config_agent.ConfigAgent(_FakeRegistry(), _FakeClient())

    turn = agent.run_turn("ciao", history=storia)

    assert visti["n"] <= config_agent._MAX_HISTORY_MESSAGES + 1
    assert turn.text == "ok"
    assert len(turn.messages) <= config_agent._MAX_HISTORY_MESSAGES + 2
