"""Test del lettore di conferme XTrader (PR-17/#... PHASE 7): logica pura."""

import pytest

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


# ── P3-cw4 (#166): `_remove_first` e `_has_keyword` devono usare gli STESSI confini ─────────────
# `_kw_pattern` usa confini ADATTIVI (li mette solo se il bordo è alfanumerico); `_remove_first`
# imponeva `\b` sempre. Su una frase che inizia o finisce con un SIMBOLO i due divergevano: il
# campo veniva TROVATO ma non CONSUMATO, quindi la stessa porzione di testo poteva soddisfare
# due campi diversi. Il test qui sopra (`..._dentro_evento_non_basta`) copriva già l'intenzione,
# ma solo per la forma di bordo in cui le due implementazioni per caso coincidono.

def test_una_conferma_non_associa_un_segnale_di_cui_non_nomina_la_selezione():
    """Il caso operativo che conta: un CONFIRMED errato **chiude un segnale attivo** e lo
    rimuove da coda e CSV.

    Qui la notifica nomina evento e mercato ma NON la selezione. Poiché l'evento finisce con
    «)» — un bordo simbolo — non veniva consumato, e la selezione «Inter» veniva ritrovata
    dentro il nome dell'evento: il segnale risultava confermato da una notifica che non lo
    riguardava."""
    pending = [{"signal_id": "x", "ref": "",
                "EventName": "Inter v Milan (Serie A)", "MarketName": "Esito Finale",
                "SelectionName": "Inter"}]
    res = cr.interpret("Piazzata: Inter v Milan (Serie A) - Esito Finale", pending)
    assert res.status == cr.UNMATCHED

    # Se invece la selezione è nominata a sé, il match è legittimo e deve restare tale.
    ok = cr.interpret("Piazzata: Inter v Milan (Serie A) - Esito Finale - Inter", pending)
    assert ok.status == cr.CONFIRMED


@pytest.mark.parametrize("frase", [
    "inter v milan (serie a)",   # finisce con «)»
    "+1,5",                      # handicap: inizia con «+»
    "✅ goal",                    # inizia con un'emoji
    "over 2,5",                  # tutto alfanumerico: caso di controllo, già funzionante
])
def test_cio_che_viene_trovato_viene_anche_consumato(frase):
    """L'invariante che rende corretto `all_name_fields_present`: se `_has_keyword` trova una
    frase, `_remove_first` deve saperla togliere.

    Finché le due usavano definizioni diverse di «confine» — adattivo l'una, `\\b` fisso
    l'altra — l'invariante valeva solo per le frasi con bordi alfanumerici, ed è esattamente il
    motivo per cui il caso con «)» sfuggiva ai test esistenti."""
    testo = f"piazzata: {frase} - esito finale"
    assert cr._has_keyword(testo, frase), "presupposto del test: la frase è trovata"
    ripulito = cr._remove_first(testo, frase)
    assert not cr._has_keyword(ripulito, frase), (
        f"trovata ma non consumata: {frase!r} resta in {ripulito!r}")


def test_remove_first_ignora_una_frase_vuota():
    """Guardia: `_kw_pattern("")` è vuoto e `re.sub("", …)` sostituirebbe a OGNI posizione,
    sfregiando il testo. Non è raggiungibile da `all_name_fields_present` (che controlla i campi
    prima), ma la funzione è pubblica dentro il modulo e non deve avere quel comportamento."""
    assert cr._remove_first("inter v milan", "") == "inter v milan"
    assert cr._remove_first("inter v milan", "   ") == "inter v milan"


def test_il_fix_recupera_una_conferma_legittima_resa_ambigua_dal_doppio_conteggio():
    """Rilievo GPT-5.5 (#168): il fix è più restrittivo, quindi può trasformare un caso
    AMBIGUO in una conferma singola. Va verificato che sia quella giusta — ed è così.

    Due segnali sullo stesso evento, selezioni «Inter» e «Milan»: entrambe contenute nel nome
    dell'evento. Prima, con l'evento non consumato, **entrambi** i segnali risultavano presenti
    → ambiguo → nessuna conferma, e quella legittima andava persa. Ora l'evento viene consumato
    e resta solo la selezione davvero nominata."""
    pending = [
        {"signal_id": "inter", "ref": "", "EventName": "Inter v Milan (Serie A)",
         "MarketName": "Esito Finale", "SelectionName": "Inter"},
        {"signal_id": "milan", "ref": "", "EventName": "Inter v Milan (Serie A)",
         "MarketName": "Esito Finale", "SelectionName": "Milan"},
    ]
    scelto = cr.match_pending(
        "Piazzata: Inter v Milan (Serie A) - Esito Finale - Inter", pending)
    assert scelto is not None and scelto["signal_id"] == "inter"

    # E il gemello: se la notifica nomina «Milan», si associa l'altro. La distinzione regge in
    # entrambe le direzioni, non per fortuna sull'ordine della lista.
    altro = cr.match_pending(
        "Piazzata: Inter v Milan (Serie A) - Esito Finale - Milan", pending)
    assert altro is not None and altro["signal_id"] == "milan"


@pytest.mark.parametrize("frase", ["Inter v Milan (Serie A)", "INTER V MILAN (SERIE A)",
                                   "inter v milan (serie a)"])
def test_trova_e_consuma_normalizzano_il_case_allo_stesso_modo(frase):
    """Punto di verifica chiesto da Claude Fable 5 (#168): `_has_keyword` e `_remove_first`
    devono normalizzare il case in modo coerente, altrimenti tornerebbero a divergere per un
    motivo diverso da quello appena corretto.

    Entrambe passano da `_kw_pattern`, che minuscola la frase; il testo arriva già normalizzato
    da `match_pending` (`_norm`). Qualunque grafia della stessa frase deve quindi essere sia
    trovata sia consumata."""
    testo = cr._norm("Piazzata: Inter v Milan (Serie A) - Esito Finale")
    assert cr._has_keyword(testo, frase)
    assert not cr._has_keyword(cr._remove_first(testo, frase), frase)
