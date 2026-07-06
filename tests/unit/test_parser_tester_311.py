"""Test hard del tester multiplo (#311 §3.2) — split ESPLICITO + report per-messaggio.

Il batch riusa ESATTAMENTE la pipeline read-only del singolo «Prova messaggio»
(test_message/diagnose/preview_rows/test_verdict): qui si verifica lo split (nessuna
euristica: solo righe «---»), il tetto fail-safe e che il report porti verdetto col
motivo + anteprima righe per ogni messaggio, senza alcuna scrittura."""

import importlib
import sys
import types

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_builder as pb

MSG_OK = (
    "P.Bet. PREMACHT 0,5HT 🔊 ✅\n"
    "🏆Saudi Professional League\n"
    "🆚Al-Kholood Club v Al-Hilal\n"
    "⚽ 0 - 0\n"
    "⌚ 1m\n"
)


def _builder():
    b = pb.ParserBuilder()
    b.name = "BatchTest"
    b.mode = "NAME_ONLY"
    b.add_rule(target="Provider", fixed_value="PBet")
    b.add_rule(target="EventName", start_after="🆚", end_before="\n", required=True)
    b.add_rule(target="Price", fixed_value="1.50", required=True)
    b.add_rule(target="BetType", fixed_value="PUNTA", required=True)
    b.add_rule(target="MarketType", fixed_value="MATCH_ODDS", required=True)
    b.add_rule(target="SelectionName", fixed_value="Al-Kholood Club", required=True)
    return b


# ── split_messages: separatore esplicito, nessuna euristica ──────────────────

def test_split_solo_su_riga_separatore():
    text = f"{MSG_OK}---\naltro messaggio\ncon due righe\n --- \nterzo"
    msgs = pb.ParserBuilder.split_messages(text)
    assert len(msgs) == 3
    assert msgs[0] == MSG_OK.strip()          # righe vuote/emoji interne preservate
    assert msgs[1] == "altro messaggio\ncon due righe"
    assert msgs[2] == "terzo"


def test_split_blocchi_vuoti_scartati_e_niente_split_interno():
    assert pb.ParserBuilder.split_messages("---\n\n---\n") == []
    # Un «---» DENTRO una riga non è un separatore (solo riga intera).
    msgs = pb.ParserBuilder.split_messages("quota 1.85 --- non separo\nriga2")
    # Contenuto INTEGRALE preservato: un separatore in-linea non deve né dividere né
    # mangiare la riga che lo contiene.
    assert msgs == ["quota 1.85 --- non separo\nriga2"]
    assert pb.ParserBuilder.split_messages("") == []
    assert pb.ParserBuilder.split_messages(None) == []


# ── batch_report: verdetto col motivo + anteprima per messaggio ──────────────

def test_batch_report_misto_valido_e_scartato():
    b = _builder()
    text = f"{MSG_OK}---\nciao come va?"      # 1 segnale vero + 1 chiacchiera
    reports, skipped = b.batch_report(text, mode="NAME_ONLY")
    assert skipped == 0 and len(reports) == 2
    ok, ko = reports
    assert ok.ok is True and ok.verdict.startswith("✅")
    assert ok.rows and ok.rows[0].placeable
    assert "EventName=Al-Kholood Club v Al-Hilal" in ok.rows[0].summary
    assert ko.ok is False and ko.verdict.startswith("⛔")
    # Il motivo esatto è nel verdetto (stesso testo del singolo «Prova messaggio»).
    assert "Non pronto" in ko.verdict
    assert ko.first_line == "ciao come va?"


def test_batch_report_tetto_fail_safe():
    b = _builder()
    text = "\n---\n".join(f"msg {i}" for i in range(pb.MAX_BATCH_MESSAGES + 5))
    reports, skipped = b.batch_report(text, mode="NAME_ONLY")
    assert len(reports) == pb.MAX_BATCH_MESSAGES and skipped == 5


def test_batch_report_riusa_il_verdetto_del_singolo():
    # Anti-drift: per lo stesso messaggio, il verdetto del batch DEVE essere identico a
    # quello che il flusso singolo comporrebbe (stessa pipeline, stessi motivi).
    b = _builder()
    from xtrader_bridge import parser_diagnostics
    reports, _ = b.batch_report(MSG_OK, mode="NAME_ONLY")
    res = b.test_message(MSG_OK, mode="NAME_ONLY", require_price=b.to_def().price_required())
    diag = parser_diagnostics.diagnose(b.to_def(), MSG_OK, provider="", mode="NAME_ONLY",
                                       require_price=b.to_def().price_required(),
                                       name_mapping_profiles=None,
                                       market_mapping_profiles=None, id_resolver=None)
    atteso = pb.ParserBuilder.test_verdict(
        b.errors(), b.preview_rows(MSG_OK, mode="NAME_ONLY"),
        diag_placeable=diag.placeable, diag_status=diag.status, res_row=res.row,
        res_missing_required=res.missing_required, res_detail=res.detail,
        content_ok=not diag.message_error)
    assert reports[0].verdict == atteso


# ── glue GUI: il VERO _test_batch su pannello nudo con stub ──────────────────

class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


def _gui_mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.custom_parser_gui", raising=False)
    return importlib.import_module("xtrader_bridge.custom_parser_gui")


def test_gui_test_batch_valuta_e_renderizza(monkeypatch):
    gui = _gui_mod(monkeypatch)
    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)

    class _Box:
        def get(self, *_a):
            return f"{MSG_OK}---\nciao\n"

    class _Result:
        text = ""

        def configure(self, **k):
            type(self).text = k.get("text", "")

    rendered = []
    panel._reload_profile_checks = lambda: None
    panel._reload_market_profile_checks = lambda: None
    panel._sync_to_builder = lambda: None
    panel._refresh_multi_warnings = lambda: None
    panel._unresolved_selected = lambda: []
    panel._unresolved_market_selected = lambda: []
    panel._msg_box = _Box()
    panel._result = _Result()
    panel._label_to_mode = lambda _v: "NAME_ONLY"
    panel._mode_var = types.SimpleNamespace(get=lambda: "NAME_ONLY")
    panel._global_mode = "NAME_ONLY"
    panel._provider = ""
    panel._resolve_mapping_profiles = lambda _d: None
    panel._resolve_market_mapping_profiles = lambda _d: None
    panel._preview_id_resolver = lambda: None
    panel._render_batch_table = lambda reports: rendered.extend(reports)
    panel.builder = _builder()

    panel._test_batch()

    assert len(rendered) == 2
    assert rendered[0].ok is True and rendered[1].ok is False
    assert "Messaggi validi: 1/2" in _Result.text


def test_gui_test_batch_senza_messaggi_avvisa(monkeypatch):
    gui = _gui_mod(monkeypatch)
    panel = gui.CustomParserPanel.__new__(gui.CustomParserPanel)

    class _Result:
        text = ""

        def configure(self, **k):
            type(self).text = k.get("text", "")

    panel._reload_profile_checks = lambda: None
    panel._reload_market_profile_checks = lambda: None
    panel._sync_to_builder = lambda: None
    panel._refresh_multi_warnings = lambda: None
    panel._unresolved_selected = lambda: []
    panel._unresolved_market_selected = lambda: []
    panel._msg_box = types.SimpleNamespace(get=lambda *_a: "  \n---\n ")
    panel._result = _Result()
    panel._label_to_mode = lambda _v: "NAME_ONLY"
    panel._mode_var = types.SimpleNamespace(get=lambda: "NAME_ONLY")
    panel._global_mode = "NAME_ONLY"
    panel._provider = ""
    panel._resolve_mapping_profiles = lambda _d: None
    panel._resolve_market_mapping_profiles = lambda _d: None
    panel._preview_id_resolver = lambda: None
    panel._render_batch_table = lambda reports: pytest.fail("non deve renderizzare")
    panel.builder = _builder()

    panel._test_batch()
    assert "Nessun messaggio" in _Result.text
