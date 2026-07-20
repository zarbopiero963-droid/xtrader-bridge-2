"""Sezione critica del percorso di scrittura del segnale (#136 item 1, slice 6).

Estratta da `App._process`: la sequenza **valuta-guardrail → coda → scrittura CSV →
rollback**, cioè il cuore anti-doppia-scommessa. Tenerla qui la rende esercitabile in
CI con coda/tracker/daily **reali** e una `write_rows` iniettabile che può fallire.

INVARIANTI (non negoziabili):
- **Lock del chiamante.** `commit_signal` NON prende il lock: `App._process` lo invoca
  mentre tiene `_queue_lock`. `SignalTracker`/`DailyLimiter`/`SignalQueue` non hanno lock
  interno, e la sequenza «valuta + scrivi» deve restare atomica (audit A2), altrimenti
  due callback interlacciati potrebbero passare entrambi il dedup → doppia scommessa.
- **Solo WRITE scrive.** Ogni altro esito `live_guard` (DUPLICATE/RATE_LIMITED/
  DAILY_LIMITED/DRY_RUN) sopprime la scrittura e non tocca la coda. Inoltre lo stato dei
  guardrail riflette SOLO i WRITE reali: il consumo fatto da `evaluate` su un esito che NON
  scrive viene disfatto. DAILY_LIMITED → si annulla solo l'hash del tracker (il tetto non aveva
  consumato slot, solo normalizzato il giorno: si preserva, altrimenti un giorno corrotto
  bloccherebbe per sempre). DRY_RUN → si annulla solo l'hash del tracker: (P3-rs1 audit #114)
  `evaluate` valuta DRY_RUN PRIMA di `daily.allow()`, quindi in simulazione NESSUNA slot
  giornaliera è consumata e non serve alcun `release()` (che, senza consumo, restituirebbe la
  slot di un WRITE reale precedente → overtrading). Così la simulazione non consuma tetto/dedupe
  reali e un segnale soppresso resta ritentabile, senza rischio di doppia scommessa
  (#184 low-tracker-nonwrite).
- **Rollback fail-safe.** Se la scrittura CSV fallisce, coda E guardrail tornano allo
  stato precedente (allineati al CSV ancora su disco): il segnale resta RITENTABILE e in
  OVERWRITE_LAST il precedente non va perso. Stesso rollback dei guardrail quando il
  segnale è oltre il tetto di righe attive (#136 p5): non accodato → ritentabile.
- **Nessun side-effect oltre `write_rows`.** Niente GUI, niente persistenza su disco dei
  guardrail (resta a carico di `App` dopo il commit), niente eccezioni propagate per un
  fallimento di scrittura (riportato in `CommitResult.write_error`).

`evaluate` (dedup/limiti/dry-run) è chiamato SENZA `now`: il dedup usa il proprio
wallclock persistito; `now` (monotòno) serve solo alla coda (expire/add), come in origine.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import live_guard, safety_guard, signal_dedupe, signal_queue


@dataclass(frozen=True)
class CommitResult:
    """Esito della sezione critica.

    - `decision`: esito `live_guard` (WRITE o un esito che sopprime la scrittura);
    - `blocked_by_cap`: True se — pur essendo WRITE — il nuovo segnale è oltre il tetto
      di righe attive (#136 p5): NON accodato, guardrail già ripristinati. Il CSV viene
      riscritto SOLO se `expire` ha rimosso righe scadute (disco da sincronizzare);
      altrimenti il contenuto attivo su disco è già identico e non si tocca (#259 C2);
    - `rows`: righe attive (post-expire) nel ramo WRITE — scritte, salvo il caso
      cap-senza-scaduti qui sopra dove sono riportate ma il CSV non è riscritto;
      `[]` altrimenti;
    - `write_error`: l'eccezione se la scrittura CSV è fallita (con rollback completo),
      altrimenti `None`;
    - `write_attempted`: True se `write_rows` è stata CHIAMATA (riuscita o fallita).
      Serve al contatore CSV-lock (#153 H2) del chiamante: un esito WRITE che NON ha
      toccato il disco (cap-senza-scaduti, #259 C2) non deve contare come successo di
      scrittura — falsificherebbe il recovery di un CSV bloccato.
    """

    decision: str
    blocked_by_cap: bool
    rows: list
    write_error: BaseException | None
    write_attempted: bool = False


def commit_signal(tracker, daily, queue, cfg, text, row, path, now, write_rows,
                  disk_dirty=False):
    """Esegue, SOTTO IL LOCK DEL CHIAMANTE, la sequenza valuta-guardrail → coda →
    scrittura con rollback fail-safe (vedi il docstring del modulo per le invarianti).

    `disk_dirty` (Codex P1 #300): True se il chiamante sa che il CSV su disco può essere
    STANTIO rispetto alla coda — una riscrittura precedente (post-conferma o post-scadenza)
    è fallita e il suo retry non è ancora riuscito. In quel caso il ramo cap-senza-scaduti
    NON salta la scrittura: il presupposto «disco già identico» non vale e il commit
    riallinea il disco alle righe attive correnti.

    Ritorna una `CommitResult`. Non solleva mai per un fallimento di scrittura: ripristina
    coda E guardrail e riporta l'eccezione in `write_error`."""
    decision = live_guard.WRITE
    blocked_by_cap = False
    rows = []
    write_error = None
    write_attempted = False
    tracker_snap = daily_snap = None

    def _restore_guards():
        # Riporta tracker E daily allo snapshot pre-valutazione: il segnale torna
        # RITENTABILE. Unico punto di rollback dei guardrail per tutti i rami
        # (cap-senza-scaduti, cap-con-scaduti, write fallita): tenerli in lockstep.
        if tracker is not None:
            tracker.restore_state(tracker_snap)
            if daily is not None and daily_snap is not None:
                daily.restore_state(daily_snap)

    # `tracker is None` (test/chiamanti senza guardrail) → resta WRITE di default.
    if tracker is not None:
        tracker_snap = tracker.state()
        daily_snap = daily.state() if daily is not None else None
        # kyW #192: controllo cross-namespace PRE-scrittura. La dedup single-row è sull'hash-messaggio,
        # ma la stessa riga può essere già stata scritta dal percorso MULTI (chiave per-riga) — anche
        # da uno stato dedupe PERSISTITO da una versione precedente. Se la chiave per-riga è già vista,
        # è un duplicato → non scrivere (fail-closed anti-doppia-scommessa), invece di controllare solo
        # l'hash-messaggio che il percorso multi non registra.
        #
        # P2-1 audit #76: la finestra del tracker (default 300s) può essere PIÙ CORTA della vita
        # della riga (`confirmation_timeout`/`clear_delay`): un reinvio identico oltre la finestra
        # sarebbe NEW e in APPEND/QUEUE accoderebbe una SECONDA riga uguale → doppia scommessa.
        # Quindi una riga la cui chiave è ancora tra le ATTIVE della coda (non scadute, provenienza
        # esatta memorizzata all'add) è un DUPLICATE a prescindere dalla finestra. Escluso
        # OVERWRITE_LAST: lì `add` SOSTITUISCE (mai doppia riga) e il reinvio deve poter
        # riscrivere l'ultima istruzione (comportamento storico invariato).
        key = signal_dedupe.row_dedup_key(text, row)
        # Filtro difensivo (review #77 Fable): si confrontano solo chiavi NON vuote, allineato al
        # percorso multi. Oggi `row_dedup_key` non può restituire "" (sha256 hexdigest, sempre 64
        # char), ma se un refactor futuro lo permettesse, una chiave vuota NON deve combaciare con
        # una riga legacy accodata senza chiave ("") e bloccare un segnale nuovo (over-blocking).
        if tracker.is_seen(key) or (
                queue.mode != signal_queue.OVERWRITE_LAST and key
                and key in {k for k in queue.active_keys(now=now) if k}):
            decision = live_guard.DUPLICATE
        else:
            decision = live_guard.evaluate(cfg, tracker, daily, text)

    if decision == live_guard.WRITE:
        # Coda dei segnali attivi: expire dei già scaduti, add del nuovo, riscrittura
        # atomica di TUTTE le righe attive. Snapshot per il rollback su write fallita.
        queue_snap = queue.state()
        expired = queue.expire(now=now)
        # Accoda la riga con la sua chiave PER-RIGA (provenienza): serve al commit MULTI di un
        # eventuale passaggio di modalità a runtime (single→multi). In OVERWRITE_LAST `commit_signals`
        # tiene una riga duplicata solo se la sua chiave è tra `queue.active_keys()`; senza questa
        # chiave la riga già attiva verrebbe scartata dal blocco A+B (kyh + kyW #192, Codex).
        sid = queue.add(row, now=now, dedup_key=signal_dedupe.row_dedup_key(text, row))
        # `add` ritorna None se il nuovo segnale è oltre il tetto (#136 p5): le righe
        # attive restano quelle correnti (post-expire).
        blocked_by_cap = sid is None
        rows = queue.active_rows()
        if blocked_by_cap and not expired and not disk_dirty:
            # #259 C2: bloccato dal tetto E nessuna riga scaduta rimossa → il contenuto attivo
            # su disco è già identico a `rows` (l'unico altro mutatore, `add`, non ha accodato).
            # Riscrivere sarebbe un no-op che tocca mtime/inode del CSV e riapre la finestra di
            # ri-lettura lato XTrader. Si scrive comunque in DUE casi in cui il disco va
            # riallineato: `expire` HA rimosso righe (coda sovra-riempita via force=True dal
            # percorso multi-row #192 che resta piena al tetto → le scadute sono ancora su
            # disco), oppure `disk_dirty` (una riscrittura precedente è fallita e il retry non
            # è ancora riuscito: il disco è indietro rispetto alla coda — Codex P1 #300).
            _restore_guards()   # segnale NON accodato → ritentabile
            return CommitResult(decision=decision, blocked_by_cap=True,
                                rows=rows, write_error=None, write_attempted=False)
        write_attempted = True   # unico punto in cui `write_rows` viene chiamata
        try:
            write_rows(rows, path)
        except Exception as ex:   # noqa: BLE001 — riportato al chiamante, no crash
            # Scrittura fallita: RIPRISTINA coda E guardrail (allineati al CSV su disco).
            queue.restore_state(queue_snap)
            _restore_guards()
            write_error = ex
        else:
            if blocked_by_cap:
                # Bloccato dal tetto (con righe scadute rimosse, vedi sopra): segnale NON
                # accodato → rollback guardrail (ritentabile).
                _restore_guards()
            elif tracker is not None:
                # Scrittura REALE riuscita (single-row, dedup a hash-messaggio): ombreggia ANCHE la
                # chiave PER-RIGA di questa riga (#192 kyW). Così un retry dello STESSO messaggio dopo
                # una transizione del parser a MULTI-riga riconosce la riga già scritta come duplicato
                # (la chiave per-riga di quella riga è già "vista"), invece di riscriverla → doppia
                # scommessa. Lo shadow non conta verso il rate-limit (`mark_seen`).
                tracker.mark_seen(signal_dedupe.row_dedup_key(text, row))
    elif tracker is not None and decision == live_guard.DAILY_LIMITED:
        # `evaluate` aveva registrato l'hash nel tracker (segnale NEW) ma `daily.allow()` ha
        # RIFIUTATO **senza consumare** una slot — ha solo (eventualmente) normalizzato il giorno
        # corrente. Si annulla SOLO l'hash del tracker (segnale ritentabile dopo il reset), NON si
        # tocca il daily: ripristinare il suo snapshot riporterebbe un giorno corrotto (state file
        # malformato) e lascerebbe il bridge bloccato per sempre (#184 low-tracker-nonwrite, Codex).
        tracker.restore_state(tracker_snap)
    elif tracker is not None and decision == live_guard.DRY_RUN:
        # Simulazione: `evaluate` ha registrato l'hash nel tracker ma (P3-rs1 audit #114) NON consuma
        # più alcuna slot giornaliera — il check DRY_RUN precede `daily.allow()`. Basta annullare
        # l'hash del tracker perché la simulazione non intacchi dedupe reali; il `daily` non è stato
        # toccato, quindi nessun `release()` (che, senza consumo, restituirebbe la slot di un WRITE
        # reale precedente → overtrading). DUPLICATE/RATE_LIMITED non aggiungono nulla.
        tracker.restore_state(tracker_snap)

    return CommitResult(decision=decision, blocked_by_cap=blocked_by_cap,
                        rows=rows, write_error=write_error,
                        write_attempted=write_attempted)


def _summary_decision(decisions: list, accepted: int) -> str:
    """Esito riassuntivo del commit multi-riga: WRITE se almeno una riga è stata accodata,
    altrimenti il primo esito di soppressione (DUPLICATE/RATE_LIMITED/DAILY_LIMITED) per la
    diagnostica."""
    if accepted > 0:
        return live_guard.WRITE
    for d in decisions:
        if d != live_guard.WRITE:
            return d
    return live_guard.WRITE


def _noop_decision(decisions: list) -> str:
    """Esito di un commit `OVERWRITE_LAST` che NON ha cambiato il CSV (reinvio identico, o righe
    tutte soppresse/non-attive): **mai** WRITE — nulla è stato scritto, quindi `_process` deve
    prendere il percorso non-write. Riporta il primo esito di soppressione se presente; se invece
    tutte le righe erano WRITE ma il blocco coincideva già con l'attivo (chiavi dedup scadute con
    `clear_delay` > finestra dedup), l'esito è `DUPLICATE` (di fatto un reinvio identico)."""
    for d in decisions:
        if d != live_guard.WRITE:
            return d
    return live_guard.DUPLICATE


def _same_rows_unordered(a: list, b: list) -> bool:
    """True se `a` e `b` contengono lo **stesso multiset di righe** a PRESCINDERE dall'ordine. In
    `OVERWRITE_LAST` un reinvio con le sole righe **riordinate** (`A+B` vs `B+A`) è semanticamente
    identico: il CSV non va riscritto (XTrader non deve riconsumare un'istruzione uguale) — Codex
    #281. Le righe sono dict con valori stringa (contratto CSV), quindi confrontabili per contenuto."""
    if len(a) != len(b):
        return False
    ca = sorted(tuple(sorted(r.items())) for r in a)
    cb = sorted(tuple(sorted(r.items())) for r in b)
    return ca == cb


def commit_signals(tracker, daily, queue, cfg, text, rows, path, now, write_rows,
                   disk_dirty=False):
    """Commit MULTI-RIGA (#192): un singolo messaggio produce più righe (MultiMarket/
    MultiSelection). Valuta OGNI riga con **deduplica PER-RIGA** (`signal_dedupe.row_dedup_key`),
    accoda le righe `WRITE` e riscrive ATOMICAMENTE tutte le righe attive, con rollback fail-safe.

    Stesse invarianti di `commit_signal` (vedi docstring del modulo): chiamato SOTTO il lock del
    chiamante; solo le righe `WRITE` finiscono in coda; in `DRY_RUN` il CSV operativo NON viene
    scritto e i guardrail consumati sono ripristinati; se la scrittura fallisce, coda E guardrail
    tornano allo stato precedente (segnali ritentabili). Per il single-row usare `commit_signal`
    (percorso legacy, comportamento bit-identico e invariato).

    Accodamento per modo coda (Codex/CodeRabbit #239/#192):
    - `OVERWRITE_LAST`: l'«ultima istruzione» è il BLOCCO INTERO del messaggio → il blocco è
      composto dalle righe NUOVE (`WRITE`) del messaggio PIÙ le righe `DUPLICATE` che sono **ancora
      attive con la STESSA provenienza** (chiave dedup memorizzata al piazzamento, confrontata via
      `queue.active_keys`), con i **valori del messaggio corrente**. Così: un'espansione `A→A+B`
      riscrive TENENDO A (kyh #192); un duplicato **scaduto** NON viene rivissuto (rispetta il
      clear-timeout) e due regole che risolvono alla **stessa riga** non la scrivono due volte
      (dedup intra-blocco) — Codex #281 P1. Il CSV è riscritto SOLO se il blocco **differisce, per
      contenuto, dalle righe già attive**: un reinvio identico non tocca il CSV (XTrader non
      riconsuma; su questo no-op i guardrail consumati da eventuali chiavi scadute sono
      **ripristinati**), uno shrink `A+B→A` riscrive togliendo B, un blocco vuoto NON svuota il CSV
      (lo svuotamento a timeout è dell'expire-tick).
    - `APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED`: `queue.add(..., force=True)` per ogni riga NUOVA →
      **auto-raise del tetto** (decisione proprietario #192): il blocco coerente di UN messaggio
      multi NON viene MAI spezzato dal tetto `max_active`. Elimina alla radice il partial-drop
      silenzioso (alcune righe scritte, altre troncate dal tetto senza avviso; Codex #281). Il
      tetto continua a limitare l'accumulo TRA messaggi distinti sul percorso single-row.

    Accounting guardrail PER-BLOCCO (AC-M3 audit #114, decisione proprietario 2026-07-20; mirror
    del single-row, dove `evaluate` gira UNA volta per messaggio): il MESSAGGIO — non la singola
    gamba — consuma 1 slot rate e 1 slot daily. I limiti rate/daily NON spezzano MAI il blocco:
    a limite già esaurito l'INTERO blocco è soppresso con esito onesto (`RATE_LIMITED`/
    `DAILY_LIMITED`) e resta ritentabile (tracker ripristinato; il daily non aveva consumato slot,
    solo normalizzato il giorno) — mai un partial-drop silenzioso di alcune gambe (un dutching o
    esce intero o non esce). La deduplica resta PER-RIGA (provenienza, espansione A→A+B,
    cross-namespace, intra-blocco: invariate). Se NESSUNA riga NUOVA è presente (tutte duplicati),
    il CSV operativo NON viene toccato (come il single-row su DUPLICATE). In `DRY_RUN` non si
    scrive e i guardrail sono ripristinati. Se la scrittura fallisce, coda E guardrail tornano
    allo stato precedente. Per il single-row usare `commit_signal` (percorso legacy invariato).

    `disk_dirty` (D1 audit #114, simmetria con `commit_signal`): True se il chiamante sa che il CSV
    su disco può essere STANTIO rispetto alla coda — una riscrittura precedente (post-conferma o
    post-scadenza) è fallita e il retry non è ancora riuscito. In quel caso i rami no-op (OVERWRITE
    col blocco == attivo, oppure APPEND senza righe nuove) NON saltano la scrittura: il presupposto
    «disco già identico» non vale e si RIALLINEA il disco riscrivendo le righe attive correnti (i
    guardrail vengono comunque ripristinati e l'esito resta l'esito non-WRITE onesto — DUPLICATE/
    limite — così `_process` non lo tratta come un nuovo piazzamento, ma sa che il disco è stato
    riallineato per azzerare `_csv_dirty` su successo)."""
    rows = list(rows or [])
    # kyW #192: fallback cross-namespace PRE-scrittura per uno stato dedupe PERSISTITO da una versione
    # precedente SOLO single-row (che ha registrato l'hash-messaggio ma NON le chiavi per-riga). Se
    # l'hash-messaggio è già visto e NESSUNA delle chiavi per-riga di questo messaggio lo è, il
    # messaggio è già stato processato come single-row → fail-closed: si sopprime l'intero blocco (non
    # è possibile identificare quale riga corrispondesse), invece di riscriverlo → doppia scommessa. Se
    # invece almeno una chiave per-riga è già vista, è un normale duplicato/espansione multi (gestito
    # per-riga, così l'espansione A→A+B non viene soppressa).
    if tracker is not None and rows:
        row_keys = [signal_dedupe.row_dedup_key(text, r) for r in rows]
        if tracker.is_seen(signal_dedupe.message_hash(text)) and \
                not any(tracker.is_seen(k) for k in row_keys):
            return CommitResult(decision=live_guard.DUPLICATE, blocked_by_cap=False,
                                rows=[], write_error=None)
    tracker_snap = tracker.state() if tracker is not None else None
    daily_snap = (daily.state() if (tracker is not None and daily is not None) else None)
    queue_snap = queue.state()
    overwrite = queue.mode == signal_queue.OVERWRITE_LAST
    queue.expire(now=now)
    # OVERWRITE_LAST: chiavi (PROVENIENZA esatta, memorizzate al piazzamento) delle righe ANCORA
    # attive dopo l'expire. Una riga duplicata dell'istruzione va tenuta nel blocco SOLO se
    # corrisponde a una di queste (stessa chiave = stessa riga già piazzata): così non si rivive un
    # segnale SCADUTO (clear-timeout) né si scambia una riga di un ALTRO messaggio con la corrente
    # (Codex #281 P1/provenance). Le chiavi sono lette dalla coda, NON ricalcolate dal testo corrente.
    active_keys = set(queue.active_keys(now=now)) if overwrite else set()
    # P2-1 audit #76 (solo APPEND/QUEUE): una riga la cui chiave è ancora ATTIVA in coda è un
    # DUPLICATE anche se l'hash è uscito dalla finestra dedup del tracker (vita riga > finestra):
    # senza questo check un reinvio identico oltre la finestra verrebbe ri-accodato con
    # `force=True` → seconda riga uguale nel CSV → doppia scommessa. Chiavi vuote escluse (righe
    # legacy accodate senza `dedup_key` non devono mai bloccare). In OVERWRITE il blocco è già
    # protetto da `active_keys` + `_same_rows_unordered` (reinvio identico = no-op).
    queue_active = set() if overwrite else {k for k in queue.active_keys(now=now) if k}

    decisions = []
    fresh = []             # righe NUOVE (non duplicate) di QUESTO messaggio, in ordine
    fresh_keys = []        # chiavi parallele a `fresh` (provenienza)
    block = []             # OVERWRITE_LAST: righe dell'istruzione corrente da tenere attive
    block_keys = []        # chiavi parallele a `block` (provenienza, memorizzate per il commit dopo)
    seen_in_block = set()  # dedup INTRA-blocco: una stessa chiave non entra due volte (no doppia riga)
    for row in rows:
        if tracker is None:
            # Chiamanti senza guardrail (test): ogni riga è NUOVA, nessuna dedup disponibile.
            decisions.append(live_guard.WRITE)
            fresh.append(row)
            fresh_keys.append("")
            block.append(row)
            block_keys.append("")
            if not overwrite:
                queue.add(row, now=now, force=True)
            continue
        key = signal_dedupe.row_dedup_key(text, row)
        if key in queue_active:
            # P2-1 #76: riga identica ANCORA attiva (provenienza esatta) → duplicato, senza
            # consumare tracker/daily (nessun `evaluate`): non accodata, non scritta.
            decisions.append(live_guard.DUPLICATE)
            continue
        if key in seen_in_block:
            # Dedup intra-blocco (due regole → stessa riga, Codex #281 P1): la seconda
            # occorrenza non entra due volte né nel blocco né in coda.
            decisions.append(live_guard.DUPLICATE)
            continue
        if tracker.is_seen(key):
            decisions.append(live_guard.DUPLICATE)
            # OVERWRITE_LAST: una riga duplicata resta nel blocco SOLO se è ANCORA attiva con la
            # STESSA provenienza (kyh #192): altrimenti riscriverebbe un segnale scaduto (viola il
            # clear-timeout) o duplicherebbe una riga già presente (Codex #281 P1). Si usa la riga
            # del MESSAGGIO corrente (valori aggiornati), non quella stantia in coda.
            if overwrite and key in active_keys:
                block.append(row)
                block_keys.append(key)
                seen_in_block.add(key)
            continue
        # Riga NUOVA: la classificazione qui NON consuma guardrail — l'ammissione rate/daily
        # è PER-BLOCCO, una sola volta per messaggio (AC-M3, vedi sotto).
        decisions.append(live_guard.WRITE)
        fresh.append(row)
        fresh_keys.append(key)
        seen_in_block.add(key)
        if overwrite:
            block.append(row)
            block_keys.append(key)

    # ── Ammissione PER-BLOCCO dei guardrail (AC-M3 audit #114, decisione proprietario
    # 2026-07-20). Mirror del single-row, dove `evaluate` gira UNA volta per messaggio:
    # il MESSAGGIO — non la singola gamba — consuma 1 slot rate e 1 slot daily. Un dutching
    # non viene MAI spezzato dai limiti: o esce intero, o (limite già esaurito) è soppresso
    # INTERO con esito onesto — mai gambe scartate in silenzio (partial-drop). La prima
    # chiave nuova passa da `evaluate` (dedup + rate + dry-run + daily); le altre sono
    # ombreggiate con `mark_seen` (valgono per la dedup dei reinvii, NON contano verso il
    # rate-limit: la slot del messaggio è già stata consumata dalla prima).
    block_decision = live_guard.WRITE
    if tracker is not None and fresh:
        block_decision = live_guard.evaluate(cfg, tracker, daily, text,
                                             dedup_key=fresh_keys[0])
        if block_decision == live_guard.WRITE:
            for k in fresh_keys[1:]:
                tracker.mark_seen(k)
            if not overwrite:
                # Auto-raise del tetto (#192): `force=True` → la riga NUOVA entra sempre; la
                # chiave è memorizzata sul segnale per la provenienza al commit successivo.
                for row, key in zip(fresh, fresh_keys):
                    queue.add(row, now=now, force=True, dedup_key=key)

    # DRY_RUN: simulazione → NON scrivere il CSV operativo; ripristina coda E tracker. (P3-rs1 audit
    # #114) `evaluate` valuta DRY_RUN PRIMA di `daily.allow()`, quindi in simulazione NESSUNA slot
    # giornaliera è stata consumata: niente `release()` (che, senza consumo, restituirebbe la slot di
    # un WRITE reale precedente → overtrading). Basta ripristinare coda e tracker (dedupe coerente).
    if safety_guard.is_dry_run(cfg):
        queue.restore_state(queue_snap)
        if tracker is not None:
            tracker.restore_state(tracker_snap)
        return CommitResult(decision=live_guard.DRY_RUN, blocked_by_cap=False,
                            rows=[], write_error=None)

    def _realign_dirty_disk(dec):
        """D1 audit #114: disco STANTIO (retry pendente) + commit multi senza cambiamento LOGICO →
        riscrive le righe attive correnti per RIALLINEARE il disco, senza toccare la coda (già
        post-expire) né i guardrail (già ripristinati dal chiamante). Esito NON-WRITE onesto (`dec`)
        con `write_attempted=True`: `_process` non lo tratta come nuovo piazzamento ma, su successo,
        azzera `_csv_dirty`. Su write ancora fallita, il disco resta stantio (`_csv_dirty` invariato,
        retry pendente) — nessun rollback ulteriore: non abbiamo accodato nulla di nuovo."""
        active_now = queue.active_rows(now=now)
        try:
            write_rows(active_now, path)
        except Exception as ex:   # noqa: BLE001 — riportato al chiamante, no crash
            return CommitResult(decision=dec, blocked_by_cap=False, rows=[],
                                write_error=ex, write_attempted=True)
        return CommitResult(decision=dec, blocked_by_cap=False, rows=active_now,
                            write_error=None, write_attempted=True)

    if block_decision in (live_guard.RATE_LIMITED, live_guard.DAILY_LIMITED):
        # AC-M3: blocco INTERO soppresso — nessuna gamba accodata né scritta (niente partial).
        # Si annulla la registrazione della prima chiave nel tracker (messaggio ritentabile);
        # su DAILY_LIMITED il daily NON ha consumato slot (solo normalizzato il giorno):
        # come nel single-row, non si ripristina il suo snapshot.
        tracker.restore_state(tracker_snap)
        if disk_dirty:
            # D1 #114: disco stantio (retry pendente) → si riallinea comunque alle righe
            # attive correnti (coda post-expire), con l'esito non-WRITE onesto.
            return _realign_dirty_disk(block_decision)
        queue.restore_state(queue_snap)
        return CommitResult(decision=block_decision, blocked_by_cap=False,
                            rows=[], write_error=None)

    if overwrite:
        # Il blocco È l'istruzione corrente (righe nuove + duplicate ANCORA attive). Si riscrive il
        # CSV SOLO se differisce — per contenuto — dalle righe già attive: reinvio identico → nessuna
        # riscrittura (XTrader non riconsuma), espansione A→A+B → riscrive tenendo A (kyh #192),
        # shrink A+B→A → riscrive togliendo B. Un blocco vuoto (tutte soppresse/scadute) NON svuota
        # il CSV: lo svuotamento a timeout è compito dell'expire-tick, non di un reinvio.
        current_active = queue.active_rows(now=now)
        if not block or _same_rows_unordered(block, current_active):
            # NESSUN cambiamento reale (blocco == attivo, anche solo RIORDINATO) → RIPRISTINA i
            # guardrail: una riga WRITE con chiave dedup SCADUTA (clear_delay > finestra dedup) ha
            # già registrato tracker/daily pur non scrivendo nulla; senza rollback conterebbe un
            # non-write contro i limiti e `_process` lo vedrebbe come WRITE riuscito (Codex #281).
            if tracker is not None:
                tracker.restore_state(tracker_snap)
                # daily: `release()` della slot consumata dal blocco (AC-M3: l'ammissione è
                # per-MESSAGGIO → al più UNA slot, se c'era almeno una riga nuova aged-out),
                # mantenendo il giorno normalizzato — non `restore_state` (reintrodurrebbe un
                # giorno malformato).
                if daily is not None and fresh:
                    daily.release()
            if disk_dirty:
                # D1: blocco == attivo ma il DISCO è STANTIO (retry pendente) → si RIALLINEA
                # riscrivendo le righe attive correnti. La coda resta post-expire (== current_active)
                # per combaciare col disco riscritto: NON si ripristina la coda qui.
                return _realign_dirty_disk(_noop_decision(decisions))
            # Disco già identico all'attivo → non riscrivere (XTrader non riconsuma) e RIPRISTINA la
            # coda: l'expire di un reinvio identico non è compito suo, ma dell'expire-tick.
            queue.restore_state(queue_snap)
            return CommitResult(decision=_noop_decision(decisions), blocked_by_cap=False,
                                rows=current_active, write_error=None)
        queue.replace_block(block, now=now, keys=block_keys)
    elif not fresh:
        if disk_dirty:
            # D1 audit #114: nessuna riga NUOVA ma DISCO STANTIO (retry pendente) → si RIALLINEA
            # riscrivendo le righe attive correnti (post-expire). Nessun guardrail nuovo da annullare
            # (in append le righe NUOVE sono sempre accodate → finiscono in `fresh`, qui vuoto).
            # La coda resta post-expire per combaciare col disco riscritto.
            return _realign_dirty_disk(_summary_decision(decisions, 0))
        # APPEND/QUEUE: nessuna riga NUOVA accodata (tutte duplicati) → CSV invariato (come il
        # single-row su DUPLICATE). Nessun guardrail da annullare: in append le righe NUOVE sono
        # sempre accodate (`force=True`) quindi finiscono in `fresh`; qui non ce n'erano.
        queue.restore_state(queue_snap)
        return CommitResult(decision=_summary_decision(decisions, 0), blocked_by_cap=False,
                            rows=[], write_error=None)

    active = queue.active_rows()
    try:
        write_rows(active, path)
    except Exception as ex:   # noqa: BLE001 — riportato al chiamante, no crash
        queue.restore_state(queue_snap)
        if tracker is not None:
            tracker.restore_state(tracker_snap)
            if daily is not None and daily_snap is not None:
                daily.restore_state(daily_snap)
        return CommitResult(decision=live_guard.WRITE, blocked_by_cap=False,
                            rows=[], write_error=ex, write_attempted=True)

    # Si arriva qui solo dopo un CAMBIAMENTO reale (blocco OVERWRITE differente, o righe NUOVE in
    # append) e una scrittura riuscita → l'esito è WRITE (uno shrink OVERWRITE ha `new_rows` vuoto
    # ma HA scritto: non va riportato come DUPLICATE, altrimenti `_process` salterebbe il post-write).
    if tracker is not None:
        # Scrittura REALE riuscita (multi, dedup PER-RIGA): ombreggia ANCHE l'hash-messaggio (#192
        # kyW). Così un retry dello STESSO messaggio dopo una transizione del parser a SINGLE-row —
        # che deduplica sull'hash-messaggio, mai registrato dal percorso multi — riconosce il
        # messaggio come già processato (DUPLICATE) invece di riscriverlo → doppia scommessa.
        # Fail-closed a livello di messaggio: al più restrittivo, mai una scommessa doppia. Lo
        # shadow non conta verso il rate-limit (`mark_seen`).
        tracker.mark_seen(signal_dedupe.message_hash(text))
    return CommitResult(decision=live_guard.WRITE, blocked_by_cap=False,
                        rows=active, write_error=None, write_attempted=True)
