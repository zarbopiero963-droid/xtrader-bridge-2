"""Contratto CSV XTrader e scrittura righe (nessuna dipendenza dalla GUI).

Header reale a 14 colonne basato sui CSV di esempio del team XTrader.
Scrittura: UTF-8 con BOM (utf-8-sig) e tutti i campi tra virgolette (QUOTE_ALL).
Vedi docs/xtrader_csv_contract.md.
"""

import csv
import os
import tempfile
import threading
import time

# Lock condiviso: serializza scrittura segnale e svuotamento, eliminando la
# race tra il thread del bot (write_csv) e il timer di auto-clear (init_csv).
_write_lock = threading.Lock()

CSV_HEADER = [
    "Provider", "EventId", "EventName", "MarketId", "MarketName",
    "MarketType", "SelectionId", "SelectionName", "Handicap", "Price",
    "MinPrice", "MaxPrice", "BetType", "Points"
]

# Valori di default coerenti con gli esempi reali XTrader.
DEFAULT_POINTS = ""      # Points lasciato vuoto: lo stake/moltiplicatore lo gestisce XTrader.
DEFAULT_HANDICAP = "0"   # Handicap "0" come negli esempi reali.

# BetType nel CSV XTrader è in italiano: PUNTA (back) / BANCA (lay).
BETTYPE_MAP = {
    "BACK": "PUNTA",
    "LAY":  "BANCA",
}

CSV_ENCODING = "utf-8-sig"  # BOM richiesto dagli esempi XTrader.

MARKET_MAPPING = {
    "GOL SECONDO TEMPO": "NEXT_GOAL",
    "OVER 0.5":          "OVER_UNDER_05",
    "OVER 1.5":          "OVER_UNDER_15",
    "OVER 2.5":          "OVER_UNDER_25",
    "OVER 3.5":          "OVER_UNDER_35",
    "OVER 4.5":          "OVER_UNDER_45",
    "MATCH ODDS":        "MATCH_ODDS",
    "1X2":               "MATCH_ODDS",
    "GG":                "BOTH_TEAMS_TO_SCORE",
    "GOAL GOAL":         "BOTH_TEAMS_TO_SCORE",
    "NEXT GOAL":         "NEXT_GOAL",
    "DOPPIA CHANCE":     "DOUBLE_CHANCE",
}


def build_csv_row(parsed: dict, provider: str) -> dict:
    """Converte i dati parsati in una riga XTrader."""
    market_type = "MATCH_ODDS"
    signal_upper = parsed['signal_type'].upper()
    for key, val in MARKET_MAPPING.items():
        if key in signal_upper:
            market_type = val
            break

    teams = parsed['teams']
    home = teams.split(' v ')[0] if ' v ' in teams else teams
    is_goals = any(k in signal_upper for k in ["GOL", "OVER", "GOAL"])
    selection = "Over 0.5 Goals" if is_goals else home

    # XTrader usa PUNTA/BANCA; il segnale interno resta BACK/LAY (default BACK).
    # Un bet_type sconosciuto NON deve essere mappato silenziosamente: piazzerebbe
    # il lato opposto della scommessa. Lo blocchiamo (safety-critical).
    raw_bet_type = str(parsed.get('bet_type', 'BACK')).strip().upper()
    if raw_bet_type not in BETTYPE_MAP:
        raise ValueError(f"bet_type non supportato: {raw_bet_type!r} (atteso BACK o LAY)")
    bet_type = BETTYPE_MAP[raw_bet_type]

    # Gli ID (EventId/MarketId/SelectionId) non sono presenti nel messaggio
    # Telegram: restano vuoti. XTrader valida via EventName+MarketType+SelectionName.
    return {
        'Provider':      provider,
        'EventId':       '',
        'EventName':     teams,
        'MarketId':      '',
        'MarketName':    parsed['signal_type'],
        'MarketType':    market_type,
        'SelectionId':   '',
        'SelectionName': selection,
        'Handicap':      DEFAULT_HANDICAP,
        'Price':         parsed.get('quota', ''),
        'MinPrice':      '',
        'MaxPrice':      '',
        'BetType':       bet_type,
        'Points':        DEFAULT_POINTS,
    }


def _replace_with_retry(src: str, dst: str, attempts: int = 3, delay: float = 0.1) -> None:
    """`os.replace` con qualche retry: su Windows il file può essere
    momentaneamente bloccato da XTrader che lo sta leggendo."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def _atomic_write(path: str, write_rows) -> None:
    """Scrive il CSV in modo atomico: file temporaneo nella stessa cartella,
    flush + fsync, poi rename atomico (`os.replace`) sul file finale.

    Così XTrader non legge mai un file parziale. In caso di errore il file
    temporaneo viene rimosso e l'eccezione propagata (il CSV esistente resta
    intatto). Tutto sotto `_write_lock` per serializzare write/clear.
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    with _write_lock:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".segnali_", suffix=".tmp")
        try:
            with os.fdopen(fd, 'w', newline='', encoding=CSV_ENCODING) as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADER, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                write_rows(writer)
                f.flush()
                os.fsync(f.fileno())
            _replace_with_retry(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise


def init_csv(path: str):
    """Crea/svuota il CSV lasciando solo l'header (scrittura atomica)."""
    _atomic_write(path, lambda writer: None)


def write_csv(row: dict, path: str):
    """Scrive un segnale nel CSV, sovrascrivendo (scrittura atomica)."""
    _atomic_write(path, lambda writer: writer.writerow(row))
