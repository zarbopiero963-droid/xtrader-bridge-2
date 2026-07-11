"""Sottosistema dizionario locale del bridge — **solo locale e solo read-only**.

Storicamente questo subpackage ospitava anche il login Betfair, il client
catalogo e il motore di sync online (issue #86). Quella **funzione «Betfair Sync»
è stata rimossa**: il bridge non contatta più Betfair e non costruisce più il
dizionario automaticamente. Il dizionario locale (`betfair_dictionary.db`, SQLite
in AppData) resta come **substrato**: viene ora popolato dall'utente con i propri
campi personalizzati, e i moduli qui sotto lo leggono in sola lettura.

Vincoli **non negoziabili** validi per ogni modulo qui dentro:

- **100% locale**: nessun dato (dizionario, eventi, MarketId/SelectionId, mapping)
  esce dal PC/VPS. Niente cloud, niente backup/import/export.
- **Solo read-only**: nessuna operazione di scommessa; questi moduli non fanno rete.

Moduli superstiti:

- `local_db`            — storage SQLite del dizionario locale (lettura/scrittura locale);
- `dictionary_resolver` — risoluzione EventId/MarketId/SelectionId dal dizionario (il
  «gancio» per l'arricchimento ID, oggi non cablato sul CSV live — vedi `app.py`);
- `dictionary_viewer`(+`_gui`) — consultazione read-only del dizionario;
- `guided_mapping`      — alberi Sport→Competizione→Squadre dal dizionario (mapping guidato).
"""

from . import (
    dictionary_resolver,
    dictionary_viewer,
    local_db,
)
from .dictionary_resolver import DictionaryResolver
from .dictionary_viewer import DictionaryViewerController
from .local_db import BetfairLocalDB

# NB: `dictionary_viewer_gui` (widget customtkinter) NON è importato qui: l'import del
# package non deve richiedere un display/customtkinter. La GUI si importa esplicitamente.

__all__ = [
    "BetfairLocalDB",
    "DictionaryViewerController",
    "dictionary_viewer",
    "DictionaryResolver",
    "dictionary_resolver",
    "local_db",
]
