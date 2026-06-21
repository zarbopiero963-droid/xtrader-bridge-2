"""CP-07: gestione del Parser Personalizzato attivo.

Decide QUALE parser usare, leggendo la config:
- `active_parser`: nome del parser attivo di default ("" = usa il parser hardcoded);
- `parser_by_chat`: override per chat sorgente `{chat_id: nome}` (forward-compatibile
  col multi-chat; con la singola chat attuale funziona comunque).

Funzioni pure su `dict` di config + caricamento dei parser salvati (CP-01). NON
scrive il CSV e NON tocca il runtime/GUI: la sostituzione del parser hardcoded
nel flusso live è CP-09.
"""

from . import custom_parser


def active_parser_name(cfg: dict) -> str:
    return str((cfg or {}).get("active_parser", "") or "").strip()


def parser_by_chat(cfg: dict) -> dict:
    value = (cfg or {}).get("parser_by_chat", {})
    if not isinstance(value, dict):
        return {}
    # Chiavi normalizzate a str ALLA FONTE: i chat_id arrivano come stringhe nel live e
    # tutti i consumatori (is_chat_allowed/allowed_chats, _chat_approved_for_custom,
    # resolve_parser_name) confrontano `str(chat)`. Una chiave non-stringa (es. int da
    # config editata a mano) darebbe lookup incoerenti: la chat verrebbe ammessa ma il
    # parser per-chat non trovato (Codex P2). Normalizzare qui allinea tutti i percorsi.
    return {str(k): v for k, v in value.items()}


def resolve_parser_name(cfg: dict, chat_id: str = "") -> str:
    """Nome del parser da usare per `chat_id`: prima l'override per chat, poi
    l'attivo globale. "" = nessuno (→ parser hardcoded)."""
    chat_key = str(chat_id or "").strip()
    if chat_key:
        override = str(parser_by_chat(cfg).get(chat_key, "") or "").strip()
        if override:
            return override
    return active_parser_name(cfg)


def set_active(cfg: dict, name: str) -> dict:
    """Ritorna una COPIA della config con il parser attivo impostato."""
    out = dict(cfg or {})
    out["active_parser"] = str(name or "").strip()
    out["parser_by_chat"] = parser_by_chat(out)  # copia: non condividere la mappa
    return out


def set_for_chat(cfg: dict, chat_id: str, name: str) -> dict:
    """Ritorna una copia della config con l'override per la chat impostato
    (nome vuoto → rimuove l'override)."""
    out = dict(cfg or {})
    mapping = parser_by_chat(out)
    chat_key = str(chat_id or "").strip()
    clean = str(name or "").strip()
    if chat_key:
        if clean:
            mapping[chat_key] = clean
        else:
            mapping.pop(chat_key, None)
    out["parser_by_chat"] = mapping
    return out


def available_parser_names(dir_path: str = None) -> list:
    """Nomi dei parser salvati (dal campo `name`), per i menu di selezione.
    I file illeggibili vengono saltati."""
    import os
    names = []
    for path in custom_parser.list_parser_files(dir_path):
        try:
            defn = custom_parser.load_parser(path)
        except (OSError, ValueError):
            continue
        # Elenca solo i nomi che load_active() saprebbe ricaricare: il parser
        # dev'essere valido E il suo nome deve ri-mappare proprio a questo file
        # (un file rinominato a mano, es. Wrong.json con name "Shown", offrirebbe
        # altrimenti un nome che porta a un fallback silenzioso).
        if not custom_parser.is_valid(defn):
            continue
        if os.path.abspath(custom_parser.parser_path(defn.name, dir_path)) != os.path.abspath(path):
            continue
        names.append(defn.name)
    return sorted(names)


def load_active(cfg: dict, chat_id: str = "", dir_path: str = None):
    """Carica la definizione del parser attivo per `chat_id`, oppure None se
    nessun parser è selezionato o il file non esiste (→ il chiamante usa il
    parser hardcoded). Un file corrotto → None (fail-safe)."""
    name = resolve_parser_name(cfg, chat_id)
    if not name:
        return None
    path = custom_parser.parser_path(name, dir_path)
    try:
        defn = custom_parser.load_parser(path)
    except (OSError, ValueError):
        return None
    # Fail-closed (alimenta il live, CP-09):
    # - il file caricato deve essere PROPRIO il parser richiesto: nomi diversi che
    #   si sanitizzano allo stesso file (es. "A/B" → AB.json) non devono caricare
    #   il parser sbagliato;
    # - la definizione dev'essere valida (un file modificato a mano con, es.,
    #   BetType duplicato non deve raggiungere il CSV).
    if defn.name != name or not custom_parser.is_valid(defn):
        return None
    return defn
