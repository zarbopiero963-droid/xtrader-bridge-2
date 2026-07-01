"""Test della scrittura CSV atomica (PR-05).

Verifica che `write_csv`/`init_csv` producano sempre un file valido (header +
eventuale riga), senza lasciare file temporanei, e che concorrenza write/clear
non corrompa il file (lock condiviso). Chiude #2 (race) e #6 (scrittura atomica).
"""

import builtins
import csv
import glob
import os
import threading

import pytest

from xtrader_bridge import csv_writer

ROW = {
    "Provider": "PBet", "EventId": "", "EventName": "Inter v Milan", "MarketId": "",
    "MarketName": "MATCH ODDS", "MarketType": "MATCH_ODDS", "SelectionId": "",
    "SelectionName": "Inter", "Handicap": "0", "Price": "1.85", "MinPrice": "",
    "MaxPrice": "", "BetType": "PUNTA", "Points": "",
}


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def _no_tmp_left(d):
    return glob.glob(os.path.join(d, ".segnali_*.tmp")) == []


def test_write_csv_header_piu_una_riga(tmp_path):
    p = tmp_path / "segnali.csv"
    csv_writer.write_csv(ROW, str(p))
    rows = _read(str(p))
    assert rows[0] == csv_writer.CSV_HEADER          # header esatto
    assert len(rows) == 2                            # header + 1 segnale
    assert rows[1][0] == "PBet"
    assert _no_tmp_left(str(tmp_path))               # nessun .tmp residuo


def test_init_csv_solo_header(tmp_path):
    p = tmp_path / "segnali.csv"
    csv_writer.init_csv(str(p))
    rows = _read(str(p))
    assert rows == [csv_writer.CSV_HEADER]           # solo header
    assert _no_tmp_left(str(tmp_path))


def test_bom_presente(tmp_path):
    p = tmp_path / "segnali.csv"
    csv_writer.write_csv(ROW, str(p))
    assert open(p, "rb").read().startswith(b"\xef\xbb\xbf")


def test_scritture_ripetute_non_appendono(tmp_path):
    p = tmp_path / "segnali.csv"
    for _ in range(5):
        csv_writer.write_csv(ROW, str(p))            # 5 segnali consecutivi
    rows = _read(str(p))
    assert len(rows) == 2                            # sempre header + 1 (sovrascrive)
    assert _no_tmp_left(str(tmp_path))


def test_clear_dopo_write_lascia_solo_header(tmp_path):
    p = tmp_path / "segnali.csv"
    csv_writer.write_csv(ROW, str(p))
    csv_writer.init_csv(str(p))
    assert _read(str(p)) == [csv_writer.CSV_HEADER]


# ── anti-segnale-stantio: clear_stale_csv (recovery dopo crash/blackout) ─────

def test_clear_stale_csv_rimuove_riga_orfana(tmp_path):
    # Scenario blackout: una sessione precedente ha lasciato una riga attiva nel CSV.
    # All'avvio/STOP la riga orfana deve sparire (resta solo header).
    p = tmp_path / "segnali.csv"
    csv_writer.write_csv(ROW, str(p))                 # riga "stantia" lasciata sul disco
    # Stato di partenza esplicito (header + riga attesa): se il writer cambiasse
    # comportamento (es. righe extra), questo test lo farebbe emergere subito.
    rows_prima = _read(str(p))
    assert rows_prima[0] == csv_writer.CSV_HEADER
    assert rows_prima[1] == [ROW[col] for col in csv_writer.CSV_HEADER]
    assert len(rows_prima) == 2
    assert csv_writer.clear_stale_csv(str(p)) is True
    assert _read(str(p)) == [csv_writer.CSV_HEADER]   # solo header
    assert _no_tmp_left(str(tmp_path))


def test_has_active_row_distingue_riga_da_solo_header(tmp_path):
    # #234: `has_active_row` deve distinguere un CSV del bridge CON una riga dati da uno a SOLO
    # header (riscrittura idempotente). Serve a non registrare un falso crash-recovery all'avvio.
    p = tmp_path / "segnali.csv"
    csv_writer.init_csv(str(p))                        # CSV del bridge a solo header
    assert csv_writer.has_active_row(str(p)) is False
    csv_writer.write_csv(ROW, str(p))                  # ora con una riga attiva
    assert csv_writer.has_active_row(str(p)) is True


def test_has_active_row_falsa_su_assente_vuoto_o_non_bridge(tmp_path):
    # Read-only/best-effort: path vuoto, file assente, o file NON-bridge → False (mai eccezioni).
    assert csv_writer.has_active_row("") is False
    assert csv_writer.has_active_row(str(tmp_path / "non_esiste.csv")) is False
    altro = tmp_path / "documento_utente.csv"
    altro.write_text("colonnaA,colonnaB\nvalore1,valore2\n", encoding="utf-8")
    assert csv_writer.has_active_row(str(altro)) is False   # header diverso da CSV_HEADER


def test_clear_stale_csv_non_tocca_file_non_bridge(tmp_path):
    # Sicurezza (Codex P2): un file esistente che NON è un CSV del bridge (prima
    # riga diversa da CSV_HEADER) non deve mai essere sovrascritto/distrutto.
    p = tmp_path / "documento_utente.csv"
    contenuto = "colonnaA,colonnaB\nvalore1,valore2\n"
    p.write_text(contenuto, encoding="utf-8")
    assert csv_writer.clear_stale_csv(str(p)) is False
    assert p.read_text(encoding="utf-8") == contenuto   # intatto
    # Anche un file di testo non-CSV resta intatto.
    q = tmp_path / "note.txt"
    q.write_text("appunti importanti", encoding="utf-8")
    assert csv_writer.clear_stale_csv(str(q)) is False
    assert q.read_text(encoding="utf-8") == "appunti importanti"


def test_clear_stale_csv_logga_avviso_su_header_diverso(tmp_path, caplog):
    # audit #105 P2: un file esistente con header diverso NON viene ripulito (anti
    # data-loss) MA non più in silenzio: si logga un avviso diagnostico con METADATI
    # strutturali (path + numero colonne) così l'utente capisce perché il file non è stato
    # toccato (es. csv_path sbagliato).
    p = tmp_path / "documento_utente.csv"
    p.write_text("colonnaA,colonnaB\nvalore1,valore2\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="xtrader_bridge.csv_writer"):
        assert csv_writer.clear_stale_csv(str(p)) is False
    msgs = [r.getMessage() for r in caplog.records]
    assert any("non è un CSV del bridge" in m and str(p) in m for m in msgs)
    # Riporta i metadati strutturali (2 colonne rilevate vs le 14 attese), non il contenuto.
    assert any("2 colonne" in m for m in msgs)
    assert any(str(len(csv_writer.CSV_HEADER)) in m for m in msgs)


def test_clear_stale_csv_avviso_non_logga_il_contenuto_header(tmp_path, caplog):
    # Codex P2 (sicurezza): se per errore csv_path punta a un file con un SEGRETO nella prima
    # riga (es. un token), l'avviso NON deve loggarlo verbatim (questo sink non passa per la
    # redazione di event_log). Si verifica che il segreto non compaia in ALCUN messaggio.
    secret = "123456789:AAEdummyBotTokenSecretValue_abcDEF"   # forma di un bot token
    p = tmp_path / "config_per_errore.csv"
    p.write_text(secret + ",altro\nx,y\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="xtrader_bridge.csv_writer"):
        assert csv_writer.clear_stale_csv(str(p)) is False
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "non è un CSV del bridge" in joined        # l'avviso c'è...
    assert secret not in joined                        # ...ma il segreto NON è loggato


def test_clear_stale_csv_on_mismatch_riceve_metadati_non_contenuto(tmp_path):
    # #105 P2 (Codex): `on_mismatch` fa emergere la diagnosi nel log del bridge/GUI (il solo
    # logging.warning non si vede in un EXE --windowed). Riceve i METADATI strutturali, MAI il
    # contenuto/segreto della prima riga.
    secret = "123456789:AAEdummyBotTokenSecretValue_abcDEF"
    p = tmp_path / "config_per_errore.csv"
    p.write_text(secret + ",altro\nx,y\n", encoding="utf-8")
    seen = []
    assert csv_writer.clear_stale_csv(str(p), on_mismatch=seen.append) is False
    assert seen, "on_mismatch deve essere invocato su header diverso"
    assert "non è un CSV del bridge" in seen[0] and str(p) in seen[0]
    assert "2 colonne" in seen[0]                       # metadati strutturali
    assert secret not in seen[0]                        # nessun contenuto/segreto
    assert p.read_text(encoding="utf-8").startswith(secret)   # file NON toccato (anti data-loss)


def test_clear_stale_csv_on_mismatch_non_invocato_se_bridge_o_assente(tmp_path):
    # Su un CSV del bridge (ripulito → True) o un file assente (→ False), `on_mismatch` NON va
    # chiamato: è riservato al solo caso "file esistente ma non-bridge".
    seen = []
    assert csv_writer.clear_stale_csv(str(tmp_path / "manca.csv"),
                                      on_mismatch=seen.append) is False   # assente
    p = tmp_path / "segnali.csv"
    csv_writer.init_csv(str(p))                          # CSV del bridge (solo header)
    assert csv_writer.clear_stale_csv(str(p), on_mismatch=seen.append) is True
    assert seen == []                                   # mai invocato


def test_clear_stale_csv_on_mismatch_che_solleva_non_propaga(tmp_path):
    # Codex P2 (#266): un `on_mismatch` che solleva (es. `_log` su una root Tk distrutta) è
    # best-effort ENFORCED: NON deve propagare e rompere il cleanup anti-segnale-stantio.
    # `clear_stale_csv` ritorna comunque `False` e il file non-bridge resta intatto.
    p = tmp_path / "documento_utente.csv"
    p.write_text("colonnaA,colonnaB\nv1,v2\n", encoding="utf-8")

    def _boom(_msg):
        raise RuntimeError("sink log/GUI fallito (simulato)")

    assert csv_writer.clear_stale_csv(str(p), on_mismatch=_boom) is False   # nessuna propagazione
    assert p.read_text(encoding="utf-8").startswith("colonnaA")             # file intatto


def test_clear_stale_csv_file_non_decodificabile_non_bridge(tmp_path):
    # Codex P2: un file esistente non-UTF8 (CSV ANSI, binario scelto per errore)
    # non deve far crashare l'avvio: trattato come non-bridge e lasciato intatto.
    p = tmp_path / "ansi_o_binario.csv"
    raw = b"\xff\xfe\x00dati binari\x80\x81 non utf8"
    p.write_bytes(raw)
    assert csv_writer.clear_stale_csv(str(p)) is False
    assert p.read_bytes() == raw   # intatto


def test_clear_stale_csv_errore_io_si_propaga(tmp_path, monkeypatch):
    # Codex P2: un errore di I/O reale (permessi/lock Windows) NON deve essere
    # silenziato come "assente/non-bridge": si propaga, così il chiamante lo segnala.
    p = tmp_path / "segnali.csv"
    csv_writer.write_csv(ROW, str(p))           # file bridge valido
    real_open = builtins.open

    def fake_open(file, *a, **k):
        if str(file) == str(p):
            raise PermissionError("file bloccato (simulato)")
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    with pytest.raises(PermissionError):
        csv_writer.clear_stale_csv(str(p))


def test_clear_stale_csv_non_crea_file_assente(tmp_path):
    # Se il CSV non esiste ancora (primo avvio), NON va creato a sproposito.
    p = tmp_path / "mai_esistito.csv"
    assert csv_writer.clear_stale_csv(str(p)) is False
    assert not p.exists()


def test_clear_stale_csv_path_vuoto(tmp_path):
    # Path vuoto/None: nessuna operazione, nessun errore.
    assert csv_writer.clear_stale_csv("") is False
    assert csv_writer.clear_stale_csv(None) is False


def test_clear_stale_csv_idempotente_su_header(tmp_path):
    # Un CSV già a solo header resta valido (idempotente) e non lascia .tmp.
    p = tmp_path / "segnali.csv"
    csv_writer.init_csv(str(p))
    assert csv_writer.clear_stale_csv(str(p)) is True
    assert _read(str(p)) == [csv_writer.CSV_HEADER]
    assert _no_tmp_left(str(tmp_path))


def test_concorrenza_write_clear_non_corrompe(tmp_path):
    # Stress: write e clear concorrenti. Il file deve restare sempre valido
    # (header presente, 1 o 2 righe), nessun .tmp residuo, nessuna eccezione.
    p = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(p)
    errors = []

    def writer_loop():
        for _ in range(50):
            try:
                csv_writer.write_csv(ROW, p)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    def clear_loop():
        for _ in range(50):
            try:
                csv_writer.init_csv(p)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=writer_loop), threading.Thread(target=clear_loop)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"eccezioni durante la concorrenza: {errors}"
    rows = _read(p)
    assert rows[0] == csv_writer.CSV_HEADER          # header sempre integro
    assert len(rows) in (1, 2)                        # solo header o header+1
    assert _no_tmp_left(str(tmp_path))                # nessun temporaneo residuo


@pytest.mark.slow
def test_stress_write_clear_500_iterazioni_non_corrompe(tmp_path):
    # #109/18: stress più alto (500 iter per thread) di write/clear concorrenti — marcato
    # `slow`, escluso dai profili commit/pr (-m "not slow"). Stesso invariante del test base:
    # il CSV resta SEMPRE valido (header integro, 0/1 righe), nessun .tmp, nessuna eccezione.
    p = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(p)
    errors = []

    def writer_loop():
        for _ in range(500):
            try:
                csv_writer.write_csv(ROW, p)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    def clear_loop():
        for _ in range(500):
            try:
                csv_writer.init_csv(p)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=writer_loop), threading.Thread(target=clear_loop)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"eccezioni durante lo stress: {errors}"
    rows = _read(p)
    assert rows[0] == csv_writer.CSV_HEADER
    assert len(rows) in (1, 2)
    assert _no_tmp_left(str(tmp_path))


def test_errore_permessi_non_lascia_tmp(tmp_path, monkeypatch):
    # Se la rename atomica fallisce, il file finale resta intatto e nessun .tmp resta.
    p = tmp_path / "segnali.csv"
    csv_writer.write_csv(ROW, str(p))                # stato iniziale valido
    contenuto_prima = open(p, "rb").read()

    def boom(src, dst, attempts=3, delay=0.1):
        raise OSError("rename non permessa (simulata)")

    monkeypatch.setattr(csv_writer, "_replace_with_retry", boom)
    try:
        csv_writer.write_csv(ROW, str(p))
    except OSError:
        pass
    assert open(p, "rb").read() == contenuto_prima    # file finale intatto
    assert _no_tmp_left(str(tmp_path))                # tmp rimosso anche su errore


def test_replace_with_retry_riprova_oltre_il_vecchio_budget(monkeypatch):
    # audit C3: il budget di retry deve essere ampio (~1s, non 0.3s) così un lock di XTrader
    # un po' più lungo non fa fallire lo svuotamento/scrittura. Qui os.replace fallisce 5
    # volte (più dei vecchi 3 tentativi) e poi riesce: con il budget nuovo deve convergere.
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 5:
            raise OSError("lock XTrader (simulato)")
        # all'ultimo tentativo simula il successo senza toccare il filesystem reale
        return None

    monkeypatch.setattr(csv_writer.os, "replace", flaky_replace)
    monkeypatch.setattr(csv_writer.time, "sleep", lambda *_: None)   # niente attese vere
    csv_writer._replace_with_retry("src", "dst")                    # non deve sollevare
    assert calls["n"] == 6                                          # 5 fallimenti + 1 successo


def test_replace_with_retry_solleva_dopo_budget_esaurito(monkeypatch):
    # Esaurito il budget, l'errore si propaga (il chiamante lo gestisce/logga, audit C3).
    def always_fail(src, dst):
        raise OSError("lock permanente (simulato)")

    monkeypatch.setattr(csv_writer.os, "replace", always_fail)
    monkeypatch.setattr(csv_writer.time, "sleep", lambda *_: None)
    with pytest.raises(OSError):
        csv_writer._replace_with_retry("src", "dst", attempts=4)


# ── _replace_with_retry: lock Windows di XTrader (audit C3, issue #106) ─────────

def test_replace_with_retry_riprova_e_poi_riesce(monkeypatch):
    """`os.replace` bloccato (lock Windows) per N-1 volte, poi riesce: la funzione
    riprova entro il budget e completa, senza propagare l'errore transitorio."""
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:                 # fallisce 2 volte, poi "riesce"
            raise OSError("file lockato (simulato)")
        return None                        # successo: niente eccezione

    monkeypatch.setattr(csv_writer.os, "replace", flaky)
    csv_writer._replace_with_retry("src.tmp", "dst.csv", attempts=5, delay=0)
    assert calls["n"] == 3                 # 2 fallimenti + 1 successo


def test_replace_with_retry_esaurisce_gli_attempt_e_rilancia(monkeypatch):
    """Se il lock persiste oltre il budget di retry, l'ultimo `os.replace` propaga
    l'`OSError` (così il chiamante sa che la scrittura non è andata a buon fine)."""
    calls = {"n": 0}

    def always_fail(src, dst):
        calls["n"] += 1
        raise OSError("lock perenne (simulato)")

    monkeypatch.setattr(csv_writer.os, "replace", always_fail)
    with pytest.raises(OSError):
        csv_writer._replace_with_retry("src.tmp", "dst.csv", attempts=4, delay=0)
    assert calls["n"] == 4                 # ha provato esattamente `attempts` volte


# ── _replace_with_retry: errori STRUTTURALI escalano subito (M5, issue #184) ───────

def _oserror(errno_=None, winerror=None, msg="boom"):
    """Costruisce un OSError con `errno`/`winerror` espliciti (winerror settato come attributo,
    così il test gira anche su POSIX dove `os.replace` non lo valorizzerebbe)."""
    exc = OSError(errno_ if errno_ is not None else 0, msg)
    if winerror is not None:
        exc.winerror = winerror
    return exc


def test_replace_with_retry_errore_strutturale_escala_subito(monkeypatch):
    """#184 M5: un errore STRUTTURALE/permanente (es. EISDIR: la destinazione è una directory,
    o EACCES: dir read-only) NON deve essere ritentato 10×0.1s (~1s sprecato a ogni segnale
    prima dell'escalation): si propaga al PRIMO tentativo.

    Fail-first: il vecchio codice catturava OGNI OSError e ritentava `attempts` volte."""
    import errno as _errno
    for permanent in (_errno.EISDIR, _errno.EACCES, _errno.ENOENT, _errno.EXDEV):
        calls = {"n": 0}

        def boom(src, dst, _e=permanent):
            calls["n"] += 1
            raise _oserror(errno_=_e)

        monkeypatch.setattr(csv_writer.os, "replace", boom)
        monkeypatch.setattr(csv_writer.time, "sleep", lambda *_: None)
        with pytest.raises(OSError):
            csv_writer._replace_with_retry("src", "dst", attempts=10, delay=0)
        assert calls["n"] == 1, f"errno {permanent}: ritentato invece di escalare subito"


def test_replace_with_retry_windows_sharing_violation_ritenta(monkeypatch):
    """#184 M5: su Windows una ERROR_SHARING_VIOLATION (winerror 32 — XTrader tiene il CSV
    aperto in lettura) è TRANSITORIA → si ritenta entro il budget e poi riesce."""
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _oserror(errno_=13, winerror=32)     # sharing violation (transitoria)
        return None

    monkeypatch.setattr(csv_writer.os, "replace", flaky)
    csv_writer._replace_with_retry("src", "dst", attempts=5, delay=0)
    assert calls["n"] == 3                              # 2 retry + successo


def test_replace_with_retry_windows_access_denied_e_ritentabile(monkeypatch):
    """#184 M5 (Codex #201 P1): su Windows il read-lock di XTrader fa fallire `os.replace` con
    ERROR_ACCESS_DENIED (winerror 5) quando il CSV è aperto in lettura — è il caso PIÙ comune,
    quindi TRANSITORIO e ritentabile (non lo si confonde con un read-only permanente, che è
    raro e accettiamo costi ~1s)."""
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _oserror(errno_=13, winerror=5)      # access denied = lock di lettura (transitorio)
        return None

    monkeypatch.setattr(csv_writer.os, "replace", flaky)
    csv_writer._replace_with_retry("src", "dst", attempts=5, delay=0)
    assert calls["n"] == 3                              # 2 retry + successo (non escala subito)


def test_replace_with_retry_windows_winerror_strutturale_escala_subito(monkeypatch):
    """#184 M5: un `winerror` NON di contesa lock (es. 267 ERROR_DIRECTORY, 123 ERROR_INVALID_NAME)
    è strutturale → escala al primo tentativo."""
    for structural in (267, 123, 3):                   # ERROR_DIRECTORY / INVALID_NAME / PATH_NOT_FOUND
        calls = {"n": 0}

        def boom(src, dst, _w=structural):
            calls["n"] += 1
            raise _oserror(errno_=13, winerror=_w)

        monkeypatch.setattr(csv_writer.os, "replace", boom)
        monkeypatch.setattr(csv_writer.time, "sleep", lambda *_: None)
        with pytest.raises(OSError):
            csv_writer._replace_with_retry("src", "dst", attempts=10, delay=0)
        assert calls["n"] == 1, f"winerror {structural}: ritentato invece di escalare"


def test_is_retryable_replace_error_classifica_transitori_e_permanenti():
    """#184 M5: la classificazione. Windows: lock/sharing (32/33) e access-denied (5, read-lock
    XTrader) ritentabili; altri winerror strutturali. POSIX/generico: errno permanenti no,
    errore senza errno (lock simulato) sì."""
    import errno as _errno
    assert csv_writer._is_retryable_replace_error(_oserror(winerror=32)) is True
    assert csv_writer._is_retryable_replace_error(_oserror(winerror=33)) is True
    assert csv_writer._is_retryable_replace_error(_oserror(winerror=5)) is True    # read-lock XTrader
    assert csv_writer._is_retryable_replace_error(_oserror(winerror=267)) is False  # ERROR_DIRECTORY
    assert csv_writer._is_retryable_replace_error(OSError("lock generico")) is True  # errno None
    for permanent in (_errno.EISDIR, _errno.EACCES, _errno.ENOENT, _errno.ENOTDIR, _errno.EXDEV):
        assert csv_writer._is_retryable_replace_error(_oserror(errno_=permanent)) is False


# ── H3 (#184): check-then-clear di clear_stale_csv ATOMICO sotto _write_lock ──

def test_clear_stale_csv_legge_header_sotto_il_lock(tmp_path, monkeypatch):
    # Il bug H3: la lettura dell'header avveniva FUORI dal _write_lock e il clear lo
    # riprendeva → una write concorrente poteva inserirsi tra check e clear e perdere un
    # segnale. Verifica deterministica: durante la lettura dell'header il _write_lock è GIÀ
    # tenuto (una acquire non-bloccante fallisce), quindi nessuna write può intromettersi.
    p = tmp_path / "segnali.csv"
    csv_writer.write_csv(ROW, str(p))                     # un segnale "stantio" sul disco
    held = {}
    real_reader = csv.reader

    def spy_reader(f, *a, **k):
        got = csv_writer._write_lock.acquire(blocking=False)
        held["locked_during_read"] = not got              # non acquisibile = già tenuto
        if got:
            csv_writer._write_lock.release()
        return real_reader(f, *a, **k)

    monkeypatch.setattr(csv_writer.csv, "reader", spy_reader)
    assert csv_writer.clear_stale_csv(str(p)) is True
    assert held["locked_during_read"] is True             # check sotto lock (assert PRIMA di _read)
    monkeypatch.undo()                                    # ripristina csv.reader per _read
    assert _read(str(p)) == [csv_writer.CSV_HEADER]       # svuotato a solo header


def test_clear_e_write_concorrenti_non_corrompono(tmp_path):
    # Resilienza concorrenza: write_csv e clear_stale_csv in parallelo da più thread non
    # devono mai lasciare un file torn/perso: header sempre integro, 0 o 1 riga dati,
    # nessun temporaneo residuo (scrittura atomica + serializzazione sotto _write_lock).
    p = str(tmp_path / "segnali.csv")
    csv_writer.write_csv(ROW, p)
    errors = []

    def writer_t():
        for _ in range(50):
            try:
                csv_writer.write_csv(ROW, p)
            except Exception as e:                        # noqa: BLE001 — raccolto per l'assert
                errors.append(e)

    def clearer_t():
        for _ in range(50):
            try:
                csv_writer.clear_stale_csv(p)
            except Exception as e:                        # noqa: BLE001
                errors.append(e)

    threads = ([threading.Thread(target=writer_t) for _ in range(2)]
               + [threading.Thread(target=clearer_t) for _ in range(2)])
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    rows = _read(p)
    assert rows[0] == csv_writer.CSV_HEADER                # header sempre presente e integro
    assert len(rows) in (1, 2)                             # solo header, o header + 1 riga
    if len(rows) == 2:
        assert rows[1] == [ROW[c] for c in csv_writer.CSV_HEADER]
    assert _no_tmp_left(str(tmp_path))                     # nessun temporaneo residuo


# ── LOW (#184): sweep degli orfani `.segnali_*.tmp` lasciati da un crash ──────

def test_sweep_orphan_temps_rimuove_il_tmp_lasciato_da_un_crash(tmp_path):
    # Un crash DURO del processo (kill/power-loss) tra mkstemp e replace salta il cleanup
    # di atomic_write e lascia un `.segnali_*.tmp` orfano: il CSV finale è intatto (il
    # rename non è avvenuto). Lo riproduciamo creando a mano l'orfano col vero prefisso/
    # suffisso del CSV; lo sweep allo startup deve rimuoverlo senza toccare il CSV reale.
    p = str(tmp_path / "segnali.csv")
    csv_writer.write_csv(ROW, p)                           # CSV reale valido
    (tmp_path / ".segnali_orfano.tmp").write_text("RESIDUO PARZIALE")
    assert glob.glob(os.path.join(str(tmp_path), ".segnali_*.tmp"))   # orfano presente

    removed = csv_writer.sweep_orphan_temps(p)
    assert removed == 1
    assert _no_tmp_left(str(tmp_path))                     # orfano rimosso
    rows = _read(p)
    assert rows[0] == csv_writer.CSV_HEADER                # CSV reale ancora intatto
    assert rows[1] == [ROW[c] for c in csv_writer.CSV_HEADER]


def test_sweep_orphan_temps_path_vuoto_e_no_op(tmp_path):
    assert csv_writer.sweep_orphan_temps("") == 0
    assert csv_writer.sweep_orphan_temps("   ") == 0
