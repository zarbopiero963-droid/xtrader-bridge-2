"""Loader del dizionario XTrader (PR-07).

Il dizionario (`data/dizionario_xtrader.csv`) è il "traduttore" tra gli alias dei
segnali Telegram e i valori esatti che XTrader si aspetta (MarketType, MarketName,
SelectionName, Handicap, BetType). Basato sui dati reali forniti dal team XTrader.

PR-07 fornisce solo caricamento e validazione strutturale; il lookup vero e
proprio (alias → riga) e l'integrazione in `build_csv_row` sono PR-08.
"""

import csv
import os
import re
import sys


def _data_dir() -> str:
    """Cartella `data/`. Nell'EXE PyInstaller i dati stanno in sys._MEIPASS
    (vedi --add-data nel workflow), non accanto a __file__ (bundle temporaneo)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data")


DIZIONARIO_PATH = os.path.join(_data_dir(), "dizionario_xtrader.csv")

EXPECTED_COLUMNS = [
    "Sport", "Periodo", "MarketAliasTelegram", "SelectionAliasTelegram",
    "MarketType_XTrader", "MarketName_XTrader", "SelectionRole",
    "SelectionName_XTrader", "Linea", "Handicap", "BetType_XTrader", "Lingua",
    "SelezioneDinamica", "MetodoConsigliato", "Stato", "Fonte",
    "EsempioEventName", "EsempioEventId", "EsempioMarketId",
    "EsempioSelectionId", "Note",
]


def load_dizionario(path: str = DIZIONARIO_PATH) -> list:
    """Carica il dizionario come lista di dict (una per riga)."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalize(s: str) -> str:
    """Normalizzazione per il lookup (case/space-insensitive): minuscolo, trim e
    collasso degli spazi interni (es. "Over  0.5  HT" -> "over 0.5 ht").

    Funzione pubblica: fonte unica della normalizzazione, riusata anche dalle
    value-map (CP-03) per evitare implementazioni divergenti."""
    return " ".join(str(s).strip().lower().split())


_norm = normalize  # alias interno storico


def alias_key(market_alias: str, selection_alias: str) -> tuple:
    """Chiave normalizzata (case/space-insensitive) usata per il lookup (PR-08)."""
    return (_norm(market_alias), _norm(selection_alias))


def duplicate_alias_pairs(rows: list) -> list:
    """Coppie (MarketAliasTelegram, SelectionAliasTelegram) duplicate: devono
    essere zero, altrimenti il lookup sarebbe ambiguo. Le righe con alias vuoti
    vengono ignorate (non sono lookabili e non devono generare falsi duplicati)."""
    seen, dups = set(), []
    for row in rows:
        ma = str(row.get("MarketAliasTelegram", "")).strip()
        sa = str(row.get("SelectionAliasTelegram", "")).strip()
        if not ma or not sa:
            continue
        k = alias_key(ma, sa)
        if k in seen:
            dups.append(k)
        else:
            seen.add(k)
    return dups


def market_types(rows: list) -> set:
    return {row["MarketType_XTrader"] for row in rows}


# ── Catalogo per le tendine della GUI (A1) ──────────────────────────────────
# Funzioni PURE costruite sul dizionario reale: popolano i menù a tendina del
# Parser Personalizzato (scelta del VALORE FISSO della colonna) senza che la GUI
# conosca il formato del CSV/del dizionario. Mercati e selezioni sono restituiti
# nell'ordine del file: stabile e prevedibile per l'utente.

_ROWS_CACHE = None
_PLACEHOLDER_RE = re.compile(r"\{[A-Z_]+\}")


def _rows(rows=None) -> list:
    """Righe del dizionario: quelle passate, oppure il file reale caricato UNA
    volta e tenuto in cache (il catalogo non cambia a runtime). Passare `rows`
    espliciti mantiene le funzioni pure/testabili senza toccare il disco."""
    global _ROWS_CACHE
    if rows is not None:
        return rows
    if _ROWS_CACHE is None:
        _ROWS_CACHE = load_dizionario()
    return _ROWS_CACHE


def market_catalog(rows=None) -> list:
    """Elenco ordinato e SENZA duplicati dei mercati nell'ordine di prima comparsa:
    ``[{"MarketType": ..., "MarketName": ...}, …]``. Popola la tendina dei mercati
    (l'utente sceglie il MarketName; il MarketType è accoppiato e ricavabile)."""
    seen, out = set(), []
    for r in _rows(rows):
        mt = (r.get("MarketType_XTrader") or "").strip()
        mn = (r.get("MarketName_XTrader") or "").strip()
        if not mt or mt in seen:
            continue
        seen.add(mt)
        out.append({"MarketType": mt, "MarketName": mn})
    return out


def market_names(rows=None) -> list:
    """Solo i MarketName (per popolare direttamente una tendina)."""
    return [m["MarketName"] for m in market_catalog(rows)]


def market_name_for_type(market_type, rows=None):
    """MarketName accoppiato a un MarketType, o None se non esiste."""
    key = (market_type or "").strip()
    for m in market_catalog(rows):
        if m["MarketType"] == key:
            return m["MarketName"]
    return None


def market_type_for_name(market_name, rows=None):
    """MarketType accoppiato a un MarketName (case/space-insensitive), o None."""
    key = _norm(market_name)
    for m in market_catalog(rows):
        if _norm(m["MarketName"]) == key:
            return m["MarketType"]
    return None


def selections_for_market(market, rows=None) -> list:
    """Selezioni di un mercato (match per MarketType **o** MarketName,
    case/space-insensitive), nell'ordine del dizionario. Ogni voce è un dict con i
    campi utili a tendina e riga CSV. ``dynamic=True`` marca una selezione che
    contiene un placeholder squadra ({HOME_TEAM}/{AWAY_TEAM}): quel valore va
    completato dal parser (Home/Away), non scelto come fisso."""
    key = _norm(market)
    if not key:
        return []
    out = []
    for r in _rows(rows):
        mt = _norm(r.get("MarketType_XTrader"))
        mn = _norm(r.get("MarketName_XTrader"))
        if key not in (mt, mn):
            continue
        name = (r.get("SelectionName_XTrader") or "").strip()
        out.append({
            "SelectionName":          name,
            "SelectionRole":          (r.get("SelectionRole") or "").strip(),
            "MarketType":             (r.get("MarketType_XTrader") or "").strip(),
            "MarketName":             (r.get("MarketName_XTrader") or "").strip(),
            "MarketAliasTelegram":    (r.get("MarketAliasTelegram") or "").strip(),
            "SelectionAliasTelegram": (r.get("SelectionAliasTelegram") or "").strip(),
            "Linea":                  (r.get("Linea") or "").strip(),
            "Handicap":               ((r.get("Handicap") or "").strip() or "0"),
            "BetType":                (r.get("BetType_XTrader") or "").strip(),
            "dynamic":                has_placeholder(name),
        })
    return out


def has_placeholder(value) -> bool:
    """True se nel valore restano placeholder non risolti (es. ``{HOME_TEAM}``)."""
    return bool(_PLACEHOLDER_RE.search(str(value)))


def compose_event_name(home, away) -> str:
    """Compone l'EventName nel formato del dizionario/XTrader: ``"Casa - Trasferta"``
    (separatore " - ", come negli esempi reali). Se manca una squadra ritorna
    l'altra (o stringa vuota), senza separatori penzolanti."""
    h = str(home or "").strip()
    a = str(away or "").strip()
    if h and a:
        return f"{h} - {a}"
    return h or a


def fill_placeholders(value, home="", away="") -> str:
    """Sostituisce i placeholder dinamici di un valore del dizionario:
    ``{HOME_TEAM}``/``{AWAY_TEAM}`` con le squadre e ``{EVENT_NAME}`` con l'EventName
    composto (solo se entrambe le squadre sono note). I placeholder privi di valore
    restano invariati: il chiamante può rilevarli con `has_placeholder` e scartare
    una selezione non completabile."""
    out = str(value)
    h = str(home or "").strip()
    a = str(away or "").strip()
    if h:
        out = out.replace("{HOME_TEAM}", h)
    if a:
        out = out.replace("{AWAY_TEAM}", a)
    if h and a:
        out = out.replace("{EVENT_NAME}", compose_event_name(h, a))
    return out
