"""Slice 5b «wiring» (epica multilingua #3): la pipeline consuma la lingua-fonte.

Verifica che `source_language` (5a) venga effettivamente PASSATA da:
- il percorso LIVE (`signal_router.resolve_row`),
- l'anteprima (`ParserBuilder.preview_rows`/`test_message`),
al filtro-lingua del dizionario nomi (5b store), con l'INVARIANTE DI PARITÀ live/preview:
la stessa config + parser + messaggio devono produrre la stessa riga in entrambi.

Esercita funzioni reali dell'intera catena, non mock. Fail-first: prima di questa slice la
lingua non veniva passata a `resolve_event_name`, quindi il filtro era inerte a runtime.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import name_mapping_store as nm
from xtrader_bridge import recognition, signal_router, validator
from xtrader_bridge.parser_builder import ParserBuilder


def _parser():
    return cp.CustomParserDef(
        name="LangMap", mode="NAME_ONLY",
        name_mapping_profiles=["P"], team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
            cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", fixed_value="BACK", required=True),
        ])


# Dizionario con le stesse due squadre in DUE lingue (EN e IT) per lo stesso alias provider.
_ROWS = [
    {"betfair": "Liverpool", "provider": "Reds", "entity_type": "team", "language": "EN"},
    {"betfair": "Liverpool IT", "provider": "Reds", "entity_type": "team", "language": "IT"},
    {"betfair": "Leeds", "provider": "Blues", "entity_type": "team", "language": "EN"},
    {"betfair": "Leeds IT", "provider": "Blues", "entity_type": "team", "language": "IT"},
]

_MSG = "Match: Reds v Blues\nQuota: 1,85\n"


def _cfg(source_language=""):
    return {"provider": "TG", "active_parser": "LangMap", "chat_id": "42",
            "recognition_mode": "NAME_ONLY", "source_language": source_language,
            "name_mappings": {"P": list(_ROWS)}}


def test_pipeline_source_language_filtra_mappatura_nomi():
    # Wiring diretto in `build_validated_row`: la lingua passata sceglie le righe di dizionario.
    profs = nm.entries_for_profiles(_cfg(), ["P"])
    r_en = pipe.build_validated_row(_parser(), _MSG, name_mapping_profiles=profs,
                                    source_language="EN")
    r_it = pipe.build_validated_row(_parser(), _MSG, name_mapping_profiles=profs,
                                    source_language="IT")
    assert r_en.placeable and r_en.row["EventName"] == "Liverpool - Leeds"
    assert r_it.placeable and r_it.row["EventName"] == "Liverpool IT - Leeds IT"


def test_signal_router_passa_source_language_effettiva(tmp_path):
    # LIVE: `resolve_row` calcola `effective_source_language(cfg, defn)` e la propaga → la riga
    # scritta usa il dizionario della lingua-fonte globale.
    cp.save_parser(_parser(), str(tmp_path))
    res_en = signal_router.resolve_row(_MSG, _cfg("EN"), chat_id="42", parsers_dir=str(tmp_path))
    res_it = signal_router.resolve_row(_MSG, _cfg("IT"), chat_id="42", parsers_dir=str(tmp_path))
    assert res_en.placeable and res_en.row["EventName"] == "Liverpool - Leeds"
    assert res_it.placeable and res_it.row["EventName"] == "Liverpool IT - Leeds IT"


def test_source_language_override_per_parser_vince_nel_live(tmp_path):
    # L'override per-parser (`defn.source_language`) vince sul globale, come a runtime.
    defn = _parser()
    defn.source_language = "IT"
    cp.save_parser(defn, str(tmp_path))
    # globale EN, ma il parser dichiara IT → deve vincere IT
    res = signal_router.resolve_row(_MSG, _cfg("EN"), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable and res.row["EventName"] == "Liverpool IT - Leeds IT"


def test_parita_live_preview_source_language(tmp_path):
    # INVARIANTE DI PARITÀ (il cuore della slice): la stessa config+parser+messaggio deve dare la
    # STESSA riga in live (`resolve_row`) e in anteprima (`preview_rows`), per ogni lingua-fonte.
    cp.save_parser(_parser(), str(tmp_path))
    for lang in ("EN", "IT", ""):
        cfg = _cfg(lang)
        defn = _parser()
        live = signal_router.resolve_row(_MSG, cfg, chat_id="42", parsers_dir=str(tmp_path))
        # anteprima: stessa risoluzione lingua + profili del runtime
        profs = nm.entries_for_profiles(cfg, ["P"])
        eff = recognition.effective_source_language(cfg, defn)
        preview = ParserBuilder(defn).preview_rows(
            _MSG, provider="TG", name_mapping_profiles=profs, source_language=eff)
        assert len(preview) == 1, lang
        # La parità è fra i DUE PERCORSI, non una promessa che ogni lingua produca una riga:
        # da PR-P (B21) la lingua-fonte assente su dizionario ambiguo fail-closa, e la parità
        # deve valere anche lì — anzi soprattutto lì, perché un'anteprima che mostra una riga
        # mentre il live la scarta (o viceversa) è il modo peggiore di sbagliare.
        assert live.placeable == preview[0].placeable, lang
        if live.placeable:
            assert live.row["EventName"] == preview[0].row["EventName"], lang
    # Le lingue dichiarate restano risolvibili: la guardia colpisce l'ambiguità, non il filtro.
    for lang in ("EN", "IT"):
        assert signal_router.resolve_row(
            _MSG, _cfg(lang), chat_id="42", parsers_dir=str(tmp_path)).placeable, lang


def test_retrocompat_dizionario_agnostico_live(tmp_path):
    # Un dizionario AGNOSTICO (nessuna lingua per riga, come i setup esistenti) continua a
    # risolvere anche con `source_language` impostata (nessuna regressione runtime).
    agn = [{"betfair": "Liverpool", "provider": "Reds", "entity_type": "team"},
           {"betfair": "Leeds", "provider": "Blues", "entity_type": "team"}]
    cfg = {"provider": "TG", "active_parser": "LangMap", "chat_id": "42",
           "recognition_mode": "NAME_ONLY", "source_language": "EN",
           "name_mappings": {"P": agn}}
    cp.save_parser(_parser(), str(tmp_path))
    res = signal_router.resolve_row(_MSG, cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable and res.row["EventName"] == "Liverpool - Leeds"


def _multi_parser():
    """Parser MultiSelection (#192): la BASE mappa l'EventName (una volta), ogni selezione
    genera una riga che eredita quell'EventName tradotto."""
    defn = cp.CustomParserDef(
        name="LangMulti", mode="NAME_ONLY",
        name_mapping_profiles=["P"], team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
            cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", fixed_value="BACK", required=True),
        ])
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name=s) for s in ("1 - 0", "2 - 1")]
    return defn


def test_multirow_source_language_propaga_a_tutte_le_righe():
    # Fable #24: la lingua-fonte deve propagarsi anche sul percorso MULTI-RIGA. La mappatura
    # EventName avviene sulla BASE (una volta) e ogni riga MultiSelection eredita l'EventName
    # tradotto → il filtro-lingua NON resta inerte sul multi (passthrough `**kwargs` di
    # `build_validated_rows` su base+retry + eredità base→derivate). Fail-first: se
    # `build_validated_rows` perdesse il kwarg su base/retry, EN/IT non filtrerebbero qui.
    profs = nm.entries_for_profiles(_cfg(), ["P"])
    for lang, exp in (("EN", "Liverpool - Leeds"), ("IT", "Liverpool IT - Leeds IT")):
        rows = pipe.build_validated_rows(_multi_parser(), _MSG, name_mapping_profiles=profs,
                                         source_language=lang)
        placeable = [r for r in rows if r.placeable]
        assert len(placeable) == 2, lang                       # due selezioni generate
        assert all(r.row["EventName"] == exp for r in placeable), lang   # lingua propagata a TUTTE
        assert {r.row["SelectionName"] for r in placeable} == {"1 - 0", "2 - 1"}, lang


def test_source_language_globale_malformata_fail_safe(tmp_path):
    # Fail-safe lato QUERY (GLM #24): una `source_language` globale MALFORMATA ("ENG"/"FR"/…)
    # normalizza a "" → nessun filtro, NON un filtro rotto che scarta tutto. Un valore sporco
    # dal chiamante non deve azzerare il matching e far perdere segnali validi.
    #
    # L'invariante è «malformata == assente», e da PR-P (B21) va verificata così invece che
    # cablando l'esito «Liverpool - Leeds»: quell'esito era il comportamento a ordine di
    # salvataggio, non la garanzia che questo test difende. Misurata sul dizionario DECIDIBILE
    # (una sola lingua) l'invariante è visibile in positivo — la riga si scrive — e su quello
    # ambiguo resta comunque un'uguaglianza fra i due percorsi, verificata sotto.
    cfg_dec = _cfg("")
    cfg_dec["name_mappings"] = {"P": [r for r in _ROWS if r["language"] == "EN"]}
    cp.save_parser(_parser(), str(tmp_path))
    for bad in ("ENG", "FR", "xx", "123"):
        sporca = dict(cfg_dec, source_language=bad)
        res = signal_router.resolve_row(_MSG, sporca, chat_id="42", parsers_dir=str(tmp_path))
        assert res.placeable and res.row["EventName"] == "Liverpool - Leeds", bad
    # stesso fail-safe a livello di pipeline: `source_language` malformata == nessun filtro
    profs = nm.entries_for_profiles(cfg_dec, ["P"])
    r = pipe.build_validated_row(_parser(), _MSG, name_mapping_profiles=profs,
                                 source_language="ENG")
    assert r.placeable and r.row["EventName"] == "Liverpool - Leeds"
    # E l'equivalenza vale anche dove «nessun filtro» significa fail-closed: una lingua
    # malformata non deve MAI comportarsi diversamente da una lingua assente.
    profs_amb = nm.entries_for_profiles(_cfg(), ["P"])
    assorted = [pipe.build_validated_row(_parser(), _MSG, name_mapping_profiles=profs_amb,
                                         source_language=lang).status
                for lang in ("", "ENG", "FR", "xx", "123")]
    assert len(set(assorted)) == 1, f"malformata != assente: {assorted}"


def test_source_language_none_su_dizionario_ambiguo_ora_fail_closed(tmp_path):
    # Prima di PR-P (B21) questo test si chiamava `..._comportamento_legacy` e pretendeva
    # «Liverpool - Leeds», cioè la riga EN — non perché fosse quella giusta, ma perché era la
    # PRIMA SALVATA. Con le righe invertite nel dizionario sarebbe uscita la squadra italiana,
    # sullo stesso messaggio: una traduzione decisa dall'ordine di salvataggio, non dal dato.
    #
    # Decisione del proprietario (fail-closed): senza `source_language` un dizionario che ha
    # due destinazioni per lo stesso alias NON viene risolto. Un segnale perso è visibile e si
    # corregge; una squadra sbagliata finisce nell'EventName, quindi nel mercato e nella
    # selezione su cui si scommette, e non si vede.
    cp.save_parser(_parser(), str(tmp_path))
    res = signal_router.resolve_row(_MSG, _cfg(""), chat_id="42", parsers_dir=str(tmp_path))
    assert not res.placeable
    assert res.status == "MAPPING_MISSING"
    # E l'esito non dipende più dall'ordine di salvataggio: è la proprietà che rende la
    # risoluzione una risoluzione invece di un sorteggio.
    cfg_invertita = _cfg("")
    cfg_invertita["name_mappings"] = {"P": list(reversed(_ROWS))}
    res2 = signal_router.resolve_row(_MSG, cfg_invertita, chat_id="42", parsers_dir=str(tmp_path))
    assert res2.status == res.status


def test_source_language_none_su_dizionario_DECIDIBILE_risolve_come_sempre(tmp_path):
    # Il rovescio, ed è la metà che protegge dal «non risolvo mai»: senza `source_language`, un
    # dizionario in cui l'alias ha UNA sola destinazione continua a tradurre esattamente come
    # prima, BetType canonicalizzato incluso. La guardia colpisce l'ambiguità, non il filtro
    # assente — è la garanzia che i parser esistenti senza lingua-fonte non smettono di funzionare.
    cfg = _cfg("")
    cfg["name_mappings"] = {"P": [r for r in _ROWS if r["language"] == "EN"]}
    cp.save_parser(_parser(), str(tmp_path))
    res = signal_router.resolve_row(_MSG, cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable and res.row["EventName"] == "Liverpool - Leeds"
    assert res.row["BetType"] == "PUNTA"          # BACK canonicalizzato (invariato)
    assert validator.is_valid(res.row, "NAME_ONLY")
