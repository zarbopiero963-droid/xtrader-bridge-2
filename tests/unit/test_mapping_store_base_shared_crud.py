"""Store refactor #114 — LOCK del CRUD condiviso (`mapping_store_base.make_profile_crud`).

`name_mapping_store` e `market_mapping_store` condividono ora le dieci funzioni CRUD via
`mapping_store_base`, iniettando le proprie tre differenze (chiave di config, `_clean_entry`,
prefisso di log). Questi test — parametrizzati sui DUE store, come `test_store_lookup_guards_76`
— blindano l'estrazione contro un mis-wire silenzioso (safety-critical: un profilo scritto sotto
la chiave sbagliata, o validato con lo schema dell'altro store, = mappatura persa → riga CSV
sbagliata o non riconosciuta):

- ogni store scrive/legge SOTTO LA PROPRIA chiave (`name_mappings` / `market_mappings`), mai
  quella dell'altro (store_key iniettato correttamente);
- ogni store usa il PROPRIO `_clean_entry` (schema nomi vs schema mercati): una riga valida per
  uno store NON è accettata dall'altro (clean_entry non scambiato);
- le funzioni di modifica ritornano una COPIA (config originale intatta: invariante di purezza).
"""

import pytest

from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import name_mapping_store as nms

# (modulo store, chiave di config attesa, riga VALIDA per QUEL store, riga valida per l'ALTRO store)
_NAME_ENTRY = {"betfair": "Liverpool", "provider": "Liverpool FC"}
_MARKET_ENTRY = {"phrase": "Over 2.5", "market_name": "Over/Under 2.5", "selection_name": "Over 2.5"}

_CASES = [
    pytest.param(nms, "name_mappings", _NAME_ENTRY, _MARKET_ENTRY, id="name_store"),
    pytest.param(mms, "market_mappings", _MARKET_ENTRY, _NAME_ENTRY, id="market_store"),
]


@pytest.mark.parametrize("store, store_key, own_entry, other_entry", _CASES)
def test_set_entries_scrive_sotto_la_propria_chiave(store, store_key, own_entry, other_entry):
    """`set_entries` deve scrivere SOTTO `store_key` del proprio store (store_key iniettato giusto),
    e non sotto la chiave dell'altro store."""
    other_key = "market_mappings" if store_key == "name_mappings" else "name_mappings"
    out = store.set_entries({}, "Profilo", [own_entry])
    assert store_key in out and out[store_key].get("Profilo")
    assert other_key not in out


@pytest.mark.parametrize("store, store_key, own_entry, other_entry", _CASES)
def test_get_entries_roundtrip_con_clean_entry_proprio(store, store_key, own_entry, other_entry):
    """Una riga VALIDA per lo store fa round-trip (set→get); una riga valida SOLO per l'ALTRO store
    (schema diverso) viene SCARTATA dal `_clean_entry` di questo store → prova che ogni store usa il
    proprio `_clean_entry`, non quello dell'altro."""
    cfg = store.set_entries({}, "P", [own_entry])
    assert store.get_entries(cfg, "P"), "la riga valida del proprio store deve sopravvivere"
    cfg2 = store.set_entries({}, "P", [other_entry])
    assert store.get_entries(cfg2, "P") == [], "una riga dello schema dell'altro store va scartata"


@pytest.mark.parametrize("store, store_key, own_entry, other_entry", _CASES)
def test_crud_non_muta_la_config_originale(store, store_key, own_entry, other_entry):
    """Invariante di purezza: `set_entries`/`add_profile`/`delete_profile`/`rename_profile`
    ritornano una COPIA — la config passata non viene mai mutata."""
    base = {store_key: {"Esistente": [own_entry]}}
    import copy
    snapshot = copy.deepcopy(base)
    store.set_entries(base, "Nuovo", [own_entry])
    store.add_profile(base, "Altro")
    store.delete_profile(base, "Esistente")
    store.rename_profile(base, "Esistente", "Rinominato")
    assert base == snapshot, "la config originale è stata mutata da un'operazione CRUD"


@pytest.mark.parametrize("store, store_key, own_entry, other_entry", _CASES)
def test_store_legge_solo_la_propria_sezione(store, store_key, own_entry, other_entry):
    """`_store` del factory legge SOLO la sezione dello store giusto: dati sotto la chiave
    dell'altro store non compaiono nei profili di questo."""
    other_key = "market_mappings" if store_key == "name_mappings" else "name_mappings"
    cfg = {other_key: {"AltroProfilo": [own_entry]}}
    assert store.profile_names(cfg) == []
    assert store._store(cfg) == {}


def test_i_due_store_restano_indipendenti():
    """Scrivere sullo store nomi non tocca lo store mercati e viceversa (chiavi distinte)."""
    cfg = nms.set_entries({}, "Nomi", [_NAME_ENTRY])
    cfg = mms.set_entries(cfg, "Mercati", [_MARKET_ENTRY])
    assert nms.profile_names(cfg) == ["Nomi"]
    assert mms.profile_names(cfg) == ["Mercati"]
    # rimuovere un profilo nomi non tocca i mercati
    cfg = nms.delete_profile(cfg, "Nomi")
    assert nms.profile_names(cfg) == [] and mms.profile_names(cfg) == ["Mercati"]
