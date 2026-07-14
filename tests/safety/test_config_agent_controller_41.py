"""Test hard veritieri — Issue #41 PR-3 (controller assistente: ciclo di vita + worker).

Coprono la macchina a stati Abilita/Stop, le guardie (niente elaborazione da spento, enable senza
API key → ERROR), la persistenza redatta della cronologia dopo ogni turno, e il teardown pulito del
worker (sentinella + join). Nessuna rete: client Anthropic finto; nessun thread reale dove non
serve (`run_pending` esegue il loop in modo sincrono).
"""

import json
import os

from xtrader_bridge import config_agent as ca
from xtrader_bridge import config_agent_controller as ctl
from xtrader_bridge import config_store, event_log, token_store


class FakeClient:
    def __init__(self, reply="ok"):
        self.reply = reply
        self.calls = 0

    def create_message(self, *, system, messages, tools):
        self.calls += 1
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": self.reply}]}


def _controller(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    kw.setdefault("config_loader", lambda: {"chat_id": "-1001234567890"})
    return ctl.AgentController(**kw)


# ── macchina a stati ─────────────────────────────────────────────────────────────

def test_stato_iniziale_stopped(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    assert c.state == ctl.STOPPED and c.is_running() is False


def test_submit_da_stopped_rifiutato(tmp_path, monkeypatch):
    events = []
    c = _controller(tmp_path, monkeypatch, client=FakeClient(),
                    on_event=lambda k, d: events.append(k))
    assert c.submit("ciao") is False
    assert "rejected" in events


def test_enable_senza_api_key_va_in_error(tmp_path, monkeypatch):
    # Nessun client iniettato, nessun factory, keyring vuoto → ERROR, resta spento.
    monkeypatch.setattr(token_store, "load_api_key", lambda: None)
    c = _controller(tmp_path, monkeypatch)     # niente client
    assert c.enable() is False
    assert c.state == ctl.ERROR and "API key" in c.last_error


def test_enable_con_client_va_in_running(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    assert c.enable() is True and c.state == ctl.RUNNING
    c.stop()


def test_enable_idempotente(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    c.enable()
    assert c.enable() is True and c.state == ctl.RUNNING   # no-op
    c.stop()


def test_client_factory_usato_se_niente_client(tmp_path, monkeypatch):
    fake = FakeClient("da-factory")
    c = _controller(tmp_path, monkeypatch, client=None, client_factory=lambda: fake)
    assert c.enable() is True
    c.submit("hey")
    c._worker.run_pending()
    assert fake.calls == 1
    c.stop()


# ── invio + persistenza cronologia redatta ──────────────────────────────────────

def test_turno_aggiorna_e_salva_history(tmp_path, monkeypatch):
    turns = []
    c = _controller(tmp_path, monkeypatch, client=FakeClient("risposta!"),
                    on_event=lambda k, d: turns.append((k, d)))
    c.enable()
    assert c.submit("come sto?") is True
    c._worker.run_pending()      # esegue il turno in modo sincrono
    # cronologia in RAM aggiornata (user + assistant) e SALVATA su disco
    assert len(c.history.messages) == 2
    hp = os.path.join(str(tmp_path), ca.HISTORY_FILENAME)
    assert os.path.exists(hp)
    data = json.load(open(hp, encoding="utf-8"))
    assert isinstance(data["messages"], list) and len(data["messages"]) == 2
    c.stop()


def test_history_salvata_redatta(tmp_path, monkeypatch):
    # un segreto nel messaggio utente non deve finire in chiaro nel file cronologia.
    secret = "sk-ant-api03-REDACTMEPLEASE1234567890"
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    c.enable()
    c.submit(f"la mia chiave e' {secret}")
    c._worker.run_pending()
    raw = open(os.path.join(str(tmp_path), ca.HISTORY_FILENAME), encoding="utf-8").read()
    assert secret not in raw and "[REDACTED_TOKEN]" in raw
    # anche il chat_id di sessione (extra_secrets) è redatto
    assert "-1001234567890" not in raw
    c.stop()


def test_enable_carica_cronologia_persistente(tmp_path, monkeypatch):
    # una cronologia già su disco viene ricaricata a enable() («sa dove siamo»).
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    ca.ConversationHistory([{"role": "user", "content": "vecchio messaggio"}]).save(
        path=os.path.join(str(tmp_path), ca.HISTORY_FILENAME))
    c = ctl.AgentController(client=FakeClient(), config_loader=lambda: {})
    c.enable()
    assert c.history.messages == [{"role": "user", "content": "vecchio messaggio"}]
    c.stop()


def test_stop_ferma_e_azzera_worker(tmp_path, monkeypatch):
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    c.enable()
    c.stop()
    assert c.state == ctl.STOPPED and c._worker is None
    assert c.submit("ciao") is False       # da fermo, di nuovo rifiutato


# ── worker: loop, sentinella, teardown ──────────────────────────────────────────

def test_worker_process_one_messaggio_e_sentinella():
    seen = []
    w = ctl.AgentWorker(lambda t: f"h:{t}", on_result=seen.append)
    assert w._process_one("ciao") is True and seen == ["h:ciao"]
    assert w._process_one(ctl._STOP) is False     # sentinella ferma il loop


def test_worker_run_pending_si_ferma_alla_sentinella():
    seen = []
    w = ctl.AgentWorker(lambda t: t.upper(), on_result=seen.append)
    w.submit("a")
    w.submit("b")
    w.stop()                 # accoda la sentinella (nessun thread avviato → join no-op)
    w.run_pending()
    assert seen == ["A", "B"]     # elabora a,b poi si ferma alla sentinella


def test_worker_handle_che_solleva_non_uccide_il_loop():
    seen = []

    def boom(_t):
        raise RuntimeError("x")

    w = ctl.AgentWorker(boom, on_result=seen.append)
    assert w._process_one("x") is True        # il worker sopravvive
    assert seen and "[errore interno" in seen[0].text


def test_worker_thread_reale_start_submit_stop():
    # esercita il loop su un thread reale + teardown (join) — deterministico.
    import threading as _t
    got = _t.Event()
    seen = []

    def handle(text):
        return f"done:{text}"

    def on_result(r):
        seen.append(r)
        got.set()

    w = ctl.AgentWorker(handle, on_result=on_result)
    w.start()
    w.submit("x")
    assert got.wait(timeout=3.0) is True
    assert seen == ["done:x"]
    w.stop()                                  # join pulito
    assert w._thread is None


def test_worker_stop_idempotente_senza_start():
    w = ctl.AgentWorker(lambda t: t)
    w.stop()          # nessun thread avviato → non deve sollevare
    w.stop()          # idempotente
