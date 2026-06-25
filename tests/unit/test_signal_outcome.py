"""Test di `xtrader_bridge.signal_outcome` — mappatura esito non-WRITE → presentazione.

Pura, headless: esercita `describe_non_write` con le decisioni reali di `live_guard`,
verificando contatore, testo di log e aggiornamento «ultimo segnale» (solo DRY_RUN).
"""

from xtrader_bridge import live_guard, signal_outcome

ROW = {"EventName": "Milan v Inter", "SelectionName": "Milan", "Price": "1,85"}


def test_dry_run_aggiorna_ultimo_segnale_e_contatore():
    o = signal_outcome.describe_non_write(live_guard.DRY_RUN, ROW)
    assert o is not None
    assert o.counter == "dry_run"
    assert "DRY_RUN" in o.log and "Milan v Inter" in o.log and "Milan" in o.log
    # solo DRY_RUN aggiorna «ultimo segnale», con colore arancio
    assert o.last_signal is not None
    assert "Milan" in o.last_signal and "1,85" in o.last_signal
    assert o.last_color == "#ffb74d"


def test_duplicate_non_aggiorna_ultimo_segnale():
    o = signal_outcome.describe_non_write(live_guard.DUPLICATE, ROW)
    assert o.counter == "duplicate"
    assert "Duplicato" in o.log
    assert o.last_signal is None        # nessun aggiornamento «ultimo segnale»


def test_rate_e_daily_limited_usano_contatore_limited():
    rate = signal_outcome.describe_non_write(live_guard.RATE_LIMITED, ROW)
    daily = signal_outcome.describe_non_write(live_guard.DAILY_LIMITED, ROW)
    assert rate.counter == "limited" and daily.counter == "limited"
    # messaggi DISTINTI (minuto vs giorno), così l'utente capisce quale limite è scattato
    assert "minuto" in rate.log and "giornaliero" in daily.log
    assert rate.log != daily.log
    assert rate.last_signal is None and daily.last_signal is None


def test_write_e_decisioni_ignote_ritornano_none():
    # WRITE non passa da qui (ha il percorso di scrittura), idem un valore sconosciuto:
    # il chiamante non fa nulla.
    assert signal_outcome.describe_non_write(live_guard.WRITE, ROW) is None
    assert signal_outcome.describe_non_write("BOH", ROW) is None
    assert signal_outcome.describe_non_write(None, ROW) is None


def test_campi_mancanti_nella_row_non_sollevano():
    # row senza i campi attesi → stringhe vuote, nessun KeyError.
    o = signal_outcome.describe_non_write(live_guard.DRY_RUN, {})
    assert o is not None
    assert "DRY_RUN" in o.log
    assert "q." in o.last_signal       # prezzo vuoto, ma il formato regge
