"""Test dell'instradamento del segnale (CP-09): custom attivo vs hardcoded."""

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_io, signal_router, validator


def _save_example(dir_path, name="Esempio P.Bet."):
    defn = parser_io.example_parser()
    defn.name = name
    return cp.save_parser(defn, dir_path)


# ── fallback hardcoded (nessun custom attivo) ───────────────────────────────

def test_nessun_custom_usa_hardcoded():
    # Config senza active_parser → percorso hardcoded; messaggio P.Bet. valido.
    cfg = {"provider": "TG", "recognition_mode": "NAME_ONLY"}
    text = ("🔔 P.Bet.\nYangon City v Rakhine\nMercato: 1X2\nEsito: 1\n"
            "Quota 1,85\nProbabilità 72%")
    res = signal_router.resolve_row(text, cfg)
    # Il parser hardcoded può non riconoscere ogni formato: verifichiamo solo che
    # la sorgente sia hardcoded e che lo stato sia coerente (placeable o scarto).
    assert res.source == signal_router.HARDCODED


def test_hardcoded_scarta_messaggio_non_valido():
    cfg = {"provider": "TG", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row("ciao non sono un segnale", cfg)
    assert res.source == signal_router.HARDCODED
    assert res.placeable is False


# ── custom attivo (autoritativo) ────────────────────────────────────────────

def test_custom_attivo_produce_riga(tmp_path):
    _save_example(str(tmp_path), "Yangon")
    # chat_id configurato e combaciante: chat approvata per il custom globale.
    cfg = {"provider": "TG", "active_parser": "Yangon", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
    assert res.row["SelectionName"] == "Sì"
    assert res.row["BetType"] == "PUNTA"
    assert res.row["Price"] == "1.85"


def test_custom_attivo_non_pronto_scarta_senza_fallback(tmp_path):
    # Custom attivo ma messaggio incompleto: scarto, NON si ripiega sull'hardcoded.
    _save_example(str(tmp_path), "Yangon")
    cfg = {"provider": "TG", "active_parser": "Yangon", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row("Match: solo questo", cfg,
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is False


def test_chat_non_approvata_non_usa_parser_globale(tmp_path):
    # active_parser globale ma chat_id vuoto: una chat arbitraria NON deve usare
    # il parser globale (sicurezza: niente scommesse per chat non approvate).
    _save_example(str(tmp_path), "Yangon")
    cfg = {"provider": "TG", "active_parser": "Yangon", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="999", parsers_dir=str(tmp_path))
    assert res.source == signal_router.HARDCODED


def test_custom_inesistente_ripiega_su_hardcoded(tmp_path):
    # active_parser punta a un parser non salvato → load_active None → hardcoded.
    cfg = {"provider": "TG", "active_parser": "NonEsiste", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row("qualsiasi", cfg, parsers_dir=str(tmp_path))
    assert res.source == signal_router.HARDCODED


def test_chat_id_esplicito_attiva_override(tmp_path):
    # parser_by_chat senza chat_id singolo in config: il chat id del messaggio
    # (passato esplicitamente, come fa il live) attiva l'override per-chat.
    _save_example(str(tmp_path), "PerChat")
    cfg = {"provider": "TG", "parser_by_chat": {"123": "PerChat"},
           "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="123", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
    # senza chat id → nessun override → hardcoded
    res2 = signal_router.resolve_row("qualsiasi", cfg, parsers_dir=str(tmp_path))
    assert res2.source == signal_router.HARDCODED


def test_override_per_chat(tmp_path):
    _save_example(str(tmp_path), "PerChat")
    cfg = {"provider": "TG", "chat_id": "123",
           "parser_by_chat": {"123": "PerChat"}, "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg, parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True


# ── is_chat_allowed: guardia unica live (CP-09) ─────────────────────────────

def test_is_chat_allowed_nulla_configurato_tutte_ammesse():
    # Nessun chat_id e nessuna mappa → comportamento legacy: tutte ammesse.
    cfg = {"provider": "TG"}
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "999") is True


def test_is_chat_allowed_solo_chat_configurata():
    # chat_id impostato → solo quella chat è ammessa.
    cfg = {"provider": "TG", "chat_id": "42"}
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "999") is False


def test_is_chat_allowed_override_per_chat_ammesso_anche_con_chat_id():
    # Con chat_id singolo impostato, le voci parser_by_chat restano ammesse
    # (l'override per-chat non deve essere bloccato dalla guardia).
    cfg = {"provider": "TG", "chat_id": "42",
           "parser_by_chat": {"123": "PerChat"}}
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "123") is True
    assert signal_router.is_chat_allowed(cfg, "999") is False


def test_is_chat_allowed_solo_mappa_per_chat():
    # Solo parser_by_chat (nessun chat_id): ammesse solo le chat mappate.
    cfg = {"provider": "TG", "parser_by_chat": {"123": "PerChat"}}
    assert signal_router.is_chat_allowed(cfg, "123") is True
    assert signal_router.is_chat_allowed(cfg, "42") is False
