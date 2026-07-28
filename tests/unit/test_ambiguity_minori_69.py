"""Guard delle ambiguità minori — voci M1, M3, M4 della #69.

Tre nomi che rispondevano a domande diverse con la stessa faccia:

- **M1** — `resolve` esisteva in due moduli: `mapping.resolve(market_alias, selection_alias, …)`
  risolveva una **coppia di alias in una selezione XTrader**, `value_maps.resolve(value, map_name)`
  traduceva **un singolo valore**. Un import sbagliato non dava errore: dava un risultato sbagliato.
  Ora `mapping.resolve_selection` e `value_maps.map_value`.
- **M3** — `load_active` (parser **primario**) vs `load_active_list` (**tutti** i parser della
  chat): usare il primo dove serviva il secondo ignorava **in silenzio** i parser secondari, cioè
  perdeva segnali senza dirlo. Ora `load_primary_parser` e `load_all_parsers`.
- **M4** — `market_name_for_type` confrontava in modo **esatto** mentre lo speculare
  `market_type_for_name` usava `_norm` (case/space-insensitive): due funzioni gemelle con criteri
  diversi. Ora simmetriche.

Come per gli altri guard della #69, questi test non ri-verificano cosa fanno le funzioni (è già
coperto altrove): fissano che i **nomi ambigui non tornino** e che la **simmetria** resti.
"""

import pytest

from xtrader_bridge import dizionario, mapping, parser_manager, value_maps


# ── M1: due `resolve` per due domande diverse ────────────────────────────────────────────────────
def test_i_due_resolve_ambigui_non_esistono_piu():
    assert not hasattr(mapping, "resolve"), \
        "reintrodotto `mapping.resolve`: collideva con `value_maps.resolve` — usa `resolve_selection`"
    assert not hasattr(value_maps, "resolve"), \
        "reintrodotto `value_maps.resolve`: collideva con `mapping.resolve` — usa `map_value`"
    assert callable(mapping.resolve_selection) and callable(value_maps.map_value)


def test_i_due_nomi_nuovi_fanno_cose_diverse():
    """La prova che servivano due nomi: firme e risultati non sono intercambiabili.

    `resolve_selection` prende una **coppia** di alias e ritorna un **dict** (la selezione
    completa); `map_value` prende **un valore** e ritorna una **stringa**."""
    selezione = mapping.resolve_selection("esito_finale", "1", home="Inter", away="Milan")
    assert isinstance(selezione, dict) and "SelectionName" in selezione

    tradotto = value_maps.map_value("BACK", "bettype")
    assert isinstance(tradotto, str)


# ── M3: parser primario ≠ tutti i parser ────────────────────────────────────────────────────────
def test_i_nomi_load_active_non_esistono_piu():
    assert not hasattr(parser_manager, "load_active"), \
        "reintrodotto `load_active`: non diceva «primario» — usa `load_primary_parser`"
    assert not hasattr(parser_manager, "load_active_list"), \
        "reintrodotto `load_active_list`: usa `load_all_parsers`"
    assert callable(parser_manager.load_primary_parser)
    assert callable(parser_manager.load_all_parsers)


def test_primario_e_tutti_restano_distinti(tmp_path):
    """Il primario è **uno**, `load_all_parsers` li dà **tutti**: è la differenza che rendeva
    pericoloso confonderli — chi usava il primario dove servivano tutti perdeva i parser
    secondari della chat, e quindi dei segnali, senza alcun errore."""
    from xtrader_bridge import custom_parser, parser_io
    for nome in ("primo", "secondo"):
        defn = parser_io.example_parser()
        defn.name = nome
        custom_parser.save_parser(defn, str(tmp_path))

    cfg = {"parser_list_by_chat": {"123": ["primo", "secondo"]}}
    primario = parser_manager.load_primary_parser(cfg, "123", str(tmp_path))
    tutti = parser_manager.load_all_parsers(cfg, "123", str(tmp_path))

    assert primario is not None and primario.name == "primo"
    assert [d.name for d in tutti] == ["primo", "secondo"]
    assert len(tutti) > 1, "il caso interessante è proprio quando i parser sono più di uno"


# ── M4: le due funzioni gemelle del dizionario devono normalizzare allo stesso modo ──────────────
@pytest.mark.parametrize("scritto_male", ["match_odds", "  MATCH_ODDS  ", "Match_Odds"])
def test_market_name_for_type_e_case_insensitive_come_il_gemello(scritto_male):
    """Simmetria: se `market_type_for_name` tollera maiuscole e spazi, deve farlo anche
    `market_name_for_type`. Prima uno dei due rispondeva `None` — «non nel dizionario» — a una
    domanda a cui l'altro rispondeva correttamente."""
    atteso = dizionario.market_name_for_type("MATCH_ODDS")
    assert atteso, "il fixture presuppone che MATCH_ODDS esista nel dizionario"
    assert dizionario.market_name_for_type(scritto_male) == atteso


def test_le_due_direzioni_sono_reciproche():
    """Andata e ritorno: dal tipo al nome e dal nome al tipo si torna al punto di partenza,
    anche partendo da una grafia sciatta."""
    nome = dizionario.market_name_for_type("match_odds")
    assert nome
    assert dizionario.market_type_for_name(nome) == "MATCH_ODDS"
    assert dizionario.market_type_for_name(f"  {nome.lower()}  ") == "MATCH_ODDS"


def test_market_name_for_type_resta_fail_closed_su_ignoto():
    """La tolleranza è sulla GRAFIA, non sul contenuto: un mercato inesistente resta `None`."""
    assert dizionario.market_name_for_type("NON_ESISTE") is None
    assert dizionario.market_name_for_type("") is None
    assert dizionario.market_name_for_type(None) is None
