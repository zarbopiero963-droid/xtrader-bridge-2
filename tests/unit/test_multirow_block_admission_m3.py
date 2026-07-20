"""Test hard AC-M3 (audit di controllo #114, decisione proprietario 2026-07-20):
ammissione PER-BLOCCO dei guardrail rate/daily in `write_path.commit_signals`.

Invariante: un messaggio multi-gamba (dutching) NON viene MAI spezzato dai limiti —
o vengono scritte TUTTE le gambe, o (limite già esaurito) l'INTERO blocco è soppresso
con esito onesto (`RATE_LIMITED`/`DAILY_LIMITED`) e resta ritentabile. Il MESSAGGIO,
non la singola gamba, consuma 1 slot rate e 1 slot daily (mirror del single-row, dove
`evaluate` gira una volta per messaggio).

Fail-first: sul codice precedente (una `evaluate` PER RIGA) questi test falliscono —
con `max_per_minute=2` un blocco da 5 scriveva 2 gambe e ne scartava 3 in silenzio
(`test_rate_limit_non_spezza_il_blocco`), e un blocco da 3 con `max_per_day=2`
consumava 2 slot e perdeva la terza gamba (`test_daily_consuma_una_slot_per_messaggio`).

Collaboratori REALI (SignalTracker/DailyLimiter/SignalQueue), `write_rows` iniettabile,
headless — come `test_write_path.py`.
"""

from xtrader_bridge import (
    live_guard,
    safety_guard,
    signal_dedupe,
    signal_queue,
    write_path,
)

CFG_REAL = {"dry_run": False}
CFG_DRY = {"dry_run": True}


def _row(name):
    return {"EventName": name, "SelectionName": name, "Price": "1,90"}


def _rows(*names):
    return [_row(n) for n in names]


def _ok_writer(sink):
    def _w(rows, path):
        sink.append([dict(r) for r in rows])
    return _w


def _boom_writer(exc=OSError("CSV locked")):
    def _w(rows, path):
        raise exc
    return _w


def _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=0, max_per_day=10,
           max_per_minute=20):
    tracker = signal_dedupe.SignalTracker(max_per_minute=max_per_minute)
    daily = safety_guard.DailyLimiter(max_per_day=max_per_day)
    queue = signal_queue.SignalQueue(mode=mode, max_active=max_active)
    return tracker, daily, queue


def test_rate_limit_non_spezza_il_blocco():
    """Blocco da 5 gambe con `max_per_minute=2`: TUTTE e 5 le gambe vengono scritte
    (il messaggio consuma UNA slot rate). Prima del fix: 2 scritte, 3 scartate in
    silenzio con esito WRITE «pieno» (partial-drop, AC-M3)."""
    tracker, daily, queue = _fresh(max_per_minute=2)
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "dutch", _rows("A", "B", "C", "D", "E"),
        "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.write_error is None
    assert len(queue.active_rows()) == 5          # nessuna gamba persa in coda
    assert len(written) == 1 and len(written[0]) == 5   # CSV con TUTTE le gambe


def test_daily_consuma_una_slot_per_messaggio():
    """`max_per_day=2`: un blocco da 3 gambe passa INTERO e consuma UNA slot
    (istruzione = messaggio). Prima del fix: 2 gambe scritte, la terza scartata."""
    tracker, daily, queue = _fresh(max_per_day=2)
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "dutch", _rows("A", "B", "C"),
        "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert len(written[0]) == 3
    assert daily.remaining() == 1                 # 1 slot per il messaggio, non 3


def test_daily_esaurito_sopprime_il_blocco_intero_ritentabile():
    """Tetto giornaliero già esaurito: NESSUNA gamba scritta o accodata, esito onesto
    `DAILY_LIMITED` (visibile a `_process`/log), messaggio RITENTABILE dopo un
    `release()` — mai un blocco scritto a metà."""
    tracker, daily, queue = _fresh(max_per_day=1)
    assert daily.allow() is True                  # esaurisce l'unica slot
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "dutch", _rows("A", "B"),
        "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.DAILY_LIMITED
    assert written == []                          # niente CSV
    assert queue.active_rows() == []              # niente in coda
    assert res.write_attempted is False
    # Ritentabile: liberata una slot, lo STESSO messaggio ora passa intero.
    daily.release()
    res2 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "dutch", _rows("A", "B"),
        "out.csv", 101.0, _ok_writer(written))
    assert res2.decision == live_guard.WRITE
    assert len(written) == 1 and len(written[0]) == 2


def test_rate_esaurito_sopprime_il_blocco_intero():
    """Rate-limit già esaurito da messaggi PRECEDENTI: il blocco è soppresso INTERO
    con `RATE_LIMITED` (nessun partial), tracker ripristinato (nessuna chiave del
    blocco resta registrata → niente falso DUPLICATE al retry)."""
    tracker, daily, queue = _fresh(max_per_minute=1)
    # Un messaggio reale precedente consuma l'unica slot del minuto.
    r0 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "prima", _rows("X"),
        "out.csv", 100.0, _ok_writer([]))
    assert r0.decision == live_guard.WRITE
    tracker_snap = tracker.state()
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "dutch", _rows("A", "B", "C"),
        "out.csv", 101.0, _ok_writer(written))
    assert res.decision == live_guard.RATE_LIMITED
    assert written == []
    assert len(queue.active_rows()) == 1          # resta solo il segnale precedente
    assert tracker.state() == tracker_snap        # tracker com'era: ritentabile


def test_espansione_con_duplicato_attivo_scrive_tutte_le_gambe():
    """OVERWRITE_LAST, espansione A→A+B+C con A ancora attiva (kyh #192) e
    `max_per_minute=2`: due MESSAGGI = due slot rate, e il secondo blocco esce INTERO
    (A tenuta come duplicato attivo, B e C nuove insieme) — la dedup per-riga resta
    invariata, l'ammissione è per-messaggio (prima del fix: B ammessa e C scartata,
    perché ogni gamba consumava una slot)."""
    tracker, daily, queue = _fresh(mode=signal_queue.OVERWRITE_LAST, max_per_minute=2)
    written = []
    r1 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", _rows("A"),
        "out.csv", 100.0, _ok_writer(written))
    assert r1.decision == live_guard.WRITE
    r2 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", _rows("A", "B", "C"),
        "out.csv", 101.0, _ok_writer(written))
    assert r2.decision == live_guard.WRITE
    assert len(written[-1]) == 3                  # A + B + C, nessuna gamba persa


def test_dry_run_blocco_non_consuma_daily_ne_dedupe():
    """DRY_RUN per-blocco: nessuna slot daily consumata, tracker ripristinato
    (le gambe restano ritentabili in reale), CSV mai scritto — P3-rs1 invariato."""
    tracker, daily, queue = _fresh(max_per_day=5)
    tracker_snap = tracker.state()
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_DRY, "sim", _rows("A", "B", "C"),
        "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.DRY_RUN
    assert written == []
    assert daily.remaining() == 5
    assert tracker.state() == tracker_snap


def test_write_fallita_rollback_completo_del_blocco():
    """Scrittura fallita: coda, tracker E daily tornano allo stato precedente —
    l'INTERO blocco resta ritentabile (invariante storica preservata col nuovo
    accounting per-blocco)."""
    tracker, daily, queue = _fresh(max_per_day=4)
    tracker_snap = tracker.state()
    daily_before = daily.remaining()
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "dutch", _rows("A", "B", "C"),
        "out.csv", 100.0, _boom_writer())
    assert isinstance(res.write_error, OSError)
    assert queue.active_rows() == []
    assert tracker.state() == tracker_snap
    assert daily.remaining() == daily_before
    # Retry dopo il fallimento: passa intero.
    written = []
    res2 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "dutch", _rows("A", "B", "C"),
        "out.csv", 101.0, _ok_writer(written))
    assert res2.decision == live_guard.WRITE
    assert len(written[0]) == 3


def test_duplicato_intra_blocco_non_raddoppia_la_gamba():
    """Due regole che risolvono alla STESSA riga nello stesso messaggio (APPEND):
    una sola gamba accodata/scritta (Codex #281 P1, preservato)."""
    tracker, daily, queue = _fresh()
    written = []
    same = _row("A")
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", [dict(same), dict(same), _row("B")],
        "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert len(queue.active_rows()) == 2          # A una volta sola + B
    assert len(written[0]) == 2


def test_reinvio_identico_no_op_restituisce_una_sola_slot():
    """OVERWRITE_LAST: reinvio identico con chiavi dedup SCADUTE (aged-out) → no-op
    che RESTITUISCE la singola slot consumata dal blocco (non una per gamba):
    il tetto giornaliero resta esatto."""
    tracker, daily, queue = _fresh(mode=signal_queue.OVERWRITE_LAST, max_per_day=5)
    written = []
    r1 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", _rows("A", "B"),
        "out.csv", 100.0, _ok_writer(written))
    assert r1.decision == live_guard.WRITE
    assert daily.remaining() == 4                 # 1 slot per il blocco
    # Chiavi dedup fuori finestra (aged-out): reinvio identico → riga per riga WRITE,
    # ma blocco == attivo → no-op con release della slot del blocco.
    tracker.restore_state([])                     # svuota la finestra dedup
    r2 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", _rows("A", "B"),
        "out.csv", 150.0, _ok_writer(written))
    assert r2.decision != live_guard.WRITE        # no-op onesto (non un nuovo piazzamento)
    assert daily.remaining() == 4                 # slot restituita: né persa né doppia
    assert len(written) == 1                      # CSV NON riscritto (mtime intatto)
