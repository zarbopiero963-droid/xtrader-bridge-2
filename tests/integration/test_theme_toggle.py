"""Test hard: toggle tema chiaro/scuro (#288 Delta 1) — glue `App._toggle_theme`.

Esercita il metodo REALE via l'harness headless (`make_app`) con la VERA `save_config` su un
`CONFIG_FILE` temporaneo. `ctk.set_appearance_mode` è monkeypatchato (cattura), il pulsante tema
è un fake con `.configure()`. Il rendering reale del tema chiaro è GUI-only → smoke manuale.
"""

from xtrader_bridge import config_store


class _FakeBtn:
    def __init__(self):
        self.text = None

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]


def _prep(make_app, app_mod, tmp_path, monkeypatch, *, theme):
    cfgfile = str(tmp_path / "config.json")
    monkeypatch.setattr(app_mod, "CONFIG_FILE", cfgfile)
    a = make_app(config={"theme": theme, "chat_id": "42"}, running=False)
    a._theme_btn = _FakeBtn()
    a.appearance_calls = []
    monkeypatch.setattr(app_mod.ctk, "set_appearance_mode",
                        lambda m: a.appearance_calls.append(m))
    # Guardia token PR-08c (come gli altri save non-form): stub di default.
    a._had_incomplete_token_load = lambda: False
    a.resync_calls = []
    a._resync_token_field = lambda had=None: a.resync_calls.append(had)
    return a, cfgfile


def test_toggle_da_dark_a_light_applica_e_persiste(make_app, app_mod, tmp_path, monkeypatch):
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, theme="dark")
    new = app_mod.App._toggle_theme(a)
    assert new == "light"
    assert a.appearance_calls == ["light"]            # applicato subito
    assert a._config["theme"] == "light"              # config vivo aggiornato
    assert a._config["chat_id"] == "42"               # altri campi preservati (merge)
    assert a._theme_btn.text == "☀️"                  # icona = chiaro attivo
    # persistito su disco: reload conferma
    assert config_store.load_config(cfgfile)["theme"] == "light"


def test_toggle_da_light_a_dark(make_app, app_mod, tmp_path, monkeypatch):
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, theme="light")
    assert app_mod.App._toggle_theme(a) == "dark"
    assert a.appearance_calls == ["dark"]
    assert a._theme_btn.text == "🌙"                  # icona = scuro attivo
    assert config_store.load_config(cfgfile)["theme"] == "dark"


def test_toggle_da_tema_malformato_tratta_come_dark(make_app, app_mod, tmp_path, monkeypatch):
    # Config vivo con valore sporco → `normalize_theme` lo tratta come "dark" → toggle a "light".
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, theme="PURPLE")
    assert app_mod.App._toggle_theme(a) == "light"
    assert a.appearance_calls == ["light"]


def test_toggle_guardia_token_pr08c(make_app, app_mod, tmp_path, monkeypatch):
    # Il save non-form cattura il marker load-incompleto PRIMA e risincronizza DOPO, così un
    # toggle col keyring giù al load non fa poi cancellare il token al «Salva Config» seguente.
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, theme="dark")
    a._had_incomplete_token_load = lambda: "MARKER"
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg_arg, _p: config_store.SaveResult(
                            dict(cfg_arg), True, config_store.SAVE_OK))
    app_mod.App._toggle_theme(a)
    assert a.resync_calls == ["MARKER"]


def test_toggle_save_fallito_avvisa(make_app, app_mod, tmp_path, monkeypatch):
    # Ramo di fallimento disco: applica comunque il tema (set_appearance_mode) ma avvisa nel log.
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, theme="dark")
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg_arg, _p: config_store.SaveResult(
                            dict(cfg_arg), False, config_store.SAVE_DISK_ERROR))
    app_mod.App._toggle_theme(a)
    assert a.appearance_calls == ["light"]            # il tema è comunque applicato all'UI
    assert any("tema NON salvat" in m for m in a.logs)
