"""Test hard del guard read-only Betfair (issue #86 PR-P1).

Esercita le funzioni reali di `xtrader_bridge.betfair.safety`: il guard deve
bloccare le 4 operazioni di scommessa (anche in varianti di maiuscole/spazi) e
lasciar passare le operazioni di lettura. È una regola di sicurezza assoluta del
blocco personale: nessuna scommessa diretta può mai partire dal bridge.
"""

import pytest

from xtrader_bridge import betfair
from xtrader_bridge.betfair import safety


# ── elenco operazioni vietate ─────────────────────────────────────────────────

def test_forbidden_set_contiene_le_quattro_operazioni():
    assert safety.FORBIDDEN_BETTING_OPS == frozenset(
        {"placeOrders", "cancelOrders", "replaceOrders", "updateOrders"})


def test_reexport_dal_package():
    # Le API del guard sono raggiungibili anche da `xtrader_bridge.betfair`.
    assert betfair.FORBIDDEN_BETTING_OPS == safety.FORBIDDEN_BETTING_OPS
    assert betfair.assert_read_only is safety.assert_read_only
    assert betfair.is_forbidden_betting_op is safety.is_forbidden_betting_op
    assert betfair.ReadOnlyViolation is safety.ReadOnlyViolation


# ── assert_read_only: blocca le scommesse ─────────────────────────────────────

def test_assert_read_only_blocca_ogni_operazione_di_scommessa():
    for op in ("placeOrders", "cancelOrders", "replaceOrders", "updateOrders"):
        with pytest.raises(safety.ReadOnlyViolation):
            safety.assert_read_only(op)


def test_blocco_robusto_a_maiuscole_e_spazi():
    # Un guard aggirabile con una maiuscola diversa non protegge: deve reggere.
    for op in ("PlaceOrders", "PLACEORDERS", " placeorders ", "cancelORDERS"):
        assert safety.is_forbidden_betting_op(op) is True
        with pytest.raises(safety.ReadOnlyViolation):
            safety.assert_read_only(op)


def test_assert_read_only_consente_le_letture_e_le_ritorna():
    # Le operazioni di sola lettura usate dal sync passano e vengono ritornate.
    for op in ("listEventTypes", "listEvents", "listCompetitions",
               "listMarketCatalogue", "listMarketTypes", "navigation"):
        assert safety.assert_read_only(op) == op
        assert safety.is_forbidden_betting_op(op) is False


def test_input_non_stringa_non_e_operazione_vietata():
    # None/oggetti non sono operazioni note: non vietati (e non crashano).
    for bad in (None, 123, object()):
        assert safety.is_forbidden_betting_op(bad) is False
        assert safety.assert_read_only(bad) is bad
