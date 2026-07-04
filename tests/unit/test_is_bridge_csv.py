"""Test del predicato `csv_writer.is_bridge_csv` (#286).

`is_bridge_csv` è l'anti data-loss della feature «📄 Crea CSV»: distingue un CSV del bridge
(prima riga == `CSV_HEADER`, sovrascrivibile a solo header) da un file estraneo dell'utente
(da NON distruggere). Esercita la funzione REALE su file veri creati in `tmp_path`.
"""

import csv

from xtrader_bridge import csv_writer
from xtrader_bridge.csv_writer import CSV_HEADER, init_csv, is_bridge_csv


def test_is_bridge_csv_su_csv_del_bridge(tmp_path):
    p = tmp_path / "segnale.csv"
    init_csv(str(p))                       # header-only nel formato del bridge
    assert is_bridge_csv(str(p)) is True


def test_is_bridge_csv_con_riga_dati_resta_true(tmp_path):
    # Anche con una riga dati la prima riga è comunque CSV_HEADER → è un CSV del bridge.
    p = tmp_path / "segnale.csv"
    csv_writer.write_csv({c: "" for c in CSV_HEADER}, str(p))
    assert is_bridge_csv(str(p)) is True


def test_is_bridge_csv_file_estraneo_false(tmp_path):
    # File CSV con header DIVERSO (documento dell'utente) → NON è del bridge.
    p = tmp_path / "documento.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(["Nome", "Cognome", "Email"])
    assert is_bridge_csv(str(p)) is False


def test_is_bridge_csv_file_assente_false(tmp_path):
    assert is_bridge_csv(str(tmp_path / "non_esiste.csv")) is False


def test_is_bridge_csv_path_vuoto_false():
    assert is_bridge_csv("") is False
    assert is_bridge_csv(None) is False


def test_is_bridge_csv_file_binario_illeggibile_false(tmp_path):
    # Binario scelto per errore: non decodificabile utf-8-sig → False, nessun crash.
    p = tmp_path / "immagine.bin"
    p.write_bytes(b"\x00\x01\x02\xff\xfe garbage")
    assert is_bridge_csv(str(p)) is False


def test_is_bridge_csv_header_generato_byte_esatti(tmp_path):
    # Contratto XTrader: BOM utf-8-sig + QUOTE_ALL + CRLF, solo header (nessuna riga dati).
    p = tmp_path / "segnale.csv"
    init_csv(str(p))
    expected = "\ufeff" + ",".join('"%s"' % c for c in CSV_HEADER) + "\r\n"
    assert p.read_bytes().decode("utf-8") == expected
