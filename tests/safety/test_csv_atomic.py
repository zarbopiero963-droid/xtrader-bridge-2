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
