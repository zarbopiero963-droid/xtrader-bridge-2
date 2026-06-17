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

from . import custom_parser_engine, custom_pipeline, parser_manager, recognition, validator
from .csv_writer import build_csv_row
from .parser import parse_message

CUSTOM = "custom"
HARDCODED = "hardcoded"

# Gate di contenuto: il custom è piazzabile ma non ha estratto nulla dal messaggio
# (parser a soli valori fissi su testo arbitrario) → scartato, niente scrittura.
NO_CONTENT_MATCH = "NO_CONTENT_MATCH"


def _chat_approved_for_custom(cfg: dict, chat: str) -> bool:
    """Una chat è approvata per il parsing custom solo se è quella CONFIGURATA
    (`chat_id`) o ha una voce esplicita in `parser_by_chat`. Un `active_parser`
    GLOBALE non deve quindi far scommettere chat non autorizzate (con `chat_id`
    vuoto in un bot multi-chat sarebbe un buco): non si indebolisce il filtro chat."""
    chat = str(chat or "")
    if chat and chat in parser_manager.parser_by_chat(cfg):
        return True
    configured = str(cfg.get("chat_id", "") or "").strip()
    return bool(configured) and chat == configured


def is_chat_allowed(cfg: dict, chat: str) -> bool:
    """Chat che il bridge può processare nel live: quella CONFIGURATA (`chat_id`)
    e le chiavi `parser_by_chat`. Se NULLA è configurato (chat_id vuoto e mappa
    vuota) → comportamento legacy: tutte ammesse (responsabilità dell'utente).
    Gatea sia il percorso custom sia l'hardcoded: nessuna scrittura per chat non
    autorizzate."""
    chat = str(chat or "")
    configured = str(cfg.get("chat_id", "") or "").strip()
    per_chat = parser_manager.parser_by_chat(cfg)
    if not configured and not per_chat:
        return True
    allowed = set(per_chat.keys())
    if configured:
        allowed.add(configured)
    return chat in allowed


def active_custom_parser(cfg: dict, chat: str, parsers_dir: str = None):
    """Parser custom da usare per `chat`, oppure None se la chat non è approvata
    o nessun parser è attivo. Usato sia dal router sia dal prefiltro live."""
    if not _chat_approved_for_custom(cfg, chat):
        return None
    return parser_manager.load_active(cfg, chat, parsers_dir)


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


def resolve_row(text: str, cfg: dict, *, chat_id: str = None, parsers_dir: str = None) -> RouteResult:
    """Sceglie il parser e ritorna la riga da scrivere (o `row=None` se scartata).

    `chat_id` è la chat di ORIGINE del messaggio (dal live): se passato ha la
    precedenza sul `chat_id` di config, così l'override `parser_by_chat` funziona
    anche in setup multi-chat dove il singolo `chat_id` non è impostato."""
    mode = recognition.normalize_mode(cfg.get("recognition_mode", "NAME_ONLY"))
    require_price = validator.require_price_enabled(cfg)
    provider = str(cfg.get("provider", "") or "")
    chat = str((chat_id if chat_id is not None else cfg.get("chat_id", "")) or "")

    defn = active_custom_parser(cfg, chat, parsers_dir)
    if defn is not None:
        # Parser Personalizzato attivo: autoritativo (nessun fallback hardcoded).
        res = custom_pipeline.build_validated_row(
            defn, text, provider=provider, mode=mode, require_price=require_price)
        if not res.placeable:
            return RouteResult(None, res.status, CUSTOM, res.detail, list(res.missing_required))
        # Gate di contenuto: la riga è piazzabile, ma il parser deve aver estratto
        # qualcosa DA QUESTO messaggio. Un parser a soli valori fissi sarebbe
        # piazzabile su qualsiasi testo (anche vuoto): nel live, che bypassa il
        # prefiltro marker, scriverebbe lo stesso bet su ogni messaggio. Scartiamo.
        if not custom_parser_engine.matches_message(defn, text):
            return RouteResult(None, NO_CONTENT_MATCH, CUSTOM, "no_content_match")
        return RouteResult(res.row, validator.VALID, CUSTOM)

    # Fallback: parser hardcoded storico.
    parsed = parse_message(text)
    row = build_csv_row(parsed, provider)
    status, detail = validator.validate(row, mode, require_price=require_price)
    if status == validator.VALID:
        return RouteResult(row, status, HARDCODED)
    return RouteResult(None, status, HARDCODED, detail)
