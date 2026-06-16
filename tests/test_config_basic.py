"""Test baseline della configurazione (PR-02).

`_load_config` è un metodo di `App` ma non usa attributi della GUI: lo possiamo
invocare in modo headless passando un self fittizio. Il test di `_save_config`
(legato ai widget) e lo spostamento in `%APPDATA%` sono previsti in PR-04.
"""

import json
import types

import main


def test_config_file_e_config_json():
    # CONFIG_FILE deve essere un path assoluto che termina con config.json.
    assert main.CONFIG_FILE.endswith("config.json")
    import os
    assert os.path.isabs(main.CONFIG_FILE)


def test_load_config_default_senza_file(tmp_path, monkeypatch):
    # Nessun file presente -> ritorna i default attesi.
    monkeypatch.setattr(main, "CONFIG_FILE", str(tmp_path / "assente.json"))
    cfg = main.App._load_config(types.SimpleNamespace())
    for k in ("bot_token", "chat_id", "csv_path", "clear_delay", "provider"):
        assert k in cfg
    assert isinstance(cfg["clear_delay"], int)
    assert cfg["provider"]                      # default non vuoto


def test_load_config_merge_con_file(tmp_path, monkeypatch):
    # Un file esistente sovrascrive i default, mantenendo le chiavi mancanti.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "TG_PRE", "chat_id": "-100123"}))
    monkeypatch.setattr(main, "CONFIG_FILE", str(p))
    cfg = main.App._load_config(types.SimpleNamespace())
    assert cfg["provider"] == "TG_PRE"
    assert cfg["chat_id"] == "-100123"
    assert "csv_path" in cfg                     # default preservato
