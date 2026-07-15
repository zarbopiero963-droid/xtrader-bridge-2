"""Test hard veritieri — Issue #76 P2-2 (audit 2026-07-15).

Virgola non normalizzata su `Handicap`/`Points`: `_normalize_to_contract` convertiva
virgola→punto solo sulle quote (`_PRICE_COLS`), ma `_HANDICAP_RE` accetta la virgola
(«+1,5») e `Handicap` fa parte di `_ROW_KEY_FIELDS` della chiave di deduplica
(confronto su stringa grezza). Due parser sulla stessa chat che generano la STESSA
scommessa — uno con Handicap «0.5» e uno con «0,5» — producevano chiavi dedup diverse
→ nessuna dedup → due righe identiche nel CSV localizzato (doppia scommessa).

Fix testato: la normalizzazione virgola→punto si applica anche a `Handicap` e `Points`
(segno preservato, malformati invariati → fail-closed `INVALID_HANDICAP` intatto).
L'output CSV non cambia: `csv_writer._localize_decimal` serializzava già in modo
uniforme per lingua — il bug era SOLO nelle chiavi interne (dedup/validatori), dove la
docstring di `localize_row` promette «valori canonici col punto».
"""

from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import (
    custom_parser as cp,
    live_guard,
    safety_guard,
    signal_dedupe,
    signal_queue,
    validator,
    write_path,
)
from xtrader_bridge.custom_parser import CustomParserDef, FieldRule


def _parser(name="P", *, handicap="", points="", extra_rules=()):
    rules = [
        FieldRule(target="Provider", fixed_value="TG"),
        FieldRule(target="EventName", fixed_value="Milan v Inter", required=True),
        FieldRule(target="MarketType", fixed_value="ASIAN_HANDICAP", required=True),
        FieldRule(target="SelectionName", fixed_value="Milan", required=True),
        FieldRule(target="BetType", fixed_value="PUNTA"),
        *extra_rules,
    ]
    if handicap:
        rules.append(FieldRule(target="Handicap", fixed_value=handicap))
    if points:
        rules.append(FieldRule(target="Points", fixed_value=points))
    return CustomParserDef(name=name, mode="NAME_ONLY", rules=rules)


def _build(defn):
    return pipe.build_validated_row(defn, "msg", provider="TG", require_price=False)


# ── P2-2 core: virgola normalizzata a punto nella riga INTERNA (canonica) ───────────────────

def test_handicap_virgola_normalizzato_a_punto():
    res = _build(_parser(handicap="0,5"))
    assert res.status == validator.VALID
    assert res.row["Handicap"] == "0.5"          # canonico col punto, non "0,5"


def test_points_virgola_normalizzato_a_punto():
    res = _build(_parser(points="1,5"))
    assert res.row["Points"] == "1.5"


def test_handicap_segno_preservato():
    assert _build(_parser(handicap="+1,5")).row["Handicap"] == "+1.5"
    assert _build(_parser(handicap="-0,25")).row["Handicap"] == "-0.25"


def test_chiavi_dedup_identiche_per_stessa_scommessa_virgola_vs_punto():
    # Il cuore del finding: stessa scommessa da due parser (stile «0.5» vs «0,5») deve
    # produrre la STESSA chiave di deduplica per-riga.
    row_dot = _build(_parser(name="A", handicap="0.5")).row
    row_comma = _build(_parser(name="B", handicap="0,5")).row
    assert signal_dedupe.row_dedup_key("msg", row_dot) == \
        signal_dedupe.row_dedup_key("msg", row_comma)


# ── end-to-end anti-doppia-scommessa: commit multi con le due varianti → UNA sola riga ──────

def test_commit_signals_deduplica_le_due_varianti_stessa_scommessa():
    # Due parser sulla stessa chat (PR-2 «scattano tutti») generano la stessa scommessa
    # con separatore diverso: al commit deve restare UNA riga attiva, non due.
    tracker = signal_dedupe.SignalTracker()
    daily = safety_guard.DailyLimiter(max_per_day=100)
    queue = signal_queue.SignalQueue(mode=signal_queue.APPEND_ACTIVE, default_timeout=90)
    row_dot = _build(_parser(name="A", handicap="0.5")).row
    row_comma = _build(_parser(name="B", handicap="0,5")).row
    written = []

    def _w(rows, path):
        written.append([dict(r) for r in rows])

    res = write_path.commit_signals(
        tracker, daily, queue, {"dry_run": False}, "msg", [row_dot, row_comma],
        "out.csv", 100.0, _w)
    assert res.decision == live_guard.WRITE
    assert len(queue.active_rows()) == 1          # UNA sola riga attiva, mai due
    assert written[-1] == [row_dot]               # CSV con la sola prima variante


# ── fail-closed intatto: malformati ancora scartati, default e punti invariati ──────────────

def test_handicap_malformato_resta_invalid_handicap():
    res = _build(_parser(handicap="abc"))
    assert res.status == pipe.INVALID_HANDICAP    # _decimal_sep_to_point non "aggiusta"


def test_handicap_doppio_separatore_malformato_resta_scartato():
    # "1.2,3" non è un raggruppamento migliaia valido → invariato → INVALID_HANDICAP.
    res = _build(_parser(handicap="1.2,3"))
    assert res.status == pipe.INVALID_HANDICAP


def test_handicap_col_punto_e_default_invariati():
    assert _build(_parser(handicap="0.5")).row["Handicap"] == "0.5"    # già canonico
    assert _build(_parser()).row["Handicap"] == "0"                    # default intatto


# ── percorso MULTI: override handicap della regola normalizzato come la base ────────────────

def test_override_multi_handicap_virgola_normalizzato():
    defn = CustomParserDef(
        name="M", mode="NAME_ONLY", multi_selection_enabled=True,
        multi_selections=[cp.MultiRowRule(enabled=True, selection_name="Inter",
                                          handicap="-0,5")],
        rules=[
            FieldRule(target="Provider", fixed_value="TG"),
            FieldRule(target="EventName", fixed_value="Milan v Inter", required=True),
            FieldRule(target="MarketType", fixed_value="ASIAN_HANDICAP", required=True),
        ])
    results = pipe.build_validated_rows(defn, "msg", provider="TG", require_price=False)
    derived = [r for r in results if r.row.get("SelectionName") == "Inter"]
    assert derived and derived[0].row["Handicap"] == "-0.5"
