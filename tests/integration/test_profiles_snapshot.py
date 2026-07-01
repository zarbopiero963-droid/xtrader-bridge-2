"""#60 (Codex P2): salvare un profilo NON deve persistere config.json prima che la scrittura
del profilo riesca. `App._save_config(persist=False)` è uno SNAPSHOT del form (gated) senza
effetti su disco; la persistenza avviene solo con `persist=True`. Test headless via make_app."""


class _E:
    """Stand-in di un campo GUI: `.get()` ritorna il valore."""

    def __init__(self, v=""):
        self._v = v

    def get(self):
        return self._v


def _prep_form(a):
    """Popola l'App headless coi widget/metodi minimi che `_save_config` legge."""
    a._config = {}
    a._running = False
    a._e_token = _E("tok")
    a._e_chat = _E("111")
    a._e_csv = _E("out.csv")
    a._e_delay = _E("30")
    a._e_provider = _E("TG")
    a._adv = {}
    a._had_incomplete_token_load = lambda *x, **k: False
    a._resync_token_field = lambda *x, **k: None
    a._gate_dangerous_transitions = lambda old, new: new
    a._register_secret_token = lambda *x, **k: None
    a._update_real_mode_banner = lambda *x, **k: None
    a._update_active_indicator = lambda *x, **k: None
    a._refresh_listened_chats = lambda *x, **k: None
    a._dbg = lambda *x, **k: None


def test_save_config_snapshot_non_persiste(make_app, app_mod, monkeypatch):
    a = make_app(running=False)
    _prep_form(a)
    persisted = []
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg, path: (persisted.append(dict(cfg)), (dict(cfg), True))[1])

    # SNAPSHOT: ritorna la config del form ma NON scrive su disco né muta self._config.
    snap = a._save_config(persist=False)
    assert persisted == []                         # nessuna persistenza
    assert snap["csv_path"] == "out.csv"           # ma legge il form
    assert snap["chat_id"] == "111"
    assert a._config == {}                          # self._config invariato dallo snapshot

    # PERSIST: ora scrive davvero e aggiorna self._config.
    saved = a._save_config(persist=True)
    assert len(persisted) == 1                      # persistito una volta
    assert saved["csv_path"] == "out.csv"
    assert a._config == saved
