"""Lista di **revoche** licenze — formato firmato + verifica (issue #140, revoca online).

Il proprietario può **revocare** una licenza ancora valida prima della sua scadenza pubblicando una
**lista di revoche firmata** su un URL statico; il bridge la scarica, ne **verifica la firma** con la
chiave pubblica già incorporata e **blocca** le licenze revocate. Questo modulo è la **logica pura e
condivisa**: firma (lato License Manager) e **verifica** (lato bridge), senza rete né GUI.

Modello di sicurezza (coerente con `license.py`):

- la lista è **firmata Ed25519** con la stessa chiave **privata** del proprietario (mai nel repo/EXE);
  il bridge verifica con la **pubblica** incorporata → nessuno può falsificare «non revocato» né
  iniettare una lista fasulla;
- **fail-closed**: qualunque anomalia in `verify_revocation_list` (formato, firma, versione) →
  `None` (lista non fidata). La *policy* su cosa fare quando la lista è assente/non verificabile è
  del chiamante (il bridge, fase successiva), non di questo modulo;
- revoca **per serial e/o per Hardware ID**: una entry può bloccare una specifica emissione (serial,
  deterministico dal token) e/o un'intera macchina (Hardware ID, stabile tra i rinnovi).

Formato (stesso envelope del token licenza): ``<b64u(payload_json)>.<b64u(signature)>`` dove
``payload_json`` = ``{"v":1,"iss":<unix>,"revoked":[{"serial":..}|{"hw":..}, ...]}`` canonico
(chiavi ordinate). `signature` = Ed25519 sul payload **trasportato verbatim** (nessuna
ri-serializzazione in verifica → nessun mismatch firma/verifica).
"""

from __future__ import annotations

import base64
import json
from collections import namedtuple

from . import ed25519
from .license import LICENSE_PUBLIC_KEY_HEX

# Versione del formato lista di revoche (per migrazioni future senza ambiguità).
REVOCATION_FORMAT_VERSION = 1

# Esito della verifica: `issued` (unix della lista, per freschezza/monotònia lato bridge) +
# gli insiemi normalizzati dei serial e degli Hardware ID revocati.
RevocationList = namedtuple("RevocationList", ["issued", "serials", "hardware_ids"])


def _b64u_encode(raw: bytes) -> str:
    """Base64url senza padding (come `license._b64u_encode`)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    """Base64url ripristinando il padding rimosso da `_b64u_encode`."""
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _norm_serial(serial) -> str:
    """Serial normalizzato (spazi/maiuscole), o `""` se assente/non stringa."""
    return str(serial).strip().upper() if isinstance(serial, str) else ""


def _norm_hw(hw) -> str:
    """Hardware ID normalizzato (spazi), o `""` se assente/non stringa. Le maiuscole NON si
    toccano: l'Hardware ID è confrontato esatto come in `verify_license`."""
    return str(hw).strip() if isinstance(hw, str) else ""


def normalize_entries(entries) -> list:
    """Entry canoniche `[{"serial":..}|{"hw":..}|{"serial":..,"hw":..}]` da una lista di dict.

    Per ogni entry tiene solo i campi `serial`/`hw` **non vuoti** (serial upper, hw verbatim); scarta
    un'entry **senza né serial né hw** (non revocherebbe nulla). Ordina in modo deterministico
    (firma riproducibile). Solleva `ValueError` se `entries` non è una lista."""
    if not isinstance(entries, list):
        raise ValueError("entries deve essere una lista di dict")
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        serial = _norm_serial(e.get("serial"))
        hw = _norm_hw(e.get("hw"))
        entry = {}
        if serial:
            entry["serial"] = serial
        if hw:
            entry["hw"] = hw
        if entry:                       # scarta le entry vuote (nessun criterio di revoca)
            out.append(entry)
    out.sort(key=lambda d: (d.get("serial", ""), d.get("hw", "")))
    return out


def _payload_bytes(entries: list, issued: int) -> bytes:
    """Serializzazione canonica del payload (chiavi ordinate, separatori compatti)."""
    obj = {"v": REVOCATION_FORMAT_VERSION, "iss": int(issued), "revoked": entries}
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_revocation_list(private_seed: bytes, entries, *, now: int) -> str:
    """Crea una **lista di revoche firmata**. Usata dal **License Manager** (il bridge NON la chiama:
    non possiede il seed privato). `private_seed` = seed Ed25519 di 32 byte del proprietario;
    `entries` = lista di dict con `serial`/`hw`; `now` = unix di emissione."""
    norm = normalize_entries(entries)
    payload = _payload_bytes(norm, now)
    signature = ed25519.sign(private_seed, payload)
    return _b64u_encode(payload) + "." + _b64u_encode(signature)


def verify_revocation_list(signed: str, *, public_key_hex: "str | None" = None) -> "RevocationList | None":
    """Verifica una lista di revoche firmata. **Fail-closed**: qualunque anomalia (formato, firma,
    versione, tipi) → `None` (lista non fidata: il chiamante decide la policy). Ritorna una
    `RevocationList(issued, serials, hardware_ids)` con gli insiemi normalizzati se e solo se la
    firma è valida per la chiave pubblica. `public_key_hex=None` usa `LICENSE_PUBLIC_KEY_HEX`."""
    try:
        if not signed or "." not in signed:
            return None
        part_payload, part_sig = signed.strip().split(".", 1)
        payload_bytes = _b64u_decode(part_payload)
        signature = _b64u_decode(part_sig)
    except Exception:       # noqa: BLE001 — lista corrotta/incompleta: fail-closed
        return None
    try:
        public = bytes.fromhex(public_key_hex or LICENSE_PUBLIC_KEY_HEX)
    except Exception:       # noqa: BLE001 — chiave pubblica malformata: rifiuta (fail-closed)
        return None
    if not ed25519.verify(public, payload_bytes, signature):
        return None
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != REVOCATION_FORMAT_VERSION:
            return None
        issued = int(payload["iss"])
        revoked = payload.get("revoked")
        if not isinstance(revoked, list):
            return None
    except Exception:       # noqa: BLE001 — payload non conforme: fail-closed
        return None
    serials, hardware_ids = set(), set()
    for e in revoked:
        if not isinstance(e, dict):
            continue
        s = _norm_serial(e.get("serial"))
        h = _norm_hw(e.get("hw"))
        if s:
            serials.add(s)
        if h:
            hardware_ids.add(h)
    return RevocationList(issued=issued, serials=serials, hardware_ids=hardware_ids)


def is_revoked(revlist: "RevocationList | None", *, serial: "str | None" = None,
               hardware_id: "str | None" = None) -> bool:
    """`True` se la licenza è revocata: il suo **serial** o il suo **Hardware ID** è nella lista.

    `revlist=None` → `False` (nessuna lista fidata = nessuna revoca **nota** da qui; la policy su
    lista assente/non verificabile è del bridge, non di questa funzione). Confronto normalizzato
    (serial upper, hw verbatim), coerente con `normalize_entries`/`verify_revocation_list`."""
    if revlist is None:
        return False
    s = _norm_serial(serial)
    h = _norm_hw(hardware_id)
    return (bool(s) and s in revlist.serials) or (bool(h) and h in revlist.hardware_ids)
