"""Contratto CSV XTrader e scrittura righe (nessuna dipendenza dalla GUI).

Header reale a 14 colonne basato sui CSV di esempio del team XTrader.
Scrittura: UTF-8 con BOM (utf-8-sig) e tutti i campi tra virgolette (QUOTE_ALL).
Vedi docs/xtrader_csv_contract.md.
"""

import csv
import os
import re
import tempfile
import threading
import time

from . import mapping

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
    """Converte i dati parsati in una riga XTrader.

    Se l'alias del segnale è riconosciuto nel dizionario (PR-07/08) usa i valori
    italiani ufficiali (MarketType/MarketName/SelectionName); altrimenti ricade
    sul mapping legacy. Il `bet_type` viene sempre dal segnale (PUNTA/BANCA).
    """
    teams = parsed['teams']
    parts = teams.split(' v ')
    home = parts[0].strip() if parts else teams
    away = parts[1].strip() if len(parts) > 1 else ""

    # XTrader usa PUNTA/BANCA; il segnale interno resta BACK/LAY (default BACK).
    # Un bet_type sconosciuto NON deve essere mappato silenziosamente: piazzerebbe
    # il lato opposto della scommessa. Lo blocchiamo (safety-critical).
    raw_bet_type = str(parsed.get('bet_type', 'BACK')).strip().upper()
    if raw_bet_type not in BETTYPE_MAP:
        raise ValueError(f"bet_type non supportato: {raw_bet_type!r} (atteso BACK o LAY)")
    bet_type = BETTYPE_MAP[raw_bet_type]

    resolved = mapping.resolve_shorthand(parsed['signal_type'], home=home, away=away)
    if resolved:
        market_type = resolved["MarketType"]
        market_name = resolved["MarketName"]
        selection = resolved["SelectionName"]
        handicap = resolved["Handicap"]   # già normalizzato in mapping.resolve()
    elif mapping.is_known_shorthand(parsed['signal_type']):
        # Alias noto ma non risolvibile (es. nome squadra mancante per 1/2):
        # NON ripiegare su una selezione errata né scrivere il placeholder.
        # SelectionName vuoto → il riconoscimento (PR-06) scarta la riga.
        market_type = ""
        market_name = parsed['signal_type']
        selection = ""
        handicap = DEFAULT_HANDICAP
    else:
        # Fallback legacy: mapping inglese del SOLO tipo mercato. La **selezione NON va
        # inventata** (A1): "OVER 2.5" non è "Over 0.5 Goals" (mercato/linea diversi) e un
        # MATCH ODDS non è sempre l'home (può essere away/pareggio). Sintetizzarla
        # piazzerebbe la selezione SBAGLIATA. SelectionName vuoto → scartato dal
        # riconoscimento (PR-06), fail-closed: meglio nessuna riga che una riga sbagliata.
        signal_upper = parsed['signal_type'].upper()
        market_name = parsed['signal_type']
        handicap = DEFAULT_HANDICAP
        market_type = ""
        for key, val in MARKET_MAPPING.items():
            if key in signal_upper:
                market_type = val
                break
        selection = ""

    # Gli ID (EventId/MarketId/SelectionId) non sono presenti nel messaggio
    # Telegram: restano vuoti. XTrader valida via EventName+MarketType+SelectionName.
    return {
        'Provider':      provider,
        'EventId':       '',
        'EventName':     teams,
        'MarketId':      '',
        'MarketName':    market_name,
        'MarketType':    market_type,
        'SelectionId':   '',
        'SelectionName': selection,
        'Handicap':      handicap,
        'Price':         parsed.get('quota', ''),
        'MinPrice':      '',
        'MaxPrice':      '',
        'BetType':       bet_type,
        'Points':        DEFAULT_POINTS,
    }


def _replace_with_retry(src: str, dst: str, attempts: int = 10, delay: float = 0.1) -> None:
    """`os.replace` con retry: su Windows il file può essere momentaneamente bloccato da
    XTrader che lo sta leggendo. Budget ~1s (10×0.1s, audit C3): 3×0.1s (~0.3s) erano troppo
    pochi — se XTrader teneva il lock più a lungo lo svuotamento/scrittura falliva e poteva
    lasciare un segnale stale attivo nel CSV. ~1s copre la contesa tipica del lock di lettura
    senza ritardare troppo il percorso live in caso di contesa."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


# Caratteri che, se in TESTA a una cella, possono far interpretare la cella come
# formula/comando da un reader formula-aware (Excel/LibreOffice/Google Sheets) o
# iniettare un controllo di riga: `= + - @` e i control-char TAB/CR/LF. `QUOTE_ALL`
# mette in sicurezza il PARSING ma non neutralizza questi prefissi (audit B1).
_CSV_FORMULA_CHARS = ("=", "+", "-", "@")
_CSV_CTRL_CHARS = ("\t", "\r", "\n")
# Numero "puro" (segno opzionale + decimale con . o ,): es. Handicap "-1"/"+1,5", Price
# "1.85". Un numero legittimo NON va prefissato, altrimenti XTrader leggerebbe "'-1" come
# testo e il contratto numerico si romperebbe.
_NUMERIC_RE = re.compile(r"[+-]?\d+(?:[.,]\d+)?")


def _sanitize_cell(value):
    """Neutralizza l'iniezione formula/control-char nel CSV (audit B1): se una cella inizia
    con `= + - @` (e NON è un numero) o con un control-char (TAB/CR/LF), antepone un apice
    ``'`` (mitigazione standard OWASP). I numeri (Handicap negativo, Price…) restano intatti.
    Non-stringa/vuoto: invariato."""
    s = "" if value is None else str(value)
    if not s:
        return s
    first = s[0]
    if first in _CSV_CTRL_CHARS:
        return "'" + s
    if first in _CSV_FORMULA_CHARS and not _NUMERIC_RE.fullmatch(s.strip()):
        return "'" + s
    return s


def _sanitize_row(row: dict) -> dict:
    """Copia della riga con ogni cella passata da `_sanitize_cell` (anti CSV-injection)."""
    return {k: _sanitize_cell(v) for k, v in row.items()}


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


def clear_stale_csv(path: str) -> bool:
    """Svuota il CSV (solo header) **se il file esiste già**: rimuove una riga
    lasciata da una sessione precedente terminata male (crash, blackout, chiusura).

    Ritorna ``True`` se ha ripulito un file esistente, ``False`` se non c'era nulla
    da fare (``path`` vuoto o file assente). **Non crea** il file se manca: all'avvio
    non si tocca un path non ancora usato.

    Difesa anti-segnale-stantio: se il processo muore mentre nel CSV c'è una riga
    attiva, il timer di auto-clear non può girare. Richiamando questa funzione
    all'avvio dell'app (prima che il listener riparta) e alla chiusura/STOP, il CSV
    torna a solo header, così XTrader non legge un segnale orfano.

    **Sicurezza (anti data-loss):** ripulisce SOLO un file che è già un CSV del
    bridge, cioè la cui prima riga è esattamente `CSV_HEADER`. Se `csv_path` punta
    per errore a un file NON-bridge (typo/path riusato in config), il file **non**
    viene toccato: aprire/chiudere l'app non deve poter distruggere un file
    arbitrario dell'utente."""
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            first_row = next(csv.reader(f), None)
    except (UnicodeDecodeError, csv.Error):
        # File non decodificabile/non parsabile (CSV ANSI, binario scelto per
        # errore…) → non è un CSV del bridge: non toccarlo (e niente crash).
        return False
    # NB: un OSError (permessi/lock di Windows, es. file tenuto aperto) NON è
    # catturato qui: si propaga al chiamante, che lo segnala come cleanup fallito
    # invece di silenziarlo come se il file fosse assente/non-bridge.
    if first_row != CSV_HEADER:
        return False   # non è un CSV del bridge → non sovrascrivere
    init_csv(path)
    return True


def write_rows(rows, path: str):
    """Scrive PIÙ segnali nel CSV (header + una riga per ciascuno), sovrascrivendo
    in modo atomico. `rows` vuota → solo header (equivale a `init_csv`). Usato dalla
    coda dei segnali attivi (PR-22): in OVERWRITE_LAST è una sola riga, in
    APPEND_ACTIVE/QUEUE_UNTIL_CONFIRMED sono i segnali attivi correnti."""
    rows = list(rows or [])

    def _emit(writer):
        for r in rows:
            # Anti CSV-injection (B1): neutralizza i prefissi formula/control-char nelle celle
            # (testo attacker-controlled da Telegram) prima di scriverle; i numeri restano intatti.
            writer.writerow(_sanitize_row(r))

    _atomic_write(path, _emit)


def write_csv(row: dict, path: str):
    """Scrive un singolo segnale nel CSV, sovrascrivendo (scrittura atomica)."""
    write_rows([row], path)
