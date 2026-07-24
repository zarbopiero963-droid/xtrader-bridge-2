"""Test hard del **registro licenze** del License Manager (issue #140, opzione A).

Esercitano la logica reale di `license_manager.registry`: serial deterministico dal token,
costruzione del record dal payload firmato, append/lettura append-only robusti (torn-line +
file assente), stato ATTIVA/SCADUTA, giorni rimasti, filtro di ricerca e assenza del token nelle
righe della vista. Nessun segreto reale: seed generato al volo, hardware id di TEST."""

import json
import os

from license_manager import core, registry

_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_700_000_000            # istante fisso deterministico (unix)
_DAY = 86_400


def _issue(days=15, name="Mario Rossi", hw=_HW, now=_NOW):
    """Emette un token reale con una keypair fresca (come farebbe il tool)."""
    seed, _pub = core.generate_keypair()
    return core.issue_license(seed, name, days, hw, now)


# ── serial deterministico ─────────────────────────────────────────────────────────────────────

def test_license_serial_deterministico_e_formato():
    tok = _issue()
    s1 = registry.license_serial(tok)
    s2 = registry.license_serial(tok)
    assert s1 == s2, "il serial deve essere deterministico per lo stesso token"
    assert s1.startswith("LIC-") and len(s1) == len("LIC-") + 12
    assert s1[4:].isalnum() and s1[4:].isupper()


def test_license_serial_token_diversi_differiscono():
    a, b = _issue(days=15), _issue(days=30)
    assert registry.license_serial(a) != registry.license_serial(b)


# ── decode payload / record dal token ─────────────────────────────────────────────────────────

def test_decode_token_payload_valido():
    tok = _issue(days=10, name="Anna Bianchi")
    payload = registry.decode_token_payload(tok)
    assert payload["name"] == "Anna Bianchi"
    assert payload["hw"] == _HW
    assert payload["exp"] - payload["iss"] == 10 * _DAY


def test_decode_token_payload_malformato_fail_closed():
    for bad in ("", "senza-punto", "a.b.c", ".firma", "€€€.zzz"):
        try:
            registry.decode_token_payload(bad)
        except ValueError:
            continue
        raise AssertionError(f"atteso ValueError su token malformato: {bad!r}")


def test_record_from_token_campi_autoritativi():
    tok = _issue(days=15, name="Mario Rossi", now=_NOW)
    rec = registry.record_from_token(tok, now=_NOW + 5)
    assert rec["serial"] == registry.license_serial(tok)
    assert rec["name"] == "Mario Rossi"
    assert rec["hardware_id"] == _HW
    assert rec["issued"] == _NOW
    assert rec["expiry"] == _NOW + 15 * _DAY
    assert rec["days"] == 15
    assert rec["token"] == tok
    assert rec["recorded_at"] == _NOW + 5


def test_record_from_token_malformato_solleva():
    try:
        registry.record_from_token("non.valido", now=_NOW)
    except ValueError:
        return
    raise AssertionError("record_from_token deve sollevare su token malformato")


# ── append / read append-only ─────────────────────────────────────────────────────────────────

def test_append_e_read_round_trip(tmp_path):
    d = str(tmp_path)
    r1 = registry.record_from_token(_issue(name="Uno"), now=_NOW)
    r2 = registry.record_from_token(_issue(name="Due"), now=_NOW + 1)
    registry.append_record(r1, directory=d)
    registry.append_record(r2, directory=d)
    got = registry.read_records(directory=d)
    assert [r["name"] for r in got] == ["Uno", "Due"]
    assert os.path.isfile(registry.registry_path(d))


def test_read_records_file_assente_e_riga_troncata(tmp_path):
    d = str(tmp_path)
    assert registry.read_records(directory=d) == []          # file assente → []
    rec = registry.record_from_token(_issue(name="Buono"), now=_NOW)
    registry.append_record(rec, directory=d)
    # simula una riga TRONCATA appesa da un crash (nessun \n finale, JSON incompleto)
    with open(registry.registry_path(d), "a", encoding="utf-8") as f:
        f.write('{"serial": "LIC-DEAD', )   # troncata di proposito
    got = registry.read_records(directory=d)
    assert [r["name"] for r in got] == ["Buono"], "la riga troncata va saltata, il valido resta"
    # il prossimo append antepone un separatore e non perde il nuovo record
    registry.append_record(registry.record_from_token(_issue(name="Dopo"), now=_NOW + 2), directory=d)
    assert [r["name"] for r in registry.read_records(directory=d)] == ["Buono", "Dopo"]


# ── stato / giorni ────────────────────────────────────────────────────────────────────────────

def test_record_status_attiva_scaduta_e_expiry_mancante():
    rec = {"expiry": _NOW + 10 * _DAY}
    assert registry.record_status(rec, now=_NOW) == registry.STATUS_ACTIVE
    assert registry.record_status(rec, now=_NOW + 11 * _DAY) == registry.STATUS_EXPIRED
    assert registry.record_status({"expiry": "boh"}, now=_NOW) == registry.STATUS_EXPIRED
    assert registry.record_status({}, now=_NOW) == registry.STATUS_EXPIRED


def test_days_left():
    rec = {"expiry": _NOW + 3 * _DAY + 100}
    assert registry.days_left(rec, now=_NOW) == 4          # arrotonda per eccesso
    assert registry.days_left({"expiry": _NOW - 1}, now=_NOW) == 0
    assert registry.days_left({"expiry": None}, now=_NOW) == 0


# ── vista / ricerca ───────────────────────────────────────────────────────────────────────────

def _records():
    return [
        registry.record_from_token(_issue(days=15, name="Mario Rossi", hw="HW1-AAAA-BBBB-CCCC-DDDD"), now=_NOW),
        registry.record_from_token(_issue(days=30, name="Anna Verdi", hw="HW1-1111-2222-3333-4444"), now=_NOW),
    ]


def test_view_rows_filtro_case_insensitive_per_nome_hw_serial():
    recs = _records()
    all_rows = registry.view_rows(recs, now=_NOW)
    assert len(all_rows) == 2
    # per nome (case-insensitive)
    assert [r["name"] for r in registry.view_rows(recs, query="mario", now=_NOW)] == ["Mario Rossi"]
    # per hardware id (sottostringa)
    assert [r["name"] for r in registry.view_rows(recs, query="1111", now=_NOW)] == ["Anna Verdi"]
    # per serial
    ser = registry.license_serial(recs[0]["token"])
    assert [r["serial"] for r in registry.view_rows(recs, query=ser.lower(), now=_NOW)] == [ser]
    # query che non matcha → vuoto
    assert registry.view_rows(recs, query="zzz", now=_NOW) == []


def test_view_rows_non_espone_il_token():
    rows = registry.view_rows(_records(), now=_NOW)
    assert rows, "attese righe"
    for r in rows:
        assert "token" not in r, "la vista d'elenco non deve esporre il token di attivazione"
    # serializzabile senza segreti (nessuna chiave 'token')
    assert "token" not in json.dumps(rows)


def test_view_rows_annota_stato_e_giorni():
    recs = _records()
    rows_now = registry.view_rows(recs, now=_NOW)
    assert all(r["status"] == registry.STATUS_ACTIVE for r in rows_now)
    # oltre ogni scadenza → tutte SCADUTA, giorni 0
    rows_future = registry.view_rows(recs, now=_NOW + 40 * _DAY)
    assert all(r["status"] == registry.STATUS_EXPIRED and r["days_left"] == 0 for r in rows_future)
