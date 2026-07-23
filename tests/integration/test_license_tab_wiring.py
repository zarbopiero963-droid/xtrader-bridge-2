"""Test ESEGUIBILE del cablaggio della scheda «🔑 Licenza» in `app.py` (#140 PR 2, review CR #144).

Invoca il VERO `App._build_license_tab` su un'istanza headless con un `LicensePanel` registratore,
e verifica che i provider iniettati siano cablati alle implementazioni reali del progetto:
- `hardware_id_provider` → `licensing.hardware_id`;
- `load_state`/`save_state` → `license_store` sul path `license_state_path(config_dir())`;
- `now_provider` → epoch intero.
Sostituisce il vecchio guard a sole stringhe (che provava solo che tre stringhe esistessero).
"""

import sys
import types

from xtrader_bridge import license_store, licensing
from xtrader_bridge.config_store import config_dir


def test_build_license_tab_cabla_i_provider_reali(app_mod, monkeypatch):
    captured = {}

    class _RecorderPanel:
        def __init__(self, parent, **kw):
            captured.update(kw)
            captured["parent"] = parent

        def pack(self, **_k):
            captured["packed"] = True

    # `_build_license_tab` fa `from . import license_gui`: iniettiamo un modulo finto con il
    # pannello registratore, così non serve customtkinter e catturiamo i kwargs reali. `from .
    # import X` risolve X sia da sys.modules sia come ATTRIBUTO del package → si patcha entrambi.
    import xtrader_bridge
    fake_lg = types.ModuleType("xtrader_bridge.license_gui")
    fake_lg.LicensePanel = _RecorderPanel
    monkeypatch.setitem(sys.modules, "xtrader_bridge.license_gui", fake_lg)
    monkeypatch.setattr(xtrader_bridge, "license_gui", fake_lg, raising=False)

    app = object.__new__(app_mod.App)
    app_mod.App._build_license_tab(app, parent=object())

    assert captured.get("packed") is True
    # 1) Hardware ID provider = l'impronta reale del progetto.
    assert captured["hardware_id_provider"] is licensing.hardware_id
    # 2) now provider = epoch intero.
    assert isinstance(captured["now_provider"](), int)

    # 3) load_state legge dallo store sul path license_state_path(config_dir()).
    seen = {}

    def _fake_load(p):
        seen["load"] = p
        return ("T", 1)

    monkeypatch.setattr(license_store, "load_license", _fake_load)
    assert captured["load_state"]() == ("T", 1)
    assert seen["load"] == license_store.license_state_path(config_dir())

    # 4) save_state scrive sullo store con lo stesso path e i valori passati.
    monkeypatch.setattr(license_store, "save_license",
                        lambda p, tok, ls: seen.update(save=(p, tok, ls)))
    captured["save_state"]("TOK", 999)
    assert seen["save"] == (license_store.license_state_path(config_dir()), "TOK", 999)
