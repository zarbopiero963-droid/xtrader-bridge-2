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


def test_should_process_riflette_chat_aggiunta_senza_riavvio(tmp_path):
    # Anche l'ammissione chat usa la config viva: una chat non ancora ammessa diventa
    # processabile appena la config (parser_by_chat) la include, senza riavvio.
    cp.save_parser(_mapping_parser(), str(tmp_path))
    base = _cfg(with_mappings=True)
    assert signal_router.should_process(base, "999", _MSG, parsers_dir=str(tmp_path)) is False
    live = dict(base, parser_by_chat={"999": "Map"})
    assert signal_router.should_process(live, "999", _MSG, parsers_dir=str(tmp_path)) is True
