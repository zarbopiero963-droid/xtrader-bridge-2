"""Test del token di generazione (PR-05, fix race #2).

Verifica che un auto-clear "obsoleto" non cancelli un segnale più recente.
"""

from xtrader_bridge.signal_gate import SignalGate


def test_begin_incrementa_e_restituisce_generazione():
    g = SignalGate()
    assert g.begin() == 1
    assert g.begin() == 2


def test_is_current_solo_per_ultima_generazione():
    g = SignalGate()
    g1 = g.begin()
    g2 = g.begin()
    assert g.is_current(g2) is True
    assert g.is_current(g1) is False


def test_clear_obsoleto_non_esegue_azione():
    g = SignalGate()
    g1 = g.begin()
    g.begin()  # arriva un segnale più recente (g2)
    called = []
    ok = g.clear_if_current(g1, lambda: called.append(True))
    assert ok is False
    assert called == []          # il clear obsoleto NON svuota


def test_clear_corrente_esegue_azione():
    g = SignalGate()
    g1 = g.begin()
    called = []
    ok = g.clear_if_current(g1, lambda: called.append(True))
    assert ok is True
    assert called == [True]


def test_scenario_race_clear_dopo_nuovo_segnale():
    # Riproduce il caso Codex: timer del segnale 1 parte, poi arriva il segnale 2.
    g = SignalGate()
    gen_segnale1 = g.begin()
    cleared = []
    # nuovo segnale prima che il clear del primo esegua:
    g.begin()
    # il clear del primo segnale ora è obsoleto e non deve cancellare:
    g.clear_if_current(gen_segnale1, lambda: cleared.append("svuotato"))
    assert cleared == []
