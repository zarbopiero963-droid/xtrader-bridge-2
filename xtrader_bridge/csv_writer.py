"""Contratto CSV XTrader e scrittura righe (nessuna dipendenza dalla GUI).

Header reale a 14 colonne basato sui CSV di esempio del team XTrader.
Scrittura: UTF-8 con BOM (utf-8-sig) e tutti i campi tra virgolette (QUOTE_ALL).
Vedi docs/xtrader_csv_contract.md.
"""

import csv
import errno
import logging
import os
import re
import threading
import time

from . import atomic_io, mapping, numbers_re

# Logger di modulo: un file esistente che NON è un CSV del bridge non viene ripulito;
# prima era un return silenzioso, ora si logga il motivo per la diagnosi (audit #105 P2).
logger = logging.getLogger(__name__)

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

# Nome del temporaneo della scrittura atomica del CSV: fonte unica di verità, usata sia
# per scrivere (`_atomic_write_locked`) sia per spazzare gli orfani allo startup
# (`sweep_orphan_temps`), così i due non possono divergere.
_CSV_TMP_PREFIX = ".segnali_"
_CSV_TMP_SUFFIX = ".tmp"

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


# errno STRUTTURALI/permanenti per `os.replace`: ritentarli è inutile e ritarda solo
# l'escalation di ~1s a ogni segnale (audit/M5 #184). Non sono contese transitorie del lock
# di lettura di XTrader: src inesistente, destinazione che è una directory, componente di
# percorso non-directory, rename cross-device, filesystem/destinazione di sola lettura,
# permesso negato (es. dir read-only), nome troppo lungo. Si rilanciano SUBITO.
_PERMANENT_REPLACE_ERRNOS = frozenset(
    e for e in (
        getattr(errno, "ENOENT", None), getattr(errno, "EISDIR", None),
        getattr(errno, "ENOTDIR", None), getattr(errno, "EXDEV", None),
        getattr(errno, "EROFS", None), getattr(errno, "EACCES", None),
        getattr(errno, "EPERM", None), getattr(errno, "ENAMETOOLONG", None),
    ) if e is not None
)
# Windows: codici `winerror` che indicano una contesa TRANSITORIA del file (XTrader lo tiene
# aperto in lettura) e quindi vanno ritentati. ERROR_SHARING_VIOLATION=32, ERROR_LOCK_VIOLATION=33
# e — soprattutto — ERROR_ACCESS_DENIED=5: il read-lock di XTrader fa fallire `MoveFileEx`/
# `os.replace` proprio con ACCESS_DENIED quando la destinazione è aperta in lettura (è il caso
# PIÙ comune, Codex #201 P1). Un read-only/ACL permanente surfacerebbe anch'esso come 5 — i due
# non sono distinguibili dall'errore — ma poiché il lock è la causa tipica si preferisce ritentare
# (al più ~1s sprecato su un raro read-only Windows) piuttosto che perdere il retry sul lock vero.
# Su POSIX, dove il rename atomico NON ha contese di lock, l'`EACCES` resta invece permanente.
_RETRYABLE_REPLACE_WINERRORS = frozenset({5, 32, 33})


def _is_retryable_replace_error(exc: OSError) -> bool:
    """True se l'errore di `os.replace` è una contesa TRANSITORIA che vale la pena ritentare
    (lock di lettura di XTrader su Windows); False se è strutturale/permanente (escalation
    immediata, M5 #184).

    - Su **Windows** (`winerror` valorizzato) si ritenta le contese di lock/condivisione
      `32`/`33` E l'access-denied `5` (il read-lock di XTrader surfacea tipicamente come
      ACCESS_DENIED, Codex #201 P1); gli altri `winerror` sono strutturali.
    - Su **POSIX**/errore generico (niente `winerror`) il rename atomico non ha contese di lock
      transitorie: si ritenta solo se l'`errno` NON è chiaramente permanente — così un errore
      SENZA `errno` (es. il lock simulato nei test/edge inattesi) resta ritentabile, mentre
      ENOENT/EISDIR/EACCES/EXDEV/... escalano subito invece di sprecare ~1s."""
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        return winerror in _RETRYABLE_REPLACE_WINERRORS
    return exc.errno not in _PERMANENT_REPLACE_ERRNOS


def _replace_with_retry(src: str, dst: str, attempts: int = 10, delay: float = 0.1) -> None:
    """`os.replace` con retry: su Windows il file può essere momentaneamente bloccato da
    XTrader che lo sta leggendo. Budget ~1s (10×0.1s, audit C3): 3×0.1s (~0.3s) erano troppo
    pochi — se XTrader teneva il lock più a lungo lo svuotamento/scrittura falliva e poteva
    lasciare un segnale stale attivo nel CSV. ~1s copre la contesa tipica del lock di lettura
    senza ritardare troppo il percorso live in caso di contesa.

    Solo gli errori TRANSITORI vengono ritentati (`_is_retryable_replace_error`, M5 #184): un
    errore strutturale (dir read-only/EACCES, EISDIR, ENOENT, cross-device) si propaga SUBITO,
    senza sprecare ~1s per ogni segnale prima dell'escalation."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            if i == attempts - 1 or not _is_retryable_replace_error(exc):
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
# testo e il contratto numerico si romperebbe. Frammento condiviso (anti-drift, audit L4).
_NUMERIC_RE = re.compile(numbers_re.SIGNED_DECIMAL)


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
    """Scrive il CSV in modo atomico (helper condiviso `atomic_io.atomic_write`): file
    temporaneo nella stessa cartella, flush + fsync, poi rename atomico sul file finale.

    Così XTrader non legge mai un file parziale. In caso di errore il file temporaneo
    viene rimosso e l'eccezione propagata (il CSV esistente resta intatto). Il rename usa
    `_replace_with_retry` (retry su lock Windows). Tutto sotto `_write_lock` per
    serializzare write/clear.
    """
    with _write_lock:
        _atomic_write_locked(path, write_rows)


def _atomic_write_locked(path: str, write_rows) -> None:
    """Come `_atomic_write` ma **assume che `_write_lock` sia GIÀ tenuto dal chiamante**.

    Serve a chi deve fare un'operazione composita atomica sotto lo stesso lock — es.
    `clear_stale_csv` legge l'header e poi svuota: il check-then-clear dev'essere un blocco
    unico, senza che una `write_csv` concorrente si inserisca in mezzo (issue #184 H3). NON
    riacquisisce `_write_lock` (che è un `threading.Lock` non rientrante: riacquisirlo dallo
    stesso thread sarebbe un deadlock)."""
    def _write_csv(f):
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        write_rows(writer)

    atomic_io.atomic_write(path, _write_csv, prefix=_CSV_TMP_PREFIX, suffix=_CSV_TMP_SUFFIX,
                           encoding=CSV_ENCODING, newline="", replace=_replace_with_retry)


def sweep_orphan_temps(path: str) -> int:
    """Rimuove i temporanei orfani del CSV (`.segnali_…​.tmp`) nella cartella di `path`,
    lasciati da un crash/blackout TRA la creazione del tmp e il rename (issue #184 LOW).

    Va chiamata **allo startup**, quando il listener è ancora spento: nessuna scrittura è
    in volo, quindi ogni `.segnali_*.tmp` è orfano di un processo morto. Best-effort: non
    solleva mai e non tocca il CSV reale (nome senza prefisso/suffisso). Ritorna quanti ne
    ha rimossi. È solo igiene del disco: il CSV finale era già intatto (il rename, se non
    avvenuto, non lo ha mai sovrascritto)."""
    p = str(path or "").strip()
    if not p:
        return 0
    d = os.path.dirname(os.path.abspath(p)) or "."
    return atomic_io.sweep_orphan_temps(d, _CSV_TMP_PREFIX, _CSV_TMP_SUFFIX)


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
    arbitrario dell'utente.

    **Atomicità check-then-clear (issue #184 H3):** la lettura dell'header E il successivo
    svuotamento avvengono SOTTO lo stesso `_write_lock`. Prima il check era fuori dal lock
    e lo svuotamento (`init_csv`) lo riprendeva: una `write_csv` concorrente dal thread del
    bot poteva inserirsi TRA la lettura dell'header e il clear, e un segnale appena scritto
    veniva azzerato a solo-header. Ora la sequenza è un blocco unico serializzato con le
    scritture."""
    if not path:
        return False
    with _write_lock:
        if not os.path.exists(path):
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
            # File esistente e decodificabile ma con header diverso da CSV_HEADER: NON è un CSV
            # del bridge → non si tocca (anti data-loss). Prima il return era SILENZIOSO: ora si
            # logga un avviso per la diagnosi, ma **senza il contenuto** dell'header. Se per
            # errore `csv_path` punta a un file con un segreto (es. un token nella prima riga, più
            # corto di una troncatura) NON deve finire nei log, e questo sink non passa per la
            # redazione di `event_log` (Codex P2). Si riportano solo METADATI strutturali (numero
            # colonne e lunghezza), che bastano a capire che è il file sbagliato.
            n_cols = len(first_row or [])
            n_chars = sum(len(str(c)) for c in (first_row or []))
            logger.warning("CSV non ripulito: %s non è un CSV del bridge (header atteso %d "
                           "colonne; rilevate %d colonne, %d caratteri — contenuto non loggato). "
                           "Controlla csv_path.", path, len(CSV_HEADER), n_cols, n_chars)
            return False   # non è un CSV del bridge → non sovrascrivere
        # svuotamento SOTTO lo stesso lock (no init_csv: riacquisirebbe _write_lock → deadlock)
        _atomic_write_locked(path, lambda writer: None)
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
