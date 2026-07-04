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
    # Guardia token PR-08c (come gli altri save non-form): stub no-op di default;
    # i test specifici li rimpiazzano con spie.
    a._had_incomplete_token_load = lambda: False
    a.resync_calls = []
    a._resync_token_field = lambda had=None: a.resync_calls.append(had)
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


def test_apply_e_salva_csv_path_guardia_token_pr08c(make_app, app_mod, tmp_path, monkeypatch):
    # PR-08c (CodeRabbit #328): il save non-form cattura il marker load-incompleto PRIMA e
    # risincronizza il campo token DOPO, come gli altri save non-form — così un «Sfoglia…»
    # col keyring giù al load NON fa poi cancellare il token al «Salva Config» seguente.
    cfg = {"csv_path": "vecchio.csv", "bot_token": "SEGRETO"}
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, config=cfg, gui_csv="vecchio.csv")
    a._had_incomplete_token_load = lambda: "MARKER"       # spia: valore catturato
    # stub `save_config`: il test verifica SOLO la guardia token (resync), non deve toccare il
    # keyring REALE della macchina col `bot_token` — isolamento deterministico (CodeRabbit #328).
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg_arg, _p: app_mod.config_store.SaveResult(
                            dict(cfg_arg), True, app_mod.config_store.SAVE_OK))
    app_mod.App._apply_and_save_csv_path(a, "/nuovo.csv")
    # `_resync_token_field` chiamato UNA volta col valore catturato PRIMA del save
    assert a.resync_calls == ["MARKER"]


def test_apply_e_salva_csv_path_fallimento_disco_avvisa(make_app, app_mod, tmp_path, monkeypatch):
    # Ramo di fallimento (Fugu #328): `save_config` → ok=False. Il metodo ritorna False,
    # NON solleva su `result.status` (SaveResult è una 2-tupla con `.status`) e avvisa nel log.
    cfg = {"csv_path": "vecchio.csv"}
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, config=cfg, gui_csv="vecchio.csv")

    def _fake_save(cfg_arg, _path):
        return app_mod.config_store.SaveResult(dict(cfg_arg), False,
                                               app_mod.config_store.SAVE_DISK_ERROR)
    monkeypatch.setattr(app_mod, "save_config", _fake_save)
    ok = app_mod.App._apply_and_save_csv_path(a, "/nuovo.csv")
    assert ok is False
    assert any("NON salvato" in m for m in a.logs)        # avviso chiaro nel log
    assert a.resync_calls == [False]                       # guardia token comunque eseguita
    # comportamento documentato (CodeRabbit #328): entry + config vivo aggiornati ANCHE su save
    # fallito — lo stato in memoria resta coerente, solo il disco è stantio (e l'utente è avvisato)
    assert a._e_csv.get() == "/nuovo.csv"
    assert a._config["csv_path"] == "/nuovo.csv"
