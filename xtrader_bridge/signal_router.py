"""CP-09: instradamento del segnale al parser giusto (logica testabile).

Decide la riga CSV da scrivere per un messaggio Telegram:

- se per la chat è attivo un **Parser Personalizzato** (CP-07), è lui a parsare:
  se produce una riga piazzabile la si scrive, altrimenti il segnale è scartato.
  Un custom attivo è **autoritativo**: NON si ripiega sull'hardcoded (che
  potrebbe interpretare diversamente un messaggio che il custom ha rifiutato);
- se nessun custom è attivo, si usa il **parser hardcoded** (comportamento
  storico): `parse_message` → `build_csv_row` → `validator`.

Funzione pura (nessuna GUI/scrittura): ritorna la riga e lo stato; è `app` a
scrivere il CSV. Così l'instradamento è interamente testabile.
"""

from dataclasses import dataclass, field

from . import custom_pipeline, parser_manager, recognition, validator
from .csv_writer import build_csv_row
from .parser import parse_message

CUSTOM = "custom"
HARDCODED = "hardcoded"


@dataclass
class RouteResult:
    """Esito dell'instradamento. `row` è valorizzata SOLO se piazzabile."""

    row: dict = None
    status: str = validator.VALID
    source: str = HARDCODED                       # custom | hardcoded
    detail: object = None                         # motivo dello scarto
    missing_required: list = field(default_factory=list)

    @property
    def placeable(self) -> bool:
        return self.row is not None


def resolve_row(text: str, cfg: dict, *, parsers_dir: str = None) -> RouteResult:
    """Sceglie il parser e ritorna la riga da scrivere (o `row=None` se scartata)."""
    mode = recognition.normalize_mode(cfg.get("recognition_mode", "NAME_ONLY"))
    require_price = validator.require_price_enabled(cfg)
    provider = str(cfg.get("provider", "") or "")
    chat_id = str(cfg.get("chat_id", "") or "")

    defn = parser_manager.load_active(cfg, chat_id, parsers_dir)
    if defn is not None:
        # Parser Personalizzato attivo: autoritativo.
        res = custom_pipeline.build_validated_row(
            defn, text, provider=provider, mode=mode, require_price=require_price)
        if res.placeable:
            return RouteResult(res.row, validator.VALID, CUSTOM)
        return RouteResult(None, res.status, CUSTOM, res.detail, list(res.missing_required))

    # Fallback: parser hardcoded storico.
    parsed = parse_message(text)
    row = build_csv_row(parsed, provider)
    status, detail = validator.validate(row, mode, require_price=require_price)
    if status == validator.VALID:
        return RouteResult(row, status, HARDCODED)
    return RouteResult(None, status, HARDCODED, detail)
