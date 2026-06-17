"""CP-03: value-map del Parser Personalizzato.

Una *value-map* traduce un valore grezzo estratto da un messaggio (un alias, es.
"BACK", "OVER 2.5", "GG") nel valore esatto che XTrader si aspetta (es. "PUNTA",
"Over 2,5 gol", "Sì"). Le regole (`FieldRule`, CP-01) indicano quale value-map
usare nel campo `value_map`; il motore (CP-02) la applica dopo l'estrazione.

Fonti delle value-map:
- **built-in**: `bettype` (BACK/LAY e sinonimi → PUNTA/BANCA), safety-critical.
- **dizionario**: `data/dizionario_xtrader.csv` (CP-07/08) esposto come mappe
  per-colonna selezionabili da menu a tendina nel costruttore (CP-06).

Regole di sicurezza:
- lookup **normalizzato** (case/spazi-insensibile), come il dizionario.
- alias **ambiguo** (stesso alias → valori diversi) viene **scartato** dalla
  mappa: meglio "Non pronto" che indovinare un valore sbagliato.
- valore non mappato o mappa sconosciuta → stringa vuota: un obbligatorio resta
  "Non pronto" e non si scrive una riga CSV errata. NON tradurre mai a caso un
  lato di scommessa (PUNTA/BANCA) o una selezione.
"""

from . import dizionario

# Lookup normalizzato coerente col dizionario (minuscolo, trim, spazi collassati).
# Usa la funzione pubblica del dizionario: fonte unica, niente accoppiamento a
# un helper privato.
_norm = dizionario.normalize


# ── built-in: BetType (lato scommessa) ─────────────────────────────────────
# PUNTA = back, BANCA = lay. Sinonimi comuni IT/EN; tutto il resto NON è mappato
# (→ vuoto → "Non pronto"): non si indovina mai il lato della scommessa.
_BETTYPE = {
    "back": "PUNTA", "punta": "PUNTA", "p": "PUNTA", "punto": "PUNTA",
    "lay": "BANCA", "banca": "BANCA", "b": "BANCA", "banco": "BANCA",
}

_BUILTIN = {
    "bettype": dict(_BETTYPE),
}


def value_map_from_pairs(pairs) -> dict:
    """Costruisce una value-map normalizzata da coppie (alias, valore).

    - alias/valore vuoti → ignorati;
    - alias **ambiguo** (stesso alias normalizzato → valori diversi) → rimosso
      (non si indovina). Ritorna `{alias_normalizzato: valore}`.
    """
    acc = {}
    ambiguous = set()
    for alias, value in pairs:
        a = _norm(alias)
        v = str(value).strip() if value is not None else ""
        if a == "" or v == "":
            continue
        if a in acc and acc[a] != v:
            ambiguous.add(a)
        else:
            acc.setdefault(a, v)
    for a in ambiguous:
        acc.pop(a, None)
    return acc


# Colonne del dizionario esposte come value-map per-campo (alias → valore XTrader).
_DIZIONARIO_MAPS = {
    "markettype":    ("MarketAliasTelegram", "MarketType_XTrader"),
    "marketname":    ("MarketAliasTelegram", "MarketName_XTrader"),
    "selectionname": ("SelectionAliasTelegram", "SelectionName_XTrader"),
}


def dizionario_value_maps(rows=None) -> dict:
    """Costruisce le value-map derivate dal dizionario (una per colonna utile).

    `rows` opzionale (lista di dict come da `dizionario.load_dizionario`); se
    assente carica il dizionario ufficiale. Alias ambigui scartati."""
    if rows is None:
        rows = dizionario.load_dizionario()
    maps = {}
    for name, (alias_col, value_col) in _DIZIONARIO_MAPS.items():
        pairs = ((r.get(alias_col, ""), r.get(value_col, "")) for r in rows)
        maps[name] = value_map_from_pairs(pairs)
    return maps


def registry(include_dizionario: bool = False, rows=None) -> dict:
    """Registro `nome → value-map`. Sempre i built-in; opzionalmente le mappe
    derivate dal dizionario (lettura CSV, quindi off di default per i test/uso
    offline)."""
    reg = {name: dict(m) for name, m in _BUILTIN.items()}
    if include_dizionario:
        reg.update(dizionario_value_maps(rows))
    return reg


def available_value_maps(include_dizionario: bool = False, rows=None) -> list:
    """Nomi delle value-map disponibili (per il menu a tendina del costruttore)."""
    return sorted(registry(include_dizionario=include_dizionario, rows=rows))


def resolve(value: str, map_name: str, reg: dict = None) -> str:
    """Traduce `value` tramite la value-map `map_name`.

    Sicuro per default: mappa sconosciuta, valore vuoto o alias non mappato →
    stringa vuota (→ un campo obbligatorio resta "Non pronto"). Mai pass-through
    di un valore non riconosciuto."""
    if reg is None:
        reg = registry()
    table = reg.get(map_name)
    if not table or not value:
        return ""
    return table.get(_norm(value), "")
