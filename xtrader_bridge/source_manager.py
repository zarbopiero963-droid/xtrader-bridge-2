"""PR-12: gestione di più chat sorgente (multi-chat), logica pura e testabile.

Una **sorgente** è una chat/canale Telegram da cui il bridge accetta segnali, con
una sua identità:

    {"name": str, "chat_id": str, "enabled": bool, "provider": str, "mode": str}

- `mode` ∈ {PRE, LIVE}: pre-match o live. Determina il `Provider` di default
  (PRE → ``TG_PRE``, LIVE → ``TG_LIVE``) se non se ne imposta uno esplicito.
- `provider` esplicito (se valorizzato) ha la precedenza sul default della modalità.
- `enabled=False`: la sorgente è ignorata (non processata).

Questo modulo è **puro**: non tocca GUI, Telegram, CSV o config su disco. Espone
risoluzione (provider/sorgente per chat) e validazione (chat_id duplicato =
errore bloccante; nome duplicato = avviso). Il wiring nel listener/router live è
un passo successivo (come `parser_manager` CP-07 ha preceduto CP-09), così questa
parte resta interamente testabile headless e a rischio zero per il CSV.
"""

MODES = ("PRE", "LIVE")
DEFAULT_MODE = "PRE"
# Provider di default per modalità: DERIVATO da MODES (PRE → "TG_PRE", LIVE →
# "TG_LIVE"), così aggiungere/cambiare una modalità non può desincronizzare la
# mappa (fonte unica = MODES).
_MODE_PROVIDER = {m: "TG_" + m for m in MODES}


def is_valid_mode(mode) -> bool:
    """True se `mode` (case/spazi-insensibile) è una modalità ammessa. Fonte unica
    usata sia dalla normalizzazione runtime sia dalla validazione, per non divergere."""
    return str(mode or "").strip().upper() in MODES


def _as_bool(value) -> bool:
    """Coercizione robusta a bool (JSON può portare stringhe '0'/'false')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def normalize_mode(mode) -> str:
    """Normalizza la modalità a PRE/LIVE; valore mancante/ignoto → DEFAULT_MODE
    (coercizione difensiva a runtime; la validazione invece RIFIUTA un valore
    ignoto, vedi `validate_sources`)."""
    m = str(mode or "").strip().upper()
    return m if is_valid_mode(m) else DEFAULT_MODE


def _normalize_source(raw: dict) -> dict:
    """Porta una sorgente grezza alla forma canonica (tipi e default coerenti).

    `enabled` è True di default (una sorgente appena aggiunta è attiva); `chat_id`
    e `provider` sono rifilati; `mode` normalizzato a PRE/LIVE."""
    return {
        "name": str(raw.get("name", "") or "").strip(),
        "chat_id": str(raw.get("chat_id", "") or "").strip(),
        "enabled": _as_bool(raw.get("enabled", True)),
        "provider": str(raw.get("provider", "") or "").strip(),
        "mode": normalize_mode(raw.get("mode", "")),
    }


def source_chats(cfg: dict) -> list:
    """Elenco normalizzato delle sorgenti in config (le voci non-dict sono
    ignorate). Ritorna una COPIA: mutarla non altera la config."""
    out = []
    for raw in cfg.get("source_chats", []) or []:
        if isinstance(raw, dict):
            out.append(_normalize_source(raw))
    return out


def enabled_sources(cfg: dict) -> list:
    """Solo le sorgenti attive (`enabled=True`)."""
    return [s for s in source_chats(cfg) if s["enabled"]]


def enabled_chat_ids(cfg: dict) -> set:
    """Insieme dei `chat_id` delle sorgenti attive (esclusi quelli vuoti)."""
    return {s["chat_id"] for s in enabled_sources(cfg) if s["chat_id"]}


def source_for_chat(cfg: dict, chat_id: str):
    """La sorgente ATTIVA che gestisce `chat_id`, oppure None (chat non
    configurata o sorgente disattivata → ignorata)."""
    chat = str(chat_id or "").strip()
    if not chat:
        return None
    for s in enabled_sources(cfg):
        if s["chat_id"] == chat:
            return s
    return None


def provider_for_chat(cfg: dict, chat_id: str, default: str = "") -> str:
    """Provider da usare per `chat_id`:

    - provider esplicito della sorgente, se valorizzato;
    - altrimenti il default della modalità (PRE → ``TG_PRE``, LIVE → ``TG_LIVE``);
    - se non esiste una sorgente attiva per quella chat → `default` (il provider
      globale di config, per retro-compatibilità con il setup mono-chat)."""
    src = source_for_chat(cfg, chat_id)
    if src is None:
        return default
    if src["provider"]:
        return src["provider"]
    return _MODE_PROVIDER.get(src["mode"], default)


def validate_sources(raw_sources) -> list:
    """Errori **bloccanti** sulle sorgenti: `chat_id` mancante, `chat_id`
    duplicato (ogni chat una sola sorgente, altrimenti il provider sarebbe
    ambiguo), modalità non valida. Lista vuota = sorgenti valide."""
    errors = []
    seen_ids = set()
    for i, raw in enumerate(raw_sources or []):
        where = f"sorgente #{i + 1}"
        if not isinstance(raw, dict):
            errors.append(f"{where}: non è un oggetto.")
            continue
        chat = str(raw.get("chat_id", "") or "").strip()
        if not chat:
            errors.append(f"{where}: chat_id mancante.")
        elif chat in seen_ids:
            errors.append(
                f"{where}: chat_id duplicato {chat!r} (ogni chat una sola sorgente).")
        else:
            seen_ids.add(chat)
        raw_mode = str(raw.get("mode", "") or "").strip()
        # La validazione RIFIUTA una modalità ignota (a differenza di
        # normalize_mode che la coercizza a default): qui vogliamo avvisare l'utente.
        if raw_mode and not is_valid_mode(raw_mode):
            errors.append(
                f"{where}: modalità non valida {raw_mode!r}; ammesse {', '.join(MODES)}.")
    return errors


def duplicate_name_warnings(raw_sources) -> list:
    """Avvisi **non bloccanti**: nomi di sorgente duplicati (confondono l'utente,
    ma non compromettono il routing, che usa il `chat_id`)."""
    counts = {}
    for raw in raw_sources or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    return [
        f"Nome sorgente duplicato {name!r} ({n} volte): rinominane uno per distinguerle."
        for name, n in counts.items() if n > 1
    ]
