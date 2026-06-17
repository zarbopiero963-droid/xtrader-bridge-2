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

from dataclasses import dataclass, field

from . import recognition, validator
from .csv_writer import DEFAULT_HANDICAP, DEFAULT_POINTS
from .custom_parser import CustomParserDef
from .custom_parser_engine import apply_parser

NOT_READY = "NOT_READY"   # gate parser: manca un campo obbligatorio della regola


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


def _with_contract_defaults(row: dict) -> dict:
    """Applica i default del contratto alle colonne non valorizzate dalle regole:
    `Handicap` = "0" (come negli esempi XTrader), `Points` resta vuoto. Non tocca
    i valori già impostati."""
    out = dict(row)
    hcap = out.get("Handicap")
    # None o stringa vuota → default; evita str(None)=="None" (truthy) che
    # impedirebbe l'applicazione del default.
    if hcap is None or not str(hcap).strip():
        out["Handicap"] = DEFAULT_HANDICAP
    # Points: default solo se assente o None; un valore esplicito (anche "") resta.
    if out.get("Points") is None:
        out["Points"] = DEFAULT_POINTS
    return out


def build_validated_row(defn: CustomParserDef, text: str, *,
                        value_maps_registry: dict = None,
                        mode: str = recognition.DEFAULT_MODE,
                        require_price: bool = True) -> PipelineResult:
    """Applica il parser al messaggio e valida la riga risultante.

    Ritorna un `PipelineResult`: `placeable` True solo se supera il gate "Non
    pronto" del parser E la validazione (modalità + prezzo + BetType)."""
    res = apply_parser(defn, text, value_maps_registry)
    row = _with_contract_defaults(res.as_csv_row())

    if not res.ready:
        # Manca un obbligatorio della regola: non si costruisce un segnale.
        return PipelineResult(NOT_READY, row, list(res.missing_required))

    status, detail = validator.validate(row, mode, require_price)
    return PipelineResult(status, row, list(res.missing_required), detail)


def is_placeable(defn: CustomParserDef, text: str, **kwargs) -> bool:
    """Scorciatoia: True se il messaggio produce una riga piazzabile."""
    return build_validated_row(defn, text, **kwargs).placeable
