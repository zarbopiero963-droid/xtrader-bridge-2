"""Test hard AC-M1 + AC-M2 (audit di controllo #114, ondata 2 PR-4).

AC-M2 — race conferma/scadenza in `App._process_confirmation`: se il segnale è GIÀ
stato rimosso (expire-tick/sostituzione) tra lo snapshot di `pending()` e il
ricontrollo sotto lock, l'esito di `queue.confirm()` è `False` e:
- a disco ALLINEATO non si riscrive un CSV identico (mtime intatto: niente finestra
  di ri-lettura XTrader, #259 C2) e NON si registra un `XTRADER_CONFIRMED` falso;
- a disco STANTIO (`_csv_dirty`) si riallinea il CSV ma senza esito falso nel diario.

AC-M1 — `_run_bot` registra un error handler PTB: un'eccezione imprevista negli
handler non muore più solo sul logger `telegram.ext` (invisibile nell'EXE
--windowed) ma arriva a log GUI + semaforo errori + contatore.

Fail-first sul codice precedente: la conferma-fantasma riscriveva il CSV identico e
registrava `XTRADER_CONFIRMED` nel diario; `add_error_handler` non esisteva in
tutto il repo (grep: zero occorrenze).

Metodi REALI di `App` via harness headless (`make_app`, conftest #108); l'invocazione
live dell'error handler dentro l'event loop PTB reale resta smoke manuale su Windows
(vedi `manual` in fondo), qui si blinda la registrazione e il corpo dell'handler a
livello sorgente come per l'invariante `__dict__.get("_csv_dirty")` già in suite.
"""

import inspect

from xtrader_bridge import confirmation_reader, csv_writer, i18n, signal_queue

# Messaggi asseriti dai test (review Fable/Fugu/GLM/GPT #124). Questo repo usa i18n
# VALUE-AS-KEY: la frase italiana È la chiave del catalogo (che mappa IT→EN/ES), quindi
# passare la frase sorgente a `i18n.tr()` è corretto e la traduce nella lingua attiva. I
# test confrontano contro `i18n.tr(<chiave>)` invece che contro literal IT, così restano
# deterministici anche con lingua diversa (isolamento fra test / locale CI). Se una frase
# sorgente cambiasse, `tr(chiave-vecchia)` la restituirebbe verbatim (fallback) mentre
# l'app logga la nuova → il test FALLISCE (drift catturato, direzione sicura), NON un falso
# verde. Le costanti devono restare VERBATIM identiche alle stringhe passate a `i18n.tr`
# in `app.py::_process_confirmation`.
_MSG_INVARIATO = "ℹ️ Conferma XTrader per un segnale già scaduto/rimosso: CSV invariato."
_MSG_RIALLINEATO = "ℹ️ Conferma XTrader per un segnale già rimosso: CSV riallineato."


def _row(event, selection=None):
    return {"EventName": event, "MarketName": "Esito finale",
            "SelectionName": selection or event.split(" ")[0],
            "Price": "1.85", "BetType": "PUNTA"}


def _queue_with(*rows):
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED,
                                 default_timeout=120)
    for i, r in enumerate(rows):
        q.add(r, now=1000 + i)
    return q


def _ghost_confirm(monkeypatch, app_mod):
    """`interpret` che riporta CONFIRMED per un signal_id NON più in coda: è la race
    reale (scadenza tra snapshot e lock) resa deterministica."""
    monkeypatch.setattr(
        app_mod.confirmation_reader, "interpret",
        lambda *a, **k: confirmation_reader.ConfirmationResult(
            confirmation_reader.CONFIRMED, "ghost-id"))


def _spy_writes(monkeypatch, app_mod, sink):
    real = app_mod.write_rows
    monkeypatch.setattr(app_mod, "write_rows",
                        lambda rows, path: sink.append(len(rows)) or real(rows, path))


# ── AC-M2 ───────────────────────────────────────────────────────────────────


def test_conferma_fantasma_disco_allineato_non_riscrive_ne_journala(
        make_app, app_mod, monkeypatch, tmp_path):
    """Segnale già rimosso + disco allineato → NESSUNA riscrittura (mtime intatto),
    NESSUN `XTRADER_CONFIRMED` nel diario, log onesto. Prima del fix: CSV identico
    riscritto + evento diario falso."""
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    a._csv_dirty = False
    journal = []
    a._journal = lambda *ar, **kw: journal.append(ar)
    writes = []
    _spy_writes(monkeypatch, app_mod, writes)
    _ghost_confirm(monkeypatch, app_mod)

    app_mod.App._process_confirmation(a, "notifica xtrader", {"csv_path": path})

    assert writes == []                       # CSV MAI riscritto (no-op evitato)
    assert journal == []                      # nessun esito falso nel diario
    assert any(i18n.tr(_MSG_INVARIATO) in m for m in a.logs)
    # La riga attiva reale resta al suo posto (la conferma-fantasma non tocca nulla).
    assert [r["EventName"] for r in q.active_rows()] == ["Roma v Lazio"]


def test_conferma_fantasma_disco_stantio_riallinea_senza_esito_falso(
        make_app, app_mod, monkeypatch, tmp_path):
    """Segnale già rimosso ma `_csv_dirty=True` (retry pendente) → il CSV VIENE
    riallineato (una scrittura) ma senza `XTRADER_CONFIRMED` falso; `_csv_dirty`
    torna False su successo."""
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    a._csv_dirty = True
    journal = []
    a._journal = lambda *ar, **kw: journal.append(ar)
    writes = []
    _spy_writes(monkeypatch, app_mod, writes)
    _ghost_confirm(monkeypatch, app_mod)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1005.0)

    app_mod.App._process_confirmation(a, "notifica xtrader", {"csv_path": path})

    assert writes == [1]                      # UNA scrittura di riallineamento
    assert journal == []                      # nessun XTRADER_CONFIRMED falso
    assert any(i18n.tr(_MSG_RIALLINEATO) in m for m in a.logs)
    assert a._csv_dirty is False              # disco di nuovo allineato


def test_conferma_reale_intatta(make_app, app_mod, monkeypatch, tmp_path):
    """Regressione inversa: la conferma NORMALE (segnale ancora in coda) continua a
    rimuovere, riscrivere e journalare come prima."""
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Inter v Milan"), _row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    a._csv_dirty = False
    journal = []
    a._journal = lambda *ar, **kw: journal.append(ar)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1005.0)

    app_mod.App._process_confirmation(a, "Inter v Milan Esito finale Inter piazzata",
                                      {"csv_path": path})

    assert [r["EventName"] for r in q.active_rows()] == ["Roma v Lazio"]
    assert journal and journal[0][0] == "XTRADER_CONFIRMED"


# ── AC-M1 (registrazione + corpo dell'handler, regression-guard a sorgente) ─


def test_error_handler_ptb_registrato_e_cablato():
    """`_run_bot` DEVE registrare un error handler PTB che inoltra a contatore,
    semaforo errori e log del bridge. Guard a sorgente (stesso pattern del meta-test
    `__dict__.get("_csv_dirty")` già in suite): l'invocazione live dentro l'event
    loop PTB richiede Telegram reale → smoke manuale. Prima del fix: zero occorrenze
    di `add_error_handler` in tutto il repo → questo test falliva."""
    import xtrader_bridge.app as app_module
    src = inspect.getsource(app_module)
    assert "app.add_error_handler(_on_handler_error)" in src, (
        "app.py: l'Application PTB deve registrare l'error handler (AC-M1 #114)")
    body = src.split("async def _on_handler_error", 1)[1].split("app.add_error_handler", 1)[0]
    assert '_bump("errors")' in body            # contatore errori
    assert '_set_last("error"' in body          # semaforo «Ultimo errore»
    assert "self._log" in body or "._log(" in body  # log GUI (sink che redige)
    assert "_safe_after" in body                # mai chiamate Tk dirette dal bot thread


def test_costanti_messaggio_allineate_alla_sorgente():
    """Guard anti-drift (review GLM #124): le costanti `_MSG_*` asserite dai test devono
    esistere VERBATIM come stringhe passate a `i18n.tr` in `app.py`. Se un refactor
    cambiasse il messaggio in sorgente senza aggiornare qui, questo test FALLISCE subito
    (invece di lasciare i test degli scenari a verificare una stringa non più prodotta)."""
    import xtrader_bridge.app as app_module
    src = inspect.getsource(app_module)
    assert _MSG_INVARIATO in src, "app.py non contiene più _MSG_INVARIATO verbatim"
    assert _MSG_RIALLINEATO in src, "app.py non contiene più _MSG_RIALLINEATO verbatim"
    # E le chiavi devono essere nel catalogo i18n EN/ES (traduzioni non orfane). Il
    # cambio lingua è in try/finally: un assert fallito NON deve lasciare una lingua
    # attiva stantia per gli altri test (leak fra test — proprio il rischio segnalato).
    prev = i18n.get_language()
    try:
        for key in (_MSG_INVARIATO, _MSG_RIALLINEATO):
            i18n.set_language("EN")
            assert i18n.tr(key) != key, f"manca traduzione EN: {key!r}"
            i18n.set_language("ES")
            assert i18n.tr(key) != key, f"manca traduzione ES: {key!r}"
    finally:
        i18n.set_language(prev)


def test_ghost_realign_write_fallita_non_dichiara_riallineato(
        make_app, app_mod, monkeypatch, tmp_path):
    """Blocker Fable PR #124: ghost-confirm + disco stantio + scrittura FALLITA → il log
    NON deve dichiarare «riallineato» (sarebbe falso), `_csv_dirty` resta True e il
    retry breve è programmato. Fail-first: prima del fix il log «riallineato» usciva
    prima del check di `write_error`."""
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    a = make_app(csv_path=path, queue=q)
    a._csv_dirty = True
    a._journal = lambda *ar, **kw: None
    monkeypatch.setattr(app_mod, "write_rows",
                        lambda rows, p: (_ for _ in ()).throw(OSError("CSV locked")))
    _ghost_confirm(monkeypatch, app_mod)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 1005.0)

    app_mod.App._process_confirmation(a, "notifica xtrader", {"csv_path": path})

    assert not any(i18n.tr(_MSG_RIALLINEATO) in m for m in a.logs)   # niente dichiarazione falsa
    assert a._csv_dirty is True                          # disco ancora stantio
    assert (path, app_mod._WRITE_RETRY_DELAY) in a.expiry_calls   # retry programmato


def test_ghost_realign_che_svuota_journala_realign_non_confirmation(
        make_app, app_mod, monkeypatch, tmp_path):
    """Blocker Fable PR #124 (round 1+2): ghost-realign che riporta il CSV a solo header
    (coda ormai vuota) → il `CSV_CLEARED` nel diario deve avere `reason="realign"` —
    NON `"confirmation"` (il segnale non è stato confermato da questa notifica) e
    nemmeno `"expiry"` hardcodato (round 2: la causa reale della rimozione non è
    conoscibile qui — poteva essere anche una rimozione precedente con write fallita).
    Fail-first: round 1 journalava "confirmation", round 2 "expiry"."""
    path = str(tmp_path / "segnali.csv")
    q = _queue_with(_row("Roma v Lazio"))
    csv_writer.write_rows(q.active_rows(), path)
    q.expire(now=2000)                       # il segnale scade e viene rimosso dal tick...
    a = make_app(csv_path=path, queue=q)
    a._csv_dirty = True                      # ...ma la riscrittura post-scadenza era fallita
    a._csv_had_active_row = True
    cleared = []
    a._journal_csv_cleared_if_had_row = lambda ev, **data: cleared.append((ev, data))
    a._journal = lambda *ar, **kw: None
    _ghost_confirm(monkeypatch, app_mod)
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: 2000.0)

    app_mod.App._process_confirmation(a, "notifica xtrader", {"csv_path": path})

    assert cleared == [("CSV_CLEARED", {"reason": "realign"})]  # nessuna attribuzione falsa
    assert a._csv_dirty is False                                # riallineato davvero
    assert any(i18n.tr(_MSG_RIALLINEATO) in m for m in a.logs)
