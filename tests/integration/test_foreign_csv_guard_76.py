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


# ── P2-3: guardia strutturale su _start ──────────────────────────────────────────────────────

def test_start_bloccato_su_csv_estraneo_guardia_strutturale(app_mod):
    # FAIL-FIRST: sul codice precedente `is_foreign_csv` non compariva in _start.
    src = inspect.getsource(app_mod.App._start)
    assert "is_foreign_csv" in src
    idx = src.index("is_foreign_csv")
    blocco = src[idx:idx + 600]
    assert "non lo sovrascrivo" in blocco                   # istruzione visibile all'utente
    assert "Avvio annullato" in blocco
    assert "return" in blocco                               # BLOCCANTE, non avviso
    # La guardia sta PRIMA dell'avvio vero (`_bot_thread` esiste e viene dopo) e PRIMA di
    # `init_csv` (l'unico punto che sovrascriverebbe il file).
    assert "_bot_thread" in src
    assert idx < src.index("_bot_thread")
    assert idx < src.index("init_csv(")
