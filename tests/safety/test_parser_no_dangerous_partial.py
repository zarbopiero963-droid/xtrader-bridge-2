"""Safety: un parsing parziale/casuale non deve mai produrre una riga CSV valida.

Combina parser → build_csv_row → recognition: un testo casuale, o un segnale con
solo quota o sole squadre, NON deve risultare scrivibile (niente riga pericolosa).
"""

from xtrader_bridge.parser import parse_message
from xtrader_bridge.csv_writer import build_csv_row
from xtrader_bridge import recognition, validator


def _is_writable(text):
    row = build_csv_row(parse_message(text), "PBet")
    return recognition.is_valid(row, "NAME_ONLY")


def _is_placeable(text):
    """Pipeline reale completa (PR-10): parse → build → validate (incl. prezzo)."""
    row = build_csv_row(parse_message(text), "PBet")
    return validator.is_valid(row, "NAME_ONLY")


def test_testo_casuale_non_scrivibile():
    assert _is_writable("Ciao a tutti, bella giornata.\nNiente di che.") is False


def test_solo_quota_non_scrivibile():
    assert _is_writable("Quota 1,85") is False


def test_solo_squadre_non_scrivibile():
    assert _is_writable("Inter v Milan") is False


def test_segnale_completo_e_scrivibile():
    # Contro-prova: un segnale completo mappato DEVE essere scrivibile.
    text = "P.Bet. OVER 2.5\nInter v Milan\nQuota 1,85"
    assert _is_writable(text) is True


def test_segnale_senza_prezzo_non_piazzabile():
    # Squadre + mercato ma SENZA quota: riconoscibile ma NON piazzabile (PR-10).
    text = "P.Bet. OVER 2.5\nInter v Milan"
    assert _is_writable(text) is True          # i nomi ci sono...
    assert _is_placeable(text) is False        # ...ma manca il prezzo → scartato


def test_segnale_completo_e_piazzabile():
    text = "P.Bet. OVER 2.5\nInter v Milan\nQuota 1,85"
    assert _is_placeable(text) is True


def test_prezzo_non_valido_non_piazzabile():
    # Prezzo 1,00 (non piazzabile) e prezzo non numerico: riga riconoscibile ma
    # NON piazzabile (il parser scarta la quota → prezzo mancante → validatore blocca).
    for text in ("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,00",
                 "P.Bet. OVER 2.5\nInter v Milan\nQuota abc"):
        assert _is_writable(text) is True
        assert _is_placeable(text) is False
