"""P3-6 audit #76 — riga stantia irrecuperabile su path CSV abbandonato.

Bug: STOP con clear CSV fallito (XTrader tiene il lock) armava solo un retry Tk
IN-PROCESS. Se l'app chiude (o crasha) prima che il retry riesca e l'utente cambia
`csv_path`, la recovery d'avvio pulisce solo il path in config: il path ABBANDONATO
resta con una riga ATTIVA per sempre — scommessa fantasma visibile a XTrader.

Fix testato: registro persistente `dirty_csv_store` (sidecar `dirty_csv.json`
atomico accanto al config) — marcato PRIMA di armare il retry (crash-safe), rimosso
solo a pulizia riuscita (retry, START-init o recovery d'avvio, che ripassa tutti i
path marcati).

Il registro è PURO e testato per davvero su file temporanei; il wiring in app.py
(non importabile headless) è verificato sul sorgente pinnato, pattern #311."""

import json
import re
from pathlib import Path

from xtrader_bridge import dirty_csv_store

_APP = Path(__file__).resolve().parents[2] / "xtrader_bridge" / "app.py"


# ── store puro: comportamento REALE su disco ─────────────────────────────────────────

def test_mark_e_read_roundtrip(tmp_path):
    sp = str(tmp_path / "dirty_csv.json")
    dirty_csv_store.mark_dirty(r"C:\vecchio\segnali.csv", store_path=sp)
    dirty_csv_store.mark_dirty("/altro/out.csv", store_path=sp)
    assert dirty_csv_store.dirty_paths(store_path=sp) == [r"C:\vecchio\segnali.csv",
                                                          "/altro/out.csv"]
    data = json.loads(Path(sp).read_text(encoding="utf-8"))   # file JSON valido su disco
    assert data == {"paths": [r"C:\vecchio\segnali.csv", "/altro/out.csv"]}


def test_marker_sopravvive_al_crash(tmp_path):
    """Semantica crash/power-loss: il marker scritto da un «processo» è letto da uno
    nuovo (round-trip su disco reale, nessuno stato in memoria richiesto)."""
    sp = str(tmp_path / "dirty_csv.json")
    dirty_csv_store.mark_dirty("/sessione/morta.csv", store_path=sp)
    # «riavvio»: nessun riuso di oggetti — si rilegge dal file
    assert dirty_csv_store.dirty_paths(store_path=sp) == ["/sessione/morta.csv"]


def test_dedup_normalizzato(tmp_path):
    """Stesso file con case/forma diversi (Windows) non produce doppioni."""
    sp = str(tmp_path / "dirty_csv.json")
    dirty_csv_store.mark_dirty(str(tmp_path / "out.csv"), store_path=sp)
    dirty_csv_store.mark_dirty(str(tmp_path / "sub" / ".." / "out.csv"), store_path=sp)
    assert len(dirty_csv_store.dirty_paths(store_path=sp)) == 1


def test_clear_dirty_confronto_normalizzato(tmp_path):
    sp = str(tmp_path / "dirty_csv.json")
    dirty_csv_store.mark_dirty(str(tmp_path / "out.csv"), store_path=sp)
    dirty_csv_store.clear_dirty(str(tmp_path / "sub" / ".." / "out.csv"), store_path=sp)
    assert dirty_csv_store.dirty_paths(store_path=sp) == []


def test_fail_safe_su_assente_corrotto_e_vuoto(tmp_path):
    sp = str(tmp_path / "dirty_csv.json")
    assert dirty_csv_store.dirty_paths(store_path=sp) == []          # assente
    Path(sp).write_text("{corrotto", encoding="utf-8")
    assert dirty_csv_store.dirty_paths(store_path=sp) == []          # corrotto
    Path(sp).write_text('{"paths": "non-lista"}', encoding="utf-8")
    assert dirty_csv_store.dirty_paths(store_path=sp) == []          # schema inatteso
    dirty_csv_store.mark_dirty("", store_path=sp)                    # vuoto: no-op
    dirty_csv_store.mark_dirty(None, store_path=sp)
    dirty_csv_store.clear_dirty(None, store_path=sp)                 # mai raise


def test_scrittura_mai_raise_su_store_path_invalido(tmp_path):
    """Un I/O rotto non deve bloccare STOP/chiusura: best-effort silenzioso."""
    invalido = str(tmp_path / ("non-esiste/" * 5) / "x\0invalido" / "dirty.json")
    dirty_csv_store.mark_dirty("/qualcosa.csv", store_path=invalido)   # no raise
    dirty_csv_store.clear_dirty("/qualcosa.csv", store_path=invalido)  # no raise


# ── wiring in app.py (sorgente pinnato, pattern #311) ────────────────────────────────

def _src():
    return _APP.read_text(encoding="utf-8")


def test_stop_marca_il_path_prima_del_retry():
    """Crash-safe: la marcatura su disco deve avvenire PRIMA di armare il retry
    in-process — un crash subito dopo lo STOP lascia comunque il marker."""
    src = _src()
    blocco = src[src.index("if not stop_cleared:"):]
    mark = blocco.index("dirty_csv_store.mark_dirty(stop_path)")
    retry = blocco.index("self._schedule_stop_clear_retry(stop_path)")
    assert mark < retry, "app.py/_stop: mark_dirty deve precedere il retry (P3-6 #76)"


def test_retry_riuscito_rimuove_il_marker():
    src = _src()
    blocco = src[src.index("def _retry_stop_clear"):src.index("def _journal(")]
    ok_branch = blocco[blocco.index("if cleared:"):]
    assert "dirty_csv_store.clear_dirty(path)" in ok_branch.split("def ")[0]


def test_start_rimuove_il_marker_dopo_init_riuscito():
    src = _src()
    i = src.index("self._csv_dirty = False   # nuova sessione")
    assert 'dirty_csv_store.clear_dirty(cfg["csv_path"])' in src[i:i + 400], (
        "app.py/_start: init riuscito = path pulito sotto la nuova sessione → marker via")


def test_avvio_ripassa_i_path_abbandonati_dopo_il_clear():
    src = _src()
    avvio = src.index('self._clear_stale_csv("all\'avvio")')
    recovery = src.find("self._recover_dirty_csv_paths()", avvio)
    assert recovery != -1, "app.py: manca la recovery dei path abbandonati all'avvio"
    corpo = src[src.index("def _recover_dirty_csv_paths"):src.index("def _schedule_stop_clear_retry")]
    assert "dirty_csv_store.dirty_paths()" in corpo
    assert re.search(r"if self\._clear_stale_csv\(.+path=path\):\s*\n\s*"
                     r"dirty_csv_store\.clear_dirty\(path\)", corpo), (
        "il marker deve cadere SOLO a pulizia riuscita (lock ancora attivo → resta)")
