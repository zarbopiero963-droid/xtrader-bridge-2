"""Slice 5d (CHIUSURA epica multilingua #3): garanzia END-TO-END nomi + mercati insieme.

Contesto (risposte supporto Betting Toolkit/XTrader, ticket 06-07-2026).
- Col riconoscimento a NOMI i nomi di evento/mercato/selezione dipendono dalla LINGUA della
  fonte (e, "più a fondo", dall'exchange Betfair: BF fa piccole differenze tra i nomi
  dell'exchange IT e UK, e usa ID diversi tra exchange). È un'incoerenza DI Betfair, che
  "va verificata puntualmente e non dipende da" BT/XT.
- Struttura CSV, header, codici `MarketType` e BetType sono IDENTICI tra versioni/lingue.

Conseguenza per QUESTO bridge (Betfair Sync RIMOSSO, dizionario user-built a mano,
`id_resolver=None`): la disuniformità per-exchange si gestisce facendo costruire all'utente
il dizionario nomi/mercati con i nomi ESATTI della propria fonte/exchange, taggati con la
lingua-fonte. Il meccanismo è quello di 5a-5c; NON serve un asse "exchange" separato (sarebbe
complessità morta su un sottosistema rimosso, e non auto-popolabile senza la sync). Gli ID
diversi-per-exchange non toccano il CSV live perché l'arricchimento ID è staccato.

Questa slice NON cambia il codice runtime: BLOCCA con un test la garanzia che chiude l'epica
#3 — un UNICO segnale, con UNA sola lingua-fonte, filtra COERENTEMENTE sia il dizionario NOMI
(`EventName`) sia il dizionario MERCATI (`MarketType`/`SelectionName`). Prima esistevano test
separati per i nomi (5b) e per i mercati (5c), ma nessuno esercitava i due dizionari INSIEME
sullo stesso segnale: è la garanzia end-to-end mancante. Esercita funzioni reali dell'intera
catena (`signal_router.resolve_row`, `ParserBuilder.preview_rows`), non mock.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import name_mapping_store as nm
from xtrader_bridge import recognition, signal_router, validator
from xtrader_bridge.parser_builder import ParserBuilder


def _parser():
    # NAME_ONLY con ENTRAMBI i dizionari attivi: EventName dal dizionario NOMI (profilo "P"),
    # mercato/selezione dal dizionario MERCATI a frase (profilo "M"). La base porta un mercato
    # VALIDO ma DIVERSO da entrambi gli esiti del dizionario, così l'override mercato è sempre
    # visibile (prova che il dizionario è stato consultato).
    return cp.CustomParserDef(
        name="MultiLang", mode="NAME_ONLY",
        name_mapping_profiles=["P"], market_mapping_profiles=["M"], team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="FIRST_HALF_GOALS_15", required=True),
            cp.FieldRule(target="MarketName", fixed_value="1º tempo - Totale goal 1,5"),
            cp.FieldRule(target="SelectionName", fixed_value="Over 1,5 goal", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", fixed_value="BACK", required=True),
        ])


# Dizionario NOMI: le stesse due squadre in DUE lingue (EN e IT) per lo stesso alias provider.
_NAME_ROWS = [
    {"betfair": "Liverpool", "provider": "Reds", "entity_type": "team", "language": "EN"},
    {"betfair": "Liverpool IT", "provider": "Reds", "entity_type": "team", "language": "IT"},
    {"betfair": "Leeds", "provider": "Blues", "entity_type": "team", "language": "EN"},
    {"betfair": "Leeds IT", "provider": "Blues", "entity_type": "team", "language": "IT"},
]


def _mentry(language, market, selection):
    return {"start_after": "Mercato:", "end_before": "\n", "phrase": "gg",
            "market_type": "", "market_name": market, "selection_name": selection,
            "language": language}


# Dizionario MERCATI: stessa frase «gg» in DUE lingue → mercati DIVERSI.
_MARKET_ROWS = [
    _mentry("EN", "Entrambe le squadre a segno", "Sì"),
    _mentry("IT", "1º tempo - Totale goal 0,5", "Over 0,5 goal"),
]

_MSG = "Match: Reds v Blues\nMercato: gg\nQuota: 1,85\n"

# Esito atteso per lingua-fonte: (EventName tradotto, MarketType, SelectionName).
_EXPECTED = {
    "EN": ("Liverpool - Leeds", "BOTH_TEAMS_TO_SCORE", "Sì"),
    "IT": ("Liverpool IT - Leeds IT", "FIRST_HALF_GOALS_05", "Over 0,5 goal"),
}


def _cfg(source_language=""):
    return {"provider": "TG", "active_parser": "MultiLang", "chat_id": "42",
            "recognition_mode": "NAME_ONLY", "source_language": source_language,
            "name_mappings": {"P": list(_NAME_ROWS)},
            "market_mappings": {"M": list(_MARKET_ROWS)}}


def test_end_to_end_una_lingua_filtra_nomi_e_mercati():
    # Wiring diretto (`build_validated_row`): UNA lingua-fonte deve scegliere COERENTEMENTE la
    # voce del dizionario NOMI e quella del dizionario MERCATI nello STESSO segnale.
    name_profs = nm.entries_for_profiles(_cfg(), ["P"])
    mkt_profs = mms.entries_for_profiles(_cfg(), ["M"])
    for lang, (event, mtype, sel) in _EXPECTED.items():
        r = pipe.build_validated_row(
            _parser(), _MSG, name_mapping_profiles=name_profs,
            market_mapping_profiles=mkt_profs, source_language=lang)
        assert r.placeable, lang
        assert r.row["EventName"] == event, lang          # dizionario NOMI filtrato per lingua
        assert r.row["MarketType"] == mtype, lang          # dizionario MERCATI filtrato per lingua
        assert r.row["SelectionName"] == sel, lang


def test_end_to_end_lingua_sbagliata_non_contamina(tmp_path):
    # Isolamento: con lingua-fonte IT le voci SOLO-EN non devono contaminare né i nomi né i
    # mercati (e viceversa). Lo si prova mostrando che EN e IT danno righe interamente diverse
    # sullo stesso segnale — mai un mix (es. EventName IT con mercato EN).
    cp.save_parser(_parser(), str(tmp_path))
    res_en = signal_router.resolve_row(_MSG, _cfg("EN"), chat_id="42", parsers_dir=str(tmp_path))
    res_it = signal_router.resolve_row(_MSG, _cfg("IT"), chat_id="42", parsers_dir=str(tmp_path))
    for res, lang in ((res_en, "EN"), (res_it, "IT")):
        event, mtype, sel = _EXPECTED[lang]
        assert res.placeable, lang
        assert res.row["EventName"] == event, lang
        assert res.row["MarketType"] == mtype, lang
        assert res.row["SelectionName"] == sel, lang
    # nessun incrocio: gli esiti EN e IT sono interamente distinti
    assert res_en.row["EventName"] != res_it.row["EventName"]
    assert res_en.row["MarketType"] != res_it.row["MarketType"]


def test_end_to_end_parita_live_preview():
    # INVARIANTE DI PARITÀ end-to-end: stessa config+parser+messaggio → STESSA riga in live
    # (`resolve_row`) e anteprima (`preview_rows`), per ogni lingua-fonte, coi DUE dizionari
    # attivi insieme. Incluso il caso "" (agnostico): EN e IT matchano il mercato con tipi
    # DIVERSI → ambiguità → fail-closed IDENTICO in entrambi i percorsi.
    import tempfile
    with tempfile.TemporaryDirectory() as pdir:
        cp.save_parser(_parser(), pdir)
        for lang in ("EN", "IT", ""):
            cfg = _cfg(lang)
            defn = _parser()
            live = signal_router.resolve_row(_MSG, cfg, chat_id="42", parsers_dir=pdir)
            name_profs = nm.entries_for_profiles(cfg, ["P"])
            mkt_profs = mms.entries_for_profiles(cfg, ["M"])
            eff = recognition.effective_source_language(cfg, defn)
            preview = ParserBuilder(defn).preview_rows(
                _MSG, provider="TG", name_mapping_profiles=name_profs,
                market_mapping_profiles=mkt_profs, source_language=eff)
            assert len(preview) == 1, lang
            assert live.placeable == preview[0].placeable, lang     # parità sul verdetto
            if live.placeable:
                for col in ("EventName", "MarketType", "SelectionName"):
                    assert live.row[col] == preview[0].row[col], (lang, col)
            else:
                assert live.status == preview[0].status, lang       # parità anche sul fail-closed


def test_end_to_end_agnostico_fail_closed_su_ambiguita():
    # Con lingua-fonte "" (non dichiarata) e voci mercato in DUE lingue che matchano la stessa
    # frase con MarketType DIVERSI → ambiguità → riga SCARTATA (fail-closed, comportamento
    # storico pre-5c: il dizionario non tira a indovinare). Nomi risolti ma segnale non
    # piazzabile per il mercato ambiguo: nessun mercato inventato.
    name_profs = nm.entries_for_profiles(_cfg(), ["P"])
    mkt_profs = mms.entries_for_profiles(_cfg(), ["M"])
    r = pipe.build_validated_row(
        _parser(), _MSG, name_mapping_profiles=name_profs,
        market_mapping_profiles=mkt_profs, source_language="")
    assert not r.placeable
    assert r.status == "MARKET_MAPPING_MISSING"


def test_end_to_end_bettype_canonico_invariato(tmp_path):
    # La chiusura dell'epica non altera il contratto CSV: BetType grezzo `BACK` resta
    # canonicalizzato a `PUNTA` (slice #3-2) e la riga tradotta è valida NAME_ONLY.
    cp.save_parser(_parser(), str(tmp_path))
    res = signal_router.resolve_row(_MSG, _cfg("IT"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable
    assert res.row["BetType"] == "PUNTA"
    assert validator.is_valid(res.row, "NAME_ONLY")
