"""PR-16: coda dei segnali attivi (logica pura, testabile).

Gestisce uno o più segnali "attivi" (le righe che XTrader dovrebbe vedere nel
CSV) con un **timeout per singolo segnale** e tre modalità:

- ``OVERWRITE_LAST`` (default): un solo segnale attivo alla volta — un nuovo
  segnale sostituisce il precedente. È il comportamento storico del bridge
  (one-signal-at-a-time), il più conservativo per il rischio di doppia scommessa.
- ``APPEND_ACTIVE``: più segnali attivi contemporaneamente (più righe), ognuno
  con il proprio timeout.
- ``QUEUE_UNTIL_CONFIRMED``: come append, ma i segnali restano finché non sono
  **confermati** (o scadono per timeout).

Invarianti di sicurezza preservate:
- nessun **vecchio segnale** resta per sempre: ogni segnale scade comunque per
  timeout, anche se mai confermato;
- la coda gestisce **solo le righe**; non scrive il CSV e non tocca l'header (lo
  mantiene `csv_writer`). L'aggancio al runtime è un passo successivo.

Modulo puro: nessuna dipendenza da GUI/CSV/Telegram, interamente testabile.
"""

import math
import time
from dataclasses import dataclass, field

OVERWRITE_LAST = "OVERWRITE_LAST"
APPEND_ACTIVE = "APPEND_ACTIVE"
QUEUE_UNTIL_CONFIRMED = "QUEUE_UNTIL_CONFIRMED"
MODES = (OVERWRITE_LAST, APPEND_ACTIVE, QUEUE_UNTIL_CONFIRMED)
DEFAULT_MODE = OVERWRITE_LAST
DEFAULT_TIMEOUT = 90        # secondi di vita di un segnale se non confermato/sostituito


def normalize_mode(mode) -> str:
    """Normalizza la modalità a una di MODES; valore ignoto/mancante → DEFAULT_MODE
    (il default conservativo: un solo segnale attivo)."""
    m = str(mode or "").strip().upper()
    return m if m in MODES else DEFAULT_MODE


@dataclass
class ActiveSignal:
    """Un segnale attualmente attivo nella coda."""

    signal_id: str
    row: dict
    added_at: float
    timeout: float

    def expires_at(self) -> float:
        return self.added_at + self.timeout


@dataclass
class SignalQueue:
    """Coda dei segnali attivi. Pura: gestisce righe, non scrive il CSV."""

    mode: str = DEFAULT_MODE
    default_timeout: float = DEFAULT_TIMEOUT
    _active: list = field(default_factory=list)   # ActiveSignal, in ordine d'arrivo
    _counter: int = 0

    def __post_init__(self):
        self.mode = normalize_mode(self.mode)
        self.default_timeout = self._validate_timeout(self.default_timeout)

    @staticmethod
    def _validate_timeout(value) -> float:
        """Un timeout deve essere un numero FINITO e > 0. Un valore non valido
        (None già gestito a monte, ma anche `NaN`/`inf`/negativo/non numerico)
        romperebbe l'invariante "nessun vecchio segnale resta attivo per sempre":
        es. con `NaN`, `expires_at()` non è mai `<= now` e il segnale non
        scadrebbe MAI. Quindi si fallisce subito (fail-fast)."""
        try:
            t = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"timeout non valido: {value!r}")
        if not math.isfinite(t) or t <= 0:
            raise ValueError(f"timeout deve essere un numero finito > 0 (ricevuto {value!r})")
        return t

    def add(self, row: dict, *, signal_id: str = None, now: float = None,
            timeout: float = None) -> str:
        """Aggiunge un segnale e ritorna il suo `signal_id`.

        - ``OVERWRITE_LAST``: sostituisce tutti i segnali attivi con questo;
        - altre modalità: aggiorna se `signal_id` è già presente, altrimenti accoda.

        `signal_id` assente → generato automaticamente. `timeout` assente →
        `default_timeout`."""
        now = time.time() if now is None else now
        timeout = self.default_timeout if timeout is None else self._validate_timeout(timeout)
        if signal_id is None:
            # Id auto-generato che NON collide con un id fornito dal chiamante:
            # altrimenti un "s1" esplicito verrebbe sovrascritto dal primo add()
            # senza id (stesso "s1") e una riga ancora attiva sparirebbe.
            existing = {a.signal_id for a in self._active}
            self._counter += 1
            while f"s{self._counter}" in existing:
                self._counter += 1
            signal_id = f"s{self._counter}"
        sig = ActiveSignal(signal_id, dict(row), now, timeout)
        if self.mode == OVERWRITE_LAST:
            self._active = [sig]
        else:
            self._active = [a for a in self._active if a.signal_id != signal_id]
            self._active.append(sig)
        return signal_id

    def expire(self, now: float = None) -> list:
        """Rimuove i segnali scaduti (timeout raggiunto) e ne ritorna gli id.
        Garantisce che nessun vecchio segnale resti attivo per sempre."""
        now = time.time() if now is None else now
        expired = [a.signal_id for a in self._active if a.expires_at() <= now]
        if expired:
            self._active = [a for a in self._active if a.expires_at() > now]
        return expired

    def remove(self, signal_id: str) -> bool:
        """Rimuove un segnale per id. True se era presente."""
        before = len(self._active)
        self._active = [a for a in self._active if a.signal_id != signal_id]
        return len(self._active) < before

    def confirm(self, signal_id: str) -> bool:
        """Un segnale confermato (es. da XTrader, PR-17) viene rimosso dagli attivi.
        Alias semantico di `remove`."""
        return self.remove(signal_id)

    def active_ids(self) -> list:
        return [a.signal_id for a in self._active]

    def active_rows(self) -> list:
        """Righe attualmente attive (copie difensive), in ordine d'arrivo. È ciò
        che andrebbe scritto nel CSV sotto l'header."""
        return [dict(a.row) for a in self._active]

    def is_empty(self) -> bool:
        return not self._active
