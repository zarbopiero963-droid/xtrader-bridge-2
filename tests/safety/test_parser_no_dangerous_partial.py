"""Safety: un parsing parziale/casuale non deve mai produrre una riga CSV valida.

Combina parser → build_csv_row → recognition: un testo casuale, o un segnale con
solo quota o sole squadre, NON deve risultare scrivibile (niente riga pericolosa).
"""

from xtrader_bridge.parser import parse_message
from xtrader_bridge.csv_writer import build_csv_row
from xtrader_bridge import recognition


def _is_writable(text):
    row = build_csv_row(parse_message(text), "PBet")
    return recognition.is_valid(row, "NAME_ONLY")


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
