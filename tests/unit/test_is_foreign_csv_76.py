"""Test hard veritieri — Issue #76 P2-3/P2-4 (audit 2026-07-15): helper `is_foreign_csv`.

Guardia anti data-loss per i percorsi che chiamavano `init_csv` su un path arbitrario
(AVVIA, «🗑️ Svuota CSV ora» a bridge fermo): un file dell'utente con contenuto non-bridge
non deve mai essere troncato a solo header senza conferma. Qui si testa la logica PURA;
il wiring in `app.py` è coperto da tests/integration/test_foreign_csv_guard_76.py.
"""

import os

from xtrader_bridge import csv_writer


def test_file_utente_con_contenuto_e_foreign(tmp_path):
    p = str(tmp_path / "dati_utente.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("colA,colB\n1,2\n")                    # CSV dell'utente, header diverso
    assert csv_writer.is_foreign_csv(p) is True


def test_file_binario_illeggibile_e_foreign_fail_closed(tmp_path):
    p = str(tmp_path / "junk.bin")
    with open(p, "wb") as f:
        f.write(b"\xff\xfe\x00\x01PK\x03\x04")          # binario: non decodificabile
    assert csv_writer.is_foreign_csv(p) is True         # non provabile bridge → non toccare


def test_csv_del_bridge_non_e_foreign(tmp_path):
    p = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(p)                               # header canonico del bridge
    assert csv_writer.is_foreign_csv(p) is False
    # anche con una riga attiva resta un CSV del bridge (svuotabile)
    row = {c: "" for c in csv_writer.CSV_HEADER}
    row.update({"Provider": "TG", "EventName": "A v B", "BetType": "PUNTA"})
    csv_writer.write_rows([row], p)
    assert csv_writer.is_foreign_csv(p) is False


def test_file_vuoto_non_e_foreign(tmp_path):
    # Un file a 0 byte (appena creato dal dialogo Sfoglia) non ha dati da perdere:
    # deve restare inizializzabile senza attrito.
    p = str(tmp_path / "vuoto.csv")
    open(p, "w").close()
    assert os.path.getsize(p) == 0
    assert csv_writer.is_foreign_csv(p) is False


def test_file_assente_e_path_vuoto_non_sono_foreign(tmp_path):
    assert csv_writer.is_foreign_csv(str(tmp_path / "inesistente.csv")) is False
    assert csv_writer.is_foreign_csv("") is False


# ── init_csv_for_session: check-and-init ATOMICO (review #79 Fable, TOCTOU) ──────────────────

def test_init_for_session_crea_su_assente_e_vuoto(tmp_path):
    assente = str(tmp_path / "nuovo.csv")
    assert csv_writer.init_csv_for_session(assente) == csv_writer.CSV_INIT_DONE
    assert csv_writer.is_bridge_csv(assente)
    vuoto = str(tmp_path / "vuoto.csv")
    open(vuoto, "w").close()
    assert csv_writer.init_csv_for_session(vuoto) == csv_writer.CSV_INIT_DONE
    assert csv_writer.is_bridge_csv(vuoto)


def test_init_for_session_azzera_bridge_anche_con_riga_attiva(tmp_path):
    # A differenza di create_header_only_csv (REFUSED_ACTIVE), a START/clear la riga
    # stantia DEVE essere rimossa: è la difesa anti-segnale-stantio.
    p = str(tmp_path / "segnali.csv")
    row = {c: "" for c in csv_writer.CSV_HEADER}
    row.update({"Provider": "TG", "EventName": "A v B", "BetType": "PUNTA"})
    csv_writer.write_rows([row], p)
    assert csv_writer.init_csv_for_session(p) == csv_writer.CSV_INIT_DONE
    assert not csv_writer.has_active_row(p)              # solo header


def test_init_for_session_rifiuta_file_estraneo_senza_toccarlo(tmp_path):
    p = str(tmp_path / "dati_utente.csv")
    contenuto = "colA,colB\n1,2\n"
    with open(p, "w", encoding="utf-8") as f:
        f.write(contenuto)
    assert csv_writer.init_csv_for_session(p) == csv_writer.CSV_INIT_FOREIGN
    with open(p, encoding="utf-8") as f:
        assert f.read() == contenuto                      # intatto byte per byte


def test_init_for_session_distingue_io_fallito_da_estraneo(tmp_path, monkeypatch):
    # Review #79 Fable: un OSError di LETTURA (file lockato da XTrader con share esclusivo,
    # permessi) NON deve essere classificato «foreign» (potrebbe essere un CSV del bridge
    # legittimo): esito dedicato UNREADABLE, file non toccato.
    p = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(p)
    orig_open = open

    def _locked_open(file, *a, **k):
        if str(file) == p and "r" in str(k.get("mode", a[0] if a else "r")):
            raise PermissionError(13, "sharing violation")
        return orig_open(file, *a, **k)

    monkeypatch.setattr("builtins.open", _locked_open)
    assert csv_writer.init_csv_for_session(p) == csv_writer.CSV_INIT_UNREADABLE
    monkeypatch.undo()
    assert csv_writer.is_bridge_csv(p)                    # non toccato
    # is_foreign_csv resta fail-closed (True) anche sul caso I/O: il CHIAMANTE che deve
    # distinguere la diagnosi usa gli esiti di init_csv_for_session.
    monkeypatch.setattr("builtins.open", _locked_open)
    assert csv_writer.is_foreign_csv(p) is True
