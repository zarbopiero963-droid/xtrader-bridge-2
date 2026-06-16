"""Test hard del contratto CSV XTrader (PR-01).

Esercita le funzioni reali di `main.py` (`CSV_HEADER`, `build_csv_row`).
`main.py` importa `customtkinter` a livello di modulo: se la libreria GUI non è
installata nell'ambiente di test, qui ne forniamo uno stub minimo così che i test
restino eseguibili senza GUI e senza token Telegram. Il runner pytest e la CI sono
configurati in PR-02.
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


CONTRACT_HEADER = [
    "Provider", "SelectionId", "MarketId", "SelectionName", "MarketName",
    "EventName", "MarketType", "BetType", "Price", "MinPrice", "MaxPrice",
    "Points",
]


def test_header_matches_contract():
    main = _import_main()
    assert main.CSV_HEADER == CONTRACT_HEADER


def test_points_is_last_column():
    main = _import_main()
    assert main.CSV_HEADER[-1] == "Points"


def test_header_has_no_stake_or_timestamp():
    main = _import_main()
    assert "Stake" not in main.CSV_HEADER
    assert "Timestamp" not in main.CSV_HEADER


def test_build_csv_row_emits_points_default():
    main = _import_main()
    parsed = {
        "signal_type": "MATCH ODDS", "competition": "Serie A",
        "teams": "Inter v Milan", "score": "1 - 0", "time_": "67m",
        "quota": "1.85", "probability": "72.5", "bet_type": "BACK",
    }
    row = main.build_csv_row(parsed, "PBet")
    assert row["Points"] == main.DEFAULT_POINTS == "1"


def test_build_csv_row_keys_match_header():
    main = _import_main()
    parsed = {
        "signal_type": "OVER 2.5", "competition": "", "teams": "A v B",
        "score": "", "time_": "", "quota": "2,10", "probability": "",
        "bet_type": "BACK",
    }
    row = main.build_csv_row(parsed, "PBet")
    assert sorted(row.keys()) == sorted(CONTRACT_HEADER)


def test_bettype_default_is_back_or_lay():
    main = _import_main()
    row = main.build_csv_row({
        "signal_type": "MATCH ODDS", "teams": "A v B", "quota": "1.5",
        "bet_type": "BACK",
    }, "PBet")
    assert row["BetType"] in ("BACK", "LAY")


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
