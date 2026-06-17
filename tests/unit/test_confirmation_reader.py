"""Test del lettore di conferme XTrader (PR-17/#... PHASE 7): logica pura."""

from xtrader_bridge import confirmation_reader as cr


def _pending():
    return [
        {"signal_id": "s1", "ref": "ABC123",
         "EventName": "Inter v Milan", "MarketName": "Over/Under 2,5 gol",
         "SelectionName": "Over 2,5 goal"},
        {"signal_id": "s2", "ref": "",
         "EventName": "Roma v Lazio", "MarketName": "Both Teams To Score",
         "SelectionName": "Sì"},
    ]


# ── classify_outcome ─────────────────────────────────────────────────────────

def test_classify_confermato_e_rifiutato():
    assert cr.classify_outcome("Scommessa piazzata con successo") == cr.CONFIRMED
    assert cr.classify_outcome("Errore: scommessa rifiutata") == cr.REJECTED
    assert cr.classify_outcome("messaggio neutro") is None


def test_reject_ha_precedenza_su_confirm():
    # "non piazzata: errore" contiene sia "piazzata" sia "errore" → REJECTED (fail-safe).
    assert cr.classify_outcome("Scommessa NON piazzata: errore") == cr.REJECTED


def test_keyword_personalizzate():
    assert cr.classify_outcome("BET DONE", confirm_keywords=["bet done"]) == cr.CONFIRMED


def test_keyword_match_parola_intera_no_falsi_positivi():
    # "ok" non deve scattare dentro parole più lunghe (token/stock/Oklahoma):
    # eviterebbe un falso CONFIRMED su un messaggio neutro.
    assert cr.classify_outcome("nuovo token generato") is None
    assert cr.classify_outcome("stock aggiornato") is None
    # ma "ok" come parola intera è una conferma
    assert cr.classify_outcome("ok, fatto") == cr.CONFIRMED


# ── match per SignalRef ──────────────────────────────────────────────────────

def test_conferma_con_signalref():
    res = cr.interpret("Scommessa ABC123 confermata", _pending())
    assert res.status == cr.CONFIRMED
    assert res.signal_id == "s1"


def test_messaggio_errore_rejected():
    res = cr.interpret("Ref ABC123: errore di piazzamento", _pending())
    assert res.status == cr.REJECTED
    assert res.signal_id == "s1"


# ── fallback per Event+Market+Selection (senza SignalRef) ────────────────────

def test_fallback_senza_signalref():
    text = "Piazzata: Roma v Lazio - Both Teams To Score - Sì"
    res = cr.interpret(text, _pending())
    assert res.status == cr.CONFIRMED
    assert res.signal_id == "s2"


def test_match_ma_esito_sconosciuto_e_unknown():
    res = cr.interpret("Roma v Lazio Both Teams To Score Sì", _pending())
    assert res.status == cr.UNKNOWN          # so quale segnale, ma non l'esito
    assert res.signal_id == "s2"


# ── non associare a segnali altrui ───────────────────────────────────────────

def test_conferma_di_altro_segnale_non_associata():
    res = cr.interpret("Scommessa XYZ999 confermata", _pending())
    assert res.status == cr.UNMATCHED
    assert res.signal_id is None


def test_fallback_parziale_non_associa():
    # Solo l'evento combacia (manca mercato/selezione): non si associa a caso.
    res = cr.interpret("Inter v Milan confermata", _pending())
    assert res.status == cr.UNMATCHED


def test_ref_ambiguo_non_associa():
    pending = [
        {"signal_id": "a", "ref": "REF"},
        {"signal_id": "b", "ref": "REF"},
    ]
    assert cr.match_pending("esito REF", pending) is None


# ── timeout ──────────────────────────────────────────────────────────────────

def test_timed_out():
    assert cr.timed_out(added_at=1000, now=1000 + 120, timeout=120) is True
    assert cr.timed_out(added_at=1000, now=1000 + 119, timeout=120) is False
