"""PR-15: ciclo di vita del segnale e deduplica (logica pura, testabile).

Riduce il rischio di **doppia scommessa** (#5): lo stesso messaggio non deve
generare due segnali, e una raffica anomala va limitata. È logica pura, separata
da GUI/CSV/Telegram: la deduplica **non altera** il CSV XTrader, decide solo se
un segnale va processato.

Componenti:
- `message_hash(text)`: impronta stabile del messaggio (normalizzato su spazi),
  per riconoscere lo stesso messaggio anche con spaziatura diversa.
- `SignalTracker`: ricorda gli hash recenti in una **finestra** temporale e
  applica un **limite al minuto**. `register(text)` ritorna NEW / DUPLICATE /
  RATE_LIMITED senza scrivere nulla.
- `state()` / `restore_state()` + `save_state`/`load_state` su file: gli hash
  recenti sopravvivono a un **riavvio** (history giornaliera), così un duplicato
  ravvicinato è riconosciuto anche dopo il restart.

Il vocabolario del ciclo di vita (`STATES`) è qui come riferimento per le fasi
successive (PR-16 coda, PR-17 conferma XTrader); l'aggancio al runtime è separato.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

from . import atomic_io, validators

# Stati del ciclo di vita del segnale (vocabolario condiviso; usati appieno in
# PR-16/PR-17). DUPLICATE/RATE_LIMITED sono gli esiti decisi qui.
STATES = (
    "RECEIVED", "PARSED", "VALIDATED", "CSV_WRITTEN", "WAITING_XTRADER",
    "CONFIRMED", "TIMEOUT", "FAILED", "DUPLICATE",
)

NEW = "NEW"
DUPLICATE = "DUPLICATE"
RATE_LIMITED = "RATE_LIMITED"

DEFAULT_DEDUPE_WINDOW = 300     # secondi: finestra entro cui un messaggio è "lo stesso"
DEFAULT_MAX_PER_MINUTE = 20     # segnali nuovi ammessi al minuto

_WS = re.compile(r"\s+")


# Validatori difensivi (audit #105 P2): allineano `SignalTracker` allo stile di
# `safety_guard.DailyLimiter` — un parametro/timestamp malformato non deve rendere
# la deduplica/limite inefficaci o sempre bloccanti. Fonte UNICA condivisa in
# `validators` (era duplicato qui e in safety_guard, #133 item 6, parte "validatori").


def message_hash(text: str) -> str:
    """Hash SHA-256 del messaggio normalizzato (trim + spazi collassati), così
    differenze di sola spaziatura non sfuggono alla deduplica."""
    norm = _WS.sub(" ", str(text or "").strip())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


@dataclass
class RegisterResult:
    """Esito di `SignalTracker.register`."""

    status: str            # NEW | DUPLICATE | RATE_LIMITED
    hash: str

    @property
    def accepted(self) -> bool:
        return self.status == NEW


@dataclass
class SignalTracker:
    """Tiene gli hash recenti per deduplica e limite al minuto. In-memory, ma lo
    stato è serializzabile (`state`/`restore_state`) per sopravvivere al riavvio."""

    dedupe_window: int = DEFAULT_DEDUPE_WINDOW
    max_per_minute: int = DEFAULT_MAX_PER_MINUTE
    _seen: list = field(default_factory=list)   # (hash, epoch_seconds)

    def __post_init__(self):
        # Parametri validati come in DailyLimiter (audit #105 P2): una finestra/limite
        # malformato (bool/NaN/<=0) renderebbe la protezione inefficace o sempre bloccante.
        self.dedupe_window = validators.require_positive_int(self.dedupe_window, "dedupe_window")
        self.max_per_minute = validators.require_positive_int(self.max_per_minute, "max_per_minute")

    def _prune(self, now: float) -> None:
        # Si conserva la storia per il MASSIMO tra finestra dedup e 60s: altrimenti
        # con una finestra dedup < 60s il conteggio al minuto verrebbe falsato
        # (voci rimosse prima di contarle) e il limite sarebbe aggirabile.
        cutoff = now - max(self.dedupe_window, 60)
        self._seen = [(h, t) for (h, t) in self._seen if t >= cutoff]

    def register(self, text: str, *, now: float = None) -> RegisterResult:
        """Registra un messaggio e decide il suo esito (senza scrivere nulla):

        - **DUPLICATE**: stesso hash già visto nella finestra di deduplica;
        - **RATE_LIMITED**: troppi segnali NUOVI nell'ultimo minuto;
        - **NEW**: accettato (e memorizzato).

        Un DUPLICATE o un RATE_LIMITED NON vengono memorizzati come nuovi."""
        now = time.time() if now is None else validators.require_finite_now(now)
        self._prune(now)
        h = message_hash(text)
        # Duplicato: stesso hash entro la finestra di deduplica (NON l'intera
        # storia conservata, che può essere più lunga per il conteggio al minuto).
        dedupe_cutoff = now - self.dedupe_window
        if any(hh == h and t >= dedupe_cutoff for (hh, t) in self._seen):
            return RegisterResult(DUPLICATE, h)
        minute_ago = now - 60
        recent = sum(1 for (_, t) in self._seen if t >= minute_ago)
        if recent >= self.max_per_minute:
            return RegisterResult(RATE_LIMITED, h)
        self._seen.append((h, now))
        return RegisterResult(NEW, h)

    # ── persistenza (riconoscimento duplicati dopo un riavvio) ───────────────

    def state(self) -> list:
        """Stato serializzabile: lista di [hash, timestamp]."""
        return [[h, t] for (h, t) in self._seen]

    def restore_state(self, data) -> None:
        """Ripristina lo stato da `state()` (tollerante a voci malformate)."""
        restored = []
        for item in data or []:
            try:
                h, t = item
                restored.append((str(h), float(t)))
            except (ValueError, TypeError):
                continue
        self._seen = restored


def save_state(tracker: SignalTracker, path: str) -> bool:
    """Salva lo stato del tracker su file JSON **atomicamente** (best-effort) via
    `atomic_io.atomic_write_json`: si scrive un temporaneo e poi `os.replace`. Così
    un'interruzione/errore lascia la history precedente intatta, invece di troncarla
    e perdere la protezione anti-duplicato dopo un riavvio. True se riuscito."""
    try:
        atomic_io.atomic_write_json(path, tracker.state(), prefix=".dedupe_", suffix=".tmp")
        return True
    except OSError:
        return False


def load_state(tracker: SignalTracker, path: str) -> bool:
    """Carica lo stato nel tracker da file JSON (best-effort). True se riuscito;
    file assente/corrotto → lascia il tracker invariato e ritorna False."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, list):
        return False
    tracker.restore_state(data)
    return True
