"""Privacy/robustezza assistente #41 — AC-M8 / AC-M9 / AC-M10 (audit #114 ondata-3).

Tre finding MEDIA sull'assistente di configurazione, tutti risolti **al confine** (nulla lascia la
macchina in chiaro / la cronologia resta ripetibile):

- **AC-M8** — *cronologia avvelenabile*: un `tool_use` ORFANO (troncamento `max_tokens` a metà
  chiamata) o un content VUOTO salvato su disco e rispedito a ogni turno fa rifiutare TUTTA la
  history dall'API (400) → l'assistente resta in «[errore interno]» PERMANENTEMENTE, anche tra
  sessioni. Fix: `_repair_history` sintetizza i `tool_result` di errore mancanti e scarta i content
  vuoti, applicato sia quando si SCRIVE (`run_turn`) sia quando si LEGGE (`ConversationHistory.load`,
  auto-guarigione di un file già corrotto).
- **AC-M9** — *chat ID nel log*: il trascritto chat andava in `bridge-*.log` con solo
  `redact_secrets` (token/API key), MA non i chat ID → un chat ID digitato in chat finiva in chiaro
  nel log persistente (mentre la history su disco lo redige già). Fix: `AgentController.redact_for_log`
  redige anche i chat ID della config viva (stessa fonte della history).
- **AC-M10** — *messaggio Telegram grezzo verso l'API*: il semaforo «Ultimo messaggio» in stato
  VERDE conteneva il testo GREZZO dell'ultimo messaggio → nel tool `explain_health` finiva all'API
  Anthropic e persistito in `assistant_history.json`. Fix: redazione (hash + prima riga troncata,
  come `debug_message_payload`) in `_health_items_to_dicts` prima che lasci la macchina; il pannello
  🚦 locale dell'app non passa di qui e resta a testo pieno.

Tutti i test esercitano le funzioni REALI e falliscono sul codice pre-fix.
"""

import json

import pytest

from xtrader_bridge import config_agent as ca
from xtrader_bridge import health_check
from xtrader_bridge import config_agent_controller as ctl


# ══════════════════════════ AC-M8 — history ripetibile ══════════════════════════

def test_repair_history_sintetizza_tool_result_per_tool_use_orfano():
    """FAIL-FIRST: pre-fix un `tool_use` senza `tool_result` restava orfano → 400 permanente.
    Ora `_repair_history` aggiunge un `tool_result` di ERRORE con lo stesso `tool_use_id`."""
    orphan = [
        {"role": "user", "content": "ciao"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "tu1", "name": "get_health", "input": {}}]},
    ]
    rep = ca._repair_history(orphan)
    last = rep[-1]
    assert last["role"] == "user"
    block = last["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tu1"
    assert block.get("is_error") is True
    assert block["content"] == ca._ORPHAN_TOOL_RESULT


def test_repair_history_scarta_content_vuoto():
    """Un messaggio con content lista vuota o stringa vuota/spazi (l'API lo rifiuta) è scartato."""
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": []},       # vuoto
        {"role": "assistant", "content": "   "},     # vuoto (spazi)
    ]
    assert ca._repair_history(msgs) == [{"role": "user", "content": "hi"}]


def test_repair_history_noop_e_idempotente_su_ben_formata():
    """Su una history già ben formata (coppie tool_use/tool_result complete) è un NO-OP, e
    applicarla due volte non cambia il risultato (idempotente)."""
    good = [
        {"role": "user", "content": "ciao"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "x", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "fatto"}]},
    ]
    assert ca._repair_history(good) == good
    once = ca._repair_history([
        {"role": "assistant", "content": [{"type": "tool_use", "id": "z", "name": "x", "input": {}}]}])
    assert ca._repair_history(once) == once


def test_repair_history_unisce_risposte_parziali_senza_spezzare_il_turno():
    """Due `tool_use` nello stesso turno ma solo uno risposto (troncamento a metà del secondo):
    il turno risultati DEVE contenere entrambi gli id (uno reale, uno sintetico) in UN SOLO
    messaggio user — mai due user consecutivi che spezzerebbero la coppia."""
    partial = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "x", "input": {}},
            {"type": "tool_use", "id": "b", "name": "y", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]},
    ]
    rep = ca._repair_history(partial)
    assert len(rep) == 2
    results = rep[-1]["content"]
    ids = {b["tool_use_id"] for b in results}
    assert ids == {"a", "b"}
    synth = next(b for b in results if b["tool_use_id"] == "b")
    assert synth.get("is_error") is True


def test_repair_history_fail_safe_su_input_sporco():
    """Voci non-dict / None → ignorate senza eccezioni; input vuoto → lista vuota."""
    assert ca._repair_history(None) == []
    assert ca._repair_history([None, "x", 3, {"role": "user", "content": "ok"}]) == \
        [{"role": "user", "content": "ok"}]


def test_repair_history_scarta_content_none(tmp_path):
    """FAIL-FIRST (review Fable #133): un `content: null` (file editato) NON deve passare — l'API
    lo rifiuta e vanificherebbe l'auto-guarigione. Va scartato come i content vuoti."""
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": None},
            {"role": "assistant", "content": 123},   # anche un tipo inatteso
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}]
    out = ca._repair_history(msgs)
    assert all(isinstance(m["content"], (str, list)) and m["content"] for m in out)
    assert len(out) == 2


def test_repair_history_scarta_tool_result_orfano():
    """FAIL-FIRST (review Fugu #133): un `tool_result` SENZA un `tool_use` a monte (file editato /
    testa tagliata a metà turno) è rifiutato dall'API → va scartato, altrimenti AC-M8 resta aperto."""
    msgs = [{"role": "user", "content": "hi"},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "ghost", "content": "x"}]}]
    out = ca._repair_history(msgs)
    # il tool_result orfano è sparito; resta solo il turno testuale valido
    assert out == [{"role": "user", "content": "hi"}]


def test_repair_history_dedup_tool_use_id_duplicati():
    """Review GLM #133: id `tool_use` DUPLICATI in un turno (file corrotto) → un SOLO `tool_result`
    sintetico per id, mai un output che l'API rifiuta di nuovo."""
    msgs = [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "dup", "name": "x", "input": {}},
        {"type": "tool_use", "id": "dup", "name": "y", "input": {}}]}]
    out = ca._repair_history(msgs)
    results = out[-1]["content"]
    assert [b["tool_use_id"] for b in results] == ["dup"]


def test_repair_history_nessun_ruolo_consecutivo_uguale():
    """FAIL-FIRST (review Fable #133): il fix di un `tool_use` orfano in coda produce un turno
    `user` sintetico; se poi arriva un altro `user` (testo) si avrebbero DUE `user` consecutivi,
    che l'API rifiuta. `_repair_history` unisce i ruoli consecutivi."""
    msgs = [{"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "x", "input": {}}]},
            {"role": "user", "content": "una domanda successiva"}]
    out = ca._repair_history(msgs)
    roles = [m["role"] for m in out]
    assert not any(roles[i] == roles[i + 1] for i in range(len(roles) - 1)), roles
    # il tool_use ha comunque il suo tool_result (sintetico) e il testo utente non è perso
    flat = str(out)
    assert "tool_result" in flat and "una domanda successiva" in flat


def test_run_turn_dopo_riparazione_non_manda_due_user_consecutivi():
    """FAIL-FIRST end-to-end (review Fable #133): con una history riparata che TERMINA con un
    `tool_result` sintetico (orfano in coda), il turno successivo NON deve inviare all'API due
    messaggi `user` di fila."""
    seen = {}

    class _Client:
        def create_message(self, *, system, messages, tools):
            seen["messages"] = [m["role"] for m in messages]
            return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]}

    class _Reg:
        def tool_specs(self, include_writes=False):
            return []

    hist = ca._repair_history([
        {"role": "user", "content": "prima"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "x", "input": {}}]}])
    assert hist[-1]["role"] == "user"   # termina con il tool_result sintetico
    ca.ConfigAgent(_Reg(), _Client()).run_turn("nuova domanda", history=hist)
    roles = seen["messages"]
    assert not any(roles[i] == roles[i + 1] == "user" for i in range(len(roles) - 1)), roles


def test_run_turn_max_tokens_non_lascia_tool_use_orfano():
    """FAIL-FIRST end-to-end: un modello che si ferma per `max_tokens` mentre stava chiamando un
    tool lascerebbe (pre-fix) un `tool_use` orfano in `turn.messages` → il chiamante lo persiste e
    l'assistente si blocca. Ora `run_turn` ripara: ogni `tool_use` ha il suo `tool_result`."""
    class _MaxTokensClient:
        def create_message(self, *, system, messages, tools):
            return {"stop_reason": "max_tokens",
                    "content": [{"type": "tool_use", "id": "tuX", "name": "get_health", "input": {}}]}

    class _FakeRegistry:
        def tool_specs(self, include_writes=False):
            return []

    agent = ca.ConfigAgent(_FakeRegistry(), _MaxTokensClient())
    turn = agent.run_turn("come sto?")

    tool_use_ids = [b.get("id") for m in turn.messages if m.get("role") == "assistant"
                    and isinstance(m.get("content"), list)
                    for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
    tool_result_ids = [b.get("tool_use_id") for m in turn.messages if m.get("role") == "user"
                       and isinstance(m.get("content"), list)
                       for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert tool_use_ids == ["tuX"]
    assert "tuX" in tool_result_ids, "tool_use orfano persistito → API 400 permanente"


def test_load_auto_guarisce_un_file_history_corrotto(tmp_path):
    """FAIL-FIRST: un file `assistant_history.json` di una sessione precedente con un `tool_use`
    orfano (o content vuoto) veniva ricaricato COSÌ com'era → 400 a ogni avvio. `load` ora lo
    ripara, così l'assistente riparte utilizzabile."""
    p = tmp_path / "assistant_history.json"
    corrotto = {"version": ca.HISTORY_SCHEMA_VERSION, "messages": [
        {"role": "user", "content": "ciao"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "orph", "name": "x", "input": {}}]},
        {"role": "assistant", "content": []},  # anche un content vuoto persistito
    ]}
    p.write_text(json.dumps(corrotto), encoding="utf-8")

    hist = ca.ConversationHistory.load(path=str(p))
    msgs = hist.messages
    # niente content vuoto rimasto
    assert all(m.get("content") not in ([], "") for m in msgs)
    # il tool_use orfano ora ha il suo tool_result
    result_ids = [b.get("tool_use_id") for m in msgs if m.get("role") == "user"
                  and isinstance(m.get("content"), list)
                  for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert "orph" in result_ids


# ══════════════════════════ AC-M9 — chat ID fuori dal log ══════════════════════════

def test_redact_for_log_redige_chat_id_oltre_ai_secret_registrati():
    """FAIL-FIRST: pre-fix il log usava il solo `redact_secrets` (token/API key), NON i chat ID.
    `redact_for_log` redige anche i chat ID della config viva (chat_id, sorgenti, mapping)."""
    cfg = {"chat_id": "-1001234567890",
           "xtrader_notification_chat_id": "-100888",
           "source_chats": [{"chat_id": "987654321", "enabled": True}],
           "parser_by_chat": {"-100777": "P"}}
    c = ctl.AgentController(config_loader=lambda: dict(cfg))
    line = ("🧑 Tu: chat -1001234567890, notifiche -100888, sorgente 987654321, mapping -100777")
    out = c.redact_for_log(line)
    assert "-1001234567890" not in out
    assert "-100888" not in out          # review GLM #133: anche la chat notifiche XTrader
    assert "987654321" not in out
    assert "-100777" not in out


def test_redact_for_log_fail_safe_su_config_loader_rotto():
    """Se il config_loader manca/solleva, `redact_for_log` NON propaga l'eccezione (il logging
    della view è best-effort) e ritorna comunque la riga coi soli segreti registrati redatti."""
    def _boom():
        raise RuntimeError("config illeggibile")
    c = ctl.AgentController(config_loader=_boom)
    out = c.redact_for_log("linea qualunque 123")
    assert isinstance(out, str) and "linea qualunque" in out


def test_redact_for_log_senza_chat_id_non_altera_oltre_i_secret():
    """Config senza chat ID: nessuna over-redazione, la riga resta leggibile (solo secret redatti)."""
    c = ctl.AgentController(config_loader=lambda: {})
    assert c.redact_for_log("🤖 Assistente: ciao") == "🤖 Assistente: ciao"


# ══════════════════════════ AC-M10 — messaggio grezzo fuori dall'API ══════════════════════════

def test_health_message_verde_redatto_prima_dellapi():
    """FAIL-FIRST: pre-fix il detail del semaforo «Ultimo messaggio» VERDE (testo Telegram grezzo)
    finiva verbatim nell'output di `explain_health` → API Anthropic + `assistant_history.json`.
    Ora è redatto: solo hash + prima riga troncata; le righe successive (note riservate) spariscono."""
    grezzo = ("P.Bet. Lazio v Roma\nMercato: Over 2.5\nQuota: 1,85\nStake: 50\n"
              "Note riservate del canale privato")
    item = health_check.HealthItem("message", "Ultimo messaggio", health_check.GREEN, grezzo)
    out = ca._health_items_to_dicts([item])[0]
    assert out["detail"].startswith("[redatto:")
    assert "sha256:" in out["detail"]
    assert "Note riservate" not in out["detail"]
    assert "Mercato" not in out["detail"]   # solo la PRIMA riga, troncata


def test_health_message_redatto_anche_in_stato_non_verde():
    """FAIL-FIRST (review Fugu #133): la redazione NON deve dipendere dallo stato VERDE. Se un
    provider esponesse testo Telegram grezzo nel semaforo «message» in ROSSO (o altro stato ≠
    GIALLO), finirebbe comunque grezzo verso l'API. Va redatto per QUALSIASI stato tranne il
    GIALLO (l'unico che porta il placeholder «nessun messaggio»)."""
    # Il token sensibile è OLTRE i 40 char della prima riga, così la redazione lo elimina davvero
    # (i primi 40 char grezzi restano visibili per policy, come `debug_message_payload`).
    grezzo = "Riga iniziale lunga abbastanza da superare i quaranta NOTE_RISERVATE_DEL_CANALE"
    item = health_check.HealthItem("message", "Ultimo messaggio", health_check.RED, grezzo)
    out = ca._health_items_to_dicts([item])[0]
    assert out["detail"].startswith("[redatto:")
    assert "NOTE_RISERVATE_DEL_CANALE" not in out["detail"]


def test_health_message_giallo_placeholder_non_redatto():
    """In stato GIALLO il detail è il placeholder «nessun messaggio…», NON un messaggio grezzo:
    non deve essere trasformato in una forma «[redatto: …]» fuorviante."""
    item = health_check.HealthItem("message", "Ultimo messaggio", health_check.YELLOW,
                                   "nessun messaggio ricevuto in questa sessione")
    out = ca._health_items_to_dicts([item])[0]
    assert out["detail"] == "nessun messaggio ricevuto in questa sessione"


def test_altri_semafori_non_sono_redatti():
    """Solo il semaforo `message` è redatto: gli altri detail (path CSV, errori) devono restare
    leggibili per l'assistente (non sono contenuto di messaggi Telegram)."""
    csv_item = health_check.HealthItem("csv", "CSV", health_check.GREEN, "C:/percorso/segnali.csv")
    out = ca._health_items_to_dicts([csv_item])[0]
    assert out["detail"] == "C:/percorso/segnali.csv"


def test_build_health_report_redige_il_messaggio_live_dal_provider():
    """End-to-end: `build_health_report` con un `health_provider` LIVE che espone un messaggio
    VERDE grezzo → il report (che alimenta il tool `explain_health`) NON contiene il testo grezzo."""
    grezzo = "Segnale riservato Juventus v Milan 1X2 quota 2,10 note interne"
    provider = lambda: [health_check.HealthItem("message", "Ultimo messaggio", health_check.GREEN, grezzo)]
    rep = ca.build_health_report({}, health_provider=provider)
    msg_item = next(s for s in rep["semafori"] if s["key"] == "message")
    assert "note interne" not in msg_item["detail"]
    assert msg_item["detail"].startswith("[redatto:")
    assert rep["live"] is True
