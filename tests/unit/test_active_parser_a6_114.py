"""A6 audit #114 / #69 — «parser attivo» ×2 definizioni divergenti (quick-win).

L'assistente di configurazione (#41) valutava «c'è un parser attivo?» con il solo
`bool(cfg.get("active_parser"))` (attivo GLOBALE), mentre il **gate reale di START** e il
**pannello 🚦 Salute** (`app._live_health_items`) usano la fonte canonica
`signal_router.has_active_parser_config`, che conta anche gli **override per-chat** e le
**liste multi-parser**. Risultato (bug): con un parser configurato SOLO per-chat, il semaforo
reale diceva ATTIVO ma `get_health` / `get_setup_status` / il fallback `build_health_report`
dell'assistente dicevano «nessun parser» — un indicatore di sicurezza incoerente.

Questi test esercitano le funzioni REALI dell'assistente e falliscono sul vecchio codice
(narrow check) per una config con parser SOLO per-chat.
"""

import json

from xtrader_bridge import config_agent, health_check, signal_router

# Parser configurato SOLO per-chat (nessun `active_parser` globale): è il caso che il
# vecchio narrow-check `bool(cfg.get("active_parser"))` NON riconosceva.
_CFG_PER_CHAT = {"parser_by_chat": {"123456789": "MioParser"}, "csv_path": ""}


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


def test_precondizione_divergenza_narrow_vs_canonico():
    """Documenta la divergenza che il fix elimina: canonico=True, narrow=False."""
    assert signal_router.has_active_parser_config(_CFG_PER_CHAT) is True
    assert bool(_CFG_PER_CHAT.get("active_parser")) is False


def test_get_setup_status_parser_active_usa_fonte_canonica():
    """FAIL-FIRST: sul vecchio codice `requirements.parser_active` era False per un parser
    solo per-chat → checklist «manca il parser» pur essendo configurato (e lo START partirebbe)."""
    tools = config_agent.build_read_only_tools(config_loader=lambda: dict(_CFG_PER_CHAT))
    out = json.loads(_tool(tools, "get_setup_status").handler({}))
    assert out["requirements"]["parser_active"] is True, \
        "parser solo per-chat DEVE contare come «parser attivo» (fonte canonica del gate START)"


def test_get_health_parser_semaforo_coerente_col_reale():
    """Il semaforo «parser» di `get_health` (assistente) deve coincidere con quello del
    pannello reale, che usa `has_active_parser_config`. Confronto contro l'atteso canonico."""
    tools = config_agent.build_read_only_tools(config_loader=lambda: dict(_CFG_PER_CHAT))
    items = json.loads(_tool(tools, "get_health").handler({}))
    parser_item = next(i for i in items if i["key"] == "parser")
    atteso = next(i for i in health_check.evaluate(parser_active=True) if i.key == "parser")
    assert parser_item["state"] == atteso.state, \
        "il semaforo parser dell'assistente deve dire ATTIVO come il pannello reale"


def test_build_health_report_fallback_coerente():
    """Il fallback `build_health_report` (usato quando manca un health_provider live) deve
    riflettere il parser per-chat come ATTIVO, non «nessun parser»."""
    rep = config_agent.build_health_report(dict(_CFG_PER_CHAT))
    parser_sem = next(s for s in rep["semafori"] if s["key"] == "parser")
    atteso = next(i for i in health_check.evaluate(parser_active=True) if i.key == "parser")
    assert parser_sem["state"] == atteso.state
