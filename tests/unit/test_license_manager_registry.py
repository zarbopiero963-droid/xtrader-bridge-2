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


def test_record_from_token_payload_incompleto_fail_closed():
    """Payload VALIDO come JSON ma con un campo obbligatorio MANCANTE (es. `exp`): il decode riesce,
    ma `record_from_token` deve **fallire fail-closed** invece di registrare un record monco
    (review GLM #152)."""
    import base64
    payload = {"v": 1, "name": "Senza Exp", "hw": _HW, "iss": _NOW}   # manca 'exp'
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("ascii")
    token = seg + ".firmafinta"
    assert registry.decode_token_payload(token)["name"] == "Senza Exp"   # il decode riesce
    try:
        registry.record_from_token(token, now=_NOW)
    except ValueError:
        return
    raise AssertionError("record_from_token deve sollevare su payload incompleto (manca 'exp')")


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


def test_view_rows_sort_tollerante_expiry_non_numerico():
    """La sort NON deve crashare se un record ha `expiry` non numerico (riga editata a mano/formato
    futuro): i validi in testa per scadenza DECRESCENTE, i non numerici/None in fondo (review
    Sourcery #152)."""
    recs = [
        {"serial": "LIC-BAD1", "name": "Rotto", "hardware_id": _HW, "expiry": "boh"},
        {"serial": "LIC-OK-A", "name": "Vecchia", "hardware_id": _HW, "expiry": _NOW + 5 * _DAY},
        {"serial": "LIC-NONE", "name": "SenzaExp", "hardware_id": _HW, "expiry": None},
        {"serial": "LIC-OK-B", "name": "Nuova", "hardware_id": _HW, "expiry": _NOW + 30 * _DAY},
    ]
    rows = registry.view_rows(recs, now=_NOW)   # non deve sollevare TypeError
    names = [r["name"] for r in rows]
    # i due validi per primi, scadenza DECRESCENTE (Nuova prima di Vecchia)
    assert names[:2] == ["Nuova", "Vecchia"]
    # i non-numerici/None in coda (ordine tra loro non garantito, ma dopo i validi)
    assert set(names[2:]) == {"Rotto", "SenzaExp"}


# ── find_by_serial (opzione B) ────────────────────────────────────────────────────────────────
def test_find_by_serial():
    a = registry.record_from_token(_issue(name="Uno"), now=_NOW)
    b = registry.record_from_token(_issue(name="Due"), now=_NOW)
    recs = [a, b]
    assert registry.find_by_serial(recs, a["serial"]) is a
    # normalizzazione spazi/maiuscole
    assert registry.find_by_serial(recs, "  " + b["serial"].lower() + " ") is b
    # non trovato / vuoto → None
    assert registry.find_by_serial(recs, "LIC-INESISTENTE") is None
    assert registry.find_by_serial(recs, "") is None
    assert registry.find_by_serial([], a["serial"]) is None


# ── store revoche (R3b) ──────────────────────────────────────────────────────────────────────────
def test_revocation_record_dal_record_licenza():
    """`revocation_record` prende serial (autoritativo) + metadati nome/hw + timestamp."""
    rec = {"serial": "lic-abc123", "name": "Mario Rossi", "hardware_id": _HW, "expiry": _NOW + _DAY}
    out = registry.revocation_record(rec, now=_NOW)
    assert out == {"serial": "LIC-ABC123", "name": "Mario Rossi",
                   "hardware_id": _HW, "revoked_at": _NOW}


def test_revocation_record_senza_serial_solleva():
    """Fail-closed: un record senza serial non è revocabile → `ValueError` (non si revoca «nulla»)."""
    for bad in ({}, {"serial": ""}, {"serial": "   "}, {"name": "x"}):
        try:
            registry.revocation_record(bad, now=_NOW)
        except ValueError:
            continue
        raise AssertionError(f"atteso ValueError per record senza serial: {bad!r}")


def test_append_e_read_revocations_round_trip(tmp_path):
    """Append + lettura dello store revoche, nell'ordine d'inserimento (file separato dal registro)."""
    registry.append_revocation({"serial": "LIC-A", "hardware_id": _HW, "revoked_at": _NOW},
                               directory=str(tmp_path))
    registry.append_revocation({"serial": "LIC-B", "hardware_id": "", "revoked_at": _NOW + 1},
                               directory=str(tmp_path))
    revs = registry.read_revocations(directory=str(tmp_path))
    assert [r["serial"] for r in revs] == ["LIC-A", "LIC-B"]
    # store separato: il registro licenze resta vuoto
    assert registry.read_records(directory=str(tmp_path)) == []


def test_read_revocations_file_assente_e_riga_troncata(tmp_path):
    """Fail-safe: store assente → `[]`; ultima riga troncata da un crash → saltata, resto letto."""
    assert registry.read_revocations(directory=str(tmp_path)) == []
    path = registry.revoked_registry_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"serial": "LIC-OK", "revoked_at": _NOW}) + "\n")
        f.write('{"serial": "LIC-TRONCA')     # riga troncata, senza newline
    revs = registry.read_revocations(directory=str(tmp_path))
    assert [r["serial"] for r in revs] == ["LIC-OK"]


def test_is_serial_revoked_normalizza():
    """`is_serial_revoked` confronta normalizzando spazi/maiuscole; vuoto → False."""
    revs = [{"serial": "LIC-X"}, {"serial": "LIC-Y"}]
    assert registry.is_serial_revoked(revs, "  lic-x ") is True
    assert registry.is_serial_revoked(revs, "LIC-Z") is False
    assert registry.is_serial_revoked(revs, "") is False


def test_revocation_entries_dedup_serial_only():
    """`revocation_entries`: entry `{"serial"}` deduplicate; l'hardware_id NON è emesso (revoca
    per-serial di R3b); record senza serial ignorati."""
    revs = [{"serial": "LIC-A", "hardware_id": _HW}, {"serial": "lic-a", "hardware_id": "HWX"},
            {"serial": "LIC-B"}, {"hardware_id": "HWY"}, {"serial": ""}]
    entries = registry.revocation_entries(revs)
    assert entries == [{"serial": "LIC-A"}, {"serial": "LIC-B"}]
    assert all("hw" not in e and "hardware_id" not in e for e in entries)
