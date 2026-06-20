"""Scarto dei messaggi Telegram troppo vecchi (anti-segnale-stantio).

`python-telegram-bot` gestisce internamente le cadute di rete durante il polling e,
quando la connessione torna, **recupera** i messaggi accumulati offline. Per il
trading live un segnale vecchio di minuti è inutile/pericoloso (verrebbe scritto nel
CSV e ripiazzato). Questo modulo decide — in modo **puro e testabile** — se un
messaggio è troppo vecchio rispetto a "adesso", in base al suo timestamp (`msg.date`).
"""

import math

DEFAULT_MAX_AGE = 120  # secondi


def is_stale(message_epoch, now, max_age=DEFAULT_MAX_AGE) -> bool:
    """`True` se il messaggio (epoch UNIX `message_epoch`) è più vecchio di `max_age`
    secondi rispetto a `now` (epoch UNIX).

    - `max_age` **coerciuto a float** in modo sicuro: un valore malformato in config
      (es. ``"120"`` editato a mano funziona, ma `"abc"`/`bool`/`NaN`/`inf`/`None`/
      ``<= 0`` → filtro **disattivato**). Niente eccezioni: un `max_signal_age`
      rotto NON deve far crashare l'handler Telegram, al più disabilita il filtro;
    - timestamp/now non interpretabili → **non** stantio (fail-open: meglio processare
      un segnale buono che scartarlo per un timestamp illeggibile);
    - un messaggio dal **futuro** (clock skew) non è stantio.
    """
    if isinstance(max_age, bool):
        return False                 # un bool non è una soglia in secondi → filtro off
    try:
        max_age = float(max_age)
    except (TypeError, ValueError):
        return False                 # None/"abc"/oggetti → filtro off (no crash)
    if not math.isfinite(max_age) or max_age <= 0:
        return False                 # NaN/inf/<=0 → filtro off
    try:
        age = float(now) - float(message_epoch)
    except (TypeError, ValueError):
        return False
    return age > max_age
