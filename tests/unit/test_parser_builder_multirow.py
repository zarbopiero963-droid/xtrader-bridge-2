"""Test hard del controller multi-riga (#192, PR2) — `parser_builder.ParserBuilder`.

La GUI (`custom_parser_gui.py`) è una vista sottile non testabile in CI (richiede display):
TUTTA la logica multi-riga che la GUI usa vive qui nel controller ed è esercitata da questi
test con le funzioni REALI del progetto — round-trip dei campi multi in `to_def()`/`__init__`,
gestione righe MultiMarket/MultiSelection, avvisi, e l'anteprima `preview_rows()` (che usa lo
stesso motore del runtime, `custom_pipeline.build_validated_rows`).

Regressione bloccata: prima di PR2 `to_def()` SCARTAVA i campi multi, quindi un parser
MultiMarket configurato via builder generava 1 sola riga; questi test falliscono su quel codice.
"""

import importlib
import inspect
import os
import sys
import types

import pytest

from xtrader_bridge import csv_writer
from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_builder as pb
from xtrader_bridge import recognition
from xtrader_bridge import validator
from xtrader_bridge.csv_writer import CSV_HEADER


@pytest.fixture(autouse=True)
def _restore_csv_language():
    """L'anteprima localizza i decimali con la lingua CSV corrente (#342): ripristina lo
    stato del modulo dopo ogni test, così un set_csv_language qui non inquina altri file."""
    prev = csv_writer.get_csv_language()
    yield
    csv_writer.set_csv_language(prev)

# Messaggio reale della issue #192.
MSG = (
    "P.Bet. PREMACHT 0,5HT 🔊 ✅\n"
    "🏆Saudi Professional League\n"
    "🆚Al-Kholood Club v Al-Hilal\n"
    "⚽ 0 - 0\n"
    "⌚ 1m\n"
)
EVENT = "Al-Kholood Club v Al-Hilal"


def _base_builder(extra_rules=()):
    """Builder con la riga base valida (Provider + EventName estratto + Price + BetType)."""
    b = pb.ParserBuilder()
    b.name = "MultiTest"
    b.mode = "NAME_ONLY"
    b.add_rule(target="Provider", fixed_value="PBet")
    b.add_rule(target="EventName", start_after="🆚", end_before="\n", required=True)
    b.add_rule(target="Price", fixed_value="1.50", required=True)
    b.add_rule(target="BetType", fixed_value="PUNTA", required=True)
    for r in extra_rules:
        b.rules.append(r)
    return b


def _multimarket_builder():
    b = _base_builder()
    b.multi_market_enabled = True
    b.add_multi_market(market_type="FIRST_HALF_GOALS_05",
                       market_name="1º tempo - Totale goal 0,5", selection_name="Over 0,5")
    b.add_multi_market(market_type="OVER_UNDER_15", market_name="Totale goal 1,5",
                       selection_name="Over 1,5")
    return b


def _multiselection_builder():
    # La base fornisce MarketType/MarketName: le selezioni ereditano il mercato.
    b = _base_builder(extra_rules=[
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
    ])
    b.multi_selection_enabled = True
    b.add_multi_selection(selection_name="1 - 0")
    b.add_multi_selection(selection_name="2 - 1")
    b.add_multi_selection(selection_name="1 - 2")
    return b


# ── round-trip dei campi multi (la regressione principale di PR2) ─────────────

def test_to_def_includes_multi_fields():
    b = _multimarket_builder()
    defn = b.to_def()
    assert defn.multi_market_enabled is True
    assert defn.multi_selection_enabled is False
    assert len(defn.multi_markets) == 2
    assert defn.multi_markets[0].market_type == "FIRST_HALF_GOALS_05"
    assert defn.active_multi_markets() == defn.multi_markets


def test_builder_from_def_reloads_multi_deep_copy():
    defn = _multimarket_builder().to_def()
    b2 = pb.ParserBuilder(defn)
    assert b2.multi_market_enabled is True
    assert len(b2.multi_markets) == 2
    assert b2.multi_markets[1].selection_name == "Over 1,5"
    # Copia profonda: mutare il builder NON deve toccare il def originale (no aliasing).
    b2.multi_markets[0].market_type = "MUTATED"
    assert defn.multi_markets[0].market_type == "FIRST_HALF_GOALS_05"


def test_add_and_remove_multi_rows():
    b = _base_builder()
    b.add_multi_market(market_type="A")
    b.add_multi_market(market_type="B")
    b.add_multi_selection(selection_name="S1")
    assert len(b.multi_markets) == 2 and len(b.multi_selections) == 1
    b.remove_multi_market(0)
    assert [r.market_type for r in b.multi_markets] == ["B"]
    b.remove_multi_selection(0)
    assert b.multi_selections == []


# ── anteprima multi-riga (stesso motore del runtime) ──────────────────────────

def test_preview_rows_single_when_no_multi():
    b = _base_builder(extra_rules=[
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="1 - 0", required=True),
    ])
    rows = b.preview_rows(MSG, mode="NAME_ONLY")
    assert len(rows) == 1
    assert rows[0].kind == "base"
    assert rows[0].placeable is True
    assert rows[0].status == validator.VALID
    assert rows[0].row["EventName"] == EVENT
    assert list(rows[0].row.keys()) == CSV_HEADER
    assert "EventName=" in rows[0].summary


def test_preview_rows_multimarket_two_rows():
    rows = _multimarket_builder().preview_rows(MSG, mode="NAME_ONLY")
    assert len(rows) == 2
    assert [r.kind for r in rows] == ["market", "market"]
    assert all(r.placeable for r in rows)
    assert [r.row["MarketType"] for r in rows] == ["FIRST_HALF_GOALS_05", "OVER_UNDER_15"]
    assert [r.row["SelectionName"] for r in rows] == ["Over 0,5", "Over 1,5"]
    # L'evento comune (dalla base) è ereditato da tutte le righe.
    assert all(r.row["EventName"] == EVENT for r in rows)


def test_preview_rows_multiselection_three_rows():
    rows = _multiselection_builder().preview_rows(MSG, mode="NAME_ONLY")
    assert len(rows) == 3
    assert [r.kind for r in rows] == ["selection", "selection", "selection"]
    assert [r.row["SelectionName"] for r in rows] == ["1 - 0", "2 - 1", "1 - 2"]
    # Tutte ereditano il mercato dalla base.
    assert all(r.row["MarketType"] == "CORRECT_SCORE" for r in rows)
    assert all(r.placeable for r in rows)


def test_preview_rows_both_active_separate_not_cartesian():
    b = _multiselection_builder()
    b.multi_market_enabled = True
    b.add_multi_market(market_type="FIRST_HALF_GOALS_05",
                       market_name="1º tempo - Totale goal 0,5", selection_name="Over 0,5")
    b.add_multi_market(market_type="OVER_UNDER_15", market_name="Totale goal 1,5",
                       selection_name="Over 1,5")
    rows = b.preview_rows(MSG, mode="NAME_ONLY")
    # 2 mercati PRIMA, poi 3 selezioni: 5 righe SEPARATE, mai il prodotto cartesiano (≠ 6).
    assert len(rows) == 5
    assert [r.kind for r in rows] == ["market", "market", "selection", "selection", "selection"]
    assert [r.row["MarketType"] for r in rows] == [
        "FIRST_HALF_GOALS_05", "OVER_UNDER_15", "CORRECT_SCORE", "CORRECT_SCORE", "CORRECT_SCORE"]


def test_preview_rows_partial_invalid_does_not_block_others():
    b = _multiselection_builder()
    # Una selezione che azzera il mercato base e non ne fornisce uno proprio → riga non
    # piazzabile, ma NON deve bloccare le altre due valide.
    b.add_multi_selection(selection_name="")  # override vuoto: eredita, resta valida...
    b.multi_selections[-1].selection_name = ""  # esplicitamente vuota
    rows = b.preview_rows(MSG, mode="NAME_ONLY")
    placeable = [r for r in rows if r.placeable]
    assert len(placeable) >= 3            # le tre selezioni nominate restano piazzabili
    assert any(r.row["SelectionName"] == "2 - 1" for r in placeable)


def test_preview_rows_backward_compat_legacy_def():
    # Un parser legacy (dict senza campi multi) → builder → 1 sola riga base.
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
    b = pb.ParserBuilder(legacy)
    assert b.multi_market_enabled is False and b.multi_selection_enabled is False
    rows = b.preview_rows(MSG, mode="NAME_ONLY")
    assert len(rows) == 1 and rows[0].kind == "base" and rows[0].placeable


# ── avvisi non bloccanti ──────────────────────────────────────────────────────

def test_multi_warnings_both_active():
    b = _multiselection_builder()
    b.multi_market_enabled = True
    b.add_multi_market(market_type="OVER_UNDER_15", market_name="Totale goal 1,5",
                       selection_name="Over 1,5")
    warnings = b.multi_warnings()
    assert any("SEPARATE" in w for w in warnings)


def test_multi_warnings_enabled_but_no_rows():
    b = _base_builder()
    b.multi_market_enabled = True            # attivo ma nessuna riga
    warnings = b.multi_warnings()
    assert any("nessuna riga extra" in w for w in warnings)


def test_multi_warnings_silent_when_single_row():
    assert _base_builder().multi_warnings() == []


# ── persistenza: save → load preserva la config multi ─────────────────────────

def test_save_load_roundtrip_preserves_multi(tmp_path):
    b = _multimarket_builder()
    path = b.save(str(tmp_path))
    assert os.path.exists(path)
    b2 = pb.ParserBuilder.load(path)
    assert b2.multi_market_enabled is True
    assert [r.market_type for r in b2.multi_markets] == ["FIRST_HALF_GOALS_05", "OVER_UNDER_15"]
    # E l'anteprima dal parser ricaricato genera ancora le 2 righe mercato.
    rows = b2.preview_rows(MSG, mode="NAME_ONLY")
    assert len(rows) == 2 and all(r.placeable for r in rows)


# ── verdetto sintetico multi-riga (`preview_summary`, Codex P2) ───────────────

def _pr(**kw):
    """PreviewRow di comodo per i test del verdetto sintetico."""
    base = dict(index=0, kind="market", placeable=True, status=validator.VALID,
                missing_required=[], row={}, summary="")
    base.update(kw)
    return pb.PreviewRow(**base)


def test_preview_summary_all_placeable():
    rows = [_pr(index=0), _pr(index=1)]
    msg = pb.ParserBuilder.preview_summary(rows)
    assert msg.startswith("✅ Pronto") and "2 righe" in msg


def test_preview_summary_none_placeable_lists_status():
    rows = [_pr(placeable=False, status="INVALID_MISSING_FIELDS")]
    msg = pb.ParserBuilder.preview_summary(rows)
    assert msg.startswith("⛔") and "INVALID_MISSING_FIELDS" in msg


def test_preview_summary_partial():
    rows = [_pr(index=0, placeable=True),
            _pr(index=1, placeable=False, status="INVALID_MISSING_FIELDS")]
    msg = pb.ParserBuilder.preview_summary(rows)
    assert msg.startswith("⚠") and "1/2" in msg


def test_preview_summary_empty():
    assert pb.ParserBuilder.preview_summary([]).startswith("⛔")


# ── verdetto sintetico single-row (`test_verdict`, Codex #19) ─────────────────

def _base_pr(**kw):
    """PreviewRow single-row (kind='base') di comodo per i test del verdetto."""
    base = dict(index=0, kind="base", placeable=True, status=validator.VALID,
                missing_required=[], row={}, summary="")
    base.update(kw)
    return pb.PreviewRow(**base)


def test_test_verdict_errori_strutturali_non_salvabile():
    # #19 (Codex P2): un parser con errori STRUTTURALI (che Save rifiuterebbe) non deve mai
    # risultare «Pronto», anche se per caso la pipeline produce una riga piazzabile.
    errors = ["Regola #1 (Provider): ha sia 'fixed_value' sia 'start_after'/'end_before' (…)."]
    msg = pb.ParserBuilder.test_verdict(
        errors, [_base_pr(placeable=True)], diag_placeable=True, diag_status=validator.VALID,
        res_row={"Provider": "TG"}, res_missing_required=[], res_detail=None)
    assert msg.startswith("⛔ Non salvabile")
    assert "fixed_value" in msg
    assert "✅" not in msg


def test_test_verdict_missing_recognition_fields_elencati():
    # #19 (Codex P2): su INVALID_MISSING_FIELDS il verdetto deve dire QUALE campo di
    # riconoscimento manca (in res.detail), non solo lo status. `missing_required` (gate
    # parser) è vuoto in questo caso.
    msg = pb.ParserBuilder.test_verdict(
        [], [_base_pr(placeable=False, status=validator.INVALID_MISSING_FIELDS)],
        diag_placeable=False, diag_status=validator.INVALID_MISSING_FIELDS,
        res_row={"EventName": "Inter v Milan"}, res_missing_required=[], res_detail=["MarketType"])
    assert msg.startswith("⛔ Non pronto")
    assert "INVALID_MISSING_FIELDS" in msg
    assert "mancanti: MarketType" in msg


def test_test_verdict_bounds_detail_non_scambiato_per_mancanti():
    # Il detail di INVALID_PRICE_BOUNDS è una TUPLA di colonne (Min/Max che offendono),
    # NON campi mancanti: non deve diventare «mancanti: …».
    msg = pb.ParserBuilder.test_verdict(
        [], [_base_pr(placeable=False, status="INVALID_PRICE_BOUNDS")],
        diag_placeable=False, diag_status="INVALID_PRICE_BOUNDS",
        res_row={}, res_missing_required=[], res_detail=("MinPrice", "MaxPrice"))
    assert "INVALID_PRICE_BOUNDS" in msg
    assert "mancanti" not in msg


def test_test_verdict_pronto_single_row():
    # Lingua EN = separatore punto: il verdetto mostra i decimali CANONICI (col punto).
    csv_writer.set_csv_language("EN")
    msg = pb.ParserBuilder.test_verdict(
        [], [_base_pr(placeable=True)], diag_placeable=True, diag_status=validator.VALID,
        res_row={"EventName": "Inter v Milan", "Price": "1.85", "Handicap": ""},
        res_missing_required=[], res_detail=None)
    assert msg.startswith("✅ Pronto")
    assert "EventName=Inter v Milan" in msg and "Price=1.85" in msg
    assert "Handicap" not in msg              # i vuoti non compaiono


def test_test_verdict_pronto_decimali_localizzati_it():
    # #342 follow-up (#344): il verdetto mostra i decimali COME usciranno nel file — con
    # csv_language IT la Price è «1,85» (virgola), non il canonico interno «1.85».
    csv_writer.set_csv_language("IT")
    msg = pb.ParserBuilder.test_verdict(
        [], [_base_pr(placeable=True)], diag_placeable=True, diag_status=validator.VALID,
        res_row={"EventName": "Inter v Milan", "Price": "1.85"},
        res_missing_required=[], res_detail=None)
    assert "Price=1,85" in msg
    assert "Price=1.85" not in msg
    assert "EventName=Inter v Milan" in msg   # le colonne testuali NON sono toccate


def test_test_verdict_multi_delega_a_preview_summary():
    # Con output multi-riga attivo (e contenuto estratto) il verdetto si basa sulle righe generate.
    rows = [_pr(index=0, kind="market", placeable=True),
            _pr(index=1, kind="market", placeable=False, status="INVALID_MISSING_FIELDS")]
    msg = pb.ParserBuilder.test_verdict(
        [], rows, diag_placeable=False, diag_status="X",
        res_row={}, res_missing_required=[], res_detail=None, content_ok=True)
    assert msg == pb.ParserBuilder.preview_summary(rows)


def test_test_verdict_multi_onora_no_content_match():
    """#192 (Codex): con output multi-riga, se il gate di contenuto whole-message fallisce
    (`content_ok=False`, cioè il parser non estrae NULLA dal messaggio → il runtime scarterebbe
    con NO_CONTENT_MATCH), il verdetto NON deve dire «✅ Pronto · N righe» anche se le righe
    generate sono piazzabili — deve segnalare NO_CONTENT_MATCH come il runtime.

    Fail-first: prima di questo fix il ramo multi ritornava sempre `preview_summary`, ignorando
    il gate → «✅ Pronto» per un parser che il runtime non scriverebbe (over-promise)."""
    rows = [_pr(index=0, kind="market", placeable=True),
            _pr(index=1, kind="market", placeable=True)]
    msg = pb.ParserBuilder.test_verdict(
        [], rows, diag_placeable=False, diag_status="X",
        res_row={}, res_missing_required=[], res_detail=None, content_ok=False)
    assert msg.startswith("⛔")
    assert "NO_CONTENT_MATCH" in msg
    assert "Pronto" not in msg
    # controprova: con content_ok=True le stesse righe danno il verdetto positivo di preview_summary.
    ok = pb.ParserBuilder.test_verdict(
        [], rows, diag_placeable=False, diag_status="X",
        res_row={}, res_missing_required=[], res_detail=None, content_ok=True)
    assert ok == pb.ParserBuilder.preview_summary(rows) and ok.startswith("✅ Pronto")


def test_test_verdict_multi_content_gate_solo_se_riga_piazzabile():
    """#192 (Codex, follow-up): il gate NO_CONTENT_MATCH nel ramo multi va applicato SOLO se
    esiste almeno una riga piazzabile — come il runtime (`signal_router`: controlla
    `matches_message` DOPO aver trovato righe piazzabili; con zero piazzabili ritorna lo status
    di validazione reale). Con ZERO righe piazzabili + `content_ok=False` il verdetto NON deve
    mascherare l'errore reale con NO_CONTENT_MATCH, ma mostrare `preview_summary` (gli status
    delle righe scartate), così l'utente vede QUALE validazione blocca.

    Fail-first: prima del fix il ramo multi ritornava NO_CONTENT_MATCH per `content_ok=False`
    indipendentemente dalla piazzabilità → mascherava il vero errore bloccante."""
    rows = [_pr(index=0, kind="market", placeable=False, status="INVALID_MISSING_FIELDS"),
            _pr(index=1, kind="market", placeable=False, status="INVALID_PRICE_BOUNDS")]
    msg = pb.ParserBuilder.test_verdict(
        [], rows, diag_placeable=False, diag_status="X",
        res_row={}, res_missing_required=[], res_detail=None, content_ok=False)
    assert msg == pb.ParserBuilder.preview_summary(rows)     # status reali, NON mascherati
    assert "NO_CONTENT_MATCH" not in msg
    assert "INVALID_MISSING_FIELDS" in msg


# ── il salvataggio NON azzera i campi multi non esposti (Codex P1) ────────────
# La GUI espone solo `_MULTI_FIELDS`: i campi min_price/max_price/points/start_after/
# end_before di una regola CARICATA devono sopravvivere al salvataggio. La logica vive nel
# controller (`merge_multi_rule_overrides`, pura) ed è qui testata direttamente; più sotto
# si esercita anche il VERO metodo della vista (stub di customtkinter) per coprire il wrapper.

def test_apply_mode_defaults_marca_obbligatori_su_parser_nuovo():
    # #72 (Codex P2): un parser NUOVO deve avere i campi del set della modalità già
    # "Obblig.". Le 14 colonne vanno create PRIMA di allineare la modalità: chiamare
    # set_mode su un builder senza regole non marcherebbe nulla (auto-Obblig. non applicata).
    b = pb.ParserBuilder()   # nuovo, senza regole
    b.apply_mode_defaults(recognition.NAME_ONLY)
    req = {r.target: r.required for r in b.rules}
    assert req["EventName"] is True
    assert req["MarketType"] is True
    assert req["SelectionName"] is True
    # un campo NON di riconoscimento resta facoltativo
    assert req["MinPrice"] is False


def test_ensure_all_columns_preserva_regole_duplicate():
    # #72 (Codex P2): regole duplicate (JSON manomesso/corrotto) NON devono essere droppate
    # in silenzio dalla griglia fissa: restano così che `validate_parser_def` le segnali e il
    # salvataggio sia bloccato, invece di persistere una definizione alterata senza avviso.
    b = pb.ParserBuilder()
    b.rules = [cp.FieldRule(target="EventName", start_after="A", required=True),
               cp.FieldRule(target="EventName", start_after="B", required=True),  # duplicato
               cp.FieldRule(target="Price", fixed_value="1.85")]
    b.ensure_all_columns()
    ev = [r for r in b.rules if r.target == "EventName"]
    assert len(ev) == 2                                    # entrambe le regole preservate
    assert any("duplicat" in e.lower() for e in b.errors())   # validate le segnala


def test_merge_multi_rule_overrides_preserves_hidden_fields():
    source = cp.MultiRowRule(
        market_type="OLD_MT", selection_name="OLD_SEL",
        min_price="1.20", max_price="3.50", points="2", start_after="[", end_before="]")
    rule = pb.ParserBuilder.merge_multi_rule_overrides(
        source, {"market_type": "NEW_MT", "market_name": "", "selection_name": "Over 0,5",
                 "price": "", "bet_type": "", "handicap": ""}, enabled=True)
    # Campi NON esposti: PRESERVATI dalla sorgente.
    assert rule.min_price == "1.20" and rule.max_price == "3.50" and rule.points == "2"
    assert rule.start_after == "[" and rule.end_before == "]"
    # Override visibili: APPLICATI; sorgente NON mutata (copia difensiva).
    assert rule.market_type == "NEW_MT" and rule.selection_name == "Over 0,5"
    assert rule.enabled is True and source.market_type == "OLD_MT"


def test_merge_multi_rule_overrides_new_row_no_hidden_values():
    rule = pb.ParserBuilder.merge_multi_rule_overrides(
        cp.MultiRowRule(), {"market_type": "", "market_name": "", "selection_name": "1 - 0",
                            "price": "", "bet_type": "", "handicap": ""}, enabled=True)
    assert rule.selection_name == "1 - 0"
    assert rule.min_price == "" and rule.max_price == "" and rule.points == ""


# ── vista: il VERO `_multi_rule_from_refs` preserva i campi nascosti (stub Tk) ─

class _FakeVar:
    """Stub di StringVar/BooleanVar: espone solo `.get()` (niente display Tk)."""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo è una classe reale vuota, così il modulo GUI
    si importa headless e si può esercitare il vero metodo su un `self` finto."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


def test_gui_multi_rule_from_refs_preserves_hidden_fields(monkeypatch):
    # Esercita il VERO metodo della vista `CustomParserPanel._multi_rule_from_refs` (che
    # delega al controller), stubbando customtkinter SOLO se assente (in CI lo è).
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    gui = importlib.import_module("xtrader_bridge.custom_parser_gui")

    source = cp.MultiRowRule(market_type="OLD_MT", min_price="1.20", points="2",
                             start_after="[", end_before="]")
    refs = {
        "_rule": source,
        "market_type": _FakeVar("NEW_MT"), "market_name": _FakeVar(""),
        "selection_name": _FakeVar("Over 0,5"), "price": _FakeVar(""),
        "bet_type": _FakeVar(""), "handicap": _FakeVar(""), "enabled": _FakeVar(True),
    }
    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)   # no __init__: nessun widget
    rule = panel._multi_rule_from_refs(refs)
    assert rule.min_price == "1.20" and rule.points == "2"          # preservati
    assert rule.start_after == "[" and rule.end_before == "]"
    assert rule.market_type == "NEW_MT" and rule.selection_name == "Over 0,5"   # applicati
    assert rule.enabled is True


# ── #325 slice 2: delimitatori «Inizia dopo/Finisce prima» sulle righe SELEZIONE ─

def _gui_module(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    return importlib.import_module("xtrader_bridge.custom_parser_gui")


def test_gui_selection_fields_espongono_delimitatori_solo_sulle_selezioni(monkeypatch):
    # #325 slice 2: i delimitatori sono esposti SOLO sulle righe SELEZIONE; le righe MERCATO
    # restano senza (lì sarebbero solo la misconfigurazione da cui il gate #341 difende).
    gui = _gui_module(monkeypatch)
    sel_attrs = [a for a, _, _ in gui.CustomParserPanel._MULTI_SELECTION_FIELDS]
    mkt_attrs = [a for a, _, _ in gui.CustomParserPanel._MULTI_FIELDS]
    assert "start_after" in sel_attrs and "end_before" in sel_attrs
    assert "start_after" not in mkt_attrs and "end_before" not in mkt_attrs
    # le colonne base restano identiche (nessuna rimozione: solo aggiunta in coda)
    assert sel_attrs[:len(mkt_attrs)] == mkt_attrs


def test_gui_multi_rule_from_refs_selezione_applica_delimitatori(monkeypatch):
    # Il VERO `_multi_rule_from_refs` con `_fields` = campi SELEZIONE applica anche i
    # delimitatori digitati (fail-first sul threading di `_fields`: iterando sempre
    # `_MULTI_FIELDS` i delimitatori resterebbero quelli della sorgente).
    gui = _gui_module(monkeypatch)
    refs = {
        "_rule": cp.MultiRowRule(), "_fields": gui.CustomParserPanel._MULTI_SELECTION_FIELDS,
        "market_type": _FakeVar(""), "market_name": _FakeVar(""),
        "selection_name": _FakeVar(""), "price": _FakeVar(""),
        "bet_type": _FakeVar(""), "handicap": _FakeVar(""),
        "start_after": _FakeVar("Risultati:"), "end_before": _FakeVar("\n"),
        "enabled": _FakeVar(True),
    }
    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)
    rule = panel._multi_rule_from_refs(refs)
    assert rule.start_after == "Risultati:"
    # «\n» NON strippato (stesso contratto della griglia base): un delimitatore whitespace
    # è legittimo e non deve sparire a ogni apri+salva.
    assert rule.end_before == "\n"
    assert rule.selection_name == ""   # selezione vuota + delimitatore → riga dinamica (#325)


def test_gui_multi_rule_from_refs_selezione_svuotare_cancella_delimitatori(monkeypatch):
    # Campo ESPOSTO svuotato dall'utente = intento esplicito → il delimitatore va CANCELLATO
    # (non più "campo nascosto da preservare"): la riga torna fissa/inerte.
    gui = _gui_module(monkeypatch)
    source = cp.MultiRowRule(start_after="[", end_before="]", min_price="1.20")
    refs = {
        "_rule": source, "_fields": gui.CustomParserPanel._MULTI_SELECTION_FIELDS,
        "market_type": _FakeVar(""), "market_name": _FakeVar(""),
        "selection_name": _FakeVar("1 - 0"), "price": _FakeVar(""),
        "bet_type": _FakeVar(""), "handicap": _FakeVar(""),
        "start_after": _FakeVar(""), "end_before": _FakeVar(""),
        "enabled": _FakeVar(True),
    }
    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)
    rule = panel._multi_rule_from_refs(refs)
    assert rule.start_after == "" and rule.end_before == ""   # cancellati (esposti)
    assert rule.min_price == "1.20"                           # non esposto → preservato


def test_gui_multi_rule_from_refs_mercato_preserva_delimitatori(monkeypatch):
    # Riga MERCATO (`_fields` = _MULTI_FIELDS): i delimitatori NON sono esposti → restano
    # preservati dalla sorgente (comportamento Codex P1 invariato per i mercati).
    gui = _gui_module(monkeypatch)
    source = cp.MultiRowRule(market_type="OLD", start_after="[", end_before="]")
    refs = {
        "_rule": source, "_fields": gui.CustomParserPanel._MULTI_FIELDS,
        "market_type": _FakeVar("OVER_UNDER_25"), "market_name": _FakeVar(""),
        "selection_name": _FakeVar(""), "price": _FakeVar(""),
        "bet_type": _FakeVar(""), "handicap": _FakeVar(""),
        "enabled": _FakeVar(True),
    }
    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)
    rule = panel._multi_rule_from_refs(refs)
    assert rule.start_after == "[" and rule.end_before == "]"   # preservati
    assert rule.market_type == "OVER_UNDER_25"


# ── #192 (Codex): il resolver ID dell'anteprima è best-effort/fail-open ───────

def _headless_panel(monkeypatch, factory):
    """Costruisce un `CustomParserPanel` headless (no __init__/no widget) con la sola
    factory del resolver impostata, per esercitare il VERO `_preview_id_resolver`."""
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    gui = importlib.import_module("xtrader_bridge.custom_parser_gui")
    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)   # no __init__: nessun widget
    panel._id_resolver_factory = factory
    return panel


def test_preview_id_resolver_senza_factory_ritorna_none(monkeypatch):
    """Senza factory (app non l'ha fornita) l'anteprima resta conservativa: `None`."""
    panel = _headless_panel(monkeypatch, None)
    assert panel._preview_id_resolver() is None


def test_preview_id_resolver_invoca_la_factory(monkeypatch):
    """Con factory presente ritorna il resolver che essa produce (così «Prova messaggio»
    usa lo stesso dizionario del runtime)."""
    sentinel = object()
    calls = []

    def factory():
        calls.append(1)
        return sentinel

    panel = _headless_panel(monkeypatch, factory)
    assert panel._preview_id_resolver() is sentinel
    assert calls == [1]                                # la factory è stata invocata


def test_preview_id_resolver_fail_open_su_eccezione(monkeypatch):
    """Fail-open: una factory che solleva NON deve far crashare l'anteprima → `None`
    (comportamento conservativo storico, nessun effetto sul runtime reale)."""
    def boom():
        raise RuntimeError("dizionario non disponibile")

    panel = _headless_panel(monkeypatch, boom)
    assert panel._preview_id_resolver() is None


# ── kyb (#192): round-trip COMPLETO su disco preserva i campi multi nascosti ──

def test_kyb_full_disk_roundtrip_preserva_campi_multi_nascosti(tmp_path):
    """kyb (#192): il ciclo COMPLETO apri→salva→ricarica di un parser multi NON deve azzerare
    in silenzio i campi per-riga NON esposti dalla GUI (`min_price`/`max_price`/`points`/
    `start_after`/`end_before`) — né `handicap` (esposto) né il flag `enabled`. Esercita la catena REALE end-to-end:
    `ParserBuilder → to_def → save_parser` (JSON su disco) `→ load_parser → ParserBuilder → to_def`.

    Regressione bloccata: se un qualsiasi anello del round-trip (`to_def`, `__init__`,
    `MultiRowRule.to_dict/from_dict`, `CustomParserDef.to_dict/from_dict`) tornasse a SCARTARE i
    campi multi — com'era prima di #240 — questo test fallirebbe. È il guard end-to-end che
    mancava (gli altri test coprono i singoli layer, non l'intero ciclo su disco coi campi nascosti)."""
    b = _base_builder(extra_rules=[
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
    ])
    b.name = "MultiHidden"
    b.multi_selection_enabled = True
    # Riga con campi VISIBILI (selection_name) + NASCOSTI valorizzati.
    b.add_multi_selection(selection_name="1 - 0", min_price="1.20", max_price="3.50",
                          points="2", start_after="[", end_before="]", handicap="-0.5")
    b.add_multi_selection(selection_name="2 - 1", enabled=False)   # anche il flag enabled

    # apri→salva su DISCO (JSON) → ricarica → ri-costruisci il builder (come "Carica" in GUI) → to_def
    path = cp.save_parser(b.to_def(), str(tmp_path))
    reloaded = pb.ParserBuilder(cp.load_parser(path)).to_def()

    assert reloaded.multi_selection_enabled is True
    assert len(reloaded.multi_selections) == 2
    r0, r1 = reloaded.multi_selections
    assert r0.selection_name == "1 - 0"
    # campi NASCOSTI (min_price/max_price/points/start_after/end_before) preservati end-to-end...
    assert r0.min_price == "1.20" and r0.max_price == "3.50" and r0.points == "2"
    assert r0.start_after == "[" and r0.end_before == "]"
    assert r0.handicap == "-0.5"      # ...e handicap (campo VISIBILE) round-trip completo
    # flag `enabled` preservato: una riga disabilitata non "resuscita" attiva
    assert r1.selection_name == "2 - 1" and r1.enabled is False


# ── PR-cestino (follow-up review #341/#344): avvisi per-riga sulle selezioni ──
# La detection specchia `custom_pipeline._is_dynamic_selection`: gli avvisi devono dire
# all'utente ESATTAMENTE quando il runtime ignora i delimitatori (Selezione fissa) o non
# attiva l'estrazione dinamica (mercato effettivo non-punteggio, gate #341).

def test_warning_selezione_fissa_con_delimitatori():
    # Config ambigua: Selezione fissa + delimitatori → il runtime IGNORA i delimitatori.
    b = _multiselection_builder()
    b.multi_selections[1].start_after = "⚽"
    warnings = b.multi_warnings()
    assert any("Riga selezione 2" in w and "IGNORATI" in w for w in warnings)
    # le righe senza delimitatori non generano avvisi per-riga
    assert not any("Riga selezione 1" in w or "Riga selezione 3" in w for w in warnings)


def test_no_warning_dinamica_su_mercato_punteggio():
    # Selezione vuota + delimitatori + base fissa CORRECT_SCORE → estrazione ATTIVA: silenzio.
    b = _multiselection_builder()
    b.add_multi_selection(selection_name="", start_after="⚽")
    assert not any("Riga selezione" in w for w in b.multi_warnings())


def test_warning_dinamica_inattiva_override_non_punteggio():
    # L'override MarketType della riga vince sulla base: MATCH_ODDS non è un mercato-punteggio
    # → la riga resta FISSA (gate #341) e l'avviso lo dice, citando il mercato.
    b = _multiselection_builder()
    b.add_multi_selection(selection_name="", start_after="⚽", market_type="MATCH_ODDS")
    warnings = b.multi_warnings()
    assert any("Riga selezione 4" in w and "INATTIVA" in w and "MATCH_ODDS" in w
               for w in warnings)


def test_warning_dinamica_inattiva_base_fissa_non_punteggio():
    # Nessun override sulla riga: conta il MarketType FISSO della base (statico → certo).
    b = _base_builder(extra_rules=[cp.FieldRule(target="MarketType", fixed_value="MATCH_ODDS")])
    b.multi_selection_enabled = True
    b.add_multi_selection(selection_name="", end_before="⌚")
    warnings = b.multi_warnings()
    assert any("Riga selezione 1" in w and "INATTIVA" in w for w in warnings)


def test_warning_dinamica_inattiva_mercato_vuoto():
    # Base SENZA regola MarketType (e nessuna mappatura mercati): mercato effettivo statico
    # = "" → non-punteggio certo → avviso con "(vuoto)".
    b = _base_builder()
    b.multi_selection_enabled = True
    b.add_multi_selection(selection_name="", start_after="⚽")
    warnings = b.multi_warnings()
    assert any("(vuoto)" in w and "INATTIVA" in w for w in warnings)


def test_no_warning_se_mercato_base_noto_solo_a_runtime():
    # MarketType estratto dal messaggio → il mercato effettivo è ignoto staticamente:
    # NESSUN falso allarme (fail-safe: meglio tacere che gridare al lupo).
    b = _base_builder(extra_rules=[cp.FieldRule(target="MarketType", start_after="🏆")])
    b.multi_selection_enabled = True
    b.add_multi_selection(selection_name="", start_after="⚽")
    assert not any("INATTIVA" in w for w in b.multi_warnings())


def test_no_warning_inattiva_se_mappatura_mercati_attiva():
    # Coi profili mercati la mappatura a frase può SOVRASCRIVERE il MarketType a runtime
    # (D1 «il dizionario vince»): base fissa non-punteggio NON è più una certezza → silenzio.
    b = _base_builder(extra_rules=[cp.FieldRule(target="MarketType", fixed_value="MATCH_ODDS")])
    b.market_mapping_profiles = ["profilo-mercati"]
    b.multi_selection_enabled = True
    b.add_multi_selection(selection_name="", start_after="⚽")
    assert not any("INATTIVA" in w for w in b.multi_warnings())


def test_no_warning_riga_disabilitata_o_toggle_spento():
    # Una riga disattivata (o il toggle MultiSelection spento) non genera righe → niente avvisi.
    b = _multiselection_builder()
    b.multi_selections[0].selection_name = ""
    b.multi_selections[0].start_after = "⚽"
    b.multi_selections[0].market_type = "MATCH_ODDS"
    b.multi_selections[0].enabled = False
    assert not any("Riga selezione" in w for w in b.multi_warnings())
    b.multi_selections[0].enabled = True
    b.multi_selection_enabled = False
    assert not any("Riga selezione" in w for w in b.multi_warnings())


def test_no_warning_delimitatore_solo_spazi():
    # Come il runtime (`_is_dynamic_selection`): un delimitatore di soli spazi NON conta —
    # né per l'estrazione dinamica né per gli avvisi (nessuna riga «ambigua» da segnalare).
    b = _multiselection_builder()
    b.multi_selections[0].start_after = "   "
    assert not any("Riga selezione" in w for w in b.multi_warnings())


def test_warning_gate_allineato_al_runtime():
    # Anti-drift: il set dei mercati-punteggio degli avvisi È quello del runtime (import,
    # non copia). Se divergessero, l'avviso mentirebbe sul comportamento reale.
    from xtrader_bridge import custom_pipeline
    assert pb.DYNAMIC_SCORE_MARKETS is custom_pipeline._DYNAMIC_SCORE_MARKETS


# ── PR-cestino: anteprima coi decimali nel formato csv_language (#342/#344) ──

def test_preview_rows_summary_decimali_localizzati_it():
    # Con csv_language IT il summary mostra «1,50» (come nel file); il DATO `row` resta
    # canonico col punto (validatori/dedup non dipendono dalla lingua).
    csv_writer.set_csv_language("IT")
    b = _multiselection_builder()
    rows = b.preview_rows(MSG, mode="NAME_ONLY")
    assert rows and all(r.placeable for r in rows)
    assert all("Price=1,50" in r.summary for r in rows)
    assert all(r.row["Price"] == "1.50" for r in rows)


def test_preview_rows_summary_decimali_punto_en():
    csv_writer.set_csv_language("EN")
    b = _multiselection_builder()
    rows = b.preview_rows(MSG, mode="NAME_ONLY")
    assert rows and all("Price=1.50" in r.summary for r in rows)
    assert not any("Price=1,50" in r.summary for r in rows)


def test_preview_rows_summary_testo_non_toccato():
    # Solo le colonne DECIMALI sono localizzate: un SelectionName «1 - 0» o un MarketName
    # con virgola/punto restano identici nel summary (stessa regola del write-path #342).
    csv_writer.set_csv_language("IT")
    b = _multiselection_builder()
    rows = b.preview_rows(MSG, mode="NAME_ONLY")
    assert any("SelectionName=1 - 0" in r.summary for r in rows)
    assert all("MarketName=Risultato esatto" in r.summary for r in rows)


# ── PR-cestino: glue GUI — il banner avvisi si aggiorna sui campi digitati ──

class _RecEntry:
    """CTkEntry finto che REGISTRA i bind: verifica che ogni campo riga multi aggiorni
    il banner avvisi quando l'utente lascia il campo (<FocusOut>)."""

    def __init__(self, *a, **k):
        self.bindings = {}
        self._text = ""

    def insert(self, _i, s):
        self._text += s

    def get(self):
        return self._text

    def pack(self, *a, **k):
        return self

    def bind(self, event, cb):
        self.bindings[event] = cb


class _RecCheckBox:
    """CTkCheckBox finto che registra i kwargs (per verificare `command=`)."""

    created = []

    def __init__(self, *a, **k):
        type(self).created.append(k)

    def pack(self, *a, **k):
        return self


class _NoopWidget:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: _NoopWidget()


class _RecFakeCtk(types.ModuleType):
    CTkEntry = _RecEntry
    CTkCheckBox = _RecCheckBox

    def __getattr__(self, _name):        # ogni altro widget/font/var → no-op
        return _NoopWidget


def test_gui_add_multi_row_aggancia_refresh_avvisi(monkeypatch):
    # Esercita il VERO `_add_multi_row_widget`: ogni entry della riga deve avere il bind
    # <FocusOut> → `_refresh_multi_warnings`, e la checkbox «Attiva» il `command=` omologo
    # (gli avvisi per-riga dipendono dal testo digitato e dallo stato Attiva).
    monkeypatch.setitem(sys.modules, "customtkinter", _RecFakeCtk("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    gui = importlib.import_module("xtrader_bridge.custom_parser_gui")

    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)   # no __init__: nessun widget
    calls = []
    panel._refresh_multi_warnings = lambda: calls.append(1)
    _RecCheckBox.created = []
    refs_list = []
    panel._add_multi_row_widget(_NoopWidget(), refs_list, cp.MultiRowRule(),
                                fields=gui.CustomParserPanel._MULTI_SELECTION_FIELDS)
    refs = refs_list[0]
    for attr, _, _ in gui.CustomParserPanel._MULTI_SELECTION_FIELDS:
        cb = refs[attr].bindings.get("<FocusOut>")
        assert cb is not None, f"campo {attr}: manca il bind <FocusOut>"
        cb(None)                                       # simula l'uscita dal campo
    assert len(calls) == len(gui.CustomParserPanel._MULTI_SELECTION_FIELDS)
    # checkbox «Attiva»: command aggiorna il banner
    attiva = [k for k in _RecCheckBox.created if k.get("text") == "Attiva"]
    assert attiva and attiva[0].get("command") is not None
    attiva[0]["command"]()
    assert len(calls) == len(gui.CustomParserPanel._MULTI_SELECTION_FIELDS) + 1


def test_gui_test_riallinea_banner_avvisi(monkeypatch):
    # Pin strutturale (come i pin di `_start` in test_app_runtime_glue: `_test` è
    # GUI-coupled): «Prova messaggio» deve riallineare il banner avvisi DOPO la
    # sincronizzazione dei widget (gli avvisi dipendono anche dalla griglia base).
    gui = _gui_module(monkeypatch)
    src = inspect.getsource(gui.CustomParserPanel._test)
    assert "_refresh_multi_warnings" in src
    assert src.index("_sync_to_builder") < src.index("_refresh_multi_warnings")
