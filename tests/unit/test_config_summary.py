"""Riepilogo READ-ONLY della configurazione (#293 slice 3) — logica pura.

Esercita `config_summary.summarize_config`/`summarize_channel` con funzioni/costanti REALI
del progetto: modalità Simulazione/REALE, passthrough stato Betfair, e «Pronto?» SEVERO per
canale (parser che si carica + traduzioni risolte, fail-closed sui profili fantasma ⚠).
Nessuna GUI, nessuna rete: i parser sono file veri in una tmp_path, le mappature usano gli
store reali.
"""

from xtrader_bridge import config_summary as cs
from xtrader_bridge import custom_parser as cp
from xtrader_bridge import market_mapping_store, name_mapping_store


def _save_parser(name, dir_path, *, names=None, markets=None):
    """Parser valido minimo (una regola Price obbligatoria) con eventuali profili di
    mappatura nomi/mercati selezionati."""
    defn = cp.CustomParserDef(
        name=name, rules=[cp.FieldRule(target="Price", required=True)],
        name_mapping_profiles=list(names or []),
        market_mapping_profiles=list(markets or []))
    return cp.save_parser(defn, str(dir_path))


def _with_name_profile(cfg, name):
    return name_mapping_store.set_entries(
        cfg, name, [{"betfair": "Milan", "provider": "AC Milan", "sport": "Calcio"}])


def _with_market_profile(cfg, name):
    return market_mapping_store.set_entries(
        cfg, name, [{"phrase": "goal", "market_name": "Over", "selection_name": "Yes"}])


# ── modalità e stato Betfair ─────────────────────────────────────────────────

def test_mode_reale_vs_simulazione():
    assert cs.summarize_config({"dry_run": False}).real_mode is True
    assert cs.summarize_config({"dry_run": True}).real_mode is False
    # Default sicuro: chiave assente → simulazione (non reale).
    assert cs.summarize_config({}).real_mode is False


def test_betfair_flags_passthrough():
    s = cs.summarize_config({}, betfair_synced=True, betfair_logged_in=False)
    assert s.betfair_synced is True and s.betfair_logged_in is False
    s2 = cs.summarize_config({})            # default: nessuno stato Betfair
    assert s2.betfair_synced is False and s2.betfair_logged_in is False


# ── «Pronto?» severo per canale ──────────────────────────────────────────────

def test_canale_pronto(tmp_path):
    _save_parser("P1", tmp_path)
    cfg = {"active_parser": "P1",
           "source_chats": [{"name": "Canale A", "chat_id": "100", "enabled": True}]}
    s = cs.summarize_config(cfg, parsers_dir=str(tmp_path))
    assert s.total_channels == 1 and s.ready_channels == 1
    ch = s.channels[0]
    assert ch.ready is True and ch.reason == ""
    assert ch.parser_name == "P1" and ch.parser_loaded is True
    assert ch.name == "Canale A" and ch.chat_id == "100"


def test_canale_disattivato_non_pronto(tmp_path):
    _save_parser("P1", tmp_path)
    cfg = {"active_parser": "P1",
           "source_chats": [{"name": "Spenta", "chat_id": "100", "enabled": False}]}
    ch = cs.summarize_config(cfg, parsers_dir=str(tmp_path)).channels[0]
    assert ch.ready is False and ch.reason == cs.REASON_DISABLED


def test_canale_senza_parser_non_pronto(tmp_path):
    cfg = {"source_chats": [{"name": "A", "chat_id": "100", "enabled": True}]}
    ch = cs.summarize_config(cfg, parsers_dir=str(tmp_path)).channels[0]
    assert ch.ready is False and ch.reason == cs.REASON_NO_PARSER
    assert ch.parser_name == "" and ch.parser_loaded is False


def test_canale_senza_chat_id_non_pronto(tmp_path):
    # Una sorgente con chat_id mancante non è ascoltabile: fail-closed, non «Pronto».
    cfg = {"active_parser": "P1",
           "source_chats": [{"name": "SenzaId", "chat_id": "", "enabled": True}]}
    ch = cs.summarize_config(cfg, parsers_dir=str(tmp_path)).channels[0]
    assert ch.ready is False and ch.reason == cs.REASON_NO_CHAT_ID


def test_parser_non_caricabile_non_pronto(tmp_path):
    # active_parser punta a un nome che NON ha un file valido → non caricabile (fail-closed),
    # col nome nel motivo per non far sparire il problema in silenzio.
    cfg = {"active_parser": "Fantasma",
           "source_chats": [{"name": "A", "chat_id": "100", "enabled": True}]}
    ch = cs.summarize_config(cfg, parsers_dir=str(tmp_path)).channels[0]
    assert ch.ready is False
    assert ch.reason == f"{cs.REASON_PARSER_UNLOADABLE}: Fantasma"
    assert ch.parser_name == "Fantasma" and ch.parser_loaded is False


# ── traduzioni risolte vs fantasma ⚠ ─────────────────────────────────────────

def test_traduzioni_risolte_pronto(tmp_path):
    _save_parser("P1", tmp_path, names=["Nomi1"], markets=["Mkt1"])
    cfg = {"active_parser": "P1",
           "source_chats": [{"name": "A", "chat_id": "100", "enabled": True}]}
    cfg = _with_name_profile(cfg, "Nomi1")
    cfg = _with_market_profile(cfg, "Mkt1")
    ch = cs.summarize_config(cfg, parsers_dir=str(tmp_path)).channels[0]
    assert ch.ready is True and ch.reason == ""
    assert ch.names.count == 1 and ch.names.resolved == ("Nomi1",) and ch.names.missing == ()
    assert ch.markets.count == 1 and ch.markets.resolved == ("Mkt1",)


def test_traduzione_fantasma_non_pronto(tmp_path):
    # Il parser seleziona un profilo nomi che NON esiste nello store (⚠ fantasma):
    # non è una traduzione attiva e rende il canale non pronto (fail-closed).
    _save_parser("P1", tmp_path, names=["Ghost"])
    cfg = {"active_parser": "P1",
           "source_chats": [{"name": "A", "chat_id": "100", "enabled": True}]}
    ch = cs.summarize_config(cfg, parsers_dir=str(tmp_path)).channels[0]
    assert ch.ready is False
    assert ch.reason == f"{cs.REASON_MISSING_TRANSLATION}: Ghost"
    assert ch.names.count == 0 and ch.names.missing == ("Ghost",)


def test_fantasma_mercato_conta_nel_motivo(tmp_path):
    # Simmetrico: un profilo MERCATI fantasma abbassa comunque lo stato a non-pronto.
    _save_parser("P1", tmp_path, names=["Nomi1"], markets=["GhostM"])
    cfg = {"active_parser": "P1",
           "source_chats": [{"name": "A", "chat_id": "100", "enabled": True}]}
    cfg = _with_name_profile(cfg, "Nomi1")
    ch = cs.summarize_config(cfg, parsers_dir=str(tmp_path)).channels[0]
    assert ch.ready is False
    assert ch.reason == f"{cs.REASON_MISSING_TRANSLATION}: GhostM"
    assert ch.markets.missing == ("GhostM",) and ch.names.count == 1


# ── enumerazione canali / conteggi / immutabilità ────────────────────────────

def test_canale_da_parser_by_chat_senza_sorgente(tmp_path):
    # Una chat ammessa via parser_by_chat ma senza voce source_chats appare come canale
    # extra (nome vuoto, solo id), e usa il suo override per-chat.
    _save_parser("PerChat", tmp_path)
    cfg = {"parser_by_chat": {"777": "PerChat"}}
    s = cs.summarize_config(cfg, parsers_dir=str(tmp_path))
    assert [c.chat_id for c in s.channels] == ["777"]
    ch = s.channels[0]
    assert ch.name == "" and ch.parser_name == "PerChat" and ch.ready is True


def test_ordine_e_conteggi(tmp_path):
    _save_parser("P1", tmp_path)
    cfg = {"active_parser": "P1",
           "source_chats": [
               {"name": "B", "chat_id": "200", "enabled": True},
               {"name": "A", "chat_id": "100", "enabled": False}],
           "parser_by_chat": {"900": "P1"}}
    s = cs.summarize_config(cfg, parsers_dir=str(tmp_path))
    # Sorgenti nell'ordine di config, poi gli extra (900) ordinati per id.
    assert [c.chat_id for c in s.channels] == ["200", "100", "900"]
    assert s.total_channels == 3
    assert s.ready_channels == 2          # "200" e "900" pronti; "100" disattivata


def test_summarize_config_non_muta_cfg(tmp_path):
    # SOLA LETTURA: la funzione non deve mutare la config passata.
    _save_parser("P1", tmp_path, names=["Nomi1"])
    cfg = {"active_parser": "P1", "dry_run": True,
           "source_chats": [{"name": "A", "chat_id": "100", "enabled": True}]}
    cfg = _with_name_profile(cfg, "Nomi1")
    import copy
    snapshot = copy.deepcopy(cfg)
    cs.summarize_config(cfg, betfair_synced=True, parsers_dir=str(tmp_path))
    assert cfg == snapshot
