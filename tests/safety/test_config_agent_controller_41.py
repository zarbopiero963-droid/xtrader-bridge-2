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
    with open(hp, encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data["messages"], list) and len(data["messages"]) == 2
    c.stop()


def test_history_salvata_redatta(tmp_path, monkeypatch):
    # un segreto nel messaggio utente non deve finire in chiaro nel file cronologia.
    # (literal spezzato: a runtime = una API key sk-ant valida, ma nel sorgente non è un literal
    # contiguo → non innesca il secret-scanner del diff dei reviewer.)
    secret = "sk-ant-" + "api03-" + "REDACTMEPLEASE1234567890"
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    c.enable()
    c.submit(f"la mia chiave e' {secret}")
    c._worker.run_pending()
    with open(os.path.join(str(tmp_path), ca.HISTORY_FILENAME), encoding="utf-8") as fh:
        raw = fh.read()
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


# ── fix review #64 ───────────────────────────────────────────────────────────────

def test_build_client_registra_api_key_dal_keyring(tmp_path, monkeypatch):
    # Fugu #64: la chiave caricata dal keyring va REGISTRATA come segreto (redazione anche se il
    # formato non combacia col pattern sk-ant). Uso una chiave che NON è pattern-riconoscibile.
    key = "custom-anthropic-key-abcdefghij"
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    monkeypatch.setattr(token_store, "load_api_key", lambda: key)

    class _FakeRC:
        def __init__(self, k):
            pass
    monkeypatch.setattr(ca, "RealAnthropicClient", _FakeRC)
    c = ctl.AgentController(config_loader=lambda: {})
    try:
        assert c.enable() is True
        # ora la chiave è mascherata da redact_secrets (registrata), pur non essendo un sk-ant
        assert event_log.redact_secrets(f"chiave {key}") == "chiave [REDACTED_TOKEN]"
    finally:
        event_log.unregister_secret(key)
        c.stop()


def test_rotazione_chiave_vecchia_resta_redatta(tmp_path, monkeypatch):
    # Fable/GPT #64: dopo la ROTAZIONE la chiave VECCHIA NON viene de-registrata → resta redatta
    # (può essere ancora valida o presente nella cronologia residua). Entrambe mascherate.
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    old = "old-anthropic-key-1234567890"
    new = "new-anthropic-key-abcdefghij"
    keys = {"v": old}
    monkeypatch.setattr(token_store, "load_api_key", lambda: keys["v"])
    monkeypatch.setattr(ca, "RealAnthropicClient", lambda k: object())
    c = ctl.AgentController(config_loader=lambda: {})
    try:
        c.enable()
        c.stop()
        keys["v"] = new                       # rotazione della chiave
        c.enable()
        c.stop()
        assert event_log.redact_secrets(f"a {old} b {new}") == \
            "a [REDACTED_TOKEN] b [REDACTED_TOKEN]"
    finally:
        event_log.unregister_secret(old)
        event_log.unregister_secret(new)


def test_emit_handler_rientrante_no_deadlock(tmp_path, monkeypatch):
    # Fable/Fugu #64: l'emit del turno avviene FUORI dal `_history_lock` (non rientrante). Un handler
    # `on_event` che richiama `stop()` durante l'emit NON deve deadlockare né crashare (il lock non è
    # tenuto durante la callback; il worker non fa join di sé). Se andasse in deadlock, il test si
    # appenderebbe (fallisce per pytest-timeout).
    holder = {}

    def on_event(kind, data):
        if kind == "turn" and holder.get("c") is not None:
            holder["c"].stop()                # stop() dallo stesso thread che emette
    c = _controller(tmp_path, monkeypatch, client=FakeClient(), on_event=on_event)
    holder["c"] = c
    c.enable()
    c.submit("ciao")
    c._worker.run_pending()                   # emit fuori dal lock + handler che chiama stop() → ok
    assert c.state == ctl.STOPPED             # lo stop dall'handler ha avuto effetto


def test_handle_message_dopo_stop_non_solleva(tmp_path, monkeypatch):
    # Fable #64: con epoch stale (dopo stop) _handle_message è un no-op (None), niente
    # AttributeError, niente messaggio-fantasma.
    events = []
    c = _controller(tmp_path, monkeypatch, client=FakeClient(),
                    on_event=lambda k, d: events.append(k))
    c.enable()
    epoch = c._epoch
    c.stop()                                  # incrementa epoch → il vecchio è stale
    assert c._handle_message("messaggio in volo dopo stop", epoch) is None
    assert "turn" not in events               # nessuna risposta-fantasma emessa


def test_epoch_worker_stale_non_tocca_nuova_sessione(tmp_path, monkeypatch):
    # CodeRabbit/GPT/GLM #64 (deterministico): un worker di una sessione precedente (epoch vecchio),
    # dopo Stop→Enable, NON deve emettere risultati né mutare la cronologia della NUOVA sessione.
    events = []
    c = _controller(tmp_path, monkeypatch, client=FakeClient("risposta vecchia"),
                    on_event=lambda k, d: events.append((k, d)))
    c.enable()
    old_epoch = c._epoch
    c.stop()
    c.enable()                                # nuova sessione: epoch avanzato, storia nuova
    new_hist = list(c.history.messages)
    events.clear()
    # il worker STALE (old_epoch) prova a elaborare un messaggio in coda
    assert c._handle_message("messaggio della vecchia sessione", old_epoch) is None
    assert all(k != "turn" for k, _ in events)          # nessun risultato emesso
    assert c.history.messages == new_hist               # cronologia nuova intatta
    c.stop()


def test_turno_scartato_se_stop_durante_run(tmp_path, monkeypatch):
    # CodeRabbit #64 (deterministico): se Stop scatta MENTRE run_turn è in volo, il turno che
    # completa dopo è STALE → scartato (niente save, niente risposta-fantasma). Il client fa
    # partire lo stop DURANTE la propria create_message.
    events, holder = [], {}

    class StopDuringClient:
        def create_message(self, *, system, messages, tools):
            holder["c"].stop()      # Stop durante il turno → epoch avanza
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "risposta tardiva"}]}

    c = _controller(tmp_path, monkeypatch, client=StopDuringClient(),
                    on_event=lambda k, d: events.append(k))
    holder["c"] = c
    c.enable()
    epoch = c._epoch
    assert c._handle_message("ciao", epoch) is None       # scartato
    assert "turn" not in events                            # nessuna risposta-fantasma
    hp = os.path.join(str(tmp_path), ca.HISTORY_FILENAME)
    if os.path.exists(hp):
        with open(hp, encoding="utf-8") as fh:
            assert json.load(fh)["messages"] == []


def test_worker_stop_thread_vivo_ritorna_false():
    # Fugu #64: se il thread è bloccato in un turno (reale in volo), stop() ritorna False e NON
    # azzera il riferimento (niente doppio worker); allo sblocco un nuovo stop() ritorna True.
    import threading
    started, release = threading.Event(), threading.Event()

    def handle(_t):
        started.set()
        release.wait(timeout=5.0)
        return "done"

    w = ctl.AgentWorker(handle)
    w.start()
    w.submit("x")
    assert started.wait(2.0) is True
    assert w.stop(timeout=0.2) is False       # bloccato nell'handle → ancora vivo
    assert w.is_alive() is True
    release.set()
    assert w.stop(timeout=3.0) is True         # sbloccato → termina, riferimento azzerato
    assert w._thread is None


def test_evento_turn_porta_epoch_corrente(tmp_path, monkeypatch):
    # #64: l'emit del `turn` avviene FUORI dal lock → deve portare l'`epoch` della sessione così il
    # consumer (GUI) può scartare le risposte-fantasma di sessioni chiuse. Qui verifichiamo che
    # l'epoch stampato combaci con quello corrente del controller.
    events = []
    c = _controller(tmp_path, monkeypatch, client=FakeClient("ok"),
                    on_event=lambda k, d: events.append((k, d)))
    c.enable()
    c.submit("ciao")
    c._worker.run_pending()
    turn_evts = [d for k, d in events if k == "turn"]
    assert turn_evts and turn_evts[-1].get("epoch") == c.current_epoch()
    c.stop()


def test_current_epoch_avanza_su_enable_e_stop(tmp_path, monkeypatch):
    # #64: `current_epoch()` è la fonte unica letta dal consumer; deve avanzare a ogni enable()/stop().
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    e0 = c.current_epoch()
    c.enable()
    e1 = c.current_epoch()
    c.stop()
    e2 = c.current_epoch()
    assert e0 < e1 < e2                        # monotòno crescente


def test_worker_stop_same_thread_ritorna_true():
    # Fugu #64: `stop()` invocato DALLO STESSO thread worker (handler sincrono che rientra) non può
    # fare join di sé → si sta auto-fermando alla sentinella già in coda → ritorna `True` (non
    # `False`: nessun call-site lo legge come «stop fallito»). Deterministico via Event.
    import threading
    holder, result, done = {}, {}, threading.Event()

    def handle(_t):
        result["ret"] = holder["w"].stop()    # stop() dal thread del worker stesso
        done.set()
        return "x"

    w = ctl.AgentWorker(handle)
    holder["w"] = w
    w.start()
    w.submit("go")
    assert done.wait(2.0) is True
    assert result["ret"] is True              # auto-fermante → True, non False


class WriteToolClient:
    """Client finto che al primo giro PROPONE `set_config_value` (senza confirm), poi risponde."""

    def __init__(self, key="theme", value="light"):
        self.key, self.value, self.n, self.offered = key, value, 0, None

    def create_message(self, *, system, messages, tools):
        self.n += 1
        self.offered = [t["name"] for t in (tools or [])]
        if self.n == 1:
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "w1", "name": "set_config_value",
                 "input": {"key": self.key, "value": self.value}}]}
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "fatto"}]}


def _write_controller(tmp_path, monkeypatch, client, path):
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    return ctl.AgentController(
        client=client,
        config_loader=lambda: config_store.load_config(path),
        config_saver=lambda cfg: config_store.save_config(cfg, path))


def test_proposta_non_scrive_finche_utente_non_applica(tmp_path, monkeypatch):
    # review #65: il tool PROPONE soltanto — nessuna scrittura finché l'utente non applica.
    events = []
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark", "chat_id": "-1001234567890"}, path)
    c = _write_controller(tmp_path, monkeypatch, WriteToolClient("theme", "light"), path)
    c._on_event = lambda k, d: events.append((k, d))
    c.enable()
    c.submit("metti il tema chiaro")
    c._worker.run_pending()
    # la modifica è PENDING, NON scritta
    assert config_store.load_config(path)["theme"] == "dark"
    assert c.pending() == {"key": "theme", "new": "light", "old": "dark", "epoch": c.current_epoch()}
    assert any(k == "pending" for k, _ in events)
    # ora l'UTENTE applica → SOLO adesso scrive
    assert c.apply_pending() is True
    saved = config_store.load_config(path)
    assert saved["theme"] == "light"                        # scritto dall'utente
    assert saved["chat_id"] == "-1001234567890"             # resto preservato
    assert c.pending() is None
    c.stop()


def test_apply_pending_senza_proposta_e_falso(tmp_path, monkeypatch):
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)
    c = _write_controller(tmp_path, monkeypatch, FakeClient(), path)
    c.enable()
    assert c.apply_pending() is False                       # niente da applicare
    c.stop()


def test_cancel_pending_non_scrive(tmp_path, monkeypatch):
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)
    c = _write_controller(tmp_path, monkeypatch, WriteToolClient("theme", "light"), path)
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()
    assert c.pending() is not None
    c.cancel_pending()
    assert c.pending() is None
    assert c.apply_pending() is False                       # dopo annulla non c'è nulla
    assert config_store.load_config(path)["theme"] == "dark"   # mai scritto
    c.stop()


def test_apply_pending_save_fallito_ritorna_false(tmp_path, monkeypatch):
    # GLM/Fable #65: apply con save fallito → False + messaggio d'errore, MAI falso «Fatto».
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)
    events = []
    c = ctl.AgentController(
        client=WriteToolClient("theme", "light"),
        config_loader=lambda: config_store.load_config(path),
        config_saver=lambda cfg: config_store.SaveResult(cfg, False, config_store.SAVE_DISK_ERROR))
    c._on_event = lambda k, d: events.append((k, d))
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()
    assert c.apply_pending() is False
    assert config_store.load_config(path)["theme"] == "dark"        # non scritto
    assert c.pending() is None
    assert any(k == "turn" and "non riuscito" in d.get("text", "") for k, d in events)
    c.stop()


def test_apply_pending_saver_che_solleva_non_crasha(tmp_path, monkeypatch):
    # un saver che SOLLEVA non deve crashare il thread GUI: esito fallito, config intatta.
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)

    def _boom(_cfg):
        raise OSError("disco in fiamme")

    c = ctl.AgentController(
        client=WriteToolClient("theme", "light"),
        config_loader=lambda: config_store.load_config(path), config_saver=_boom)
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()
    assert c.apply_pending() is False                              # nessun crash
    assert config_store.load_config(path)["theme"] == "dark"
    assert c.pending() is None
    c.stop()


def test_apply_pending_chiave_cambiata_non_sovrascrive(tmp_path, monkeypatch):
    # Fugu #65: se la STESSA chiave è cambiata concorrentemente dopo la proposta, apply NON
    # sovrascrive il valore concorrente — la proposta stantia è annullata.
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"clear_delay": 90}, path)
    c = _write_controller(tmp_path, monkeypatch, WriteToolClient("clear_delay", 45), path)
    c.enable()
    c.submit("clear 45")
    c._worker.run_pending()
    assert c.pending()["old"] == 90                       # proposta basata su 90
    config_store.save_config({"clear_delay": 120}, path)  # cambio CONCORRENTE (es. GUI «Salva»)
    assert c.apply_pending() is False                     # non sovrascrive
    assert config_store.load_config(path)["clear_delay"] == 120   # cambio concorrente preservato
    assert c.pending() is None
    c.stop()


def test_apply_pending_load_invalido_non_azzera_config(tmp_path, monkeypatch):
    # Fugu #65: un load che non dà una config valida NON deve scrivere (un fallback a {} azzererebbe
    # chat_id/csv_path/limiti). Il pending resta per il retry.
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark", "chat_id": "-1001234567890"}, path)
    valid = {"on": True}
    c = ctl.AgentController(
        client=WriteToolClient("theme", "light"),
        config_loader=lambda: (config_store.load_config(path) if valid["on"] else {}),
        config_saver=lambda cfg: config_store.save_config(cfg, path))
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()
    assert c.pending() is not None
    valid["on"] = False                                   # ora il load "fallisce" (dà {})
    assert c.apply_pending() is False                     # NON scrive
    valid["on"] = True
    saved = config_store.load_config(path)
    assert saved["theme"] == "dark" and saved["chat_id"] == "-1001234567890"   # config intatta
    assert c.pending() is not None                        # pending mantenuto per il retry
    c.stop()


def test_apply_pending_loader_che_solleva_non_crasha(tmp_path, monkeypatch):
    # GPT/Fable #65: un LOADER che solleva (OSError su disco) NON deve crashare il thread GUI →
    # trattato come «config non disponibile»; il pending resta per il retry.
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark", "chat_id": "-1001234567890"}, path)
    armed = {"on": False}

    def _loader():
        if armed["on"]:
            raise OSError("config illeggibile")
        return config_store.load_config(path)

    c = ctl.AgentController(client=WriteToolClient("theme", "light"), config_loader=_loader,
                            config_saver=lambda cfg: config_store.save_config(cfg, path))
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()
    assert c.pending() is not None
    armed["on"] = True
    assert c.apply_pending() is False                 # loader solleva → nessun crash, no write
    armed["on"] = False
    assert config_store.load_config(path)["theme"] == "dark"
    assert c.pending() is not None                    # pending mantenuto per il retry
    c.stop()


def test_apply_pending_stop_durante_apply_non_scrive(tmp_path, monkeypatch):
    # Fable #65 (commit gate): se la sessione cambia (Stop) DOPO la lettura del pending ma prima
    # della scrittura, apply NON scrive (ri-verifica identità+epoch sotto lock). Deterministico: il
    # loader fa da hook e chiama stop() durante l'apply.
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark", "chat_id": "-1001234567890"}, path)
    holder, armed = {}, {"on": False}

    def _loader():
        cfg = config_store.load_config(path)
        if armed["on"]:
            armed["on"] = False
            holder["c"].stop()            # Stop concorrente DURANTE l'apply → epoch avanza, pending svuotato
        return cfg

    c = ctl.AgentController(client=WriteToolClient("theme", "light"), config_loader=_loader,
                            config_saver=lambda cfg: config_store.save_config(cfg, path))
    holder["c"] = c
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()
    assert c.pending() is not None
    armed["on"] = True
    assert c.apply_pending() is False                 # sessione cambiata → non scrive
    assert config_store.load_config(path)["theme"] == "dark"
    assert c.pending() is None


def test_apply_pending_proposta_piu_nuova_non_emette_pending_cleared(tmp_path, monkeypatch):
    # Fable/GPT/Fugu #65: se una proposta PIÙ NUOVA subentra mentre apply è in corso (e la chiave
    # della vecchia è cambiata), il ramo stantìo NON deve emettere `pending_cleared` (nasconderebbe
    # il banner della proposta nuova) né azzerarla.
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark", "clear_delay": 90}, path)
    events, holder, armed = [], {}, {"on": False}

    def _loader():
        cfg = config_store.load_config(path)
        if armed["on"]:
            armed["on"] = False
            config_store.save_config({**cfg, "theme": "light"}, path)   # cambia la chiave di p1
            holder["c"]._stage_pending("clear_delay", 30, 90)           # proposta PIÙ NUOVA (p2)
            return config_store.load_config(path)
        return cfg

    c = ctl.AgentController(client=WriteToolClient("theme", "light"), config_loader=_loader,
                            config_saver=lambda cfg: config_store.save_config(cfg, path))
    c._on_event = lambda k, d: events.append((k, d))
    holder["c"] = c
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()                        # propone theme dark→light (p1)
    assert c.pending()["key"] == "theme"
    armed["on"] = True
    events.clear()
    assert c.apply_pending() is False              # p1 stantìa (chiave cambiata + rimpiazzata da p2)
    assert c.pending()["key"] == "clear_delay"     # la proposta PIÙ NUOVA è preservata
    assert all(k != "pending_cleared" for k, _ in events)   # niente desync del banner nuovo
    c.stop()


def test_apply_pending_proposta_nuova_durante_save_non_emette_pending_cleared(tmp_path, monkeypatch):
    # GPT/Fugu #65: se una proposta PIÙ NUOVA (chiave diversa, stesso epoch) è staged MENTRE il save
    # è in corso, il ramo di successo NON deve emettere `pending_cleared` (nasconderebbe il banner
    # della proposta nuova). Il save di p1 avviene comunque; p2 resta pendente.
    monkeypatch.setattr(config_store, "config_dir", lambda: str(tmp_path))
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark", "clear_delay": 90}, path)
    events, holder, armed = [], {}, {"on": False}

    def _saver(cfg):
        if armed["on"]:
            armed["on"] = False
            holder["c"]._stage_pending("clear_delay", 30, 90)   # p2 staged DURANTE il save
        return config_store.save_config(cfg, path)

    c = ctl.AgentController(client=WriteToolClient("theme", "light"),
                            config_loader=lambda: config_store.load_config(path), config_saver=_saver)
    c._on_event = lambda k, d: events.append((k, d))
    holder["c"] = c
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()                        # p1: theme dark→light
    armed["on"] = True
    events.clear()
    assert c.apply_pending() is True               # p1 applicato (chiave invariata)
    assert config_store.load_config(path)["theme"] == "light"   # scritto
    assert c.pending()["key"] == "clear_delay"     # la proposta PIÙ NUOVA (p2) è preservata
    assert all(k != "pending_cleared" for k, _ in events)   # niente hide del banner p2
    c.stop()


def test_stop_scarta_la_proposta_pendente(tmp_path, monkeypatch):
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)
    c = _write_controller(tmp_path, monkeypatch, WriteToolClient("theme", "light"), path)
    c.enable()
    c.submit("tema chiaro")
    c._worker.run_pending()
    assert c.pending() is not None
    c.stop()
    assert c.pending() is None                              # sessione chiusa → proposta scartata
    assert c.apply_pending() is False and config_store.load_config(path)["theme"] == "dark"


def test_apply_pending_stale_epoch_non_scrive(tmp_path, monkeypatch):
    # una proposta di una sessione, se la sessione cambia (stop→enable), non si applica più.
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)
    c = _write_controller(tmp_path, monkeypatch, WriteToolClient("theme", "light"), path)
    c.enable()
    # stage manuale legato all'epoch corrente, poi avanza sessione
    c._stage_pending("theme", "light", "dark")
    old = c.pending()
    assert old is not None
    c.stop()
    c.enable()
    # inietta la vecchia proposta (epoch stale) e prova ad applicare
    with c._pending_lock:
        c._pending = old
    assert c.apply_pending() is False
    assert config_store.load_config(path)["theme"] == "dark"
    c.stop()


def test_proposta_di_turno_stale_non_messa_in_pending(tmp_path, monkeypatch):
    # review #65 + epoch #64: se Stop scatta MENTRE il turno è in volo, la PROPOSTA che il tool
    # tenta di mettere in pending dopo è di una sessione chiusa → SCARTATA (né pending né evento).
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)
    events, holder = [], {}

    class ProposeThenStopClient:
        def __init__(self):
            self.n = 0

        def create_message(self, *, system, messages, tools):
            self.n += 1
            if self.n == 1:
                holder["c"].stop()          # Stop DURANTE il turno → epoch avanza
                return {"stop_reason": "tool_use", "content": [
                    {"type": "tool_use", "id": "w1", "name": "set_config_value",
                     "input": {"key": "theme", "value": "light"}}]}
            return {"stop_reason": "end_turn", "content": []}

    c = _write_controller(tmp_path, monkeypatch, ProposeThenStopClient(), path)
    c._on_event = lambda k, d: events.append(k)
    holder["c"] = c
    c.enable()
    epoch = c._epoch
    c._handle_message("tema chiaro", epoch)
    assert c.pending() is None                  # proposta stale scartata
    assert "pending" not in events              # nessun banner-fantasma
    assert config_store.load_config(path)["theme"] == "dark"


def test_proposta_safety_critical_non_mette_in_pending(tmp_path, monkeypatch):
    # anche con allow_writes=True, una chiave safety-critical (chat_id) NON diventa una proposta.
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark", "chat_id": "-1001234567890"}, path)
    c = _write_controller(tmp_path, monkeypatch, WriteToolClient("chat_id", "-100999999"), path)
    c.enable()
    c.submit("cambia la chat sorgente")
    c._worker.run_pending()
    assert c.pending() is None                              # nessuna proposta staged
    assert c.apply_pending() is False
    assert config_store.load_config(path)["chat_id"] == "-1001234567890"   # filtro chat intatto
    c.stop()


def test_set_config_value_offerto_al_modello(tmp_path, monkeypatch):
    path = os.path.join(str(tmp_path), "config.json")
    config_store.save_config({"theme": "dark"}, path)
    client = WriteToolClient("theme", "light")
    c = _write_controller(tmp_path, monkeypatch, client, path)
    c.enable()
    c.submit("x")
    c._worker.run_pending()
    assert "set_config_value" in client.offered            # offerto con allow_writes=True
    c.stop()


def test_enable_stop_enable_riparte(tmp_path, monkeypatch):
    # dopo uno Stop pulito (worker terminato), un nuovo enable() riparte senza residui.
    c = _controller(tmp_path, monkeypatch, client=FakeClient())
    assert c.enable() is True
    c.stop()
    assert c._worker is None                    # worker terminato e scartato
    assert c.enable() is True and c.state == ctl.RUNNING
    c.stop()
