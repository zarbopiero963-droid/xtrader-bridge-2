"""License Manager — **logica pura** (issue #140, PR 3a).

Funzioni senza GUI e senza stato globale: generazione della keypair Ed25519, custodia locale del
seed PRIVATO e firma delle licenze. La GUI e il workflow di build sono la **PR 3b**.

Riuso deliberato: la firma passa da `xtrader_bridge.licensing.license.build_license` (già presente,
PR 1) e la keypair da `xtrader_bridge.licensing.ed25519` (Ed25519 pure-Python). La scrittura su
disco usa `xtrader_bridge.atomic_io` (atomica come il resto del repo). Importare queste utility del
bridge nel tool del proprietario va bene: è il **bridge** che non deve importare **questo** package
(niente firma/chiave privata nell'EXe del bridge) — non il contrario.

Custodia della chiave (decisione proprietario): **file locale** in `%APPDATA%\\XTraderLicenseManager\\
signing_key.json`, MAI nel repo/EXE, con funzione di **export/backup**. Regola di sicurezza chiave:
un file-chiave **corrotto** NON viene mai scartato in silenzio (a differenza dello stato-licenza del
bridge) — perderlo = non poter più rinnovare le licenze dei bridge già distribuiti. Perciò
`load_signing_key` **solleva** su corruzione e `save_signing_key` **rifiuta** di sovrascrivere una
chiave valida senza `overwrite=True` esplicito.
"""

from __future__ import annotations

import json
import os

from xtrader_bridge import atomic_io
from xtrader_bridge.licensing import ed25519
from xtrader_bridge.licensing.hwid import is_identifiable
from xtrader_bridge.licensing.license import build_license

# Cartella utente del License Manager (SEPARATA da quella del bridge, `XTraderBridge`), così la
# chiave privata del proprietario non finisce mai vicino ai dati del bridge distribuito.
APP_DIR_NAME = "XTraderLicenseManager"
SIGNING_KEY_FILE = "signing_key.json"

# Versione dello schema del file-chiave (per migrazioni future senza ambiguità).
KEY_FORMAT_VERSION = 1

# Un seed Ed25519 è esattamente 32 byte → 64 caratteri esadecimali.
_SEED_BYTES = 32
_SEED_HEX_LEN = _SEED_BYTES * 2

# Secondi in un giorno (durata licenza espressa in giorni interi).
_SECONDS_PER_DAY = 86_400

# Tetto anti-typo sui giorni di licenza (~10 anni). Non è una policy commerciale: evita solo che un
# «fat finger» (es. 100000) generi una licenza di fatto perenne. Il proprietario può alzarlo.
MAX_LICENSE_DAYS = 3650

# Prefisso/suffisso del temporaneo della scrittura atomica del file-chiave (coerente con gli altri
# moduli del repo, che filtrano i temporanei per prefisso).
_TMP_PREFIX = ".signing_key_"
_TMP_SUFFIX = ".tmp"


class KeyFileCorruptError(Exception):
    """Il file-chiave esiste ma è illeggibile/incoerente. **Mai** trattato come «assente»: si
    solleva così il chiamante NON ci sovrascrive sopra perdendo una chiave forse recuperabile."""


class KeyExistsError(Exception):
    """Esiste già una chiave valida e `save_signing_key` è stato chiamato senza `overwrite=True`.
    Rigenerare la keypair invaliderebbe la chiave pubblica incorporata nei bridge già distribuiti:
    l'overwrite deve essere una scelta esplicita del proprietario."""


def manager_dir() -> str:
    """Cartella utente del License Manager.

    Windows: ``%APPDATA%\\XTraderLicenseManager``. Altrove (dev/CI/Linux/macOS):
    ``$XDG_CONFIG_HOME/XTraderLicenseManager`` o ``~/.config/XTraderLicenseManager``. Stessa logica
    di `xtrader_bridge.config_store.config_dir`, ma cartella dedicata."""
    base = (
        os.environ.get("APPDATA")
        or os.environ.get("XDG_CONFIG_HOME")
        or os.path.join(os.path.expanduser("~"), ".config")
    )
    return os.path.join(base, APP_DIR_NAME)


def signing_key_path(directory: "str | None" = None) -> str:
    """Percorso del file-chiave (`signing_key.json`) nella cartella data o in `manager_dir()`."""
    return os.path.join(directory or manager_dir(), SIGNING_KEY_FILE)


def _seed_from_hex(seed_hex: str) -> bytes:
    """Converte un seed esadecimale in 32 byte, validando lunghezza/formato (fail-closed)."""
    if not isinstance(seed_hex, str) or len(seed_hex) != _SEED_HEX_LEN:
        raise ValueError("il seed della chiave privata deve essere 64 caratteri esadecimali (32 byte)")
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError as exc:
        raise ValueError("seed della chiave privata non esadecimale") from exc
    if len(seed) != _SEED_BYTES:
        raise ValueError("il seed della chiave privata deve essere 32 byte")
    return seed


def generate_keypair() -> "tuple[str, str]":
    """Genera una nuova keypair Ed25519 → ``(seed_privato_hex, chiave_pubblica_hex)``.

    Il seed è 32 byte da `os.urandom` (CSPRNG del sistema). La pubblica è derivata dal seed. Il
    proprietario incolla la **pubblica** nel bridge (`LICENSE_PUBLIC_KEY_HEX`) e custodisce il
    **seed** (mai nel repo/EXE)."""
    seed = os.urandom(_SEED_BYTES)
    public = ed25519.public_key(seed)
    return seed.hex(), public.hex()


def _public_for_seed(seed_hex: str) -> str:
    """Chiave pubblica (hex) derivata dal seed dato — fonte unica per i controlli di coerenza."""
    return ed25519.public_key(_seed_from_hex(seed_hex)).hex()


def _restrict_perms(path: str) -> None:
    """Permessi `0o600` best-effort (POSIX; su Windows il modello ACL è diverso → no-op)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass    # Windows / filesystem senza permessi POSIX: best-effort, non è un errore


def _persist_key_file(path: str, payload: dict, *, overwrite: bool) -> None:
    """Scrive il file-chiave. Due modalità (review Fable #145, TOCTOU):

    - `overwrite=False` → **creazione ESCLUSIVA** `O_CREAT|O_EXCL`: se il file esiste già la `open`
      fallisce **atomicamente** con `KeyExistsError`, senza la finestra check-then-write in cui due
      processi concorrenti potrebbero entrambi passare il controllo e sovrascrivere (perdere) una
      chiave esistente. Un crash a metà di una create (nessuna chiave preesistente per definizione)
      lascia un file parziale → `load_signing_key` lo segnala corrotto e il proprietario rigenera;
    - `overwrite=True` → **sostituzione atomica** (temp + `os.replace`): rimpiazzo DELIBERATO e
      crash-safe di una chiave esistente.
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True)
    if overwrite:
        atomic_io.atomic_write_text(path, data, prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX)
        _restrict_perms(path)
        return
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise KeyExistsError(
            f"esiste già una chiave di firma in {path}: rigenerarla invaliderebbe i bridge "
            "distribuiti; usa overwrite=True per sostituirla deliberatamente") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        # create fallita a metà: rimuovi il file parziale appena creato (non c'era una chiave
        # prima, quindi non si distrugge nulla di irrecuperabile) e propaga.
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    _restrict_perms(path)


def save_signing_key(path: str, seed_hex: str, public_hex: str, now: int,
                     *, overwrite: bool = False) -> None:
    """Salva la keypair sul file-chiave in modo **atomico** e con permessi ristretti.

    - Verifica di **coerenza**: `public_hex` deve corrispondere davvero al seed (previene di
      salvare una coppia incongruente che poi firmerebbe licenze non verificabili).
    - **Non sovrascrive** una chiave valida già presente senza `overwrite=True` (protezione contro
      la rigenerazione accidentale che invaliderebbe i bridge distribuiti). L'enforcement è
      **atomico** via `O_EXCL` in `_persist_key_file` (niente race TOCTOU, review Fable #145); la
      `load_signing_key` qui sotto serve a dare un errore precoce e a distinguere il caso **corrotto**
      (`KeyFileCorruptError`, si decide a mano) da quello di una chiave valida già presente.
    - Permessi `0o600` best-effort (POSIX; su Windows il modello ACL è diverso).
    """
    seed_hex = str(seed_hex).strip().lower()
    public_hex = str(public_hex).strip().lower()
    if _public_for_seed(seed_hex) != public_hex:
        raise ValueError("chiave pubblica incoerente col seed privato: coppia non valida")

    if not overwrite and load_signing_key(path) is not None:
        raise KeyExistsError(
            "esiste già una chiave di firma: rigenerarla invaliderebbe i bridge distribuiti; "
            "usa overwrite=True per sostituirla deliberatamente")

    payload = {
        "v": KEY_FORMAT_VERSION,
        "seed": seed_hex,
        "public": public_hex,
        "created": int(now),
    }
    _persist_key_file(path, payload, overwrite=overwrite)


def load_signing_key(path: str) -> "dict | None":
    """Carica il file-chiave. **Assente → `None`**; **corrotto/incoerente → solleva**
    `KeyFileCorruptError` (mai scartato in silenzio).

    Ritorna ``{"seed", "public", "created"}`` (validati) se presente e coerente. Un errore di
    I/O diverso da «non esiste» (permessi) viene propagato: non è né «assente» né «corrotto»,
    e nascondere il seed dietro un `None` porterebbe a sovrascriverlo."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return None
    # OSError (permessi/altro) propaga di proposito: non è «assente».

    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise KeyFileCorruptError(f"file-chiave non è JSON valido: {path}") from exc

    if not isinstance(data, dict):
        raise KeyFileCorruptError(f"file-chiave con struttura inattesa: {path}")
    seed_hex = data.get("seed")
    public_hex = data.get("public")
    if not isinstance(seed_hex, str) or not isinstance(public_hex, str):
        raise KeyFileCorruptError(f"file-chiave privo di seed/public: {path}")
    # Coerenza crittografica: la pubblica salvata deve derivare dal seed salvato (intercetta
    # manomissioni/bit-rot del file). `_public_for_seed` valida anche il formato del seed.
    try:
        derived = _public_for_seed(seed_hex)
    except ValueError as exc:
        raise KeyFileCorruptError(f"seed del file-chiave non valido: {path}") from exc
    if derived != public_hex.strip().lower():
        raise KeyFileCorruptError(f"seed e chiave pubblica del file-chiave non coerenti: {path}")

    created = data.get("created")
    return {"seed": seed_hex.strip().lower(),
            "public": public_hex.strip().lower(),
            "created": created if isinstance(created, int) and not isinstance(created, bool) else None}


def export_signing_key(src_path: str, dest_path: str, *, overwrite: bool = False) -> None:
    """Copia il file-chiave in `dest_path` (backup su chiavetta/altra cartella), in modo atomico.

    Rilegge e riscrive il contenuto **validato** (via `load_signing_key`): un backup di un file
    corrotto solleverebbe, così non si esporta spazzatura al posto della chiave. Assente → solleva
    `FileNotFoundError` (non c'è nulla da esportare).

    Come `save_signing_key`, **non sovrascrive** una chiave valida già presente in `dest_path`
    senza `overwrite=True` (review CodeRabbit #145): un backup esistente — magari di un'ALTRA
    keypair — non va perso in silenzio (perderla = non poter più rinnovare quei bridge).
    L'enforcement no-overwrite è **atomico** (`O_EXCL`, review Fable #145): niente race TOCTOU."""
    key = load_signing_key(src_path)
    if key is None:
        raise FileNotFoundError(f"nessun file-chiave da esportare: {src_path}")
    if not overwrite and load_signing_key(dest_path) is not None:
        raise KeyExistsError(
            f"esiste già una chiave di firma in {dest_path}: usa overwrite=True per sostituirla "
            "deliberatamente")
    payload = {
        "v": KEY_FORMAT_VERSION,
        "seed": key["seed"],
        "public": key["public"],
        "created": int(key["created"]) if isinstance(key["created"], int) else 0,
    }
    _persist_key_file(dest_path, payload, overwrite=overwrite)


def issue_license(seed_hex: str, name: str, days: int, hardware_id: str, now: int) -> str:
    """Firma una licenza: ``(seed, Nome Cognome, Giorni, Hardware ID, now)`` → **token**.

    Validazioni **fail-closed** (una licenza si emette solo con dati sensati):
    - `name`: stringa non vuota (dopo strip);
    - `days`: intero ``1 <= days <= MAX_LICENSE_DAYS`` (no bool, no float, no ≤0);
    - `hardware_id`: **identificabile** (`is_identifiable` — non la sentinella `NO_HARDWARE_ID`,
      non vuoto): una licenza legata a un hardware cieco varrebbe su tutte le macchine anonime;
    - `seed_hex`: 32 byte esadecimali.

    Scadenza: ``exp = now + days*86400`` (unix seconds UTC); ``iss = now``. La firma la produce
    `build_license` con la chiave PRIVATA. Ritorna il token base64 copia-incollabile."""
    seed = _seed_from_hex(str(seed_hex).strip())

    clean_name = str(name).strip() if isinstance(name, str) else ""
    if not clean_name:
        raise ValueError("il nome del titolare della licenza non può essere vuoto")

    if isinstance(days, bool) or not isinstance(days, int):
        raise ValueError("i giorni di licenza devono essere un intero")
    if days < 1:
        raise ValueError("i giorni di licenza devono essere almeno 1")
    if days > MAX_LICENSE_DAYS:
        raise ValueError(f"i giorni di licenza superano il massimo consentito ({MAX_LICENSE_DAYS})")

    clean_hw = str(hardware_id).strip() if isinstance(hardware_id, str) else ""
    if not is_identifiable(clean_hw):
        raise ValueError("Hardware ID non identificabile: impossibile legare la licenza a questa macchina")

    issued = int(now)
    expiry = issued + days * _SECONDS_PER_DAY
    return build_license(seed, clean_name, clean_hw, issued, expiry)
