"""Test hard della GLUE runtime di `App` (issue #108 P1) — eseguono i METODI REALI.

Copre i punti che l'audit #108 segnalava come «runtime app.py glue: da rafforzare»
e prioritari (P1), prima testabili solo a mano su Windows:

- `_process`: scrittura riuscita (accoda + scrive), fallimento con ROLLBACK completo
  (segnale ritentabile), gate `_running` (STOP in corso → non scrive), duplicato che
  non riscrive ma persiste lo stato;
- `_process_confirmation`: conferma rimuove il segnale e riscrive il CSV; fallimento
  scrittura → segnale già rimosso + retry BREVE programmato; gate `_running` (no-op);
- `_expire_tick`: rimuove gli scaduti e svuota il CSV; fallimento → retry programmato;
  gate `_running` (non riscrive dopo lo STOP);
- `_manual_clear`: in esecuzione svuota il CSV ATTIVO della sessione, NON il path del
  campo GUI (anti riga orfana); fallimento I/O non azzera la coda;
- `_stop`: svuota coda + CSV ATTIVO della sessione (non il path GUI cambiato).

L'harness (`tests/integration/conftest.py`) istanzia `App` headless con collaboratori
REALI; qui si iniettano solo i guasti (`write_rows`/`init_csv` che sollevano) e, per
isolare la glue di scrittura dal parser (coperto altrove), un `resolve_row` che ritorna
un `RouteResult` reale.
"""

import csv

import pytest

from xtrader_bridge import safety_guard, signal_dedupe, signal_queue


# ── helper ────────────────────────────────────────────────────────────────────

def _row(name, selection=None, price="1,90"):
    # SelectionName realistica (squadra di casa) così il lettore conferme può associare
    # l'esito XTrader al segnale (EventName + Selection), come nei messaggi reali.
    sel = selection if selection is not None else name.split(" v ")[0]
    return {"EventName": name, "MarketName": "Esito finale",
            "SelectionName": sel, "Price": price, "BetType": "PUNTA"}


def _events_in_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r["EventName"] for r in csv.DictReader(f)]


def _patch_resolve(monkeypatch, app_mod, row):
    """Forza `signal_router.resolve_row` a un esito REALE (RouteResult): isola la glue
    di scrittura dal parser, già coperto da test dedicati."""
    rr = app_mod.signal_router.RouteResult(row=row)
    monkeypatch.setattr(app_mod.signal_router, "resolve_row", lambda *a, **k: rr)


def _spy_writer(monkeypatch, app_mod, *, fail=False):
    """Avvolge `app.write_rows` per CONTARE le scritture; con `fail=True` solleva sempre
    (CSV lockato), così la write atomica non tocca il file precedente."""
    from xtrader_bridge import csv_writer
    calls = {"n": 0}

    def _w(rows, path):
        calls["n"] += 1
        if fail:
            raise OSError("CSV lockato (simulato)")
        csv_writer.write_rows(rows, path)

    monkeypatch.setattr(app_mod, "write_rows", _w)
    return calls


# ── _process ───────────────────────────────────────────────────────────────────

def test_process_write_success_accoda_e_scrive(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1")

    assert _events_in_csv(path) == ["Inter v Milan"]          # CSV scritto (1 riga)
    assert [r["EventName"] for r in q.active_rows()] == ["Inter v Milan"]
    assert a.guard_saves                                      # stato guardrail persistito
    assert (path, None) in a.expiry_calls                     # scadenza programmata


def test_process_write_failure_rollback_e_ritentabile(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    a = make_app(csv_path=path, queue=q, tracker=tracker,
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))
    _spy_writer(monkeypatch, app_mod, fail=True)

    app_mod.App._process(a, "msg-x", {"csv_path": path, "dry_run": False}, chat_id="1")

    # Coda ripristinata: nessuna riga stantia attiva dopo una write fallita.
    assert q.active_rows() == []
    # Dedupe ripristinato: lo STESSO messaggio è ritentabile (non DUPLICATE).
    assert tracker.register("msg-x").status != signal_dedupe.DUPLICATE
    # La glue programma comunque la scadenza (i segnali ripristinati devono scadere).
    assert (path, None) in a.expiry_calls
    assert any("Scrittura CSV fallita" in m for m in a.logs)


def test_process_gate_running_false_non_scrive(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q, running=False,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1")

    assert spy["n"] == 0                      # STOP in corso: nessuna scrittura
    assert q.active_rows() == []


def test_process_gate_epoch_superato_non_scrive(make_app, app_mod, monkeypatch, tmp_path):
    """#191 P1 (round 3): un callback del VECCHIO updater non deve scrivere se la sessione
    listener è cambiata (STOP→START → epoch avanzato) anche con `_running=True`. Con
    `epoch=1` ma `_listener_epoch=2`, `_process` NON scrive (gate d'ingresso `_epoch_current`).

    Fail-first: sul vecchio codice `_process` ignorava l'epoch → scriveva (running True)."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    a._listener_epoch = 2                      # un nuovo START è già intervenuto
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1", epoch=1)

    assert spy["n"] == 0                       # sessione superata: nessuna scrittura
    assert q.active_rows() == []


def test_process_epoch_cambia_durante_il_processo_non_scrive(make_app, app_mod, monkeypatch, tmp_path):
    """#191 P1 (round 3) — TOCTOU sotto il lock: l'epoch coincide all'INGRESSO (passa il gate),
    poi un STOP→START avanza l'epoch PRIMA della scrittura. Il ricontrollo sotto `_queue_lock`
    deve impedire la scrittura con la cfg della vecchia sessione.

    Si simula il cambio epoch col primo `self.after` di `_process` (eseguito subito
    dall'harness, dopo il gate d'ingresso e prima del lock di scrittura).

    Fail-first: senza il ricontrollo sotto il lock, `_process` scrive (gate d'ingresso già
    passato con epoch=1)."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    a._listener_epoch = 1                      # coincide all'ingresso → il gate iniziale passa
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))

    # Un nuovo START avanza l'epoch DOPO il gate d'ingresso ma PRIMA del lock di scrittura:
    # lo si aggancia al primo `after` invocato da `_process` (bump "received"), che l'harness
    # esegue immediatamente. Si ripristina `after` subito dopo per non riavanzare ad ogni call.
    orig_after = a.after

    def _after_then_bump_epoch(delay=None, func=None, *x, **k):
        a._listener_epoch = 2                  # STOP→START intervenuto a metà processo
        a.after = orig_after
        return orig_after(delay, func, *x, **k)

    a.after = _after_then_bump_epoch

    app_mod.App._process(a, "msg", {"csv_path": path, "dry_run": False}, chat_id="1", epoch=1)

    assert spy["n"] == 0                       # ricontrollo sotto il lock: nessuna scrittura
    assert q.active_rows() == []               # coda non mutata (segnale resta ritentabile)


def test_process_duplicato_non_riscrive_ma_persiste(make_app, app_mod, monkeypatch, tmp_path):
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    a = make_app(csv_path=path, queue=q,
                 tracker=signal_dedupe.SignalTracker(),
                 daily=safety_guard.DailyLimiter(max_per_day=10))
    _patch_resolve(monkeypatch, app_mod, _row("Inter v Milan"))
    spy = _spy_writer(monkeypatch, app_mod, fail=False)

    cfg = {"csv_path": path, "dry_run": False}
    app_mod.App._process(a, "stesso", cfg, chat_id="1")
    app_mod.App._process(a, "stesso", cfg, chat_id="1")   # duplicato

    assert spy["n"] == 1                       # la seconda volta NON riscrive
    assert _events_in_csv(path) == ["Inter v Milan"]
    assert len(a.guard_saves) >= 2             # stato persistito anche sull'esito non-WRITE


# ── _process_confirmation ───────────────────────────────────────────────────────

def _queue_with(*rows):
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    for i, r in enumerate(rows):
        q.add(r, now=1000 + i)
    return q


def test_confirmation_conferma_rimuove_e_riscrive(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"), _row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)

    app_mod.App._process_confirmation(a, "Inter v Milan Esito finale Inter piazzata",
                                      {"csv_path": path})

    assert [r["EventName"] for r in q.active_rows()] == ["Roma v Lazio"]
    assert _events_in_csv(path) == ["Roma v Lazio"]
    assert a.expiry_calls and a.expiry_calls[-1][0] == path


def test_confirmation_write_failure_segnale_rimosso_e_retry_breve(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"), _row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    _spy_writer(monkeypatch, app_mod, fail=True)

    app_mod.App._process_confirmation(a, "Inter v Milan Esito finale Inter piazzata",
                                      {"csv_path": path})

    # Il segnale è già fuori dalla coda; il CSV (write fallita) resta indietro → retry BREVE.
    assert [r["EventName"] for r in q.active_rows()] == ["Roma v Lazio"]
    assert (path, app_mod._WRITE_RETRY_DELAY) in a.expiry_calls
    assert any("dopo conferma" in m for m in a.logs)


def test_confirmation_gate_running_false_e_no_op(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q, running=False)

    app_mod.App._process_confirmation(a, "Roma v Lazio Esito finale Roma piazzata",
                                      {"csv_path": path})

    assert len(q.active_rows()) == 1               # callback tardivo: coda non mutata
    assert _events_in_csv(path) == ["Roma v Lazio"]
    assert a.expiry_calls == []


def test_confirmation_gate_epoch_superato_e_no_op(make_app, app_mod, tmp_path):
    """#191 P1 (round 3): una conferma del VECCHIO updater non deve rimuovere/riscrivere se la
    sessione listener è cambiata (epoch avanzato) anche con `_running=True`. Con `epoch=1` ma
    `_listener_epoch=2`, `_process_confirmation` è no-op (coda e CSV intatti, segnale ritentabile).

    Fail-first: sul vecchio codice ignorava l'epoch → confermava e riscriveva (running True)."""
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    a._listener_epoch = 2                          # un nuovo START è già intervenuto

    app_mod.App._process_confirmation(a, "Roma v Lazio Esito finale Roma piazzata",
                                      {"csv_path": path}, epoch=1)

    assert len(q.active_rows()) == 1               # sessione superata: coda non mutata
    assert _events_in_csv(path) == ["Roma v Lazio"]
    assert a.expiry_calls == []


# ── _expire_tick ────────────────────────────────────────────────────────────────

def test_expire_tick_rimuove_scaduti_e_svuota_csv(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)            # scade a now=10
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)   # ben oltre la scadenza

    app_mod.App._expire_tick(a, path)

    assert q.is_empty()
    assert _events_in_csv(path) == []              # CSV riportato a solo header
    # coda vuota → nessuna riprogrammazione
    assert a.expiry_calls == []


def test_expire_tick_write_failure_schedula_retry(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)
    _spy_writer(monkeypatch, app_mod, fail=True)

    app_mod.App._expire_tick(a, path)

    assert (path, app_mod._WRITE_RETRY_DELAY) in a.expiry_calls
    assert any("scadenza" in m.lower() for m in a.logs)


def test_expire_tick_gate_running_false_non_riscrive(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=10)
    q.add(_row("Inter v Milan"), now=0)
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q, running=False)
    spy = _spy_writer(monkeypatch, app_mod, fail=False)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1000.0)

    app_mod.App._expire_tick(a, path)

    assert spy["n"] == 0                            # STOP in corso: nessuna riscrittura
    assert _events_in_csv(path) == ["Inter v Milan"]   # CSV intatto


# ── _manual_clear ───────────────────────────────────────────────────────────────

def test_manual_clear_running_usa_active_path_non_gui(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    active = str(tmp_path / "attivo.csv")
    gui = str(tmp_path / "gui.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    csv_writer.write_rows([_row("Roma v Lazio")], gui)
    a = make_app(csv_path=active, queue=q, gui_csv=gui)   # GUI punta a un path DIVERSO

    app_mod.App._manual_clear(a)

    assert _events_in_csv(active) == []                  # svuotato il CSV ATTIVO
    assert _events_in_csv(gui) == ["Roma v Lazio"]       # il path GUI NON è toccato
    assert q.is_empty()


def test_manual_clear_write_failure_non_svuota_coda(make_app, app_mod, monkeypatch, tmp_path):
    from xtrader_bridge import csv_writer
    active = str(tmp_path / "attivo.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    a = make_app(csv_path=active, queue=q)
    monkeypatch.setattr(app_mod, "init_csv",
                        lambda p: (_ for _ in ()).throw(OSError("lockato")))

    app_mod.App._manual_clear(a)

    assert len(q.active_rows()) == 1                      # I/O fallito: coda NON azzerata
    assert a.expiry_calls and a.expiry_calls[-1][0] == active   # riprogramma la pulizia
    assert any("Svuotamento CSV fallito" in m for m in a.logs)


# ── _stop ───────────────────────────────────────────────────────────────────────

def test_stop_svuota_coda_e_csv_attivo_non_gui(make_app, app_mod, tmp_path):
    from xtrader_bridge import csv_writer
    active = str(tmp_path / "attivo.csv")
    gui = str(tmp_path / "gui.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    csv_writer.write_rows([_row("Roma v Lazio")], gui)
    a = make_app(csv_path=active, queue=q, gui_csv=gui, capture_schedule=False)
    a._expire_timer = None

    app_mod.App._stop(a)

    assert q.is_empty()                                  # coda in memoria svuotata
    assert _events_in_csv(active) == []                  # CSV ATTIVO svuotato (solo header)
    assert _events_in_csv(gui) == ["Roma v Lazio"]       # path GUI cambiato NON toccato
    assert a._active_csv_path is None
    assert a._running is False


def test_stop_non_sottomette_coroutine_fire_and_forget_al_loop(
        make_app, app_mod, monkeypatch, tmp_path):
    """#184 H5: con una sessione viva (`_loop` + `_tg_app` presenti) `_stop` NON deve
    fare fire-and-forget di `updater.stop()`/`stop()` sul loop con
    `run_coroutine_threadsafe`. Quelle coroutine non vengono mai attese e `loop.close()`
    nel supervisor le scarta ("Event loop is closed", eccezioni silenziate, doppio stop
    dell'updater). Lo shutdown autorevole è IN-loop (`_async_run`, dopo che
    `_is_current()` diventa False). `_stop` deve solo segnalare lo stop
    (`_running=False`, `_stop_event`) e gestire coda/CSV.

    Fail-first: sul vecchio codice `submitted` conterrebbe 2 coroutine."""
    from unittest.mock import MagicMock
    from xtrader_bridge import csv_writer

    active = str(tmp_path / "attivo.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    a = make_app(csv_path=active, queue=q, capture_schedule=False)
    a._expire_timer = None
    # Sessione viva: loop non-None e app Telegram con updater.stop()/stop(). Sul VECCHIO
    # codice `_stop` qui sottometterebbe due coroutine fire-and-forget al loop.
    a._loop = object()
    a._tg_app = MagicMock()
    submitted = []
    monkeypatch.setattr(app_mod.asyncio, "run_coroutine_threadsafe",
                        lambda coro, loop: submitted.append(coro))

    app_mod.App._stop(a)

    assert submitted == []            # nessuna coroutine fire-and-forget (regressione H5)
    assert a._stop_event.is_set()     # ma lo stop È segnalato: il supervisor esce e chiude in-loop
    assert a._running is False
    assert q.is_empty()               # coda/CSV gestiti come sempre
    assert _events_in_csv(active) == []


def test_register_secret_token_maschera_il_token_nei_log(make_app, app_mod):
    """#184 M7: `_register_secret_token` registra il bot token nel redattore di `event_log`,
    così `redact_secrets` lo maschera per-literal in QUALSIASI forma finisca in un log (anche
    non-canonica). Glue chiamata da `_load_config`/`_save_config`.

    Fail-first: senza la registrazione il token in forma non-canonica resta in chiaro."""
    from xtrader_bridge import event_log
    event_log.clear_secrets()
    try:
        a = make_app()
        token = "555:shortSecret_nonCanonico"      # porzione < 20 → la regex NON lo prende
        assert token in event_log.redact_secrets(f"x {token} y")   # baseline: non mascherato
        app_mod.App._register_secret_token(a, {"bot_token": token})
        assert token not in event_log.redact_secrets(f"❌ {token} fine")   # ora mascherato
        # Codex #184 M7: registrando il solo GREZZO, anche la forma URL-encoded è mascherata.
        from urllib.parse import quote
        enc = quote(token, safe="")
        assert enc != token and enc not in event_log.redact_secrets(f"GET /bot{enc}/x")
        # cfg senza token o non-dict → no-op senza crash
        app_mod.App._register_secret_token(a, {})
        app_mod.App._register_secret_token(a, None)
    finally:
        event_log.clear_secrets()


def test_register_secret_token_non_passa_da_getattr_su_attr_assente(app_mod):
    """#184 M7 regression (CI RecursionError): su un widget Tk un attributo ASSENTE fa ricorrere
    `__getattr__` (e il default di `getattr` NON intercetta il RecursionError). La lettura di
    `_registered_tokens`/`_running` deve avvenire via `__dict__`, non via `getattr(self, ...)`.

    Fail-first: col vecchio `getattr(self, ...)` questo solleva RecursionError, esattamente come
    nel job `integration` su CI."""
    from xtrader_bridge import event_log

    class _TkLike:
        # Imita tkinter.Misc.__getattr__: un attributo mancante delega a se stesso → ricorsione.
        def __getattr__(self, name):
            return getattr(self, name)

    event_log.clear_secrets()
    try:
        obj = _TkLike()                              # nessun _registered_tokens/_running in __dict__
        tok = "123456789:RegressionTokenValue_abcd"
        app_mod.App._register_secret_token(obj, {"bot_token": tok})   # non deve ricorrere
        assert tok in obj.__dict__.get("_registered_tokens", set())
        assert tok not in event_log.redact_secrets(f"err {tok} x")
    finally:
        event_log.clear_secrets()


def test_register_secret_token_deregistra_il_precedente_quando_cambia(make_app, app_mod):
    """#184 M7 (Sourcery): quando il bot token CAMBIA, il precedente viene deregistrato, così il
    registro dei segreti non cresce all'infinito e un vecchio token non resta mascherato per
    sempre. Quando viene RIMOSSO (cfg senza token), idem.

    Fail-first: sul vecchio codice `_register_secret_token` registrava soltanto, senza mai
    deregistrare → il vecchio token restava mascherato per sempre."""
    from xtrader_bridge import event_log
    event_log.clear_secrets()
    try:
        a = make_app(running=False)                # listener fermo: la de-registrazione è permessa (#203)
        old = "111:oldSecret_nonCanonico"          # porzioni < 20 → la regex non li prende
        new = "222:newSecret_nonCanonico"
        app_mod.App._register_secret_token(a, {"bot_token": old})
        assert old not in event_log.redact_secrets(f"x {old} y")   # vecchio mascherato
        # cambio token → il vecchio NON deve più essere mascherato, il nuovo sì
        app_mod.App._register_secret_token(a, {"bot_token": new})
        assert old in event_log.redact_secrets(f"x {old} y")       # vecchio NON più mascherato
        assert new not in event_log.redact_secrets(f"x {new} y")   # nuovo mascherato
        # rimozione token (cfg senza token) → anche il nuovo viene deregistrato
        app_mod.App._register_secret_token(a, {})
        assert new in event_log.redact_secrets(f"x {new} y")       # non più mascherato
    finally:
        event_log.clear_secrets()


def test_register_secret_token_non_deregistra_il_vecchio_mentre_attivo(make_app, app_mod):
    """#203 (Codex): se il bot token cambia mentre il listener è ATTIVO, il vecchio token NON va
    de-registrato: il poller in esecuzione lo usa ancora (snapshot a START) e de-registrarlo lo
    scriverebbe in chiaro se finisse in un log. Resta mascherato finché la sessione è attiva; la
    pulizia avviene al primo register a listener fermo (bound).

    Fail-first: senza il guard su `_running`, il cambio token de-registrava subito il vecchio →
    un'eccezione del poller con quel token l'avrebbe scritto in chiaro."""
    from xtrader_bridge import event_log
    event_log.clear_secrets()
    try:
        a = make_app()
        a._running = True                          # listener ATTIVO
        old = "111:oldSecret_nonCanonico"
        new = "222:newSecret_nonCanonico"
        app_mod.App._register_secret_token(a, {"bot_token": old})
        app_mod.App._register_secret_token(a, {"bot_token": new})   # cambio token a sessione attiva
        # ENTRAMBI restano mascherati: il vecchio è ancora in uso dal poller della sessione
        assert old not in event_log.redact_secrets(f"x {old} y")
        assert new not in event_log.redact_secrets(f"x {new} y")
        # a listener fermo, un nuovo register ripulisce i token non più correnti (bound)
        a._running = False
        app_mod.App._register_secret_token(a, {"bot_token": new})
        assert old in event_log.redact_secrets(f"x {old} y")        # ora de-registrato
        assert new not in event_log.redact_secrets(f"x {new} y")    # il corrente resta mascherato
    finally:
        event_log.clear_secrets()


def test_register_secret_token_aspetta_il_thread_del_poller(make_app, app_mod):
    """#203 (CodeRabbit): `_stop` azzera `_running` PRIMA che il thread del poller sia uscito. In
    quella finestra (`_running=False` ma `_bot_thread.is_alive()` True) il vecchio token è ancora
    in uso: la de-registrazione deve attendere che il thread sia davvero terminato.

    Fail-first: gating solo su `_running`, durante il teardown il vecchio token veniva
    de-registrato e sarebbe tornato in chiaro in un eventuale log del poller in chiusura."""
    from xtrader_bridge import event_log

    class _LiveThread:
        def is_alive(self):
            return True

    event_log.clear_secrets()
    try:
        a = make_app(running=True)
        old = "111:oldSecret_nonCanonico"
        new = "222:newSecret_nonCanonico"
        app_mod.App._register_secret_token(a, {"bot_token": old})
        # STOP in corso: _running già False MA il thread del poller è ancora vivo
        a._running = False
        a._bot_thread = _LiveThread()
        app_mod.App._register_secret_token(a, {"bot_token": new})
        assert old not in event_log.redact_secrets(f"x {old} y")    # vecchio ancora mascherato
        assert new not in event_log.redact_secrets(f"x {new} y")
        # thread del poller uscito → ora la pulizia procede
        a._bot_thread = None
        app_mod.App._register_secret_token(a, {"bot_token": new})
        assert old in event_log.redact_secrets(f"x {old} y")        # de-registrato
        assert new not in event_log.redact_secrets(f"x {new} y")    # il corrente resta mascherato
    finally:
        event_log.clear_secrets()


def test_stop_sveglia_attesa_in_loop_via_call_soon_threadsafe(make_app, app_mod, tmp_path):
    """#184 H5 / Codex #191: con una sessione viva `_stop` sveglia SUBITO l'attesa in-loop di
    `_async_run` settando `_async_stop_event` tramite `call_soon_threadsafe` (dal thread GUI).
    Così l'updater viene fermato promptamente — niente finestra di ~1s in cui il vecchio poller
    resta attivo — restando un percorso atteso in-loop (no coroutine scartate da `loop.close`).

    Fail-first: sul vecchio codice `_stop` non tocca alcun evento in-loop (`scheduled` resta vuoto)."""
    from xtrader_bridge import csv_writer

    active = str(tmp_path / "attivo.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    a = make_app(csv_path=active, queue=q, capture_schedule=False)
    a._expire_timer = None

    scheduled = []

    class _FakeLoop:
        def call_soon_threadsafe(self, fn, *args):
            scheduled.append(fn)
            fn(*args)                 # il loop processa subito il callback (simulazione)

    class _Evt:
        def __init__(self):
            self._set = False

        def set(self):
            self._set = True

        def is_set(self):
            return self._set

    evt = _Evt()
    a._loop = _FakeLoop()
    a._async_stop_event = evt

    app_mod.App._stop(a)

    assert len(scheduled) == 1        # svegliato via call_soon_threadsafe (thread-safe dal GUI)
    assert evt.is_set()               # l'attesa in-loop di _async_run è stata svegliata
    assert a._running is False


# ── #184 low-timer-lock: replace/cancel del timer di scadenza atomico sotto lock ──

def test_schedule_expiry_concorrente_non_lascia_timer_orfani(make_app, app_mod, monkeypatch):
    """#184 low-timer-lock: due caller concorrenti di `_schedule_expiry` non devono avviare un
    secondo `threading.Timer` che resta poi non referenziato (leak, double-fire idempotente). Il
    replace (cancel+create+assign+start) è atomico sotto `_timer_lock`.

    Fail-first: senza il lock, l'interleaving cancel→assign lascia DUE timer vivi (started e mai
    cancellati) invece di uno."""
    import threading as _t

    rec_lock = _t.Lock()
    started, cancelled = [], []
    proceed_b = _t.Event()       # A→B: il secondo caller può procedere
    b_done = _t.Event()          # B→A: il secondo caller ha finito il replace
    first_cancel = {"done": False}

    class _FakeTimer:
        def __init__(self, delay, fn):
            self.fn = fn
            self.daemon = False

        def start(self):
            with rec_lock:
                started.append(self)

        def cancel(self):
            with rec_lock:
                cancelled.append(self)
                is_first = not first_cancel["done"]
                first_cancel["done"] = True
            if is_first:
                # Forza l'interleaving: lascia correre il caller B e aspettalo. Nel caso CON lock,
                # B resta bloccato sull'acquisizione di `_timer_lock` → qui si esce per timeout.
                proceed_b.set()
                b_done.wait(timeout=0.5)

    monkeypatch.setattr(app_mod.threading, "Timer", _FakeTimer)
    a = make_app(capture_schedule=False)      # usa il `_schedule_expiry` REALE
    a._timer_lock = _t.Lock()                 # __init__ non è girato (object.__new__): lo creiamo
    a._expire_timer = None

    path = "out.csv"
    a._schedule_expiry(path, delay=60)        # pre-seed: T0 (nessun cancel: era None)

    def _caller_b():
        proceed_b.wait(timeout=1.0)
        a._schedule_expiry(path, delay=60)    # caller B
        b_done.set()

    tb = _t.Thread(target=_caller_b)
    tb.start()
    a._schedule_expiry(path, delay=60)        # caller A: cancella T0 → handoff verso B
    tb.join(timeout=2.0)
    assert not tb.is_alive()

    # Esattamente UN timer vivo (avviato e non cancellato): nessun orfano.
    live = [t for t in started if t not in cancelled]
    assert len(live) == 1
    # Il cancel di teardown (sotto lock) lo ferma: nessun timer vivo residuo.
    a._cancel_expiry_timer()
    assert [t for t in started if t not in cancelled] == []


# ── PR-08c: risincronizzazione del campo token dopo un load incompleto (#140/#256) ──
#
# Dopo un outage del keyring al load, `config_store` lascia il marker
# `_token_load_incomplete` e `bot_token=""`: il campo password GUI resta vuoto pur
# esistendo una credenziale. `save_config` reidrata il token e consuma il marker, ma il
# campo restava vuoto → il save successivo lo scambiava per un clear e CANCELLAVA il token
# (perdita al 2° save). PR-08c risincronizza il campo (`_resync_token_field`) su TUTTI i path
# di save/START. Questi test esercitano i metodi REALI di `App`.

class _FakeTokenEntry:
    """Stand-in del campo password del token (`_e_token`): `get`/`delete`/`insert` con la
    stessa semantica di un `CTkEntry` (insert appende; delete(0,'end') azzera)."""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def delete(self, first, last=None):
        self._v = ""

    def insert(self, index, s):
        self._v = (self._v or "") + str(s)


class _FakeKeyring:
    """Backend keyring simulato per `config_store.token_store` (monkeypatch): `readable`/
    `writable`/`available` controllabili per riprodurre un outage e il suo rientro."""

    def __init__(self, stored=None, available=True, readable=True, writable=True,
                 become_readable_at=None):
        self.stored = stored
        self._available = available
        self.readable = readable
        self.writable = writable
        self.deleted = 0
        # `become_readable_at`: numero della lettura a partire dalla quale il keyring diventa
        # leggibile (per simulare un keyring che torna su a metà di un `_save_config`: la
        # lettura pre-save MANCA, quella interna a `save_config` RIESCE). None = usa `readable`.
        self.become_readable_at = become_readable_at
        self.reads = 0

    def available(self):
        return self._available

    def _readable_now(self):
        self.reads += 1
        if self.become_readable_at is None:
            return self.readable
        return self.reads >= self.become_readable_at

    def load_token(self):
        return self.stored if self._readable_now() else None

    def load_token_status(self):
        return (self.stored, True) if self._readable_now() else (None, False)

    def save_token(self, tok):
        if not self.writable:
            return False
        self.stored = tok
        return True

    def delete_token(self):
        if not self.writable:
            return False
        self.stored = None
        self.deleted += 1
        return True


def _token_marker():
    from xtrader_bridge import config_store
    return config_store.TOKEN_LOAD_INCOMPLETE_KEY


def test_had_incomplete_token_load_riflette_il_marker(make_app, app_mod):
    """`_had_incomplete_token_load` è True solo se la config viva porta il marker #140."""
    a = make_app(config={"bot_token": "", _token_marker(): True})
    assert app_mod.App._had_incomplete_token_load(a) is True
    a._config = {"bot_token": "ABC"}                 # nessun marker
    assert app_mod.App._had_incomplete_token_load(a) is False
    a._config = "non-dict"                            # robusto su config non-dict
    assert app_mod.App._had_incomplete_token_load(a) is False


def test_resync_reidrata_dal_config_e_consuma_marker(make_app, app_mod):
    """Post-save: la config è già stata reidratata (`bot_token` valorizzato) ma il campo è
    vuoto → il refill ripopola il campo dal token in config, lo registra nel redattore e
    consuma il marker. Caso dei save non-GUI / tab Tools (had passato esplicitamente)."""
    from xtrader_bridge import event_log
    event_log.clear_secrets()
    try:
        a = make_app(config={"bot_token": "999:REHYDRATED", "bot_token_storage": "keyring"})
        a._e_token = _FakeTokenEntry("")
        # had=True anche se il marker è già stato consumato da save_config (caso reale post-save).
        app_mod.App._resync_token_field(a, True)
        assert a._e_token.get() == "999:REHYDRATED"            # campo risincronizzato
        assert _token_marker() not in a._config               # marker consumato (no-op se già assente)
        assert "999:REHYDRATED" not in event_log.redact_secrets("log 999:REHYDRATED")  # registrato
    finally:
        event_log.clear_secrets()


def test_resync_legge_il_keyring_quando_config_non_ancora_reidratata(make_app, app_mod, monkeypatch):
    """START prima di qualunque save: la config ha il marker ma `bot_token=""` (non ancora
    reidratato). Il refill legge DIRETTAMENTE dal keyring, ripopola il campo e consuma il marker."""
    from xtrader_bridge import config_store, event_log
    fake = _FakeKeyring(stored="123:FROMKEYRING", readable=True)
    monkeypatch.setattr(config_store, "token_store", fake)
    event_log.clear_secrets()
    try:
        a = make_app(config={"bot_token": "", "bot_token_storage": "keyring", _token_marker(): True})
        a._e_token = _FakeTokenEntry("")
        app_mod.App._resync_token_field(a)                    # had dedotto dal marker
        assert a._e_token.get() == "123:FROMKEYRING"
        assert _token_marker() not in a._config
        assert "123:FROMKEYRING" not in event_log.redact_secrets("x 123:FROMKEYRING y")
    finally:
        event_log.clear_secrets()


def test_resync_no_op_su_clear_deliberato_senza_marker(make_app, app_mod, monkeypatch):
    """Clear DELIBERATO: load COMPLETO (nessun marker), l'utente ha svuotato il campo a mano.
    Il refill NON deve reidratare nulla, altrimenti resusciterebbe un clear voluto (Codex)."""
    from xtrader_bridge import config_store
    fake = _FakeKeyring(stored="should:NOT:berestored", readable=True)
    monkeypatch.setattr(config_store, "token_store", fake)
    a = make_app(config={"bot_token": "OLD", "bot_token_storage": "keyring"})   # nessun marker
    a._e_token = _FakeTokenEntry("")                          # campo svuotato a mano
    app_mod.App._resync_token_field(a)
    assert a._e_token.get() == ""                             # resta vuoto: clear preservato


def test_resync_non_sovrascrive_un_token_digitato(make_app, app_mod, monkeypatch):
    """Campo NON vuoto (token appena digitato dall'utente): il refill non deve mai
    sovrascriverlo, anche se il marker è presente."""
    from xtrader_bridge import config_store
    fake = _FakeKeyring(stored="999:KEYRING", readable=True)
    monkeypatch.setattr(config_store, "token_store", fake)
    a = make_app(config={"bot_token": "", "bot_token_storage": "keyring", _token_marker(): True})
    a._e_token = _FakeTokenEntry("888:TYPED_BY_USER")
    app_mod.App._resync_token_field(a)
    assert a._e_token.get() == "888:TYPED_BY_USER"            # input dell'utente intatto


def test_resync_keyring_ancora_giu_mantiene_il_marker(make_app, app_mod, monkeypatch):
    """Keyring ANCORA illeggibile al refill: niente token da reidratare → campo resta vuoto e
    il marker NON viene consumato, così la protezione sopravvive per il retry successivo."""
    from xtrader_bridge import config_store
    fake = _FakeKeyring(stored="123:HIDDEN", readable=False)  # lettura fallita
    monkeypatch.setattr(config_store, "token_store", fake)
    a = make_app(config={"bot_token": "", "bot_token_storage": "keyring", _token_marker(): True})
    a._e_token = _FakeTokenEntry("")
    app_mod.App._resync_token_field(a)
    assert a._e_token.get() == ""                             # niente reidratazione
    assert a._config.get(_token_marker()) is True            # marker PRESERVATO per il retry


def test_due_save_dopo_outage_keyring_non_perdono_il_token(make_app, app_mod, monkeypatch, tmp_path):
    """REGRESSIONE END-TO-END (perdita al 2° save, Codex #256): outage del keyring al load →
    marker + campo vuoto. Keyring rientrato. Un save non-GUI (`_on_debug_toggle`) reidrata la
    config; senza PR-08c il campo restava vuoto e il Salva principale (`_save_config`) lo
    cancellava. Con il fix il campo è risincronizzato e il 2° save NON cancella il token.

    Fail-first: sul vecchio `app.py` (senza `_resync_token_field`) il primo assert sul campo
    fallisce (resta vuoto) e il token verrebbe poi cancellato dal keyring."""
    from xtrader_bridge import config_store, event_log
    cfgfile = tmp_path / "config.json"
    fake = _FakeKeyring(stored="999:REALTOKEN", readable=True)
    monkeypatch.setattr(config_store, "token_store", fake)
    monkeypatch.setattr(app_mod, "CONFIG_FILE", str(cfgfile))
    event_log.clear_secrets()
    try:
        a = make_app(running=False, config={
            "bot_token": "", "bot_token_storage": "keyring", _token_marker(): True,
            "chat_id": "123456", "csv_path": str(tmp_path / "segnali.csv"),
            "provider": "TelegramBot", "dry_run": True,
        })
        a._e_token = _FakeTokenEntry("")
        a._e_chat = _FakeTokenEntry("123456")
        a._e_csv = _FakeTokenEntry(str(tmp_path / "segnali.csv"))
        a._e_provider = _FakeTokenEntry("TelegramBot")
        a._e_delay = _FakeTokenEntry("90")
        a._adv = {}
        a._save_ok = True
        a._debug_var = _FakeTokenEntry(True)                 # .get() → True
        a._refresh_listened_chats = lambda *x, **k: None

        # 1º save (non-GUI): reidrata la config e — con il fix — risincronizza il campo.
        app_mod.App._on_debug_toggle(a)
        assert a._e_token.get() == "999:REALTOKEN"           # campo risincronizzato (fail-first)

        # 2º save (Salva principale): legge il campo ORA pieno → ramo SET, niente clear.
        app_mod.App._save_config(a)
        assert fake.stored == "999:REALTOKEN"                # token NON cancellato
        assert fake.deleted == 0                             # delete_token MAI chiamato
    finally:
        event_log.clear_secrets()


def test_provider_saved_risincronizza_il_campo_token(make_app, app_mod):
    """Save da un tab Tools (Provider): il pannello reidrata la config e consuma il marker
    lasciando il campo vuoto; il callback deve risincronizzarlo così il Salva principale
    successivo non lo scambi per un clear (Codex tool-panel saves)."""
    a = make_app(config={"bot_token": "", _token_marker(): True})   # stato pre-save (marker)
    a._e_token = _FakeTokenEntry("")
    a._refresh_listened_chats = lambda *x, **k: None
    # new_cfg come lo restituisce il pannello dopo il suo save: token reidratato, marker consumato.
    new_cfg = {"bot_token": "777:FROMPANEL", "bot_token_storage": "keyring", "provider": "X"}

    # Riproduce il corpo del callback `_provider_saved` (closure non testabile direttamente):
    had = app_mod.App._had_incomplete_token_load(a)
    a._config = new_cfg
    app_mod.App._resync_token_field(a, had)
    assert a._e_token.get() == "777:FROMPANEL"              # campo allineato al token del pannello


def test_resync_specchia_il_token_reidratato_in_config(make_app, app_mod, monkeypatch):
    """Codex #257 (P2, finding 1): quando il refill reidrata dal keyring deve SPECCHIARE il
    token anche in `self._config["bot_token"]`, non solo nel campo GUI. Senza, un path che usa
    `self._config` direttamente (save non-GUI) dopo che il marker è stato consumato vedrebbe un
    token vuoto e cancellerebbe la credenziale.

    Fail-first: sul codice senza il mirror `self._config["bot_token"]` resta "" dopo il refill."""
    from xtrader_bridge import config_store, event_log
    fake = _FakeKeyring(stored="123:KEYRING", readable=True)
    monkeypatch.setattr(config_store, "token_store", fake)
    event_log.clear_secrets()
    try:
        a = make_app(config={"bot_token": "", "bot_token_storage": "keyring", _token_marker(): True})
        a._e_token = _FakeTokenEntry("")
        app_mod.App._resync_token_field(a)
        assert a._e_token.get() == "123:KEYRING"
        assert a._config["bot_token"] == "123:KEYRING"        # MIRROR in config (fail-first)
        assert _token_marker() not in a._config
    finally:
        event_log.clear_secrets()


def test_start_refill_poi_abort_poi_save_non_gui_non_cancella(make_app, app_mod, monkeypatch, tmp_path):
    """Codex #257 (P2, finding 1) END-TO-END: START reidrata il campo dal keyring e consuma il
    marker, poi ABORTA (es. csv invalido) prima di `_save_config`; in seguito un save non-GUI
    (`_on_debug_toggle`) usa `self._config` direttamente. Col mirror del token in config il save
    non-GUI vede un token presente → ramo SET, NON cancella la credenziale.

    Fail-first: senza il mirror, `self._config['bot_token']` resta "" senza marker → il save
    non-GUI entra nel ramo clear REALE e `delete_token` cancella il token (`deleted==1`)."""
    from xtrader_bridge import config_store, event_log
    cfgfile = tmp_path / "config.json"
    fake = _FakeKeyring(stored="999:REALTOKEN", readable=True)
    monkeypatch.setattr(config_store, "token_store", fake)
    monkeypatch.setattr(app_mod, "CONFIG_FILE", str(cfgfile))
    event_log.clear_secrets()
    try:
        a = make_app(running=False, config={
            "bot_token": "", "bot_token_storage": "keyring", _token_marker(): True,
        })
        a._e_token = _FakeTokenEntry("")
        a._debug_var = _FakeTokenEntry(True)
        # START-like: reidrata il campo + specchia in config + consuma il marker, poi "aborta".
        app_mod.App._resync_token_field(a)
        assert a._e_token.get() == "999:REALTOKEN"
        assert a._config["bot_token"] == "999:REALTOKEN"

        # Save non-GUI successivo: usa self._config direttamente. Non deve cancellare il token.
        app_mod.App._on_debug_toggle(a)
        assert fake.stored == "999:REALTOKEN"                 # token PRESERVATO
        assert fake.deleted == 0                              # delete_token MAI chiamato
    finally:
        event_log.clear_secrets()


def test_save_config_refill_post_save_se_keyring_torna_durante_il_save(
        make_app, app_mod, monkeypatch, tmp_path):
    """Codex #257 (P2, finding 2): il keyring è illeggibile al refill PRE-lettura di `_save_config`
    ma torna leggibile DENTRO `save_config` (race): `save_config` reidrata e consuma il marker
    lasciando il campo vuoto. Il refill POST-save deve ripopolare il campo, così un save successivo
    non lo scambia per un clear.

    Fail-first: senza il refill post-save il campo resta vuoto dopo `_save_config` (e un save
    successivo cancellerebbe il token)."""
    from xtrader_bridge import config_store, event_log
    cfgfile = tmp_path / "config.json"
    # become_readable_at=2: lettura 1 (pre-save refill) FALLISCE, lettura 2 (dentro save_config) RIESCE.
    fake = _FakeKeyring(stored="999:REALTOKEN", become_readable_at=2)
    monkeypatch.setattr(config_store, "token_store", fake)
    monkeypatch.setattr(app_mod, "CONFIG_FILE", str(cfgfile))
    event_log.clear_secrets()
    try:
        a = make_app(running=False, config={
            "bot_token": "", "bot_token_storage": "keyring", _token_marker(): True,
            "chat_id": "123456", "csv_path": str(tmp_path / "segnali.csv"),
            "provider": "TelegramBot", "dry_run": True,
        })
        a._e_token = _FakeTokenEntry("")
        a._e_chat = _FakeTokenEntry("123456")
        a._e_csv = _FakeTokenEntry(str(tmp_path / "segnali.csv"))
        a._e_provider = _FakeTokenEntry("TelegramBot")
        a._e_delay = _FakeTokenEntry("90")
        a._adv = {}
        a._save_ok = True
        a._refresh_listened_chats = lambda *x, **k: None

        app_mod.App._save_config(a)
        assert a._e_token.get() == "999:REALTOKEN"            # campo risincronizzato post-save
        assert fake.stored == "999:REALTOKEN"                 # token NON cancellato
        assert fake.deleted == 0
    finally:
        event_log.clear_secrets()
