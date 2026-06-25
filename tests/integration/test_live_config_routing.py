"""Integrazione: live-reload del routing (issue #82).

Il listener in esecuzione passa la config VIVA (`self._config`) a
`signal_router.resolve_row`/`should_process`, non più lo snapshot catturato a START.
Questo test dimostra il **meccanismo** a livello di routing (la parte che l'app ora
alimenta con la config aggiornata): la stessa `resolve_row`, con una config in cui il
profilo di mappatura è stato aggiunto/aggiornato, risolve l'`EventName` che con la
config precedente dava `MAPPING_MISSING` — senza bisogno di riavviare.

La glue dentro `app._handle/_process` non è testabile in CI (richiede `customtkinter`):
va verificata a mano su Windows. Qui si verifica l'invariante su cui poggia.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline, signal_router, validator


def _mapping_parser(name="Map"):
    return cp.CustomParserDef(
        name=name, mode="NAME_ONLY",
        name_mapping_profiles=["Premier"], team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
            cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ])


_MSG = "Match: Liverpool FC v Leeds Utd\nSel: Sì\nQuota: 1,85\nLato: BACK"


def _cfg(with_mappings):
    cfg = {"provider": "TG", "active_parser": "Map", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    if with_mappings:
        cfg["name_mappings"] = {"Premier": [
            {"betfair": "Liverpool", "provider": "Liverpool FC"},
            {"betfair": "Leeds", "provider": "Leeds Utd"},
        ]}
    return cfg


def test_routing_riflette_mappatura_aggiunta_senza_riavvio(tmp_path):
    cp.save_parser(_mapping_parser(), str(tmp_path))

    # Config "vecchia" (snapshot a START): il profilo non esiste ancora → fail-closed.
    old = signal_router.resolve_row(_MSG, _cfg(with_mappings=False),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert old.placeable is False
    assert old.status == custom_pipeline.MAPPING_MISSING

    # Config "viva" (l'utente ha riempito il Dizionario nomi mentre il bridge gira):
    # passando la config aggiornata, la stessa resolve_row ora traduce l'EventName.
    new = signal_router.resolve_row(_MSG, _cfg(with_mappings=True),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert new.placeable is True
    assert new.status == validator.VALID
    assert new.row["EventName"] == "Liverpool - Leeds"


def test_should_process_fail_closed_senza_filtro_chat(tmp_path):
    # Difesa-in-profondità (CodeRabbit): una config viva SENZA criterio chat
    # (chat_id/parser_by_chat/sources vuoti) ma con active_parser NON deve far processare
    # chat arbitrarie. `has_chat_filter` è False e `should_process` resta False: il listener
    # (oltre al guard esplicito in `app._handle`) non instrada nessuna chat non configurata.
    cp.save_parser(_mapping_parser(), str(tmp_path))
    no_filter = {"provider": "TG", "active_parser": "Map", "recognition_mode": "NAME_ONLY"}
    assert signal_router.has_chat_filter(no_filter) is False
    assert signal_router.should_process(no_filter, "12345", _MSG, parsers_dir=str(tmp_path)) is False


def test_is_notification_chat_dalla_config_viva():
    # audit C8: la chat-notifiche XTrader è letta dalla config VIVA come il routing.
    # Nessuna notif-chat configurata → nessuna chat è "di notifica".
    assert signal_router.is_notification_chat({"provider": "TG"}, "777") is False
    # Notif-chat configurata → solo quella chat (confronto stringa-vs-stringa).
    cfg = {"xtrader_notification_chat_id": "777"}
    assert signal_router.is_notification_chat(cfg, "777") is True
    assert signal_router.is_notification_chat(cfg, "778") is False
    # Live-reload: cambiando la notif-chat a runtime la decisione segue subito la config viva
    # (col vecchio snapshot a START un cambiamento veniva ignorato fino al riavvio).
    live = {"xtrader_notification_chat_id": "999"}
    assert signal_router.is_notification_chat(live, "777") is False
    assert signal_router.is_notification_chat(live, "999") is True
    # Vuoto/None robusti: niente notif-chat → mai (no falso positivo che dirotterebbe segnali).
    assert signal_router.is_notification_chat(cfg, "") is False
    assert signal_router.is_notification_chat({"xtrader_notification_chat_id": ""}, "999") is False
    # Whitespace simmetrico (Sourcery): ID configurato e chat runtime sono entrambi trimmati,
    # così un eventuale spazio (config a mano) non fa fallire un match logicamente valido.
    ws = {"xtrader_notification_chat_id": "  777  "}
    assert signal_router.is_notification_chat(ws, "777") is True
    assert signal_router.is_notification_chat(cfg, " 777 ") is True


def test_notif_chat_in_conflitto_con_sorgente_e_rilevabile(tmp_path):
    # Codex P2: con la config VIVA l'utente può salvare una notif-chat che COINCIDE con una
    # sorgente ammessa (a START `_start` rifiuta l'avvio). Il listener rileva l'ambiguità con
    # `is_notification_chat AND is_chat_allowed` e va FAIL-CLOSED: ignora il messaggio (né
    # segnale né conferma) con avviso, perché ogni interpretazione è pericolosa (bet mancata
    # o bet errata). Qui verifichiamo l'invariante su cui poggia la decisione del listener.
    cp.save_parser(_mapping_parser(), str(tmp_path))
    # Caso normale: notif-chat SEPARATA dalle sorgenti → notifica sì, sorgente no.
    ok = {"xtrader_notification_chat_id": "555", "chat_id": "42", "active_parser": "Map"}
    assert signal_router.is_notification_chat(ok, "555") is True
    assert signal_router.is_chat_allowed(ok, "555") is False        # non è una sorgente
    # Caso conflitto: notif-chat == una sorgente ammessa → ENTRAMBI True (ambiguo).
    clash = {"xtrader_notification_chat_id": "42", "chat_id": "42", "active_parser": "Map"}
    assert signal_router.is_notification_chat(clash, "42") is True
    assert signal_router.is_chat_allowed(clash, "42") is True       # il listener: FAIL-CLOSED (ignora)


def test_should_process_riflette_chat_aggiunta_senza_riavvio(tmp_path):
    # Anche l'ammissione chat usa la config viva: una chat non ancora ammessa diventa
    # processabile appena la config (parser_by_chat) la include, senza riavvio.
    cp.save_parser(_mapping_parser(), str(tmp_path))
    base = _cfg(with_mappings=True)
    assert signal_router.should_process(base, "999", _MSG, parsers_dir=str(tmp_path)) is False
    live = dict(base, parser_by_chat={"999": "Map"})
    assert signal_router.should_process(live, "999", _MSG, parsers_dir=str(tmp_path)) is True
