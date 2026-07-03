"""Test hard della CLI read-only di ispezione del diario eventi (#236, PR 8).

Esercita la logica pura di `journal_view` (filtro/ordinamento/rendering) su un
ledger reale scritto con `event_journal.append_event`, più i casi fail-safe (file
assente, riga troncata/malformata saltata) e l'invariante «read-only, mai
de-redazione». Modulo puro: nessuna GUI/Telegram/CSV.
"""

import json

from xtrader_bridge import event_journal as ej
from xtrader_bridge import journal_view as jv


def _ledger(tmp_path):
    """Ledger di esempio con eventi a ts noti (fuori ordine sul file, per verificare
    il riordino per ts della vista)."""
    p = str(tmp_path / "event_journal.jsonl")
    ej.append_event(p, "CSV_WRITTEN", {"rows": 1}, now=1002.0, event_id="b")
    ej.append_event(p, "START", {"mode": "DRY_RUN"}, now=1000.0, event_id="a")
    ej.append_event(p, "CSV_CLEARED", {"reason": "timeout"}, now=1003.0, event_id="c")
    ej.append_event(p, "STOP", {}, now=1001.0, event_id="d")
    return p


# ── ordinamento e round-trip ──────────────────────────────────────────────────

def test_filter_ordina_per_ts(tmp_path):
    events = ej.read_events(_ledger(tmp_path))
    ordered = jv.filter_events(events)
    assert [e["type"] for e in ordered] == ["START", "STOP", "CSV_WRITTEN", "CSV_CLEARED"]
    assert [e["ts"] for e in ordered] == [1000.0, 1001.0, 1002.0, 1003.0]


def test_filter_non_muta_input(tmp_path):
    events = ej.read_events(_ledger(tmp_path))
    prima = list(events)
    jv.filter_events(events, types=["START"], last=1)
    assert events == prima                       # la lista originale resta intatta


# ── filtri ────────────────────────────────────────────────────────────────────

def test_filter_per_tipo(tmp_path):
    events = ej.read_events(_ledger(tmp_path))
    only = jv.filter_events(events, types=["CSV_WRITTEN", "CSV_CLEARED"])
    assert [e["type"] for e in only] == ["CSV_WRITTEN", "CSV_CLEARED"]


def test_filter_ultimi_n(tmp_path):
    events = ej.read_events(_ledger(tmp_path))
    assert [e["type"] for e in jv.filter_events(events, last=2)] == ["CSV_WRITTEN", "CSV_CLEARED"]
    assert jv.filter_events(events, last=0) == []          # ultimi 0 = nessuno
    assert len(jv.filter_events(events, last=-1)) == 4     # negativo = nessun taglio


def test_filter_intervallo_ts(tmp_path):
    events = ej.read_events(_ledger(tmp_path))
    fin = jv.filter_events(events, since=1001.0, until=1002.0)
    assert [e["type"] for e in fin] == ["STOP", "CSV_WRITTEN"]


def test_filter_combinato_tipo_e_ultimi(tmp_path):
    events = ej.read_events(_ledger(tmp_path))
    fin = jv.filter_events(events, types=["START", "STOP", "CSV_WRITTEN"], last=2)
    assert [e["type"] for e in fin] == ["STOP", "CSV_WRITTEN"]


# ── fail-safe: file assente / riga malformata ─────────────────────────────────

def test_render_file_assente_e_vuoto(tmp_path):
    assert jv.render(str(tmp_path / "non_esiste.jsonl")) == ""
    assert jv.render(str(tmp_path / "non_esiste.jsonl"), as_json=True) == "[]"


def test_render_riga_malformata_saltata(tmp_path):
    # Ledger valido + una riga di spazzatura appesa a mano: la vista salta la riga
    # rotta (come read_events) e mostra solo gli eventi validi, senza crashare.
    p = _ledger(tmp_path)
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"ts": 9999, "type": "START", "data":\n')   # JSON troncato
    out = jv.render(p)
    assert out.count("\n") == 3                  # 4 eventi validi → 4 righe (3 newline)
    assert "START" in out and "CSV_CLEARED" in out


# ── rendering ─────────────────────────────────────────────────────────────────

def test_format_table_ts_leggibile_e_dati(tmp_path):
    events = jv.filter_events(ej.read_events(_ledger(tmp_path)), types=["START"])
    riga = jv.format_table(events)
    assert "START" in riga
    assert '{"mode": "DRY_RUN"}' in riga         # data JSON compatto, chiavi ordinate
    # ts 1000.0 reso come data/ora locale leggibile (non l'epoch grezzo).
    assert "1000.0" not in riga and ":" in riga


def test_ts_label_robusto_su_ts_rotto():
    assert jv._ts_label(None) == "None"          # ts assente → mostrato grezzo, no crash
    assert jv._ts_label("boh") == "boh"
    assert jv._ts_label(1000.0).count(":") == 2  # epoch valido → HH:MM:SS


def test_format_json_e_lista_valida(tmp_path):
    events = jv.filter_events(ej.read_events(_ledger(tmp_path)), last=2)
    parsed = json.loads(jv.format_json(events))
    assert [e["type"] for e in parsed] == ["CSV_WRITTEN", "CSV_CLEARED"]


# ── read-only + niente de-redazione ───────────────────────────────────────────

def test_vista_non_de_redige_ne_riscrive(tmp_path):
    # Un token finito per errore nel payload è già redatto sul ledger da append_event;
    # la vista deve mostrarlo REDATTO (non de-redarlo) e NON deve modificare il file.
    p = str(tmp_path / "event_journal.jsonl")
    token = "123456789:LiveBotTokenSecretValue_xyz"
    ej.append_event(p, "SIGNAL_RECEIVED", {"raw": f"msg {token}"}, now=5.0, event_id="x")
    import os
    mtime_prima = os.path.getmtime(p)
    out = jv.render(p)
    out_json = jv.render(p, as_json=True)
    assert token not in out and token not in out_json    # mai il token in chiaro
    assert "[REDACTED_TOKEN]" in out                     # mostrato redatto, com'è sul file
    assert os.path.getmtime(p) == mtime_prima            # read-only: file non toccato


# ── entrypoint main ───────────────────────────────────────────────────────────

def test_main_stampa_e_ritorna_zero(tmp_path, capsys):
    p = _ledger(tmp_path)
    rc = jv.main(["--path", p, "--type", "START", "--json"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert len(parsed) == 1 and parsed[0]["type"] == "START"


def test_main_last_e_tabella(tmp_path, capsys):
    p = _ledger(tmp_path)
    assert jv.main(["--path", p, "--last", "1"]) == 0
    out = capsys.readouterr().out
    assert "CSV_CLEARED" in out and "START" not in out
