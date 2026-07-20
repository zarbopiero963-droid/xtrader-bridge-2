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

from xtrader_bridge import confirmation_reader, csv_writer, signal_queue


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
    assert any("già scaduto/rimosso" in m for m in a.logs)
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
    assert any("riallineato" in m for m in a.logs)
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
