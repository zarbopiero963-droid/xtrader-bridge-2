"""Test del filtro anti-segnale-stantio (logica pura)."""

from xtrader_bridge import message_freshness as mf


def test_messaggio_recente_non_e_stantio():
    now = 1_000_000.0
    assert mf.is_stale(now - 5, now, max_age=120) is False     # 5s fa: live
    assert mf.is_stale(now, now, max_age=120) is False         # adesso


def test_messaggio_vecchio_oltre_soglia_e_stantio():
    now = 1_000_000.0
    assert mf.is_stale(now - 121, now, max_age=120) is True    # appena oltre
    assert mf.is_stale(now - 600, now, max_age=120) is True    # arretrato di 10 min


def test_soglia_esatta_non_e_stantio():
    now = 1_000_000.0
    assert mf.is_stale(now - 120, now, max_age=120) is False   # == soglia: ammesso


def test_filtro_disattivato_solo_con_soglia_non_positiva():
    # Solo un numero esplicito <= 0 disattiva il filtro (scelta dell'utente).
    now = 1_000_000.0
    assert mf.is_stale(now - 99999, now, max_age=0) is False
    assert mf.is_stale(now - 99999, now, max_age=-5) is False


def test_messaggio_dal_futuro_non_e_stantio():
    now = 1_000_000.0
    assert mf.is_stale(now + 30, now, max_age=120) is False     # clock skew


def test_timestamp_illeggibile_fail_open():
    now = 1_000_000.0
    # Meglio processare un segnale buono che scartarlo per un timestamp illeggibile.
    assert mf.is_stale(None, now, max_age=120) is False
    assert mf.is_stale("boh", now, max_age=120) is False


def test_max_age_malformato_usa_default_sicuro():
    # Audit (P1): un max_signal_age non numerico in config NON deve sollevare
    # TypeError nell'handler Telegram, e NON deve disattivare il filtro: ricade sul
    # default sicuro (120s), così un valore corrotto non lascia passare backlog
    # vecchio dopo un reconnect. Una stringa numerica funziona come il numero.
    now = 1_000_000.0
    # Stringa numerica: si comporta come il numero (utile per config a mano).
    assert mf.is_stale(now - 200, now, max_age="120") is True
    assert mf.is_stale(now - 5, now, max_age="120") is False
    # Malformati → default 120s ATTIVO (fail-safe): un vecchio backlog è stantio,
    # un messaggio recente no. Niente crash.
    for bad in ("abc", True, False, float("nan"), float("inf"), [], {}, object(), None):
        assert mf.is_stale(now - 99999, now, max_age=bad) is True, bad   # default attivo
        assert mf.is_stale(now - 5, now, max_age=bad) is False, bad


def test_timestamp_overflow_non_crasha():
    # Audit (Sourcery): float() su un int enorme solleva OverflowError; la funzione
    # deve restare fail-open su timestamp/now e, su max_age, ricadere sul default
    # sicuro — sempre senza crash.
    huge = 10 ** 400                 # int fuori dal range di un float → OverflowError
    now = 1_000_000.0
    assert mf.is_stale(huge, now, max_age=120) is False          # epoch illeggibile → fail-open
    assert mf.is_stale(now - 200, huge, max_age=120) is False    # now illeggibile → fail-open
    # max_age illeggibile → default 120s attivo: vecchio = stantio, recente = no.
    assert mf.is_stale(now - 200, now, max_age=huge) is True
    assert mf.is_stale(now - 5, now, max_age=huge) is False
