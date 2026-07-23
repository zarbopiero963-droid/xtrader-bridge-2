"""Persistenza dello stato licenza (#140 PR 2): il token attivato + `last_seen` per l'anti-rollback.

Salvato in `config_dir` (`%APPDATA%\\XTraderBridge` su Windows) — accanto a config/dedupe/daily —
così **sopravvive a chiusura/riavvio** e a disinstallazione/reinstallazione del portable EXE.
Scrittura **atomica** (`atomic_io.atomic_write_json`: temporaneo + `os.replace`) e lettura
**fail-safe**: file assente/corrotto → «nessuna licenza» (`(None, None)`), mai un crash.

Qui NON si verifica nulla e non si blocca nulla: solo I/O. La verifica è in `licensing`, il calcolo
dello stato per la UI in `license_status`, il blocco (PR 4) altrove.
"""

from __future__ import annotations

import json

from . import atomic_io

LICENSE_STATE_FILE = "license_state.json"


def license_state_path(config_dir_path: str) -> str:
    """Percorso del file di stato licenza dentro `config_dir`."""
    import os  # noqa: PLC0415 — import locale, coerente con gli altri path helper
    return os.path.join(config_dir_path, LICENSE_STATE_FILE)


def save_license(path: str, token: str, last_seen: int) -> None:
    """Scrive atomicamente il token attivo + `last_seen` (unix seconds UTC)."""
    atomic_io.atomic_write_json(path, {"token": str(token), "last_seen": int(last_seen)},
                                prefix=".license_", suffix=".tmp")


def load_license(path: str):
    """Ritorna `(token, last_seen)` dal file, oppure `(None, None)` se assente/corrotto.

    Fail-safe: qualunque errore di lettura/parse/tipo → `(None, None)` (nessuna licenza), così una
    licenza illeggibile non sblocca né fa crashare — coerente col fail-closed della verifica.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return (None, None)
        token = data.get("token")
        last_seen = data.get("last_seen")
        token = str(token) if isinstance(token, str) and token else None
        last_seen = int(last_seen) if isinstance(last_seen, (int, float)) else None
        return (token, last_seen)
    except FileNotFoundError:
        return (None, None)
    except Exception:       # noqa: BLE001 — file corrotto/illeggibile: fail-safe «nessuna licenza»
        return (None, None)


def clear_license(path: str) -> None:
    """Rimuove lo stato licenza (best-effort). Utile per test/reset; non usato dal blocco."""
    try:
        import os  # noqa: PLC0415
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception:       # noqa: BLE001 — rimozione best-effort
        pass
