"""Test hard veritieri — Issue #76 P2-1 (audit 2026-07-15).

Reinvio identico OLTRE la finestra di deduplica (default 300s) con la riga ancora
ATTIVA in coda: nelle modalità multi-riga (`APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED`)
la vita della riga (`confirmation_timeout`/`clear_delay`) può superare la finestra
dedup del `SignalTracker`; senza un confronto con le chiavi ATTIVE della coda, il
reinvio è `NEW` → seconda riga identica nel CSV → doppia scommessa.

Fix testato: `write_path.commit_signal`/`commit_signals` trattano come `DUPLICATE`
una riga la cui `row_dedup_key` è ancora tra `queue.active_keys(now)` (solo modalità
non-OVERWRITE: in `OVERWRITE_LAST` non esiste il rischio doppia-riga e il blocco
multi è già protetto da `_same_rows_unordered`).

Tecnica: il tracker usa wall-clock interno (`time.time()`); per simulare il passare
del tempo OLTRE la finestra si invecchiano i timestamp dello stato del tracker via
`restore_state` (stesso meccanismo della persistenza reale). Il clock della CODA è
monotòno e passato esplicitamente (`now`), quindi la riga resta/scade in modo
controllato e indipendente.
"""

from xtrader_bridge import live_guard, safety_guard, signal_dedupe, signal_queue, write_path

CFG_REAL = {"dry_run": False}


def _row(name):
    return {"EventName": name, "SelectionName": name, "Price": "1,90"}


def _ok_writer(sink):
    def _w(rows, path):
        sink.append([dict(r) for r in rows])
    return _w


def _age_tracker(tracker, seconds):
    """Invecchia TUTTE le voci del tracker di `seconds` (simula il passare del tempo
    wall-clock oltre la finestra dedup, come dopo un idle reale)."""
    tracker.restore_state([[h, t - seconds, r] for (h, t, r) in tracker.state()])


def _fresh(mode, timeout):
    tracker = signal_dedupe.SignalTracker()
    daily = safety_guard.DailyLimiter(max_per_day=100)
    queue = signal_queue.SignalQueue(mode=mode, default_timeout=timeout)
    return tracker, daily, queue


# ── P2-1 core: reinvio identico oltre finestra, riga ANCORA attiva → DUPLICATE ──────────────

def test_single_row_queue_mode_reinvio_oltre_finestra_non_scrive_seconda_riga():
    # QUEUE_UNTIL_CONFIRMED con confirmation_timeout (600) > finestra dedup (300).
    tracker, daily, queue = _fresh(signal_queue.QUEUE_UNTIL_CONFIRMED, timeout=600)
    written = []
    row = _row("A")
    res1 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    assert res1.decision == live_guard.WRITE
    assert queue.active_rows() == [row]
    # Il canale riposta lo STESSO identico messaggio dopo 400s (oltre la finestra dedup):
    # l'hash è uscito dalla finestra ma la riga è ancora attiva (scade a now=700).
    _age_tracker(tracker, 400)
    res2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 500.0, _ok_writer(written))
    assert res2.decision == live_guard.DUPLICATE      # NON un secondo WRITE
    assert res2.write_error is None
    assert queue.active_rows(now=500.0) == [row]      # UNA sola riga attiva, mai due
    assert len(written) == 1                          # CSV scritto una volta sola


def test_single_row_append_mode_reinvio_oltre_finestra_non_scrive_seconda_riga():
    # APPEND_ACTIVE con clear_delay (600) > finestra dedup (300): stesso scenario.
    tracker, daily, queue = _fresh(signal_queue.APPEND_ACTIVE, timeout=600)
    written = []
    row = _row("A")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    _age_tracker(tracker, 400)
    res2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 500.0, _ok_writer(written))
    assert res2.decision == live_guard.DUPLICATE
    assert queue.active_rows(now=500.0) == [row]
    assert len(written) == 1


def test_multi_append_reinvio_oltre_finestra_non_accoda_duplicati():
    # Percorso MULTI (commit_signals) in APPEND: un messaggio con 2 righe reinviato
    # oltre finestra con entrambe le righe ancora attive → nessuna riga aggiunta.
    tracker, daily, queue = _fresh(signal_queue.APPEND_ACTIVE, timeout=600)
    written = []
    rows = [_row("A"), _row("B")]
    res1 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", rows, "out.csv", 100.0, _ok_writer(written))
    assert res1.decision == live_guard.WRITE
    assert len(queue.active_rows()) == 2
    _age_tracker(tracker, 400)
    res2 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", rows, "out.csv", 500.0, _ok_writer(written))
    assert res2.decision == live_guard.DUPLICATE
    assert len(queue.active_rows(now=500.0)) == 2     # ancora 2, non 4
    assert len(written) == 1                          # nessuna riscrittura


def test_multi_append_espansione_oltre_finestra_accoda_solo_la_nuova():
    # A attiva e "aged-out" dal tracker; il messaggio si espande ad A+B: A è un
    # duplicato ancora attivo (soppressa), B è nuova (accodata e scritta).
    tracker, daily, queue = _fresh(signal_queue.APPEND_ACTIVE, timeout=600)
    written = []
    res1 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", [_row("A")], "out.csv", 100.0, _ok_writer(written))
    assert res1.decision == live_guard.WRITE
    _age_tracker(tracker, 400)
    res2 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", [_row("A"), _row("B")], "out.csv", 500.0,
        _ok_writer(written))
    assert res2.decision == live_guard.WRITE
    active = queue.active_rows(now=500.0)
    assert active == [_row("A"), _row("B")]           # A una sola volta + B nuova
    assert len(written) == 2                          # riscrittura con il blocco aggiornato


# ── nessun over-blocking: dopo la SCADENZA della riga il reinvio è legittimo ─────────────────

def test_reinvio_dopo_scadenza_riga_e_finestra_viene_riaccettato():
    # Riga scaduta (timeout 50, reinvio a now=200) e hash fuori finestra: il reinvio è
    # un segnale legittimamente NUOVO (il clear-timeout è passato) → WRITE, una riga.
    tracker, daily, queue = _fresh(signal_queue.QUEUE_UNTIL_CONFIRMED, timeout=50)
    written = []
    row = _row("A")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    _age_tracker(tracker, 400)
    res2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 200.0, _ok_writer(written))
    assert res2.decision == live_guard.WRITE          # non bloccato: la riga era scaduta
    assert queue.active_rows(now=200.0) == [row]      # una sola riga (la nuova)
    assert len(written) == 2


def test_dentro_finestra_resta_duplicate_comportamento_storico():
    # Regressione: entro la finestra dedup il reinvio era e resta DUPLICATE.
    tracker, daily, queue = _fresh(signal_queue.QUEUE_UNTIL_CONFIRMED, timeout=600)
    written = []
    row = _row("A")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    res2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 150.0, _ok_writer(written))
    assert res2.decision == live_guard.DUPLICATE
    assert len(written) == 1


# ── righe con chiave vuota (add legacy senza dedup_key) non devono mai bloccare ─────────────

def test_chiave_vuota_in_coda_non_blocca_un_segnale_nuovo():
    tracker, daily, queue = _fresh(signal_queue.APPEND_ACTIVE, timeout=600)
    queue.add(_row("X"), now=100.0)                   # riga legacy senza dedup_key ("")
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgY", _row("Y"), "out.csv", 110.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE           # "" non combacia mai con una chiave vera
    assert len(written) == 1
    res_m = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgZ", [_row("Z")], "out.csv", 120.0, _ok_writer(written))
    assert res_m.decision == live_guard.WRITE
    assert len(written) == 2


def test_chiave_calcolata_vuota_non_combacia_con_legacy_vuota(monkeypatch):
    # Filtro difensivo (review #77 Fable): scenario IPOTETICO in cui `row_dedup_key` degenerasse
    # a "" (oggi impossibile: sha256 hexdigest, sempre 64 char) con una riga legacy a chiave ""
    # in coda → il segnale nuovo NON deve essere marcato DUPLICATE (over-blocking = bet persa).
    tracker, daily, queue = _fresh(signal_queue.APPEND_ACTIVE, timeout=600)
    queue.add(_row("X"), now=100.0)                   # riga legacy senza dedup_key → ""
    monkeypatch.setattr(write_path.signal_dedupe, "row_dedup_key", lambda t, r: "")
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgY", _row("Y"), "out.csv", 110.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE           # "" non blocca mai: chiavi vuote escluse
    assert len(written) == 1


# ── OVERWRITE_LAST: comportamento invariato (nessun rischio doppia-riga) ────────────────────

def test_overwrite_single_row_reinvio_oltre_finestra_resta_write_sostituzione():
    # In OVERWRITE_LAST `add` SOSTITUISCE: il reinvio oltre finestra resta WRITE (una
    # riga sola, valori del messaggio corrente) — comportamento storico preservato.
    tracker, daily, queue = _fresh(signal_queue.OVERWRITE_LAST, timeout=600)
    written = []
    row = _row("A")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    _age_tracker(tracker, 400)
    res2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 500.0, _ok_writer(written))
    assert res2.decision == live_guard.WRITE
    assert queue.active_rows(now=500.0) == [row]      # sempre UNA riga (sostituita)
    assert len(written) == 2


def test_overwrite_multi_reinvio_identico_oltre_finestra_resta_noop():
    # Regressione (già garantito da _same_rows_unordered): reinvio identico multi in
    # OVERWRITE non riscrive il CSV (XTrader non deve riconsumare).
    tracker, daily, queue = _fresh(signal_queue.OVERWRITE_LAST, timeout=600)
    written = []
    rows = [_row("A"), _row("B")]
    write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", rows, "out.csv", 100.0, _ok_writer(written))
    _age_tracker(tracker, 400)
    res2 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", rows, "out.csv", 500.0, _ok_writer(written))
    assert res2.decision == live_guard.DUPLICATE      # no-op, nessuna riscrittura
    assert len(written) == 1


# ── rollback su write fallita resta coerente col nuovo check ────────────────────────────────

def test_write_fallita_su_riga_nuova_resta_ritentabile_anche_col_check_attivi():
    # La riga B fallisce la scrittura → rollback completo → B NON è tra le chiavi attive
    # e resta ritentabile (il check sulle chiavi attive non deve "ricordare" la riga rollbackata).
    tracker, daily, queue = _fresh(signal_queue.APPEND_ACTIVE, timeout=600)
    written = []
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", _row("A"), "out.csv", 100.0, _ok_writer(written))

    def _boom(rows, path):
        raise OSError("CSV locked")

    res_fail = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgB", _row("B"), "out.csv", 110.0, _boom)
    assert isinstance(res_fail.write_error, OSError)
    assert queue.active_rows(now=110.0) == [_row("A")]   # rollback: B non attiva
    res_retry = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgB", _row("B"), "out.csv", 120.0, _ok_writer(written))
    assert res_retry.decision == live_guard.WRITE         # ritentabile
    assert queue.active_rows(now=120.0) == [_row("A"), _row("B")]
