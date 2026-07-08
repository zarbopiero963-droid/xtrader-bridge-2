"""Test del modulo condiviso `xtrader_bridge.validators` (fonte unica anti-drift).

Esercitano le funzioni reali ora condivise da `safety_guard`/`signal_dedupe`
(`require_positive_int`/`require_finite_now`) e da `custom_parser`/`profile_store`
(`safe_filename_core` + `WIN_RESERVED`).
"""

import math

import pytest

from xtrader_bridge import validators as v


def test_require_positive_int_accetta_interi_validi():
    assert v.require_positive_int(10, "x") == 10
    assert v.require_positive_int("10", "x") == 10        # stringa numerica intera
    assert v.require_positive_int(10.0, "x") == 10        # float intero


def test_require_positive_int_rifiuta_bool_e_malformati():
    # bool: True/False da JSON NON devono diventare 1/0 (config malformata).
    # `10**400` (#318 L1-1): int troppo grande per float → OverflowError, da trattare come malformato.
    for bad in (True, False, 0, -1, 1.5, "1.5", float("nan"), float("inf"), "abc", None, 10 ** 400):
        with pytest.raises(ValueError):
            v.require_positive_int(bad, "x")


def test_require_finite_now_accetta_finiti():
    assert v.require_finite_now(1000) == 1000.0
    assert v.require_finite_now(1000.5) == 1000.5
    assert v.require_finite_now("1000") == 1000.0


def test_require_finite_now_rifiuta_bool_e_non_finiti():
    # `10**400` (#318 L1-1): int troppo grande per float → OverflowError, da trattare come malformato.
    for bad in (True, False, float("nan"), float("inf"), float("-inf"), "abc", None, 10 ** 400):
        with pytest.raises(ValueError):
            v.require_finite_now(bad)


def test_int_enorme_solleva_valueerror_non_overflowerror():
    """#318 L1-1: un int troppo grande per un float (es. 10**400) faceva sollevare `OverflowError`
    (sottoclasse di ArithmeticError, NON di ValueError) da `float()` → crash dell'handler/START.
    Ora è catturato e riportato come `ValueError` controllato, come ogni altro input malformato.

    Mutation-guard: sul vecchio codice queste chiamate propagavano `OverflowError`, che
    `pytest.raises(ValueError)` NON cattura → il test falliva."""
    huge = 10 ** 400
    with pytest.raises(ValueError):
        v.require_positive_int(huge, "max_per_day")
    with pytest.raises(ValueError):
        v.require_finite_now(huge)
    # Sanity: `float(huge)` solleva davvero OverflowError (documenta il perché del fix).
    with pytest.raises(OverflowError):
        float(huge)


def test_safe_filename_core_sanitizza():
    assert v.safe_filename_core("  Inter v Milan  ") == "Inter_v_Milan"   # spazi → _
    assert v.safe_filename_core("a/b\\c:d") == "abcd"                     # caratteri non validi rimossi
    assert v.safe_filename_core("Prematch") == "Prematch"                 # nome normale invariato


def test_safe_filename_core_mangla_device_riservati_windows():
    # Match ESATTO, case-insensitive (mantiene il case originale del nome).
    assert v.safe_filename_core("con") == "_con"
    assert v.safe_filename_core("NUL") == "_NUL"
    assert v.safe_filename_core("com1") == "_com1"
    assert v.safe_filename_core("lpt9") == "_lpt9"
    # Solo il match esatto è riservato.
    assert v.safe_filename_core("console") == "console"


def test_safe_filename_core_vuoto_resta_vuoto():
    # Il nucleo NON applica fallback: ritorna "" se il nome si pulisce a vuoto
    # (il fallback per-dominio è responsabilità del chiamante).
    assert v.safe_filename_core("") == ""
    assert v.safe_filename_core("///") == ""
    assert v.safe_filename_core("   ") == ""


def test_win_reserved_copre_con_prn_aux_nul_com_lpt():
    assert {"con", "prn", "aux", "nul"} <= v.WIN_RESERVED
    assert "com1" in v.WIN_RESERVED and "com9" in v.WIN_RESERVED
    assert "lpt1" in v.WIN_RESERVED and "lpt9" in v.WIN_RESERVED
    assert "console" not in v.WIN_RESERVED


def test_math_isfinite_coerente_con_require():
    # Sanity: la soglia usata internamente è math.isfinite (documenta l'intento).
    assert math.isfinite(1.0) and not math.isfinite(float("inf"))
    assert v.require_finite_now(1.0) == 1.0
