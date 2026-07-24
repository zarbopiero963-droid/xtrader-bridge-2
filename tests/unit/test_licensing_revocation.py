"""Test hard del modulo **revoca** (`xtrader_bridge.licensing.revocation`, #140 revoca online).

Logica pura e fail-closed: firma della lista di revoche (lato proprietario), verifica firma (lato
bridge) e appartenenza per serial/Hardware ID. Nessun segreto reale: keypair generata al volo."""

import base64
import json

from xtrader_bridge.licensing import ed25519, revocation

_HW = "HW1-1234-5678-9ABC-DEF0"
_HW2 = "HW1-AAAA-BBBB-CCCC-DDDD"
_NOW = 1_700_000_000


def _seed_pub():
    """Seed + chiave pubblica hex (usa il License Manager core come nei test licenza)."""
    from license_manager import core
    return core.generate_keypair()   # (seed_hex, public_hex)


def _sign_payload(seed_hex, payload_obj):
    """Firma un payload arbitrario (dict) come envelope `<b64u(json)>.<b64u(sig)>`, così i test
    possono costruire payload firmati **ma non canonici** (tipi errati, entry spazzatura) che solo
    la firma valida ma la verifica fail-closed deve comunque rifiutare."""
    payload = json.dumps(payload_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = ed25519.sign(bytes.fromhex(seed_hex), payload)
    return (base64.urlsafe_b64encode(payload).rstrip(b"=").decode() + "."
            + base64.urlsafe_b64encode(sig).rstrip(b"=").decode())


# ── build + verify round-trip ───────────────────────────────────────────────────────────────────
def test_build_verify_round_trip():
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(
        bytes.fromhex(seed_hex),
        [{"serial": "LIC-ABC123DEF456"}, {"hw": _HW}],
        now=_NOW)
    rev = revocation.verify_revocation_list(signed, public_key_hex=public_hex)
    assert rev is not None
    assert rev.issued == _NOW
    assert "LIC-ABC123DEF456" in rev.serials
    assert _HW in rev.hardware_ids


def test_verify_firma_sbagliata_fail_closed():
    seed_hex, _pub = _seed_pub()
    _seed2, public_hex2 = _seed_pub()      # chiave pubblica DIVERSA da quella che ha firmato
    signed = revocation.build_revocation_list(bytes.fromhex(seed_hex), [{"hw": _HW}], now=_NOW)
    assert revocation.verify_revocation_list(signed, public_key_hex=public_hex2) is None


def test_verify_payload_manomesso_fail_closed():
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(bytes.fromhex(seed_hex), [{"hw": _HW}], now=_NOW)
    part_payload, part_sig = signed.split(".", 1)
    # sostituisce il payload (aggiunge una revoca) tenendo la vecchia firma → firma non valida
    tampered_payload = json.dumps({"v": 1, "iss": _NOW, "revoked": [{"hw": _HW2}]},
                                  sort_keys=True, separators=(",", ":")).encode("utf-8")
    forged = base64.urlsafe_b64encode(tampered_payload).rstrip(b"=").decode() + "." + part_sig
    assert revocation.verify_revocation_list(forged, public_key_hex=public_hex) is None


def test_verify_malformato_e_versione_fail_closed():
    _seed, public_hex = _seed_pub()
    for bad in ("", "senza-punto", "a.b.c-non-b64", ".firma"):
        assert revocation.verify_revocation_list(bad, public_key_hex=public_hex) is None
    # versione errata: firma valida ma v != 1 → None
    seed_hex, public_hex = _seed_pub()
    payload = json.dumps({"v": 999, "iss": _NOW, "revoked": []},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = ed25519.sign(bytes.fromhex(seed_hex), payload)
    signed = (base64.urlsafe_b64encode(payload).rstrip(b"=").decode() + "."
              + base64.urlsafe_b64encode(sig).rstrip(b"=").decode())
    assert revocation.verify_revocation_list(signed, public_key_hex=public_hex) is None


# ── normalize_entries ───────────────────────────────────────────────────────────────────────────
def test_normalize_entries_scarta_vuote_e_normalizza():
    norm = revocation.normalize_entries([
        {"serial": "  lic-abc  "},         # trim + upper
        {"hw": " HW1-X "},                 # trim (hw verbatim tranne spazi)
        {"serial": "", "hw": ""},          # entry vuota → scartata
        {"foo": "bar"},                    # nessun criterio → scartata
        "non-dict",                        # ignorata
    ])
    assert {"serial": "LIC-ABC"} in norm
    assert {"hw": "HW1-X"} in norm
    assert len(norm) == 2


def test_normalize_entries_non_lista_solleva():
    try:
        revocation.normalize_entries("non-lista")
    except ValueError:
        return
    raise AssertionError("normalize_entries deve sollevare su input non-lista")


# ── is_revoked ──────────────────────────────────────────────────────────────────────────────────
def test_is_revoked_per_serial_e_hw():
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(
        bytes.fromhex(seed_hex), [{"serial": "LIC-DEAD"}, {"hw": _HW}], now=_NOW)
    rev = revocation.verify_revocation_list(signed, public_key_hex=public_hex)
    # per serial (case-insensitive)
    assert revocation.is_revoked(rev, serial="lic-dead") is True
    # per hardware id (esatto)
    assert revocation.is_revoked(rev, hardware_id=_HW) is True
    # non revocati
    assert revocation.is_revoked(rev, serial="LIC-ALIVE", hardware_id=_HW2) is False
    # o-logico: basta uno dei due a matchare
    assert revocation.is_revoked(rev, serial="LIC-DEAD", hardware_id=_HW2) is True


def test_is_revoked_lista_none_e_criteri_vuoti():
    assert revocation.is_revoked(None, serial="LIC-X", hardware_id=_HW) is False
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(bytes.fromhex(seed_hex), [{"hw": _HW}], now=_NOW)
    rev = revocation.verify_revocation_list(signed, public_key_hex=public_hex)
    # nessun criterio passato → False (non revoca "tutto")
    assert revocation.is_revoked(rev) is False
    assert revocation.is_revoked(rev, serial="", hardware_id="") is False


def test_build_lista_vuota_verificabile():
    """Una lista SENZA revoche è comunque una lista firmata valida (stato «niente revocato»)."""
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(bytes.fromhex(seed_hex), [], now=_NOW)
    rev = revocation.verify_revocation_list(signed, public_key_hex=public_hex)
    assert rev is not None and rev.serials == set() and rev.hardware_ids == set()
    assert revocation.is_revoked(rev, serial="LIC-X", hardware_id=_HW) is False


def test_verify_public_key_hex_malformato_fail_closed():
    """`public_key_hex` non-hex (ramo `except` su `bytes.fromhex`): fail-closed → `None`, nessun
    crash (review GLM #154)."""
    seed_hex, _pub = _seed_pub()
    signed = revocation.build_revocation_list(bytes.fromhex(seed_hex), [{"hw": _HW}], now=_NOW)
    assert revocation.verify_revocation_list(signed, public_key_hex="non-hex!!") is None
    assert revocation.verify_revocation_list(signed, public_key_hex="abc") is None   # hex dispari


def test_verify_dedup_entry_duplicate():
    """Entry duplicate (stesso serial in casi diversi / stesso hw ripetuto): gli insiemi le
    deduplicano e normalizzano (review GLM #154)."""
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(
        bytes.fromhex(seed_hex),
        [{"serial": "LIC-X"}, {"serial": "lic-x"}, {"hw": _HW}, {"hw": _HW}],
        now=_NOW)
    rev = revocation.verify_revocation_list(signed, public_key_hex=public_hex)
    assert rev is not None                                # diagnostica esplicita (review GPT-5.5 #154)
    assert rev.serials == {"LIC-X"} and rev.hardware_ids == {_HW}


def test_verify_entry_mista_serial_e_hw():
    """Una singola entry con **sia** `serial` **sia** `hw` deve popolare **entrambi** gli insiemi
    revocati (review Sourcery #154): la stessa emissione blocca sia il serial sia la macchina."""
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(
        bytes.fromhex(seed_hex), [{"serial": "LIC-DEAD", "hw": _HW}], now=_NOW)
    rev = revocation.verify_revocation_list(signed, public_key_hex=public_hex)
    assert rev is not None
    assert rev.serials == {"LIC-DEAD"} and rev.hardware_ids == {_HW}
    # entrambi i criteri matchano indipendentemente
    assert revocation.is_revoked(rev, serial="lic-dead") is True
    assert revocation.is_revoked(rev, hardware_id=_HW) is True


def test_verify_revoked_entry_malformata_fail_closed():
    """**Fail-closed sul contratto** (review CodeRabbit Major #154): un payload **firmato** ma con
    `revoked` che contiene un elemento non-dict (`"junk"`, `123`) NON deve produrre una lista
    parziale «attendibile» — l'intera lista è corrotta → `None`. Silenziosamente saltare una entry
    potrebbe far sparire una revoca legittima (un utente revocato resterebbe attivo)."""
    seed_hex, public_hex = _seed_pub()
    for bad_revoked in ([{"serial": "LIC-DEAD"}, "junk"],      # elemento stringa
                        [{"serial": "LIC-DEAD"}, 123],         # elemento int
                        [{"serial": "LIC-DEAD"}, None],        # elemento None
                        [{}],                                  # dict senza alcun criterio
                        [{"serial": "", "hw": ""}],            # criteri vuoti
                        [{"serial": 123}],                     # campo serial non-stringa
                        [{"hw": 123}],                         # campo hw non-stringa
                        [{"serial": [1, 2], "hw": None}]):     # campi di tipo errato → nessun criterio
        signed = _sign_payload(seed_hex, {"v": revocation.REVOCATION_FORMAT_VERSION,
                                          "iss": _NOW, "revoked": bad_revoked})
        # NB: nessun crash (i campi non-stringa sono neutralizzati da `_norm_serial`/`_norm_hw`
        # via `isinstance`), solo fail-closed → None (il loop fuori dal try/except è sicuro).
        assert revocation.verify_revocation_list(signed, public_key_hex=public_hex) is None


def test_verify_tipi_v_e_iss_non_interi_fail_closed():
    """**Fail-closed sui tipi header** (review CodeRabbit Major #154): un payload **firmato** con
    `v`/`iss` non interi ESATTI deve essere rifiutato, senza coercizione né confusione bool→int
    (`True == 1`, `int("1700..")`, `int(1.9)`). Altrimenti uno schema non canonico verrebbe
    trattato come lista fidata."""
    seed_hex, public_hex = _seed_pub()
    # v = True passerebbe `!= 1` (True == 1) senza il controllo di tipo esatto → deve dare None
    assert revocation.verify_revocation_list(
        _sign_payload(seed_hex, {"v": True, "iss": _NOW, "revoked": [{"hw": _HW}]}),
        public_key_hex=public_hex) is None
    # iss non-intero: stringa, float, bool → tutti rifiutati (nessuna coercizione)
    for bad_iss in ("1700000000", 1700000000.0, True, None):
        signed = _sign_payload(seed_hex, {"v": revocation.REVOCATION_FORMAT_VERSION,
                                          "iss": bad_iss, "revoked": [{"hw": _HW}]})
        assert revocation.verify_revocation_list(signed, public_key_hex=public_hex) is None


def test_verify_envelope_troppi_punti_fail_closed():
    """Contratto envelope «due parti esatte» (review GPT-5.5 #154): un envelope con un punto in più
    non deve mai verificare → `None`."""
    seed_hex, public_hex = _seed_pub()
    signed = revocation.build_revocation_list(bytes.fromhex(seed_hex), [{"hw": _HW}], now=_NOW)
    assert revocation.verify_revocation_list(signed + ".coda", public_key_hex=public_hex) is None
