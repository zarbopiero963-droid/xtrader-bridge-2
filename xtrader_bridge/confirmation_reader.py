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

import math
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
    # Frasi NEGATE: contengono una keyword di conferma ma indicano il contrario.
    # Stanno tra i reject (valutati per primi) per non risultare un falso CONFIRMED.
    "non piazzata", "non piazzato", "non confermata", "non confermato",
    "non eseguita", "non eseguito", "not matched", "not placed", "not confirmed",
)


def normalize_keywords(value):
    """Normalizza le keyword di conferma/rifiuto (dalla config) a **lista** o None.

    Una **stringa** singola (es. un `config.json` scritto a mano con `"piazzata"`
    invece di `["piazzata"]`) NON va passata così a `classify_outcome`: essendo
    iterabile verrebbe scandita **carattere per carattere** e una notifica con una
    lettera comune (es. "a") risulterebbe CONFIRMED/REJECTED per sbaglio. Quindi una
    stringa è avvolta come **singola** keyword. Lista/tupla → stringhe non vuote.
    Vuoto/None/tipo inatteso → None (usa i default del modulo)."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else None
    if isinstance(value, (list, tuple)):
        kws = [str(x).strip() for x in value if str(x).strip()]
        return kws or None
    return None


def _norm(s) -> str:
    return str(s or "").lower()


_NEGATION_WORDS = ("non", "not", "nessun", "nessuna", "mai")


def _has_keyword(text: str, keyword: str) -> bool:
    """True se `keyword` compare delimitata in `text`. Su un bordo **alfanumerico**
    si richiede un confine di parola (es. "ok" non scatta dentro "token"); su un
    bordo **non alfanumerico** (es. una keyword-simbolo come "✅") il confine `\\b`
    non esiste, quindi lì si fa match diretto — così le keyword simbolo funzionano."""
    kw = _norm(keyword).strip()
    if not kw:
        return False
    left = r"(?<!\w)" if (kw[0].isalnum() or kw[0] == "_") else ""
    right = r"(?!\w)" if (kw[-1].isalnum() or kw[-1] == "_") else ""
    return re.search(left + re.escape(kw) + right, text) is not None


def _has_negation(text: str) -> bool:
    """True se nel testo compare una parola di negazione (non/not/nessun/mai)."""
    return any(_has_keyword(text, w) for w in _NEGATION_WORDS)


# Ref ETICHETTATO nel testo: "Ref ABC123", "Rif: 123", "ID-9", "#ABC". Serve a
# capire se la notifica è esplicitamente per un certo ref. Copre le forme comuni;
# il formato esatto di XTrader si fisserà al wiring reale.
_REF_LABEL_RE = re.compile(
    r"(?:\b(?:ref|rif|reference|id)\b[^\w-]*|#)([0-9a-z][\w-]*)", re.IGNORECASE)


def _message_ref_tokens(text: str) -> list:
    """Token di ref etichettati trovati nel testo (minuscoli). Vuoto se nessuno."""
    return [m.group(1).lower() for m in _REF_LABEL_RE.finditer(text)]


def _has_ref_token(text: str, ref: str) -> bool:
    """True se `ref` compare come **token intero** in `text`, delimitato da inizio/
    fine o da un carattere che NON prosegue il token (`[\\w-]`). Più stretto di
    `\\b`: un ref `"ABC123"` non combacia dentro `"ABC123-4"` (ref diverso con
    suffisso), evitando di associare il segnale sbagliato."""
    r = _norm(ref).strip()
    if not r:
        return False
    # Continuazione del token: oltre a word/`-`, anche `/` e `.` (suffissi comuni
    # nei ref), così "ABC123" non combacia dentro "ABC123-4"/"ABC123/4"/"ABC123.4".
    return re.search(r"(?<![\w/.-])" + re.escape(r) + r"(?![\w/.-])", text) is not None


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
        # Guardia negazione: una keyword di conferma con una negazione nel testo
        # (es. "non è stata piazzata", "not successfully placed") NON è una
        # conferma. Fail-safe: nel dubbio si rifiuta, mai un falso CONFIRMED su una
        # scommessa non piazzata.
        return REJECTED if _has_negation(t) else CONFIRMED
    return None


def match_pending(text: str, pending):
    """Il segnale (dict) a cui la notifica si riferisce, o None se nessuno/ambiguo.

    `pending`: lista di dict con `signal_id`, opzionale `ref` (SignalRef) e i campi
    nome `EventName`/`MarketName`/`SelectionName`. Match per `ref` se presente nel
    testo (più affidabile); altrimenti per tutti i campi nome presenti. Se più di
    un candidato combacia → None (ambiguo: non si associa a caso)."""
    t = _norm(text)
    # Match per ref come TOKEN intero: un ref "123" non combacia dentro "ABC1234"
    # né "ABC123" dentro "ABC123-4" (ref diverso): non si associa il segnale sbagliato.
    by_ref = [p for p in pending
              if _norm(p.get("ref")).strip() and _has_ref_token(t, p.get("ref"))]
    if len(by_ref) == 1:
        return by_ref[0]
    if len(by_ref) > 1:
        return None

    def _remove_first(text: str, phrase: str) -> str:
        """Rimuove la prima occorrenza (parola intera) di `phrase` da `text`."""
        return re.sub(r"\b" + re.escape(phrase) + r"\b", " ", text, count=1)

    def all_name_fields_present(p) -> bool:
        # Fallback: servono TUTTI E TRE i campi identità, non vuoti e presenti nel
        # testo come PAROLE INTERE e su porzioni DISTINTE: si consuma il testo via
        # via, così una selezione contenuta nell'evento (es. "Inter" dentro
        # "Inter v Milan") non viene contata due volte. Un sottoinsieme NON basta:
        # meglio nessun match che il segnale sbagliato.
        ev = _norm(p.get("EventName")).strip()
        mk = _norm(p.get("MarketName")).strip()
        sel = _norm(p.get("SelectionName")).strip()
        if not (ev and mk and sel):
            return False
        if not _has_keyword(t, ev):
            return False
        rest = _remove_first(t, ev)
        if not _has_keyword(rest, mk):
            return False
        rest = _remove_first(rest, mk)
        return _has_keyword(rest, sel)

    # Se la notifica porta un ref ETICHETTATO ("Ref/Rif/ID/#") che NON è di
    # nessun nostro segnale, è esplicitamente per un'altra scommessa: niente
    # fallback per nomi (eviterebbe di confermare un nostro segnale senza ref con i
    # nomi coincidenti — es. scommesse ripetute sullo stesso mercato). Fail-safe:
    # nel dubbio non si associa.
    pending_refs = {_norm(p.get("ref")).strip() for p in pending if _norm(p.get("ref")).strip()}
    msg_refs = _message_ref_tokens(t)
    if msg_refs and not any(r in pending_refs for r in msg_refs):
        return None

    # Il fallback per nomi vale SOLO per i segnali SENZA ref: se un segnale ha un
    # SignalRef, va confermato solo via quel ref.
    by_fields = [p for p in pending
                 if not _norm(p.get("ref")).strip() and all_name_fields_present(p)]
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


def _require_finite(value, name: str) -> float:
    """`value` come float finito, altrimenti ValueError. Un `NaN`/`inf` (accettato
    da `json.load` su stato persistito) romperebbe i confronti temporali."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} non valido: {value!r}")
    if not math.isfinite(f):
        raise ValueError(f"{name} deve essere un numero finito (ricevuto {value!r})")
    return f


def timed_out(added_at: float, now: float, timeout: float) -> bool:
    """True se è trascorso almeno `timeout` dalla creazione del segnale senza
    conferma: il chiamante può marcarlo TIMEOUT.

    Tutti i valori devono essere finiti e `timeout > 0`: un `NaN` (anche in
    `added_at`/`now`, da stato persistito via `json.load`) renderebbe il confronto
    sempre falso → segnale mai in TIMEOUT; `now=inf` scadrebbe sempre; `timeout<=0`
    scadrebbe subito. Fail-fast con ValueError (come la coda dei segnali)."""
    a = _require_finite(added_at, "added_at")
    n = _require_finite(now, "now")
    t = _require_finite(timeout, "timeout")
    if t <= 0:
        raise ValueError(f"timeout deve essere > 0 (ricevuto {timeout!r})")
    return (n - a) >= t
