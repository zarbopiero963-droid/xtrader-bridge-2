"""CP-05: trasformazioni configurabili del Parser Personalizzato.

Una *trasformazione* deriva un valore da quello estratto, quando il valore da
scrivere non è nel messaggio ma va calcolato. Esempio del proprietario: dal
punteggio "6-0" si ricava la linea Over della somma gol → "Over 6,5".

Le regole (`FieldRule`, CP-01) indicano la trasformazione nel campo `transform`;
il motore (CP-02) la applica DOPO l'estrazione e PRIMA della value-map (CP-03).

Sicurezza (fail-closed): trasformazione sconosciuta o input non interpretabile
→ stringa vuota, così un campo obbligatorio resta "Non pronto" e non si scrive
una riga CSV inventata.
"""

import re

# Punteggio "X-Y" / "X:Y" / "X x Y" (con spazi opzionali).
# Cifre ASCII SOLTANTO (`[0-9]`, non `\d`): come `numbers_re.DECIMAL` (#318 L2-1). Con `\d` un
# «٦-٠» produceva «Over 6,5» — la linea Over finisce nella riga CSV, quindi era una selezione
# inventata a partire da cifre che nel messaggio non sono un punteggio (#166 P3-cp1).
_SCORE_RE = re.compile(r"^\s*([0-9]{1,3})\s*[-:x]\s*([0-9]{1,3})\s*$", re.IGNORECASE)

# Gol per lato oltre cui il punteggio è implausibile per una partita reale: un input
# come "999-999" (ben formato ma assurdo) non deve generare una linea Over inventata (A5).
_MAX_GOALS_PER_SIDE = 30
# Cap anche sulla SOMMA: "30-30" sta nel limite per-lato ma dà un totale assurdo
# ("Over 60,5"). Il pipeline custom richiede solo SelectionName/price/event/bet non vuoti,
# quindi senza questo cap potrebbe scrivere una riga CSV con una linea inventata (Codex).
_MAX_GOALS_TOTAL = 30


def _somma_gol(value: str):
    """Somma gol di un punteggio **plausibile**, oppure ``None`` se non lo è.

    FONTE UNICA della lettura del punteggio (regola 3): le trasformazioni Over — tempo
    pieno e primo tempo — devono accettare **esattamente** gli stessi input. Duplicare
    regex e cap significherebbe che, il giorno in cui uno dei due cambia, lo stesso
    messaggio produce una linea con una trasformazione e nessuna con l'altra: un buco
    invisibile finché non capita in produzione.

    ``None`` (non zero: uno 0-0 è un punteggio valido con somma 0) quando l'input non è
    un punteggio, quando un lato supera `_MAX_GOALS_PER_SIDE`, o quando la **somma**
    supera `_MAX_GOALS_TOTAL` (A5 + Codex: "30-30" starebbe nel limite per-lato ma darebbe
    un totale assurdo)."""
    m = _SCORE_RE.match(value or "")
    if not m:
        return None
    home, away = int(m.group(1)), int(m.group(2))
    if home > _MAX_GOALS_PER_SIDE or away > _MAX_GOALS_PER_SIDE:
        return None
    if home + away > _MAX_GOALS_TOTAL:
        return None
    return home + away


def _score_to_over(value: str) -> str:
    """Punteggio → linea Over **tempo pieno**: "6-0" → "Over 6,5", "2-3" → "Over 5,5".

    Input non interpretabile o implausibile → "" (fail-closed, vedi `_somma_gol`).

    La forma prodotta ("Over N,5") è quella che le value-map del dizionario risolvono a
    `OVER_UNDER_*`, cioè **tempo pieno**. Per il primo tempo serve `_score_to_over_ht`:
    questa stringa non porta con sé l'informazione sul periodo, quindi nessuna value-map
    a valle può dedurlo."""
    tot = _somma_gol(value)
    return "" if tot is None else f"Over {tot},5"


def _score_to_over_ht(value: str) -> str:
    """Punteggio → linea Over **primo tempo**: "0-1" → "over 1,5 ht".

    Stessa disciplina fail-closed della variante tempo pieno (fonte unica `_somma_gol`):
    stessi input accettati, stessi cap, stesso "" in caso di dubbio.

    Emette la **forma-alias del dizionario** ("over N,5 ht") invece della forma-nome
    ("Over N,5"): è quella che le mappe `markettype`/`marketname`/`selectionname` già
    esistenti risolvono a `FIRST_HALF_GOALS_*`. Così il primo tempo si ottiene senza
    toccare né il dizionario né il motore.

    ⚠️ Il `SelectionName` risolto è **identico** fra i due tempi ("Over 0,5 goal"): a
    distinguere il mercato è solo il `MarketType`. Per questo la scelta fra le due
    trasformazioni dev'essere **esplicita nella regola**, mai dedotta.

    Copertura: il dizionario ha le righe primo tempo fino a **2,5** (contro 8,5 del tempo
    pieno). Oltre, la value-map non trova nulla e il campo resta vuoto — fail-closed: il
    segnale si perde, ma non se ne scrive uno sbagliato."""
    tot = _somma_gol(value)
    return "" if tot is None else f"over {tot},5 ht"


# Registro delle trasformazioni disponibili (per il menu del costruttore, CP-06).
# `score_to_over` NON viene rinominata in `..._ft` né rimossa dal menu: la tendina del
# costruttore si popola da `available_transforms()`, quindi un parser già salvato con quel
# nome si troverebbe un menu privo del proprio valore — e perderebbe la trasformazione in
# silenzio al primo salvataggio. Il nome storico resta, e significa **tempo pieno**.
_TRANSFORMS = {
    "score_to_over": _score_to_over,
    "score_to_over_ht": _score_to_over_ht,
}


def available_transforms() -> list:
    return sorted(_TRANSFORMS)


def has_transform(name: str) -> bool:
    return name in _TRANSFORMS


def apply(value: str, name: str) -> str:
    """Applica la trasformazione `name` a `value`.

    Sicuro per default: trasformazione sconosciuta → "" (→ "Non pronto" se il
    campo è obbligatorio). Mai propagare un valore non trasformato a caso."""
    fn = _TRANSFORMS.get(name)
    if fn is None:
        return ""
    return fn(value)
