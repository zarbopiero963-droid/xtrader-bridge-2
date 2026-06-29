"""Test hard del ledger eventi append-only (`event_journal`, issue #110 voce 20).

Esercita gli invarianti del ledger: append-only ordinato, una riga = un evento con id
univoco + timestamp, tipo fail-closed, redazione dei token, lettura tollerante a una
riga finale troncata (crash a metà append), `now` non finito rifiutato, clear atomico.
Modulo puro: nessuna GUI/Telegram/CSV.
"""

import json

import pytest

from xtrader_bridge import event_journal as ej
from xtrader_bridge import runtime_state


def test_append_e_read_round_trip(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    e1 = ej.append_event(p, "START", {"mode": "DRY_RUN"}, now=1000.0, event_id="a")
    e2 = ej.append_event(p, "CSV_WRITTEN", {"rows": 1}, now=1001.0, event_id="b")
    events = ej.read_events(p)
    assert [e["id"] for e in events] == ["a", "b"]            # ordine d'inserimento
    assert events[0]["type"] == "START" and events[0]["data"] == {"mode": "DRY_RUN"}
    assert events[1] == e2
    assert events[0]["ts"] == 1000.0


def test_tipo_sconosciuto_fail_closed(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    with pytest.raises(ValueError):
        ej.append_event(p, "NON_ESISTE", {}, now=1.0)
    # niente scritto sul ledger
    assert ej.read_events(p) == []


def test_now_non_finito_rifiutato(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    for bad in (float("nan"), float("inf"), True, "x"):
        with pytest.raises(ValueError):
            ej.append_event(p, "START", {}, now=bad)
    assert ej.read_events(p) == []


# Token finto COSTRUITO PER CONCATENAZIONE: il sorgente non contiene una stringa
# token-shaped contigua (così non fa scattare il secret-scan del repo), ma a runtime
# forma un valore che matcha la regex di redazione (`\d{6,}:[A-Za-z0-9_-]{20,}`).
_FAKE_TOKEN = "1234567890" + ":" + ("A" * 35)


def test_token_telegram_redatto(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    token = _FAKE_TOKEN
    ej.append_event(p, "RECONNECT", {"err": f"bot {token} giù", "nested": {"t": token}},
                    now=1.0, event_id="z")
    raw = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert token not in raw                                   # mai token in chiaro
    assert "[REDACTED_TOKEN]" in raw
    ev = ej.read_events(p)[0]
    assert token not in json.dumps(ev)                        # redatto anche nel payload nidificato


def test_token_redatto_anche_nelle_chiavi(tmp_path):
    # review Codex: un token usato come CHIAVE del payload non deve restare in chiaro
    # né nell'evento ritornato né sulla riga persistita.
    p = str(tmp_path / "journal.jsonl")
    ev = ej.append_event(p, "RECONNECT", {_FAKE_TOKEN: "x"}, now=1.0, event_id="k")
    assert _FAKE_TOKEN not in json.dumps(ev)                  # redatto nell'evento ritornato
    raw = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert _FAKE_TOKEN not in raw                             # redatto sulla riga persistita
    assert "[REDACTED_TOKEN]" in next(iter(ej.read_events(p)[0]["data"].keys()))


def test_evento_dopo_coda_troncata_non_va_perso(tmp_path):
    # review Codex P1: una riga finale TRONCATA (crash a metà append, niente \n finale)
    # non deve far perdere il PROSSIMO evento appeso. Il separatore in _append_line isola
    # la riga parziale (saltata) e mette il nuovo evento su una riga pulita.
    p = tmp_path / "journal.jsonl"
    good = json.dumps({"id": "1", "ts": 1.0, "type": "START", "data": {}})
    # riga valida + riga parziale SENZA newline finale (come dopo un crash)
    p.write_text(good + "\n" + '{"id": "2", "ts": 2.0, "type": "CSV_WR', encoding="utf-8")

    ej.append_event(str(p), "CSV_WRITTEN", {"rows": 1}, now=3.0, event_id="3")

    events = ej.read_events(str(p))
    ids = [e["id"] for e in events]
    assert "1" in ids and "3" in ids        # vecchio valido + nuovo evento PRESERVATI
    assert "2" not in ids                    # la riga troncata resta saltata (non corrompe)


def test_append_only_preserva_ordine_e_id_univoci(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    for i in range(5):
        ej.append_event(p, "SIGNAL_RECEIVED", {"n": i}, now=float(i))
    events = ej.read_events(p)
    assert [e["data"]["n"] for e in events] == [0, 1, 2, 3, 4]
    ids = [e["id"] for e in events]
    assert len(set(ids)) == 5                                 # id auto (uuid) univoci


def test_riga_finale_troncata_viene_saltata(tmp_path):
    # Simula un crash a metà append: una riga JSON valida + una riga troncata.
    p = tmp_path / "journal.jsonl"
    good = json.dumps({"id": "1", "ts": 1.0, "type": "START", "data": {}})
    p.write_text(good + "\n" + '{"id": "2", "ts": 2.0, "type": "CSV_WR', encoding="utf-8")
    events = ej.read_events(str(p))
    assert len(events) == 1 and events[0]["id"] == "1"        # la riga troncata è saltata, no crash


def _counting_open(monkeypatch):
    """Wrappa `event_journal.open` per registrare i `write` sul file (per #184 M6)."""
    writes = []
    real_open = open

    class _CountingFile:
        def __init__(self, f):
            self._f = f

        def write(self, s):
            writes.append(s)
            return self._f.write(s)

        def __getattr__(self, name):
            return getattr(self._f, name)

        def __enter__(self):
            self._f.__enter__()
            return self

        def __exit__(self, *a):
            return self._f.__exit__(*a)

    # Si patcha `ej.open` (non `builtins.open`): `_append_line` chiama il nome libero `open`,
    # che Python risolve via LEGB con i GLOBAL del modulo PRIMA dei builtins — quindi un
    # `open` iniettato nel namespace di `event_journal` lo shadowa ed è effettivamente usato
    # (più mirato che patchare l'`open` globale). Le assert su `writes` lo confermano: se la
    # patch non avesse effetto, `writes` resterebbe `[]` e l'uguaglianza fallirebbe.
    monkeypatch.setattr(ej, "open", lambda *a, **k: _CountingFile(real_open(*a, **k)),
                        raising=False)
    return writes


def test_append_dopo_troncamento_una_sola_write(tmp_path, monkeypatch):
    """#184 M6: con separatore necessario (ultima riga troncata) il separatore + la riga +
    `\\n` devono essere scritti in UN SOLO `f.write`, non in due write separati. Due write
    prima del flush/fsync potevano lasciare, su un crash a metà, solo il separatore senza
    l'evento (perdita) e l'"atomicità della singola riga" era sovrastimata.

    Fail-first: il vecchio codice faceva `f.write("\\n")` e poi `f.write(line+"\\n")` → 2 write."""
    p = tmp_path / "journal.jsonl"
    p.write_text('{"id": "1", "ts": 1.0, "type": "CSV_WR', encoding="utf-8")   # troncata, no \n
    writes = _counting_open(monkeypatch)

    ej._append_line(str(p), '{"id":"2"}')

    assert writes == ['\n{"id":"2"}\n']      # separatore+riga+newline in UNA write (non due)
    # e il risultato resta corretto: riga troncata saltata, nuovo evento leggibile
    assert ej.read_events(str(p)) == [{"id": "2"}]


def test_append_senza_troncamento_una_sola_write(tmp_path, monkeypatch):
    """#184 M6 (controprova): senza separatore (file che termina con `\\n` o vuoto) la riga è
    comunque una sola write `line+\\n` — comportamento invariato."""
    p = tmp_path / "journal.jsonl"
    p.write_text('{"id": "1"}\n', encoding="utf-8")        # termina con newline → niente separatore
    writes = _counting_open(monkeypatch)

    ej._append_line(str(p), '{"id":"2"}')

    assert writes == ['{"id":"2"}\n']                       # nessun separatore, una sola write


def test_coda_utf8_troncata_non_rompe_il_replay(tmp_path):
    # review Codex: un crash a metà di un carattere non-ASCII lascia una coda di byte
    # UTF-8 INVALIDA. read_events deve comunque restituire gli eventi validi precedenti
    # (errors="replace") invece di sollevare UnicodeDecodeError su tutto il file.
    p = tmp_path / "journal.jsonl"
    good = json.dumps({"id": "1", "ts": 1.0, "type": "START", "data": {}})
    # riga valida + coda troncata a metà di "è" (\xc3\xa8): solo il primo byte \xc3
    p.write_bytes(good.encode("utf-8") + b"\n" + b'{"id":"2","data":"caff\xc3')
    events = ej.read_events(str(p))                     # non deve sollevare
    assert [e["id"] for e in events] == ["1"]           # l'evento valido è preservato


def test_read_file_assente_ritorna_vuoto(tmp_path):
    assert ej.read_events(str(tmp_path / "manca.jsonl")) == []


def test_data_multilinea_resta_una_sola_riga(tmp_path):
    # Un contenuto con newline non deve spezzare il JSONL (json.dumps escapa \n).
    p = str(tmp_path / "journal.jsonl")
    ej.append_event(p, "SIGNAL_PARSED", {"msg": "riga1\nriga2"}, now=1.0)
    raw = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert raw.count("\n") == 1                               # una sola riga (newline finale)
    assert ej.read_events(p)[0]["data"]["msg"] == "riga1\nriga2"


def test_clear_atomico_svuota(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    ej.append_event(p, "START", {}, now=1.0)
    assert ej.read_events(p)                                  # non vuoto
    assert ej.clear(p) is True
    assert ej.read_events(p) == []                            # svuotato
    # nessun temporaneo residuo
    assert [f for f in __import__("os").listdir(tmp_path) if f.startswith(".journal_")] == []


def test_crea_la_cartella_se_assente(tmp_path):
    p = str(tmp_path / "sub" / "dir" / "journal.jsonl")
    ej.append_event(p, "STOP", {}, now=1.0, event_id="x")
    assert ej.read_events(p)[0]["id"] == "x"


def test_event_journal_path_accanto_al_config(tmp_path):
    path = runtime_state.event_journal_path(str(tmp_path))
    assert path.endswith("event_journal.jsonl")
    assert str(tmp_path) in path


def test_tutti_i_tipi_di_evento_documentati_sono_validi(tmp_path):
    # G2: i tipi del vocabolario sono accettati (nessuno solleva).
    p = str(tmp_path / "journal.jsonl")
    for i, t in enumerate(sorted(ej.EVENT_TYPES)):
        ej.append_event(p, t, {"i": i}, now=float(i))
    assert len(ej.read_events(p)) == len(ej.EVENT_TYPES)
