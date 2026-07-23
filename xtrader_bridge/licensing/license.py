"""Licenza del bridge — formato token e **verifica** (firma Ed25519 + hardware + scadenza +
anti-rollback). Logica PURA e fail-closed: nessuna GUI, nessun blocco, nessun accesso a disco.

Il blocco vero (lock della GUI finché la licenza non è valida) è **un'altra PR** (#140 PR 4).
Qui c'è solo la logica che quella PR — e la schermata «Licenza» (PR 2) — chiameranno.

Formato token (decisione proprietario #140 §4: base64 compatto copia-incollabile):

    <b64url(payload_json)>.<b64url(signature)>

- `payload_json` = JSON compatto e ordinato: ``{"v":1,"name":..,"hw":..,"iss":..,"exp":..}``
  (v=versione formato, name="Nome Cognome", hw=Hardware ID legato, iss/exp = unix seconds UTC).
- `signature` = Ed25519 sul **payload_json trasportato verbatim** (nessuna ri-serializzazione in
  verifica → nessun rischio di mismatch tra chi firma e chi verifica).

La firma la produce SOLO il License Manager del proprietario (PR 3) con la chiave PRIVATA, **mai**
committata. Il bridge contiene solo la chiave PUBBLICA e fa solo `verify_license`.
"""

from __future__ import annotations

import base64
import json
import math
from collections import namedtuple

from . import ed25519
from .hwid import NO_HARDWARE_ID

# ── Chiave pubblica di verifica ──────────────────────────────────────────────────────────────
# ⚠️ PLACEHOLDER — chiave pubblica di **TEST** (il seed corrispondente è noto nei test).
# SOSTITUIRE con la chiave pubblica reale del proprietario **prima di distribuire copie
# licenziate** (una sola riga). Finché resta questo placeholder, il bridge accetta licenze
# firmate col seed di TEST: va bene **solo in sviluppo**, non in distribuzione.
# La chiave PRIVATA non è e non deve mai essere nel repository (invariante #1, issue #140).
LICENSE_PUBLIC_KEY_HEX = "42aaead72ceea9f9423f281440c6cfac7a5f99b796b81862f452328972b21b61"

# Marcatore RILEVABILE del placeholder (review Fable/Fugu #143): resta `True` finché sopra c'è la
# chiave di TEST. Sostituendo la chiave con la propria pubblica reale, il proprietario DEVE portarlo
# a `False`. Un gate di release / il lock GUI (PR 4) può rifiutarsi di operare in distribuzione
# finché è `True` (chiave di test = licenze forgiabili). Un test lega i due (coerenza deliberata).
LICENSE_PUBLIC_KEY_IS_PLACEHOLDER = True

# Versione del formato payload accettata.
LICENSE_FORMAT_VERSION = 1

# Tolleranza anti-rollback: quanto indietro può andare l'orologio senza far scattare l'allarme
# (assorbe piccole correzioni NTP; i timestamp sono UTC → nessun problema di fuso/DST). Oltre
# questa soglia si assume una manomissione della data per estendere una licenza scaduta.
_CLOCK_TOLERANCE_S = 6 * 3600

# ── Esiti della verifica ─────────────────────────────────────────────────────────────────────
VALID = "VALID"
MALFORMED = "MALFORMED"                 # token non decodificabile / payload non conforme
INVALID_SIGNATURE = "INVALID_SIGNATURE"  # firma non valida per la chiave pubblica
WRONG_HARDWARE = "WRONG_HARDWARE"       # licenza emessa per un'altra macchina
EXPIRED = "EXPIRED"                     # oltre la data di scadenza
CLOCK_ROLLBACK = "CLOCK_ROLLBACK"       # orologio spostato indietro rispetto all'ultimo visto

# Stato restituito da verify_license. `valid` è l'unico gate booleano; gli altri campi sono per la
# UI (nome, scadenza, giorni rimasti) e sono `None`/0 quando non applicabili.
LicenseStatus = namedtuple("LicenseStatus",
                           ["valid", "reason", "name", "issued", "expiry", "days_left"])


def _b64u_encode(raw: bytes) -> str:
    """Base64url senza padding (token compatto copia-incollabile)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    """Decodifica base64url ripristinando il padding rimosso da `_b64u_encode`."""
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _payload_bytes(name: str, hardware_id: str, issued: int, expiry: int) -> bytes:
    """Serializzazione canonica del payload (chiavi ordinate, separatori compatti)."""
    obj = {"v": LICENSE_FORMAT_VERSION, "name": name, "hw": hardware_id,
           "iss": int(issued), "exp": int(expiry)}
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_license(private_seed: bytes, name: str, hardware_id: str,
                  issued: int, expiry: int) -> str:
    """Crea un token licenza firmato. Usato dal **License Manager** (PR 3) e dai test.

    Il bridge NON chiama questa funzione (non possiede la chiave privata). `private_seed` è il
    seed Ed25519 di 32 byte del proprietario.
    """
    payload = _payload_bytes(name, hardware_id, issued, expiry)
    signature = ed25519.sign(private_seed, payload)
    return _b64u_encode(payload) + "." + _b64u_encode(signature)


def _invalid(reason: str) -> LicenseStatus:
    """Stato «non valida» con il motivo dato e i campi UI azzerati."""
    return LicenseStatus(valid=False, reason=reason, name=None,
                         issued=None, expiry=None, days_left=0)


def verify_license(token: str, hardware_id: str, now: int,
                   last_seen: "int | None" = None,
                   public_key_hex: "str | None" = None) -> LicenseStatus:
    """Verifica un token licenza. **Fail-closed**: qualunque anomalia → `valid=False`.

    Ordine dei controlli (il primo che fallisce determina il motivo):
    1. formato token decodificabile e payload conforme (versione, campi, tipi);
    2. firma Ed25519 valida per la chiave pubblica;
    3. hardware corrispondente a questa macchina;
    4. anti-rollback: l'orologio non è stato spostato indietro rispetto a `last_seen`;
    5. non scaduta (`now <= exp`).

    `now`/`last_seen`/`exp` sono unix seconds UTC. `last_seen=None` = nessuno storico (primo avvio):
    l'anti-rollback non scatta. `public_key_hex=None` usa `LICENSE_PUBLIC_KEY_HEX`.
    """
    # 1) decodifica token + payload
    try:
        if not token or "." not in token:
            return _invalid(MALFORMED)
        part_payload, part_sig = token.strip().split(".", 1)
        payload_bytes = _b64u_decode(part_payload)
        signature = _b64u_decode(part_sig)
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != LICENSE_FORMAT_VERSION:
            return _invalid(MALFORMED)
        name = payload["name"]
        hw = payload["hw"]
        issued = int(payload["iss"])
        expiry = int(payload["exp"])
        if not isinstance(name, str) or not isinstance(hw, str):
            return _invalid(MALFORMED)
    except Exception:       # noqa: BLE001 — token corrotto/incompleto: fail-closed
        return _invalid(MALFORMED)

    # 2) firma
    try:
        public = bytes.fromhex(public_key_hex or LICENSE_PUBLIC_KEY_HEX)
    except Exception:       # noqa: BLE001 — chiave pubblica malformata: rifiuta tutto (fail-closed)
        return _invalid(INVALID_SIGNATURE)
    if not ed25519.verify(public, payload_bytes, signature):
        return _invalid(INVALID_SIGNATURE)

    # 3) hardware — confronto esatto sull'Hardware ID legato.
    # Fail-closed (review Fable/Fugu #143): una macchina non identificabile (`NO_HARDWARE_ID`) o una
    # licenza legata all'impronta nulla NON è mai accettabile, altrimenti una singola licenza
    # varrebbe su TUTTE le macchine "cieche" che collassano sulla stessa impronta.
    if hardware_id == NO_HARDWARE_ID or hw == NO_HARDWARE_ID:
        return _invalid(WRONG_HARDWARE)
    if hw != hardware_id:
        return _invalid(WRONG_HARDWARE)

    # 4) anti-rollback — orologio indietro rispetto all'ultimo timestamp visto
    if last_seen is not None and now < int(last_seen) - _CLOCK_TOLERANCE_S:
        return _invalid(CLOCK_ROLLBACK)

    # 5) scadenza
    if now > expiry:
        return LicenseStatus(valid=False, reason=EXPIRED, name=name,
                             issued=issued, expiry=expiry, days_left=0)

    days_left = max(0, math.ceil((expiry - now) / 86400))
    return LicenseStatus(valid=True, reason=VALID, name=name,
                         issued=issued, expiry=expiry, days_left=days_left)
