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
