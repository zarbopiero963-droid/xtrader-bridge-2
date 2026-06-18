"""PR-14: test dei contatori della dashboard (logica pura)."""

import pytest

from xtrader_bridge import dashboard_stats as ds


def test_nuovo_parte_da_zero():
    s = ds.DashboardStats()
    assert s.as_dict() == {name: 0 for name in ds.COUNTER_NAMES}


def test_bump_incrementa_e_ritorna_il_valore():
    s = ds.DashboardStats()
    assert s.bump("received") == 1
    assert s.bump("received") == 2
    assert s.bump("written", 3) == 3
    assert s.get("received") == 2
    assert s.get("written") == 3


def test_bump_contatore_sconosciuto_solleva():
    s = ds.DashboardStats()
    with pytest.raises(KeyError):
        s.bump("inesistente")
    with pytest.raises(KeyError):
        s.get("inesistente")


def test_reset_azzera():
    s = ds.DashboardStats()
    s.bump("written")
    s.bump("errors", 5)
    s.reset()
    assert s.as_dict() == {name: 0 for name in ds.COUNTER_NAMES}


def test_summary_ordine_e_contenuto():
    s = ds.DashboardStats()
    s.bump("received", 4)
    s.bump("discarded", 2)
    summary = s.summary()
    # Stesso ordine ed etichette di COUNTERS (fonte unica).
    assert [label for label, _ in summary] == [label for _, label in ds.COUNTERS]
    as_map = dict(summary)
    assert as_map["📥 Ricevuti"] == 4
    assert as_map["⚠️ Scartati"] == 2
    assert as_map["✅ Scritti"] == 0


def test_as_dict_e_una_copia():
    s = ds.DashboardStats()
    d = s.as_dict()
    d["received"] = 999
    assert s.get("received") == 0   # la copia non altera lo stato interno
