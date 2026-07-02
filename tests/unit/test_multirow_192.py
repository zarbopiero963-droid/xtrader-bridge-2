"""Test hard del Parser Personalizzato MULTI-RIGA (#192): un messaggio → più righe CSV.

Esercita le funzioni REALI: `custom_parser` (modello + migrazione), `custom_pipeline.
build_validated_rows` (MultiMarket/MultiSelection + validazione per-riga), `signal_router.
resolve_row` (RouteResult.rows), `signal_dedupe.row_dedup_key` (dedup per-riga),
`write_path.commit_signals` (commit atomico N righe) e `csv_writer.write_rows` (CSV).

Copre i 7 test richiesti dalla issue: backward-compat, MultiMarket (2 righe), MultiSelection
(3 righe), dedup per-riga, scrittura CSV, dati della preview (N righe), validazione parziale.
"""

import csv
import os

from xtrader_bridge import (
    custom_parser as cp,
    custom_pipeline as pipe,
    csv_writer,
    live_guard,
    name_mapping_store as nm,
    safety_guard,
    signal_dedupe,
    signal_queue,
    validator,
    write_path,
)
from xtrader_bridge.csv_writer import CSV_HEADER

# Config di mappatura nomi minima per il test kyZ (mapping su righe derivate da base NOT_READY).
_MAP_CFG = {"name_mappings": {"Premier": [
    {"country": "Inghilterra", "betfair": "Liverpool", "provider": "Liverpool FC"},
    {"country": "Inghilterra", "betfair": "Leeds", "provider": "Leeds Utd"},
]}}

# Messaggio reale della issue #192.
MSG = (
    "P.Bet. PREMACHT 0,5HT 🔊 ✅\n"
    "🏆Saudi Professional League\n"
    "🆚Al-Kholood Club v Al-Hilal\n"
    "⚽ 0 - 0\n"
    "⌚ 1m\n"
)
EVENT = "Al-Kholood Club v Al-Hilal"


def _base_rules(extra=()):
    """Riga base comune: Provider + EventName (estratto) + Price + BetType validi."""
    rules = [
        cp.FieldRule(target="Provider", fixed_value="PBet"),
        cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True),
        cp.FieldRule(target="Price", fixed_value="1.50", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ]
    rules.extend(extra)
    return rules


def _multimarket_parser():
    defn = cp.CustomParserDef(name="MM", mode="NAME_ONLY", rules=_base_rules())
    defn.multi_market_enabled = True
    defn.multi_markets = [
        cp.MultiRowRule(market_type="FIRST_HALF_GOALS_05",
                        market_name="1º tempo - Totale goal 0,5",
                        selection_name="Over 0,5", points="1"),
        cp.MultiRowRule(market_type="OVER_UNDER_15", market_name="Totale goal 1,5",
                        selection_name="Over 1,5", points="1"),
    ]
    return defn


def _multiselection_parser_with(selections):
    # La base fornisce anche MarketType/MarketName: le selezioni ereditano il mercato. Le
    # selezioni sono parametriche per simulare un parser che, con lo STESSO testo, produce un
    # numero DIVERSO di righe dopo un cambio di config a runtime (kyh #192).
    extra = [
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
    ]
    defn = cp.CustomParserDef(name="MS", mode="NAME_ONLY", rules=_base_rules(extra))
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name=s) for s in selections]
    return defn


def _multiselection_parser():
    return _multiselection_parser_with(["1 - 0", "2 - 1", "1 - 2"])


def _rows(results):
    return [r.row for r in results]


# ── Test 1 — backward compatibility ───────────────────────────────────────────

def test_backward_compat_parser_senza_multi_una_sola_riga():
    # Un parser "vecchio" (dict senza i campi multi) carica con default sicuri...
    legacy = cp.CustomParserDef.from_dict({
        "name": "Legacy", "mode": "NAME_ONLY",
        "rules": [
            {"target": "Provider", "fixed_value": "PBet"},
            {"target": "EventName", "start_after": "🆚", "end_before": "\n", "required": True},
            {"target": "MarketType", "fixed_value": "CORRECT_SCORE", "required": True},
            {"target": "SelectionName", "fixed_value": "1 - 0", "required": True},
            {"target": "Price", "fixed_value": "1.50", "required": True},
            {"target": "BetType", "fixed_value": "PUNTA", "required": True},
        ],
    })
    assert legacy.multi_market_enabled is False
    assert legacy.multi_selection_enabled is False
    assert legacy.multi_markets == [] and legacy.multi_selections == []
    # ...e produce ESATTAMENTE una riga (comportamento single-row invariato).
    results = pipe.build_validated_rows(legacy, MSG, mode="NAME_ONLY")
    assert len(results) == 1
    assert results[0].status == validator.VALID
    assert results[0].row["EventName"] == EVENT
    assert list(results[0].row.keys()) == CSV_HEADER


def test_roundtrip_to_dict_from_dict_preserva_multi():
    defn = _multimarket_parser()
    again = cp.CustomParserDef.from_dict(defn.to_dict())
    assert again.multi_market_enabled is True
    assert len(again.multi_markets) == 2
    assert again.multi_markets[0].market_type == "FIRST_HALF_GOALS_05"
    assert again.multi_markets[0].selection_name == "Over 0,5"
    assert again.active_multi_markets() == again.multi_markets


# ── Test 2 — MultiMarket: 2 righe ─────────────────────────────────────────────

def test_multimarket_due_righe():
    results = pipe.build_validated_rows(_multimarket_parser(), MSG, mode="NAME_ONLY")
    assert len(results) == 2
    rows = _rows(results)
    assert rows[0]["EventName"] == EVENT
    assert rows[0]["MarketType"] == "FIRST_HALF_GOALS_05"
    assert rows[0]["SelectionName"] == "Over 0,5"
    assert rows[1]["EventName"] == EVENT
    assert rows[1]["MarketType"] == "OVER_UNDER_15"
    assert rows[1]["SelectionName"] == "Over 1,5"
    # Entrambe valide e piazzabili (ereditano Provider/EventName/Price/BetType dalla base).
    assert all(r.status == validator.VALID and r.placeable for r in results)


# ── Test 3 — MultiSelection: 3 righe ──────────────────────────────────────────

def test_multiselection_tre_righe():
    results = pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY")
    assert len(results) == 3
    rows = _rows(results)
    assert [r["SelectionName"] for r in rows] == ["1 - 0", "2 - 1", "1 - 2"]
    assert all(r["MarketType"] == "CORRECT_SCORE" for r in rows)
    assert all(r["EventName"] == EVENT for r in rows)
    assert all(r.status == validator.VALID for r in results)


# ── Test 4 — deduplica per-riga ───────────────────────────────────────────────

def test_dedup_per_riga():
    rows = [pipe._apply_multi_rule(
        {"Provider": "PBet", "EventName": EVENT, "MarketType": "CORRECT_SCORE",
         "SelectionName": "", "BetType": "PUNTA"},
        cp.MultiRowRule(selection_name=s)) for s in ("1 - 0", "2 - 1", "1 - 2")]
    tracker = signal_dedupe.SignalTracker()
    # Le 3 righe DIVERSE dallo STESSO messaggio non sono duplicati tra loro.
    first = [tracker.register(MSG, key=signal_dedupe.row_dedup_key(MSG, r), now=0) for r in rows]
    assert [r.status for r in first] == [signal_dedupe.NEW] * 3
    # Lo STESSO identico messaggio reinviato → le stesse 3 righe sono duplicati.
    again = [tracker.register(MSG, key=signal_dedupe.row_dedup_key(MSG, r), now=1) for r in rows]
    assert [r.status for r in again] == [signal_dedupe.DUPLICATE] * 3


def test_dedup_provider_diverso_non_e_duplicato():
    r1 = {"Provider": "PBet", "EventName": EVENT, "MarketType": "CORRECT_SCORE",
          "SelectionName": "1 - 0", "BetType": "PUNTA"}
    r2 = dict(r1, Provider="Altro")
    assert signal_dedupe.row_dedup_key(MSG, r1) != signal_dedupe.row_dedup_key(MSG, r2)


# ── Test 5 — scrittura CSV di N righe ─────────────────────────────────────────

def test_csv_scrive_tutte_le_righe(tmp_path):
    results = pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY")
    rows = _rows(results)
    path = str(tmp_path / "segnali.csv")
    csv_writer.write_rows(rows, path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        data = list(reader)
    assert header == CSV_HEADER                    # 1 header, ordine colonne invariato
    assert len(data) == 3                          # 3 righe dati
    # Nessuna cella spostata: la colonna SelectionName (indice 7) ha i 3 valori attesi.
    sel_idx = CSV_HEADER.index("SelectionName")
    assert [r[sel_idx] for r in data] == ["1 - 0", "2 - 1", "1 - 2"]


# ── Test 6 — dati della preview: N righe ──────────────────────────────────────

def test_preview_data_mostra_n_righe():
    # La preview "Prova messaggio" si basa su build_validated_rows: MultiSelection → 3 righe,
    # MultiMarket → 2 righe (la GUI le renderizza nella tabella; qui si verifica il DATO).
    assert len(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY")) == 3
    assert len(pipe.build_validated_rows(_multimarket_parser(), MSG, mode="NAME_ONLY")) == 2


# ── Test 7 — validazione parziale ─────────────────────────────────────────────

def test_validazione_parziale_riga_non_valida_non_blocca_le_altre():
    defn = _multiselection_parser()
    # La 2ª selezione ha SelectionName vuoto → eredita la base (vuota) → riga NON valida,
    # mentre la 1ª e la 3ª restano valide.
    defn.multi_selections = [
        cp.MultiRowRule(selection_name="1 - 0"),
        cp.MultiRowRule(selection_name=""),
        cp.MultiRowRule(selection_name="1 - 2"),
    ]
    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY")
    assert len(results) == 3
    assert results[0].status == validator.VALID
    assert results[1].status != validator.VALID and not results[1].placeable
    assert results[2].status == validator.VALID
    # Le righe valide restano (il router scrive solo quelle piazzabili).
    placeable = [r.row for r in results if r.placeable]
    assert [r["SelectionName"] for r in placeable] == ["1 - 0", "1 - 2"]


# ── kyZ (#192): NOT_READY della base non blocca le righe multi ────────────────

def _multiselection_parser_selname_obbligatoria():
    """Parser MultiSelection dove `SelectionName` è OBBLIGATORIO nella base ma la base NON lo
    estrae (nessun marcatore nel messaggio) → base `NOT_READY`. Sono le righe MultiSelection a
    fornire il SelectionName. Riproduce il finding kyZ."""
    extra = [
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
        # SelectionName obbligatorio ma estratto da un marcatore ASSENTE nel messaggio → vuoto.
        cp.FieldRule(target="SelectionName", start_after="SEL:", end_before="\n", required=True),
    ]
    defn = cp.CustomParserDef(name="MSreq", mode="NAME_ONLY", rules=_base_rules(extra))
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name=s) for s in ("1 - 0", "2 - 1")]
    return defn


def test_kyz_base_not_ready_riempita_da_multiselection():
    """kyZ (#192, finding A/#4): se la base è `NOT_READY` per un obbligatorio che le righe
    multi riempiono (`SelectionName`), le righe multi devono comunque essere generate e validate.

    Fail-first: sul vecchio codice `build_validated_rows` tornava `[base]` (1 sola riga
    `NOT_READY`, non piazzabile) → ZERO righe scritte a runtime."""
    defn = _multiselection_parser_selname_obbligatoria()
    # Sanity: la base da sola È NOT_READY (SelectionName obbligatorio mancante).
    base = pipe.build_validated_row(defn, MSG, mode="NAME_ONLY")
    assert base.status == pipe.NOT_READY and not base.placeable

    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY")
    assert len(results) == 2                                  # una riga per selezione, NON [base]
    assert all(r.status == validator.VALID and r.placeable for r in results)
    assert [r.row["SelectionName"] for r in results] == ["1 - 0", "2 - 1"]
    assert all(r.row["EventName"] == EVENT for r in results)  # campi comuni ereditati dalla base


def test_kyz_altri_gate_base_restano_fail_closed():
    """kyZ non deve indebolire gli ALTRI gate strutturali: una base senza `Provider`
    (`INVALID_MISSING_PROVIDER`, in `_BASE_BLOCKING`) resta fail-closed anche con multi attivo →
    `[base]`, nessuna riga derivata (mai un bet senza provider)."""
    # Base SENZA Provider ma con SelectionName obbligatorio mancante: prima il NOT_READY viene
    # rilassato, poi il gate provider deve comunque bloccare.
    rules = [
        cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True),
        cp.FieldRule(target="Price", fixed_value="1.50", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="SelectionName", start_after="SEL:", end_before="\n", required=True),
    ]
    defn = cp.CustomParserDef(name="NoProv", mode="NAME_ONLY", rules=rules)
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name="1 - 0")]
    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY", provider="")
    assert len(results) == 1                                       # solo la base, nessuna derivata
    assert results[0].status == pipe.INVALID_MISSING_PROVIDER
    assert not results[0].placeable


def test_kyz_mapping_applicata_su_righe_derivate_da_base_not_ready():
    """kyZ: quando la base `NOT_READY` viene ri-costruita, deve passare COMUNQUE per la mappatura
    nomi (a valle del gate NOT_READY). Le righe derivate devono avere l'`EventName` TRADOTTO, non
    quello provider grezzo — altrimenti si scriverebbe un evento sbagliato.

    Fail-first: col vecchio codice non venivano generate righe; con un bypass ingenuo (derivare
    dalla base NOT_READY non mappata) l'EventName resterebbe non tradotto."""
    profiles = nm.entries_for_profiles(_MAP_CFG, ["Premier"])
    defn = cp.CustomParserDef(
        name="MSmap", mode="NAME_ONLY",
        name_mapping_profiles=["Premier"], team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="PBet"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
            # SelectionName obbligatorio ma non estratto → base NOT_READY.
            cp.FieldRule(target="SelectionName", start_after="SEL:", end_before="\n", required=True),
            cp.FieldRule(target="Price", fixed_value="1.50", required=True),
            cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        ])
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name="1 - 0")]
    msg = "Match: Liverpool FC v Leeds Utd\n⚽ 0 - 0\n"
    results = pipe.build_validated_rows(defn, msg, mode="NAME_ONLY",
                                        name_mapping_profiles=profiles)
    assert len(results) == 1
    assert results[0].status == validator.VALID and results[0].placeable
    assert results[0].row["EventName"] == "Liverpool - Leeds"    # tradotto, non "Liverpool FC v Leeds Utd"
    assert results[0].row["SelectionName"] == "1 - 0"


def test_kyz_obbligatorio_non_coperto_dal_multi_resta_bloccante():
    """kyZ / Codex P1: il rilassamento di `NOT_READY` copre SOLO gli obbligatori che OGNI riga
    multi riempie. Un obbligatorio della base che il multi **non** fornisce (qui `MarketName`,
    che il validator NAME_ONLY non ri-controlla) deve restare **bloccante** — un messaggio che il
    parser ha dichiarato incompleto NON deve raggiungere il CSV.

    Fail-first: col rilassamento «cieco» (bypass di TUTTI i NOT_READY) la base diventava
    derivabile e le righe finivano nel CSV."""
    extra = [
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        # SelectionName obbligatorio → fornito dal MultiSelection; MarketName obbligatorio ma
        # NON fornito da nessuna riga multi e assente nel messaggio → deve restare bloccante.
        cp.FieldRule(target="SelectionName", start_after="SEL:", end_before="\n", required=True),
        cp.FieldRule(target="MarketName", start_after="MKTNAME:", end_before="\n", required=True),
    ]
    defn = cp.CustomParserDef(name="MSp1", mode="NAME_ONLY", rules=_base_rules(extra))
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name=s) for s in ("1 - 0", "2 - 1")]
    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY")
    assert len(results) == 1                                  # nessuna riga derivata: fail-closed
    assert results[0].status == pipe.NOT_READY and not results[0].placeable
    assert "MarketName" in results[0].missing_required        # l'obbligatorio scoperto è ancora segnalato


def test_kyz_market_mapping_missing_risolto_dalle_selezioni():
    """kyZ / Codex P2 + CodeRabbit: con `market_mapping_profiles` attivo e NESSUNA frase che
    combacia, il fallback della mappatura mercati dava `MARKET_MAPPING_MISSING` sulla base (che ha
    `MarketType` ma non `SelectionName`) → `[base]`, zero righe — anche se ogni MultiSelection
    fornisce il `SelectionName`. Ora `MARKET_MAPPING_MISSING` è un motivo **colmabile**: la base è
    ri-valutata trattando come presenti i campi forniti da OGNI riga multi.

    Fail-first: col codice precedente (re-run solo su NOT_READY) la base restava
    `MARKET_MAPPING_MISSING` in `_BASE_BLOCKING` → nessuna riga."""
    extra = [
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
    ]
    defn = cp.CustomParserDef(name="MSmkt", mode="NAME_ONLY", rules=_base_rules(extra))
    defn.market_mapping_profiles = ["P"]                      # mappatura mercati ATTIVA
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name=s) for s in ("1 - 0", "2 - 1")]
    # Profilo la cui frase NON compare nel messaggio (delimitatore assente) → resolve_market="none".
    profiles = [[{"start_after": "Mercato:", "end_before": "\n", "phrase": "gol gol",
                  "market_type": "GOAL_NOGOAL", "market_name": "Entrambe le squadre a segno",
                  "selection_name": "Sì"}]]
    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY",
                                        market_mapping_profiles=profiles)
    placeable = [r for r in results if r.placeable]
    assert [r.row["SelectionName"] for r in placeable] == ["1 - 0", "2 - 1"]  # righe generate


def test_kyz_multi_supplied_gia_in_kwargs_non_crasha():
    """kyZ / CodeRabbit: il re-run interno passa `multi_supplied`; se un chiamante l'ha GIÀ messo
    nei kwargs, un merge naïf darebbe `TypeError: got multiple values`. Il fix copia/scarta i kwargs:
    la chiamata non deve sollevare e deve generare comunque le righe."""
    defn = _multiselection_parser_selname_obbligatoria()      # base NOT_READY → attiva il re-run
    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY",
                                        multi_supplied=frozenset())   # kwarg che collide col re-run
    assert [r.row["SelectionName"] for r in results if r.placeable] == ["1 - 0", "2 - 1"]


def test_kyz_multi_supplied_del_chiamante_ignorato_e_non_indebolisce_il_gate():
    """kyZ / CodeRabbit (Major, safety): `multi_supplied` è INTERNO. Un chiamante che lo passa
    NON deve poter rilassare i gate della prima valutazione: la copertura è ricalcolata SOLO dalle
    regole multi realmente attive. Qui `MarketName` è obbligatorio, NON fornito da nessuna riga
    multi, ma il chiamante finge che lo sia → deve restare `NOT_READY` (fail-closed).

    Fail-first: se il primo `build_validated_row` onorasse il `multi_supplied` del chiamante, la
    base verrebbe rilassata e le righe finirebbero nel CSV."""
    extra = [
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="SelectionName", start_after="SEL:", end_before="\n", required=True),
        cp.FieldRule(target="MarketName", start_after="MKTNAME:", end_before="\n", required=True),
    ]
    defn = cp.CustomParserDef(name="MSspoof", mode="NAME_ONLY", rules=_base_rules(extra))
    defn.multi_selection_enabled = True
    defn.multi_selections = [cp.MultiRowRule(selection_name=s) for s in ("1 - 0", "2 - 1")]
    # Il chiamante finge che MarketName+SelectionName siano forniti dal multi (non è vero per MarketName).
    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY",
                                        multi_supplied=frozenset({"MarketName", "SelectionName"}))
    assert len(results) == 1                                   # gate NON indebolito: nessuna riga
    assert results[0].status == pipe.NOT_READY and not results[0].placeable
    assert "MarketName" in results[0].missing_required


def test_kyz_handicap_multi_malformato_non_raggiunge_il_csv():
    """kyZ / Codex (safety): un override `handicap` malformato in una riga multi NON deve
    raggiungere il CSV. Il gate `INVALID_HANDICAP` della base vede l'Handicap BASE (default "0") e
    `validator.validate` non controlla l'Handicap → serve un controllo di formato sulla riga
    DERIVATA. Vale sia col rilassamento kyZ sia nel percorso multi normale.

    Fail-first: prima del controllo per-riga la riga con `handicap="abc"` risultava `VALID`."""
    extra = [
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
    ]
    defn = cp.CustomParserDef(name="MShcap", mode="NAME_ONLY", rules=_base_rules(extra))
    defn.multi_selection_enabled = True
    defn.multi_selections = [
        cp.MultiRowRule(selection_name="1 - 0", handicap="abc"),   # malformato → scartato
        cp.MultiRowRule(selection_name="2 - 1", handicap="0.5"),   # valido → piazzabile
    ]
    results = pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY")
    assert len(results) == 2
    bad = next(r for r in results if r.row["SelectionName"] == "1 - 0")
    good = next(r for r in results if r.row["SelectionName"] == "2 - 1")
    assert bad.status == pipe.INVALID_HANDICAP and not bad.placeable   # fail-closed
    assert good.status == validator.VALID and good.placeable


# ── commit atomico multi-riga (coda + CSV + rollback) ─────────────────────────

def _cfg(path):
    return {"csv_path": path, "dry_run": False}


def test_commit_signals_scrive_tutte_e_dedupa(tmp_path):
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert res.write_error is None
    assert res.write_attempted is True              # #153 H2: la scrittura conta nel CSV-lock
    assert len(res.rows) == 3                       # 3 righe attive scritte
    assert len(q.active_rows()) == 3
    with open(path, newline="", encoding="utf-8-sig") as f:
        assert sum(1 for _ in f) == 1 + 3           # header + 3 righe

    # Stesso messaggio reinviato (coda svuotata) → tutte duplicate, nessuna scritta.
    q2 = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    res2 = write_path.commit_signals(tracker, None, q2, _cfg(path), MSG, rows, path, now=1,
                                     write_rows=csv_writer.write_rows)
    assert res2.decision == "DUPLICATE"
    assert res2.write_attempted is False            # nessuna scrittura → CSV-lock non toccato
    assert q2.active_rows() == []


def test_commit_signals_write_failure_rollback_completo(tmp_path):
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()

    def _boom(_rows, _path):
        raise OSError("disco pieno (simulato)")

    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=0,
                                    write_rows=_boom)
    assert isinstance(res.write_error, OSError)
    assert q.active_rows() == []                    # coda ripristinata (segnali ritentabili)
    # Guardrail ripristinati: un retry riuscito riscrive le righe (non bloccate come duplicati).
    res2 = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=1,
                                     write_rows=csv_writer.write_rows)
    assert res2.write_error is None and len(res2.rows) == 3


def test_resolve_row_multi_ritorna_rows(monkeypatch):
    # Glue runtime: `signal_router.resolve_row` (chiamato da `app._process`) deve restituire un
    # RouteResult con tutte le righe in `rows`, e `row` = la prima (retro-compatibile).
    from xtrader_bridge import signal_router
    defn = _multiselection_parser()
    monkeypatch.setattr(signal_router, "active_custom_parser", lambda cfg, chat, pd=None: defn)
    monkeypatch.setattr(signal_router.custom_parser_engine, "matches_message",
                        lambda d, t, m: True)
    monkeypatch.setattr(signal_router.source_manager, "source_for_chat", lambda cfg, chat: None)
    res = signal_router.resolve_row(MSG, {"chat_id": "1", "recognition_mode": "NAME_ONLY"})
    assert res.placeable
    assert len(res.all_rows()) == 3
    assert [r["SelectionName"] for r in res.all_rows()] == ["1 - 0", "2 - 1", "1 - 2"]
    assert res.row == res.all_rows()[0]


def test_resolve_row_multi_una_riga_preserva_provenienza(monkeypatch):
    """#239/#192 (Codex P1): un parser MULTI che ORA produce UNA sola riga piazzabile deve
    comunque esporre `rows` (provenienza multi), così il commit usa la dedup PER-RIGA. Prima,
    con una sola riga, `resolve_row` collassava a `rows=None` (single) → l'hash-messaggio
    non riconosceva la riga se in seguito il messaggio ne generava di più (doppia scommessa)."""
    from xtrader_bridge import signal_router
    defn = _multiselection_parser()
    defn.multi_selections = [cp.MultiRowRule(selection_name="1 - 0")]   # UNA sola selezione → 1 riga
    assert defn.is_multi_row() is True
    monkeypatch.setattr(signal_router, "active_custom_parser", lambda cfg, chat, pd=None: defn)
    monkeypatch.setattr(signal_router.custom_parser_engine, "matches_message",
                        lambda d, t, m: True)
    monkeypatch.setattr(signal_router.source_manager, "source_for_chat", lambda cfg, chat: None)
    res = signal_router.resolve_row(MSG, {"chat_id": "1", "recognition_mode": "NAME_ONLY"})
    assert res.placeable
    assert len(res.all_rows()) == 1                 # una sola riga ORA…
    assert res.rows is not None                     # …ma provenienza MULTI preservata (non collassa a single)
    assert res.rows[0]["SelectionName"] == "1 - 0"


def test_is_multi_row_solo_con_righe_attive(monkeypatch):
    """Codex #281: `is_multi_row` si basa sulle righe multi ATTIVE, non sul solo toggle. Una
    modalità abilitata ma SENZA righe attive → single-row (base row), dedup legacy a
    hash-messaggio; con almeno una riga attiva → multi (per-riga)."""
    # toggle acceso ma nessuna riga attiva → NON multi (ripiega sulla riga base single-row).
    defn = cp.CustomParserDef(name="MSempty", mode="NAME_ONLY", rules=_base_rules([
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="1 - 0", required=True),
    ]))
    defn.multi_selection_enabled = True
    defn.multi_selections = []                       # nessuna riga
    assert defn.is_multi_row() is False
    defn.multi_selections = [cp.MultiRowRule(selection_name="X", enabled=False)]  # solo disattivate
    assert defn.is_multi_row() is False
    defn.multi_selections = [cp.MultiRowRule(selection_name="1 - 0")]             # una attiva
    assert defn.is_multi_row() is True
    # e via resolve_row: toggle acceso senza righe attive → RouteResult single-row (rows None).
    from xtrader_bridge import signal_router
    defn.multi_selections = []
    monkeypatch.setattr(signal_router, "active_custom_parser", lambda cfg, chat, pd=None: defn)
    monkeypatch.setattr(signal_router.custom_parser_engine, "matches_message",
                        lambda d, t, m: True)
    monkeypatch.setattr(signal_router.source_manager, "source_for_chat", lambda cfg, chat: None)
    res = signal_router.resolve_row(MSG, {"chat_id": "1", "recognition_mode": "NAME_ONLY"})
    assert res.placeable and res.rows is None        # nessuna riga attiva → single-row legacy


def test_resolve_row_single_resta_invariato(monkeypatch):
    # Un parser senza multi → RouteResult single-row classico: `rows` None, `row` valorizzata.
    from xtrader_bridge import signal_router
    defn = cp.CustomParserDef(name="S", mode="NAME_ONLY", rules=_base_rules([
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="1 - 0", required=True),
    ]))
    monkeypatch.setattr(signal_router, "active_custom_parser", lambda cfg, chat, pd=None: defn)
    monkeypatch.setattr(signal_router.custom_parser_engine, "matches_message",
                        lambda d, t, m: True)
    monkeypatch.setattr(signal_router.source_manager, "source_for_chat", lambda cfg, chat: None)
    res = signal_router.resolve_row(MSG, {"chat_id": "1", "recognition_mode": "NAME_ONLY"})
    assert res.placeable and res.rows is None
    assert res.all_rows() == [res.row]
    assert res.row["SelectionName"] == "1 - 0"


def test_commit_signals_dry_run_non_scrive(tmp_path):
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    cfg = {"csv_path": path, "dry_run": True}
    assert safety_guard.is_dry_run(cfg) is True
    res = write_path.commit_signals(tracker, None, q, cfg, MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert res.decision == "DRY_RUN"
    assert res.rows == [] and q.active_rows() == []     # simulazione: niente CSV operativo
    assert not os.path.exists(path)                     # il file CSV non viene neppure creato


# ── review #239 (Codex/CodeRabbit): correzioni del commit multi-riga ───────────

def test_both_multi_active_righe_separate_non_cartesiane():
    # MultiMarket + MultiSelection insieme → righe SEPARATE (prima i mercati, poi le selezioni),
    # MAI il prodotto cartesiano (2 mercati + 3 selezioni = 5 righe, non 6).
    defn = _multiselection_parser()
    defn.multi_market_enabled = True
    defn.multi_markets = [
        cp.MultiRowRule(market_type="FIRST_HALF_GOALS_05",
                        market_name="1º tempo - Totale goal 0,5",
                        selection_name="Over 0,5", points="1"),
        cp.MultiRowRule(market_type="OVER_UNDER_15", market_name="Totale goal 1,5",
                        selection_name="Over 1,5", points="1"),
    ]
    assert pipe.both_multi_active(defn) is True
    rows = _rows(pipe.build_validated_rows(defn, MSG, mode="NAME_ONLY"))
    assert len(rows) == 5
    assert [r["MarketType"] for r in rows] == [
        "FIRST_HALF_GOALS_05", "OVER_UNDER_15", "CORRECT_SCORE", "CORRECT_SCORE", "CORRECT_SCORE"]
    assert [r["SelectionName"] for r in rows] == [
        "Over 0,5", "Over 1,5", "1 - 0", "2 - 1", "1 - 2"]


def test_multi_rule_azzera_id_stantii_su_cambio_mercato():
    # Se la base porta MarketId/SelectionId (regola ID/dizionario) e la regola multi cambia
    # mercato/selezione, gli ID stantii vanno AZZERATI (CSV non incoerente); l'evento resta.
    base = {col: "" for col in CSV_HEADER}
    base.update({"Provider": "PBet", "EventName": EVENT, "EventId": "42",
                 "MarketType": "OLD_MKT", "MarketName": "Vecchio", "MarketId": "1.111",
                 "SelectionName": "Vecchia", "SelectionId": "999",
                 "Price": "1.50", "BetType": "PUNTA"})
    derived = pipe._apply_multi_rule(base, cp.MultiRowRule(
        market_type="CORRECT_SCORE", market_name="Risultato esatto", selection_name="1 - 0"))
    assert derived["MarketType"] == "CORRECT_SCORE" and derived["SelectionName"] == "1 - 0"
    assert derived["MarketId"] == "" and derived["SelectionId"] == ""   # ID stantii azzerati
    assert derived["EventId"] == "42"                                   # evento invariato


def test_dedup_handicap_diverso_non_e_duplicato():
    # Due righe identiche ma con Handicap diverso sono scommesse DIVERSE → chiavi diverse.
    r1 = {"Provider": "PBet", "EventName": EVENT, "MarketType": "ASIAN_HANDICAP",
          "SelectionName": "Casa", "BetType": "PUNTA", "Handicap": "-0.5"}
    r2 = dict(r1, Handicap="-1.0")
    assert signal_dedupe.row_dedup_key(MSG, r1) != signal_dedupe.row_dedup_key(MSG, r2)


def test_overwrite_last_tiene_tutto_il_blocco(tmp_path):
    # In OVERWRITE_LAST l'«ultima istruzione» è il BLOCCO del messaggio: tutte e 3 le righe
    # restano attive (l'add per-riga ne avrebbe lasciata solo l'ultima).
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert res.write_error is None and len(res.rows) == 3
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0", "2 - 1", "1 - 2"]


def test_overwrite_last_preserva_riga_attiva_su_espansione(tmp_path):
    """kyh #192 (Codex #281, app.py:2129): in OVERWRITE_LAST un parser multi che prima produce UNA
    riga (A) e poi — STESSO testo, config espansa a runtime — produce A+B non deve PERDERE A. La
    riga A è ora un duplicato ma è ANCORA attiva in coda: deve restare nel blocco riscritto (tutte
    le righe dell'istruzione), non essere scartata lasciando solo la riga nuova B."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    # 1) stesso messaggio → una sola riga A ("1 - 0"): scritta e attiva.
    rows1 = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0"]), MSG, mode="NAME_ONLY"))
    write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows1, path, now=0,
                              write_rows=csv_writer.write_rows)
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0"]
    # 2) stesso testo, ora il parser espande a A+B ("1 - 0" + "2 - 1"): A è duplicata ma ATTIVA.
    rows2 = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    r2 = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows2, path, now=1,
                                   write_rows=csv_writer.write_rows)
    assert r2.write_error is None
    # A PRESERVATA: il blocco è A+B (istruzione voluta), non solo B (il bug kyh).
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0", "2 - 1"]
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)
        data = list(reader)
    sel = CSV_HEADER.index("SelectionName")
    assert [d[sel] for d in data] == ["1 - 0", "2 - 1"]


def test_overwrite_last_non_rivive_duplicato_scaduto(tmp_path):
    """P1 (Codex #281, `write_path`:205): in OVERWRITE_LAST una riga già SCADUTA dalla coda (timeout)
    ma ancora DUPLICATE nella finestra dedup NON deve essere rivissuta nel blocco (violerebbe il
    clear-timeout: XTrader rivedrebbe un segnale stantio). Scenario: A scritta a now=0 (timeout 120),
    reinvio a now=200 (A scaduta, 0+120<200) che ora espande ad A+B → si scrive SOLO B (A non rivive)."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()               # dedupe_window default 300 > timeout 120
    rows1 = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0"]), MSG, mode="NAME_ONLY"))
    write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows1, path, now=0,
                              write_rows=csv_writer.write_rows)
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0"]
    rows2 = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows2, path, now=200,
                                    write_rows=csv_writer.write_rows)
    assert res.write_error is None
    # A (scaduta) NON rivive: solo B è attiva/scritta.
    assert [r["SelectionName"] for r in q.active_rows()] == ["2 - 1"]
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)
        data = list(reader)
    sel = CSV_HEADER.index("SelectionName")
    assert [d[sel] for d in data] == ["2 - 1"]


def test_overwrite_last_due_regole_stessa_riga_non_duplica(tmp_path):
    """P1 (Codex #281, `write_path`:205): due regole multi che risolvono alla STESSA riga in UN solo
    messaggio non devono scrivere DUE righe identiche (doppia scommessa). La prima è WRITE, la
    seconda è un duplicato intra-messaggio e va soppressa: nel CSV resta UNA sola riga."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    # Due selezioni IDENTICHE ("1 - 0" due volte) → stessa riga per-riga.
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "1 - 0"]), MSG, mode="NAME_ONLY"))
    assert len(rows) == 2                                  # il parser produce 2 righe identiche…
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert res.write_error is None
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0"]   # …ma ne resta UNA sola
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)
        assert len(list(reader)) == 1                     # una sola riga dati (no doppia scommessa)


def test_overwrite_last_noop_ripristina_guardrail(tmp_path):
    """P2 (Codex #281, `write_path`:232): un commit OVERWRITE il cui blocco coincide già con l'attivo
    è un no-op (nessuna riscrittura). Se la riga risulta `WRITE` (chiave dedup non presente nel
    tracker — es. scaduta con `clear_delay` > finestra dedup) `evaluate` ha già registrato tracker e
    consumato una slot daily: il no-op DEVE ripristinare i guardrail e NON risultare `WRITE`,
    altrimenti un segnale reale successivo sarebbe limitato per errore e `_process` registrerebbe una
    scrittura mai avvenuta. Deterministico: coda pre-popolata con A + tracker VUOTO → A è `WRITE`."""
    from xtrader_bridge import safety_guard
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0"]), MSG, mode="NAME_ONLY"))
    a_row = rows[0]
    key = signal_dedupe.row_dedup_key(MSG, a_row)
    # A è GIÀ attiva in coda (timeout ampio) con la sua chiave, ma il tracker è VUOTO → al commit A
    # risulta WRITE (registra tracker + consuma daily), poi il blocco == attivo → no-op.
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=600)
    q.replace_block([dict(a_row)], keys=[key], now=0)
    tracker = signal_dedupe.SignalTracker()
    daily = safety_guard.DailyLimiter(max_per_day=5)
    calls = []

    def _spy(rows_, path_):
        calls.append(list(rows_))
        csv_writer.write_rows(rows_, path_)

    res = write_path.commit_signals(tracker, daily, q, _cfg(path), MSG, rows, path, now=1,
                                    write_rows=_spy)
    assert calls == []                                    # blocco == attivo → nessuna riscrittura
    assert res.decision != live_guard.WRITE               # no-op: NON WRITE (percorso non-write)
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0"]   # riga ancora attiva
    # Guardrail RIPRISTINATI: la registrazione WRITE annullata (tracker vuoto, daily non consumato),
    # così un non-write non intacca dedup/limiti giornalieri.
    assert tracker.state() == []
    assert daily.remaining() == 5


def test_overwrite_last_riordino_e_noop(tmp_path):
    """P2 (Codex #281, `write_path`:255): un reinvio OVERWRITE con le stesse righe **riordinate**
    (`A+B` → `B+A`, tutte ancora attive) è semanticamente identico → NON deve riscrivere il CSV
    (XTrader non deve riconsumare). Il confronto blocco/attivo è order-insensitive."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    rows_ab = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows_ab, path, now=0,
                              write_rows=csv_writer.write_rows)
    calls = []

    def _spy(rows_, path_):
        calls.append(list(rows_))
        csv_writer.write_rows(rows_, path_)

    # stesso testo, righe RIORDINATE (2 - 1 prima di 1 - 0): stesse scommesse, solo ordine diverso.
    rows_ba = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["2 - 1", "1 - 0"]), MSG, mode="NAME_ONLY"))
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows_ba, path, now=1,
                                    write_rows=_spy)
    assert calls == []                                    # riordino ≡ no-op: nessuna riscrittura
    assert res.decision != live_guard.WRITE
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0", "2 - 1"]   # ordine invariato


def _malformed_daily(count=2, max_per_day=5):
    from xtrader_bridge import safety_guard
    d = safety_guard.DailyLimiter(max_per_day=max_per_day)
    d.restore_state({"day": "giorno-corrotto", "count": count})   # giorno malformato → _UNKNOWN_DAY
    return d


def test_overwrite_last_noop_preserva_giorno_normalizzato(tmp_path):
    """P2 (Codex #281, `write_path`:264): sul no-op OVERWRITE il rollback daily deve **restituire la
    slot** (`release`) mantenendo il giorno NORMALIZZATO da `allow`, non ripristinare lo snapshot che
    reintrodurrebbe un giorno malformato (che poi `_process` ripersisterebbe, bloccando il giorno
    reale successivo). Coda pre-popolata con A + tracker vuoto → A è WRITE → consuma daily → no-op."""
    from xtrader_bridge import safety_guard
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0"]), MSG, mode="NAME_ONLY"))
    a_row = rows[0]
    key = signal_dedupe.row_dedup_key(MSG, a_row)
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=600)
    q.replace_block([dict(a_row)], keys=[key], now=0)
    tracker = signal_dedupe.SignalTracker()
    daily = _malformed_daily(count=2)
    res = write_path.commit_signals(tracker, daily, q, _cfg(path), MSG, rows, path, now=1,
                                    write_rows=csv_writer.write_rows)
    assert res.decision != live_guard.WRITE
    # Giorno NORMALIZZATO (data reale valida), non il "giorno-corrotto"/_UNKNOWN_DAY dello snapshot;
    # e la slot consumata dalla riga WRITE aged-out è stata restituita (count torna a 2).
    st = daily.state()
    assert safety_guard._is_valid_day(st["day"])
    assert st["count"] == 2


def test_commit_signals_dry_run_preserva_giorno_normalizzato(tmp_path):
    """P2 (Codex #281, app.py:2163 / DRY_RUN): in DRY_RUN il rollback daily del commit multi deve
    usare `release()` (giorno normalizzato mantenuto), non `restore_state` (che reintrodurrebbe il
    giorno malformato dello snapshot)."""
    from xtrader_bridge import safety_guard
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0"]), MSG, mode="NAME_ONLY"))
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    daily = _malformed_daily(count=2)
    cfg = {"csv_path": path, "dry_run": True}
    res = write_path.commit_signals(tracker, daily, q, cfg, MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert res.decision == live_guard.DRY_RUN
    st = daily.state()
    assert safety_guard._is_valid_day(st["day"])          # giorno normalizzato, non _UNKNOWN_DAY
    assert st["count"] == 2                                # slot DRY_RUN restituita


def test_overwrite_last_shrink_riscrive_e_segnala_write(tmp_path):
    """OVERWRITE_LAST shrink: se l'istruzione corrente ha MENO righe della precedente (config
    ridotta, stesso testo), il blocco si riduce e il CSV viene riscritto — anche se la riga rimasta
    è un duplicato (nessuna riga NUOVA). L'esito deve essere `WRITE` (c'è stata una scrittura reale),
    non `DUPLICATE`, così `_process` esegue il post-write (indicatore/note CSV)."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    rows_ab = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows_ab, path, now=0,
                              write_rows=csv_writer.write_rows)
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0", "2 - 1"]
    # stesso testo, config ridotta a solo "1 - 0": A è duplicata ma l'istruzione ora è solo A.
    rows_a = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0"]), MSG, mode="NAME_ONLY"))
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows_a, path, now=1,
                                    write_rows=csv_writer.write_rows)
    assert res.decision == live_guard.WRITE               # scrittura reale (shrink), non DUPLICATE
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0"]   # B rimossa


def test_overwrite_last_reinvio_identico_non_riscrive(tmp_path):
    """OVERWRITE_LAST: un reinvio IDENTICO (stesso testo, stesse righe, tutte duplicate ma ancora
    attive) NON deve riscrivere il CSV — XTrader non deve riconsumare righe identiche — e il blocco
    attivo resta invariato (nessuna riga persa)."""
    path = str(tmp_path / "segnali.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    tracker = signal_dedupe.SignalTracker()
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=0,
                              write_rows=csv_writer.write_rows)
    calls = []

    def _spy(rows_, path_):
        calls.append(list(rows_))
        csv_writer.write_rows(rows_, path_)

    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=1,
                                    write_rows=_spy)
    assert res.decision == "DUPLICATE"
    assert calls == []                              # nessuna riscrittura sul reinvio identico
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0", "2 - 1", "1 - 2"]


def test_commit_signals_tutte_duplicate_non_riscrive_csv(tmp_path):
    # Se TUTTE le righe sono duplicate, il CSV operativo NON deve essere riscritto (XTrader non
    # deve riconsumare righe identiche), come nel single-row su DUPLICATE.
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    tracker = signal_dedupe.SignalTracker()
    q1 = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    write_path.commit_signals(tracker, None, q1, _cfg(path), MSG, rows, path, now=0,
                              write_rows=csv_writer.write_rows)
    q2 = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    calls = []

    def _spy(rows_, path_):
        calls.append(list(rows_))
        csv_writer.write_rows(rows_, path_)

    res = write_path.commit_signals(tracker, None, q2, _cfg(path), MSG, rows, path, now=1,
                                    write_rows=_spy)
    assert res.decision == "DUPLICATE"
    assert calls == []                              # write_rows NON chiamata sui duplicati


def test_commit_signals_cap_autoraise_scrive_tutto_il_blocco(tmp_path):
    """#192 (decisione proprietario): in APPEND/QUEUE il tetto `max_active` NON spezza il blocco di
    UN messaggio multi. Con `max_active=2` e un messaggio da 3 righe, tutte e 3 entrano (auto-raise
    del tetto tramite `queue.add(force=True)`), invece di scriverne 2 e troncare la 3ª in silenzio
    (partial-drop). Elimina alla radice il partial cap-block non segnalato all'operatore."""
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    tracker = signal_dedupe.SignalTracker()
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED,
                                 default_timeout=120, max_active=2)
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert res.write_error is None and res.blocked_by_cap is False
    assert len(res.rows) == 3                        # tutte e 3 (auto-raise: blocco non spezzato)
    assert [r["SelectionName"] for r in q.active_rows()] == ["1 - 0", "2 - 1", "1 - 2"]


# ── review #281 (Codex): cap-block reporting + shadow dedupe cross-schema ──────

def _one_active_row():
    return {"EventName": "Occupante v Altro", "MarketType": "X", "SelectionName": "Y",
            "BetType": "PUNTA", "Provider": "P", "Price": "1.5"}


def test_commit_signals_cap_pieno_autoraise_aggiunge_il_blocco(tmp_path):
    """#192 (decisione proprietario, evoluzione del reporting cap di #281): anche con il tetto GIÀ
    pieno da un segnale precedente, il blocco di un messaggio multi viene aggiunto per INTERO
    (auto-raise), non bloccato. L'operatore vede una scrittura reale con tutte le righe, non un
    WRITE a 0 righe né un cap-block: il blocco coerente dell'istruzione non è mai spezzato."""
    path = str(tmp_path / "s.csv")
    q = signal_queue.SignalQueue(mode=signal_queue.APPEND_ACTIVE, default_timeout=120, max_active=1)
    q.add(_one_active_row(), now=0)                       # tetto pieno (1/1) da un segnale precedente
    tracker = signal_dedupe.SignalTracker()
    cfg = {"csv_path": path, "dry_run": False}
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    res = write_path.commit_signals(tracker, None, q, cfg, MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert res.blocked_by_cap is False                    # niente cap-block: auto-raise del tetto
    assert res.decision == live_guard.WRITE
    assert len(res.rows) == 4                             # 1 precedente + 3 righe del blocco multi
    assert len(q.active_rows()) == 4




# ── #192 kyW: dedup cross-namespace alla transizione di modalità del parser ────

def test_transizione_single_a_multi_blocca_riga_gia_scritta(tmp_path):
    """#192 kyW: un messaggio prima scritto come SINGLE-row (dedup a hash-messaggio) e poi — dopo
    che l'operatore abilita una riga multi — ritentato come MULTI non deve riscrivere la riga già
    piazzata. Il commit single-row ombreggia la chiave PER-RIGA della sua riga (`mark_seen`), così
    il commit multi la riconosce come duplicato e scrive solo le righe NUOVE."""
    path = str(tmp_path / "s.csv")
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    row_a, row_b = rows[0], rows[1]
    tracker = signal_dedupe.SignalTracker()
    q1 = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    r1 = write_path.commit_signal(tracker, None, q1, _cfg(path), MSG, row_a, path, now=0,
                                  write_rows=csv_writer.write_rows)
    assert r1.decision == live_guard.WRITE
    # MULTI (stesso messaggio, ora row_a + row_b): row_a già vista (shadow per-riga) → solo row_b.
    q2 = signal_queue.SignalQueue(mode=signal_queue.APPEND_ACTIVE, default_timeout=120)
    write_path.commit_signals(tracker, None, q2, _cfg(path), MSG, [row_a, row_b], path, now=1,
                              write_rows=csv_writer.write_rows)
    assert [x["SelectionName"] for x in q2.active_rows()] == ["2 - 1"]   # solo la riga NUOVA


def test_transizione_multi_a_single_blocca_messaggio_gia_processato(tmp_path):
    """#192 kyW: un messaggio prima scritto come MULTI (dedup PER-RIGA) e poi ritentato come
    SINGLE-row (dedup a hash-messaggio, MAI registrato dal percorso multi) non deve riscriverlo. Il
    commit multi ombreggia l'hash-messaggio (`mark_seen`), così il single-row lo riconosce come
    duplicato — anti-doppia-scommessa alla transizione di modalità."""
    path = str(tmp_path / "s.csv")
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    tracker = signal_dedupe.SignalTracker()
    q1 = signal_queue.SignalQueue(mode=signal_queue.APPEND_ACTIVE, default_timeout=120)
    r1 = write_path.commit_signals(tracker, None, q1, _cfg(path), MSG, rows, path, now=0,
                                   write_rows=csv_writer.write_rows)
    assert r1.decision == live_guard.WRITE and len(q1.active_rows()) == 2
    assert tracker.is_seen(signal_dedupe.message_hash(MSG))   # il multi ha ombreggiato l'hash-messaggio
    q2 = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    calls = []

    def _spy(rows_, path_):
        calls.append(list(rows_))
        csv_writer.write_rows(rows_, path_)

    # Retry single-row con una riga la cui CHIAVE PER-RIGA NON è stata registrata dal multi: così il
    # blocco può venire SOLO dallo shadow dell'hash-messaggio (CodeRabbit), non dal precheck per-riga.
    single_retry_row = dict(rows[0])
    single_retry_row["SelectionName"] = "__retry_riga_non_ancora_vista__"
    assert not tracker.is_seen(signal_dedupe.row_dedup_key(MSG, single_retry_row))
    r2 = write_path.commit_signal(tracker, None, q2, _cfg(path), MSG, single_retry_row, path, now=1,
                                  write_rows=_spy)
    assert r2.decision == live_guard.DUPLICATE      # hash-messaggio ombreggiato dal commit multi
    assert calls == []                              # nessuna riscrittura (niente doppia scommessa)


def test_transizione_single_a_multi_overwrite_preserva_riga_attiva(tmp_path):
    """#192 kyW (Codex): in OVERWRITE_LAST, col bridge già in esecuzione, una riga scritta come
    single-row resta in coda; abilitando il multi lo STESSO messaggio produce A+B. La riga A (ora
    DUPLICATE per lo shadow kyW) deve restare ATTIVA nel blocco (A+B), non essere scartata lasciando
    solo B — la single-row deve aver accodato A con la sua chiave per-riga (provenienza), così
    `commit_signals` (kyh) la riconosce fra le righe ancora attive."""
    path = str(tmp_path / "s.csv")
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    row_a, row_b = rows[0], rows[1]
    tracker = signal_dedupe.SignalTracker()
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    write_path.commit_signal(tracker, None, q, _cfg(path), MSG, row_a, path, now=0,
                             write_rows=csv_writer.write_rows)
    assert [x["SelectionName"] for x in q.active_rows()] == ["1 - 0"]
    # MULTI sulla STESSA coda: A è duplicata (shadow) ma ancora attiva → blocco A+B, A NON scartata.
    write_path.commit_signals(tracker, None, q, _cfg(path), MSG, [row_a, row_b], path, now=1,
                              write_rows=csv_writer.write_rows)
    assert [x["SelectionName"] for x in q.active_rows()] == ["1 - 0", "2 - 1"]


def test_transizione_stato_multi_persistito_blocca_single(tmp_path):
    """#192 kyW (Codex): stato dedupe PERSISTITO dal percorso MULTI (solo chiavi per-riga). Dopo un
    passaggio a single-row, un retry dello stesso segnale deve risultare DUPLICATE PRIMA della
    scrittura (controllo cross-namespace sulla chiave per-riga), non essere riscritto → doppia
    scommessa."""
    path = str(tmp_path / "s.csv")
    row_a = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0"]), MSG, mode="NAME_ONLY"))[0]
    tracker = signal_dedupe.SignalTracker()
    tracker.register(MSG, key=signal_dedupe.row_dedup_key(MSG, row_a))   # stato "persistito" dal multi
    q = signal_queue.SignalQueue(mode=signal_queue.OVERWRITE_LAST, default_timeout=120)
    calls = []

    def _spy(rows_, path_):
        calls.append(list(rows_))
        csv_writer.write_rows(rows_, path_)

    res = write_path.commit_signal(tracker, None, q, _cfg(path), MSG, row_a, path, now=1,
                                   write_rows=_spy)
    assert res.decision == live_guard.DUPLICATE
    assert calls == []                              # niente scrittura (niente doppia scommessa)


def test_transizione_stato_single_persistito_blocca_multi(tmp_path):
    """#192 kyW (Codex): stato dedupe PERSISTITO dal percorso SINGLE-row (solo hash-messaggio, tipico
    di un upgrade da versione pre-kyW). Dopo un passaggio a multi-riga, un retry dello stesso
    messaggio deve essere soppresso (fail-closed) PRIMA della scrittura, non riscritto → doppia
    scommessa."""
    path = str(tmp_path / "s.csv")
    rows = _rows(pipe.build_validated_rows(
        _multiselection_parser_with(["1 - 0", "2 - 1"]), MSG, mode="NAME_ONLY"))
    tracker = signal_dedupe.SignalTracker()
    tracker.register(MSG)                           # stato "persistito" dal single: solo hash-messaggio
    q = signal_queue.SignalQueue(mode=signal_queue.APPEND_ACTIVE, default_timeout=120)
    calls = []

    def _spy(rows_, path_):
        calls.append(list(rows_))
        csv_writer.write_rows(rows_, path_)

    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=1,
                                    write_rows=_spy)
    assert res.decision == live_guard.DUPLICATE
    assert calls == [] and q.active_rows() == []    # blocco soppresso, nessuna scrittura
