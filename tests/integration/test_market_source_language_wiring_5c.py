"""Slice 5c (epica multilingua #3): la pipeline filtra il DIZIONARIO MERCATI per lingua-fonte.

La 5b «wiring» ha reso `source_language` attiva sul dizionario NOMI (live+preview). Questa
slice la fa filtrare anche il dizionario MERCATI: `custom_pipeline.build_validated_row`
inoltra la stessa `source_language` a `market_mapping_store.resolve_market(..., language=)`.

Verifica che la lingua-fonte venga PASSATA da:
- il percorso LIVE (`signal_router.resolve_row`),
- l'anteprima (`ParserBuilder.preview_rows`),
al filtro-lingua del dizionario mercati, con l'INVARIANTE DI PARITÀ live/preview (stessa
config + parser + messaggio → stessa riga). Esercita funzioni reali dell'intera catena, non
mock. Fail-first: prima di 5c la lingua non arrivava a `resolve_market`, quindi il filtro era
inerte a runtime sui mercati.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import recognition, signal_router
from xtrader_bridge.parser_builder import ParserBuilder


def _parser():
    # NAME_ONLY, EventName da colonna (niente dizionario nomi qui: si isola il filtro MERCATI).
    # La base porta un mercato VALIDO ma DIVERSO da entrambi gli esiti del dizionario, così un
    # override del dizionario è sempre visibile (prova che è stato consultato).
    return cp.CustomParserDef(
        name="MktLang", mode="NAME_ONLY",
        market_mapping_profiles=["M"], team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="FIRST_HALF_GOALS_15", required=True),
            cp.FieldRule(target="MarketName", fixed_value="1º tempo - Totale goal 1,5"),
            cp.FieldRule(target="SelectionName", fixed_value="Over 1,5 goal", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", fixed_value="BACK", required=True),
        ])


def _mentry(language, market, selection):
    return {"start_after": "Mercato:", "end_before": "\n", "phrase": "gg",
            "market_type": "", "market_name": market, "selection_name": selection,
            "language": language}


# Stessa frase «gg» in DUE lingue → mercati DIVERSI: EN=BTTS, IT=1º tempo 0,5.
_ROWS = [
    _mentry("EN", "Entrambe le squadre a segno", "Sì"),
    _mentry("IT", "1º tempo - Totale goal 0,5", "Over 0,5 goal"),
]

_MSG = "Match: Inter v Milan\nMercato: gg\nQuota: 1,85\n"


def _cfg(source_language=""):
    return {"provider": "TG", "active_parser": "MktLang", "chat_id": "42",
            "recognition_mode": "NAME_ONLY", "source_language": source_language,
            "market_mappings": {"M": list(_ROWS)}}


def test_pipeline_source_language_filtra_dizionario_mercati():
    # Wiring diretto in `build_validated_row`: la lingua sceglie la voce mercato del dizionario.
    profs = mms.entries_for_profiles(_cfg(), ["M"])
    r_en = pipe.build_validated_row(_parser(), _MSG, market_mapping_profiles=profs,
                                    source_language="EN")
    r_it = pipe.build_validated_row(_parser(), _MSG, market_mapping_profiles=profs,
                                    source_language="IT")
    assert r_en.placeable and r_en.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert r_en.row["SelectionName"] == "Sì"
    assert r_it.placeable and r_it.row["MarketType"] == "FIRST_HALF_GOALS_05"
    assert r_it.row["SelectionName"] == "Over 0,5 goal"


def test_signal_router_passa_source_language_ai_mercati(tmp_path):
    # LIVE: `resolve_row` calcola `effective_source_language(cfg, defn)` e la propaga al
    # dizionario mercati → la riga scritta usa il mercato della lingua-fonte globale.
    cp.save_parser(_parser(), str(tmp_path))
    res_en = signal_router.resolve_row(_MSG, _cfg("EN"), chat_id="42", parsers_dir=str(tmp_path))
    res_it = signal_router.resolve_row(_MSG, _cfg("IT"), chat_id="42", parsers_dir=str(tmp_path))
    assert res_en.placeable and res_en.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"
    assert res_it.placeable and res_it.row["MarketType"] == "FIRST_HALF_GOALS_05"


def test_source_language_override_per_parser_vince_nel_live_mercati(tmp_path):
    # L'override per-parser (`defn.source_language`) vince sul globale anche per i mercati.
    defn = _parser()
    defn.source_language = "IT"
    cp.save_parser(defn, str(tmp_path))
    res = signal_router.resolve_row(_MSG, _cfg("EN"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable and res.row["MarketType"] == "FIRST_HALF_GOALS_05"


def test_parita_live_preview_source_language_mercati(tmp_path):
    # INVARIANTE DI PARITÀ: stessa config+parser+messaggio → STESSO esito in live
    # (`resolve_row`) e anteprima (`preview_rows`), per ogni lingua-fonte — INCLUSO il caso
    # fail-closed ("" → EN+IT ambigui → scartati in entrambi i percorsi).
    cp.save_parser(_parser(), str(tmp_path))
    for lang in ("EN", "IT", ""):
        cfg = _cfg(lang)
        defn = _parser()
        live = signal_router.resolve_row(_MSG, cfg, chat_id="42", parsers_dir=str(tmp_path))
        profs = mms.entries_for_profiles(cfg, ["M"])
        eff = recognition.effective_source_language(cfg, defn)
        preview = ParserBuilder(defn).preview_rows(
            _MSG, provider="TG", market_mapping_profiles=profs, source_language=eff)
        assert len(preview) == 1, lang
        assert live.placeable == preview[0].placeable, lang        # parità sul verdetto
        if live.placeable:
            assert live.row["MarketType"] == preview[0].row["MarketType"], lang
            assert live.row["SelectionName"] == preview[0].row["SelectionName"], lang
        else:
            assert live.status == preview[0].status, lang          # parità anche sul fail-closed


def test_retrocompat_dizionario_mercati_agnostico_live(tmp_path):
    # Un dizionario mercati AGNOSTICO (nessuna lingua per voce, come i setup esistenti) continua
    # a risolvere anche con `source_language` impostata (nessuna regressione runtime).
    agn = {"provider": "TG", "active_parser": "MktLang", "chat_id": "42",
           "recognition_mode": "NAME_ONLY", "source_language": "ES",
           "market_mappings": {"M": [_mentry("", "Entrambe le squadre a segno", "Sì")]}}
    cp.save_parser(_parser(), str(tmp_path))
    res = signal_router.resolve_row(_MSG, agn, chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable and res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"


def test_source_language_none_comportamento_legacy_mercati(tmp_path):
    # Senza `source_language` (""), il filtro mercati è inerte: EN e IT matchano la stessa frase
    # con mercati DIVERSI → ambiguità (fail-closed, D2) → riga SCARTATA (MARKET_MAPPING_MISSING),
    # esattamente il comportamento storico prima di 5c (il dizionario non tira a indovinare).
    cp.save_parser(_parser(), str(tmp_path))
    res = signal_router.resolve_row(_MSG, _cfg(""), chat_id="42", parsers_dir=str(tmp_path))
    assert not res.placeable and res.status == "MARKET_MAPPING_MISSING"


def test_source_language_globale_malformata_fail_safe_mercati(tmp_path):
    # Fail-safe lato query (GLM #24 per i nomi, stesso principio sui mercati): una
    # `source_language` globale MALFORMATA normalizza a "" → NESSUN filtro (non un filtro rotto
    # che scarta tutto). Prova distintiva: con un'UNICA voce EN, «no filtro» la applica
    # (placeable, dict vince → BTTS); un filtro-letterale rotto ("ENG") la scarterebbe (el=EN ≠
    # ENG → none → mercato base). Deve vincere il dizionario.
    cfg_en = {"provider": "TG", "active_parser": "MktLang", "chat_id": "42",
              "recognition_mode": "NAME_ONLY",
              "market_mappings": {"M": [_mentry("EN", "Entrambe le squadre a segno", "Sì")]}}
    cp.save_parser(_parser(), str(tmp_path))
    for bad in ("ENG", "FR", "xx"):
        cfg = dict(cfg_en, source_language=bad)
        res = signal_router.resolve_row(_MSG, cfg, chat_id="42", parsers_dir=str(tmp_path))
        assert res.placeable and res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE", bad


def test_source_language_override_per_parser_malformata_fail_safe_mercati(tmp_path):
    # Companion (Sourcery #26): un override PER-PARSER (`defn.source_language`) MALFORMATO deve
    # fail-safe come il globale — `effective_source_language` lo normalizza a "" e ricade sul
    # globale (qui vuoto) → nessun filtro. Con l'unica voce EN, «no filtro» la applica (dict
    # vince → BTTS); un override-letterale rotto la scarterebbe (el=EN ≠ "ENG" → none → base).
    cfg_en = {"provider": "TG", "active_parser": "MktLang", "chat_id": "42",
              "recognition_mode": "NAME_ONLY", "source_language": "",   # globale vuoto
              "market_mappings": {"M": [_mentry("EN", "Entrambe le squadre a segno", "Sì")]}}
    for bad in ("ENG", "fr", "xx"):
        defn = _parser()
        defn.source_language = bad                # override per-parser malformato
        cp.save_parser(defn, str(tmp_path))
        res = signal_router.resolve_row(_MSG, cfg_en, chat_id="42", parsers_dir=str(tmp_path))
        assert res.placeable and res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE", bad
