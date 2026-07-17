"""Registro persistente dei path CSV «sporchi» (P3-6 audit #76).

Quando lo svuotamento del CSV allo STOP fallisce (XTrader tiene il lock) l'app arma un
retry Tk — ma il retry vive solo nel processo: se l'app CHIUDE (o crasha) prima che
riesca e l'utente nel frattempo cambia ``csv_path``, la recovery d'avvio pulisce solo
il path in config e il path ABBANDONATO resterebbe con una riga attiva per sempre —
una scommessa fantasma visibile a XTrader. Questo registro (sidecar ``dirty_csv.json``
accanto al config, scrittura atomica) ricorda i path non ripuliti finché una pulizia
non riesce: la recovery d'avvio li ripassa tutti.

Contratto:
- **fail-safe, mai raise**: lettura su file assente/corrotto → nessun path; un errore
  di scrittura non blocca STOP/chiusura (best-effort) — ma la marcatura avviene PRIMA
  di armare il retry, così anche un crash immediato lascia il marker su disco;
- **dedup normalizzato** (``normcase``+``abspath``, come `_same_csv_path` dell'app):
  lo stesso file con case o forma diversa non produce doppioni;
- il registro NON tocca mai i CSV: dice solo *quali* path la recovery deve ripulire.
"""

import json
import os

from . import atomic_io, config_store

_FILENAME = "dirty_csv.json"


def _store_path() -> str:
    """Path del sidecar: stessa cartella del config (AppData su Windows)."""
    return os.path.join(config_store.config_dir(), _FILENAME)


def _norm(path) -> str:
    """Forma canonica per il confronto (mai per la pulizia: si usa il path originale)."""
    s = str(path or "").strip()
    return os.path.normcase(os.path.abspath(s)) if s else ""


def dirty_paths(store_path=None):
    """I path marcati sporchi (originali, ordine di inserimento). ``[]`` fail-safe su
    file assente, corrotto o schema inatteso."""
    try:
        with open(store_path or _store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("paths", []) if isinstance(data, dict) else []
        if not isinstance(raw, list):   # schema inatteso (es. stringa): fail-safe, non iterarla
            return []
        return [str(p) for p in raw if str(p or "").strip()]
    except Exception:   # noqa: BLE001 — registro fail-safe: corrotto/assente = vuoto
        return []


def mark_dirty(path, store_path=None) -> None:
    """Registra `path` come sporco (dedup normalizzato). Best-effort: mai raise."""
    try:
        s = str(path or "").strip()
        if not s:
            return
        sp = store_path or _store_path()
        cur = dirty_paths(sp)
        if _norm(s) in {_norm(p) for p in cur}:
            return
        atomic_io.atomic_write_json(sp, {"paths": cur + [s]})
    except Exception:   # noqa: BLE001 — un I/O rotto non deve bloccare STOP/chiusura
        pass


def clear_dirty(path, store_path=None) -> None:
    """Rimuove `path` dal registro (confronto normalizzato). Best-effort: mai raise."""
    try:
        target = _norm(path)
        if not target:
            return
        sp = store_path or _store_path()
        cur = dirty_paths(sp)
        kept = [p for p in cur if _norm(p) != target]
        if len(kept) != len(cur):
            atomic_io.atomic_write_json(sp, {"paths": kept})
    except Exception:   # noqa: BLE001 — come sopra
        pass
