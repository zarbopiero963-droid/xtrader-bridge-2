"""Test della decisione di instradamento del listener Telegram (`telegram_dispatch.decide`).

Audit #108: la glue di `App._run_bot._handle` (filtro chat → chat-notifiche → freschezza →
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
    """Scorciatoia per decide() con NOW/MAX_AGE fissi e parametri di default."""
    return td.decide(route, chat, text, epoch, NOW, MAX_AGE)


def test_messaggio_stantio_ignorato():
    """Un messaggio oltre la finestra di freschezza → IGNORE_STALE."""
    assert _decide(ROUTE, "42", epoch=STALE) == td.IGNORE_STALE


def test_timestamp_mancante_e_fail_closed_stale():
    """msg.date assente (epoch None) → trattato come stantio (fail-closed, A4)."""
    # msg.date assente (epoch None) → trattato come stantio (fail-closed, audit A4).
    assert _decide(ROUTE, "42", epoch=None) == td.IGNORE_STALE


def test_config_viva_senza_filtro_chat_ignorato():
    """Config viva senza alcun criterio chat → IGNORE_NO_FILTER (fail-closed)."""
    # Nessun criterio chat (config azzerata a runtime) → fail-closed.
    assert _decide({}, "42") == td.IGNORE_NO_FILTER
    assert _decide({"chat_id": "", "parser_by_chat": {}, "source_chats": []}, "42") \
        == td.IGNORE_NO_FILTER


def test_chat_notifiche_separata_va_a_conferma():
    """La chat-notifiche XTrader, distinta dalle sorgenti, → CONFIRM (esiti)."""
    # La chat-notifiche XTrader (99), distinta dalle sorgenti, porta ESITI → CONFIRM.
    assert _decide(ROUTE, "99") == td.CONFIRM


def test_chat_notifiche_che_coincide_con_sorgente_e_conflitto():
    """notif-chat == sorgente ammessa → IGNORE_CONFLICT (ambigua, fail-closed)."""
    # notif-chat == sorgente ammessa → ambigua → fail-closed (né segnale né conferma).
    route = {"provider": "TG", "chat_id": "42", "active_parser": "P",
             "xtrader_notification_chat_id": "42"}
    assert _decide(route, "42") == td.IGNORE_CONFLICT


def test_chat_non_ammessa_non_pertinente():
    """Chat non configurata → IGNORE_NOT_RELEVANT (non scrive)."""
    # Chat diversa da quella configurata → non instradata (non scrive).
    assert _decide(ROUTE, "777") == td.IGNORE_NOT_RELEVANT


def test_chat_ammessa_senza_parser_custom_non_processa():
    """Chat ammessa ma senza parser custom → IGNORE_NOT_RELEVANT (CP-09b)."""
    # Chat ammessa ma senza parser custom configurato → niente processing live (CP-09b).
    route = {"provider": "TG", "chat_id": "42"}      # nessun active_parser
    assert _decide(route, "42") == td.IGNORE_NOT_RELEVANT


def test_chat_sorgente_ammessa_con_parser_va_a_process():
    """Chat ammessa + parser custom configurato → PROCESS."""
    # Chat ammessa + parser custom configurato → PROCESS (percorso di scrittura).
    assert _decide(ROUTE, "42") == td.PROCESS


def test_ordine_filtro_chat_prima_di_conferma_e_freschezza():
    """Il guard "nessun filtro" (fail-closed) precede conferma E freschezza (Codex #250).

    Se la config viva azzera tutti i filtri sorgente mentre resta una notif-chat, una
    conferma NON deve partire da uno stato prima fail-closed: l'instradamento conferma
    rimuoverebbe righe attive e svuoterebbe il CSV. Il guard `IGNORE_NO_FILTER` è quindi
    valutato per primo. Sull'ordine precedente questo caso (route vuota, notif-chat = "42",
    stantio) usciva come `IGNORE_STALE`; ora — fail-closed prima — esce come
    `IGNORE_NO_FILTER`. Entrambi ignorano: cambia solo l'etichetta, ma la difesa-in-profondità
    è più forte perché il no-filter precede anche il ramo conferma.
    """
    # Route senza alcun filtro chat, anche se la chat runtime coincide con una notif-chat:
    # il no-filter fail-closed vince su conferma e su freschezza.
    no_filter_notif = {"xtrader_notification_chat_id": "42"}
    assert _decide(no_filter_notif, "42", epoch=STALE) == td.IGNORE_NO_FILTER
    assert _decide(no_filter_notif, "42", epoch=FRESH) == td.IGNORE_NO_FILTER
    # Anche senza notif-chat, una route vuota resta IGNORE_NO_FILTER a prescindere dall'età.
    assert _decide({}, "42", epoch=STALE) == td.IGNORE_NO_FILTER


def test_conferma_xtrader_ritardata_non_filtrata_per_eta():
    # #53: una conferma XTrader sulla chat notifiche, anche RITARDATA (oltre max_age), deve
    # comunque andare a CONFIRM (rimuove il segnale attivo), non essere scartata come stantia.
    assert _decide(ROUTE, "99", epoch=STALE) == td.CONFIRM
    # una notif-chat che coincide con una sorgente resta CONFLICT anche se stantia.
    route = {"provider": "TG", "chat_id": "42", "active_parser": "P",
             "xtrader_notification_chat_id": "42"}
    assert _decide(route, "42", epoch=STALE) == td.IGNORE_CONFLICT
