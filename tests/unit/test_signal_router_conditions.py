"""Integrazione (PR-1): le CONDIZIONI di gate filtrano il parser nel router LIVE.

Prova end-to-end su `signal_router.resolve_row`: un parser attivo per la chat scatta solo se il
messaggio soddisfa le sue condizioni, altrimenti il messaggio è scartato (`NO_CONTENT_MATCH`) —
niente riga CSV. La `fixture_message` è `"Match: Inter v Milan\\nEsito: GG\\nQuota: 1,85\\nLato: BACK"`.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_io, signal_router


def _save(dir_path, name, conditions=None, mode="all"):
    defn = parser_io.example_parser()
    defn.name = name
    defn.conditions = list(conditions or [])
    defn.conditions_mode = mode
    return cp.save_parser(defn, dir_path)


def _cfg(name):
    return {"provider": "TG", "active_parser": name, "chat_id": "42",
            "recognition_mode": "NAME_ONLY"}


def test_condizione_soddisfatta_produce_riga(tmp_path):
    _save(str(tmp_path), "Cond", [cp.Condition(text="GG")])          # la fixture contiene "GG"
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg("Cond"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True


def test_condizione_non_soddisfatta_scarta(tmp_path):
    # La fixture NON contiene "OVER SUCCESSIVO" → il parser non scatta (gate condizioni).
    _save(str(tmp_path), "Cond", [cp.Condition(text="OVER SUCCESSIVO")])
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg("Cond"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.status == signal_router.NO_CONTENT_MATCH
    assert res.placeable is False


def test_non_contiene_scarta_quando_il_testo_e_presente(tmp_path):
    # «NON contiene BACK» ma la fixture contiene "BACK" → gate fallisce → scartato.
    _save(str(tmp_path), "Cond", [cp.Condition(text="BACK", negate=True)])
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg("Cond"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.status == signal_router.NO_CONTENT_MATCH
    assert res.placeable is False


def test_modo_any_una_condizione_basta(tmp_path):
    # "GG" c'è, "OVER SUCCESSIVO" no: in modo ANY basta una → scatta.
    _save(str(tmp_path), "Cond",
          [cp.Condition(text="OVER SUCCESSIVO"), cp.Condition(text="GG")], mode="any")
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg("Cond"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True


def _save_multi(dir_path, name, conditions=None, mode="all"):
    """Come `_save` ma con OUTPUT MULTI-RIGA attivo (due mercati): serve a provare che il gate
    condizioni vale anche sul percorso multi (#192), zona a rischio doppia-scommessa."""
    defn = parser_io.example_parser()
    defn.name = name
    defn.multi_market_enabled = True
    defn.multi_markets = [
        cp.MultiRowRule(market_type="OVER_UNDER_25", market_name="Over/Under 2.5",
                        selection_name="Over 2.5"),
        cp.MultiRowRule(market_type="OVER_UNDER_15", market_name="Over/Under 1.5",
                        selection_name="Over 1.5"),
    ]
    defn.conditions = list(conditions or [])
    defn.conditions_mode = mode
    return cp.save_parser(defn, dir_path)


def test_multi_riga_rispetta_il_gate_condizioni(tmp_path):
    # Fable #390 (zona doppia-scommessa): un parser MULTI-RIGA con condizioni NON soddisfatte
    # deve dare NO_CONTENT_MATCH e ZERO righe. Il gate (matches_message) è valutato per
    # l'INTERO messaggio in signal_router.resolve_row PRIMA di restituire le righe multi: se
    # un domani il percorso multi lo aggirasse, questo test fallirebbe.
    _save_multi(str(tmp_path), "MultiCond", [cp.Condition(text="ZZZ_ASSENTE")])
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg("MultiCond"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.status == signal_router.NO_CONTENT_MATCH
    assert res.placeable is False
    assert res.all_rows() == []                      # nessuna riga generata, gate rispettato


def test_multi_riga_con_condizione_soddisfatta_genera_le_righe(tmp_path):
    # Controprova: condizione soddisfatta ("GG" è nella fixture) → il parser multi scatta e
    # genera le sue righe (il gate non blocca quando le condizioni valgono).
    _save_multi(str(tmp_path), "MultiCond", [cp.Condition(text="GG")])
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg("MultiCond"),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert len(res.all_rows()) == 2                  # due mercati multi generati
