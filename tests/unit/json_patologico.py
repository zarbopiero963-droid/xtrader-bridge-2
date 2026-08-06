"""Fonte unica per l'input JSON **annidato oltre il limite di ricorsione**.

Nasce dal rilievo R5 della #211, e il grep della classe ha mostrato che il difetto non era
in un test solo: la profondità dell'input era scritta come costante fissa `3000` in **tre**
file diversi. Regola 3 — se la correzione va scritta in tre posti, il posto giusto è zero.

## Il difetto, misurato

`3000` non è una proprietà del documento: è una scommessa su `sys.getrecursionlimit()`, che
di default vale `1000`. Con il limite di default il documento è patologico; con il limite
alzato **smette di esserlo**, e `json` lo decodifica senza fiatare:

    limite  1000 | profondità 3000 | RecursionError   <- premessa valida
    limite  6000 | profondità 3000 | OK, nessuna eccezione   <- premessa EVAPORATA

Da lì, quattro test rossi a limite 6000 — ma di due specie opposte, e la differenza è tutto:

- **due erano guardie-premessa** (`test_il_veleno_solleva_ancora_le_classi_attese`,
  `test_il_veleno_e_davvero_veleno`) che vanno rosse **di proposito** quando il veleno
  smette di essere veleno. Quel rosso è corretto: è il test che dice «non sto più
  esercitando nulla» invece di tacere;
- **due asserivano il MECCANISMO** (`post_corruption is True`, `esito is False`) e andavano
  rosse **a torto**: il codice si era comportato benissimo, semplicemente l'input non era
  più ostile.

Nello stesso file b6 convivono già la forma fragile e quella robusta, affiancate: il gemello
`test_load_state_daily_su_file_annidato_non_crasha_lo_start` asserisce solo «non solleva» e
resta **verde** in entrambi gli ambienti.

## La correzione: adattiva, non più grande

La causa non erano le asserzioni, era il generatore dell'input. Una profondità legata al
limite **effettivo dell'interprete che sta girando** resta patologica ovunque — verificato in
sottoprocesso, perché alzare il limite con lo scanner C di `json` può far saltare lo stack:

    limite   1000 | profondità  3000 | RecursionError
    limite   6000 | profondità 18000 | RecursionError
    limite  20000 | profondità 60000 | RecursionError

Il fattore 3 è deliberatamente abbondante: serve superare il limite, non sfiorarlo. Il costo
resta trascurabile (a limite 20000 il documento è ~300 KB, costruito in memoria e mai scritto).
"""

import json
import sys

#: Quanto andare oltre il limite dell'interprete. Non un numero magico: un margine.
FATTORE = 3


def profondita_patologica() -> int:
    """Profondità sufficiente a far ricorrere `json` oltre il limite **di questo processo**.

    Letta a ogni chiamata e non a import-time: un test che alza il limite con
    `sys.setrecursionlimit` deve ottenere un documento coerente con il limite *nuovo*, non
    con quello in vigore quando il modulo è stato importato.
    """
    return sys.getrecursionlimit() * FATTORE


def json_annidato_liste(chiave: str, livelli: int | None = None) -> str:
    """`{"<chiave>": [[[ … ]]]}` — JSON valido, ma che `json` decodifica ricorsivamente."""
    n = profondita_patologica() if livelli is None else livelli
    return '{"' + chiave + '": ' + "[" * n + "]" * n + "}"


def json_annidato_oggetti(chiave: str, livelli: int | None = None) -> str:
    """`{"<chiave>": {"<chiave>": … 1}}` — la variante a oggetti, stessa patologia."""
    n = profondita_patologica() if livelli is None else livelli
    return '{"' + chiave + '":' * 1 + ('{"' + chiave + '":') * (n - 1) + "1" + "}" * n


def premessa_regge(documento: str) -> bool:
    """`True` se su QUESTO interprete il documento è davvero patologico.

    Serve a distinguere i due rossi che il rilievo R5 aveva confuso: un test può così
    asserire sempre l'**invariante** (il chiamante non crasha) e pretendere il
    **meccanismo** di recovery solo dove la premessa è verificata — invece di darla per
    scontata e andare rosso quando non vale.

    Risponde a una domanda, non esegue un controllo: qualunque esito diverso da
    `RecursionError` — decodifica riuscita, JSON malformato, documento troppo grande per la
    memoria — significa «qui la premessa non regge», non un errore da propagare.

    La tupla è **stretta di proposito**, non un `except Exception`: sono esattamente le
    classi che `json.loads` su una stringa può sollevare (`JSONDecodeError` è sottoclasse di
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
