"""Caricamento/salvataggio configurazione (funzioni pure, nessuna GUI).

`CONFIG_FILE` resta accanto al file principale (root del repo / cartella EXE),
comportamento invariato rispetto a prima. Lo spostamento in `%APPDATA%` è PR-04.
"""

import json
import os

# config.json nella root del repo (un livello sopra il package), come prima.
CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
)

DEFAULTS = {
    "bot_token":   "",
    "chat_id":     "",
    "csv_path":    r"C:\XTrader\segnali.csv",
    "clear_delay": 90,
    "provider":    "TelegramBot",
}


def load_config(path: str = CONFIG_FILE) -> dict:
    """Ritorna i default, sovrascritti dal file se presente e leggibile."""
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict, path: str = CONFIG_FILE) -> dict:
    """Salva la configurazione su file (best-effort) e la ritorna."""
    try:
        with open(path, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
    return cfg
