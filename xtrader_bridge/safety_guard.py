"""PR-19: guardrail di sicurezza (logica pura, testabile headless).

Riduce il rischio di uso pericoloso del bridge senza trasformarlo in un bot di
puntata aggressivo. Tre responsabilità, tutte **pure** (nessuna GUI/CSV/Telegram):

- **DRY_RUN (simulazione)**: `is_dry_run(cfg)` / `should_write_operational_csv(cfg)`
  decidono se il CSV operativo va scritto. Default **sicuro**: se il campo manca
  (config vecchia o prima installazione) il bridge è in simulazione (`True`), così
  non si genera una scommessa reale per sbaglio dopo un aggiornamento.
- **Warning modalità reale**: `real_mode_warning(cfg)` ritorna un avviso quando la
  simulazione è disattivata, che la GUI mostra come banner (qui solo il testo).
- **Limite giornaliero**: `DailyLimiter` applica un tetto di segnali **al giorno**
  (UTC) con **reset automatico** al cambio di data. Complementare al limite/minuto
  già in `signal_dedupe` (PR-15). Fail-safe: parametri non validi → ValueError.

**Sola decisione**: questo modulo non scrive il CSV e non piazza scommesse; il
wiring GUI/runtime (toggle, banner, blocco START) è un passo successivo.
"""

import json
import re
import time
from dataclasses import dataclass

from . import atomic_io, validators

DEFAULT_MAX_PER_DAY = 200      # tetto di segnali nuovi accettati in un giorno (UTC)

# Forma canonica della chiave giorno prodotta da `_day_key` (UTC). Serve a distinguere un
# giorno VALIDO diverso da oggi (→ nuovo giorno, reset legittimo) da un `day` MALFORMATO
# arrivato da uno stato corrotto (→ NON azzerare: vedi `DailyLimiter._roll`, issue #184 M4).
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Valori stringa interpretati come "spento" = modalità REALE (per config che
# arrivano da campi testuali GUI o da un vecchio config.json scritto a mano).
# NB: solo valori OFF **espliciti**. Vuoto / `None` / `"none"` NON sono qui: un
# valore non impostato o malformato deve fallire **chiuso** in simulazione, mai
# abilitare la scrittura del CSV reale (fail-safe).
_FALSEY = {"0", "false", "no", "off", "n"}


def is_dry_run(cfg) -> bool:
    """True se il bridge è in **simulazione** (non deve scrivere il CSV operativo).

    Default **sicuro**: campo assente → `True`. Un valore esplicito viene
    interpretato in modo robusto: bool diretto, oppure stringa
    (``"false"/"0"/"no"/"off"`` → False; tutto il resto non vuoto → True)."""
    if not isinstance(cfg, dict) or "dry_run" not in cfg:
        return True
    val = cfg.get("dry_run")
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val != 0
    return str(val).strip().lower() not in _FALSEY


def should_write_operational_csv(cfg) -> bool:
    """True se è consentito scrivere il CSV operativo (cioè NON in simulazione)."""
    return not is_dry_run(cfg)


def real_mode_warning(cfg) -> str:
    """Testo di avviso quando la simulazione è **disattivata** (modalità reale), da
    mostrare nella GUI. Stringa vuota se in simulazione (nessun avviso)."""
    if is_dry_run(cfg):
        return ""
    return ("ATTENZIONE: modalità REALE attiva — i segnali vengono scritti nel CSV "
            "operativo e XTrader può piazzare scommesse reali. Usa la simulazione "
            "(DRY_RUN) per i test.")


def _day_key(now: float) -> str:
    """Chiave del giorno (UTC) ``YYYY-MM-DD`` per `now` (epoch). UTC per evitare
    salti di fuso/ora legale che falserebbero il reset giornaliero."""
    t = time.gmtime(now)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"


@dataclass
class DailyLimiter:
    """Tetto di segnali **al giorno** (UTC) con reset automatico al cambio data.

    `allow(now)` ritorna True se c'è ancora capienza nel giorno corrente (e in tal
    caso conta il segnale), False se il tetto è raggiunto. Lo stato è serializzabile
    (`state`/`restore_state`) così il conteggio sopravvive a un riavvio nello stesso
    giorno (non si azzera ripartendo l'app)."""

    max_per_day: int = DEFAULT_MAX_PER_DAY
    _day: str = ""
    _count: int = 0

    def __post_init__(self):
        self.max_per_day = validators.require_positive_int(self.max_per_day, "max_per_day")

    def _roll(self, now: float) -> None:
        key = _day_key(now)
        if key == self._day:
            return
        # Giorno diverso da oggi. Se `_day` è una data VALIDA (YYYY-MM-DD) → è un nuovo giorno:
        # reset del conteggio (comportamento normale). Se invece è MALFORMATO/vuoto — stato
        # corrotto o manomesso (M4 #184) — NON si azzera: non si sa a quale giorno appartenga il
        # conteggio e fidarsi darebbe un cap PIENO oggi (overtrading, fail-OPEN). Si adotta il
        # giorno corrente CONSERVANDO il conteggio (fail-CLOSED): al più si è più restrittivi
        # oggi, mai più permissivi; al prossimo giorno reale (con `_day` valido) si azzererà.
        if _DAY_RE.match(self._day or ""):
            self._count = 0
        self._day = key

    def allow(self, *, now: float = None) -> bool:
        """True se il segnale è ammesso oggi (e lo conta); False se tetto raggiunto."""
        now = time.time() if now is None else now
        now = validators.require_finite_now(now)
        self._roll(now)
        if self._count >= self.max_per_day:
            return False
        self._count += 1
        return True

    def remaining(self, *, now: float = None) -> int:
        """Segnali ancora ammessi nel giorno corrente (senza consumarne)."""
        now = time.time() if now is None else now
        now = validators.require_finite_now(now)
        self._roll(now)
        return max(0, self.max_per_day - self._count)

    def state(self) -> dict:
        """Stato serializzabile (per sopravvivere a un riavvio nello stesso giorno)."""
        return {"day": self._day, "count": self._count}

    def restore_state(self, data) -> bool:
        """Ripristina lo stato da `state()` (tollerante a dati malformati). Ritorna ``True``
        se lo stato è stato effettivamente applicato, ``False`` se i dati erano malformati
        (limiter lasciato invariato) — così `load_state` distingue un restore reale da un no-op."""
        if not isinstance(data, dict):
            return False
        day = data.get("day")
        count = data.get("count")
        if isinstance(count, int) and count >= 0:
            # `day` valido `YYYY-MM-DD` → usato così com'è; malformato/non-stringa → "" (UNKNOWN,
            # M4 #184). Il conteggio NON viene scartato (sarebbe un cap pieno = overtrading): è
            # attribuito al giorno corrente da `_roll` (fail-closed). `day == ""` è la forma
            # canonica "sconosciuto" già usata dal limiter fresco.
            self._day = day if isinstance(day, str) and _DAY_RE.match(day) else ""
            self._count = count
            return True
        return False


def save_state(daily: DailyLimiter, path: str) -> bool:
    """Salva lo stato del DailyLimiter su file JSON **atomicamente** (audit #105 P2): via
    `atomic_io.atomic_write_json` (`.tmp` nella stessa cartella + ``flush`` + ``os.fsync`` +
    ``os.replace``, con rimozione del temporaneo su errore) — esattamente come
    `signal_dedupe.save_state`. Prima il salvataggio era best-effort SENZA fsync: in
    crash/blackout l'ultimo conteggio giornaliero poteva perdersi, riducendo la protezione
    anti-overtrading dopo un riavvio. True se riuscito, False su errore di I/O."""
    try:
        atomic_io.atomic_write_json(path, daily.state(), prefix=".guard_", suffix=".tmp")
        return True
    except OSError:
        return False


def load_state(daily: DailyLimiter, path: str) -> bool:
    """Carica lo stato nel DailyLimiter da file JSON (best-effort). True se riuscito;
    file assente/corrotto/malformato → lascia il limiter invariato e ritorna False."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    # Propaga l'esito reale del restore: un JSON valido ma con struttura inattesa
    # (ignorato da restore_state) ritorna False, non un falso "caricato" (Sourcery).
    return daily.restore_state(data)
