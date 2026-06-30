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


# ── normalize_keywords ───────────────────────────────────────────────────────

def test_normalize_keywords():
    # Stringa singola → UNA keyword (non scandita char-by-char: eviterebbe falsi esiti).
    assert cr.normalize_keywords("piazzata") == ["piazzata"]
    # con la stringa avvolta, una "a" da sola NON è una conferma
    assert cr.classify_outcome("esito a", confirm_keywords=cr.normalize_keywords("piazzata")) is None
    # lista pulita; vuoti scartati; None/vuoto/tipo inatteso → None
    assert cr.normalize_keywords(["ok", " done ", ""]) == ["ok", "done"]
    assert cr.normalize_keywords(None) is None
    assert cr.normalize_keywords("") is None
    assert cr.normalize_keywords([]) is None
    assert cr.normalize_keywords(123) is None


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


def test_negazione_separata_non_e_conferma():
    # Negazione non adiacente alla keyword positiva → NON è conferma (fail-safe).
    assert cr.classify_outcome("scommessa non è stata piazzata") == cr.REJECTED
    assert cr.classify_outcome("bet not successfully placed") == cr.REJECTED
    # senza negazione resta conferma
    assert cr.classify_outcome("scommessa piazzata con successo") == cr.CONFIRMED


def test_keyword_simbolo():
    # Keyword-simbolo (✅/❌) devono funzionare nonostante \b non si applichi.
    assert cr.classify_outcome("esito: ✅", confirm_keywords=["✅"]) == cr.CONFIRMED
    assert cr.classify_outcome("esito: ❌", reject_keywords=["❌"]) == cr.REJECTED


def test_ref_con_slash_o_punto_non_combacia():
    pending = [{"signal_id": "x", "ref": "ABC123"}]
    assert cr.match_pending("Ref ABC123/4 piazzata", pending) is None
    assert cr.match_pending("Ref ABC123.4 piazzata", pending) is None
    assert cr.match_pending("Ref ABC123 piazzata", pending) is not None


def test_timed_out_timestamp_non_finiti_rifiutati():
    import pytest
    with pytest.raises(ValueError):
        cr.timed_out(added_at=float("nan"), now=2000, timeout=120)
    with pytest.raises(ValueError):
        cr.timed_out(added_at=1000, now=float("inf"), timeout=120)


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


def test_ref_match_parola_intera():
    # Un ref "123" non deve combaciare dentro "ABC1234" (segnale sbagliato).
    pending = [{"signal_id": "x", "ref": "123"}]
    assert cr.match_pending("Ref ABC1234 piazzata", pending) is None
    assert cr.match_pending("Ref 123 piazzata", pending) is not None


def test_frase_negata_non_e_conferma():
    # "non piazzata"/"not matched" contengono una keyword di conferma ma vanno
    # interpretati come RIFIUTO (no falso CONFIRMED su scommessa non piazzata).
    res = cr.interpret("Ref ABC123: scommessa non piazzata", _pending())
    assert res.status == cr.REJECTED
    assert cr.classify_outcome("not matched") == cr.REJECTED


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


def test_fallback_richiede_tutti_e_tre_i_campi():
    # Un pending con MarketName vuoto NON è identificabile via fallback (servono
    # tutti e tre i campi): solo il SignalRef può confermarlo.
    pending = [{"signal_id": "x", "ref": "",
                "EventName": "Inter v Milan", "MarketName": "",
                "SelectionName": "Over 2,5 goal"}]
    res = cr.interpret("Inter v Milan Over 2,5 goal confermata", pending)
    assert res.status == cr.UNMATCHED


def test_fallback_selezione_corta_non_combacia_dentro_parola():
    # SelectionName "No" non deve combaciare dentro "non" (match a parola intera).
    pending = [{"signal_id": "x", "ref": "",
                "EventName": "Roma v Lazio", "MarketName": "Both Teams To Score",
                "SelectionName": "No"}]
    res = cr.interpret("Roma v Lazio Both Teams To Score non piazzata", pending)
    assert res.status == cr.UNMATCHED


def test_ref_estraneo_non_fa_scattare_il_fallback_nomi():
    # Notifica con un ref ESTRANEO (XYZ999) ma con i nomi di un nostro segnale
    # CHE HA un ref (ABC123): non deve associarsi per nomi (solo per ref).
    text = ("Ref XYZ999: Inter v Milan - Over/Under 2,5 gol - Over 2,5 goal "
            "piazzata")
    res = cr.interpret(text, _pending())
    assert res.status == cr.UNMATCHED


def test_ref_etichettato_estraneo_sopprime_fallback_nomi():
    # Notifica con ref ETICHETTATO estraneo (XYZ999) ma con i nomi di un nostro
    # segnale SENZA ref: non deve associarsi per nomi (è per un'altra scommessa).
    pending = [{"signal_id": "x", "ref": "",
                "EventName": "Roma v Lazio", "MarketName": "Both Teams To Score",
                "SelectionName": "Sì"}]
    res = cr.interpret("Ref XYZ999: Roma v Lazio - Both Teams To Score - Sì piazzata",
                       pending)
    assert res.status == cr.UNMATCHED
    # senza etichetta di ref, lo stesso messaggio per nomi si associa
    ok = cr.interpret("Roma v Lazio - Both Teams To Score - Sì piazzata", pending)
    assert ok.status == cr.CONFIRMED


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


def test_timed_out_timeout_invalido_rifiutato():
    import pytest
    for bad in (float("nan"), float("inf"), 0, -5, "abc"):
        with pytest.raises(ValueError):
            cr.timed_out(added_at=1000, now=2000, timeout=bad)


def test_ref_con_suffisso_punteggiato_non_combacia():
    # ref "ABC123" non deve combaciare dentro "ABC123-4" (ref diverso col suffisso).
    pending = [{"signal_id": "x", "ref": "ABC123"}]
    assert cr.match_pending("Ref ABC123-4 piazzata", pending) is None
    assert cr.match_pending("Ref ABC123 piazzata", pending) is not None


# ── #31: robustezza parsing conferme (3 finding Codex post-merge) ────────────

def test_ref_suffisso_estraneo_sopprime_fallback_nomi():
    # Finding 1: una notifica con ref ETICHETTATO e suffisso ("ABC123/4", scommessa di
    # un'altra leg) NON deve confermare un nostro segnale SENZA ref con i nomi coincidenti,
    # nemmeno se esiste anche un segnale con ref "ABC123". L'estrattore ora cattura il ref
    # completo "abc123/4" (≠ "abc123"), così la guardia anti-ref-estraneo sopprime il fallback.
    pending = [
        {"signal_id": "s1", "ref": "ABC123",
         "EventName": "Inter v Milan", "MarketName": "Esito", "SelectionName": "1"},
        {"signal_id": "s2", "ref": "",
         "EventName": "Roma v Lazio", "MarketName": "Both Teams To Score",
         "SelectionName": "Sì"},
    ]
    text = "Ref ABC123/4: Roma v Lazio - Both Teams To Score - Sì piazzata"
    assert cr.interpret(text, pending).status == cr.UNMATCHED
    # Controprova: lo STESSO messaggio senza etichetta di ref si associa per nomi a s2.
    ok = cr.interpret("Roma v Lazio - Both Teams To Score - Sì piazzata", pending)
    assert ok.status == cr.CONFIRMED and ok.signal_id == "s2"


def test_errore_negato_e_conferma():
    # Finding 2: "no error"/"nessun errore" indica SUCCESSO, non rifiuto.
    assert cr.classify_outcome("No error, bet placed") == cr.CONFIRMED
    assert cr.classify_outcome("Nessun errore, scommessa piazzata") == cr.CONFIRMED
    # ma un errore NON negato resta un rifiuto, e una negazione su 'piazzata' pure
    assert cr.classify_outcome("Errore di piazzamento") == cr.REJECTED
    assert cr.classify_outcome("No error ma scommessa non piazzata") == cr.REJECTED


def test_negazione_in_clausola_separata_resta_conferma():
    # Finding 3: una negazione in una proposizione SEPARATA non ribalta la conferma.
    assert cr.classify_outcome("non serve altro, scommessa piazzata") == cr.CONFIRMED
    res = cr.interpret("Ref ABC123: non serve altro, scommessa piazzata", _pending())
    assert res.status == cr.CONFIRMED and res.signal_id == "s1"
    # ma una negazione ADIACENTE (stessa proposizione) resta un rifiuto (fail-safe invariato)
    assert cr.classify_outcome("scommessa non è stata piazzata") == cr.REJECTED


# ── #31 review (Codex/CodeRabbit su PR-01): chiusura buchi del fail-safe ──────

def test_errore_reale_non_mascherato_da_errore_negato():
    # Review finding: un errore NEGATO non deve sopprimere un errore REALE più avanti.
    # "no error but error occurred" / "nessun errore iniziale, errore piazzamento" → REJECTED.
    assert cr.classify_outcome("no error but error occurred") == cr.REJECTED
    assert cr.classify_outcome(
        "Nessun errore iniziale, errore piazzamento scommessa piazzata") == cr.REJECTED


def test_negazione_conferma_oltre_quattro_parole_resta_rifiuto():
    # Review finding: una negazione adiacente nella STESSA clausola, anche distante >4 parole,
    # resta un rifiuto (fail-safe). Prima la finestra fissa a 4 la lasciava passare.
    assert cr.classify_outcome(
        "scommessa non risulta essere stata ancora piazzata") == cr.REJECTED


def test_senza_errori_e_conferma_non_rifiuto():
    # Review finding: "senza"/"without" è un qualificatore di SUCCESSO, non una negazione del
    # piazzamento: "senza errori scommessa piazzata" → CONFIRMED (non REJECTED).
    assert cr.classify_outcome("senza errori scommessa piazzata") == cr.CONFIRMED
    assert cr.classify_outcome("senza problemi scommessa piazzata") == cr.CONFIRMED


def test_fallback_selezione_dentro_evento_non_basta():
    # Selection "Inter" è dentro EventName "Inter v Milan": la notifica non nomina
    # la selezione separatamente → niente match (porzioni distinte).
    pending = [{"signal_id": "x", "ref": "",
                "EventName": "Inter v Milan", "MarketName": "Esito finale",
                "SelectionName": "Inter"}]
    res = cr.interpret("Inter v Milan - Esito finale piazzata", pending)
    assert res.status == cr.UNMATCHED
    # se la selezione è nominata separatamente, allora combacia
    ok = cr.interpret("Inter v Milan - Esito finale - Inter piazzata", pending)
    assert ok.status == cr.CONFIRMED
