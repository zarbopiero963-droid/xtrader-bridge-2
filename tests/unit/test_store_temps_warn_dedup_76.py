"""P3-17 + P3-19 audit #76 — sweep dei tmp orfani degli store e dedup warning corretto.

- **P3-17**: lo sweep d'avvio (`_sweep_orphan_csv_temps`, #184 LOW) puliva SOLO la
  cartella del CSV: i temporanei orfani delle scritture atomiche di config
  (`.config_*.tmp`), anti-duplicato (`.dedupe_*.tmp`), tetto giornaliero
  (`.guard_*.tmp`), dirty-CSV (`tmp_*.tmp`) e profili (`.profile_*.json`) si
  accumulavano per sempre riavvio dopo riavvio.
- **P3-19**: `name_mapping_store._warn_malformed` deduplicava sul valore TRONCATO a
  57 char (due valori lunghi distinti con lo stesso prefisso → un solo warning) e
  senza lock (divergente da `source_manager._WARNED_LOCK`).

Qui: warn-dedup su store REALE + wiring dello sweep pinnato sul sorgente; i test
COMPORTAMENTALI dello sweep (che importano `app`) sono in
`tests/integration/test_store_temps_sweep_76.py` (stub tkinter del conftest)."""

import threading

import pytest

from xtrader_bridge import name_mapping_store


# ── P3-17: sweep degli store all'avvio ───────────────────────────────────────────────

def test_sweep_store_cablato_allo_startup():
    """Wiring pinnato sul sorgente (pattern #311): lo sweep degli store è chiamato
    allo startup accanto a quello del CSV."""
    import pathlib
    import xtrader_bridge
    src = (pathlib.Path(xtrader_bridge.__path__[0]) / "app.py").read_text(encoding="utf-8")
    i_csv = src.index("self._sweep_orphan_csv_temps()")
    i_store = src.index("self._sweep_orphan_store_temps()")
    assert i_csv < i_store < i_csv + 400                 # subito dopo, stesso startup


# ── P3-19: dedup warning su valore intero e sotto lock ───────────────────────────────

@pytest.fixture(autouse=True)
def _warn_puliti():
    name_mapping_store._reset_warnings()
    yield
    name_mapping_store._reset_warnings()


def test_valori_lunghi_distinti_entrambi_segnalati(caplog):
    """FAIL-FIRST: pre-patch la chiave di dedup usava il valore TRONCATO a 57 char —
    il secondo valore (stesso prefisso, coda diversa) veniva soppresso dal log."""
    prefisso = "X" * 80
    with caplog.at_level("WARNING"):
        name_mapping_store._warn_malformed("sport", prefisso + "-PRIMO")
        name_mapping_store._warn_malformed("sport", prefisso + "-SECONDO")

    warnings = [r for r in caplog.records if "non riconosciuto" in r.getMessage()]
    assert len(warnings) == 2                            # nessuna collisione da troncatura


def test_stesso_valore_un_solo_warning(caplog):
    """Regressione bloccata: l'anti-flood resta — lo STESSO valore avvisa una volta."""
    with caplog.at_level("WARNING"):
        for _ in range(5):
            name_mapping_store._warn_malformed("sport", "quidditch")

    warnings = [r for r in caplog.records if "quidditch" in r.getMessage()]
    assert len(warnings) == 1


def test_warn_concorrente_sotto_lock(caplog):
    """Il check-and-add è atomico sotto `_WARNED_LOCK` (come `source_manager`):
    N thread sullo stesso valore → al più un warning, nessuna eccezione."""
    assert isinstance(name_mapping_store._WARNED_LOCK, type(threading.Lock()))
    errori = []

    def _spara():
        try:
            for _ in range(50):
                name_mapping_store._warn_malformed("sport", "concorrente")
        except Exception as exc:                         # pragma: no cover
            errori.append(exc)

    with caplog.at_level("WARNING"):
        threads = [threading.Thread(target=_spara) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errori == []
    warnings = [r for r in caplog.records if "concorrente" in r.getMessage()]
    assert len(warnings) == 1
