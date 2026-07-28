"""Guard della famiglia «lascia solo l'header» — ambiguità A4 della #69.

Cinque funzioni di `csv_writer` producono lo stesso RISULTATO (un CSV col solo header) ma con
precondizioni di sicurezza **opposte**. Il report della #69 la indicava come l'ambiguità più
rischiosa del repository, e il motivo è concreto: scegliere la funzione per il nome invece che
per il contratto può **cancellare un segnale che XTrader non ha ancora letto**.

Questi test non verificano che le funzioni «funzionino» — quello è già coperto altrove. Verificano
che le **differenze fra loro restino**, eseguendole tutte sullo stesso file di partenza:

- un CSV del bridge **con una riga attiva** → `init_csv` e `write_rows([])` la cancellano,
  `create_header_only_csv` **rifiuta**, `init_csv_for_session` e `clear_stale_csv` azzerano
  (voluto: a START/STOP la riga stantia deve sparire);
- un **file estraneo** → `create_header_only_csv`, `init_csv_for_session` e `clear_stale_csv`
  lo lasciano intatto, `init_csv` e `write_rows([])` lo sovrascrivono;
- un path **inesistente** → solo `clear_stale_csv` non crea niente.

Se un domani qualcuno uniformasse i contratti «per pulizia», questi test diventano rossi e la
decisione torna umana invece di passare inosservata. È esattamente lo scenario contro cui la
matrice in `csv_writer.py` e questo file esistono.
"""

import csv

from xtrader_bridge import csv_writer as cw

_RIGA_ATTIVA = {
    "Provider": "PBet", "EventName": "Inter v Milan", "MarketType": "OVER_UNDER_25",
    "MarketName": "Over/Under 2,5 gol", "SelectionName": "Over 2,5 goal",
    "Price": "1.85", "BetType": "PUNTA",
}


def _csv_con_riga_attiva(tmp_path):
    """Un CSV del bridge con **una riga attiva**: lo stato in cui una cancellazione sbagliata
    fa sparire un segnale che XTrader potrebbe non aver ancora letto."""
    path = str(tmp_path / "segnali.csv")
    cw.write_csv({k: _RIGA_ATTIVA.get(k, "") for k in cw.CSV_HEADER}, path)
    assert _righe_dati(path) == 1, "il fixture deve partire da una riga attiva"
    return path


def _righe_dati(path) -> int:
    """Numero di righe NON vuote dopo l'header."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)                                   # header
        return sum(1 for row in reader if any((c or "").strip() for c in row))


def _file_estraneo(tmp_path):
    """Un file dell'utente scelto per errore: non è un CSV del bridge."""
    path = tmp_path / "documento_importante.csv"
    path.write_text("colonna_mia;altra\nvalore;42\n", encoding="utf-8")
    return str(path)


# ── CSV del bridge CON RIGA ATTIVA: chi la cancella e chi si rifiuta ─────────────────────────────
def test_init_csv_cancella_la_riga_attiva_senza_chiedere(tmp_path):
    """`init_csv` non controlla niente: è il comportamento reale, ed è il motivo per cui la
    matrice esiste. Documentarlo con un test evita che qualcuno la usi credendola sicura."""
    path = _csv_con_riga_attiva(tmp_path)
    cw.init_csv(path)
    assert _righe_dati(path) == 0


def test_write_rows_vuota_e_il_gemello_di_init_csv(tmp_path):
    """`write_rows([], path)` è la stessa cosa: nessun controllo, riga attiva cancellata."""
    path = _csv_con_riga_attiva(tmp_path)
    cw.write_rows([], path)
    assert _righe_dati(path) == 0


def test_create_header_only_csv_RIFIUTA_se_c_e_una_riga_attiva(tmp_path):
    """La differenza che conta: l'azione utente «📄 Crea CSV» **non** cancella un segnale in
    volo, lo segnala. Senza questa asimmetria, un click distratto perde una scommessa."""
    path = _csv_con_riga_attiva(tmp_path)
    esito = cw.create_header_only_csv(path)
    assert esito == cw.CSV_CREATE_REFUSED_ACTIVE
    assert _righe_dati(path) == 1, "il file NON deve essere toccato"


def test_create_header_only_csv_con_force_sovrascrive(tmp_path):
    """`force=True` = l'utente ha confermato **dopo** essere stato avvisato: allora sì."""
    path = _csv_con_riga_attiva(tmp_path)
    assert cw.create_header_only_csv(path, force=True) == cw.CSV_CREATE_DONE
    assert _righe_dati(path) == 0


def test_init_csv_for_session_azzera_la_riga_stantia(tmp_path):
    """A START la riga di una sessione precedente **deve** sparire: qui azzerare è la cosa
    giusta, ed è la differenza voluta rispetto a `create_header_only_csv`."""
    path = _csv_con_riga_attiva(tmp_path)
    assert cw.init_csv_for_session(path) == cw.CSV_INIT_DONE
    assert _righe_dati(path) == 0


def test_clear_stale_csv_azzera_e_dice_di_averlo_fatto(tmp_path):
    path = _csv_con_riga_attiva(tmp_path)
    assert cw.clear_stale_csv(path) is True
    assert _righe_dati(path) == 0


# ── FILE ESTRANEO: chi lo protegge e chi lo sovrascrive ─────────────────────────────────────────
def test_le_tre_funzioni_prudenti_non_toccano_un_file_estraneo(tmp_path):
    """Un file dell'utente scelto per errore nel campo «CSV Path» non va distrutto."""
    path = _file_estraneo(tmp_path)
    # `with` e non `open(...).read()` (rilievo Fable #161): su Windows — il target del bridge —
    # un handle non chiuso può tenere il file bloccato e far fallire le operazioni successive.
    with open(path, encoding="utf-8") as f:
        originale = f.read()

    assert cw.create_header_only_csv(path) == cw.CSV_CREATE_REFUSED_FOREIGN
    assert cw.init_csv_for_session(path) == cw.CSV_INIT_FOREIGN
    avvisi = []
    assert cw.clear_stale_csv(path, on_mismatch=avvisi.append) is False
    assert avvisi, "clear_stale_csv deve AVVISARE che il file non è del bridge"

    with open(path, encoding="utf-8") as f:
        assert f.read() == originale, "file estraneo modificato!"


def test_init_csv_invece_sovrascrive_un_file_estraneo(tmp_path):
    """Il rovescio della medaglia, dichiarato: `init_csv` non guarda cosa c'era."""
    path = _file_estraneo(tmp_path)
    cw.init_csv(path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        assert next(csv.reader(f), None) == cw.CSV_HEADER


# ── PATH INESISTENTE: chi crea e chi no ─────────────────────────────────────────────────────────
def test_solo_clear_stale_csv_non_crea_il_file(tmp_path):
    """All'avvio non si tocca un path mai usato: `clear_stale_csv` non lo crea. Le altre sì —
    è la differenza che rende sbagliato usarla come «inizializza»."""
    import os
    mancante = str(tmp_path / "mai_usato.csv")
    assert cw.clear_stale_csv(mancante) is False
    assert not os.path.exists(mancante)

    cw.init_csv(mancante)
    assert os.path.exists(mancante)

    altro = str(tmp_path / "altro.csv")
    assert cw.create_header_only_csv(altro) == cw.CSV_CREATE_DONE
    assert os.path.exists(altro)


# ── la matrice nel sorgente non deve sparire ────────────────────────────────────────────────────
def test_la_matrice_e_documentata_nel_sorgente():
    """La differenza fra le cinque funzioni vive in un commento-matrice sopra `init_csv`: se
    sparisce in un riordino, si torna al punto di partenza della #69 (cinque nomi simili e
    nessun posto dove leggere quale sia sicura). Il test lo àncora al sorgente."""
    import pathlib
    src = (pathlib.Path(cw.__file__)).read_text(encoding="utf-8")
    assert "matrice delle precondizioni" in src, "la matrice della famiglia A4 è sparita"
    for nome in ("init_csv_for_session", "create_header_only_csv", "clear_stale_csv"):
        assert f"`{nome}`" in src, f"la matrice non cita più {nome}"
