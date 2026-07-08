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
