"""Test hard della sezione critica del percorso di scrittura (`write_path.commit_signal`).

Esercita il CUORE anti-doppia-scommessa con collaboratori REALI (SignalQueue,
SignalTracker, DailyLimiter) e una `write_rows` iniettabile: scrittura riuscita,
fallimento con ROLLBACK completo (coda + dedup + daily), blocco dal tetto righe attive
con rollback dei guardrail (segnale ritentabile), esito non-WRITE (duplicato) che non
tocca la coda, e `tracker=None`.

NB: il lock è responsabilità del chiamante (`App._process`); qui si testa la logica
sotto-lock in isolamento, headless.
"""

from xtrader_bridge import (
    live_guard,
    safety_guard,
    signal_dedupe,
    signal_queue,
    write_path,
)

CFG_REAL = {"dry_run": False}        # scrittura operativa (non simulazione)


def _row(name):
    return {"EventName": name, "SelectionName": name, "Price": "1,90"}


def _ok_writer(sink):
    """write_rows che registra le righe scritte (scrittura riuscita)."""
    def _w(rows, path):
        sink.append([dict(r) for r in rows])
    return _w


def _boom_writer(exc=OSError("CSV locked")):
    """write_rows che fallisce sempre (file bloccato/permessi)."""
    def _w(rows, path):
        raise exc
    return _w


def _fresh(mode=signal_queue.OVERWRITE_LAST, max_active=0, max_per_day=10):
    tracker = signal_dedupe.SignalTracker()
    daily = safety_guard.DailyLimiter(max_per_day=max_per_day)
    queue = signal_queue.SignalQueue(mode=mode, max_active=max_active)
    return tracker, daily, queue


def test_write_riuscita_accoda_e_scrive():
    tracker, daily, queue = _fresh()
    written = []
    row = _row("A")
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.write_error is None
    assert res.blocked_by_cap is False
    assert res.write_attempted is True   # #153 H2: la scrittura conta nel contatore CSV-lock
    assert res.rows == [row]
    assert written == [[row]]            # CSV scritto una volta con la riga
    assert queue.active_rows() == [row]  # segnale attivo in coda


def test_write_fallita_fa_rollback_completo_e_segnale_ritentabile():
    tracker, daily, queue = _fresh()
    row = _row("A")
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _boom_writer())
    # Esito: errore riportato, NON sollevato
    assert isinstance(res.write_error, OSError)
    assert res.decision == live_guard.WRITE
    assert res.write_attempted is True   # tentata e fallita → conta come failure CSV-lock
    # Coda ripristinata: la riga NON resta attiva (niente riga stantia se la write fallisce)
    assert queue.active_rows() == []
    # Dedup ripristinato: lo STESSO messaggio non è un duplicato → ritentabile come WRITE
    written = []
    res2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", row, "out.csv", 101.0, _ok_writer(written))
    assert res2.decision == live_guard.WRITE   # non DUPLICATE: il dedup era stato annullato
    assert res2.write_error is None
    assert written == [[row]]


def test_blocco_da_tetto_senza_scaduti_non_riscrive_e_fa_rollback_guardrail():
    """#259 C2: se il tetto blocca il nuovo segnale e NON è scaduto nulla, il contenuto
    attivo su disco è già identico → riscrivere il CSV è inutile e riapre la finestra
    di doppia lettura lato XTrader (il file cambia mtime/inode senza cambiare righe).

    Fail-first: il vecchio codice chiamava comunque `write_rows` → `written == [[rowA]]`."""
    # tetto 1: A occupa la riga, B (diverso) è oltre il tetto → bloccato.
    tracker, daily, queue = _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=1)
    rowA, rowB = _row("A"), _row("B")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", rowA, "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgB", rowB, "out.csv", 101.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.blocked_by_cap is True
    # Le righe attive riportate restano quelle correnti (solo A), ma il CSV NON viene
    # riscritto: su disco c'è già esattamente [A].
    assert res.rows == [rowA]
    assert written == []
    assert res.write_error is None
    # #153 H2: nessuna scrittura tentata → il chiamante NON deve registrare un successo
    # nel contatore CSV-lock (falsificherebbe il recovery di un CSV bloccato).
    assert res.write_attempted is False
    assert [r["EventName"] for r in queue.active_rows()] == ["A"]
    # Guardrail rollback → B è RITENTABILE: registrarlo ora NON è un duplicato
    reg = tracker.register("msgB")
    assert reg.status != signal_dedupe.DUPLICATE


def test_blocco_da_tetto_con_scaduti_sincronizza_il_csv():
    """#259 C2 (ramo opposto): una coda sovra-riempita via `force=True` (blocchi multi-row
    #192) può SCADERE una riga restando comunque piena al tetto. In quel caso il disco
    contiene ancora la riga scaduta → anche se il nuovo segnale è bloccato dal tetto,
    il CSV VA riscritto con le attive correnti, altrimenti resta una riga stantia.

    Fail-first sul fix ingenuo «se blocked_by_cap non scrivere mai»: `written == []`
    lascerebbe la riga scaduta A su disco."""
    tracker, daily, queue = _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=1)
    rowA, rowB, rowC = _row("A"), _row("B"), _row("C")
    # A entra normalmente a t=0; B entra con force=True (percorso multi-row) a t=50:
    # la coda è ora OLTRE il tetto (2 attive con max_active=1).
    assert queue.add(rowA, now=0.0) is not None
    assert queue.add(rowB, now=50.0, force=True) is not None
    # C arriva quando A è ormai SCADUTA: expire libera A ma la coda resta piena (B),
    # quindi C è comunque bloccata dal tetto — però il disco va sincronizzato a [B].
    now = 0.0 + queue.default_timeout + 1.0
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgC", rowC, "out.csv", now, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.blocked_by_cap is True
    assert res.rows == [rowB]
    assert written == [[rowB]]           # CSV riscritto: la riga scaduta A non resta su disco
    assert res.write_attempted is True   # scrittura reale → conta nel contatore CSV-lock
    assert [r["EventName"] for r in queue.active_rows(now)] == ["B"]


def test_blocco_da_tetto_disco_sporco_sincronizza_anche_senza_scaduti():
    """Codex P1 #300: il salto della scrittura nel ramo cap-senza-scaduti presuppone
    «disco già identico alla coda» — presupposto FALSO se una riscrittura precedente
    (post-conferma/scadenza) è fallita e il retry non è ancora riuscito. Il chiamante
    lo segnala con `disk_dirty=True`: in quel caso il commit bloccato dal tetto DEVE
    comunque scrivere per riallineare il disco (la riga confermata non deve restarci).

    Fail-first: senza il parametro, il ramo cap saltava la scrittura → disco stantio."""
    tracker, daily, queue = _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=1)
    rowA, rowB = _row("A"), _row("B")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgA", rowA, "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "msgB", rowB, "out.csv", 101.0, _ok_writer(written),
        disk_dirty=True)
    assert res.decision == live_guard.WRITE
    assert res.blocked_by_cap is True
    assert written == [[rowA]]           # disco stantio → riallineato alle attive correnti
    assert res.write_attempted is True
    # Guardrail rollback invariato: B resta RITENTABILE
    reg = tracker.register("msgB")
    assert reg.status != signal_dedupe.DUPLICATE


# ── D1 audit #114: `commit_signals` (multi-riga) riallinea il disco stantio ────
# Simmetria col single-row: i rami no-op del commit MULTI (OVERWRITE col blocco == attivo,
# APPEND senza righe nuove) NON devono saltare la scrittura quando il disco è STANTIO.


def test_overwrite_reinvio_identico_disco_sporco_riallinea():
    """FAIL-FIRST D1 #114: in OVERWRITE un reinvio IDENTICO normalmente NON riscrive (XTrader non
    riconsuma). Ma col DISCO STANTIO (`disk_dirty=True`: una riscrittura precedente è fallita,
    retry pendente) il commit MULTI deve RIALLINEARE il disco riscrivendo le righe attive
    correnti, invece di lasciarlo stantio."""
    tracker, daily, queue = _fresh(mode=signal_queue.OVERWRITE_LAST, max_active=0)
    rowA = _row("A")
    write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 101.0, _ok_writer(written),
        disk_dirty=True)
    assert res.write_attempted is True
    assert res.write_error is None
    assert written == [[rowA]]                 # disco riallineato alle attive correnti
    assert res.decision != live_guard.WRITE    # esito onesto: reinvio identico, NON nuovo piazzamento
    assert queue.active_rows() == [rowA]       # una sola riga attiva: nessuna doppia scommessa


def test_overwrite_reinvio_identico_disco_pulito_non_riscrive():
    """Controprova: senza `disk_dirty`, il reinvio identico OVERWRITE NON tocca il CSV
    (comportamento storico invariato)."""
    tracker, daily, queue = _fresh(mode=signal_queue.OVERWRITE_LAST, max_active=0)
    rowA = _row("A")
    write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 101.0, _ok_writer(written))
    assert written == []                       # nessuna riscrittura
    assert res.write_attempted is False
    assert res.decision != live_guard.WRITE


def test_append_reinvio_identico_disco_sporco_riallinea():
    """FAIL-FIRST D1 #114: in APPEND/QUEUE un reinvio senza righe NUOVE (tutte duplicati)
    normalmente non tocca il CSV. Col DISCO STANTIO (`disk_dirty=True`) il commit MULTI deve
    RIALLINEARE riscrivendo le righe attive correnti."""
    tracker, daily, queue = _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=0)
    rowA = _row("A")
    write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 101.0, _ok_writer(written),
        disk_dirty=True)
    assert res.write_attempted is True
    assert res.write_error is None
    assert written == [[rowA]]
    assert res.decision != live_guard.WRITE
    assert queue.active_rows() == [rowA]       # nessuna doppia riga


def test_append_reinvio_identico_disco_pulito_non_riscrive():
    """Controprova: senza `disk_dirty`, il reinvio senza righe nuove APPEND NON tocca il CSV."""
    tracker, daily, queue = _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=0)
    rowA = _row("A")
    write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 101.0, _ok_writer(written))
    assert written == []
    assert res.write_attempted is False
    assert res.decision != live_guard.WRITE


def test_realign_disco_sporco_write_fallita_riporta_errore():
    """Se la riscrittura di RIALLINEAMENTO (disk_dirty) fallisce di nuovo, l'errore è riportato
    (`write_attempted=True`, `write_error` valorizzato) e il disco resta stantio: il chiamante
    tiene `_csv_dirty` e il retry riproverà. Nessuna doppia riga introdotta."""
    tracker, daily, queue = _fresh(mode=signal_queue.OVERWRITE_LAST, max_active=0)
    rowA = _row("A")
    write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 100.0, _ok_writer([]))
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msgA", [rowA], "out.csv", 101.0, _boom_writer(),
        disk_dirty=True)
    assert res.write_attempted is True
    assert res.write_error is not None
    # Contratto completo del CommitResult sul fallimento (review Sourcery #117): nessuna riga
    # committata e esito NON-WRITE onesto (reinvio identico = DUPLICATE), mai spacciato per WRITE.
    assert res.rows == []
    assert res.decision == live_guard.DUPLICATE
    assert queue.active_rows() == [rowA]       # coda coerente: una sola riga attiva


def test_realign_disco_sporco_coda_vuota_ripulisce_il_csv():
    """Review GLM #117: disco STANTIO ma coda VUOTA (nessun segnale attivo) → il realign scrive
    le righe attive correnti = VUOTE, cioè RIPULISCE il CSV stantio (solo header). È il
    riallineamento CORRETTO: senza segnali attivi il disco deve riflettere lo stato vuoto, non
    restare con contenuto stantio. Nessuna riga fantasma introdotta. (Il realign scrive SEMPRE
    le attive correnti della coda — fonte di verità — quindi non può mai svuotare un CSV che
    la coda considera ancora pieno.)"""
    tracker, daily, queue = _fresh(mode=signal_queue.OVERWRITE_LAST, max_active=0)
    written = []
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "msg", [], "out.csv", 100.0, _ok_writer(written),
        disk_dirty=True)
    assert res.write_attempted is True
    assert res.write_error is None
    assert written == [[]]                     # coda vuota → riscrive vuoto (clear del disco stantio)
    assert res.decision != live_guard.WRITE
    assert queue.active_rows() == []


def test_duplicato_non_scrive_e_non_tocca_la_coda():
    tracker, daily, queue = _fresh()
    row = _row("A")
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "dup", row, "out.csv", 100.0, _ok_writer([]))
    before = queue.active_rows()
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "dup", row, "out.csv", 101.0, _ok_writer(written))
    assert res.decision == live_guard.DUPLICATE
    assert res.blocked_by_cap is False
    assert res.rows == []
    assert written == []                 # nessuna scrittura tentata
    assert res.write_attempted is False  # e il contatore CSV-lock non va toccato
    assert queue.active_rows() == before  # coda invariata


def test_dry_run_non_scrive():
    tracker, daily, queue = _fresh()
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, {"dry_run": True}, "msgA", _row("A"), "out.csv", 100.0,
        _ok_writer(written))
    assert res.decision == live_guard.DRY_RUN
    assert res.rows == []
    assert written == []
    assert queue.active_rows() == []     # in simulazione la coda non viene toccata


# ── #184 low-tracker-nonwrite: i guardrail riflettono SOLO i WRITE reali ──────

CFG_DRY = {"dry_run": True}


def test_dry_run_non_consuma_il_tetto_giornaliero_reale():
    """#184 low-tracker-nonwrite: in simulazione `evaluate` incrementava il `DailyLimiter` reale
    (allow() conta), quindi N segnali in DRY_RUN esaurivano il tetto e poi BLOCCAVANO i segnali
    reali. Ora DRY_RUN fa rollback del tetto: la simulazione non consuma quota reale.

    Fail-first: senza rollback, `daily.remaining()` scendeva ad ogni segnale dry-run."""
    tracker, daily, queue = _fresh(max_per_day=2)
    for i in range(5):                                  # 5 segnali DIVERSI in simulazione
        res = write_path.commit_signal(
            tracker, daily, queue, CFG_DRY, f"sim{i}", _row(f"S{i}"), "out.csv", 100.0 + i,
            _ok_writer([]))
        assert res.decision == live_guard.DRY_RUN
    assert daily.remaining() == 2                        # tetto intatto: nessuna quota consumata


def test_dry_run_non_consuma_il_dedupe_reale():
    """#184 low-tracker-nonwrite: un segnale visto in DRY_RUN non deve poi sopprimere il SUO
    piazzamento reale (passando a modalità reale). Ora il dedupe non trattiene gli hash dry-run.

    Fail-first: senza rollback, lo stesso messaggio in reale dava DUPLICATE → bet reale persa."""
    tracker, daily, queue = _fresh()
    write_path.commit_signal(
        tracker, daily, queue, CFG_DRY, "segnale", _row("A"), "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signal(                      # ora in REALE, stesso messaggio
        tracker, daily, queue, CFG_REAL, "segnale", _row("A"), "out.csv", 101.0,
        _ok_writer(written))
    assert res.decision == live_guard.WRITE              # NON DUPLICATE: il dry-run non l'ha trattenuto
    assert written == [[_row("A")]]


def test_daily_limited_resta_ritentabile_dopo_il_reset():
    """#184 low-tracker-nonwrite: un segnale bloccato dal tetto giornaliero non deve restare
    soppresso come DUPLICATE dopo il reset del giorno. Ora DAILY_LIMITED fa rollback del dedupe.

    Fail-first: senza rollback, dopo il reset lo stesso messaggio dava DUPLICATE → bet persa.

    NB: `evaluate` usa il wallclock interno del DailyLimiter (non il `now` della coda), quindi il
    reset del giorno si simula azzerando il contatore via `restore_state` (stesso giorno valido)."""
    tracker, daily, queue = _fresh(max_per_day=1)
    # A consuma l'unica slot e viene scritto; B (diverso) è oltre il tetto → DAILY_LIMITED.
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "A", _row("A"), "out.csv", 100.0, _ok_writer([]))
    resB = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "B", _row("B"), "out.csv", 101.0, _ok_writer([]))
    assert resB.decision == live_guard.DAILY_LIMITED
    # Reset del tetto (nuovo giorno): azzera il contatore, lasciando intatto lo stato dedupe.
    snap = daily.state()
    daily.restore_state({**snap, "count": 0})
    # B deve poter essere scritto, NON soppresso come duplicato (il suo hash era stato annullato).
    written = []
    resB2 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "B", _row("B"), "out.csv", 102.0, _ok_writer(written))
    assert resB2.decision == live_guard.WRITE
    assert written == [[_row("B")]]


def test_daily_limited_giorno_corrotto_resta_normalizzato_non_si_blocca():
    """#184 low-tracker-nonwrite (Codex P2): con un `daily_state` corrotto (giorno malformato) e
    count al tetto, `allow()` rifiuta MA normalizza `_day` a oggi. Il rollback NON deve scartare
    quella normalizzazione: altrimenti il giorno corrotto verrebbe ri-salvato e il bridge resterebbe
    bloccato per sempre (mai un reset domani).

    Fail-first: col rollback pieno del daily, `_day` tornava al valore corrotto (UNKNOWN)."""
    tracker = signal_dedupe.SignalTracker()
    daily = safety_guard.DailyLimiter(max_per_day=1)
    # Stato corrotto tollerato da restore_state: giorno non valido → UNKNOWN, count al tetto.
    assert daily.restore_state({"day": "20XX-99-99", "count": 1}) is True
    assert not safety_guard._is_valid_day(daily.state()["day"])     # baseline: giorno NON valido
    queue = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, max_active=0)
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "B", _row("B"), "out.csv", 100.0, _ok_writer([]))
    assert res.decision == live_guard.DAILY_LIMITED
    # Il giorno è stato NORMALIZZATO a una data valida (oggi), non riportato al valore corrotto:
    # così al prossimo giorno reale il tetto si resetterà invece di restare bloccato.
    assert safety_guard._is_valid_day(daily.state()["day"])


def test_dry_run_non_tocca_il_daily_giorno_corrotto_si_risana_al_primo_uso_reale():
    """P3-rs1 audit #114: in DRY_RUN `evaluate` valuta il dry-run PRIMA di `daily.allow()`, quindi la
    simulazione NON tocca affatto il `DailyLimiter` — né consuma una slot né chiama `release()` (che,
    senza consumo, restituirebbe la slot di un WRITE reale precedente → overtrading). Un `daily_state`
    corrotto resta com'è durante la simulazione (inerte: in DRY_RUN il tetto non è mai applicato) e si
    RISANA al primo uso reale: `_roll` in `allow`/`remaining` adotta il giorno corrente CONSERVANDO il
    count (fail-closed, mai un reset a cap pieno → mai overtrading).

    Fail-first: col vecchio evaluate (allow PRIMA del dry-run) + `release()`, la DRY_RUN normalizzava
    il giorno e «restituiva» la slot; ora non tocca nulla (il giorno resta corrotto fino al 1º uso reale)."""
    tracker = signal_dedupe.SignalTracker()
    daily = safety_guard.DailyLimiter(max_per_day=5)
    assert daily.restore_state({"day": "bad-day", "count": 0}) is True
    assert not safety_guard._is_valid_day(daily.state()["day"])
    queue = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, max_active=0)
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_DRY, "S", _row("S"), "out.csv", 100.0, _ok_writer([]))
    assert res.decision == live_guard.DRY_RUN
    # DRY_RUN non ha toccato il daily: giorno ANCORA corrotto, count invariato (nessun allow/release).
    assert not safety_guard._is_valid_day(daily.state()["day"])
    assert daily.state()["count"] == 0
    # Al PRIMO uso reale il giorno si risana (fail-closed: count conservato, mai reset a cap pieno).
    assert daily.remaining() == 5                                    # `_roll` normalizza il giorno
    assert safety_guard._is_valid_day(daily.state()["day"])


def test_dry_run_non_restituisce_la_slot_di_un_write_reale():
    """P3-rs1 audit #114 (ANTI-OVERTRADING, single-row): il fix (dry-run PRIMA di `daily.allow()` in
    `evaluate` + rimozione del `release()` DRY_RUN nel chiamante) va tenuto in LOCKSTEP. Se `evaluate`
    non consuma più su DRY_RUN ma il chiamante chiamasse ancora `release()`, decrementerebbe una slot
    MAI consumata → restituirebbe la slot di un WRITE reale precedente → una scommessa reale EXTRA.
    Qui si prova che una DRY_RUN dopo un WRITE reale lascia il tetto INVARIATO.

    Fail-first: ripristinando il `daily.release()` nel ramo DRY_RUN di `commit_signal`, `remaining`
    salirebbe da 1 a 2 (over-release) e l'assert fallirebbe."""
    tracker, daily, queue = _fresh(max_per_day=2)
    # 1 WRITE reale consuma 1/2.
    r1 = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "reale", _row("A"), "out.csv", 100.0, _ok_writer([]))
    assert r1.decision == live_guard.WRITE
    assert daily.remaining() == 1
    # 1 segnale in DRY_RUN: NON deve restituire la slot del WRITE reale (nessun over-release).
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_DRY, "sim", _row("B"), "out.csv", 101.0, _ok_writer([]))
    assert res.decision == live_guard.DRY_RUN
    assert daily.remaining() == 1                        # INVARIATO: anti-overtrading


def test_dry_run_multi_non_restituisce_slot_di_write_reali():
    """P3-rs1 audit #114 (ANTI-OVERTRADING, multi-row `commit_signals`): stesso invariante di lockstep
    sul percorso multi. Un blocco in DRY_RUN, dopo righe reali che hanno consumato quota, NON deve
    restituire alcuna slot reale.

    Fail-first: ripristinando il loop `daily.release()` DRY_RUN in `commit_signals`, `remaining`
    risalirebbe (over-release) e l'assert fallirebbe."""
    tracker, daily, queue = _fresh(mode=signal_queue.APPEND_ACTIVE, max_active=0, max_per_day=3)
    # Blocco REALE da 2 righe (auto-raise del tetto in append): con l'ammissione PER-BLOCCO
    # (AC-M3 audit #114) il MESSAGGIO consuma UNA slot, non una per gamba → 1/3.
    r1 = write_path.commit_signals(
        tracker, daily, queue, CFG_REAL, "reale", [_row("A"), _row("B")], "out.csv", 100.0,
        _ok_writer([]))
    assert r1.decision == live_guard.WRITE
    assert daily.remaining() == 2
    # Blocco in DRY_RUN con 2 righe nuove: il daily resta INVARIATO (nessun over-release).
    res = write_path.commit_signals(
        tracker, daily, queue, CFG_DRY, "sim", [_row("C"), _row("D")], "out.csv", 101.0,
        _ok_writer([]))
    assert res.decision == live_guard.DRY_RUN
    assert daily.remaining() == 2                        # INVARIATO: anti-overtrading


def test_write_reale_resta_deduplicato_nessuna_doppia_scommessa():
    """#184 low-tracker-nonwrite (guardia anti-regressione): un WRITE reale CONSUMA ancora il
    dedupe, quindi un re-send identico nella finestra resta DUPLICATE → nessuna doppia scommessa."""
    tracker, daily, queue = _fresh()
    write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "X", _row("X"), "out.csv", 100.0, _ok_writer([]))
    written = []
    res = write_path.commit_signal(
        tracker, daily, queue, CFG_REAL, "X", _row("X"), "out.csv", 101.0, _ok_writer(written))
    assert res.decision == live_guard.DUPLICATE          # ancora soppresso
    assert written == []


def test_tracker_none_scrive_come_write():
    # Nessun guardrail (tracker None) → decisione di default WRITE.
    _, _, queue = _fresh()
    written = []
    row = _row("A")
    res = write_path.commit_signal(
        None, None, queue, CFG_REAL, "msgA", row, "out.csv", 100.0, _ok_writer(written))
    assert res.decision == live_guard.WRITE
    assert res.write_error is None
    assert written == [[row]]
