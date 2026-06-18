"""Test della decisione di avvio automatico del listener (logica pura)."""

from xtrader_bridge import autostart


def _cfg(**over):
    cfg = {"auto_start_listener": True, "bot_token": "T", "chat_id": "42"}
    cfg.update(over)
    return cfg


def test_disattivato_di_default():
    ok, reason = autostart.can_auto_start({"bot_token": "T", "chat_id": "42"})
    assert ok is False and "disattivato" in reason


def test_fail_closed_su_valori_malformati():
    # Codex P2: un valore non esplicitamente affermativo NON deve abilitare l'auto-start
    # (toggle safety-critical, default OFF). null/None/"boh"/"" → disattivato.
    for bad in (None, "", "boh", "maybe", "2x", [], {},
                float("nan"), float("inf"), float("-inf")):
        assert autostart.is_enabled({"auto_start_listener": bad}) is False, bad
    # Solo valori esplicitamente veri abilitano.
    for good in (True, 1, "true", "True", "1", "yes", "on", "sì"):
        assert autostart.is_enabled({"auto_start_listener": good}) is True, good
    # E un valore malformato non rende avviabile il bridge.
    assert autostart.can_auto_start(_cfg(auto_start_listener=None))[0] is False


def test_avviabile_con_token_e_chat():
    ok, reason = autostart.can_auto_start(_cfg())
    assert ok is True and reason == ""


def test_non_avviabile_senza_token():
    ok, reason = autostart.can_auto_start(_cfg(bot_token=""))
    assert ok is False and "token" in reason


def test_non_avviabile_senza_chat():
    ok, reason = autostart.can_auto_start(_cfg(chat_id=""))
    assert ok is False and "chat" in reason


def test_chat_da_parser_by_chat_o_source_chats():
    assert autostart.can_auto_start(_cfg(chat_id="", parser_by_chat={"1": "P"}))[0] is True
    assert autostart.can_auto_start(_cfg(chat_id="", source_chats=[{"chat_id": "9"}]))[0] is True


def test_conferma_richiesta_solo_in_modalita_reale():
    # dry_run di default True → nessuna conferma; dry_run False (reale) → conferma.
    assert autostart.needs_real_mode_confirmation(_cfg()) is False          # dry_run assente → True → no conferma
    assert autostart.needs_real_mode_confirmation(_cfg(dry_run=True)) is False
    assert autostart.needs_real_mode_confirmation(_cfg(dry_run=False)) is True
