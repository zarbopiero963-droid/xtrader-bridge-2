"""CP-04: dal Parser Personalizzato a una riga CSV validata.

Collega l'output del Parser Personalizzato (estrazione CP-02 + value-map CP-03)
al `validator` (PR-10) e al contratto CSV, producendo una riga **pronta per la
scrittura** — o uno stato chiaro di scarto. NON scrive il CSV e NON tocca `app`
(l'aggancio al runtime è CP-09); NON applica trasformazioni (CP-05); NON tocca
la GUI (CP-06).

Due gate, entrambi devono passare perché la riga sia "piazzabile":
1. **parser "Non pronto"** (CP-02): se un campo obbligatorio della regola è vuoto
   → `NOT_READY` (nessuna riga).
2. **validator** (PR-10): campi della modalità di riconoscimento + `Price` > 1.0
   + `BetType` ∈ {PUNTA, BANCA}.

La riga viene comunque costruita (a 14 colonne) per diagnostica, ma va scritta
SOLO se `result.placeable` è True (status VALID).
"""

import re
from dataclasses import dataclass, field

from . import recognition, validator, value_maps
from .csv_writer import DEFAULT_HANDICAP, DEFAULT_POINTS
from .custom_parser import CustomParserDef
from .custom_parser_engine import apply_parser

# Registro value-map di default del pipeline: include il dizionario (le mappe
# markettype/marketname/selectionname usate dallo skeleton e dai parser reali).
# Costruito una volta (legge il CSV una sola volta), poi riusato.
_DEFAULT_REGISTRY = None


def _default_registry() -> dict:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = value_maps.registry(include_dizionario=True)
    return _DEFAULT_REGISTRY

NOT_READY = "NOT_READY"   # gate parser: manca un campo obbligatorio della regola
INVALID_MISSING_PROVIDER = "INVALID_MISSING_PROVIDER"  # Provider assente (contratto)
INVALID_HANDICAP = "INVALID_HANDICAP"  # Handicap valorizzato ma non numerico

# Handicap: numero con segno opzionale (es. "0", "-1", "0.5", "+1,5").
_HANDICAP_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")

# Colonne quota: il contratto XTrader usa il punto decimale (es. "1.85").
_PRICE_COLS = ("Price", "MinPrice", "MaxPrice")


@dataclass
class PipelineResult:
    """Esito del passaggio messaggio → riga validata."""

    status: str                                   # NOT_READY | validator.* (VALID/INVALID_*)
    row: "dict[str, str]" = field(default_factory=dict)   # riga 14 colonne (diagnostica)
    missing_required: "list[str]" = field(default_factory=list)  # gate parser
    detail: object = None                         # dettaglio del validator (campi/valore)

    @property
    def placeable(self) -> bool:
        """True solo se la riga ha passato entrambi i gate (status VALID)."""
        return self.status == validator.VALID


def _normalize_to_contract(row: dict, provider: str) -> dict:
    """Porta la riga al formato del contratto XTrader, senza sovrascrivere i
    valori già impostati dalle regole:

    - `Provider`: dal runtime/config (`provider`) se la regola non lo imposta;
    - `Handicap` = "0" se vuoto/None; `Points` resta vuoto;
    - `Price`/`MinPrice`/`MaxPrice`: virgola → punto (es. "1,85" → "1.85");
    - `BetType`: maiuscolo (il contratto emette esattamente PUNTA/BANCA).
    """
    out = dict(row)
    if provider and not str(out.get("Provider", "")).strip():
        out["Provider"] = provider
    hcap = out.get("Handicap")
    # None o stringa vuota → default; evita str(None)=="None" (truthy).
    if hcap is None or not str(hcap).strip():
        out["Handicap"] = DEFAULT_HANDICAP
    if out.get("Points") is None:
        out["Points"] = DEFAULT_POINTS
    for col in _PRICE_COLS:
        v = out.get(col)
        if v is not None and str(v).strip():
            out[col] = str(v).replace(",", ".")
    bt = out.get("BetType")
    if bt is not None and str(bt).strip():
        out["BetType"] = str(bt).strip().upper()
    return out


def build_validated_row(defn: CustomParserDef, text: str, *,
                        value_maps_registry: dict = None,
                        provider: str = "",
                        mode: str = recognition.DEFAULT_MODE,
                        require_price: bool = True) -> PipelineResult:
    """Applica il parser al messaggio e valida la riga risultante.

    `provider` è fornito dal runtime/config (come per il parser hardcoded) e
    riempie la colonna `Provider` se la regola non la imposta.

    `value_maps_registry` di default include il dizionario (built-in + mappe
    markettype/marketname/selectionname), così i parser/skeleton che usano quelle
    value-map risolvono senza che il chiamante debba passare un registro.

    Ritorna un `PipelineResult`: `placeable` True solo se supera il gate "Non
    pronto" del parser, ha un `Provider` E passa la validazione (modalità +
    prezzo + BetType). La riga è già in formato contratto (quota col punto,
    BetType maiuscolo)."""
    if value_maps_registry is None:
        value_maps_registry = _default_registry()
    res = apply_parser(defn, text, value_maps_registry)
    row = _normalize_to_contract(res.as_csv_row(), provider)

    if not res.ready:
        # Manca un obbligatorio della regola: non si costruisce un segnale.
        return PipelineResult(NOT_READY, row, list(res.missing_required))

    if not str(row.get("Provider", "")).strip():
        # Provider è obbligatorio per il contratto; il runtime lo passa da config.
        return PipelineResult(INVALID_MISSING_PROVIDER, row, list(res.missing_required))

    # Handicap valorizzato dal parser ma non numerico: scartato (il default "0"
    # e i valori del dizionario sono sempre numerici).
    hcap = str(row.get("Handicap", "")).strip()
    if hcap and not _HANDICAP_RE.match(hcap):
        return PipelineResult(INVALID_HANDICAP, row, list(res.missing_required))

    status, detail = validator.validate(row, mode, require_price)
    return PipelineResult(status, row, list(res.missing_required), detail)


def is_placeable(defn: CustomParserDef, text: str, **kwargs) -> bool:
    """Scorciatoia: True se il messaggio produce una riga piazzabile."""
    return build_validated_row(defn, text, **kwargs).placeable
