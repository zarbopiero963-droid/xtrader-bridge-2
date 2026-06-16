"""Test baseline della configurazione (PR-02, aggiornato PR-03).

Dopo il refactor, load/save sono funzioni pure in `xtrader_bridge.config_store`,
testabili headless con path temporanei. Lo spostamento in `%APPDATA%` è PR-04.
"""

import json
import os

from xtrader_bridge import config_store


def test_config_file_e_config_json():
    assert config_store.CONFIG_FILE.endswith("config.json")
    assert os.path.isabs(config_store.CONFIG_FILE)


def test_load_config_default_senza_file(tmp_path):
    cfg = config_store.load_config(str(tmp_path / "assente.json"))
    for k in ("bot_token", "chat_id", "csv_path", "clear_delay", "provider"):
        assert k in cfg
    assert isinstance(cfg["clear_delay"], int)
    assert cfg["provider"]                       # default non vuoto


def test_load_config_merge_con_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "TG_PRE", "chat_id": "-100123"}))
    cfg = config_store.load_config(str(p))
    assert cfg["provider"] == "TG_PRE"
    assert cfg["chat_id"] == "-100123"
    assert "csv_path" in cfg                      # default preservato


def test_load_config_json_malformato_usa_default(tmp_path):
    # File presente ma JSON non valido: best-effort -> nessuna eccezione, default preservati.
    p = tmp_path / "config.json"
    p.write_text("{ questo non e' json valido ,,, ")
    cfg = config_store.load_config(str(p))
    assert cfg["csv_path"] == config_store.DEFAULTS["csv_path"]
    assert cfg["provider"] == config_store.DEFAULTS["provider"]
    assert cfg["clear_delay"] == config_store.DEFAULTS["clear_delay"]


def test_save_then_load_roundtrip(tmp_path):
    p = str(tmp_path / "config.json")
    data = {"bot_token": "X", "chat_id": "-1", "csv_path": "/tmp/s.csv",
            "clear_delay": 30, "provider": "TG_LIVE"}
    config_store.save_config(data, p)
    assert config_store.load_config(p) == {**config_store.DEFAULTS, **data}


def test_defaults_non_contengono_segreti():
    # I default non devono contenere token o chat reali.
    assert config_store.DEFAULTS["bot_token"] == ""
    assert config_store.DEFAULTS["chat_id"] == ""
