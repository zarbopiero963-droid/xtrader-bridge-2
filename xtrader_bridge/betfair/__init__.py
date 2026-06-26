"""Sottosistema Betfair del bridge — **solo locale e solo read-only** (issue #86).

Questo subpackage ospiterà (PR-P2…PR-P11) lo storage cifrato delle credenziali,
il client di login Betfair.it con Delayed App Key, il dizionario locale multi-sport
e il motore di sync. Vincoli **non negoziabili**, validi per ogni modulo qui dentro:

- **100% locale**: nessun dato Betfair (App Key, credenziali, dizionario, eventi,
  MarketId/SelectionId, sync history, mapping) esce dal PC/VPS. Niente cloud,
  niente backup/import/export.
- **Solo read-only**: sono **vietate** le operazioni di scommessa dell'Exchange.
  L'elenco e il gate vivono in `safety.py` (`assert_read_only`,
  `FORBIDDEN_BETTING_OPS`): ogni chiamata che instrada una operazione Betfair deve
  passare da lì prima di colpire la rete.
- **Segreti mai loggati**: App Key, username, password, sessionToken, certificato,
  private key, headers e payload/response di login non vanno mai nei log. Il
  `sessionToken` vive **solo in RAM** (mai su disco).

PR-P1 ha introdotto lo scheletro e il guard read-only; PR-P2 aggiunge lo storage
locale sicuro delle credenziali, la sessione RAM-only e la redazione dei log. I
moduli funzionali (auth, dizionario, sync) arrivano nelle PR successive (vedi
`docs/audit/blocco1_personale_roadmap.md`).
"""

from . import credential_store, log_safety, sync_tab_controller
from .credential_store import BetfairCredentials
from .safety import (
    FORBIDDEN_BETTING_OPS,
    ReadOnlyViolation,
    assert_read_only,
    is_forbidden_betting_op,
)
from .session import BetfairSession
from .sync_tab_controller import BetfairSyncController

# NB: `sync_tab_gui` (widget customtkinter) NON è importato qui: l'import del package
# non deve richiedere un display/customtkinter. La GUI si importa esplicitamente.

__all__ = [
    "FORBIDDEN_BETTING_OPS",
    "ReadOnlyViolation",
    "assert_read_only",
    "is_forbidden_betting_op",
    "BetfairCredentials",
    "BetfairSession",
    "BetfairSyncController",
    "credential_store",
    "log_safety",
    "sync_tab_controller",
]
