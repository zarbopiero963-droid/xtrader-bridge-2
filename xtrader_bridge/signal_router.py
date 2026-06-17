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

from . import (
    custom_parser_engine,
    custom_pipeline,
    parser_manager,
    recognition,
    source_manager,
    validator,
)
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
    """Chat che il bridge può processare nel live: quella CONFIGURATA (`chat_id`),
    le chiavi `parser_by_chat` e le **sorgenti multi-chat ATTIVE** (`source_chats`
    con `enabled=True`, PR-24). Una sorgente disattivata NON è ammessa. Se NULLA è
    configurato (chat_id vuoto, mappa vuota, nessuna sorgente attiva) → comportamento
    legacy: tutte ammesse (responsabilità dell'utente). Gatea sia il percorso custom
    sia l'hardcoded: nessuna scrittura per chat non autorizzate."""
    chat = str(chat or "")
    configured = str(cfg.get("chat_id", "") or "").strip()
    per_chat = parser_manager.parser_by_chat(cfg)
    source_ids = source_manager.enabled_chat_ids(cfg)
    if not configured and not per_chat and not source_ids:
        return True
    allowed = set(per_chat.keys()) | set(source_ids)
    if configured:
        allowed.add(configured)
    return chat in allowed


def active_custom_parser(cfg: dict, chat: str, parsers_dir: str = None):
    """Parser custom da usare per `chat`, oppure None se la chat non è approvata
    o nessun parser è attivo. Usato sia dal router sia dal prefiltro live."""
    if not _chat_approved_for_custom(cfg, chat):
        return None
    return parser_manager.load_active(cfg, chat, parsers_dir)


# Marker del formato P.Bet. storico: il prefiltro legacy vale SOLO per il parser
# hardcoded (i formati custom non hanno questi marker).
_LEGACY_MARKERS = ("P.Bet.", "📊")


def should_process(cfg: dict, chat: str, text: str, parsers_dir: str = None) -> bool:
    """Decide se un messaggio live va instradato (PR-11). Logica pura e testabile,
    estratta dal listener Telegram:

    - chat non ammessa (`is_chat_allowed`) → mai (non si indebolisce il filtro chat);
    - chat ammessa con un Parser Personalizzato attivo → sempre (i formati custom
      non hanno i marker `P.Bet.`/📊, quindi il prefiltro legacy non si applica);
    - chat ammessa senza custom (percorso hardcoded) → solo se il testo contiene un
      marker legacy, per non passare al parser storico messaggi non pertinenti."""
    if not is_chat_allowed(cfg, chat):
        return False
    if active_custom_parser(cfg, chat, parsers_dir) is not None:
        return True
    text = text or ""
    return any(marker in text for marker in _LEGACY_MARKERS)


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
    chat = str((chat_id if chat_id is not None else cfg.get("chat_id", "")) or "")
    # Provider PER-CHAT (PR-24): per una sorgente multi-chat attiva usa il suo provider
    # (esplicito, o derivato dalla modalità PRE→TG_PRE / LIVE→TG_LIVE); altrimenti il
    # provider globale di config (retro-compatibilità mono-chat).
    provider = source_manager.provider_for_chat(
        cfg, chat, default=str(cfg.get("provider", "") or ""))

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
