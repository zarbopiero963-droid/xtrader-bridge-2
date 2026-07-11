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


def test_extract_scores_separatori_robusti_e_normalizzazione():
    # separatori misti FRA i risultati (virgola/spazio/newline/slash); zeri iniziali rimossi.
    assert extract_scores("1-0 2-1\n3 - 0 / 04-2") == ["1 - 0", "2 - 1", "3 - 0", "4 - 2"]


def test_extract_scores_esclude_orari_e_due_punti():
    # #341 (Fable/Fugu/GPT/GLM): NIENTE «:» → orari come «20:45»/«45:12» NON sono punteggi
    # (evita SelectionName fantasma → scommessa spuria). Anche un «12-30» resta un punteggio a
    # trattino valido per forma (fail-closed a valle se non nel dizionario), ma «20:45» no.
    assert extract_scores("Kickoff 20:45 HT 45:12") == []
    assert extract_scores("1:0, 2:1") == []                    # «:» non riconosciuto (di proposito)


def test_extract_scores_esclude_numeri_lunghi_e_maglie():
    # #341: confini di cifra + cap 2 cifre → numeri lunghi / maglie non diventano punteggi né
    # loro pezzi (niente «234 - 5» da «1234-5», niente «0 - 1» da «100-1»).
    assert extract_scores("Maglia 100-1 e 1-100 e 1234-5 e 007-3") == []
    # ma un punteggio normale accanto a un numero lungo resta estratto
    assert extract_scores("id 1234 punteggi: 2-1, 3-0") == ["2 - 1", "3 - 0"]


def test_extract_scores_cap_difensivo():
    # #341 (Fugu): input non attendibile con moltissimi «N-N» → tagliato al cap (nessun
    # piazzamento massivo). Genero punteggi DISTINTI oltre il cap.
    from xtrader_bridge.custom_parser_engine import _MAX_SCORES
    many = " ".join(f"{h}-{a}" for h in range(10) for a in range(10))   # 100 distinti «h-a»
    got = extract_scores(many)
    assert len(got) == _MAX_SCORES and _MAX_SCORES == 50


def test_extract_scores_dedup_preserva_ordine():
    # nessuna riga doppia (nessuna doppia scommessa) per lo stesso punteggio.
    assert extract_scores("1-0, 1-0, 2-1, 1-0") == ["1 - 0", "2 - 1"]


def test_extract_scores_esclude_decimali_handicap_quote():
    # #341 (Fable): un handicap/quota come «0-0.5», «1-0.25» o «0.5-1» NON deve produrre un punteggio
    # spurio «0 - 0»/«1 - 0»/«5 - 1» — sono selezioni Correct Score VALIDE che in NAME_ONLY darebbero
    # una riga piazzabile ERRATA. Confini anti-decimale su entrambi i lati. Fail-first: col vecchio
    # pattern «0-0.5» → «0 - 0».
    assert extract_scores("Handicap 0-0.5") == []
    assert extract_scores("Linea 1-0.25 e 2-1.5") == []
    assert extract_scores("Quota 0.5-1") == []
    assert extract_scores("0.5-0") == []
    assert extract_scores("1.0 - 0") == []
    # ma punteggi interi accanto a un decimale restano estratti
    assert extract_scores("hcap 0.5 punteggi 2-1, 3-0") == ["2 - 1", "3 - 0"]


def test_extract_scores_esclude_decimali_con_virgola_italiana():
    # #341 (Fable/Fugu/GPT): nei canali italiani i decimali usano la VIRGOLA («0,5»). «1-0,5» o
    # «0,5-1» NON devono produrre «1 - 0»/«5 - 1» spuri. I confini anti-decimale mordono su `[.,]`.
    assert extract_scores("Handicap 1-0,5") == []
    assert extract_scores("Linea 0,5-1 e 1-0,25") == []
    assert extract_scores("hcap 0,5 punteggi 2-1, 3-0") == ["2 - 1", "3 - 0"]
    # disambiguazione lista-vs-decimale: comma-SPAZIO resta una lista valida...
    assert extract_scores("1-0, 2-1, 3-0") == ["1 - 0", "2 - 1", "3 - 0"]
    # ...ma la virgola SENZA spazio è ambigua con un decimale → fail-closed (nessuna estrazione).
    assert extract_scores("1-0,2-1") == []


def test_extract_scores_esclude_decimale_senza_cifra_iniziale():
    # #341 (Fable): un decimale scritto SENZA zero iniziale («,5» / «.5») non deve produrre un
    # punteggio spurio «5 - 1» (il confine `(?<![.,])` sul primo numero morde anche senza cifra prima).
    assert extract_scores("linea .5-1") == []
    assert extract_scores("hcap ,5-1") == []
    assert extract_scores(".5-0") == []
    # ma un punteggio seguito da un semplice punto/virgola di FRASE resta estratto (non è un decimale).
    assert extract_scores("Risultato 1-0. Poi 2-1") == ["1 - 0", "2 - 1"]
    assert extract_scores("Esito 3-1, e basta") == ["3 - 1"]


def test_extract_scores_non_fonde_cifre_di_righe_diverse():
    # #341 (Fugu): lo spazio attorno al «-» è SOLO orizzontale ([^\S\r\n]*) → cifre su righe
    # adiacenti in una regione multi-riga NON si fondono in un punteggio spurio (che diventerebbe
    # una riga CSV / scommessa Betfair errata). Fail-first: col vecchio `\s*` «3\n- 0» → «3 - 0».
    assert extract_scores("Gol 3\n- 0 fine") == []
    assert extract_scores("Casa 2\n-\n1 Ospite") == []
    # ma un punteggio interamente su UNA riga (con altre righe attorno) resta valido.
    assert extract_scores("riga A\n2 - 1\nriga B") == ["2 - 1"]


def test_extract_scores_spazi_variabili_attorno_al_trattino():
    # #341 (GLM/GPT gap): il caso più comune formattato — spazi variabili attorno al «-» e testo
    # non numerico adiacente — deve estrarre e normalizzare a «N - N».
    assert extract_scores("Punteggio 1  -  0 finale") == ["1 - 0"]
    assert extract_scores("HT: 2-0 · FT 3 -1") == ["2 - 0", "3 - 1"]


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


def test_multimarket_e_multiselection_dinamica_seguono_mercato_base():
    # #341 (Fable #1 / GPT / GLM): MultiMarket + MultiSelection generano righe SEPARATE (#192, non
    # cartesiane). Entrambe derivano dalla riga BASE: la selezione dinamica segue il mercato della
    # BASE (o l'override della selezione), NON l'override della regola MERCATO. `_multi_supplied_cols`
    # e `_selection_rows` usano lo STESSO `base.row["MarketType"]` → nessuna incoerenza di gate.
    # Config: base CORRECT_SCORE + regola MERCATO OVER_UNDER (con selezione fissa) + selezione dinamica.
    defn = _dyn_parser()                                   # base CORRECT_SCORE + selezione dinamica
    defn.multi_market_enabled = True
    defn.multi_markets = [cp.MultiRowRule(market_type="OVER_UNDER", selection_name="Over 2.5")]
    res = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY")
    pairs = [(r.row["MarketType"], r.row["SelectionName"]) for r in res]
    # righe SEPARATE, NON cartesiane (#192): esattamente 1 mercato + 3 selezioni (GLM/GPT #341).
    assert len(res) == 4
    assert ("OVER_UNDER", "Over 2.5") in pairs             # riga MERCATO: usa l'override mercato
    assert ("CORRECT_SCORE", "1 - 0") in pairs             # righe SELEZIONE: dinamiche sul mercato BASE
    assert ("CORRECT_SCORE", "2 - 1") in pairs
    assert ("CORRECT_SCORE", "3 - 0") in pairs
    # NESSUNA combinazione cartesiana mercato×selezione (nessuna scommessa spuria extra).
    assert ("OVER_UNDER", "1 - 0") not in pairs
    assert ("CORRECT_SCORE", "Over 2.5") not in pairs


def test_gate_market_non_canonico_minuscolo_non_estrae_failclosed():
    # #341 (Fugu #2): il gate richiede il MarketType CANONICO (confronto esatto, niente `.upper()`).
    # Un `market_type` minuscolo da JSON legacy («correct_score») NON attiva l'estrazione dinamica →
    # nessuna riga dinamica con MarketType non canonico (che XTrader/Betfair rifiuterebbe o mapperebbe
    # male). Resta fail-closed (base NOT_READY su SelectionName vuoto, nessuna riga piazzabile).
    # Fail-first: col vecchio `.upper()` estrarrebbe «1 - 0»/«2 - 1»/«3 - 0».
    res = pipe.build_validated_rows(_dyn_parser(market_type="correct_score"), MSG, mode="NAME_ONLY")
    names = [r.row.get("SelectionName", "") for r in res]
    assert "1 - 0" not in names and "2 - 1" not in names        # nessuna estrazione dinamica
    assert not [r for r in res if r.placeable]                  # fail-closed


def test_gate_half_time_score_minuscolo_non_estrae_failclosed():
    # #341 (GPT symmetry): stesso fail-closed per L'ALTRO mercato-punteggio ammesso —
    # «half_time_score» minuscolo NON è canonico → nessuna estrazione dinamica (il gate è un
    # confronto esatto su `_DYNAMIC_SCORE_MARKETS`, uniforme per entrambi i mercati).
    res = pipe.build_validated_rows(_dyn_parser(market_type="half_time_score"), MSG, mode="NAME_ONLY")
    names = [r.row.get("SelectionName", "") for r in res]
    assert "1 - 0" not in names and "2 - 1" not in names
    assert not [r for r in res if r.placeable]


def test_un_solo_risultato():
    rows = _placeable_rows(_dyn_parser(), msg="🆚 A v B\nRisultati: 2 - 2\n")
    assert [r["SelectionName"] for r in rows] == ["2 - 2"]


def test_token_malformato_ignorato_altri_passano():
    # un token non-punteggio nella lista non genera una riga sbagliata; i validi passano.
    rows = _placeable_rows(_dyn_parser(), msg="🆚 A v B\nRisultati: 1-0, XYZ, 2-1\n")
    assert [r["SelectionName"] for r in rows] == ["1 - 0", "2 - 1"]


def test_lista_vuota_nessuna_riga_piazzabile_con_detail():
    # start_after non trovato → nessun punteggio → nessuna riga piazzabile (fail-closed), ma
    # build_validated_rows ritorna comunque un esito (non `[]`, resolve_row non crasha) con un
    # `detail` esplicito «no_scores_extracted» per la diagnostica (#341 Fable).
    res = pipe.build_validated_rows(_dyn_parser(start_after="NONESISTE:"), MSG, mode="NAME_ONLY")
    assert res and not [r for r in res if r.placeable]
    assert res[0].detail == "no_scores_extracted"


def test_retrocompat_fissa_con_delimitatori_resta_fissa():
    # #341 (Fugu): la detection è STRETTA su `selection_name` VUOTO. Una regola con selection_name
    # FISSO NON diventa dinamica anche se ha start_after/end_before (che pre-#325 erano ignorati) →
    # resta UNA riga fissa, nessuna estrazione. Nessuna regressione «crea/sopprime bet».
    defn = _dyn_parser()
    defn.multi_selections = [cp.MultiRowRule(selection_name="1 - 0",
                                             start_after="Risultati:", end_before="\n")]
    rows = _placeable_rows(defn)
    assert [r["SelectionName"] for r in rows] == ["1 - 0"]


def test_id_only_punteggi_dinamici_non_piazzabili_senza_dizionario():
    # #341: i risultati esatti Betfair sono selezioni PER-PARTITA e NON sono nel dizionario locale
    # (tipicamente assenti: nessuna SelectionName per CORRECT_SCORE/HALF_TIME_SCORE). Quindi in
    # ID_ONLY un punteggio dinamico non risolve alcun
    # SelectionId → NON piazzabile (fail-closed): l'estrazione dei punteggi è di fatto NAME_ONLY.
    res = pipe.build_validated_rows(_dyn_parser(), MSG, mode="ID_ONLY")
    assert res, "build_validated_rows non deve tornare lista vuota"
    assert not [r for r in res if r.placeable]      # nessun punteggio piazzabile a ID senza dizionario


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


def test_mercato_non_punteggio_resta_riga_fissa_no_estrazione():
    # #341 (Fable): una MultiSelection con selection_name VUOTO + delimitatori RESIDUI (campi già
    # presenti su MultiRowRule PRIMA di #325, «conservati per una futura estrazione per-riga») su un
    # mercato NON-punteggio NON diventa dinamica: resta UNA riga fissa che eredita il SelectionName
    # base, senza moltiplicare in N righe/scommesse estratte. Fail-first sul gate _DYNAMIC_SCORE_MARKETS
    # (col vecchio codice senza gate estrarrebbe «1 - 0»/«2 - 1»/«3 - 0» dal messaggio).
    defn = cp.CustomParserDef(name="MO", mode="NAME_ONLY", rules=[
        cp.FieldRule(target="Provider", fixed_value="PBet"),
        cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True),
        cp.FieldRule(target="Price", fixed_value="1.50", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
        cp.FieldRule(target="MarketName", fixed_value="1X2"),
        cp.FieldRule(target="SelectionName", fixed_value="1", required=True),
    ])
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(start_after="Risultati:", end_before="\n")]
    res = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY")
    assert [r.row["SelectionName"] for r in res] == ["1"]      # 1 riga fissa, NON i 3 punteggi


def test_market_dinamico_non_fornisce_selectionname_scoping():
    # #341 (CodeRabbit): il caso speciale «SelectionName via estrazione dinamica» è ristretto alle
    # sole regole SELEZIONE. Una regola MERCATO con selection_name VUOTO ma start_after/end_before
    # valorizzati (campi condivisi da MultiRowRule, NON validati per i mercati → JSON residuo/misconfig)
    # NON deve essere scambiata per selezione dinamica: non «fornisce» SelectionName e quindi NON
    # rilassa a torto il gate base su un SelectionName OBBLIGATORIO. Fail-first sul fix di scoping.
    defn = cp.CustomParserDef(name="MKT", mode="NAME_ONLY", rules=_base())
    defn.rules = defn.rules + [
        cp.FieldRule(target="SelectionName", start_after="ZZZ", end_before="ZZZ", required=True)]
    defn.multi_market_enabled = True
    defn.multi_selection_enabled = False
    defn.multi_selections = []
    defn.multi_markets = [cp.MultiRowRule(market_type="OVER_UNDER",
                                          start_after="X", end_before="Y")]
    res = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY")
    # base NON rilassata → propagata NOT_READY (fail-closed), nessuna riga mercato generata.
    assert len(res) == 1 and res[0].status == pipe.NOT_READY
    assert not res[0].placeable


def test_multi_supplied_cols_selectionname_solo_dalle_selezioni():
    # #341 (GLM/GPT gap): con MERCATI e SELEZIONI entrambi presenti, il credito «SelectionName via
    # estrazione dinamica» arriva SOLO dalle selezioni (`from_selection=True`); l'intersezione
    # `all(markets) and all(selections)` di `_multi_supplied_cols` resta fail-closed.
    from xtrader_bridge.custom_pipeline import _multi_supplied_cols
    market = cp.MultiRowRule(market_type="OVER_UNDER", start_after="X", end_before="Y")  # residuo
    sel = cp.MultiRowRule(start_after="Risultati:", end_before="\n")                     # dinamica
    CS = "CORRECT_SCORE"   # mercato-punteggio → la selezione dinamica è abilitata (#341 gate)
    # solo mercato (con delimitatori residui) → NON fornisce SelectionName (non lo popola via estrazione).
    assert "SelectionName" not in _multi_supplied_cols([market], [], CS)
    # solo selezione dinamica su mercato-punteggio → fornisce SelectionName.
    assert "SelectionName" in _multi_supplied_cols([], [sel], CS)
    # entrambi presenti: il mercato NON lo fornisce → intersezione all() → NON fornito (fail-closed).
    assert "SelectionName" not in _multi_supplied_cols([market], [sel], CS)
    # un mercato che POPOLA esplicitamente selection_name (attributo non vuoto) + selezione dinamica
    # → entrambi lo forniscono → SelectionName fornito.
    market_fixed = cp.MultiRowRule(market_type="OVER_UNDER", selection_name="1 - 0")
    assert "SelectionName" in _multi_supplied_cols([market_fixed], [sel], CS)
    # #341 (Fable gate): stessa selezione dinamica ma su mercato NON-punteggio → NON è dinamica →
    # NON fornisce SelectionName (nessuna moltiplicazione righe su config legacy).
    assert "SelectionName" not in _multi_supplied_cols([], [sel], "OVER_UNDER")


def test_detail_no_scores_non_e_colonna_csv():
    # #341 (GLM gap): `detail="no_scores_extracted"` è metadato diagnostico del PipelineResult,
    # NON una colonna CSV → non deve comparire nel contratto/riga scritta.
    res = pipe.build_validated_rows(_dyn_parser(start_after="NONESISTE:"), MSG, mode="NAME_ONLY")
    assert res[0].detail == "no_scores_extracted"
    assert "detail" not in res[0].row
    assert "no_scores_extracted" not in res[0].row.values()
