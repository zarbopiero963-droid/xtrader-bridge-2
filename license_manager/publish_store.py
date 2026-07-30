"""License Manager — **impostazioni della pubblicazione automatica** delle revoche (#157).

La lista di revoche firmata va **ri-pubblicata periodicamente** all'URL statico che il bridge
controlla (finestra `MAX_LIST_AGE_S`, oggi **3 giorni**): oltre quel tetto i bridge legittimi si bloccano
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
import logging
import os
import re
import time as _time

from xtrader_bridge import atomic_io
from xtrader_bridge.licensing import revocation_client

from .core import manager_dir

_log = logging.getLogger(__name__)

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
# #158). Il bridge rifiuta una lista firmata da più di `MAX_LIST_AGE_S` (3 giorni) e si blocca
# fail-closed: permettere una cadenza più lunga significherebbe accettare impostazioni che
# **garantiscono** il lockout tra una pubblicazione e l'altra — proprio il guasto che questa
# funzione esiste per evitare.
#
# Il massimo è **un TERZO** della finestra, non il suo valore pieno: così anche **saltando un tick**
# (PC sospeso, rete giù per un giro) la lista resta fresca. Deriviamo dalla costante reale del bridge
# invece di ricopiarne il numero, così i due valori non possono divergere in futuro.
_BRIDGE_FRESHNESS_HOURS = max(1, revocation_client.MAX_LIST_AGE_S // 3600)   # 72 h (3 giorni)
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = max(MIN_INTERVAL_HOURS, _BRIDGE_FRESHNESS_HOURS // 3)   # 24 h

# Charset REALE di un segmento `owner`/`nome` su GitHub (rilievo Fable #158). Il `repo` finisce
# grezzo in DUE URL (Contents API e raw): un carattere come `%`, `?` o `#` li deformerebbe entrambi
# (query-string/fragment al posto del path) → 404 → nessuna lista pubblicata e bridge bloccati
# fail-closed. Nessun repository GitHub legittimo contiene quei caratteri: rifiutarli qui, con un
# messaggio chiaro mentre si digita, è meglio di un 404 incomprensibile a pubblicazione avvenuta.
_REPO_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


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
    vuote e composte solo dai caratteri ammessi da GitHub) e che `path`/`branch` non siano vuoti."""
    norm = normalize_config(cfg)
    repo = norm["repo"]
    if not repo:
        return "Indica il repository nella forma «owner/nome» (es. tuonome/xtrader-revocation)."
    parts = repo.split("/")
    if len(parts) != 2 or not all(_REPO_SEGMENT.fullmatch(p) for p in parts):
        return (f"Repository non valido: «{repo}». Usa la forma «owner/nome», "
                "con lettere, numeri, «.», «_» o «-».")
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


# ── Stato dell'ultima pubblicazione riuscita (NON impostazioni) ─────────────────────────────────
# File SEPARATO da `publish_config.json` di proposito. Quello è **configurazione** dell'utente:
# validata, normalizzata, con default sicuri. Questo è **stato osservato**: un timestamp scritto dal
# programma. Mescolarli significherebbe far passare lo stato per `normalize_config` (che scarterebbe
# la chiave sconosciuta) o allargare la normalizzazione a un campo che l'utente non deve poter
# scrivere. Restano due file, due responsabilità.
#
# A cosa serve. La pubblicazione automatica gira solo mentre il License Manager è aperto; se si
# ferma — timer perso dopo una sospensione, rete giù, token scaduto — oggi il guasto sarebbe **muto**
# e il primo segnale arriverebbe dai bridge bloccati giorni dopo. Persistere l'istante dell'ultima
# pubblicazione RIUSCITA permette alla finestra di dirlo a colpo d'occhio, anche dopo aver chiuso e
# riaperto il programma.
PUBLISH_STATE_FILE = "publish_state.json"

# Stati di freschezza dell'ultima pubblicazione (l'ordine è di gravità crescente).
FRESHNESS_NEVER = "never"       # mai pubblicato da questo PC
FRESHNESS_OK = "ok"             # dentro il margine
FRESHNESS_WARN = "warn"         # oltre un giro di cadenza: qualcosa potrebbe essersi fermato
FRESHNESS_EXPIRED = "expired"   # oltre la finestra del bridge: i bridge legittimi si bloccano


def publish_state_path(directory: "str | None" = None) -> str:
    """Percorso del file di stato (`publish_state.json`) nella cartella data o in `manager_dir()`."""
    return os.path.join(directory or manager_dir(), PUBLISH_STATE_FILE)


def load_last_publish(directory: "str | None" = None) -> "int | None":
    """Timestamp unix dell'ultima pubblicazione **riuscita**, o `None` se non c'è.

    **Fail-safe**: file assente, JSON rotto, permessi, valore di tipo sbagliato o negativo → `None`
    («mai pubblicato»), mai un crash all'apertura della finestra. `None` è anche la direzione
    **sicura** dell'errore: mostra una situazione peggiore del reale e porta a controllare, invece di
    rassicurare a torto."""
    try:
        with open(publish_state_path(directory), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    valore = raw.get("last_publish_ok") if isinstance(raw, dict) else None
    if isinstance(valore, bool) or not isinstance(valore, int) or valore <= 0:
        return None     # `True` non è un istante; 0/negativi non sono timestamp plausibili
    return valore


def save_last_publish(ts: int, directory: "str | None" = None) -> None:
    """Registra l'istante di una pubblicazione riuscita, in modo **atomico** (`atomic_io`).

    Gli errori di I/O **non** propagano: la pubblicazione è già riuscita e non deve diventare un
    fallimento perché il file di stato non si scrive. Anche qui l'errore va nella direzione sicura —
    l'etichetta resta indietro rispetto alla realtà, quindi semmai porta a controllare."""
    path = publish_state_path(directory)
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        atomic_io.atomic_write_json(path, {"last_publish_ok": int(ts)}, indent=2, ensure_ascii=False)
    except (OSError, ValueError, TypeError) as exc:      # best-effort: mai far fallire un successo
        _log.warning("Stato ultima pubblicazione non salvato [%s]", type(exc).__name__)


def publish_freshness(last_ts: "int | None", now: int,
                      window_s: "int | None" = None) -> dict:
    """Classifica quanto è vecchia l'ultima pubblicazione riuscita.

    Ritorna ``{"state", "age_s", "window_s"}`` con `state` fra `FRESHNESS_*` e `age_s` `None` se non
    si è mai pubblicato. Le soglie sono **derivate dalla finestra del bridge**, non numeri ricopiati:

    - `expired` a `age >= window`: da lì in poi il bridge considera la lista stantia e **si blocca**;
    - `warn` a `age >= window/3`: è la cadenza massima ammessa per la pubblicazione automatica
      (`MAX_INTERVAL_HOURS`), quindi superarla significa che **almeno un giro è saltato** — il primo
      sintomo osservabile che qualcosa si è fermato, con ancora due terzi di finestra per rimediare.

    Un `age` negativo (orologio spostato indietro) è trattato come `0`: non si finge freschezza
    futura, ma nemmeno si allarma per un aggiustamento d'orologio."""
    finestra = int(revocation_client.MAX_LIST_AGE_S if window_s is None else window_s)
    if last_ts is None:
        return {"state": FRESHNESS_NEVER, "age_s": None, "window_s": finestra}
    eta = max(0, int(now) - int(last_ts))
    if eta >= finestra:
        stato = FRESHNESS_EXPIRED
    elif eta >= finestra // 3:
        stato = FRESHNESS_WARN
    else:
        stato = FRESHNESS_OK
    return {"state": stato, "age_s": eta, "window_s": finestra}


def _eta_leggibile(age_s: int) -> str:
    """«2 ore fa», «3 giorni e 4 ore fa», «meno di un'ora fa» — senza librerie esterne."""
    ore_totali = age_s // 3600
    if ore_totali < 1:
        return "meno di un'ora fa"
    giorni, ore = divmod(ore_totali, 24)
    if giorni < 1:
        return "1 ora fa" if ore == 1 else f"{ore} ore fa"
    pezzo_giorni = "1 giorno" if giorni == 1 else f"{giorni} giorni"
    if ore == 0:
        return f"{pezzo_giorni} fa"
    pezzo_ore = "1 ora" if ore == 1 else f"{ore} ore"
    return f"{pezzo_giorni} e {pezzo_ore} fa"


def format_last_publish(last_ts: "int | None", now: int,
                        window_s: "int | None" = None) -> tuple:
    """`(testo, stato)` pronti per l'etichetta della finestra — logica pura, testabile headless.

    Il testo dice **quando** e **quanto fa**; nei due stati di allarme aggiunge la conseguenza in
    chiaro, perché «3 giorni fa» da solo non dice a chi legge che cosa comporta."""
    fresh = publish_freshness(last_ts, now, window_s)
    stato = fresh["state"]
    if stato == FRESHNESS_NEVER:
        return ("Ultima pubblicazione riuscita: mai da questo PC", stato)
    quando = _time.strftime("%d/%m/%Y %H:%M", _time.localtime(int(last_ts)))
    testo = f"Ultima pubblicazione riuscita: {quando} · {_eta_leggibile(fresh['age_s'])}"
    if stato == FRESHNESS_EXPIRED:
        return (f"{testo}  ⛔ oltre la finestra: i bridge legittimi si bloccano", stato)
    if stato == FRESHNESS_WARN:
        return (f"{testo}  ⚠️ un giro di pubblicazione è saltato", stato)
    return (testo, stato)
