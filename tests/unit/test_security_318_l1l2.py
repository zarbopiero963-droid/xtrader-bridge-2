"""Test hard #318 — L2-2 (`_is_placeholder` permissivo).

Esercitano il codice reale:
- L2-2: `value_maps._is_placeholder` usa ora `or` (non `and`): un placeholder PARZIALE/troncato
  è comunque escluso dalla value-map (fail-closed).

Nota (P3-15 #76): i test L1-4 (anti-ReDoS del parser P.Bet hardcoded) vivevano in questo
file e sono stati RIMOSSI insieme al modulo `xtrader_bridge/parser.py` (decisione del
proprietario: rimozione, il modulo era fuori dal flusso live da CP-09b). La guardia
anti-reintroduzione è in `tests/unit/test_pbet_removed_76.py`.
"""

from xtrader_bridge import value_maps as vm


# ── L2-2: `_is_placeholder` fail-closed (`or`, non `and`) ──────────────────────

def test_is_placeholder_riconosce_anche_i_parziali():
    assert vm._is_placeholder("{HOME_TEAM}") is True    # completo
    assert vm._is_placeholder("{HOME_TEAM") is True     # troncato: manca `}` → ora RICONOSCIUTO
    assert vm._is_placeholder("HOME_TEAM}") is True      # manca `{` → riconosciuto
    assert vm._is_placeholder("Milan") is False          # valore reale
    assert vm._is_placeholder("") is False
    assert vm._is_placeholder(None) is False


def test_value_map_esclude_placeholder_parziale():
    # Un valore col placeholder PARZIALE non deve entrare nella value-map come valore reale.
    m = vm.value_map_from_pairs([("gg", "Goal/Goal"), ("bad", "{HOME_TEAM"), ("ok", "Milan")])
    assert m.get("gg") == "Goal/Goal"
    assert m.get("ok") == "Milan"
    # `value_map_from_pairs` non filtra i placeholder (lo fa il chiamante via `_is_placeholder`):
    # qui verifichiamo che, filtrando come in produzione, il parziale sparisce.
    pairs = [("gg", "Goal/Goal"), ("bad", "{HOME_TEAM"), ("ok", "Milan")]
    filtered = vm.value_map_from_pairs([(a, v) for a, v in pairs if not vm._is_placeholder(v)])
    assert "bad" not in filtered and filtered.get("gg") == "Goal/Goal"
