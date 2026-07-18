"""Safety (P3-15 #76): una riga costruita da dati PARZIALI non è mai scrivibile/piazzabile.

Sostituisce la copertura del rimosso `test_parser_no_dangerous_partial.py`, che pinnava
gli stessi invarianti partendo da `parse_message` (modulo P.Bet hardcoded, RIMOSSO):
la catena viva resta `build_csv_row` → `recognition` / `validator`, e qui la si esercita
direttamente dal **dict parsato** (l'unica sorgente rimasta di quei dati) sugli stessi
casi degeneri: solo quota, sole squadre, senza prezzo, prezzo 1,00 / non numerico.
Fail-closed: meglio nessuna riga che una riga pericolosa nel CSV XTrader."""

from xtrader_bridge import recognition, validator
from xtrader_bridge.csv_writer import build_csv_row


def _row(signal_type="", teams="", quota=""):
    return build_csv_row({"signal_type": signal_type, "teams": teams,
                          "quota": quota, "bet_type": "BACK"}, "PBet")


def _writable(row):
    return recognition.is_valid(row, "NAME_ONLY")


def _placeable(row):
    return validator.is_valid(row, "NAME_ONLY")


def test_solo_quota_non_scrivibile():
    row = _row(quota="1.85")
    assert _writable(row) is False
    assert _placeable(row) is False


def test_sole_squadre_non_scrivibili():
    row = _row(teams="Inter v Milan")
    assert _writable(row) is False
    assert _placeable(row) is False


def test_alias_ignoto_non_scrivibile():
    # Alias non mappato (né dizionario né legacy): SelectionName resta vuoto →
    # il riconoscimento scarta (nessuna selezione inventata, invariante A1).
    row = _row("MERCATO INESISTENTE", teams="Inter v Milan", quota="1.85")
    assert _writable(row) is False


def test_senza_prezzo_riconoscibile_ma_non_piazzabile():
    row = _row("OVER 2.5", teams="Inter v Milan")
    assert _writable(row) is True              # i nomi ci sono...
    assert _placeable(row) is False            # ...ma manca il prezzo → scartata


def test_prezzo_invalido_non_piazzabile():
    # 1,00 non è una quota piazzabile; "abc" non è un numero: entrambe scartate
    # dal validator anche se la riga è riconoscibile per nomi.
    for quota in ("1,00", "abc"):
        row = _row("OVER 2.5", teams="Inter v Milan", quota=quota)
        assert _writable(row) is True
        assert _placeable(row) is False


def test_controprova_segnale_completo_scrivibile_e_piazzabile():
    row = _row("OVER 2.5", teams="Inter v Milan", quota="1.85")
    assert _writable(row) is True
    assert _placeable(row) is True
