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
    safety_guard,
    signal_dedupe,
    signal_queue,
    validator,
    write_path,
)
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


def _multiselection_parser():
    # La base fornisce anche MarketType/MarketName: le selezioni ereditano il mercato.
    extra = [
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="MarketName", fixed_value="Risultato esatto"),
    ]
    defn = cp.CustomParserDef(name="MS", mode="NAME_ONLY", rules=_base_rules(extra))
    defn.multi_selection_enabled = True
    defn.multi_selections = [
        cp.MultiRowRule(selection_name="1 - 0"),
        cp.MultiRowRule(selection_name="2 - 1"),
        cp.MultiRowRule(selection_name="1 - 2"),
    ]
    return defn


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
    assert len(res.rows) == 3                       # 3 righe attive scritte
    assert len(q.active_rows()) == 3
    with open(path, newline="", encoding="utf-8-sig") as f:
        assert sum(1 for _ in f) == 1 + 3           # header + 3 righe

    # Stesso messaggio reinviato (coda svuotata) → tutte duplicate, nessuna scritta.
    q2 = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    res2 = write_path.commit_signals(tracker, None, q2, _cfg(path), MSG, rows, path, now=1,
                                     write_rows=csv_writer.write_rows)
    assert res2.decision == "DUPLICATE"
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


def test_commit_signals_cap_blocca_e_ripristina_guardrail(tmp_path):
    # Una riga bloccata dal tetto max_active NON è scritta E non deve restare "vista" nel dedupe:
    # con un tetto più alto, al retry quella riga passa (non è un duplicato).
    path = str(tmp_path / "segnali.csv")
    rows = _rows(pipe.build_validated_rows(_multiselection_parser(), MSG, mode="NAME_ONLY"))
    tracker = signal_dedupe.SignalTracker()
    q = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED,
                                 default_timeout=120, max_active=2)
    res = write_path.commit_signals(tracker, None, q, _cfg(path), MSG, rows, path, now=0,
                                    write_rows=csv_writer.write_rows)
    assert len(res.rows) == 2                       # solo 2 righe entrano (tetto)
    # La 3ª, bloccata dal tetto, non ha consumato il dedupe → ora passa.
    q2 = signal_queue.SignalQueue(mode=signal_queue.QUEUE_UNTIL_CONFIRMED,
                                  default_timeout=120, max_active=10)
    res2 = write_path.commit_signals(tracker, None, q2, _cfg(path), MSG, [rows[2]], path, now=1,
                                     write_rows=csv_writer.write_rows)
    assert len(res2.rows) == 1 and res2.rows[0]["SelectionName"] == "1 - 2"
