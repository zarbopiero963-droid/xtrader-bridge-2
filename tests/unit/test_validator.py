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
    # Con require_price=False una riga senza prezzo (ma riconoscibile) passa. A runtime
    # questo flag è guidato dalla riga Price del parser (CustomParserDef.price_required).
    assert validator.is_valid(_row(Price=""), "NAME_ONLY", require_price=False) is True
    # Con require_price=True (Price obbligatorio nel parser) una riga senza prezzo è scartata.
    assert validator.is_valid(_row(Price=""), "NAME_ONLY", require_price=True) is False


def test_bettype_sconosciuto_bloccato():
    status, detail = validator.validate(_row(BetType="BACK"), "NAME_ONLY")
    assert status == validator.INVALID_BETTYPE
    assert detail == "BACK"
    assert validator.is_valid(_row(BetType="BANCA"), "NAME_ONLY") is True


def test_campi_nome_mancanti_bloccati():
    status, detail = validator.validate(_row(SelectionName=""), "NAME_ONLY")
    assert status == validator.INVALID_MISSING_FIELDS
    assert "SelectionName" in detail




def test_points_resta_vuoto_non_normalizzato():
    # Il validatore non tocca Points: resta vuoto (default del contratto).
    row = _row()
    validator.validate(row, "NAME_ONLY")
    assert row["Points"] == ""


def test_points_valorizzato_malformato_bloccato():
    """#17 (Codex P2): Points è un moltiplicatore stake; se valorizzato da un parser custom
    deve essere un numero POSITIVO. Testo non numerico ("abc"), negativo ("-5") o zero ("0")
    NON deve raggiungere XTrader (il percorso hardcoded lo lascia vuoto).

    Fail-first: prima il validatore non ispezionava Points → VALID/placeable con Points sporco."""
    for bad in ("abc", "-5", "0", "0.0", "inf", "1e2", "1.2.3"):
        assert validator.validate(_row(Points=bad), "NAME_ONLY")[0] == validator.INVALID_POINTS, bad
    # valori positivi validi restano accettati (nessuna regressione: "3" è usato dai test esistenti)
    for ok in ("1", "2", "3", "0.5", "1,5"):
        assert validator.is_valid(_row(Points=ok), "NAME_ONLY") is True, ok
    # Points vuoto resta valido (default del contratto)
    assert validator.is_valid(_row(Points=""), "NAME_ONLY") is True


def test_minprice_maggiore_di_maxprice_bloccato():
    """#17 (Codex P2): limiti di prezzo incoerenti — MinPrice > MaxPrice — non sono usabili da
    XTrader e vanno scartati anche se ogni singolo limite è una quota valida.

    Fail-first: prima il validatore controllava i limiti solo singolarmente, non la relazione."""
    status, _ = validator.validate(_row(Price="2.0", MinPrice="3.0", MaxPrice="1.5"), "NAME_ONLY")
    assert status == validator.INVALID_PRICE_BOUNDS


def test_bounds_che_escludono_price_bloccati():
    """#17 (Codex P2): un intervallo Min/Max che ESCLUDE la quota selezionata (MinPrice > Price
    o MaxPrice < Price) è contraddittorio → scartato. Bordi inclusivi (Min==Price / Max==Price)
    e un intervallo che contiene Price restano validi.

    Fail-first: prima ogni limite era valido singolarmente → VALID con intervallo incoerente."""
    # MinPrice > Price
    assert validator.validate(_row(Price="2.0", MinPrice="3.0"), "NAME_ONLY")[0] == \
        validator.INVALID_PRICE_BOUNDS
    # MaxPrice < Price
    assert validator.validate(_row(Price="2.0", MaxPrice="1.5"), "NAME_ONLY")[0] == \
        validator.INVALID_PRICE_BOUNDS
    # intervallo coerente che contiene Price → valido
    assert validator.is_valid(_row(Price="2.0", MinPrice="1.5", MaxPrice="3.0"), "NAME_ONLY") is True
    # bordi inclusivi → validi
    assert validator.is_valid(_row(Price="2.0", MinPrice="2.0", MaxPrice="2.0"), "NAME_ONLY") is True
    # con virgola come separatore (normalizzato a monte, ma il validatore accetta comunque)
    assert validator.validate(_row(Price="2,0", MinPrice="3,0"), "NAME_ONLY")[0] == \
        validator.INVALID_PRICE_BOUNDS
