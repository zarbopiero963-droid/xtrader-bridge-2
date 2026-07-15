"""Test hard veritieri — Issue #76 P2-3/P2-4 (audit 2026-07-15): wiring anti data-loss in `app.py`.

- **P2-4** (`_manual_clear`, comportamentale via harness headless): a bridge FERMO il path
  viene dal campo GUI; se punta a un file esistente NON-bridge, «🗑️ Svuota CSV ora» prima
  lo troncava a solo header con `init_csv` (contenuto utente distrutto con un click). Ora
  rifiuta con messaggio e non tocca nulla. Fail-first: sul codice precedente il test del
  file estraneo falliva (file troncato).
- **P2-3** (`_start`, guardia strutturale): `_start` è GUI/thread-coupled e non
  istanziabile headless (stesso pattern di test_start_bloccato_senza_parser_configurato):
  si pinna il wiring — `is_foreign_csv` deve esistere in `_start`, loggare ❌ con
  istruzione azionabile e fare `return` PRIMA dell'avvio vero (`_bot_thread`).
  La logica pura è coperta da tests/unit/test_foreign_csv_guard_76.py.
"""

import csv
import inspect

from xtrader_bridge import csv_writer, signal_queue


def _row(name):
    return {"EventName": name, "MarketName": "Esito finale",
            "SelectionName": name.split(" v ")[0], "Price": "1,90", "BetType": "PUNTA"}


def _queue_with(row):
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    q.add(row, now=0.0)
    return q


def _events_in_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r["EventName"] for r in csv.DictReader(f)]


# ── P2-4: «Svuota CSV ora» a bridge FERMO ────────────────────────────────────────────────────

def test_manual_clear_fermo_non_tronca_file_estraneo(make_app, app_mod, tmp_path):
    # FAIL-FIRST: prima del fix il contenuto utente veniva sostituito dall'header bridge.
    p = str(tmp_path / "dati_utente.csv")
    contenuto = "colA,colB\nvalore1,valore2\n"
    with open(p, "w", encoding="utf-8") as f:
        f.write(contenuto)
    a = make_app(csv_path=None, running=False, gui_csv=p, queue=None)

    app_mod.App._manual_clear(a)

    with open(p, encoding="utf-8") as f:
        assert f.read() == contenuto                       # file INTATTO, byte per byte
    assert any("Svuotamento rifiutato" in m for m in a.logs)   # rifiuto visibile nel log


def test_manual_clear_fermo_su_csv_bridge_svuota_come_prima(make_app, app_mod, tmp_path):
    # Regressione: a bridge fermo un CSV del bridge con riga stantia resta svuotabile.
    p = str(tmp_path / "segnali.csv")
    row = {c: "" for c in csv_writer.CSV_HEADER}
    row.update({"Provider": "TG", "EventName": "A v B", "BetType": "PUNTA"})
    csv_writer.write_rows([row], p)
    a = make_app(csv_path=None, running=False, gui_csv=p, queue=None)

    app_mod.App._manual_clear(a)

    assert _events_in_csv(p) == []                          # solo header
    assert not any("rifiutato" in m for m in a.logs)


def test_manual_clear_fermo_file_vuoto_resta_inizializzabile(make_app, app_mod, tmp_path):
    # Un file a 0 byte non ha dati da perdere: il clear lo porta a solo header come prima.
    p = str(tmp_path / "vuoto.csv")
    open(p, "w").close()
    a = make_app(csv_path=None, running=False, gui_csv=p, queue=None)

    app_mod.App._manual_clear(a)

    assert _events_in_csv(p) == []                          # header scritto, nessun rifiuto
    assert not any("rifiutato" in m for m in a.logs)


def test_manual_clear_running_usa_active_e_ignora_gui_estraneo(make_app, app_mod, tmp_path):
    # A bridge ATTIVO la guardia non serve né interferisce: si svuota il CSV ATTIVO della
    # sessione anche se il campo GUI punta (per errore) a un file estraneo — che resta intatto.
    active = str(tmp_path / "attivo.csv")
    estraneo = str(tmp_path / "estraneo.csv")
    q = _queue_with(_row("Inter v Milan"))
    csv_writer.write_rows(q.active_rows(), active)
    with open(estraneo, "w", encoding="utf-8") as f:
        f.write("colA\nvalore\n")
    a = make_app(csv_path=active, running=True, gui_csv=estraneo, queue=q)

    app_mod.App._manual_clear(a)

    assert _events_in_csv(active) == []                     # svuotato l'ATTIVO
    with open(estraneo, encoding="utf-8") as f:
        assert f.read() == "colA\nvalore\n"                 # l'estraneo NON è toccato
    assert q.is_empty()


# ── P2-4 (review #79 Fable): I/O fallito in lettura ≠ file estraneo — diagnosi distinta ──────

def test_manual_clear_fermo_io_fallito_rifiuta_con_messaggio_dedicato(
        make_app, app_mod, monkeypatch, tmp_path):
    # Un CSV del bridge LEGITTIMO ma illeggibile (lock esclusivo XTrader / permessi) non va
    # toccato, e il messaggio NON deve dire «non è un CSV del bridge» (sarebbe fuorviante).
    p = str(tmp_path / "segnali.csv")
    csv_writer.init_csv(p)
    monkeypatch.setattr(app_mod, "init_csv_for_session",
                        lambda _p: csv_writer.CSV_INIT_UNREADABLE)
    a = make_app(csv_path=None, running=False, gui_csv=p, queue=None)

    app_mod.App._manual_clear(a)

    assert csv_writer.is_bridge_csv(p)                      # non toccato
    assert any("impossibile leggere" in m for m in a.logs)  # diagnosi I/O dedicata
    assert not any("non è un CSV del bridge" in m for m in a.logs)


def test_manual_clear_rifiutato_riprogramma_il_tick_di_scadenza(make_app, app_mod, tmp_path):
    # Review #79 Fable/Fugu (round 2): il tick di scadenza è cancellato PRIMA del lock (PR-22);
    # su un RIFIUTO va riprogrammato come nel ramo write-error, altrimenti nell'edge
    # `from_gui_path` con sessione attiva (`_active_csv_path` falsy) una riga attiva su disco
    # non scadrebbe mai più (segnale stantio). FAIL-FIRST: sul head precedente expiry_calls
    # restava vuota.
    p = str(tmp_path / "dati_utente.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("colA\nvalore\n")
    q = _queue_with(_row("Inter v Milan"))
    a = make_app(csv_path=None, running=True, gui_csv=p, queue=q)   # attivo ma active_path falsy

    app_mod.App._manual_clear(a)

    with open(p, encoding="utf-8") as f:
        assert f.read() == "colA\nvalore\n"                 # file intatto
    assert len(q.active_rows()) == 1                        # coda NON toccata
    assert a.expiry_calls and a.expiry_calls[-1][0] == p    # tick RIPROGRAMMATO (no riga immortale)
    assert any("Svuotamento rifiutato" in m for m in a.logs)


# ── P2-3: guardia strutturale su _start ──────────────────────────────────────────────────────

def test_start_bloccato_su_csv_estraneo_guardia_strutturale(app_mod):
    # FAIL-FIRST: sul codice precedente il check-and-init atomico non compariva in _start.
    # Review #79 Fable: si usa `init_csv_for_session` (classificazione + scrittura header sotto
    # lo STESSO lock del csv_writer → nessuna finestra TOCTOU tra guardia e troncamento) con
    # esiti bloccanti distinti per file estraneo e I/O fallito in lettura.
    src = inspect.getsource(app_mod.App._start)
    assert "init_status = init_csv_for_session(" in src     # ancora sulla CHIAMATA, non sul commento
    idx = src.index("init_status = init_csv_for_session(")
    blocco = src[idx:idx + 1200]
    assert "CSV_INIT_FOREIGN" in blocco
    assert "non lo sovrascrivo" in blocco                   # istruzione visibile (foreign)
    assert "CSV_INIT_UNREADABLE" in blocco
    assert "Impossibile leggere" in blocco                  # diagnosi I/O dedicata
    assert blocco.count("Avvio annullato") >= 2             # entrambi gli esiti bloccano
    assert "return" in blocco                               # BLOCCANTE, non avviso
    # La guardia atomica sta PRIMA dell'avvio vero, e in _start NON resta alcuna chiamata
    # diretta `init_csv(` non-atomica (sarebbe la reintroduzione della TOCTOU).
    assert "_bot_thread" in src
    assert idx < src.index("_bot_thread")
    assert "init_csv(" not in src.replace("init_csv_for_session(", "")
