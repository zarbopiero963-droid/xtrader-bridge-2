"""Stato licenza per la UI (#140 PR 2) — logica **pura**, testabile headless.

Mappa `(token memorizzato, Hardware ID, ora, last_seen)` in uno stato mostrabile: riusa
`licensing.verify_license` e aggiunge lo stato UI `NOT_PRESENT` (nessuna licenza inserita).
Nessun blocco, nessun I/O, nessuna GUI: solo calcolo + etichette localizzate.
"""

from __future__ import annotations

from . import i18n
from .licensing import (
    verify_license,
    LicenseStatus,
    EXPIRED,
    WRONG_HARDWARE,
    INVALID_SIGNATURE,
    CLOCK_ROLLBACK,
    MALFORMED,
)

# Stati UI aggiuntivi (oltre a quelli di `licensing`):
# - NOT_PRESENT: nessun token memorizzato (l'utente non ha ancora attivato);
# - PERSIST_FAILED: verifica ok ma impossibile registrare l'heartbeat anti-rollback su disco →
#   fail-CLOSED (una licenza il cui heartbeat non è persistibile non deve risultare valida, altrimenti
#   l'anti-rollback è aggirabile: vedi `license_gui.current_status`).
NOT_PRESENT = "NOT_PRESENT"
PERSIST_FAILED = "PERSIST_FAILED"


def next_last_seen(last_seen, now: int) -> int:
    """`last_seen` MONOTÒNO per l'anti-rollback: non torna mai indietro (max con `now`).

    Un `last_seen` assente/malformato riparte da `now`. Così, salvando ad ogni verifica valida,
    l'orologio-di-riferimento avanza e uno spostamento all'indietro viene poi riconosciuto.
    """
    try:
        prev = int(last_seen) if last_seen is not None else None
    except (TypeError, ValueError):
        prev = None
    return int(now) if prev is None else max(prev, int(now))


def compute_status(token, hardware_id: str, now: int,
                   last_seen=None, public_key_hex=None) -> LicenseStatus:
    """Stato della licenza corrente. Token assente/vuoto → `NOT_PRESENT`; altrimenti delega a
    `verify_license` (fail-closed)."""
    if not token:
        return LicenseStatus(valid=False, reason=NOT_PRESENT, name=None,
                             issued=None, expiry=None, days_left=0)
    return verify_license(token, hardware_id, now, last_seen=last_seen,
                          public_key_hex=public_key_hex)


def status_severity(status: LicenseStatus) -> str:
    """`ok` (valida), `warn` (nessuna licenza inserita) o `error` (non valida/scaduta/…)."""
    if status.valid:
        return "ok"
    if status.reason == NOT_PRESENT:
        return "warn"
    return "error"


def status_message(status: LicenseStatus) -> str:
    """Messaggio localizzato per la schermata Licenza (value-as-key IT, tradotto EN/ES)."""
    if status.valid:
        return i18n.tr("✅ Licenza attiva — {name} · scade tra {days} giorni").format(
            name=status.name or "", days=status.days_left)
    return {
        NOT_PRESENT: i18n.tr("🔒 Nessuna licenza inserita."),
        PERSIST_FAILED: i18n.tr("⛔ Impossibile aggiornare lo stato licenza su disco (permessi?)."),
        EXPIRED: i18n.tr("⛔ Licenza scaduta."),
        WRONG_HARDWARE: i18n.tr("⛔ Licenza emessa per un'altra macchina (hardware diverso)."),
        INVALID_SIGNATURE: i18n.tr("⛔ Licenza non valida (firma non riconosciuta)."),
        CLOCK_ROLLBACK: i18n.tr("⛔ Orologio spostato indietro: licenza sospesa."),
        MALFORMED: i18n.tr("⛔ Chiave licenza non valida (formato errato)."),
    }.get(status.reason, i18n.tr("⛔ Licenza non valida."))
