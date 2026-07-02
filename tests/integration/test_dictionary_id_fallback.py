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


# ── glue di app.py: _betfair_id_resolver best-effort (issue #178 §3) ──────────

def test_app_betfair_id_resolver_costruito_sul_db_del_motore():
    """`App._betfair_id_resolver` (chiamato come funzione unbound su un self minimale)
    ritorna un `DictionaryResolver` agganciato al DB del motore Betfair."""
    from xtrader_bridge.app import App

    db = BetfairLocalDB(":memory:")

    class _Engine:
        pass

    class _Self:
        def _betfair_sync_engine(self):
            eng = _Engine()
            eng.db = db
            return eng

    resolver = App._betfair_id_resolver(_Self())
    assert isinstance(resolver, DictionaryResolver)
    assert resolver.db is db
    db.close()


def test_app_betfair_id_resolver_fail_open_ritorna_none():
    """Se il dizionario non è disponibile (engine che solleva), il glue ritorna None
    → flusso live a NOMI (fallback), nessun crash, nessun blocco del segnale."""
    from xtrader_bridge.app import App

    class _Self:
        def _betfair_sync_engine(self):
            raise RuntimeError("DB locale non apribile (simulato)")

    assert App._betfair_id_resolver(_Self()) is None


# ── ID PER RIGA DERIVATA nelle righe multi (#192, follow-up review #290) ──────

class _PerSelectionResolver:
    """Resolver che ritorna una tripla ID DIVERSA per ciascuna `selection_name` (come il
    dizionario reale). Registra le chiamate per verificare che ogni riga risolva la SUA selezione."""

    def __init__(self, table):
        self.table = table          # selection_name → {EventId, MarketId, SelectionId}
        self.calls = []

    def resolve_ids(self, **kw):
        self.calls.append(kw)
        return dict(self.table.get(kw.get("selection_name", ""), {}))


def _multiselection_id_parser():
    """Parser ID_ONLY MultiSelection: la base fornisce evento+mercato (per nome, per la
    risoluzione), ogni MultiSelection fornisce una selezione diversa. Gli ID vengono dal resolver."""
    defn = cp.CustomParserDef(
        name="MSID", mode="ID_ONLY", sport="Calcio",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", start_after="Merc:", end_before="\n", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ])
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name="Inter"),
                             cp.MultiRowRule(selection_name="Milan")]
    return defn


def test_multi_id_per_riga_ogni_selezione_ottiene_i_suoi_id():
    """#192 (follow-up #290): in ID_ONLY ogni riga MultiSelection deve risolvere gli ID per la
    PROPRIA selezione ed essere piazzabile. Prima gli ID erano risolti solo sulla base (con
    selezione vuota) e `_apply_multi_rule` li azzerava → righe senza ID, non piazzabili.

    Fail-first: sul codice precedente entrambe le righe sono `INVALID_MISSING_FIELDS` (no ID)."""
    res = _PerSelectionResolver({
        "Inter": {"EventId": "ev1", "MarketId": "mk1", "SelectionId": "sel_inter"},
        "Milan": {"EventId": "ev1", "MarketId": "mk1", "SelectionId": "sel_milan"},
    })
    results = pipe.build_validated_rows(_multiselection_id_parser(), _MSG, mode="ID_ONLY",
                                        id_resolver=res)
    assert len(results) == 2
    assert all(r.status == validator.VALID and r.placeable for r in results)
    by_sel = {r.row["SelectionName"]: r.row for r in results}
    assert by_sel["Inter"]["SelectionId"] == "sel_inter"      # ID risolti PER RIGA
    assert by_sel["Milan"]["SelectionId"] == "sel_milan"
    assert by_sel["Inter"]["MarketId"] == "mk1" and by_sel["Milan"]["MarketId"] == "mk1"
    # il resolver è stato interrogato con la selezione di OGNI riga.
    sels = {c["selection_name"] for c in res.calls}
    assert {"Inter", "Milan"} <= sels


def test_multi_id_per_riga_fail_open_resolver_che_solleva():
    """Fail-open per riga: un resolver che solleva non blocca né fa crashare la generazione;
    in ID_ONLY, senza ID, le righe restano non piazzabili (fail-closed sul contenuto)."""
    res = _FakeResolver(boom=True)
    results = pipe.build_validated_rows(_multiselection_id_parser(), _MSG, mode="ID_ONLY",
                                        id_resolver=res)
    assert len(results) == 2
    assert all(not r.placeable and r.status == validator.INVALID_MISSING_FIELDS for r in results)


def test_multi_id_per_riga_risoluzione_mista_indipendente():
    """Indipendenza PER RIGA (Sourcery): il resolver risolve SOLO una selezione. In ID_ONLY la
    riga risolta è VALID/piazzabile, l'altra resta `INVALID_MISSING_FIELDS` — il fallimento su una
    selezione NON influenza le altre (ogni riga è arricchita/validata singolarmente)."""
    res = _PerSelectionResolver({
        "Inter": {"EventId": "ev1", "MarketId": "mk1", "SelectionId": "sel_inter"},
        # "Milan" assente → dict vuoto → nessun ID risolto per quella riga.
    })
    results = pipe.build_validated_rows(_multiselection_id_parser(), _MSG, mode="ID_ONLY",
                                        id_resolver=res)
    assert len(results) == 2
    by_sel = {r.row["SelectionName"]: r for r in results}
    assert by_sel["Inter"].status == validator.VALID and by_sel["Inter"].placeable
    assert by_sel["Inter"].row["SelectionId"] == "sel_inter"
    assert by_sel["Milan"].status == validator.INVALID_MISSING_FIELDS and not by_sel["Milan"].placeable
    assert by_sel["Milan"].row["SelectionId"] == ""          # nessun ID inventato
    # entrambe le selezioni interrogate (fail-open per riga).
    assert {"Inter", "Milan"} <= {c["selection_name"] for c in res.calls}


def test_multi_id_per_riga_senza_resolver_resta_a_nomi():
    """Senza `id_resolver` (o parser agnostico) nessun arricchimento: in NAME_ONLY le righe
    restano piazzabili a nomi — comportamento invariato del percorso multi esistente."""
    defn = _multiselection_id_parser()
    defn.mode = "NAME_ONLY"
    # aggiunge un MarketName così il mercato a NOMI è completo per NAME_ONLY
    defn.rules.append(cp.FieldRule(target="MarketName", fixed_value="Match Odds"))
    results = pipe.build_validated_rows(defn, _MSG, mode="NAME_ONLY", id_resolver=None)
    assert len(results) == 2
    assert all(r.placeable for r in results)
    assert all(r.row["SelectionId"] == "" for r in results)   # nessun ID, solo nomi


def _multiselection_id_parser_gui_required_ids():
    """Come `_multiselection_id_parser` ma con `MarketId`/`SelectionId` marcati OBBLIGATORI (come
    fa la GUI per ID_ONLY) e lasciati vuoti: gli ID arrivano dal dizionario PER RIGA."""
    defn = _multiselection_id_parser()
    defn.rules.append(cp.FieldRule(target="MarketId", required=True))     # vuoto → dal resolver
    defn.rules.append(cp.FieldRule(target="SelectionId", required=True))  # vuoto → dal resolver
    return defn


def test_multi_id_per_riga_id_only_obbligatori_riempiti_dal_resolver():
    """Codex (follow-up #290): un parser ID_ONLY «da GUI» marca `MarketId`/`SelectionId`
    OBBLIGATORI; se lasciati vuoti per farli riempire dal dizionario PER RIGA, la base è
    `NOT_READY`. Con un `id_resolver` + sport gli ID sono trattati come «forniti» per il solo gate
    della base → la generazione parte e ogni riga risolve i SUOI ID.

    Fail-first: prima di questo fix la base restava `NOT_READY` (MarketId/SelectionId non coperti
    da `multi_supplied`) → `[base]`, zero righe piazzabili."""
    res = _PerSelectionResolver({
        "Inter": {"EventId": "ev1", "MarketId": "mk1", "SelectionId": "sel_inter"},
        "Milan": {"EventId": "ev1", "MarketId": "mk1", "SelectionId": "sel_milan"},
    })
    results = pipe.build_validated_rows(_multiselection_id_parser_gui_required_ids(), _MSG,
                                        mode="ID_ONLY", id_resolver=res)
    assert len(results) == 2
    assert all(r.status == validator.VALID and r.placeable for r in results)
    by_sel = {r.row["SelectionName"]: r.row for r in results}
    assert by_sel["Inter"]["SelectionId"] == "sel_inter"
    assert by_sel["Milan"]["SelectionId"] == "sel_milan"


def test_multi_id_per_riga_id_only_obbligatori_senza_resolver_restano_bloccati():
    """Contro-prova fail-closed: stesso parser (ID obbligatori vuoti) SENZA resolver → gli ID non
    sono «forniti», la base resta `NOT_READY` e non si genera alcuna riga (mai una scommessa senza
    ID in ID_ONLY)."""
    results = pipe.build_validated_rows(_multiselection_id_parser_gui_required_ids(), _MSG,
                                        mode="ID_ONLY", id_resolver=None)
    assert len(results) == 1
    assert results[0].status == pipe.NOT_READY and not results[0].placeable


def test_multi_id_per_riga_resolver_non_dict_non_crasha():
    """CodeRabbit: un resolver che ritorna un valore NON dict (truthy) non deve far crashare la
    pipeline (fail-open). Le righe restano a nomi → in ID_ONLY non piazzabili, ma nessuna eccezione."""
    class _BadResolver:
        def resolve_ids(self, **kw):
            return ["non", "un", "dict"]     # truthy ma non dict

    results = pipe.build_validated_rows(_multiselection_id_parser(), _MSG, mode="ID_ONLY",
                                        id_resolver=_BadResolver())
    assert len(results) == 2
    assert all(not r.placeable for r in results)


def test_multi_id_per_riga_name_only_id_obbligatori_non_rilassati():
    """Codex (safety): il rilassamento degli ID obbligatori vale SOLO in ID_ONLY (dove il validator
    li ri-controlla → fail-closed se il resolver manca). In NAME_ONLY, un parser che marca
    `MarketId`/`SelectionId` obbligatori come guardia NON deve essere sbloccato dalla sola presenza
    di un resolver: se il resolver manca, una riga senza ID — che il parser ha dichiarato incompleta
    — NON deve diventare piazzabile (il validator NAME_ONLY non ri-controlla gli ID).

    Fail-first: prima di questo fix, con resolver presente gli ID erano tolti dal gate della base
    anche in NAME_ONLY → righe VALID/piazzabili con ID vuoti."""
    defn = cp.CustomParserDef(
        name="MSname_req_ids", mode="NAME_ONLY", sport="Calcio",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", start_after="Merc:", end_before="\n", required=True),
            cp.FieldRule(target="MarketName", fixed_value="Match Odds"),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
            cp.FieldRule(target="MarketId", required=True),      # guardia: obbligatorio, vuoto
            cp.FieldRule(target="SelectionId", required=True),   # guardia: obbligatorio, vuoto
        ])
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name="Inter"),
                             cp.MultiRowRule(selection_name="Milan")]
    res = _FakeResolver({})     # resolver presente ma NON risolve (manca)
    results = pipe.build_validated_rows(defn, _MSG, mode="NAME_ONLY", id_resolver=res)
    # ID obbligatori NON rilassati in NAME_ONLY → la base resta NOT_READY → nessuna riga.
    assert len(results) == 1
    assert results[0].status == pipe.NOT_READY and not results[0].placeable


def test_multi_id_per_riga_eventid_obbligatorio_resta_bloccante():
    """Codex (safety): il rilassamento tocca SOLO i campi che il validator ID_ONLY ri-controlla
    (`MarketId`/`SelectionId`), NON `EventId`. Un parser ID_ONLY che marca `EventId` obbligatorio,
    con un resolver che riempie market/selection ma NON `EventId`, NON deve produrre righe VALID
    con `EventId` vuoto (il parser l'aveva dichiarato obbligatorio).

    Fail-first: prima di questo fix `EventId` era nel set rilassato → la base passava e le righe
    diventavano VALID con `EventId` vuoto (il validator ID_ONLY non ri-controlla `EventId`)."""
    defn = _multiselection_id_parser()
    defn.rules.append(cp.FieldRule(target="EventId", required=True))      # obbligatorio, vuoto
    defn.rules.append(cp.FieldRule(target="MarketId", required=True))
    defn.rules.append(cp.FieldRule(target="SelectionId", required=True))
    # resolver che risolve market/selection ma NON EventId per ciascuna selezione.
    res = _PerSelectionResolver({
        "Inter": {"MarketId": "mk1", "SelectionId": "sel_inter"},
        "Milan": {"MarketId": "mk1", "SelectionId": "sel_milan"},
    })
    results = pipe.build_validated_rows(defn, _MSG, mode="ID_ONLY", id_resolver=res)
    assert len(results) == 1                              # EventId non rilassato → base NOT_READY
    assert results[0].status == pipe.NOT_READY and not results[0].placeable
    assert "EventId" in results[0].missing_required


def test_preview_rows_id_only_multi_con_resolver_equivale_al_runtime():
    """Codex (#1): passando `id_resolver` a `ParserBuilder.preview_rows`, l'anteprima di un parser
    ID_ONLY MultiSelection (ID obbligatori vuoti, riempiti dal dizionario) mostra le righe come
    RUNTIME (piazzabili con ID risolti). Senza resolver l'anteprima è conservativa (una sola riga
    base non pronta). Verifica che il param sia inoltrato al motore."""
    from xtrader_bridge import parser_builder as pb
    b = pb.ParserBuilder(_multiselection_id_parser_gui_required_ids())
    res = _PerSelectionResolver({
        "Inter": {"EventId": "ev1", "MarketId": "mk1", "SelectionId": "sel_inter"},
        "Milan": {"EventId": "ev1", "MarketId": "mk1", "SelectionId": "sel_milan"},
    })
    # SENZA resolver: conservativa → base non pronta, nessuna riga multi piazzabile.
    conservative = b.preview_rows(_MSG, mode="ID_ONLY")
    assert all(not r.placeable for r in conservative)
    # CON resolver: equivalente al runtime → 2 righe selezione piazzabili con i loro ID.
    equiv = b.preview_rows(_MSG, mode="ID_ONLY", id_resolver=res)
    placeable = [r for r in equiv if r.placeable]
    assert {r.row["SelectionName"] for r in placeable} == {"Inter", "Milan"}
    assert {r.row["SelectionId"] for r in placeable} == {"sel_inter", "sel_milan"}
