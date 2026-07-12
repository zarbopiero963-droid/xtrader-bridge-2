"""Modalità di riconoscimento del segnale per XTrader (PR-06).

XTrader può validare un segnale tramite gli ID (`MarketId` + `SelectionId`)
oppure tramite i nomi (`EventName` + `MarketType` + `SelectionName`).
Questa logica decide se una riga CSV ha i campi necessari per la modalità scelta:
serve a **bloccare la scrittura** di righe incomplete (non riconoscibili da
XTrader), evitando segnali ambigui.
"""

ID_ONLY = "ID_ONLY"
NAME_ONLY = "NAME_ONLY"
BOTH = "BOTH"

VALID_MODES = (ID_ONLY, NAME_ONLY, BOTH)
DEFAULT_MODE = NAME_ONLY

# Campi richiesti da ciascun "set" di riconoscimento.
_ID_FIELDS = ("MarketId", "SelectionId")
_NAME_FIELDS = ("EventName", "MarketType", "SelectionName")

# Tutte le colonne legate al riconoscimento (per il builder: sono quelle la cui
# obbligatorietà è guidata dalla Modalità, vs Price/BetType/Provider che no).
RECOGNITION_FIELDS = _ID_FIELDS + _NAME_FIELDS


def recognition_fields_for_mode(mode: str) -> tuple:
    """Campi di riconoscimento RILEVANTI per la modalità (per il content-gate A10):

    - `ID_ONLY`   → solo i campi ID (`MarketId`+`SelectionId`);
    - `NAME_ONLY` → solo i campi nome (`EventName`+`MarketType`+`SelectionName`);
    - `BOTH`      → entrambi i set (basta un set, quindi ognuno è "di segnale").

    Differisce da `RECOGNITION_FIELDS` (insieme totale, mode-agnostico): qui un
    campo ID opzionale NON conta come "contenuto di segnale" per un parser
    `NAME_ONLY`, così un'estrazione ID casuale non fa passare un non-segnale (A10).
    """
    mode = normalize_mode(mode)
    if mode == ID_ONLY:
        return _ID_FIELDS
    if mode == NAME_ONLY:
        return _NAME_FIELDS
    return RECOGNITION_FIELDS


def required_targets(mode: str) -> tuple:
    """Colonne che la Modalità rende obbligatorie nel builder (auto-Obblig.):

    - `ID_ONLY`   → `MarketId`+`SelectionId`;
    - `NAME_ONLY` → `EventName`+`MarketType`+`SelectionName`;
    - `BOTH`      → `()`: basta UN set completo, quindi il builder non forza un set
      preciso (lo decide l'utente; il validatore accetta ID **oppure** nomi).
    """
    mode = normalize_mode(mode)
    if mode == ID_ONLY:
        return _ID_FIELDS
    if mode == NAME_ONLY:
        return _NAME_FIELDS
    return ()


def normalize_mode(mode: str) -> str:
    """Riporta una modalità sconosciuta al default sicuro (NAME_ONLY)."""
    return mode if mode in VALID_MODES else DEFAULT_MODE


def _missing(row: dict, fields) -> list:
    return [f for f in fields if not str(row.get(f, "")).strip()]


def missing_fields(row: dict, mode: str) -> list:
    """Elenco dei campi mancanti perché la riga sia riconoscibile nella modalità.

    - ID_ONLY: servono tutti gli ID.
    - NAME_ONLY: servono tutti i nomi.
    - BOTH: basta che sia completo ALMENO uno dei due set (ID **oppure** nomi);
      se nessuno è completo, riporta i campi nome mancanti come indicazione.
    Lista vuota = riga valida per quella modalità.
    """
    mode = normalize_mode(mode)
    if mode == ID_ONLY:
        return _missing(row, _ID_FIELDS)
    if mode == NAME_ONLY:
        return _missing(row, _NAME_FIELDS)
    # BOTH
    id_missing = _missing(row, _ID_FIELDS)
    name_missing = _missing(row, _NAME_FIELDS)
    if not id_missing or not name_missing:
        return []
    return name_missing


def is_valid(row: dict, mode: str) -> bool:
    return not missing_fields(row, mode)


# ── Lingua della FONTE per il riconoscimento a NOMI (epica #3 slice 5a) ──────────────
# Col riconoscimento a NOMI i nomi di evento/mercato/selezione dipendono dalla LINGUA del
# palinsesto della fonte (conferma supporto Betting Toolkit §5). Questa è la FOUNDATION:
# normalizzazione + risoluzione globale/override della lingua-fonte. Il matching per-lingua
# vero e proprio (filtro sui profili nomi) arriva con la slice 5b — come `csv_language`
# (#342) fu la fondazione prima del suo consumo (#343). L'insieme lingue è lo stesso del CSV
# (`csv_writer.CSV_LANGUAGES`); qui è DUPLICATO di proposito per tenere `recognition` senza
# import (è il modulo-gate puro): un test anti-drift verifica che i due insiemi coincidano.
SOURCE_LANGUAGES = ("IT", "EN", "ES")


def normalize_source_language(value) -> str:
    """Lingua della fonte per il matching a NOMI: `IT`/`EN`/`ES` (case-insensitive, spazi
    tollerati) oppure STRINGA VUOTA (= non dichiarata → comportamento storico agnostico alla
    lingua). Come `app_language`, NESSUN fallback a IT: un valore sporco/mancante torna ""
    (fail-closed: non si finge una lingua-fonte mai scelta, che restringerebbe il matching a
    sorpresa invertendo o scartando un segnale)."""
    if isinstance(value, str) and value.strip().upper() in SOURCE_LANGUAGES:
        return value.strip().upper()
    return ""


def effective_source_language(cfg, defn=None) -> str:
    """Lingua-fonte EFFETTIVA per un parser: override per-parser (`defn.source_language`) se
    valorizzato, altrimenti il globale `cfg['source_language']`, altrimenti "" (agnostica).
    Specchio di come `recognition_mode` combina globale + override per-parser. `defn` è
    duck-typed (si legge solo l'attributo: nessun import di `custom_parser`, sarebbe un
    ciclo). Consumato dalla slice 5b."""
    per_parser = (normalize_source_language(getattr(defn, "source_language", ""))
                  if defn is not None else "")
    if per_parser:
        return per_parser
    cfg_val = cfg.get("source_language") if isinstance(cfg, dict) else ""
    return normalize_source_language(cfg_val)
