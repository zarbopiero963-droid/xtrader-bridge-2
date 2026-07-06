"""Single-instance lock (#311-1.1): impedisce la DOPPIA istanza del bridge.

Due processi bridge avrebbero `SignalTracker`/`DailyLimiter`/`SignalQueue` separati in
memoria (i lock `_write_lock`/`_queue_lock` sono intra-processo): entrambi potrebbero
scrivere il CSV → **doppia scommessa possibile**. Questo modulo fornisce un lock di
istanza a livello di sistema operativo, acquisito PRIMA di costruire la GUI.

- **Windows** (target principale): mutex **named** via ctypes (`CreateMutexW`). Scelto
  rispetto al lockfile perché il kernel lo **rilascia da solo alla morte del processo**
  (anche su crash/kill): nessun lock orfano che blocchi il riavvio dopo un blackout.
  Namespace ``Local\\`` (sessione desktop corrente) e non ``Global\\``: copre il caso
  reale (doppio avvio sullo stesso desktop) senza richiedere il privilegio
  `SeCreateGlobalPrivilege` in ambienti terminal-server.
- **POSIX** (dev/CI, nessun utente finale): lockfile con `flock` esclusivo non bloccante;
  anche `flock` si rilascia da solo alla morte del processo. Permette di testare la
  logica reale offline.

Fail-open consapevole: se la CREAZIONE del lock fallisce per un errore imprevisto del
sistema (raro), l'avvio NON viene bloccato — un bridge inutilizzabile per un falso
negativo è peggio del caso limite; l'evento viene loggato. Il rifiuto avviene SOLO
quando il lock risulta **già posseduto** da un'altra istanza (segnale certo).

Modulo foglia: nessun import dal resto del package (usabile ovunque, testabile puro).
"""

import atexit
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Nome del mutex Windows / del file di lock POSIX: identifica QUESTA applicazione.
DEFAULT_NAME = "XTraderBridge"

_ERROR_ALREADY_EXISTS = 183          # winerror: il mutex esisteva già → altra istanza attiva


class InstanceLockHandle:
    """Handle opaco del lock acquisito; da passare a `release`. `kind` è "mutex"
    (Windows) o "flock" (POSIX); `resource` l'handle/fd sottostante."""

    def __init__(self, kind: str, resource, path: str = ""):
        self.kind = kind
        self.resource = resource
        self.path = path
        self.released = False


def acquire(name: str = DEFAULT_NAME, lock_dir: str = ""):
    """Prova ad acquisire il lock di istanza. Ritorna un `InstanceLockHandle` se QUESTO
    processo è l'unica istanza, ``None`` se un'altra istanza lo possiede già.

    `lock_dir` (solo POSIX): cartella del lockfile — tipicamente la cartella dati
    dell'app (`config_store.config_dir()`), passata dal chiamante per tenere questo
    modulo foglia. Vuota → cartella temporanea di sistema.

    Errori IMPREVISTI di creazione (non "già posseduto") → fail-open: si logga e si
    ritorna un handle no-op, così un guasto raro del SO non rende il bridge inavviabile."""
    try:
        if sys.platform == "win32":
            return _acquire_windows(name)
        return _acquire_posix(name, lock_dir)
    except Exception:   # noqa: BLE001 — fail-open consapevole (vedi docstring modulo)
        logger.warning("Single-instance lock non disponibile (errore imprevisto): "
                       "avvio consentito senza protezione doppia-istanza.", exc_info=True)
        return InstanceLockHandle("noop", None)


def _acquire_windows(name: str):
    """CreateMutexW: se `GetLastError()` dice che il mutex esisteva già, un'altra
    istanza è attiva → chiudi l'handle e rifiuta (None)."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    already = (kernel32.GetLastError() == _ERROR_ALREADY_EXISTS)
    if not handle:
        # Creazione fallita (raro): fail-open, vedi docstring di `acquire`.
        logger.warning("CreateMutexW fallita (GetLastError=%s): avvio consentito "
                       "senza protezione doppia-istanza.", kernel32.GetLastError())
        return InstanceLockHandle("noop", None)
    if already:
        kernel32.CloseHandle(handle)
        return None
    lock = InstanceLockHandle("mutex", handle)
    atexit.register(release, lock)          # backstop: il kernel rilascia comunque a morte processo
    return lock


def _acquire_posix(name: str, lock_dir: str):
    """Lockfile + `flock` esclusivo non bloccante. Un secondo `flock` sullo stesso file
    (anche dallo stesso processo, su un altro fd) fallisce con EWOULDBLOCK → None."""
    import fcntl
    import tempfile
    directory = lock_dir or tempfile.gettempdir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{name}.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None                          # lock posseduto da un'altra istanza
    try:                                     # PID per diagnosi manuale (best-effort)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("ascii"))
    except OSError:
        pass
    lock = InstanceLockHandle("flock", fd, path)
    atexit.register(release, lock)          # backstop: flock cade comunque a morte processo
    return lock


def release(lock) -> None:
    """Rilascia il lock (idempotente; `None`/handle no-op = no-op). Il file di lock POSIX
    NON viene cancellato: rimuoverlo sarebbe raceabile con un'istanza in avvio — è il
    `flock`, non l'esistenza del file, a fare da lock."""
    if lock is None or getattr(lock, "released", True):
        return
    lock.released = True
    try:
        if lock.kind == "mutex":
            import ctypes
            ctypes.windll.kernel32.CloseHandle(lock.resource)
        elif lock.kind == "flock":
            import fcntl
            fcntl.flock(lock.resource, fcntl.LOCK_UN)
            os.close(lock.resource)
    except Exception:   # noqa: BLE001 — best-effort: a morte processo rilascia comunque il SO
        logger.debug("Rilascio del single-instance lock fallito (best-effort).", exc_info=True)
