"""PR-21: aggancio dei guardrail al flusso live (decisione pura, testabile).

`app._process` produce una riga piazzabile (via `signal_router`) e poi deve
decidere **se scriverla davvero** nel CSV operativo. Questa decisione qui è pura:
combina i guardrail già esistenti (PR-15/PR-19) in un unico esito, così la GUI
resta sottile e la logica è testabile headless.

Ordine (fail-safe, anti-doppia-scommessa):
1. **dedup + limite/minuto** (`SignalTracker.register`): un duplicato o una raffica
   non devono scrivere;
2. **DRY_RUN** (`safety_guard.is_dry_run`): in simulazione non si scrive il CSV
   operativo — e, valutato PRIMA del tetto giornaliero, la simulazione non consuma
   alcuna slot giornaliera (P3-rs1 audit #114: niente più consumo-e-restituzione
   delegata al chiamante, che era fragile — un caller distratto avrebbe bruciato il
   tetto reale in simulazione);
3. **limite/giorno** (`DailyLimiter.allow`): tetto giornaliero — consumato SOLO su un
   percorso che scriverà davvero (modalità reale).

Esiti:
- `WRITE`     → scrivi la riga;
- `DRY_RUN`   → riconosci il segnale ma NON scrivere (simulazione);
- `DUPLICATE` → stesso messaggio già visto nella finestra;
- `RATE_LIMITED` → troppi segnali nell'ultimo minuto;
- `DAILY_LIMITED` → raggiunto il tetto giornaliero.

Solo `WRITE` autorizza la scrittura: ogni altro esito la sopprime.
"""

from . import safety_guard, signal_dedupe

WRITE = "WRITE"
DRY_RUN = "DRY_RUN"
DUPLICATE = "DUPLICATE"
RATE_LIMITED = "RATE_LIMITED"
DAILY_LIMITED = "DAILY_LIMITED"


def evaluate(cfg, tracker, daily, text, *, now=None, dedup_key=None) -> str:
    """Decide l'esito del percorso di scrittura per `text` (vedi modulo).

    `tracker`: `signal_dedupe.SignalTracker` (dedup + limite/minuto); obbligatorio.
    `daily`: `safety_guard.DailyLimiter` o None (None = nessun limite giornaliero).
    `dedup_key` (#192): chiave di deduplica PER-RIGA per il multi-output (vedi
    `signal_dedupe.row_dedup_key`); assente → dedup sull'hash del messaggio (single-row).
    Effetti: un segnale accettato (`WRITE`) consuma una slot nel tracker e (se presente)
    nel `daily`; DUPLICATE/RATE_LIMITED/DRY_RUN NON consumano la slot giornaliera. In
    particolare DRY_RUN è valutato PRIMA di `daily.allow()` (P3-rs1 audit #114): la
    simulazione non tocca il tetto giornaliero reale, quindi il chiamante non deve più
    «restituire» slot con `daily.release()`. Il tracker, invece, registra comunque l'hash
    (dedup coerente anche in simulazione): il chiamante lo ripristina se l'esito non scrive."""
    reg = tracker.register(text, now=now, key=dedup_key)
    if reg.status == signal_dedupe.DUPLICATE:
        return DUPLICATE
    if reg.status == signal_dedupe.RATE_LIMITED:
        return RATE_LIMITED
    # DRY_RUN PRIMA del tetto (P3-rs1 #114): in simulazione non si consuma alcuna slot
    # giornaliera — solo un percorso che scriverà davvero (reale) intacca `daily`.
    if safety_guard.is_dry_run(cfg):
        return DRY_RUN
    if daily is not None and not daily.allow(now=now):
        return DAILY_LIMITED
    return WRITE
