"""License Manager — **impostazioni della pubblicazione automatica** delle revoche (#157).

La lista di revoche firmata va **ri-pubblicata periodicamente** all'URL statico che il bridge
controlla (finestra `MAX_LIST_AGE_S`, oggi 24 h): oltre quel tetto i bridge legittimi si bloccano
fail-closed. Questo modulo tiene **dove** e **ogni quanto** pubblicare, più il **token** di accesso.

Divisione netta (invariante di sicurezza):

- **su disco** (`publish_config.json` nella cartella del License Manager, accanto al registro):
  SOLO impostazioni non segrete — repo, path, branch, intervallo, on/off. **Mai il token.**
- **nel keyring del sistema** (Windows Credential Manager / Keychain / Secret Service): SOLO il
  **token**, in uno spazio dei nomi dedicato al tool (`SERVICE`), mai in chiaro su disco, mai nei log.

Il **seed privato** che firma le licenze **non è toccato** da questo modulo: resta dov'era
(`signing_key.json`), sul PC del proprietario. Qui si gestisce solo la credenziale di *upload*.

Come `xtrader_bridge.token_store`, l'import di `keyring` è **soft** (dipendenza opzionale) e
qualunque eccezione del backend è trattata come «keyring non disponibile»: mai un crash, mai una
perdita silenziosa — il chiamante mostra un avviso e la pubblicazione automatica resta spenta.
"""

from __future__ import annotations

import json
import os

from xtrader_bridge import atomic_io
from xtrader_bridge.licensing import revocation_client

from .core import manager_dir

# ── Keyring (SOLO il token) ─────────────────────────────────────────────────────────────────────
# Spazio dei nomi DEDICATO al License Manager: non condivide con `XTraderBridge` (token del bot),
# così le due credenziali restano separate e revocabili indipendentemente.
SERVICE = "XTraderLicenseManager"
ACCOUNT_TOKEN = "github_publish_token"

# ── Impostazioni (NON segrete) su disco ─────────────────────────────────────────────────────────
PUBLISH_CONFIG_FILE = "publish_config.json"

# Default sicuri: pubblicazione **spenta** finché il proprietario non la configura e la abilita
# (fail-closed sull'attivazione: nessuna pubblicazione automatica non richiesta).
DEFAULTS = {
    "enabled": False,
    "repo": "",                          # "owner/nome-repo" (es. "tizio/xtrader-revocation")
    "path": "revocation_list.txt",       # percorso del file dentro il repo
    "branch": "main",
    "interval_hours": 6,                 # ri-pubblica ogni N ore (ben dentro la finestra del bridge)
}

# Limite dell'intervallo **DERIVATO dalla finestra di freschezza del bridge** (rilievo CodeRabbit
# #158). Il bridge rifiuta una lista firmata da più di `MAX_LIST_AGE_S` (24 h) e si blocca
# fail-closed: permettere una cadenza più lunga significherebbe accettare impostazioni che
# **garantiscono** il lockout tra una pubblicazione e l'altra — proprio il guasto che questa
# funzione esiste per evitare.
#
# Il massimo è **un TERZO** della finestra, non il suo valore pieno: così anche **saltando un tick**
# (PC sospeso, rete giù per un giro) la lista resta fresca. Deriviamo dalla costante reale del bridge
# invece di ricopiarne il numero, così i due valori non possono divergere in futuro.
_BRIDGE_FRESHNESS_HOURS = max(1, revocation_client.MAX_LIST_AGE_S // 3600)   # 24 h
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = max(MIN_INTERVAL_HOURS, _BRIDGE_FRESHNESS_HOURS // 3)   # 8 h


def _keyring():
    """Il modulo `keyring` se importabile e con un backend, altrimenti `None` (dipendenza
    opzionale: la sua assenza NON deve rompere nemmeno l'import di questo modulo)."""
    try:
        import keyring
        return keyring
    except Exception:       # noqa: BLE001 — dipendenza opzionale assente/rotta: fallback pulito
        return None


def keyring_available() -> bool:
    """`True` se esiste un backend keyring **usabile** (probe non distruttivo). `False` → il token
    non è memorizzabile: la GUI lo dice e la pubblicazione automatica resta spenta."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.get_password(SERVICE, "__probe__")
        return True
    except Exception:       # noqa: BLE001 — backend `fail`/non configurato → non disponibile
        return False


def save_publish_token(token: str) -> bool:
    """Salva il token di pubblicazione nel keyring. `True` se riuscito. Un token vuoto non si salva
    (usa `delete_publish_token`). **Il token non viene mai scritto su disco né loggato.**"""
    kr = _keyring()
    if kr is None or not str(token or "").strip():
        return False
    try:
        kr.set_password(SERVICE, ACCOUNT_TOKEN, str(token).strip())
        return True
    except Exception:       # noqa: BLE001 — backend non disponibile: il chiamante avvisa
        return False


def load_publish_token() -> "str | None":
    """Il token dal keyring, o `None` se assente/backend non disponibile (fail-safe)."""
    kr = _keyring()
    if kr is None:
        return None
    try:
        value = kr.get_password(SERVICE, ACCOUNT_TOKEN)
    except Exception:       # noqa: BLE001 — lettura fallita = come assente (mai crash)
        return None
    return value or None


def delete_publish_token() -> bool:
    """Rimuove il token dal keyring. `True` se rimosso, `False` se assente/backend non disponibile."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, ACCOUNT_TOKEN)
        return True
    except Exception:       # noqa: BLE001 — voce assente o backend giù: nulla da rimuovere
        return False


def publish_config_path(directory: "str | None" = None) -> str:
    """Percorso del file impostazioni (`publish_config.json`) nella cartella data o in `manager_dir()`."""
    return os.path.join(directory or manager_dir(), PUBLISH_CONFIG_FILE)


def _coerce_int(value, default: int) -> int:
    """Intero da `value`, o `default` se non convertibile. `bool` è rifiutato (`True` non è 1 ora)."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_config(raw) -> dict:
    """Impostazioni **normalizzate e complete** a partire da un dict parziale/sporco.

    Ogni chiave assente o di tipo errato ricade sul default (mai un `KeyError` a valle). `repo`/`path`/
    `branch` sono ripuliti dagli spazi; `enabled` è un bool vero (una stringa non lo attiva per sbaglio);
    `interval_hours` è limitato a `MIN_INTERVAL_HOURS..MAX_INTERVAL_HOURS`. **Nessun campo segreto**:
    un eventuale `token` presente nel dict viene **scartato** (non deve mai finire su disco)."""
    src = raw if isinstance(raw, dict) else {}
    hours = _coerce_int(src.get("interval_hours"), DEFAULTS["interval_hours"])
    hours = max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, hours))
    return {
        "enabled": src.get("enabled") is True,
        "repo": str(src.get("repo") or "").strip(),
        "path": str(src.get("path") or "").strip() or DEFAULTS["path"],
        "branch": str(src.get("branch") or "").strip() or DEFAULTS["branch"],
        "interval_hours": hours,
    }


def load_publish_config(directory: "str | None" = None) -> dict:
    """Impostazioni dal disco, **normalizzate**. Fail-safe: file assente/corrotto/illeggibile →
    default (pubblicazione spenta), mai un crash all'avvio della GUI."""
    try:
        with open(publish_config_path(directory), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return normalize_config({})
    return normalize_config(raw)


def save_publish_config(cfg: dict, directory: "str | None" = None) -> None:
    """Scrive le impostazioni in modo **atomico** (temp + replace, via `atomic_io`), creando la
    cartella se serve. Salva SOLO i campi normalizzati: **il token non passa mai di qui**. Gli errori
    di I/O propagano (la GUI li mostra come «impostazioni non salvate»)."""
    path = publish_config_path(directory)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    atomic_io.atomic_write_json(path, normalize_config(cfg), indent=2, ensure_ascii=False)


def validate_config(cfg: dict) -> "str | None":
    """`None` se le impostazioni sono utilizzabili per pubblicare, altrimenti un **messaggio d'errore**
    leggibile. Controlla che `repo` sia nella forma `owner/nome` (un solo `/`, entrambe le parti non
    vuote, nessuno spazio) e che `path`/`branch` non siano vuoti."""
    norm = normalize_config(cfg)
    repo = norm["repo"]
    if not repo:
        return "Indica il repository nella forma «owner/nome» (es. tuonome/xtrader-revocation)."
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1] or " " in repo:
        return f"Repository non valido: «{repo}». Usa la forma «owner/nome»."
    if not norm["path"]:
        return "Indica il percorso del file nel repository (es. revocation_list.txt)."
    if not norm["branch"]:
        return "Indica il branch (es. main)."
    # Niente spazi in `path`/`branch` (rilievo Fugu #158): finiscono in DUE URL diversi (Contents API
    # e raw), e un disallineamento di codifica renderebbe il file non scaricabile dal bridge →
    # lockout fail-closed. Meglio rifiutarli qui, chiaramente, che produrre un URL che non funziona.
    for campo, etichetta in (("path", "percorso del file"), ("branch", "branch")):
        if any(c.isspace() for c in norm[campo]):
            return f"Il {etichetta} non può contenere spazi: «{norm[campo]}»."
    return None
