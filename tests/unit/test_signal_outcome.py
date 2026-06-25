"""Test di `xtrader_bridge.signal_outcome` — mappatura esito non-WRITE → presentazione.

Pura, headless: esercita `describe_non_write` con le decisioni reali di `live_guard`,
verificando contatore, testo di log e aggiornamento «ultimo segnale» (solo DRY_RUN).
"""

from xtrader_bridge import confirmation_reader, live_guard, signal_outcome

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


# ── describe_write: presentazione della scrittura CSV riuscita ────────────────

def test_describe_write_contiene_evento_selezione_prezzo_e_sorgente():
    o = signal_outcome.describe_write(ROW, "P.Bet", 1)
    assert "Milan v Inter" in o.last_signal and "Milan" in o.last_signal
    assert "1,85" in o.last_signal
    assert "P.Bet" in o.signal_log and "Milan v Inter" in o.signal_log
    assert "1,85" in o.signal_log


def test_describe_write_pluralizza_una_riga_attiva():
    o = signal_outcome.describe_write(ROW, "P.Bet", 1)
    # singolare: "1 attivo"
    assert "1 attivo)" in o.csv_log
    assert "attivi" not in o.csv_log
    assert "XTrader" in o.csv_log


def test_describe_write_pluralizza_piu_righe_attive():
    o = signal_outcome.describe_write(ROW, "Custom", 3)
    # plurale: "3 attivi"
    assert "3 attivi)" in o.csv_log


def test_describe_write_campi_mancanti_non_sollevano():
    o = signal_outcome.describe_write({}, "P.Bet", 0)
    # n_active=0 → plurale "attivi"; nessun KeyError sui campi vuoti
    assert "0 attivi)" in o.csv_log
    assert "q." in o.last_signal


def test_attivi_label_singolare_e_plurale():
    # Fonte unica della pluralizzazione: solo n==1 è singolare.
    assert signal_outcome._attivi_label(1) == "attivo"
    assert signal_outcome._attivi_label(0) == "attivi"
    assert signal_outcome._attivi_label(2) == "attivi"


# ── conferma XTrader: log esito terminale e log ignorato ──────────────────────

def test_confirmation_removed_log_terminali():
    conf = signal_outcome.confirmation_removed_log(confirmation_reader.CONFIRMED)
    rej = signal_outcome.confirmation_removed_log(confirmation_reader.REJECTED)
    assert "confermato" in conf and "rimosso dal CSV" in conf
    assert "rifiutato" in rej and "rimosso dal CSV" in rej
    assert conf != rej


def test_confirmation_removed_log_non_terminali_none():
    # UNKNOWN/UNMATCHED non sono esiti terminali → nessun log di rimozione.
    assert signal_outcome.confirmation_removed_log(confirmation_reader.UNKNOWN) is None
    assert signal_outcome.confirmation_removed_log(confirmation_reader.UNMATCHED) is None
    assert signal_outcome.confirmation_removed_log("BOH") is None


def test_confirmation_ignored_log_unknown_e_unmatched():
    unk = signal_outcome.confirmation_ignored_log(confirmation_reader.UNKNOWN)
    unm = signal_outcome.confirmation_ignored_log(confirmation_reader.UNMATCHED)
    assert "esito non chiaro" in unk
    assert "non associata ad alcun segnale" in unm
    assert unk != unm


def test_confirmation_ignored_log_terminali_none():
    # CONFIRMED/REJECTED rimuovono → non passano da qui (nessun log "ignorata").
    assert signal_outcome.confirmation_ignored_log(confirmation_reader.CONFIRMED) is None
    assert signal_outcome.confirmation_ignored_log(confirmation_reader.REJECTED) is None
    assert signal_outcome.confirmation_ignored_log(None) is None
