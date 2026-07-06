"""Glue #311 §3.3: il VERO `App._refresh_health` su istanza nuda — legge lo stato
vivo (status label, «Ultimo …», config) e colora i semafori via `health_check`."""

import pytest

from xtrader_bridge import health_check as hc


class _Lbl:
    def __init__(self, text="⬤  ATTIVO"):
        self._text = text
        self.kw = {}

    def cget(self, _k):
        return self._text

    def configure(self, **kw):
        self.kw = kw


def _bare(app_mod, tmp_path, *, status="⬤  ATTIVO"):
    app = object.__new__(app_mod.App)
    csv = tmp_path / "segnali.csv"
    app._config = {"csv_path": str(csv), "dry_run": False, "bridge_mode": "COLLAUDO",
                   "xtrader_notification_chat_id": "123",
                   "active_parser": "p1", "parsers_dir_exists_hint": True}
    app._status_lbl = _Lbl(status)
    app._last_vals = {"signal": "", "message": "msg di prova", "csv": "",
                      "error": "", "confirmation": "CONFERMATO @ 10:00"}
    app._health_lbls = {k: _Lbl("") for k in
                        ("telegram", "message", "parser", "signal",
                         "csv", "confirmation", "mode")}
    return app


def test_refresh_health_colora_dallo_stato_vivo(app_mod, tmp_path, monkeypatch):
    app = _bare(app_mod, tmp_path)
    # parser attivo forzato deterministico (la logica pura ha già i suoi unit test)
    monkeypatch.setattr(app_mod.signal_router, "has_active_parser_config", lambda _c: True)
    app._refresh_health()
    texts = {k: lbl.kw.get("text", "") for k, lbl in app._health_lbls.items()}
    assert texts["telegram"].startswith("🟢")
    assert texts["message"].startswith("🟢") and "msg di prova" in texts["message"]
    assert texts["parser"].startswith("🟢")
    assert texts["signal"].startswith("🟡")              # nessun segnale ancora
    assert texts["csv"].startswith("🟢")                 # tmp_path scrivibile
    assert texts["confirmation"].startswith("🟢")
    assert texts["mode"].startswith("🟡")                # COLLAUDO = giallo (rischio)


def test_refresh_health_no_op_su_istanza_parziale(app_mod):
    app = object.__new__(app_mod.App)
    app._refresh_health()                                # nessun crash, nessun widget
