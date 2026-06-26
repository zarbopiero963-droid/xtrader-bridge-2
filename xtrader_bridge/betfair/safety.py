"""Guard read-only del sottosistema Betfair (issue #86, regola assoluta).

Il bridge personale deve usare Betfair **solo in lettura**: scaricare il dizionario
(navigation menu + `listMarketCatalogue`) e nient'altro. Le operazioni che
**piazzano/annullano/modificano scommesse** sull'Exchange sono vietate in modo
assoluto, indipendentemente dalla App Key usata.

Questo modulo è la **fonte unica** dell'elenco delle operazioni vietate e l'unico
punto autorizzato a nominarle. Ogni modulo Betfair che instrada un'operazione verso
la rete DEVE chiamare `assert_read_only(op)` con il nome dell'operazione Betfair
prima di effettuare la richiesta: se l'operazione è una di quelle di scommessa, la
chiamata solleva `ReadOnlyViolation` e la richiesta non parte.

Modulo **puro** (nessuna dipendenza da GUI/rete/Telegram): testabile headless.
"""


class ReadOnlyViolation(RuntimeError):
    """Sollevata quando si tenta un'operazione Betfair NON read-only (scommessa)."""


# Operazioni di scommessa dell'Exchange Betfair: vietate in modo assoluto nel bridge
# personale (read-only). I nomi sono quelli ufficiali dell'API Betting (camelCase).
FORBIDDEN_BETTING_OPS = frozenset({
    "placeOrders",
    "cancelOrders",
    "replaceOrders",
    "updateOrders",
})


def _normalize(operation) -> str:
    """Nome operazione normalizzato per il confronto fail-safe.

    Confronto **case-insensitive** e senza spazi: così varianti come
    ``PlaceOrders`` o `` placeorders `` restano comunque bloccate (un guard che si
    aggira con una maiuscola diversa non protegge nulla)."""
    return str(operation or "").strip().casefold()


# Set normalizzato (lazy-free: costruito una volta) per il confronto.
_FORBIDDEN_NORMALIZED = frozenset(_normalize(op) for op in FORBIDDEN_BETTING_OPS)


def is_forbidden_betting_op(operation) -> bool:
    """`True` se `operation` è una delle operazioni di scommessa vietate.

    Tollerante all'input: `None`/non-stringa → `False` (non è un'operazione nota).
    Il confronto è case-insensitive (vedi `_normalize`)."""
    return _normalize(operation) in _FORBIDDEN_NORMALIZED


def assert_read_only(operation) -> str:
    """Verifica che `operation` sia consentita (read-only) e la ritorna.

    Solleva `ReadOnlyViolation` se `operation` è una operazione di scommessa
    (`placeOrders`/`cancelOrders`/`replaceOrders`/`updateOrders`, anche in varianti
    di maiuscole/spazi). Va chiamata da ogni punto che instrada un'operazione
    Betfair verso la rete, **prima** della richiesta, così una chiamata di scommessa
    non può mai partire.

    Ritorna la stringa `operation` originale (comodo per uso inline:
    ``method = assert_read_only("listMarketCatalogue")``)."""
    if is_forbidden_betting_op(operation):
        raise ReadOnlyViolation(
            "Operazione Betfair di scommessa vietata nel bridge personale "
            "(read-only): {!r}".format(operation)
        )
    return operation
