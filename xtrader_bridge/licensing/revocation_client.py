"""Client **bridge** della revoca online (issue #140 R3c): scarica la lista di revoche firmata da un
**URL statico**, la verifica, applica **anti-replay** e la usa nel **gate licenza fail-closed**.

Divisione delle responsabilità (coerente con `license.py`/`revocation.py`):

- **logica pura e testabile, qui**: fetch (dietro un *probe* iniettabile, come `wizard.py`), verifica +
  anti-replay (`accept_signed`), calcolo revoca per la licenza corrente (`license_revoked`) e la
  **decisione di gate** sincrona (`gate_allows`) — nessun thread, nessuna GUI;
- **orchestrazione (thread di refresh + cablaggio nel lock), in `app.py`**: un supervisore periodico
  aggiorna in memoria `(lista_verificata, verificata_a)`; il gate le legge **sincrono** (niente rete
  nel gate) e blocca **senza grazia** (decisione proprietario: il bridge deve **raggiungere e
  verificare** l'URL per operare).

Modello di sicurezza:

- la lista è **firmata Ed25519** con la chiave privata del proprietario (mai nel repo/EXE); il bridge
  verifica con la **pubblica** incorporata (`revocation.verify_revocation_list`, già fail-closed);
- **anti-replay/monotònia** (`min_iss`): una lista con `iss` **più vecchio** dell'ultima accettata è
  rifiutata → nessuno può «de-revocare» un utente ripubblicando una vecchia lista firmata;
- **fail-closed no-grace**: senza una lista **verificata e fresca**, `gate_allows` → `False`
  (bloccato). Il *cap* di freschezza assorbe i blip di rete transitori (il supervisore ritenta con
  backoff), ma un'irraggiungibilità **persistente** oltre la soglia blocca (decisione proprietario 2a).
"""

from __future__ import annotations

import json
import os

from . import license as _license
from . import revocation

# ── URL statico della lista di revoche (decisione proprietario 1a: COSTANTE nel codice) ───────────
# ⚠️ PLACEHOLDER — come `LICENSE_PUBLIC_KEY_HEX`. SOSTITUIRE con l'URL statico reale del proprietario
# (dove carica la lista firmata prodotta dal License Manager) **prima di distribuire copie
# licenziate**, e portare il marcatore sotto a `False`. Il TLD `.invalid` (RFC 2606) è **non
# risolvibile**: se il placeholder resta, il bridge fallisce **chiuso** (URL irraggiungibile →
# bloccato), non «aperto».
REVOCATION_LIST_URL = "https://revoche.example.invalid/xtrader/revocation_list.txt"

# Marcatore RILEVABILE del placeholder (come `LICENSE_PUBLIC_KEY_IS_PLACEHOLDER`): resta `True` finché
# sopra c'è l'URL di TEST. Sostituendolo col proprio URL reale il proprietario DEVE portarlo a `False`.
REVOCATION_URL_IS_PLACEHOLDER = True

# File di cache della lista accettata (accanto a `license_state.json` in `config_dir()`).
REVOCATION_CACHE_FILE = "revocation_cache.json"

# Tempi (costanti di modulo; non config utente, coerente con 1a).
DEFAULT_FETCH_TIMEOUT_S = 10          # timeout della singola fetch HTTP
REFRESH_INTERVAL_S = 5 * 60           # cadenza normale di ri-scarico del supervisore
FRESHNESS_MAX_AGE_S = 15 * 60         # oltre questa età una lista verificata è «stantia» → gate chiuso

# Tetto di dimensione della lista scaricata (una lista di revoche resta piccola; evita di ingoiare un
# corpo enorme se l'URL è dirottato su altro).
_MAX_LIST_BYTES = 1_000_000


def revocation_cache_path(config_dir: "str | None" = None) -> str:
    """Percorso del file di cache. `config_dir=None` usa `config_store.config_dir()` (la stessa
    cartella di `license_state.json`)."""
    if config_dir is None:
        from xtrader_bridge import config_store
        config_dir = config_store.config_dir()
    return os.path.join(config_dir, REVOCATION_CACHE_FILE)


def load_cached_signed(path: str) -> "str | None":
    """Legge la lista firmata dall'ultima cache, o `None` se assente/corrotta (**fail-safe**: una cache
    illeggibile non fa crashare l'avvio, degrada a «nessuna cache» → il gate resterà chiuso finché non
    arriva una fetch fresca)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        signed = obj.get("signed") if isinstance(obj, dict) else None
        return signed if isinstance(signed, str) and signed else None
    except (OSError, ValueError):       # assente, JSON rotto, permessi: nessuna cache utilizzabile
        return None


def save_cached_signed(path: str, signed: str) -> None:
    """Scrive la lista firmata in cache in modo **atomico** (tmp + `os.replace`), con `fsync`. Gli
    errori di I/O propagano al chiamante (il supervisore li tratta best-effort)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"signed": str(signed)}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _default_fetch(url: str, *, timeout: int) -> str:
    """Fetch HTTP di default (urllib). Solleva su qualunque errore di rete/HTTP/decodifica; la
    gestione fail-closed è in `fetch_signed`. Cap di dimensione a `_MAX_LIST_BYTES`."""
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as resp:      # noqa: S310 — URL costante fidato
        raw = resp.read(_MAX_LIST_BYTES + 1)
    if len(raw) > _MAX_LIST_BYTES:
        raise ValueError("lista di revoche troppo grande")
    return raw.decode("utf-8").strip()


def fetch_signed(url: str = REVOCATION_LIST_URL, *, fetch=None,
                 timeout: int = DEFAULT_FETCH_TIMEOUT_S) -> "str | None":
    """Scarica la lista firmata dall'URL. **Fail-closed**: qualunque errore (rete, DNS, HTTP, timeout,
    TLS, decodifica, lista troppo grande) → `None` (nessuna lista → il gate resta chiuso). `fetch` è un
    *probe* iniettabile `(url, *, timeout) -> str` (default `_default_fetch`); i test ne passano uno
    finto che restituisce byte canonici o solleva, **senza socket reali**."""
    fetcher = fetch or _default_fetch
    try:
        text = fetcher(url, timeout=timeout)
    except Exception:       # noqa: BLE001 — qualunque problema di fetch: fail-closed → None
        return None
    return text.strip() if isinstance(text, str) and text.strip() else None


def accept_signed(signed: "str | None", *, public_key_hex: "str | None" = None,
                  min_iss: int = 0) -> "revocation.RevocationList | None":
    """Verifica una lista firmata e applica **anti-replay**. Ritorna la `RevocationList` **solo se** la
    firma è valida (`verify_revocation_list`, già fail-closed) **e** `iss >= min_iss` (monotònia: non si
    accetta una lista più vecchia dell'ultima già vista → nessun replay che «de-revoca»). Altrimenti
    `None`."""
    if not signed:
        return None
    revlist = revocation.verify_revocation_list(signed, public_key_hex=public_key_hex)
    if revlist is None:
        return None
    if int(revlist.issued) < int(min_iss):
        return None
    return revlist


def license_revoked(revlist: "revocation.RevocationList | None", *, token: "str | None",
                    hardware_id: "str | None") -> bool:
    """`True` se la licenza corrente è revocata dalla lista: il suo **serial** (deterministico dal
    token, `license.license_serial`) **o** il suo Hardware ID è nella lista. Token vuoto → `False`
    (nessuna licenza da revocare; la validità di base la stabilisce `verify_license`). `revlist=None`
    → `False` (la policy su lista assente è di `gate_allows`, non di qui)."""
    if not token:
        return False
    serial = _license.license_serial(token)
    return revocation.is_revoked(revlist, serial=serial, hardware_id=hardware_id)


def gate_allows(revlist: "revocation.RevocationList | None", *, verified_at: "int | None",
                now: int, token: "str | None", hardware_id: "str | None",
                max_age: int = FRESHNESS_MAX_AGE_S) -> bool:
    """**Decisione di gate sincrona, fail-closed no-grace.** `True` **solo se**:

    1. esiste una lista **verificata** (`revlist is not None` e `verified_at is not None`);
    2. è **fresca** (`now - verified_at <= max_age`): una lista stantia (irraggiungibilità persistente)
       → `False` (decisione proprietario: no grazia, ma il supervisore ha ritentato con backoff entro
       la finestra);
    3. la licenza corrente **non è revocata** in quella lista.

    Nessuna rete qui: legge solo lo stato mantenuto dal supervisore → il gate resta istantaneo."""
    if revlist is None or verified_at is None:
        return False
    if int(now) - int(verified_at) > int(max_age):
        return False
    return not license_revoked(revlist, token=token, hardware_id=hardware_id)
