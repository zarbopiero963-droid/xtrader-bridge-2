"""Test di `csv_writer.create_header_only_csv` — creazione ATOMICA anti data-loss (#286).

La funzione fa il check dell'header esistente E la scrittura sotto lo STESSO `_write_lock`
(niente TOCTOU, Fable+Fugu #330). Esercita la funzione REALE su file veri in `tmp_path` e
verifica i tre esiti (DONE / REFUSED_FOREIGN / REFUSED_ACTIVE) + il bypass con `force`.
"""

import csv

from xtrader_bridge import csv_writer
from xtrader_bridge.csv_writer import (
    CSV_CREATE_DONE,
    CSV_CREATE_REFUSED_ACTIVE,
    CSV_CREATE_REFUSED_FOREIGN,
    CSV_HEADER,
    create_header_only_csv,
    init_csv,
)


def _rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def test_create_su_path_assente_crea_header_only(tmp_path):
    p = tmp_path / "nuovo.csv"
    assert create_header_only_csv(str(p)) == CSV_CREATE_DONE
    assert _rows(str(p)) == [CSV_HEADER]


def test_create_rigenera_bridge_header_only(tmp_path):
    p = tmp_path / "segnale.csv"
    init_csv(str(p))                                   # bridge già a solo header
    assert create_header_only_csv(str(p)) == CSV_CREATE_DONE
    assert _rows(str(p)) == [CSV_HEADER]


def test_create_bridge_con_riga_attiva_rifiuta_senza_force(tmp_path):
    p = tmp_path / "segnale.csv"
    csv_writer.write_csv({c: ("X" if c == "EventName" else "") for c in CSV_HEADER}, str(p))
    assert create_header_only_csv(str(p)) == CSV_CREATE_REFUSED_ACTIVE
    assert csv_writer.has_active_row(str(p)) is True   # riga NON toccata


def test_create_bridge_con_riga_attiva_con_force_rigenera(tmp_path):
    p = tmp_path / "segnale.csv"
    csv_writer.write_csv({c: ("X" if c == "EventName" else "") for c in CSV_HEADER}, str(p))
    assert create_header_only_csv(str(p), force=True) == CSV_CREATE_DONE
    assert _rows(str(p)) == [CSV_HEADER]               # riga rimossa


def test_create_file_estraneo_rifiuta_senza_force(tmp_path):
    p = tmp_path / "documento.csv"
    original = "Nome,Cognome\nMario,Rossi\n"
    p.write_text(original, encoding="utf-8")
    assert create_header_only_csv(str(p)) == CSV_CREATE_REFUSED_FOREIGN
    assert p.read_text(encoding="utf-8") == original   # file estraneo INTATTO


def test_create_file_estraneo_con_force_sovrascrive(tmp_path):
    p = tmp_path / "documento.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    assert create_header_only_csv(str(p), force=True) == CSV_CREATE_DONE
    assert _rows(str(p)) == [CSV_HEADER]


def test_create_file_binario_rifiuta_come_estraneo(tmp_path):
    p = tmp_path / "immagine.bin"
    p.write_bytes(b"\x00\x01\xff\xfe garbage")
    assert create_header_only_csv(str(p)) == CSV_CREATE_REFUSED_FOREIGN
    assert p.read_bytes() == b"\x00\x01\xff\xfe garbage"  # non toccato


def test_create_path_vuoto_rifiuta():
    assert create_header_only_csv("") == CSV_CREATE_REFUSED_FOREIGN
    assert create_header_only_csv(None) == CSV_CREATE_REFUSED_FOREIGN


def test_create_cartella_inesistente_creata(tmp_path):
    # Scrittura atomica: la cartella genitore mancante viene creata (comportamento di
    # `atomic_io.atomic_write`), quindi la creazione riesce.
    p = tmp_path / "manca" / "segnale.csv"
    assert create_header_only_csv(str(p)) == CSV_CREATE_DONE
    assert _rows(str(p)) == [CSV_HEADER]
    assert (tmp_path / "manca").is_dir()
