"""CP-09: instradamento del segnale al parser giusto (logica testabile).

Decide la riga CSV da scrivere per un messaggio Telegram:

- se per la chat è attivo un **Parser Personalizzato** (CP-07), è lui a parsare:
  se produce una riga piazzabile la si scrive, altrimenti il segnale è scartato.
  Un custom attivo è **autoritativo**;
- se nessun custom è attivo, il messaggio è **ignorato**: il parser automatico
  P.Bet (`parse_message`) è DISATTIVATO nel percorso live (CP-09b). Per processare
  una chat serve un Parser Personalizzato attivo (globale o per-chat). Il codice di
  `parse_message`/`build_csv_row` resta nel repo ma non è più nel flusso live.

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

CUSTOM = "custom"
HARDCODED = "hardcoded"

# Nessun Parser Personalizzato attivo: il parser automatico P.Bet è disattivato
# (CP-09b), quindi il messaggio è ignorato (nessuna riga scritta).
NO_PARSER = "no_parser"

# Gate di contenuto: il custom è piazzabile ma non ha estratto nulla dal messaggio
# (parser a soli valori fissi su testo arbitrario) → scartato, niente scrittura.
NO_CONTENT_MATCH = "NO_CONTENT_MATCH"


def _disabled_source_ids(cfg: dict) -> set:
    """Chat di sorgenti `source_chats` **disattivate** (deny-list): disattivare una
    sorgente deve fermarla DAVVERO, anche se la stessa chat ha un override
    `parser_by_chat` o coincide con `chat_id` (PR-24, finding Codex)."""
    return {s["chat_id"] for s in source_manager.source_chats(cfg)
            if not s["enabled"] and s["chat_id"]}


def _chat_approved_for_custom(cfg: dict, chat: str) -> bool:
    """Una chat è approvata per il parsing custom se è quella CONFIGURATA
    (`chat_id`), ha una voce esplicita in `parser_by_chat`, o è una **sorgente
    multi-chat ATTIVA** (`source_chats`, PR-24): così un `active_parser` GLOBALE
    funziona anche per le sorgenti, senza far scommettere chat non autorizzate.
    Una sorgente **disattivata** non è mai approvata, nemmeno con un override."""
    chat = str(chat or "")
    if chat in _disabled_source_ids(cfg):
        return False
    if chat and chat in parser_manager.parser_by_chat(cfg):
        return True
    if chat and chat in set(map(str, source_manager.enabled_chat_ids(cfg))):
        return True
    configured = str(cfg.get("chat_id", "") or "").strip()
    return bool(configured) and chat == configured


def has_chat_filter(cfg: dict) -> bool:
    """True se la config definisce ALMENO un criterio di ammissione chat: `chat_id`,
    una voce `parser_by_chat`, o una `source_chats` (anche **disattivata**).

    Unica fonte di verità della condizione "ammetti tutte": `is_chat_allowed` la usa
    per il ramo legacy e `app._start` per il fail-fast d'avvio, così le due non
    possono divergere (finding Sourcery). Quando ritorna False il bridge accetterebbe
    segnali da **qualsiasi** chat → `app._start` annulla l'avvio."""
    configured = str(cfg.get("chat_id", "") or "").strip()
    per_chat = parser_manager.parser_by_chat(cfg)
    has_sources = bool(source_manager.source_chats(cfg))
    return bool(configured or per_chat or has_sources)


def allowed_chats(cfg: dict) -> set:
    """Insieme ESPLICITO dei `chat_id` che il listener processerà: unione di
    `chat_id` configurato, chiavi `parser_by_chat` e sorgenti `source_chats`
    **attive**, MENO le sorgenti **disattivate** (deny-list). È il modello "ascolta
    solo queste chat, mai tutte": la GUI può mostrarlo all'utente ("ascolto queste N
    chat") e il listener processa esattamente questo insieme.

    Fonte unica della allowlist: `is_chat_allowed` la riusa, così filtro live e
    visualizzazione non possono divergere. ATTENZIONE: un set **vuoto** NON significa
    "ammetti tutte". Quando non c'è alcun criterio (`not has_chat_filter`) il
    comportamento legacy sarebbe "ammetti tutte" (vedi `is_chat_allowed`), ma è
    bloccato dal fail-fast d'avvio; distinguere i due casi con `has_chat_filter`."""
    configured = str(cfg.get("chat_id", "") or "").strip()
    # Chiavi parser_by_chat già normalizzate a str dalla fonte (parser_manager),
    # coerenti col confronto str(chat) di is_chat_allowed e coi lookup del custom.
    allowed = set(parser_manager.parser_by_chat(cfg).keys())
    allowed |= set(map(str, source_manager.enabled_chat_ids(cfg)))   # solo le attive
    if configured:
        allowed.add(configured)
    # Una sorgente DISATTIVATA è deny-list: vince su parser_by_chat/chat_id.
    allowed -= _disabled_source_ids(cfg)
    return allowed


def is_chat_allowed(cfg: dict, chat: str) -> bool:
    """Chat che il bridge può processare nel live: quella CONFIGURATA (`chat_id`),
    le chiavi `parser_by_chat` e le **sorgenti multi-chat ATTIVE** (`source_chats`
    con `enabled=True`, PR-24). Una sorgente disattivata NON è ammessa.

    Comportamento legacy "tutte ammesse" SOLO se NULLA è configurato (`not
    has_chat_filter`): `chat_id` vuoto, `parser_by_chat` vuota e **nessuna**
    `source_chats` (anche disattivata). Così disattivare tutte le sorgenti **blocca
    tutte** le chat, non riapre il gate. Gatea sia il percorso custom sia l'hardcoded:
    nessuna scrittura per chat non autorizzate. L'allowlist esplicita è calcolata da
    `allowed_chats` (fonte unica)."""
    if not has_chat_filter(cfg):
        return True
    return str(chat or "") in allowed_chats(cfg)


def listened_chats(cfg: dict) -> list:
    """Vista LEGGIBILE delle chat che il listener processerà, per la GUI (B1).

    Per ogni `chat_id` in `allowed_chats(cfg)` ritorna `{"chat_id", "name"}`: il nome è
    quello della `source_chats` corrispondente (se presente), altrimenti "" (chat da
    `chat_id`/`parser_by_chat` senza voce sorgente → solo l'ID). Ordinata per nome
    (case-insensitive), poi per ID; le chat senza nome vanno in fondo. Solo
    presentazione: nessuna decisione di routing qui, l'allowlist resta `allowed_chats`."""
    names = {}
    for src in source_manager.source_chats(cfg):
        cid = str(src.get("chat_id", "") or "").strip()
        nm = str(src.get("name", "") or "").strip()
        if cid and nm:
            names[cid] = nm
    rows = [{"chat_id": cid, "name": names.get(cid, "")} for cid in allowed_chats(cfg)]
    # Prima le chat con nome (False ordina prima di True), per nome case-insensitive,
    # poi per chat_id; quelle senza nome finiscono in fondo, ordinate per ID.
    return sorted(rows, key=lambda r: (r["name"] == "", r["name"].lower(), r["chat_id"]))


def active_custom_parser(cfg: dict, chat: str, parsers_dir: str = None):
    """Parser custom da usare per `chat`, oppure None se la chat non è approvata
    o nessun parser è attivo. Usato sia dal router sia dal prefiltro live."""
    if not _chat_approved_for_custom(cfg, chat):
        return None
    return parser_manager.load_active(cfg, chat, parsers_dir)


def has_active_parser_config(cfg: dict) -> bool:
    """True se è configurato almeno un Parser Personalizzato: l'attivo globale
    (`active_parser`) oppure un override per-chat non vuoto (`parser_by_chat`).

    Con il parser automatico P.Bet disattivato (CP-09b), senza alcun parser
    configurato il bridge non processerebbe NESSUN segnale: `app._start` lo usa per
    avvisare l'operatore (un listener "connesso" che ignora tutto in silenzio sarebbe
    fuorviante, Codex P2)."""
    if parser_manager.active_parser_name(cfg):
        return True
    return any(str(v or "").strip() for v in parser_manager.parser_by_chat(cfg).values())


def should_process(cfg: dict, chat: str, text: str, parsers_dir: str = None) -> bool:
    """Decide se un messaggio live va instradato (PR-11). Logica pura e testabile,
    estratta dal listener Telegram. Con il parser automatico P.Bet disattivato
    (CP-09b) una chat viene processata SOLO se:

    - è ammessa (`is_chat_allowed`) → altrimenti mai (non si indebolisce il filtro chat);
    - è approvata per il custom **e** ha un parser **configurato** (nome non vuoto,
      globale o per-chat).

    Si guarda il NOME configurato (`resolve_parser_name`), non il caricamento: se il
    file è mancante/invalido la chat viene comunque processata, così `resolve_row`
    gira e LOGGA il fallimento (NO_PARSER) invece di far sparire i segnali in silenzio
    (Codex P2). Senza alcun parser configurato non c'è nulla da processare. Una chat
    ammessa ma senza parser custom NON viene più processata: prima la gestiva il parser
    hardcoded col prefiltro marker `P.Bet.`/📊, ora rimosso dal percorso live. (`text`
    non è più usato: la decisione non dipende dal contenuto.)"""
    if not is_chat_allowed(cfg, chat):
        return False
    if not _chat_approved_for_custom(cfg, chat):
        return False
    return bool(parser_manager.resolve_parser_name(cfg, chat))


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
        row = res.row
        # PR-24: per una chat che è una **sorgente attiva**, il provider della
        # sorgente (esplicito o PRE/LIVE) VINCE sull'eventuale Provider fisso del
        # parser custom — così il routing per-chat del Provider vale anche per i
        # formati custom. Per le chat non-sorgente il Provider del parser resta.
        if source_manager.source_for_chat(cfg, chat) is not None:
            row = dict(row)
            row["Provider"] = provider
        return RouteResult(row, validator.VALID, CUSTOM)

    # Nessun Parser Personalizzato caricato: il parser automatico P.Bet è DISATTIVATO
    # (CP-09b), quindi il messaggio è ignorato (riga non piazzabile, nessuna scrittura).
    # Distinguo i due casi per l'operatore (Codex P2): nessun parser configurato vs un
    # parser configurato ma con file mancante/invalido (selezione stantia) — quest'ultimo
    # va segnalato col nome, così non sparisce in silenzio.
    configured = parser_manager.resolve_parser_name(cfg, chat)
    detail = f"parser_non_caricabile:{configured}" if configured else "no_active_parser"
    return RouteResult(None, NO_PARSER, NO_PARSER, detail)
