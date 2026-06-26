"""Test della fonte UNICA degli sport del blocco personale (issue #86 PR-P9).

Copre la mappa canonica sport→event_type_id, la normalizzazione case-insensitive e
la **coerenza** fra i moduli che la riusano (catalogue client + tab Betfair Sync):
non devono andare in drift rispetto a `xtrader_bridge.sports`.
"""

from xtrader_bridge import sports
from xtrader_bridge.betfair import catalogue_client, sync_tab_controller


# ── mappa canonica ────────────────────────────────────────────────────────────

def test_sports_event_type_canonico():
    assert sports.SPORTS_EVENT_TYPE == {
        "Calcio": "1", "Tennis": "2", "Basket": "7522", "Rugby Union": "5",
    }


def test_sports_ordine_visualizzazione():
    # L'ordine (tuple da dict) è quello di visualizzazione in GUI.
    assert sports.SPORTS == ("Calcio", "Tennis", "Basket", "Rugby Union")


# ── normalize_sport ─────────────────────────────────────────────────────────────

def test_normalize_sport_case_insensitive_e_spazi():
    assert sports.normalize_sport("calcio") == "Calcio"
    assert sports.normalize_sport("  TENNIS ") == "Tennis"
    assert sports.normalize_sport("rugby union") == "Rugby Union"


def test_normalize_sport_vuoto_o_ignoto_none():
    assert sports.normalize_sport("") is None
    assert sports.normalize_sport(None) is None
    assert sports.normalize_sport("Pallavolo") is None


def test_is_supported_sport():
    assert sports.is_supported_sport("Basket") is True
    assert sports.is_supported_sport("basket") is True
    assert sports.is_supported_sport("") is False
    assert sports.is_supported_sport("Cricket") is False


# ── event_type_id_for_sport ─────────────────────────────────────────────────────

def test_event_type_id_for_sport_noto():
    assert sports.event_type_id_for_sport("Calcio") == "1"
    assert sports.event_type_id_for_sport("tennis") == "2"
    assert sports.event_type_id_for_sport("Basket") == "7522"
    assert sports.event_type_id_for_sport("Rugby Union") == "5"


def test_event_type_id_for_sport_ignoto_none():
    assert sports.event_type_id_for_sport("") is None
    assert sports.event_type_id_for_sport("Hockey") is None


# ── coerenza single-source (niente drift fra moduli) ────────────────────────────

def test_catalogue_client_riusa_la_mappa_canonica():
    # catalogue_client.SPORTS_EVENT_TYPE deve essere ESATTAMENTE quella canonica.
    assert catalogue_client.SPORTS_EVENT_TYPE is sports.SPORTS_EVENT_TYPE


def test_sync_tab_controller_riusa_sport_e_normalize():
    assert sync_tab_controller.SPORTS is sports.SPORTS
    assert sync_tab_controller.normalize_sport is sports.normalize_sport
