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
import os
import sys
import types

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_builder as pb
from xtrader_bridge import validator
from xtrader_bridge.csv_writer import CSV_HEADER

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


# ── il salvataggio NON azzera i campi multi non esposti (Codex P1) ────────────
# La GUI espone solo `_MULTI_FIELDS`: i campi min_price/max_price/points/start_after/
# end_before di una regola CARICATA devono sopravvivere al salvataggio. La logica vive nel
# controller (`merge_multi_rule_overrides`, pura) ed è qui testata direttamente; più sotto
# si esercita anche il VERO metodo della vista (stub di customtkinter) per coprire il wrapper.

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
