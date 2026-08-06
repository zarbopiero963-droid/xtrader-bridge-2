"""Fonte unica per l'input JSON **annidato oltre il limite di ricorsione**.

Nasce dal rilievo R5 della #211, e il grep della classe ha mostrato che il difetto non era
in un test solo: la profondità dell'input era scritta come costante `3000` in **tre** file
diversi. Regola 3 — se la correzione va scritta in tre posti, il posto giusto è zero.

## Il difetto, misurato

`3000` livelli non sono patologici in assoluto: lo sono **relativamente** a
`sys.getrecursionlimit()`, che di default vale `1000`. Col limite alzato, lo stesso
documento viene decodificato senza fiatare:

    limite 1000 | profondità 3000 | RecursionError            <- premessa valida
    limite 6000 | profondità 3000 | OK, nessuna eccezione     <- premessa EVAPORATA

Da lì quattro test rossi a limite 6000, ma di **due specie opposte**:

- **due erano guardie-premessa** (`test_il_veleno_solleva_ancora_le_classi_attese`,
  `test_il_veleno_e_davvero_veleno`) che vanno rosse **di proposito** quando il veleno
  smette di essere veleno. Quel rosso è corretto: è il test che dice «non sto più
  esercitando nulla» invece di tacere;
- **due asserivano il MECCANISMO** (`post_corruption is True`, `esito is False`) e andavano
  rosse **a torto**: il codice aveva funzionato benissimo, l'input non era più ostile.

## Perché la profondità NON è adattiva — un errore, e la misura che l'ha mostrato

La prima stesura calcolava `sys.getrecursionlimit() * 3`, per restare patologica a ogni
limite. **Rilievo GPT-5.5 sulla PR #296, ed era giusto**, contro una cosa scritta in questo
stesso docstring e poi contraddetta dal codice.

Lo scanner C di `json` ricorre finché il contatore raggiunge il limite: i frame C
realmente consumati sono `min(profondità_documento, limite)`. Quindi con profondità **fissa**
il consumo è limitato dal documento, con profondità **adattiva** è limitato dal *limite* —
e cresce senza tetto. Misurato:

    limite 30000 | profondità fissa 3000    -> 3000 frame C, parse OK
    limite 30000 | profondità limite*3      -> 30000 frame C, RecursionError

Su Linux (stack 8 MB) la seconda regge; su **Windows**, dove lo stack di default è ~1 MB,
quei frame sono un **segfault**, non un `RecursionError` — cioè il runner che muore invece
di un test che fallisce. La robustezza guadagnata valeva per uno scenario che qui non si
verifica (nessuno alza il limite); il rischio introdotto era reale e su una piattaforma che
è il target principale del progetto.

Quindi: profondità **fissa e conservativa**, con lo stesso consumo di stack di oggi — la
patch non peggiora nulla — e la fragilità di R5 risolta dove stava davvero, cioè
nell'**asserzione**: `premessa_regge()` permette a un test di pretendere sempre
l'*invariante* e il *meccanismo* solo dove l'input è davvero ostile.
"""

import json
import sys

#: Profondità di annidamento dei documenti patologici.
#:
#: Fissa di proposito (vedi il docstring del modulo): è la stessa che il repository usa da
#: sempre, quindi il consumo di stack C resta identico a quello già collaudato in CI, Windows
#: compreso. Legarla a `sys.getrecursionlimit()` farebbe crescere quel consumo senza tetto.
PROFONDITA = 3000


def profondita_patologica() -> int:
    """La profondità usata dai generatori. Esposta per i test che la vogliono nominare."""
    return PROFONDITA


def _livelli(livelli: int | None) -> int:
    """Risolve e **valida** la profondità richiesta.

    `livelli=0` o negativo produrrebbe JSON malformato (`json_annidato_liste`) o un oggetto
    troncato (`json_annidato_oggetti`) — un input rotto travestito da input ostile, cioè un
    test che fallisce per la ragione sbagliata. Rilievo CodeRabbit sulla PR #296.
    """
    n = PROFONDITA if livelli is None else livelli
    if n < 1:
        raise ValueError(f"la profondità deve essere >= 1, ricevuto {n!r}")
    return n


def json_annidato_liste(chiave: str, livelli: int | None = None) -> str:
    """`{"<chiave>": [[[ … ]]]}` — JSON valido, ma che `json` decodifica ricorsivamente."""
    n = _livelli(livelli)
    return '{"' + chiave + '": ' + "[" * n + "]" * n + "}"


def json_annidato_oggetti(chiave: str, livelli: int | None = None) -> str:
    """`{"<chiave>": {"<chiave>": … 1}}` — la variante a oggetti, stessa patologia."""
    n = _livelli(livelli)
    return '{"' + chiave + '":' + ('{"' + chiave + '":') * (n - 1) + "1" + "}" * n


def premessa_regge(documento: str) -> bool:
    """`True` se su QUESTO interprete il documento è davvero patologico.

    È il cuore della correzione di R5: distingue i due rossi che il rilievo aveva confuso.
    Un test può così asserire **sempre** l'invariante (il chiamante non crasha) e pretendere
    il **meccanismo** di recovery solo dove la premessa è verificata — invece di darla per
    scontata e andare rosso quando non vale.

    Sicura per costruzione: i frame C consumati sono `min(PROFONDITA, limite)`, quindi al più
    `PROFONDITA` qualunque sia `sys.getrecursionlimit()` — non può far crescere il consumo di
    stack oltre quello che il repository già esercita.

    La tupla è **stretta di proposito**, non un `except Exception`: sono esattamente le classi
    che `json.loads` su una stringa può sollevare (`JSONDecodeError` è sottoclasse di
    `ValueError`). Se un domani ne comparisse una fuori elenco, è giusto che risalga e si
    faccia vedere, invece di essere silenziata in un `False` che somiglia a una risposta.
    """
    try:
        json.loads(documento)
    except RecursionError:
        return True
    except (ValueError, TypeError, MemoryError):
        return False
    return False


def limite_ricorsione() -> int:
    """`sys.getrecursionlimit()`, esposto perché i test possano *spiegare* uno skip."""
    return sys.getrecursionlimit()
