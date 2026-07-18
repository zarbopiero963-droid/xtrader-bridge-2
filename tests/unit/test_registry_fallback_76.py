"""P3-14 audit #76 — `_default_registry` fail-safe su dizionario corrotto.

Bug: `custom_pipeline._default_registry()` costruiva il registro value-map con
`value_maps.registry(include_dizionario=True)` SENZA guardia: un dizionario bundled
corrotto/mancante (header invalido → `load_dizionario` solleva apposta) faceva
esplodere l'eccezione a OGNI messaggio dentro l'handler Telegram — outage silenzioso
del bridge (e col double-checked locking il fallimento non veniva mai cacheato:
retry-storm per messaggio).

Fix testato: fallback al registro dei SOLI built-in, messo IN CACHE, con warning che
spiega il rimedio. Fail-closed a valle: le mappe-dizionario assenti risolvono a ""
→ campo «Non pronto» → nessuna riga sbagliata nel CSV."""

import pytest

from xtrader_bridge import custom_pipeline, value_maps


@pytest.fixture(autouse=True)
def _registry_pulito():
    """Azzera la cache del registro attorno a ogni test (stato di modulo)."""
    custom_pipeline._DEFAULT_REGISTRY = None
    yield
    custom_pipeline._DEFAULT_REGISTRY = None


def test_dizionario_corrotto_fallback_builtin_con_warning(monkeypatch, caplog):
    """FAIL-FIRST: pre-patch l'eccezione propagava (a ogni messaggio nel live)."""
    vero_registry = value_maps.registry

    def _rotto(include_dizionario=False, rows=None):
        if include_dizionario:
            raise ValueError("Dizionario XTrader con header non valido")
        return vero_registry(include_dizionario=False, rows=rows)

    monkeypatch.setattr(custom_pipeline.value_maps, "registry", _rotto)

    with caplog.at_level("WARNING"):
        reg = custom_pipeline._default_registry()          # NON deve sollevare

    assert reg == vero_registry(include_dizionario=False)  # i built-in ci sono tutti
    assert any("FALLBACK" in r.getMessage() for r in caplog.records)
    # In CACHE: la seconda chiamata non ricostruisce (niente retry-storm) e non logga di nuovo.
    n_warn = len(caplog.records)
    assert custom_pipeline._default_registry() is reg
    assert len(caplog.records) == n_warn


def test_dizionario_sano_comportamento_invariato():
    """Regressione bloccata: col dizionario reale il registro COMPLETO carica come
    prima (built-in + mappe-dizionario) e resta cacheato (A8)."""
    reg = custom_pipeline._default_registry()

    assert set(value_maps.registry(include_dizionario=False)) <= set(reg)
    assert len(reg) > len(value_maps.registry(include_dizionario=False))
    assert custom_pipeline._default_registry() is reg


def test_pipeline_sopravvive_al_dizionario_rotto(monkeypatch):
    """End-to-end del percorso live (P3-14): con il registro in fallback,
    `build_validated_row` NON solleva — il messaggio viene al più scartato
    (fail-closed), mai un crash per-messaggio dell'handler."""
    vero_registry = value_maps.registry

    def _rotto(include_dizionario=False, rows=None):
        if include_dizionario:
            raise OSError("dizionario mancante")
        return vero_registry(include_dizionario=False, rows=rows)

    monkeypatch.setattr(custom_pipeline.value_maps, "registry", _rotto)

    from xtrader_bridge import custom_parser as cp
    defn = cp.CustomParserDef(name="T", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="A v B", required=True),
        cp.FieldRule(target="MarketType", fixed_value="CORRECT_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="1 - 0", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])

    res = custom_pipeline.build_validated_row(defn, "msg qualsiasi")   # non solleva

    assert res.status is not None                          # esito regolare, mai crash
