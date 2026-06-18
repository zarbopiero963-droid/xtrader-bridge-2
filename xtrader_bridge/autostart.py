"""Decisione dell'avvio automatico del listener (logica pura, testabile in CI).

All'apertura dell'app il listener parte da solo SOLO se `auto_start_listener` è
attivo **e** la configurazione minima per ricevere è presente (token + almeno una
chat ammessa). In **modalità reale** (non DRY_RUN) l'avvio automatico richiede una
conferma esplicita dell'utente: il bridge non deve mettersi a scrivere scommesse da
solo senza consenso. Qui solo la decisione; il dialog e l'avvio vivono in `app`.
"""

import math

from . import config_store, safety_guard


# Valori stringa che abilitano esplicitamente l'auto-start (fail-closed).
_TRUTHY = frozenset({"true", "1", "yes", "on", "si", "sì"})


def is_enabled(cfg: dict) -> bool:
    """`True` se l'avvio automatico è attivo in config (helper pubblico, così la GUI
    non deve reimplementare la coercizione né toccare interni).

    **Fail-closed** (Codex P2): essendo un toggle safety-critical con default OFF, si
    abilita SOLO su un valore esplicitamente affermativo (`True`, numero ≠ 0, o una
    stringa in `_TRUTHY`). Un valore malformato o sconosciuto (`None`/`null` da JSON,
    `"boh"`, …) NON deve far partire il listener da solo: vale come disattivato.
    NB: non si usa `config_store.as_bool` qui perché è fail-OPEN sulle stringhe
    sconosciute (sicuro per i toggle con default True, non per questo)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    val = cfg.get("auto_start_listener", False)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        # NaN/Infinity (da un config.json editato a mano) NON devono abilitare:
        # un numero non finito non è un "true" esplicito → fail-closed.
        return math.isfinite(val) and val != 0
    return str(val).strip().lower() in _TRUTHY


def _has_admitted_chat(cfg: dict) -> bool:
    """True se esiste almeno un criterio di ammissione chat (come al runtime): chat
    singola, override per-chat o sorgenti multiple (anche disattivate contano come
    'configurazione presente')."""
    if str(cfg.get("chat_id", "") or "").strip():
        return True
    if cfg.get("parser_by_chat"):
        return True
    if cfg.get("source_chats"):
        return True
    return False


def can_auto_start(cfg: dict) -> tuple:
    """`(True, "")` se l'avvio automatico è abilitato e la config minima c'è;
    altrimenti `(False, motivo)`. Le guardie evitano che l'app provi ad avviarsi da
    sola con un setup incompleto (token o chat mancanti)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    if not is_enabled(cfg):
        return False, "auto-start disattivato"
    if not str(cfg.get("bot_token", "") or "").strip():
        return False, "token Telegram mancante"
    if not _has_admitted_chat(cfg):
        return False, "nessuna chat configurata"
    return True, ""


def needs_real_mode_confirmation(cfg: dict) -> bool:
    """In modalità REALE (non DRY_RUN) l'avvio automatico va confermato a mano."""
    cfg = cfg if isinstance(cfg, dict) else {}
    return not safety_guard.is_dry_run(cfg)
