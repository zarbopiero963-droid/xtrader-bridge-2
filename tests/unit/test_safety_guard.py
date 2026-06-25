"""Test dei guardrail di sicurezza (PR-19/PHASE 8): DRY_RUN + limite giornaliero."""

import os

import pytest

from xtrader_bridge import atomic_io
from xtrader_bridge import safety_guard as sg


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


def test_reset_al_cambio_giorno():
    lim = sg.DailyLimiter(max_per_day=2)
    day1 = 1_000_000.0                          # 1970-01-12 (UTC)
    assert lim.allow(now=day1) and lim.allow(now=day1)
    assert lim.allow(now=day1) is False         # tetto raggiunto giorno 1
    day2 = day1 + 86_400                         # +1 giorno
    assert lim.allow(now=day2) is True           # reset automatico
    assert lim.remaining(now=day2) == 1


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
