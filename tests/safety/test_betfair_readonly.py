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


def test_blocco_forma_jsonrpc_qualificata():
    """Audit #259 D1: il guard non deve essere aggirabile passando il metodo nella
    forma JSON-RPC completa dell'API Betting. Prima `_normalize` confrontava solo la
    stringa INTERA: `SportsAPING/v1.0/placeOrders` non era tra i nomi corti vietati e
    una scommessa sarebbe potuta partire. Ora si estrae anche il segmento finale.

    Fail-first: sul vecchio codice queste forme qualificate NON sollevavano."""
    for op in ("SportsAPING/v1.0/placeOrders",
               "SportsAPING/v1.0/cancelOrders",
               " sportsaping/v1.0/PLACEORDERS ",
               "SportsAPING\\v1.0\\replaceOrders",     # separatore backslash
               "SportsAPING.v1.0.updateOrders"):       # separatore punto
        assert safety.is_forbidden_betting_op(op) is True, op
        with pytest.raises(safety.ReadOnlyViolation):
            safety.assert_read_only(op)


def test_letture_qualificate_restano_consentite():
    """Contro-campo D1: le letture nella stessa forma qualificata NON devono essere
    bloccate (il segmento finale non è un'operazione di scommessa)."""
    for op in ("SportsAPING/v1.0/listMarketCatalogue",
               "SportsAPING/v1.0/listEventTypes",
               "SportsAPING/v1.0/navigationMenu"):
        assert safety.is_forbidden_betting_op(op) is False, op
        assert safety.assert_read_only(op) == op
    # Un nome che CONTIENE un'operazione vietata come sottostringa non è quel metodo:
    # il confronto è sul segmento esatto, non su substring (nessun falso positivo).
    assert safety.is_forbidden_betting_op("listPlaceOrdersReport") is False


def test_blocco_separatore_finale_non_aggira_il_guard():
    """Review Fable/Fugu #313: un'operazione con separatore FINALE (`placeOrders/`,
    `placeOrders.`) non deve produrre un segmento vuoto che aggira il guard. I
    separatori ai bordi vengono strippati prima dell'estrazione.

    Fail-first: prima queste forme davano tail vuoto e NON venivano bloccate."""
    for op in ("placeOrders/", "placeOrders.", "/placeOrders",
               "SportsAPING/v1.0/placeOrders/", "cancelOrders//",
               "SportsAPING\\v1.0\\updateOrders\\"):
        assert safety.is_forbidden_betting_op(op) is True, op
        with pytest.raises(safety.ReadOnlyViolation):
            safety.assert_read_only(op)
    # Stringhe di soli separatori / vuote non sono operazioni note (nessun crash).
    for noise in ("", "/", "...", "//", None):
        assert safety.is_forbidden_betting_op(noise) is False, noise
