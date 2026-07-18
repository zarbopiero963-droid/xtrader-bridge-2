"""P3-21 audit #76 — handicap non numerico nella PK del dizionario Betfair locale.

Bug: `_norm_handicap` coerciva QUALSIASI valore non numerico («abc») a ``0.0`` — ma
l'handicap è parte della **chiave primaria** della selezione
(market_id+selection_id+handicap): la riga malformata COLLIDEVA con la selezione
legittima a handicap 0 e l'upsert ne SOVRASCRIVEVA il `runner_name` → dizionario
corrotto in silenzio (e a valle un ID risolto sul nome sbagliato).

Fix testato: valore non numerico → riga SCARTATA (`upsert_selection` ritorna
``False`` + warning), la selezione legittima resta intatta; ``None``/``""`` restano
il default legittimo 0.0. DB SQLite REALE in memoria."""

import pytest

from xtrader_bridge.betfair.local_db import BetfairLocalDB


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


def _runner_names(db):
    with db._lock:
        rows = db._conn.execute(
            "SELECT runner_name FROM betfair_selections ORDER BY runner_name").fetchall()
    return [r[0] for r in rows]


def test_handicap_malformato_non_corrompe_la_selezione_legittima(db, caplog):
    """FAIL-FIRST: pre-patch «abc» → 0.0 → upsert sulla STESSA PK della selezione
    legittima → runner_name sovrascritto con quello della riga malformata."""
    assert db.upsert_selection("1.10", "47972", "Vincente", handicap=0.0, seen_at=1) is True

    with caplog.at_level("WARNING"):
        esito = db.upsert_selection("1.10", "47972", "Corrotto", handicap="abc", seen_at=2)

    assert esito is False                                  # riga scartata, non scritta
    assert db.count_active("betfair_selections") == 1
    assert _runner_names(db) == ["Vincente"]               # la legittima è INTATTA
    assert any("SCARTATA" in r.getMessage() for r in caplog.records)


def test_handicap_assente_resta_il_default_legittimo(db):
    """Regressione bloccata: None/'' sono il default storico 0.0 (selezione scritta)."""
    assert db.upsert_selection("1.10", "1", "A", handicap=None, seen_at=1) is True
    assert db.upsert_selection("1.10", "2", "B", handicap="", seen_at=1) is True
    assert db.count_active("betfair_selections") == 2


def test_handicap_non_finito_scartato(db, caplog):
    """FAIL-FIRST (round review, GPT-5.5): NaN in SQLite è memorizzato come NULL, e i
    NULL in una PK composita sono tutti DISTINTI → upsert ripetuti di "NaN" non
    andrebbero mai in conflitto e inserirebbero duplicati illimitati. Non-finito →
    riga scartata (stessa classe del bug, stesso fail-closed dei now di dedupe/daily)."""
    for cattivo in ("NaN", "inf", "-inf", float("nan"), float("inf")):
        with caplog.at_level("WARNING"):
            assert db.upsert_selection("1.10", "7", "X", handicap=cattivo, seen_at=1) is False
    assert db.count_active("betfair_selections") == 0      # nessuna riga scritta


def test_handicap_numerico_stringa_invariato(db):
    """Regressione bloccata: '2.5' numerico continua a scrivere la linea giusta e
    l'upsert sulla stessa tripla non duplica."""
    assert db.upsert_selection("1.10", "9", "Over", handicap="2.5", seen_at=1) is True
    assert db.upsert_selection("1.10", "9", "Over (agg)", handicap=2.5, seen_at=2) is True
    assert db.count_active("betfair_selections") == 1
    assert _runner_names(db) == ["Over (agg)"]
