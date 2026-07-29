"""Politica di riconnessione del listener Telegram (logica pura, testabile in CI).

Il listener gira in un thread (`app._run_bot`). Se la connessione cade, vogliamo
**riprovare** con un ritardo crescente (backoff) finché il bridge è in esecuzione,
SENZA:
- ritentare dopo uno STOP manuale (è una chiusura voluta);
- ritentare all'infinito su un errore **permanente** (es. token invalido), che non
  si risolve da solo e farebbe girare a vuoto.

Qui sta solo la **decisione** (quanto aspettare, se ritentare): nessun widget, nessun
asyncio, nessuna dipendenza da `python-telegram-bot`. Così è interamente testabile.
La parte di I/O (ricostruire l'updater, attendere) vive nella vista sottile `app`.
"""

import math

# Backoff esponenziale, in secondi: 2, 4, 8, 16, 32, … limitato a un tetto.
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0

# Tetto al `retry_after` di Telegram (1 ora). Il flood control reale chiede secondi o
# minuti: questo tetto è ~60× il cap del backoff locale, quindi non tocca nessuna richiesta
# plausibile. Serve contro i valori fuori scala (P3-rs3 #166), che romperebbero il
# supervisor in due modi diversi — vedi `effective_delay`.
MAX_RETRY_AFTER = 3600.0

# Errori considerati **transitori** (rete/timeout): vale la pena riprovare. La
# classificazione preferisce `isinstance` sulle CLASSI REALI di `telegram.error` (vedi
# `is_transient_error`); questi NOMI restano come **fallback** per gli ambienti dove
# `python-telegram-bot` non è importabile (es. CI headless). Tutto ciò che NON è
# transitorio è trattato come NON recuperabile (token invalido, bug, auth…) → niente
# retry: meglio fermarsi e mostrare l'errore che ciclare a vuoto.
TRANSIENT_ERROR_NAMES = frozenset({
    "NetworkError",      # telegram.error.NetworkError (base dei problemi di rete)
    "TimedOut",          # telegram.error.TimedOut
    "RetryAfter",        # flood control: riprovare più tardi
})

# Cache dei tipi transitori REALI di telegram.error, risolti al primo uso.
# None = non ancora risolto; tupla (anche vuota) = risolto. Vuota → telegram non
# importabile, si ricade sul match per nome.
_TRANSIENT_TYPES_CACHE = None


def _real_transient_types():
    """Tupla delle classi transitorie reali di `telegram.error`
    (`NetworkError`/`TimedOut`/`RetryAfter`), risolta e cache-ata al primo uso.

    Tupla **vuota** se `telegram` non è importabile (es. CI/test headless dove la
    dipendenza non è installata): in tal caso `is_transient_error` ricade sul match
    per nome. L'import è lazy proprio per non richiedere `python-telegram-bot` al
    semplice import del modulo (così la logica resta testabile senza la dipendenza)."""
    global _TRANSIENT_TYPES_CACHE
    if _TRANSIENT_TYPES_CACHE is None:
        try:
            from telegram.error import NetworkError, RetryAfter, TimedOut
            _TRANSIENT_TYPES_CACHE = (NetworkError, TimedOut, RetryAfter)
        except Exception:   # noqa: BLE001 — telegram assente/incompleto → fallback per nome
            _TRANSIENT_TYPES_CACHE = ()
    return _TRANSIENT_TYPES_CACHE


def backoff_delay(attempt: int, base: float = DEFAULT_BASE_DELAY,
                  cap: float = DEFAULT_MAX_DELAY) -> float:
    """Ritardo (secondi) prima del tentativo di riconnessione `attempt` (1-based).

    `attempt=1 → base`, poi raddoppia ad ogni tentativo, limitato a `cap`. Valori
    `attempt < 1` sono trattati come 1 (mai un ritardo negativo o nullo)."""
    if attempt < 1:
        attempt = 1
    # Cappa l'ESPONENTE prima di elevare: dopo molte ore di tentativi `attempt`
    # diventa grande e `2 ** (attempt-1)` causerebbe OverflowError (uccidendo il
    # supervisor). Una volta raggiunto il cap il delay vi resta comunque, quindi
    # un esponente limitato (2**30 · base ≫ cap) non cambia il risultato.
    exponent = min(attempt - 1, 30)
    delay = base * (2 ** exponent)
    return float(min(delay, cap))


def effective_delay(attempt: int, retry_after=None,
                    base: float = DEFAULT_BASE_DELAY,
                    cap: float = DEFAULT_MAX_DELAY) -> float:
    """Ritardo effettivo (secondi) prima della riconnessione `attempt`, combinando il
    backoff esponenziale con l'eventuale `retry_after` di Telegram (flood control).

    Se l'eccezione porta un `retry_after` (es. `telegram.error.RetryAfter`) **più
    lungo** del backoff locale, si attende QUELLO: il server ha chiesto esplicitamente
    di non riprovare prima di quel tempo, quindi riconnettersi prima sarebbe inutile e
    peggiorerebbe il flood control. Un `retry_after` assente, non numerico o non
    maggiore del backoff non ha effetto (resta il backoff).

    I `bool` sono rifiutati prima del confronto (come altrove nel progetto): `True`
    non è un `retry_after` valido, solo un intero accidentale da `getattr`.

    **Valori fuori scala (P3-rs3 #166).** `retry_after` arriva da `getattr(exc,
    "retry_after", None)`, cioè da un attributo popolato dalla risposta dell'API: non è un
    numero di cui ci si possa fidare. Il ritardo restituito finisce in `app._reconnect_wait`
    → `threading.Event.wait(delay)`, che si rompe in due modi diversi:

    - **non finito** (`inf`, `nan`) o oltre il `time_t` della piattaforma → `wait` solleva
      **OverflowError**, eccezione non gestita che uccide il thread supervisor: il bridge
      resta «avviato» nella GUI e non riconnette più;
    - **grande ma finito** (es. `1e9` ≈ 31 anni) → nessuna eccezione, `wait` **attende
      davvero**. È il caso peggiore perché è muto: nessun errore, nessun log, il supervisor
      dorme e il bridge sembra vivo.

    Perciò i non finiti sono trattati come il caso già previsto «assente o non numerico»
    (dato corrotto, non una richiesta del server → resta il backoff locale) e i finiti sono
    limitati a `MAX_RETRY_AFTER`. `backoff_delay` cappa già l'esponente per questa identica
    ragione: qui si chiude l'altra strada verso lo stesso guasto."""
    delay = backoff_delay(attempt, base, cap)
    if isinstance(retry_after, bool):
        return delay
    # `isfinite` va chiamata SOLO sui float: converte l'argomento a `float`, e gli `int` di
    # Python sono illimitati, quindi sopra ~1.8e308 quella conversione solleva `OverflowError:
    # int too large to convert to float` — la guardia scritta per impedire un OverflowError ne
    # solleverebbe uno suo, nello stesso punto e con la stessa conseguenza (CodeRabbit #169).
    # Un `int` è finito per definizione: non ha bisogno del controllo.
    if isinstance(retry_after, int):
        finito = True
    elif isinstance(retry_after, float):
        finito = math.isfinite(retry_after)
    else:
        return delay
    # Il confronto e `min` con un int gigante sono esatti e non convertono: `min` restituisce
    # `MAX_RETRY_AFTER` (un float) senza mai passare dal valore fuori scala.
    if finito and retry_after > delay:
        return float(min(retry_after, MAX_RETRY_AFTER))
    return delay


def is_transient_error(exc: BaseException) -> bool:
    """`True` se l'eccezione è un errore transitorio noto (rete/timeout) per cui ha
    senso riconnettersi. Un `TimedOut(NetworkError)` è transitorio mentre
    `InvalidToken`/`ValueError` no.

    Classificazione (audit C6): quando `python-telegram-bot` è importabile si usa
    `isinstance` sulle CLASSI REALI di `telegram.error` — preciso. Il vecchio match per
    **nome di classe** sull'MRO trattava come transitoria QUALSIASI eccezione che
    condividesse solo il nome (es. un `NetworkError` permanente di un'altra libreria o
    una sottoclasse omonima): un falso positivo che mandava il supervisor in un loop di
    reconnect infinito ("running ma sordo"). Con `isinstance` un omonimo NON-telegram non
    è istanza del tipo reale → trattato come NON transitorio.

    Fallback: se `telegram` non è importabile (es. CI/test headless) si ricade sul match
    per nome di prima, così la logica resta testabile senza la dipendenza."""
    types = _real_transient_types()
    if types:
        return isinstance(exc, types)
    # Fallback (telegram non importabile): match per nome lungo l'MRO come in precedenza.
    names = {cls.__name__ for cls in type(exc).__mro__}
    return bool(names & TRANSIENT_ERROR_NAMES)


def should_reconnect(running: bool, exc: BaseException) -> bool:
    """Decisione finale del supervisor: riconnettersi solo se il bridge è ancora in
    esecuzione (uno STOP manuale azzera `running` → nessun retry) **e** l'errore è
    transitorio. Un errore permanente o una chiusura voluta non vanno ritentati."""
    return bool(running) and is_transient_error(exc)
