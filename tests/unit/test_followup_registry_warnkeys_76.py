"""Follow-up post-audit #76 (blocco 1, approvato dal proprietario).

1) Nota Fable su PR #108: guardia difensiva sul RAMO DI FALLBACK di
   `custom_pipeline._default_registry` — se anche `registry(include_dizionario=False)`
   sollevasse (scenario teorico: i built-in non fanno I/O), l'eccezione tornava
   per-messaggio nell'handler Telegram. Ultimo-resort: registro VUOTO cacheato +
   error log (fail-closed: `value_maps.resolve` su registro vuoto ritorna sempre "").

2) Nota su PR #104: le chiavi di dedup dei warning usavano `hash()` (64 bit, salted)
   → una collisione teorica SOPPRIME il warning di un valore DIVERSO. Allineati
   `name_mapping_store._warn_malformed` e `source_manager._normalize_source` allo
   stesso pattern: digest sha256 del valore COMPLETO — memoria fissa (la proprietà
   per cui fu scelto `hash()`) e collisione praticamente impossibile, chiave
   deterministica tra processi.
"""

import hashlib

import pytest

from xtrader_bridge import custom_pipeline, name_mapping_store, source_manager, value_maps


@pytest.fixture(autouse=True)
def _stato_pulito():
    """Azzera cache registro e dedup warning attorno a ogni test (stato di modulo)."""
    custom_pipeline._DEFAULT_REGISTRY = None
    name_mapping_store._reset_warnings()
    source_manager._reset_warnings()
    yield
    custom_pipeline._DEFAULT_REGISTRY = None
    name_mapping_store._reset_warnings()
    source_manager._reset_warnings()


# ── 1) ultimo-resort su fallback rotto ──────────────────────────────────────


def test_fallback_rotto_registro_vuoto_cacheato(monkeypatch, caplog):
    """FAIL-FIRST: pre-patch, se ANCHE il ramo built-in solleva, l'eccezione
    propaga per-messaggio. Post-patch: registro vuoto, CACHEATO, error log unico."""

    def _sempre_rotto(include_dizionario=False, rows=None):
        raise OSError("value_maps irrimediabilmente rotto")

    monkeypatch.setattr(custom_pipeline.value_maps, "registry", _sempre_rotto)

    with caplog.at_level("WARNING"):
        reg = custom_pipeline._default_registry()          # NON deve sollevare

    assert reg == {}                                       # ultimo-resort: vuoto
    # Contratto «errore unico» (review Sourcery PR #110): ESATTAMENTE un ERROR —
    # una regressione che logga doppio o degrada il livello deve fallire qui.
    assert sum(1 for r in caplog.records if r.levelname == "ERROR") == 1
    n_rec = len(caplog.records)
    assert custom_pipeline._default_registry() is reg      # cacheato: no retry-storm
    assert len(caplog.records) == n_rec                    # e nessun nuovo log


def test_fallback_rotto_pipeline_fail_closed(monkeypatch):
    """Col registro di ultimo-resort (vuoto) la pipeline NON solleva e NON piazza:
    una regola con value-map obbligatoria resta «Non pronto» (mai una riga col
    valore non tradotto)."""

    def _sempre_rotto(include_dizionario=False, rows=None):
        raise ValueError("rotto ovunque")

    monkeypatch.setattr(custom_pipeline.value_maps, "registry", _sempre_rotto)

    from xtrader_bridge import custom_parser as cp
    defn = cp.CustomParserDef(name="T", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="A v B", required=True),
        cp.FieldRule(target="MarketType", fixed_value="Risultato esatto",
                     required=True, value_map="markettype"),
        cp.FieldRule(target="SelectionName", fixed_value="1 - 0", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])

    res = custom_pipeline.build_validated_row(defn, "msg")   # non solleva

    assert res.placeable is False
    assert res.row.get("MarketType", "") == ""


def test_dizionario_rotto_ma_builtin_sani_resta_il_fallback_p314(monkeypatch, caplog):
    """Regressione P3-14 bloccata: se SOLO il ramo dizionario fallisce, il fallback
    resta il registro dei built-in (non il vuoto di ultimo-resort)."""
    vero_registry = value_maps.registry

    def _rotto_solo_dizionario(include_dizionario=False, rows=None):
        if include_dizionario:
            raise ValueError("header dizionario invalido")
        return vero_registry(include_dizionario=False, rows=rows)

    monkeypatch.setattr(custom_pipeline.value_maps, "registry", _rotto_solo_dizionario)

    with caplog.at_level("WARNING"):
        reg = custom_pipeline._default_registry()

    assert reg == vero_registry(include_dizionario=False)
    assert not any(r.levelname == "ERROR" for r in caplog.records)  # solo il warning P3-14


# ── 2) chiavi dedup warning: digest deterministico, non hash() salted ───────


def test_name_mapping_warn_key_digest_deterministico(caplog):
    """FAIL-FIRST (white-box): la chiave di dedup deve essere il digest sha256 del
    valore completo — deterministico e senza collisioni pratiche. Pre-patch il set
    conteneva `hash()` (int salted per processo): questo test fallisce se si torna
    a `hash()`."""
    with caplog.at_level("WARNING"):
        name_mapping_store._warn_malformed("enabled", "valore-malformato")

    atteso = hashlib.sha256(ascii("valore-malformato").encode(
        "utf-8", "backslashreplace")).hexdigest()
    assert ("enabled", atteso) in name_mapping_store._WARNED_MALFORMED
    assert len(caplog.records) == 1


def test_name_mapping_warn_comportamento_invariato(caplog):
    """Contratto invariato: stesso valore una sola volta, valori distinti con lo
    stesso prefisso di 57 char loggano ENTRAMBI (P3-19), cap rispettato."""
    lungo_a = "x" * 57 + "AAA"
    lungo_b = "x" * 57 + "BBB"
    with caplog.at_level("WARNING"):
        name_mapping_store._warn_malformed("enabled", lungo_a)
        name_mapping_store._warn_malformed("enabled", lungo_a)   # dedup
        name_mapping_store._warn_malformed("enabled", lungo_b)   # prefisso uguale → logga

    assert len(caplog.records) == 2


def test_source_manager_warn_key_digest_deterministico(caplog):
    """FAIL-FIRST (white-box): stesso allineamento in `source_manager` — chiavi
    digest, non `hash()`."""
    with caplog.at_level("WARNING"):
        source_manager._normalize_source({"chat_id": "-100123", "enabled": "boh"})

    def _dig(s):
        return hashlib.sha256(s.encode("utf-8", "backslashreplace")).hexdigest()

    assert (_dig("-100123"), _dig(ascii("boh"))) in source_manager._WARNED_ENABLED
    assert any("non riconosciuto" in r.getMessage() for r in caplog.records)


def test_source_manager_warn_comportamento_invariato(caplog):
    """Contratto invariato: stessa coppia chat+valore una volta sola; coppia diversa
    logga; `enabled` malformato resta coercito a False (fail-closed C7)."""
    with caplog.at_level("WARNING"):
        s1 = source_manager._normalize_source({"chat_id": "-1", "enabled": "boh"})
        source_manager._normalize_source({"chat_id": "-1", "enabled": "boh"})    # dedup
        source_manager._normalize_source({"chat_id": "-2", "enabled": "boh"})    # nuova chat

    assert s1["enabled"] is False
    assert len([r for r in caplog.records if "non riconosciuto" in r.getMessage()]) == 2
