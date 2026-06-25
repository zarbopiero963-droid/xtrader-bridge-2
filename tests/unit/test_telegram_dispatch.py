"""Test della decisione di instradamento del listener Telegram (`telegram_dispatch.decide`).

Audit #108: la glue di `App._run_bot._handle` (freschezza → filtro chat → chat-notifiche →
should_process) era non testabile in CI. Qui se ne esercita la semantica headless, con i
moduli reali `signal_router`/`message_freshness`, su tutti gli esiti.
"""

from xtrader_bridge import telegram_dispatch as td

NOW = 1000.0
MAX_AGE = 90
FRESH = NOW                 # epoch = adesso → fresco
STALE = NOW - MAX_AGE - 1   # oltre la finestra → stantio

# Route con una sorgente (chat_id "42") e una chat-notifiche XTrader SEPARATA ("99"),
# più un parser custom globale così la chat sorgente è processabile.
ROUTE = {
    "provider": "TG",
    "chat_id": "42",
    "active_parser": "P",
    "xtrader_notification_chat_id": "99",
}


def _decide(route, chat, *, text="msg", epoch=FRESH):
    return td.decide(route, chat, text, epoch, NOW, MAX_AGE)


def test_messaggio_stantio_ignorato():
    assert _decide(ROUTE, "42", epoch=STALE) == td.IGNORE_STALE


def test_timestamp_mancante_e_fail_closed_stale():
    # msg.date assente (epoch None) → trattato come stantio (fail-closed, audit A4).
    assert _decide(ROUTE, "42", epoch=None) == td.IGNORE_STALE


def test_config_viva_senza_filtro_chat_ignorato():
    # Nessun criterio chat (config azzerata a runtime) → fail-closed.
    assert _decide({}, "42") == td.IGNORE_NO_FILTER
    assert _decide({"chat_id": "", "parser_by_chat": {}, "source_chats": []}, "42") \
        == td.IGNORE_NO_FILTER


def test_chat_notifiche_separata_va_a_conferma():
    # La chat-notifiche XTrader (99), distinta dalle sorgenti, porta ESITI → CONFIRM.
    assert _decide(ROUTE, "99") == td.CONFIRM


def test_chat_notifiche_che_coincide_con_sorgente_e_conflitto():
    # notif-chat == sorgente ammessa → ambigua → fail-closed (né segnale né conferma).
    route = {"provider": "TG", "chat_id": "42", "active_parser": "P",
             "xtrader_notification_chat_id": "42"}
    assert _decide(route, "42") == td.IGNORE_CONFLICT


def test_chat_non_ammessa_non_pertinente():
    # Chat diversa da quella configurata → non instradata (non scrive).
    assert _decide(ROUTE, "777") == td.IGNORE_NOT_RELEVANT


def test_chat_ammessa_senza_parser_custom_non_processa():
    # Chat ammessa ma senza parser custom configurato → niente processing live (CP-09b).
    route = {"provider": "TG", "chat_id": "42"}      # nessun active_parser
    assert _decide(route, "42") == td.IGNORE_NOT_RELEVANT


def test_chat_sorgente_ammessa_con_parser_va_a_process():
    # Chat ammessa + parser custom configurato → PROCESS (percorso di scrittura).
    assert _decide(ROUTE, "42") == td.PROCESS


def test_ordine_freschezza_prima_del_filtro_chat():
    # Un messaggio stantio è ignorato PRIMA di valutare il filtro chat: anche con config
    # senza filtro, lo stale vince (stesso ordine di _handle).
    assert _decide({}, "42", epoch=STALE) == td.IGNORE_STALE
