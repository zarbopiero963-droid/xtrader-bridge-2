"""Test hard: «📁 Sfoglia…» del CSV Path → applica + salva subito (#284, opzione b).

Esercita il metodo REALE `App._apply_and_save_csv_path` via l'harness headless (`make_app`),
con la VERA `save_config` che scrive su un file di config **temporaneo** (`CONFIG_FILE`
monkeypatchato). Il dialog Tk (`_browse_csv_path`) è GUI-only → smoke test manuale.
"""

import os

from xtrader_bridge import config_store


class _FakeEntry:
    """Campo CSV finto con delete/insert/get come una `CTkEntry` reale."""

    def __init__(self, value=""):
        self._v = value

    def delete(self, *_a):
        self._v = ""

    def insert(self, _idx, s):
        self._v = (self._v or "") + str(s)

    def get(self):
        return self._v


def _prep(make_app, app_mod, tmp_path, monkeypatch, *, config, gui_csv="",
          running=True, active=None):
    cfgfile = str(tmp_path / "config.json")
    monkeypatch.setattr(app_mod, "CONFIG_FILE", cfgfile)
    a = make_app(config=dict(config), running=running, csv_path=active)
    a._e_csv = _FakeEntry(gui_csv)
    return a, cfgfile


def test_apply_e_salva_csv_path_preserva_altri_campi(make_app, app_mod, tmp_path, monkeypatch):
    cfg = {"csv_path": "vecchio.csv", "chat_id": "42", "provider": "X", "dry_run": True}
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config=cfg, gui_csv="vecchio.csv")
    ok = app_mod.App._apply_and_save_csv_path(a, "/percorso/nuovo.csv")
    assert ok is True
    assert a._e_csv.get() == "/percorso/nuovo.csv"         # entry aggiornata
    assert a._config["csv_path"] == "/percorso/nuovo.csv"  # config vivo aggiornato
    # MERGE: gli altri campi safety-critical del config vivo NON toccati
    assert a._config["chat_id"] == "42"
    assert a._config["dry_run"] is True
    # persistito su disco: il reload conferma il nuovo path E gli altri campi
    reloaded = config_store.load_config(cfgfile)
    assert reloaded["csv_path"] == "/percorso/nuovo.csv"
    assert reloaded["chat_id"] == "42"
    assert reloaded["dry_run"] is True


def test_apply_e_salva_csv_path_vuoto_no_op(make_app, app_mod, tmp_path, monkeypatch):
    cfg = {"csv_path": "vecchio.csv", "chat_id": "42"}
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config=cfg, gui_csv="vecchio.csv")
    assert app_mod.App._apply_and_save_csv_path(a, "") is False       # dialog annullato
    assert app_mod.App._apply_and_save_csv_path(a, "   ") is False    # solo spazi
    assert a._e_csv.get() == "vecchio.csv"                # entry invariata
    assert a._config["csv_path"] == "vecchio.csv"         # config invariato
    assert not os.path.exists(cfgfile)                    # nessuna scrittura


def test_apply_e_salva_csv_path_non_tocca_active_csv_path(make_app, app_mod, tmp_path, monkeypatch):
    # Invariante STOP (#284): cambiare csv_path da GUI a bridge AVVIATO NON tocca
    # `_active_csv_path` — il CSV della sessione attiva resta quello di START finché STOP/START.
    cfg = {"csv_path": "vecchio.csv"}
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, config=cfg, gui_csv="vecchio.csv",
                 running=True, active="sessione_attiva.csv")
    app_mod.App._apply_and_save_csv_path(a, "/nuovo.csv")
    assert a._active_csv_path == "sessione_attiva.csv"    # invariato
    assert a._config["csv_path"] == "/nuovo.csv"          # ma il config vivo sì
