"""Test del validatore segnale (PR-10): prezzo, BetType e campi-nome."""

from xtrader_bridge import validator
from xtrader_bridge.csv_writer import CSV_HEADER


def _row(**over):
    """Riga CSV valida di base (NAME_ONLY + prezzo + lato), sovrascrivibile."""
    row = {k: "" for k in CSV_HEADER}
    row.update({
        "Provider": "PBet",
        "EventName": "Inter v Milan",
        "MarketType": "OVER_UNDER_25",
        "MarketName": "Over/Under 2,5 gol",
        "SelectionName": "Over 2,5 goal",
        "Handicap": "0",
        "Price": "1.85",
        "BetType": "PUNTA",
        "Points": "",
    })
    row.update(over)
    return row


def test_riga_completa_valida():
    assert validator.validate(_row(), "NAME_ONLY") == (validator.VALID, None)
    assert validator.is_valid(_row(), "NAME_ONLY") is True


def test_prezzo_mancante_bloccato():
    status, _ = validator.validate(_row(Price=""), "NAME_ONLY")
    assert status == validator.INVALID_MISSING_PRICE


def test_prezzo_uno_punto_zero_non_valido():
    # 1.00 non è una quota piazzabile (nessun guadagno).
    assert validator.validate(_row(Price="1.00"), "NAME_ONLY")[0] == validator.INVALID_PRICE
    assert validator.validate(_row(Price="1,00"), "NAME_ONLY")[0] == validator.INVALID_PRICE
    # 0,5 (linea) non è una quota.
    assert validator.validate(_row(Price="0.5"), "NAME_ONLY")[0] == validator.INVALID_PRICE


def test_prezzo_non_numerico_non_valido():
    assert validator.validate(_row(Price="abc"), "NAME_ONLY")[0] == validator.INVALID_PRICE


def test_prezzo_valido_appena_sopra_uno():
    assert validator.is_valid(_row(Price="1.01"), "NAME_ONLY") is True


def test_require_price_disattivabile():
    # Con require_price=False una riga senza prezzo (ma riconoscibile) passa.
    assert validator.is_valid(_row(Price=""), "NAME_ONLY", require_price=False) is True


def test_bettype_sconosciuto_bloccato():
    status, detail = validator.validate(_row(BetType="BACK"), "NAME_ONLY")
    assert status == validator.INVALID_BETTYPE
    assert detail == "BACK"
    assert validator.is_valid(_row(BetType="BANCA"), "NAME_ONLY") is True


def test_campi_nome_mancanti_bloccati():
    status, detail = validator.validate(_row(SelectionName=""), "NAME_ONLY")
    assert status == validator.INVALID_MISSING_FIELDS
    assert "SelectionName" in detail


def test_require_price_enabled_solo_false_disattiva():
    # Solo il booleano False disattiva il gate; tutto il resto = default sicuro True.
    assert validator.require_price_enabled({}) is True
    assert validator.require_price_enabled({"require_price": True}) is True
    assert validator.require_price_enabled({"require_price": False}) is False
    # Valori malformati (config editata a mano / migrazione) → richiedi prezzo.
    assert validator.require_price_enabled({"require_price": None}) is True
    assert validator.require_price_enabled({"require_price": 0}) is True
    assert validator.require_price_enabled({"require_price": ""}) is True
    assert validator.require_price_enabled({"require_price": "false"}) is True


def test_points_resta_vuoto_non_normalizzato():
    # Il validatore non tocca Points: resta vuoto (default del contratto).
    row = _row()
    validator.validate(row, "NAME_ONLY")
    assert row["Points"] == ""
