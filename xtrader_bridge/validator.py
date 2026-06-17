"""Validazione del segnale prima della scrittura CSV (PR-10).

Gate esplicito sopra il riconoscimento (PR-06). Oltre ai campi nome/ID richiesti
dalla modalità, verifica due cose safety-critical:

- il **prezzo** (`Price`) è una quota valida, cioè un numero **> 1.0** (una quota
  a 1.00 non dà guadagno e non è piazzabile; sotto 1 è una linea di mercato, non
  una quota). `require_price` rende il controllo disattivabile;
- il **BetType** è `PUNTA`/`BANCA` (un lato sconosciuto pizzerebbe la scommessa
  sbagliata).

Un segnale senza prezzo, con prezzo non valido o con lato sconosciuto NON deve
raggiungere XTrader. Il validatore non modifica la riga: la accetta o la scarta.
`Points` resta come arriva (vuoto di default): NON va normalizzato a "1".
"""

from . import recognition

VALID = "VALID"
INVALID_MISSING_FIELDS = "INVALID_MISSING_FIELDS"   # campi nome/ID per la modalità
INVALID_MISSING_PRICE = "INVALID_MISSING_PRICE"
INVALID_PRICE = "INVALID_PRICE"
INVALID_BETTYPE = "INVALID_BETTYPE"

_VALID_BETTYPES = ("PUNTA", "BANCA")


def _price_status(value) -> str:
    """VALID se `value` è una quota valida (> 1.0); altrimenti il codice di errore.

    `None` e stringa vuota contano come **prezzo mancante** (non malformato).
    """
    if value is None:
        return INVALID_MISSING_PRICE
    s = str(value).strip()
    if not s:
        return INVALID_MISSING_PRICE
    try:
        price = float(s.replace(",", "."))
    except ValueError:
        return INVALID_PRICE
    return VALID if price > 1.0 else INVALID_PRICE


def validate(row: dict, mode: str, require_price: bool = True):
    """Valuta una riga CSV già costruita.

    Ritorna una tupla `(status, detail)`:
    - status == VALID  → la riga può essere scritta;
    - INVALID_MISSING_FIELDS → `detail` è la lista dei campi nome/ID mancanti;
    - INVALID_BETTYPE        → `detail` è il BetType trovato;
    - INVALID_MISSING_PRICE / INVALID_PRICE → `detail` è il valore Price trovato.
    """
    missing = recognition.missing_fields(row, mode)
    if missing:
        return (INVALID_MISSING_FIELDS, missing)

    bet_type = str(row.get("BetType", "")).strip().upper()
    if bet_type not in _VALID_BETTYPES:
        return (INVALID_BETTYPE, bet_type)

    if require_price:
        status = _price_status(row.get("Price", ""))
        if status != VALID:
            return (status, str(row.get("Price", "")).strip())

    return (VALID, None)


def is_valid(row: dict, mode: str, require_price: bool = True) -> bool:
    """True se la riga supera la validazione completa."""
    return validate(row, mode, require_price)[0] == VALID


def require_price_enabled(cfg: dict) -> bool:
    """Interpreta l'opzione `require_price` dalla config in modo sicuro.

    Solo il booleano JSON `false` disattiva il gate prezzo. Qualsiasi altro valore
    (assente, `null`, `0`, `""`, la stringa `"false"`, ecc.) ricade sul default
    sicuro `True`: una config malformata non deve mai far passare segnali senza prezzo.
    """
    return cfg.get("require_price", True) is not False
