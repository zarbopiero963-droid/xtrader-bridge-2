"""Test dei guardrail di sicurezza (PR-19/PHASE 8): DRY_RUN + limite giornaliero."""

import os
import time

import pytest

from xtrader_bridge import atomic_io
from xtrader_bridge import safety_guard as sg


@pytest.fixture(autouse=True)
def _daykey_deterministico(monkeypatch):
    """#311-3.5-f: `_day_key` ora usa `time.localtime`, quindi il rollover del tetto giornaliero
    dipenderebbe dal fuso del runner (CI vs macchina di sviluppo). Per rendere DETERMINISTICI i
    test che asseriscono date assolute (`1970-01-1x`) a prescindere dal `TZ` della macchina, si
    forza `localtime = gmtime` come default. I test che verificano espressamente il comportamento
    LOCALE (mezzanotte locale ≠ UTC) SOVRASCRIVONO questo mock nel proprio corpo."""
    monkeypatch.setattr(sg.time, "localtime", time.gmtime)


# ── DRY_RUN (simulazione) ────────────────────────────────────────────────────

def test_dry_run_default_sicuro_se_campo_assente():
    # Config vecchia/senza il campo → simulazione attiva (non scrive il CSV operativo).
    assert sg.is_dry_run({}) is True
    assert sg.should_write_operational_csv({}) is False


def test_dry_run_bool_esplicito():
    assert sg.is_dry_run({"dry_run": True}) is True
    assert sg.is_dry_run({"dry_run": False}) is False
    assert sg.should_write_operational_csv({"dry_run": False}) is True


def test_dry_run_da_stringa_robusto():
    # Solo valori OFF ESPLICITI → modalità reale.
    for off in ("false", "False", "0", "no", "off", "n"):
        assert sg.is_dry_run({"dry_run": off}) is False, off
    # qualsiasi altra stringa non vuota → simulazione (default sicuro)
    for on in ("true", "1", "yes", "boh"):
        assert sg.is_dry_run({"dry_run": on}) is True, on


def test_dry_run_vuoto_o_null_fallisce_chiuso_in_simulazione():
    # Vuoto / None / "none" sono valori NON impostati o malformati: devono fallire
    # CHIUSI in simulazione (mai abilitare la scrittura del CSV reale per sbaglio).
    assert sg.is_dry_run({"dry_run": ""}) is True
    assert sg.is_dry_run({"dry_run": None}) is True
    assert sg.is_dry_run({"dry_run": "none"}) is True
    assert sg.should_write_operational_csv({"dry_run": ""}) is False
    assert sg.should_write_operational_csv({"dry_run": None}) is False


def test_dry_run_input_non_dict():
    assert sg.is_dry_run(None) is True       # fail-safe: simulazione


def test_warning_solo_in_modalita_reale():
    assert sg.real_mode_warning({"dry_run": True}) == ""
    assert sg.real_mode_warning({}) == ""     # default = simulazione
    w = sg.real_mode_warning({"dry_run": False})
    assert w and "REALE" in w


# ── limite giornaliero ───────────────────────────────────────────────────────

def test_limite_giornaliero_blocca_oltre_il_tetto():
    lim = sg.DailyLimiter(max_per_day=3)
    t = 1_000_000.0
    assert [lim.allow(now=t) for _ in range(3)] == [True, True, True]
    assert lim.allow(now=t) is False          # 4° nello stesso giorno → bloccato
    assert lim.remaining(now=t) == 0


def test_release_restituisce_una_slot_mantenendo_il_giorno():
    """#184 low-tracker-nonwrite (Codex P2): `release()` restituisce UNA slot consumata (decremento,
    mai sotto 0) MANTENENDO il giorno corrente — serve a disfare il consumo di un DRY_RUN senza
    riportare indietro la normalizzazione del giorno."""
    t = 1_000_000.0
    lim = sg.DailyLimiter(max_per_day=3)
    assert lim.allow(now=t) and lim.allow(now=t)         # 2 consumate
    assert lim.remaining(now=t) == 1
    day = lim.state()["day"]
    lim.release()                                         # restituisce 1
    assert lim.remaining(now=t) == 2
    assert lim.state()["day"] == day                     # giorno invariato
    # floor a 0: più release del consumato non va sotto zero.
    lim.release(); lim.release(); lim.release()
    assert lim.remaining(now=t) == 3
    assert lim.state()["count"] == 0


def test_reset_al_cambio_giorno():
    lim = sg.DailyLimiter(max_per_day=2)
    day1 = 1_000_000.0                          # 1970-01-12 (UTC)
    assert lim.allow(now=day1) and lim.allow(now=day1)
    assert lim.allow(now=day1) is False         # tetto raggiunto giorno 1
    day2 = day1 + 86_400                         # +1 giorno
    assert lim.allow(now=day2) is True           # reset automatico
    assert lim.remaining(now=day2) == 1


def test_salto_orologio_indietro_non_riapre_il_tetto():
    """F3 #258: un salto dell'orologio all'INDIETRO (skew NTP/regolazione manuale) non deve
    azzerare il conteggio: `_roll` vedeva un giorno «diverso» valido e resettava → il tetto
    già consumato si RIAPRIVA (overtrading, fail-open). Ora il reset avviene SOLO se il
    nuovo giorno è strettamente FUTURO; su salto indietro giorno e conteggio restano.

    Fail-first: sul vecchio codice `allow(now=ieri)` tornava True (cap riaperto)."""
    lim = sg.DailyLimiter(max_per_day=1)
    today = 1_000_000.0                           # 1970-01-12 (UTC)
    assert lim.allow(now=today) is True
    assert lim.allow(now=today) is False          # tetto consumato oggi
    yesterday = today - 86_400
    assert lim.allow(now=yesterday) is False      # salto indietro: NON riapre il tetto
    assert lim.state()["day"] == "1970-01-12"     # giorno NON retrocesso
    assert lim.allow(now=today) is False          # tornati a oggi: ancora consumato
    assert lim.allow(now=today + 86_400) is True  # il giorno DOPO si azzera normalmente


def test_giorno_futuro_persistito_resta_fail_closed():
    """F3 #258 (review GPT-5.5 su #306): uno stato persistito con `day` VALIDO ma nel FUTURO
    (orologio avanti al salvataggio, poi corretto) non deve riaprire il tetto: il conteggio
    resta attribuito a quel giorno e il limiter resta (più) restrittivo finché la data reale
    non lo raggiunge — fail-closed documentato, mai più permissivo."""
    lim = sg.DailyLimiter(max_per_day=1)
    today = 1_000_000.0                            # 1970-01-12 (UTC, `_day_key` usa gmtime)
    assert lim.restore_state({"day": "1970-01-13", "count": 1}) is True   # domani, cap pieno
    assert lim.allow(now=today) is False           # oggi < _day: NON riapre né retrocede
    assert lim.state() == {"day": "1970-01-13", "count": 1}
    assert lim.allow(now=today + 86_400) is False  # raggiunto il giorno: conteggio suo, pieno
    assert lim.allow(now=today + 2 * 86_400) is True   # il giorno DOPO: reset normale


def test_salto_avanti_poi_correzione_indietro_resta_fail_closed():
    """F3 #258 (review Fable su #306, gemello dello scenario base): orologio AVANTI di
    giorni (BIOS/VM resume) → il limiter consuma sul giorno futuro; alla CORREZIONE
    dell'orologio non retrocede né riapre: resta «stuck» fail-closed sul giorno futuro
    finché la data reale non lo supera. Comportamento documentato in `_roll`: al più
    più restrittivi, mai più permissivi."""
    lim = sg.DailyLimiter(max_per_day=1)
    today = 1_000_000.0                            # 1970-01-12 (UTC)
    future = today + 5 * 86_400                    # orologio avanti di 5 giorni
    assert lim.allow(now=future) is True           # consuma il giorno futuro
    assert lim.allow(now=today) is False           # correzione indietro: NON riapre
    assert lim.state()["day"] == "1970-01-17"      # giorno non retrocesso (stuck documentato)
    assert lim.allow(now=future + 86_400) is True  # oltre il giorno futuro: reset normale


def test_skew_avanti_oltre_mezzanotte_e_ritorno_non_riapre_il_cap_gia_speso():
    """#306 Codex P1: con cap 2 GIÀ consumato oggi, uno skew avanti oltre mezzanotte fa un
    reset legittimo (giorno nuovo) e consuma 1 sul budget di domani; alla correzione
    dell'orologio a OGGI, il vecchio codice accettava un altro segnale (count=1 < 2 sul
    budget di domani) → il cap di oggi, già pieno, si riapriva. Ora durante lo skew
    all'indietro (giorno registrato ≠ oggi) il limiter è fail-closed DURO: nessun
    segnale e capacità zero finché il tempo reale non raggiunge il giorno registrato.

    Fail-first: sul codice precedente `allow(now=oggi)` dopo il ritorno tornava True."""
    lim = sg.DailyLimiter(max_per_day=2)
    today = 1_000_000.0                            # 1970-01-12 (UTC)
    assert lim.allow(now=today) and lim.allow(now=today)
    assert lim.allow(now=today) is False           # cap di oggi PIENO
    assert lim.allow(now=today + 86_400) is True   # skew avanti: giorno nuovo, consuma 1
    assert lim.allow(now=today) is False           # correzione a oggi: NON riapre
    assert lim.remaining(now=today) == 0           # capacità zero durante lo skew indietro
    assert lim.state()["day"] == "1970-01-13"      # giorno registrato non retrocesso
    assert lim.allow(now=today + 86_400) is True   # raggiunto domani: 1 residuo del SUO budget
    assert lim.allow(now=today + 86_400) is False  # e poi pieno


# ── #311-3.5-f: reset del tetto giornaliero alla mezzanotte LOCALE (non UTC) ──────

def _tz_utc_plus(hours):
    """`localtime` simulato per un fuso fisso UTC+`hours`, così il rollover LOCALE è testabile
    in modo deterministico senza dipendere dal `TZ` reale della macchina/CI (né da `tzset`, che
    su Windows non esiste)."""
    return lambda secs=None: time.gmtime((time.time() if secs is None else secs) + hours * 3600)


def test_day_key_usa_ora_locale_non_utc(monkeypatch):
    """#311-3.5-f: `_day_key` segue la mezzanotte LOCALE. Con un fuso UTC+2 simulato, un epoch
    che in UTC è 1970-01-12 22:00 è già 1970-01-13 00:00 in locale → la chiave è quella LOCALE.
    Mutation-guard: col vecchio `gmtime` la chiave sarebbe '1970-01-12'."""
    monkeypatch.setattr(sg.time, "localtime", _tz_utc_plus(2))
    epoch = 11 * 86_400 + 22 * 3600            # 1970-01-12 22:00:00 UTC = 1970-01-13 00:00 UTC+2
    assert sg._day_key(epoch) == "1970-01-13"
    assert time.gmtime(epoch).tm_mday == 12    # baseline: in UTC è ANCORA il 12 (il fix cambia davvero)


def test_limiter_reset_a_mezzanotte_locale(monkeypatch):
    """#311-3.5-f: il DailyLimiter registra e resetta sul GIORNO LOCALE. Con UTC+2, due segnali a
    cavallo della mezzanotte LOCALE (ma stesso giorno UTC) cadono in giorni LOCALI diversi → reset.
    Mutation-guard: col vecchio `gmtime` sarebbero lo stesso giorno UTC (12) → nessun reset → il
    secondo `allow` tornerebbe False."""
    monkeypatch.setattr(sg.time, "localtime", _tz_utc_plus(2))
    lim = sg.DailyLimiter(max_per_day=1)
    before = 11 * 86_400 + 21 * 3600           # UTC 21:00 → locale 23:00 (giorno 12)
    after = 11 * 86_400 + 22 * 3600            # UTC 22:00 → locale 00:00 (giorno 13)
    assert lim.allow(now=before) is True        # giorno locale 12: consuma
    assert lim.allow(now=before) is False       # tetto pieno (giorno locale 12)
    assert lim.state()["day"] == "1970-01-12"   # giorno LOCALE registrato
    assert lim.allow(now=after) is True         # mezzanotte locale passata → nuovo giorno → reset
    assert lim.state()["day"] == "1970-01-13"


def test_invarianti_fail_closed_con_ora_locale(monkeypatch):
    """#311-3.5-f: il passaggio a ora locale NON indebolisce il fail-closed — un salto
    dell'orologio all'INDIETRO non riapre un tetto già consumato, anche con un fuso locale ≠ UTC."""
    monkeypatch.setattr(sg.time, "localtime", _tz_utc_plus(2))
    lim = sg.DailyLimiter(max_per_day=1)
    today = 11 * 86_400 + 22 * 3600            # locale 1970-01-13 00:00
    assert lim.allow(now=today) is True
    assert lim.allow(now=today) is False        # consumato
    assert lim.allow(now=today - 86_400) is False   # salto indietro: NON riapre il tetto
    assert lim.state()["day"] == "1970-01-13"   # data LOCALE non retrocessa


def test_max_per_day_invalido_rifiutato():
    # bool incluso: max_per_day=True da JSON verrebbe coercito a 1 (cap=1/giorno).
    for bad in (0, -1, 2.5, float("nan"), float("inf"), "abc", True, False):
        with pytest.raises(ValueError):
            sg.DailyLimiter(max_per_day=bad)


def test_now_non_finito_o_bool_rifiutato():
    lim = sg.DailyLimiter(max_per_day=5)
    for bad in (float("nan"), float("inf"), True, False, "x"):
        with pytest.raises(ValueError):
            lim.allow(now=bad)


def test_stato_sopravvive_al_riavvio_stesso_giorno():
    t = 1_000_000.0
    lim = sg.DailyLimiter(max_per_day=3)
    lim.allow(now=t)
    lim.allow(now=t)
    snap = lim.state()
    # nuovo limiter (riavvio): ripristina → conteggio preservato nello stesso giorno
    lim2 = sg.DailyLimiter(max_per_day=3)
    lim2.restore_state(snap)
    assert lim2.remaining(now=t) == 1
    assert lim2.allow(now=t) is True
    assert lim2.allow(now=t) is False           # tetto raggiunto (2 + 1)


def test_restore_state_malformato_ignorato():
    lim = sg.DailyLimiter(max_per_day=5)
    for bad in (None, [], {"day": 1, "count": "x"}, {"count": -1, "day": "2026-01-01"}):
        assert lim.restore_state(bad) is False  # malformato → False, non solleva
    # stato resta pulito: tetto pieno disponibile
    assert lim.remaining(now=1_000_000.0) == 5
    # un payload valido viene applicato e ritorna True.
    assert lim.restore_state({"day": "2026-01-01", "count": 2}) is True


def test_restore_state_count_bool_rifiutato_fail_closed():
    """#184 low-bool-count: un `count` BOOLEANO (da `daily_state.json` corrotto/manomesso con
    `"count": true/false`) NON deve essere accettato come 1/0 — `isinstance(True, int)` è True, ma un
    conteggio è un intero, non un bool. Restore fail-closed: False, limiter invariato.

    Fail-first: senza il guard `not isinstance(count, bool)`, `count=True` veniva applicato come 1."""
    lim = sg.DailyLimiter(max_per_day=5)
    assert lim.restore_state({"day": "2026-01-01", "count": 3}) is True   # stato valido di partenza
    for bad_count in (True, False):
        assert lim.restore_state({"day": "2026-01-02", "count": bad_count}) is False
    # il limiter NON è stato toccato dal payload bool: resta lo stato valido precedente (count=3).
    assert lim.state()["count"] == 3


def test_restore_state_day_malformato_non_azzera_il_conteggio():
    """#184 M4: uno stato corrotto con `day` MALFORMATO (non `YYYY-MM-DD`) ma `count` valido
    NON deve concedere un cap giornaliero PIENO. Prima `_roll`, vedendo `day` diverso da oggi,
    azzerava il conteggio → overtrading (fail-open). Ora il conteggio viene CONSERVATO e
    attribuito al giorno corrente (fail-closed): il tetto residuo riflette i segnali già usati.

    Fail-first: sul vecchio codice `_roll` azzerava → `remaining` tornava al massimo (5)."""
    t = 1_000_000.0
    lim = sg.DailyLimiter(max_per_day=5)
    # `day` malformato (es. file corrotto/manomesso) ma 4 segnali già consumati.
    assert lim.restore_state({"day": "non-una-data", "count": 4}) is True
    assert lim.remaining(now=t) == 1            # conteggio conservato (NON un cap pieno)
    assert lim.allow(now=t) is True             # l'ultimo ammesso
    assert lim.allow(now=t) is False            # tetto raggiunto: niente overtrading


def test_restore_state_day_impossibile_non_azzera_il_conteggio():
    """#184 M4 (Codex P1 / Sourcery): un `day` con FORMATO `YYYY-MM-DD` ma data IMPOSSIBILE
    (`2026-99-99`, `2026-02-30`) non è un giorno reale e NON deve far azzerare il conteggio.
    Con un controllo solo-regex passerebbe come "valido diverso da oggi" → reset → cap pieno
    (overtrading). La validazione di calendario lo tratta come UNKNOWN (fail-closed).

    Fail-first: con il vecchio controllo `_DAY_RE` `remaining` tornava al massimo (5)."""
    t = 1_000_000.0
    for impossibile in ("2026-99-99", "2026-02-30", "2026-13-01", "2026-00-10"):
        lim = sg.DailyLimiter(max_per_day=5)
        assert lim.restore_state({"day": impossibile, "count": 4}) is True
        assert lim.remaining(now=t) == 1, f"{impossibile}: conteggio scartato (overtrading)"
        assert lim.allow(now=t) is True
        assert lim.allow(now=t) is False        # tetto: niente cap pieno da stato corrotto


def test_is_valid_day_solo_date_canoniche_reali():
    """#184 M4: `_is_valid_day` accetta SOLO date di calendario reali in forma canonica
    zero-padded (quella di `_day_key`); rifiuta formati/varianti non canoniche e impossibili."""
    assert sg._is_valid_day("2026-06-28") is True
    assert sg._is_valid_day(sg._day_key(1_000_000.0)) is True       # round-trip con _day_key
    for bad in ("2026-99-99", "2026-02-30", "2026-13-01", "2026-1-1", " 2026-06-28",
                "2026/06/28", "garbage", "", None, 20260628):
        assert sg._is_valid_day(bad) is False, f"{bad!r} accettato per errore"


def test_restore_state_day_valido_giorno_diverso_azzera_normalmente():
    """#184 M4 (contro-prova): un `day` VALIDO ma di un GIORNO DIVERSO da oggi deve continuare
    ad azzerare il conteggio (è un nuovo giorno reale, reset legittimo). La protezione M4 vale
    SOLO per i `day` malformati, non cambia il rollover quotidiano normale."""
    ieri = 1_000_000.0                          # _day_key ≈ 1970-01-12
    oggi = ieri + 86_400.0                       # +1 giorno → chiave diversa ma VALIDA
    lim = sg.DailyLimiter(max_per_day=5)
    assert lim.restore_state({"day": sg._day_key(ieri), "count": 4}) is True
    assert lim.remaining(now=oggi) == 5         # nuovo giorno valido → reset al cap pieno


def test_restore_state_day_non_stringa_conserva_count_fail_closed():
    """#184 M4: anche un `day` non-stringa (es. `null`/numero da JSON manomesso) con `count`
    valido non scarta il conteggio: `day` → "" (unknown) e il conteggio resta del giorno
    corrente (fail-closed)."""
    t = 1_000_000.0
    lim = sg.DailyLimiter(max_per_day=3)
    assert lim.restore_state({"day": None, "count": 2}) is True   # day non-stringa accettato come unknown
    assert lim.remaining(now=t) == 1
    assert lim.allow(now=t) is True
    assert lim.allow(now=t) is False


# ── audit #105 P2: persistenza daily state atomica + fsync ────────────────────

def test_save_load_state_round_trip_senza_temporanei(tmp_path):
    t = 1_000_000.0
    lim = sg.DailyLimiter(max_per_day=3)
    lim.allow(now=t)
    lim.allow(now=t)
    p = tmp_path / "daily.json"
    assert sg.save_state(lim, str(p)) is True
    assert not (tmp_path / "daily.json.tmp").exists()       # nessun temporaneo residuo
    # ricarico in un nuovo limiter (riavvio same-day): conteggio preservato.
    lim2 = sg.DailyLimiter(max_per_day=3)
    assert sg.load_state(lim2, str(p)) is True
    assert lim2.remaining(now=t) == 1


def test_save_state_atomico_non_distrugge_il_file_su_errore(tmp_path, monkeypatch):
    # audit #105 P2: una os.replace fallita NON deve troncare/cancellare lo stato esistente
    # e non deve lasciare un .tmp (crash-safety, come signal_dedupe).
    t = 1_000_000.0
    p = tmp_path / "daily.json"
    good = sg.DailyLimiter(max_per_day=5)
    good.allow(now=t)
    assert sg.save_state(good, str(p)) is True              # stato valido iniziale

    def boom(src, dst):
        raise OSError("rename interrotto (simulato)")

    # Il rename atomico vive ora in `atomic_io` (helper condiviso): si patcha lì.
    monkeypatch.setattr(atomic_io.os, "replace", boom)
    assert sg.save_state(sg.DailyLimiter(max_per_day=5), str(p)) is False
    monkeypatch.undo()
    # Il file su disco è ancora quello valido precedente; nessun temporaneo lasciato.
    lim2 = sg.DailyLimiter(max_per_day=5)
    assert sg.load_state(lim2, str(p)) is True
    assert lim2.remaining(now=t) == 4                        # 5 - 1 (lo stato "good")
    assert not (tmp_path / "daily.json.tmp").exists()
    assert not [f for f in os.listdir(tmp_path) if f.startswith(".guard_")]


def test_load_state_file_assente_o_corrotto_ritorna_false(tmp_path):
    lim = sg.DailyLimiter(max_per_day=5)
    assert sg.load_state(lim, str(tmp_path / "mai_esistito.json")) is False
    bad = tmp_path / "corrotto.json"
    bad.write_text("{ non json ,,,")
    assert sg.load_state(lim, str(bad)) is False
    # JSON VALIDO ma struttura inattesa → load_state propaga il no-op di restore_state (False),
    # non un falso "caricato" (Sourcery).
    weird = tmp_path / "valido_ma_strano.json"
    weird.write_text('{"foo": "bar"}')
    assert sg.load_state(lim, str(weird)) is False
    assert lim.remaining(now=1_000_000.0) == 5              # limiter invariato
