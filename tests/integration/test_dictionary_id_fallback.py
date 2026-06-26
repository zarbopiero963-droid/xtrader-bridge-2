"""Integrazione PR-P12: arricchimento ID dal dizionario Betfair + fallback nomi.

Verifica end-to-end che — dopo parser + mappature a nomi — la riga venga arricchita con
EventId/MarketId/SelectionId quando il dizionario locale trova un match univoco, e che
resti a NOMI (fallback, segnale comunque piazzabile) quando non trova nulla o il
risolutore fallisce. Niente blocco del flusso, nessuna scommessa piazzata (solo CSV).
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import signal_router, validator
from xtrader_bridge.csv_writer import CSV_HEADER
from xtrader_bridge.betfair.dictionary_resolver import DictionaryResolver
from xtrader_bridge.betfair.local_db import BetfairLocalDB


_MSG = "Match: Inter - Milan\nMerc: MATCH_ODDS\nSel: Inter\nQuota: 1,85\nLato: BACK"


def _parser(sport="Calcio"):
    """Parser NAME_ONLY che estrae direttamente nomi canonici (niente name-mapping qui:
    isoliamo l'arricchimento ID)."""
    return cp.CustomParserDef(
        name="P", mode="NAME_ONLY", sport=sport,
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", start_after="Merc:", end_before="\n", required=True),
            cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ])


class _FakeResolver:
    def __init__(self, ids=None, boom=False):
        self._ids = ids or {}
        self._boom = boom
        self.calls = []

    def resolve_ids(self, **kw):
        self.calls.append(kw)
        if self._boom:
            raise RuntimeError("DB locked")
        return dict(self._ids)


def test_pipeline_arricchisce_id_quando_dizionario_trova():
    res = _FakeResolver({"EventId": "ev1", "MarketId": "mk1", "SelectionId": "s1"})
    out = pipe.build_validated_row(_parser(), _MSG, id_resolver=res)
    assert out.placeable is True
    assert out.row["EventId"] == "ev1"
    assert out.row["MarketId"] == "mk1"
    assert out.row["SelectionId"] == "s1"
    # il risolutore ha ricevuto i nomi canonici e lo sport del parser.
    assert res.calls[0]["sport"] == "Calcio"
    assert res.calls[0]["event_name"] == "Inter - Milan"


def test_pipeline_fallback_nomi_quando_dizionario_non_trova():
    res = _FakeResolver({})                      # nessun match
    out = pipe.build_validated_row(_parser(), _MSG, id_resolver=res)
    assert out.placeable is True                 # NON bloccato: fallback a nomi
    assert out.row["EventId"] == "" and out.row["MarketId"] == "" and out.row["SelectionId"] == ""
    assert out.row["EventName"] == "Inter - Milan"   # resta a nomi


def test_pipeline_resolver_che_solleva_non_blocca():
    res = _FakeResolver(boom=True)               # errore di lettura
    out = pipe.build_validated_row(_parser(), _MSG, id_resolver=res)
    assert out.placeable is True                 # fail-open: il flusso non si blocca
    assert out.row["MarketId"] == ""


def test_pipeline_senza_sport_non_chiama_il_resolver():
    res = _FakeResolver({"EventId": "x"})
    out = pipe.build_validated_row(_parser(sport=""), _MSG, id_resolver=res)
    assert out.placeable is True
    assert res.calls == []                        # parser agnostico → nessun arricchimento
    assert out.row["EventId"] == ""


def _seed_db():
    d = BetfairLocalDB(":memory:")
    m = d.new_sync_marker()
    d.upsert_event("ev_im", "1", "c1", "Inter v Milan",
                   participant_1="Inter", participant_2="Milan", seen_at=m)
    d.upsert_market("mk_im", "ev_im", "1", "Match Odds", "MATCH_ODDS", seen_at=m)
    d.upsert_selection("mk_im", "sel_inter", "Inter", seen_at=m)
    return d


def _cfg(parser_name):
    return {"chat_id": "42", "provider": "TG_CUSTOM", "active_parser": parser_name,
            "recognition_mode": "NAME_ONLY"}


def test_end_to_end_signal_router_arricchisce_id(tmp_path):
    # Parser salvato su disco + dizionario reale in memoria → resolve_row riempie gli ID.
    defn = _parser()
    defn.name = "P12"
    cp.save_parser(defn, str(tmp_path))
    db = _seed_db()
    try:
        result = signal_router.resolve_row(
            _MSG, _cfg("P12"), chat_id="42", parsers_dir=str(tmp_path),
            id_resolver=DictionaryResolver(db))
        assert result.placeable is True
        assert list(result.row.keys()) == CSV_HEADER
        assert result.row["EventId"] == "ev_im"
        assert result.row["MarketId"] == "mk_im"
        assert result.row["SelectionId"] == "sel_inter"
        assert result.row["EventName"] == "Inter - Milan"   # nomi conservati accanto agli ID
    finally:
        db.close()


def test_end_to_end_signal_router_fallback_nomi_se_dizionario_vuoto(tmp_path):
    defn = _parser()
    defn.name = "P12b"
    cp.save_parser(defn, str(tmp_path))
    db = BetfairLocalDB(":memory:")              # dizionario vuoto → nessun match
    try:
        result = signal_router.resolve_row(
            _MSG, _cfg("P12b"), chat_id="42", parsers_dir=str(tmp_path),
            id_resolver=DictionaryResolver(db))
        assert result.placeable is True          # fallback nomi: segnale comunque valido
        assert result.row["EventId"] == "" and result.row["MarketId"] == ""
        assert result.row["EventName"] == "Inter - Milan"
        assert result.status == validator.VALID
    finally:
        db.close()


def _parser_with_fixed_marketid(market_id="PARSER_MK"):
    """Parser BOTH che fornisce ESPLICITAMENTE un MarketId (modalità ID/BOTH)."""
    return cp.CustomParserDef(
        name="Pid", mode="BOTH", sport="Calcio",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", start_after="Merc:", end_before="\n", required=True),
            cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
            cp.FieldRule(target="MarketId", fixed_value=market_id),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ])


def test_id_parser_in_conflitto_non_sovrascritto():
    # Il dizionario propone un MarketId DIVERSO da quello del parser: l'arricchimento si
    # annulla del tutto, il MarketId esplicito del parser resta, e gli altri ID NON sono
    # riempiti con una tripla incoerente (Codex P1).
    res = _FakeResolver({"EventId": "evX", "MarketId": "DICT_MK", "SelectionId": "sX"})
    out = pipe.build_validated_row(_parser_with_fixed_marketid("PARSER_MK"), _MSG, id_resolver=res)
    assert out.placeable is True
    assert out.row["MarketId"] == "PARSER_MK"        # NON sovrascritto
    assert out.row["EventId"] == "" and out.row["SelectionId"] == ""   # tripla incoerente scartata


def test_id_parser_coerente_riempie_solo_i_vuoti():
    # Nessun conflitto (il MarketId del parser coincide con quello del dizionario): si
    # riempiono SOLO i campi ID vuoti (EventId/SelectionId), il MarketId del parser resta.
    res = _FakeResolver({"EventId": "ev1", "MarketId": "PARSER_MK", "SelectionId": "s1"})
    out = pipe.build_validated_row(_parser_with_fixed_marketid("PARSER_MK"), _MSG, id_resolver=res)
    assert out.row["MarketId"] == "PARSER_MK"
    assert out.row["EventId"] == "ev1" and out.row["SelectionId"] == "s1"
