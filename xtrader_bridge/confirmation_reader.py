"""PR-17: lettura delle notifiche di conferma di XTrader (logica pura, testabile).

XTrader (o l'utente) invia su una chat Telegram **separata** dalle sorgenti dei
segnali (`xtrader_notification_chat_id`) messaggi tipo "scommessa piazzata" o
"errore". Questo modulo **interpreta** quei messaggi per capire se un nostro
segnale in attesa è stato:

- **CONFIRMED**: piazzato con successo;
- **REJECTED**: rifiutato/errore;
- **UNKNOWN**: associato a un nostro segnale ma senza esito chiaro;
- **UNMATCHED**: la notifica non si associa a nessun nostro segnale (es. conferma
  di un'altra cosa) → da ignorare.

Il match avviene prima per **SignalRef** (se XTrader lo riporta, è il più
affidabile), altrimenti per **EventName + MarketName + SelectionName** tutti
presenti nel testo. `timed_out` copre il caso "nessuna conferma entro il timeout".

**Sola lettura**: questo modulo NON scrive il CSV e NON genera scommesse; ritorna
solo uno stato. L'aggancio al runtime (leggere la chat notifiche, confermare il
segnale nella coda) è un passo successivo. Modulo puro, interamente testabile.
"""

import re
from dataclasses import dataclass

CONFIRMED = "CONFIRMED"
REJECTED = "REJECTED"
TIMEOUT = "TIMEOUT"
UNKNOWN = "UNKNOWN"        # match trovato ma esito non riconoscibile
UNMATCHED = "UNMATCHED"    # la notifica non si associa a nessun segnale nostro

DEFAULT_CONFIRM_KEYWORDS = (
    "confermata", "confermato", "piazzata", "piazzato", "eseguita", "eseguito",
    "matched", "placed", "ok",
)
DEFAULT_REJECT_KEYWORDS = (
    "rifiutata", "rifiutato", "errore", "fallita", "fallito", "annullata",
    "annullato", "rejected", "failed", "no match", "unmatched", "error",
)


def _norm(s) -> str:
    return str(s or "").lower()


def _has_keyword(text: str, keyword: str) -> bool:
    """True se `keyword` compare come **parola intera** in `text` (confine `\\b`).
    Evita i falsi positivi del match a sottostringa: es. "ok" NON deve scattare
    dentro "token"/"stock", causando un falso CONFIRMED."""
    kw = _norm(keyword).strip()
    if not kw:
        return False
    return re.search(r"\b" + re.escape(kw) + r"\b", text) is not None


@dataclass
class ConfirmationResult:
    """Esito dell'interpretazione di una notifica XTrader."""

    status: str                 # CONFIRMED | REJECTED | UNKNOWN | UNMATCHED
    signal_id: object = None    # id del segnale associato (None se UNMATCHED)


def classify_outcome(text: str, confirm_keywords=None, reject_keywords=None):
    """Esito dichiarato dal testo: CONFIRMED / REJECTED / None (non riconosciuto).

    I **reject** hanno la precedenza: un messaggio d'errore che contenga per caso
    una parola di conferma non deve risultare confermato (fail-safe)."""
    t = _norm(text)
    rej = reject_keywords or DEFAULT_REJECT_KEYWORDS
    con = confirm_keywords or DEFAULT_CONFIRM_KEYWORDS
    if any(_has_keyword(t, k) for k in rej):
        return REJECTED
    if any(_has_keyword(t, k) for k in con):
        return CONFIRMED
    return None


def match_pending(text: str, pending):
    """Il segnale (dict) a cui la notifica si riferisce, o None se nessuno/ambiguo.

    `pending`: lista di dict con `signal_id`, opzionale `ref` (SignalRef) e i campi
    nome `EventName`/`MarketName`/`SelectionName`. Match per `ref` se presente nel
    testo (più affidabile); altrimenti per tutti i campi nome presenti. Se più di
    un candidato combacia → None (ambiguo: non si associa a caso)."""
    t = _norm(text)
    by_ref = [p for p in pending
              if _norm(p.get("ref")).strip() and _norm(p.get("ref")) in t]
    if len(by_ref) == 1:
        return by_ref[0]
    if len(by_ref) > 1:
        return None

    def all_name_fields_present(p) -> bool:
        fields = [p.get("EventName", ""), p.get("MarketName", ""), p.get("SelectionName", "")]
        fields = [f for f in fields if str(f or "").strip()]
        return bool(fields) and all(_norm(f) in t for f in fields)

    by_fields = [p for p in pending if all_name_fields_present(p)]
    return by_fields[0] if len(by_fields) == 1 else None


def interpret(text: str, pending, *, confirm_keywords=None,
              reject_keywords=None) -> ConfirmationResult:
    """Interpreta una notifica XTrader rispetto ai segnali in attesa.

    Se non si associa a nessun segnale → UNMATCHED (da ignorare, anche se il testo
    sembra una conferma: è di qualcun altro). Se associato ma senza esito chiaro →
    UNKNOWN. Altrimenti CONFIRMED/REJECTED."""
    matched = match_pending(text, pending)
    if matched is None:
        return ConfirmationResult(UNMATCHED, None)
    outcome = classify_outcome(text, confirm_keywords, reject_keywords)
    sid = matched.get("signal_id")
    if outcome is None:
        return ConfirmationResult(UNKNOWN, sid)
    return ConfirmationResult(outcome, sid)


def timed_out(added_at: float, now: float, timeout: float) -> bool:
    """True se è trascorso almeno `timeout` dalla creazione del segnale senza
    conferma: il chiamante può marcarlo TIMEOUT."""
    return (now - added_at) >= timeout
