"""Decisione dell'avvio automatico del listener (logica pura, testabile in CI).

All'apertura dell'app il listener parte da solo SOLO se `auto_start_listener` è
attivo **e** la configurazione minima per ricevere è presente (token + almeno una
chat ammessa). In **modalità reale** (non DRY_RUN) l'avvio automatico richiede una
conferma esplicita dell'utente: il bridge non deve mettersi a scrivere scommesse da
solo senza consenso. Qui solo la decisione; il dialog e l'avvio vivono in `app`.
"""

from . import safety_guard


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in ("", "0", "false", "no", "off")


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
    if not _as_bool(cfg.get("auto_start_listener", False)):
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
