"""Sottopacchetto **licenza** del bridge — isolato dal percorso soldi (Telegram→CSV).

Fondamenta (issue #140, PR 1): impronta hardware + verifica firma/scadenza/anti-rollback. In
questa fase è **solo logica**: nessun blocco, nessuna GUI, non importato da `app.py`. La schermata
«Licenza» (PR 2), il License Manager (PR 3) e il lock della GUI (PR 4) arrivano dopo.

Il bridge fa **solo verifica** con la chiave pubblica; la firma con la chiave privata vive nel
License Manager del proprietario e la chiave privata non è **mai** nel repository (invariante #1).
"""

# Il modulo si chiama `hwid` (non `hardware_id`) per non collidere con la funzione esportata
# `hardware_id()`: un sottomodulo e un attributo di package con lo stesso nome si ombreggiano.
from .hwid import hardware_id, is_identifiable, NO_HARDWARE_ID
from .license import (
    LicenseStatus,
    verify_license,
    VALID,
    MALFORMED,
    INVALID_SIGNATURE,
    WRONG_HARDWARE,
    EXPIRED,
    CLOCK_ROLLBACK,
    LICENSE_PUBLIC_KEY_HEX,
    LICENSE_PUBLIC_KEY_IS_PLACEHOLDER,
)

# NB: `build_license` (la FIRMA) NON è esportato dalla API pubblica del bridge (review GPT-5.5 #143:
# tenere la firma fuori dalla superficie del bridge). Vive in `license.py` per i test e il License
# Manager (PR 3), che lo importano dal sottomodulo. Il bridge usa solo `verify_license`.
__all__ = [
    "hardware_id",
    "is_identifiable",
    "NO_HARDWARE_ID",
    "LicenseStatus",
    "verify_license",
    "VALID",
    "MALFORMED",
    "INVALID_SIGNATURE",
    "WRONG_HARDWARE",
    "EXPIRED",
    "CLOCK_ROLLBACK",
    "LICENSE_PUBLIC_KEY_HEX",
    "LICENSE_PUBLIC_KEY_IS_PLACEHOLDER",
]
