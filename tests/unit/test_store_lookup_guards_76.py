"""P3-20 + P3-22 audit #76 — guardie sui lookup degli store di mappatura.

- **P3-20**: `market_mapping_store._canonical_market` risolveva il MarketName col
  PRIMO match normalizzato sul catalogo: se in futuro due nomi normalizzati-uguali
  finissero sotto MarketType DIVERSI, sceglierebbe in silenzio un mercato — e il CSV
  punterebbe un mercato potenzialmente sbagliato (oggi 0 duplicati: rischio futuro,
  guardia preventiva fail-closed).
- **P3-22**: `_find_store_key` (name + market store) ritornava la PRIMA chiave
  collidente: con doppioni normalizzati-uguali da config manomessa («Prof» e
  « Prof ») un profilo faceva shadowing silenzioso dell'altro.

Funzioni REALI con catalogo iniettato (`rows=`, purezza) e store-dict reali."""

import pytest

from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import name_mapping_store as nms


def _row(mtype, mname, sel):
    return {"MarketType_XTrader": mtype, "MarketName_XTrader": mname,
            "SelectionRole": "", "SelectionName_XTrader": sel,
            "Linea": "", "Handicap": "", "BetType_XTrader": "", "Lingua": ""}


# ── P3-20: ambiguità MarketName → fail-closed ────────────────────────────────────────

def test_marketname_ambiguo_su_tipi_diversi_rifiutato(caplog):
    """FAIL-FIRST: pre-patch il primo-match risolveva in silenzio uno dei due tipi."""
    rows = [_row("TIPO_A", "Mercato X", "Sel A"),
            _row("TIPO_B", "mercato  x", "Sel B")]        # normalizzati-uguali, tipi diversi

    with caplog.at_level("WARNING"):
        out = mms._canonical_market("Mercato X", "Sel A", rows=rows)

    assert out is None                                    # fail-closed: nessuna risoluzione
    assert any("AMBIGUO" in r.getMessage() for r in caplog.records)


def test_marketname_duplicato_stesso_tipo_risolve():
    """Regressione bloccata: duplicati INNOCUI (stesso MarketType) risolvono come prima."""
    rows = [_row("TIPO_A", "Mercato X", "Sel A"),
            _row("TIPO_A", "mercato  x", "Sel A")]

    out = mms._canonical_market("mercato x", "Sel A", rows=rows)

    assert out is not None
    assert out["market_type"] == "TIPO_A"
    assert out["selection_name"] == "Sel A"               # valore CANONICO del catalogo


def test_marketname_unico_risolve_canonico():
    """Regressione bloccata: il caso normale (catalogo senza duplicati) è invariato,
    coi valori canonici del catalogo (non quelli grezzi del config)."""
    rows = [_row("TIPO_A", "Mercato X", "Sel A")]

    out = mms._canonical_market("  MERCATO x ", "sel a", rows=rows)

    assert out == {"market_type": "TIPO_A", "market_name": "Mercato X",
                   "selection_name": "Sel A"}


# ── P3-22: doppioni normalizzati → match esatto, niente shadowing ────────────────────

@pytest.mark.parametrize("store_mod", [nms, mms], ids=["nomi", "mercati"])
def test_doppioni_il_match_esatto_vince(store_mod, caplog):
    """FAIL-FIRST (name store): pre-patch vinceva la PRIMA chiave collidente
    nell'ordine del dict — con « Prof » inserito prima, «Prof» era shadowato."""
    store = {" Prof ": ["righe-del-doppione"], "Prof": ["righe-vere"]}

    with caplog.at_level("WARNING"):
        key = store_mod._find_store_key(store, "Prof")

    assert key == "Prof"                                  # il nome ESATTO vince
    assert any("DUPLICATI" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("store_mod", [nms, mms], ids=["nomi", "mercati"])
def test_doppioni_senza_esatto_primo_deterministico(store_mod):
    """Senza un match esatto tra i doppioni si ripiega sul primo (compatibilità:
    il profilo resta raggiungibile), col warning già coperto sopra.
    NB: la normalizzazione profili è SOLO-strip (case-sensitive), quindi i doppioni
    differiscono per soli spazi."""
    store = {" Prof ": ["a"], "Prof  ": ["b"]}

    assert store_mod._find_store_key(store, "Prof") == " Prof "


@pytest.mark.parametrize("store_mod", [nms, mms], ids=["nomi", "mercati"])
def test_chiave_singola_legacy_ancora_trovata(store_mod):
    """Regressione bloccata (audit L1): il profilo legacy salvato con spazi attorno
    resta raggiungibile dal nome pulito — nessun warning."""
    store = {" Vecchio Profilo ": ["righe"]}

    assert store_mod._find_store_key(store, "Vecchio Profilo") == " Vecchio Profilo "
    assert store_mod._find_store_key(store, "inesistente") is None
