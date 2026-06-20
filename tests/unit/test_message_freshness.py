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


def test_filtro_disattivato_con_soglia_non_positiva_o_none():
    now = 1_000_000.0
    assert mf.is_stale(now - 99999, now, max_age=0) is False
    assert mf.is_stale(now - 99999, now, max_age=None) is False


def test_messaggio_dal_futuro_non_e_stantio():
    now = 1_000_000.0
    assert mf.is_stale(now + 30, now, max_age=120) is False     # clock skew


def test_timestamp_illeggibile_fail_open():
    now = 1_000_000.0
    # Meglio processare un segnale buono che scartarlo per un timestamp illeggibile.
    assert mf.is_stale(None, now, max_age=120) is False
    assert mf.is_stale("boh", now, max_age=120) is False


def test_max_age_malformato_non_crasha():
    # Audit (P1): un max_signal_age non numerico in config NON deve sollevare
    # TypeError nell'handler Telegram. Una stringa numerica funziona; il resto
    # disattiva il filtro (fail-safe), senza eccezioni.
    now = 1_000_000.0
    # Stringa numerica: si comporta come il numero (utile per config a mano).
    assert mf.is_stale(now - 200, now, max_age="120") is True
    assert mf.is_stale(now - 5, now, max_age="120") is False
    # Non numerico / bool / non finiti → filtro disattivato, niente crash.
    for bad in ("abc", True, False, float("nan"), float("inf"), [], {}, object()):
        assert mf.is_stale(now - 99999, now, max_age=bad) is False, bad
