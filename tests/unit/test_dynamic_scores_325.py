"""#325: estrazione per-riga DINAMICA dei risultati esatti (Correct Score FT + primo tempo).

Un messaggio che elenca più risultati esatti (es. «1-0, 2-1, 3-0») + una regola MultiSelection
**dinamica** (`selection_name` vuoto + «Inizia dopo/Finisce prima») → UNA riga CSV per risultato,
ognuna validata singolarmente (fail-closed per-riga). Esercita le funzioni REALI:
`custom_parser_engine.extract_scores` (lista + normalizzazione «N - N») e
`custom_pipeline.build_validated_rows` (ramo dinamico + fix `_multi_supplied_cols`).
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge.custom_parser_engine import extract_scores

MSG = "🆚 Al v Hilal\nRisultati: 1-0, 2-1, 3-0\n⌚ 1m\n"


def _base(market_type="CORRECT_SCORE"):
    return [
        cp.FieldRule(target="Provider", fixed_value="PBet"),
        cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True),
        cp.FieldRule(target="Price", fixed_value="1.50", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="MarketType", fixed_value=market_type, required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
    ]


def _dyn_parser(*, start_after="Risultati:", end_before="\n", market_type="CORRECT_SCORE"):
    defn = cp.CustomParserDef(name="DYN", mode="NAME_ONLY", rules=_base(market_type))
    defn.multi_selection_enabled = True
    # selection_name VUOTO + delimitatori → regola dinamica (#325).
    defn.multi_selections = [cp.MultiRowRule(start_after=start_after, end_before=end_before)]
    return defn


def _placeable_rows(defn, msg=MSG):
    res = pipe.build_validated_rows(defn, msg, mode="NAME_ONLY")
    assert res, "build_validated_rows non deve mai ritornare una lista vuota"
    return [r.row for r in res if r.placeable]


# ── extract_scores (puro) ────────────────────────────────────────────────────

def test_extract_scores_lista_e_normalizzazione():
    assert extract_scores("Risultati: 1-0, 2-1, 3-0 fine") == ["1 - 0", "2 - 1", "3 - 0"]


def test_extract_scores_separatori_e_formati_robusti():
    # separatori misti (virgola/spazio/newline/slash); formati «1:0»/«04-2»/«3 - 0» normalizzati.
    assert extract_scores("1-0 2:1\n3 - 0 / 04-2") == ["1 - 0", "2 - 1", "3 - 0", "4 - 2"]


def test_extract_scores_dedup_preserva_ordine():
    # nessuna riga doppia (nessuna doppia scommessa) per lo stesso punteggio.
    assert extract_scores("1-0, 1-0, 2-1, 1-0") == ["1 - 0", "2 - 1"]


def test_extract_scores_regione_delimitata():
    # solo i punteggi DENTRO la regione [start_after..end_before] contano.
    txt = "PRE 9-9 [ 1-0, 2-1 ] POST 5-5"
    assert extract_scores(txt, start_after="[", end_before="]") == ["1 - 0", "2 - 1"]


def test_extract_scores_vuota_o_nessun_punteggio():
    assert extract_scores("nessun punteggio qui") == []
    assert extract_scores("") == []
    assert extract_scores("PRE [ ] POST", start_after="[", end_before="]") == []


# ── pipeline end-to-end ──────────────────────────────────────────────────────

def test_una_riga_per_risultato_correct_score_ft():
    rows = _placeable_rows(_dyn_parser())
    assert [r["SelectionName"] for r in rows] == ["1 - 0", "2 - 1", "3 - 0"]
    assert all(r["MarketType"] == "CORRECT_SCORE" for r in rows)      # stesso mercato base


def test_primo_tempo_half_time_score():
    rows = _placeable_rows(_dyn_parser(market_type="HALF_TIME_SCORE"))
    assert [r["SelectionName"] for r in rows] == ["1 - 0", "2 - 1", "3 - 0"]
    assert all(r["MarketType"] == "HALF_TIME_SCORE" for r in rows)


def test_un_solo_risultato():
    rows = _placeable_rows(_dyn_parser(), msg="🆚 A v B\nRisultati: 2 - 2\n")
    assert [r["SelectionName"] for r in rows] == ["2 - 2"]


def test_token_malformato_ignorato_altri_passano():
    # un token non-punteggio nella lista non genera una riga sbagliata; i validi passano.
    rows = _placeable_rows(_dyn_parser(), msg="🆚 A v B\nRisultati: 1-0, XYZ, 2-1\n")
    assert [r["SelectionName"] for r in rows] == ["1 - 0", "2 - 1"]


def test_lista_vuota_nessuna_riga_piazzabile_no_crash():
    # start_after non trovato → nessun punteggio → nessuna riga piazzabile (fail-closed),
    # ma build_validated_rows ritorna comunque un esito (non `[]`, così resolve_row non crasha).
    res = pipe.build_validated_rows(_dyn_parser(start_after="NONESISTE:"), MSG, mode="NAME_ONLY")
    assert res and not [r for r in res if r.placeable]


def test_ids_azzerati_per_riga_senza_resolver():
    # ogni riga cambia SelectionName → MarketId/SelectionId azzerati (nessun resolver → vuoti);
    # in NAME_ONLY resta piazzabile a nomi (fail-open), coerente con #192.
    rows = _placeable_rows(_dyn_parser())
    assert all(r["SelectionId"] == "" and r["MarketId"] == "" for r in rows)


def test_base_not_ready_su_selectionname_obbligatorio_rilassata_dal_dinamico():
    # kyZ #192/#325: se il parser ha una regola SelectionName OBBLIGATORIA ma vuota (estrazione
    # fallita → base NOT_READY), la regola SELEZIONE dinamica «fornisce» comunque SelectionName via
    # estrazione (fix `_multi_supplied_cols`): la base viene rilassata e le righe sono generate.
    defn = _dyn_parser()
    defn.rules = defn.rules + [
        cp.FieldRule(target="SelectionName", start_after="ZZZ", end_before="ZZZ", required=True)]
    rows = _placeable_rows(defn)
    assert [r["SelectionName"] for r in rows] == ["1 - 0", "2 - 1", "3 - 0"]


def test_retrocompat_selezione_fissa_resta_single_row():
    # una regola con selection_name FISSO NON è dinamica → percorso #192 a riga singola invariato.
    defn = _dyn_parser()
    defn.multi_selections = [cp.MultiRowRule(selection_name="1 - 0")]
    rows = _placeable_rows(defn)
    assert [r["SelectionName"] for r in rows] == ["1 - 0"]
