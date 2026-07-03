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


def _method_segments(operation) -> tuple:
    """Forme confrontabili di `operation`: la stringa intera normalizzata **e** il
    **segmento finale** di un metodo JSON-RPC qualificato (dopo l'ultimo ``/`` o
    ``.``), es. ``SportsAPING/v1.0/placeOrders`` → anche ``placeorders``.

    Senza questo (audit #259 D1) un chiamante che passasse il metodo nella forma
    qualificata dell'API aggirerebbe il guard: la stringa intera non è tra i nomi
    corti vietati, e una scommessa partirebbe. Il catalogue client usa già la forma
    corta (``listMarketCatalogue``); questa estrazione rende il gate robusto anche
    alla forma lunga per qualunque chiamante presente o futuro."""
    whole = _normalize(operation)
    # Strip dei separatori ai BORDI prima di estrarre il segmento: senza, una forma
    # con separatore finale (``placeOrders/`` o ``placeOrders.``) darebbe un segmento
    # VUOTO e aggirerebbe il guard (review Fable/Fugu #313). Il tail vuoto è comunque
    # scartato dal filtro sotto, come cintura di sicurezza.
    core = whole.replace("\\", "/").strip("/.")
    tail = core.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
    return (whole, tail) if tail and tail != whole else (whole,)


# Set normalizzato (lazy-free: costruito una volta) per il confronto.
_FORBIDDEN_NORMALIZED = frozenset(_normalize(op) for op in FORBIDDEN_BETTING_OPS)


def is_forbidden_betting_op(operation) -> bool:
    """`True` se `operation` è una delle operazioni di scommessa vietate.

    Tollerante all'input: `None`/non-stringa → `False` (non è un'operazione nota).
    Il confronto è case-insensitive e riconosce sia il **nome corto**
    (``placeOrders``) sia la **forma JSON-RPC qualificata** (``SportsAPING/v1.0/
    placeOrders``), così il guard non è aggirabile col metodo completo (#259 D1)."""
    return any(seg in _FORBIDDEN_NORMALIZED for seg in _method_segments(operation))


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
