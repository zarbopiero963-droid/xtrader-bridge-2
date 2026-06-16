"""Test hard del contratto CSV XTrader (PR-01).

Esercita le funzioni reali di `main.py` (`CSV_HEADER`, `build_csv_row`).
`main.py` importa `customtkinter` a livello di modulo: se la libreria GUI non è
installata nell'ambiente di test, qui ne forniamo uno stub minimo così che i test
restino eseguibili senza GUI e senza token Telegram. Il runner pytest e la CI sono
configurati in PR-02.

Il contratto a 14 colonne è basato sui CSV di esempio reali forniti dal team XTrader.
`CONTRACT_HEADER` è volutamente un letterale indipendente da `main.CSV_HEADER`: è la
guardia che fa fallire il test se l'header di produzione cambia per errore.
"""

import os
import sys
import types

# Rendi importabile main.py (sta nella root del repo, un livello sopra tests/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _import_main():
    """Importa main.py stubbando la GUI se customtkinter non è disponibile."""
    if "customtkinter" not in sys.modules:
        try:
            import customtkinter  # noqa: F401
        except Exception:
            stub = types.ModuleType("customtkinter")
            stub.set_appearance_mode = lambda *a, **k: None
            stub.set_default_color_theme = lambda *a, **k: None
            stub.CTk = type("CTk", (), {})
            stub.CTkFont = lambda *a, **k: None
            sys.modules["customtkinter"] = stub
    import main
    return main


# Contratto ufficiale a 14 colonne (vedi docs/xtrader_csv_contract.md).
CONTRACT_HEADER = [
    "Provider", "EventId", "EventName", "MarketId", "MarketName",
    "MarketType", "SelectionId", "SelectionName", "Handicap", "Price",
    "MinPrice", "MaxPrice", "BetType", "Points",
]


def _row(**overrides):
    main = _import_main()
    parsed = {
        "signal_type": "MATCH ODDS", "competition": "Serie A",
        "teams": "Inter v Milan", "score": "1 - 0", "time_": "67m",
        "quota": "1.85", "probability": "72.5", "bet_type": "BACK",
    }
    parsed.update(overrides)
    return main.build_csv_row(parsed, "PBet")


def test_header_matches_contract_in_order():
    main = _import_main()
    assert main.CSV_HEADER == CONTRACT_HEADER


def test_header_has_14_columns():
    main = _import_main()
    assert len(main.CSV_HEADER) == 14


def test_header_has_no_stake_or_timestamp():
    main = _import_main()
    assert "Stake" not in main.CSV_HEADER
    assert "Timestamp" not in main.CSV_HEADER


def test_id_columns_present():
    main = _import_main()
    for col in ("EventId", "MarketId", "SelectionId", "Handicap"):
        assert col in main.CSV_HEADER


def test_build_csv_row_keys_match_header_order():
    # Assert order-sensitive: cattura regressioni nell'ordine delle colonne.
    main = _import_main()
    row = _row()
    assert list(row.keys()) == CONTRACT_HEADER


def test_bettype_back_maps_to_punta():
    row = _row(bet_type="BACK")
    assert row["BetType"] == "PUNTA"


def test_bettype_lay_maps_to_banca():
    row = _row(bet_type="LAY")
    assert row["BetType"] == "BANCA"


def test_points_is_empty_by_default():
    main = _import_main()
    assert _row()["Points"] == main.DEFAULT_POINTS == ""


def test_handicap_default_is_zero():
    assert _row()["Handicap"] == "0"


def test_ids_empty_when_absent_from_signal():
    row = _row()
    assert row["EventId"] == "" and row["MarketId"] == "" and row["SelectionId"] == ""


if __name__ == "__main__":
    # Esecuzione standalone (senza pytest): lancia tutti i test_* e riporta l'esito.
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(funcs) - failed}/{len(funcs)} passed")
    sys.exit(1 if failed else 0)
