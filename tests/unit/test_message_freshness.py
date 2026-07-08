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


def test_messaggio_dal_futuro_entro_skew_non_e_stantio():
    # #311-3.5-d: un messaggio nel futuro ENTRO la tolleranza max_skew (default 60s) è clampato
    # ad "adesso" → non stantio (clock skew tollerabile, orologi quasi sincronizzati).
    now = 1_000_000.0
    assert mf.is_stale(now + 30, now, max_age=120) is False      # +30s: entro 60 → fresco
    assert mf.is_stale(now + 60, now, max_age=120) is False      # +60s: confine inclusivo → fresco
    assert mf.is_stale(now + 0.5, now, max_age=120) is False     # skew minimo normale → fresco


def test_messaggio_dal_futuro_oltre_skew_e_stantio_fail_closed():
    # #311-3.5-d: OLTRE max_skew un timestamp futuro è implausibile (clock locale sballato) →
    # STANTIO (fail-closed). Con il clock locale indietro un backlog vecchio sembrerebbe "fresco":
    # scartarlo evita di ripiazzare un segnale non databile con certezza.
    now = 1_000_000.0
    assert mf.is_stale(now + 61, now, max_age=120) is True       # +61s: appena oltre → stantio
    assert mf.is_stale(now + 300, now, max_age=120) is True      # +5 min → stantio
    assert mf.is_stale(now + 99999, now, max_age=120) is True    # molto avanti → stantio
    # Mutation-guard: prima del fix il futuro era SEMPRE "non stantio" (now - msg < 0 <= max_age),
    # quindi questa riga falliva sul vecchio codice → regressione bloccata.


def test_max_skew_esplicito_e_default_esposto():
    # #311-3.5-d: max_skew configurabile per-chiamata; il default esposto è 60s.
    now = 1_000_000.0
    assert mf.DEFAULT_MAX_CLOCK_SKEW == 60
    # Tolleranza allargata a 120s: +90s ora è fresco, ma resta stantio col default (60).
    assert mf.is_stale(now + 90, now, max_age=120, max_skew=120) is False
    assert mf.is_stale(now + 90, now, max_age=120) is True       # default 60 → +90s stantio
    # Confine con max_skew esplicito: == soglia ammesso, appena oltre no.
    assert mf.is_stale(now + 120, now, max_age=120, max_skew=120) is False
    assert mf.is_stale(now + 121, now, max_age=120, max_skew=120) is True


def test_max_skew_malformato_usa_default_sicuro():
    # #311-3.5-d: un max_skew rotto NON deve spegnere la protezione: ricade su DEFAULT (60s).
    # Un futuro di +300s resta quindi stantio anche con max_skew corrotto/bool/NaN/inf/<=0.
    now = 1_000_000.0
    for bad in ("abc", True, False, float("nan"), float("inf"), None, [], {}, 0, -5):
        assert mf.is_stale(now + 300, now, max_age=120, max_skew=bad) is True, bad
        # E un futuro entro il default (30s) resta fresco anche con max_skew rotto.
        assert mf.is_stale(now + 30, now, max_age=120, max_skew=bad) is False, bad


def test_futuro_implausibile_ma_filtro_disattivato_non_e_stantio():
    # Coerenza: se l'utente ha spento l'anti-stale (max_age <= 0), NON si applica neppure il
    # reject-skew — il messaggio passa (scelta esplicita dell'utente, come per gli arretrati).
    now = 1_000_000.0
    assert mf.is_stale(now + 99999, now, max_age=0) is False
    assert mf.is_stale(now + 99999, now, max_age=-5) is False


def test_timestamp_messaggio_illeggibile_fail_closed():
    # Audit A4: un messaggio SENZA data (msg.date None) o con timestamp illeggibile NON deve
    # bypassare l'anti-stale — verrebbe ripiazzato come bet live. Fail-CLOSED → stantio.
    now = 1_000_000.0
    assert mf.is_stale(None, now, max_age=120) is True
    assert mf.is_stale("boh", now, max_age=120) is True


def test_now_illeggibile_fail_open():
    # Il `now` è il TUO clock: se illeggibile, fail-OPEN (non scartare un segnale buono).
    assert mf.is_stale(900_000.0, None, max_age=120) is False
    assert mf.is_stale(900_000.0, "boh", max_age=120) is False


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
    assert mf.is_stale(huge, now, max_age=120) is True           # epoch messaggio illeggibile → fail-CLOSED (A4)
    assert mf.is_stale(now - 200, huge, max_age=120) is False    # now illeggibile → fail-open
    # max_age illeggibile → default 120s attivo: vecchio = stantio, recente = no.
    assert mf.is_stale(now - 200, now, max_age=huge) is True
    assert mf.is_stale(now - 5, now, max_age=huge) is False


# ── #53: max_age effettivo non supera clear_delay (clamp) ────────────────────

def test_effective_max_age_clampa_a_clear_delay():
    assert mf.effective_max_age(120, 90) == 90          # 120 > 90 → clamp a 90
    assert mf.effective_max_age(60, 90) == 60           # già sotto → invariato
    assert mf.effective_max_age("120", "90") == 90      # stringhe numeriche editate a mano


def test_effective_max_age_filtro_disattivato_resta_disattivato():
    # max_signal_age <= 0 = filtro spento dall'utente: il clamp NON deve ri-attivarlo.
    assert mf.effective_max_age(0, 90) == 0
    assert mf.effective_max_age(-1, 90) == -1


def test_effective_max_age_clear_delay_invalido_nessun_clamp():
    # clear_delay inservibile (assente/malformato/non positivo/bool) → nessun clamp.
    assert mf.effective_max_age(120, None) == 120
    assert mf.effective_max_age(120, "abc") == 120
    assert mf.effective_max_age(120, 0) == 120
    assert mf.effective_max_age(120, True) == 120


def test_effective_max_age_integrazione_con_is_stale():
    # Con clamp a 90, un messaggio vecchio 100s È stantio; senza clamp (max_age 120) non lo era.
    assert mf.is_stale(0, 100, mf.effective_max_age(120, 90)) is True
    assert mf.is_stale(0, 100, 120) is False


def test_effective_max_age_malformato_clampato_al_timeout():
    # Codex #250: un max_signal_age malformato/bool/NaN/inf NON deve bypassare il clamp.
    # is_stale ricondurrebbe questi valori a DEFAULT_MAX_AGE (120); effective_max_age deve
    # quindi clampare 120 al timeout (90), non restituire il valore rotto così com'è.
    for bad in ("abc", True, False, float("nan"), float("inf"), None, [], {}):
        assert mf.effective_max_age(bad, 90) == 90, bad
    # Con clear_delay >= DEFAULT (120) non c'è clamp: resta DEFAULT_MAX_AGE.
    assert mf.effective_max_age("abc", 200) == mf.DEFAULT_MAX_AGE


def test_effective_max_age_malformato_e_is_stale_non_scrivono_arretrato():
    # Integrazione fail-first del finding: con riga da 90s e max_signal_age="abc", un
    # arretrato di 100s deve risultare STANTIO (non scritto). Prima del fix effective_max_age
    # ritornava "abc" → is_stale ricadeva su 120 → 100 < 120 → "fresco" → scritto.
    eff = mf.effective_max_age("abc", 90)
    assert mf.is_stale(0, 100, eff) is True              # 100s > clamp 90 → stantio
    assert mf.is_stale(0, 80, eff) is False              # 80s < 90 → ancora fresco


# ── #371: capped_max_age (clamp ANCHE alla finestra di deduplica) ────────────────

def test_capped_max_age_clampa_alla_finestra_dedup():
    # Config non-default con età effettiva OLTRE la finestra dedup (300s): il clamp la riporta a 300.
    assert mf.capped_max_age(600, 600, 300) == 300      # eff 600 > dedup 300 → 300
    assert mf.capped_max_age(600, 400, 300) == 300      # eff min(600,400)=400 > 300 → 300
    # Anche quando clear_delay è invalido, l'effettivo grezzo (600) va comunque clampato a 300.
    assert mf.capped_max_age(600, None, 300) == 300


def test_capped_max_age_default_non_morde():
    # Default (eff 120 < dedup 300): nessun cambiamento osservabile rispetto a effective_max_age.
    assert mf.capped_max_age(120, 120, 300) == 120
    assert mf.capped_max_age(90, 120, 300) == 90        # eff min(90,120)=90 < 300 → invariato


def test_capped_max_age_filtro_disattivato_resta_disattivato():
    # max_signal_age <= 0 = filtro spento dall'utente: il clamp NON lo ri-attiva.
    assert mf.capped_max_age(0, 600, 300) == 0
    assert mf.capped_max_age(-1, 600, 300) == -1


def test_capped_max_age_finestra_dedup_invalida_nessun_clamp():
    # dedupe_window malformata/bool/non-positiva/None → nessun clamp: resta l'effettivo.
    for bad in (None, "abc", 0, -5, True, False, float("nan"), float("inf")):
        assert mf.capped_max_age(600, 600, bad) == mf.effective_max_age(600, 600), bad


def test_capped_max_age_finestra_dedup_float_valida():
    # #371 (review GLM 5.2): `dedupe_window` come float valido (non int) deve clampare comunque.
    assert mf.capped_max_age(600, 600, 300.0) == 300     # eff 600 > 300.0 → clamp
    assert mf.is_stale(0, 350, mf.capped_max_age(600, 600, 300.0)) is True   # a 350s → stantio


def test_capped_max_age_eff_malformato_ritorna_invariato():
    # #371 (review GLM 5.2): con `clear_delay` malformato, `effective_max_age` ritorna il
    # max_signal_age grezzo; se questo NON è numerico, `capped_max_age` lo lascia invariato
    # (float(eff) fallisce → return eff) e `is_stale` lo ricondurrà a DEFAULT_MAX_AGE.
    assert mf.capped_max_age("abc", "xyz", 300) == mf.effective_max_age("abc", "xyz") == "abc"
    # is_stale ricade su DEFAULT (120): un arretrato di 130s è stantio, 110s no.
    assert mf.is_stale(0, 130, mf.capped_max_age("abc", "xyz", 300)) is True
    assert mf.is_stale(0, 110, mf.capped_max_age("abc", "xyz", 300)) is False


def test_capped_max_age_preserva_il_tipo():
    # #371 (review Fable 5 / Fugu Ultra): la funzione NON introduce un float spurio. Senza clamp
    # ritorna esattamente ciò che ritorna `effective_max_age` (stesso valore E tipo); col clamp
    # ritorna la `dedupe_window` originale (int 300), non il `dw` coerciuto a float.
    # Ramo raw di effective_max_age (clear_delay invalido) → int preservato senza clamp:
    assert mf.capped_max_age(120, None, 300) == mf.effective_max_age(120, None) == 120
    assert isinstance(mf.capped_max_age(120, None, 300), int)          # non 120.0
    # Clamp → ritorna la dedupe_window originale (int), non float:
    assert mf.capped_max_age(600, 600, 300) == 300
    assert isinstance(mf.capped_max_age(600, 600, 300), int)           # non 300.0


def test_capped_max_age_ridelivery_reconnect_e_stale():
    # Integrazione fail-first del finding #371 (ridelivery post-reconnect, drop_pending_updates=False):
    # config età effettiva 600s ma finestra dedup 300s; un update rideliverato a 350s (oltre la
    # finestra dedup, quindi NON più deduplicato) DEVE risultare STANTIO col clamp, così non viene
    # riscritto → niente doppia scommessa.
    capped = mf.capped_max_age(600, 600, 300)           # → 300
    assert mf.is_stale(0, 350, capped) is True          # 350s > 300 → stantio (scartato)
    # Mutation-guard: senza il clamp (eff 600) lo stesso update sarebbe "fresco" → riscritto.
    assert mf.is_stale(0, 350, mf.effective_max_age(600, 600)) is False
    # Entro la finestra dedup un update rideliverato resta gestito dalla dedup (non stantio).
    assert mf.is_stale(0, 250, capped) is False         # 250s < 300 → fresco (dedup lo blocca)
