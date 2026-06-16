"""Test della scrittura CSV atomica (PR-05).

Verifica che `write_csv`/`init_csv` producano sempre un file valido (header +
eventuale riga), senza lasciare file temporanei, e che concorrenza write/clear
non corrompa il file (lock condiviso). Chiude #2 (race) e #6 (scrittura atomica).
"""

import csv
import glob
import os
import threading

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
