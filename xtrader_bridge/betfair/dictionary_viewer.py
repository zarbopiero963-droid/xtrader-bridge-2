"""Viewer del dizionario Betfair locale — SOLA LETTURA (issue #86 PR-P11).

Logica pura (niente GUI, niente rete, niente scrittura DB) che interroga il dizionario
locale (`BetfairLocalDB`) per mostrarne il contenuto: sport, competizioni, eventi,
mercati, selezioni. È pensato per un pannello di sola consultazione: l'utente verifica
che cosa è stato sincronizzato sul PC, **senza** poter modificare nulla.

Vincoli (issue #86): il dizionario resta 100% locale; questo modulo non fa rete e non
muta il DB (solo `SELECT` via i metodi di lettura di `BetfairLocalDB`). Nessuna
operazione di scommessa (read-only ereditato dal resto del sottosistema).

Lo scoping per **sport** riusa la fonte unica `xtrader_bridge.sports`: sport → event_type_id
ufficiale Betfair. Sport non specificato/"(tutti)" → nessun filtro. Le selezioni non hanno
un `event_type_id` proprio: si restringono allo sport tramite i `market_id` dei mercati di
quello sport (`market_ids_for_sports`).
"""

from .. import sports

# Livelli del dizionario consultabili. Per ciascuno: tabella locale, colonne da mostrare
# (chiave DB → intestazione) e come si applica lo scope per sport.
#   scope="event_type_id" → filtro diretto sulla colonna event_type_id della tabella;
#   scope="market_id"     → filtro indiretto sui market_id dei mercati dello sport.
_LEVELS = {
    "sports": {
        "table": "betfair_sports",
        "columns": [("event_type_id", "Event Type ID"), ("name", "Sport"),
                    ("last_seen_at", "Ultima sync"), ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "competitions": {
        "table": "betfair_competitions",
        "columns": [("competition_id", "ID"), ("name", "Competizione"),
                    ("event_type_id", "Sport ID"),
                    ("last_seen_at", "Ultima sync"), ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "events": {
        "table": "betfair_events",
        "columns": [("event_id", "Event ID"), ("name", "Evento"),
                    ("competition_id", "Comp."), ("open_date", "Data"),
                    ("participant_1", "Casa"), ("participant_2", "Trasferta"),
                    ("last_seen_at", "Ultima sync"), ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "markets": {
        "table": "betfair_markets",
        "columns": [("market_id", "Market ID"), ("event_id", "Event ID"),
                    ("market_name", "Mercato"), ("market_type", "Tipo"),
                    ("last_seen_at", "Ultima sync"), ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "selections": {
        "table": "betfair_selections",
        "columns": [("market_id", "Market ID"), ("selection_id", "Selection ID"),
                    ("runner_name", "Selezione"), ("handicap", "Handicap"),
                    ("last_seen_at", "Ultima sync"), ("active", "Attivo")],
        "scope": "market_id",
    },
}

# Ordine di presentazione (dal più generale al più specifico).
LEVELS = ("sports", "competitions", "events", "markets", "selections")

# Etichette italiane dei livelli per la GUI (la chiave resta quella tecnica).
LEVEL_LABELS = {
    "sports": "Sport",
    "competitions": "Competizioni",
    "events": "Eventi",
    "markets": "Mercati",
    "selections": "Selezioni",
}


def _format_cell(col: str, value) -> str:
    """Formatta UNA cella per la visualizzazione (sola lettura):

    - `active` (0/1) → "sì"/"no" (più leggibile dello 0/1 grezzo);
    - `last_seen_at` 0/None → "" (mai sincronizzato), altrimenti il marker della sync;
    - `None` → "" (cella vuota);
    - tutto il resto → stringa."""
    if col == "active":
        try:
            return "sì" if int(value) == 1 else "no"
        except (TypeError, ValueError):
            return "no"
    if col == "last_seen_at":
        try:
            return "" if int(value) == 0 else str(int(value))
        except (TypeError, ValueError):
            return ""
    if value is None:
        return ""
    return str(value)


class DictionaryViewerController:
    """Interroga il dizionario locale per la sola consultazione. `db` è un
    `BetfairLocalDB` (iniettabile nei test). Nessuna scrittura, nessuna rete."""

    def __init__(self, db):
        self.db = db

    def levels(self) -> list:
        """Livelli consultabili, dal più generale al più specifico."""
        return list(LEVELS)

    def columns(self, level: str) -> list:
        """Intestazioni di colonna del livello (per l'header della tabella)."""
        return [header for _, header in _LEVELS[_check_level(level)]["columns"]]

    def _scoped_rows(self, level: str, sport=None) -> list:
        """Righe grezze (dict) della tabella del livello, filtrate per sport se richiesto.

        Sport non valido/non specificato → nessun filtro (tutte le righe). Sport valido →
        solo le righe di quello sport (per le selezioni, via i market_id dello sport)."""
        spec = _LEVELS[_check_level(level)]
        rows = self.db.fetchall(spec["table"])
        sport_norm = sports.normalize_sport(sport)
        if sport_norm is None:
            return rows
        etid = sports.SPORTS_EVENT_TYPE[sport_norm]
        if spec["scope"] == "event_type_id":
            return [r for r in rows if str(r.get("event_type_id", "")) == etid]
        # selezioni: nessun event_type_id proprio → filtra sui market_id dello sport.
        market_ids = {str(m) for m in self.db.market_ids_for_sports([etid])}
        return [r for r in rows if str(r.get("market_id", "")) in market_ids]

    def _apply_filters(self, rows: list, filters) -> list:
        """Filtri drill-down a corrispondenza esatta (competizione/evento/mercato, ecc.).

        `filters` è un dict ``{colonna: valore}``: una riga passa se per OGNI chiave la
        colonna esiste e il suo valore (come stringa) combacia. Una chiave che non è una
        colonna della tabella viene **ignorata** (fail-open: un viewer di sola lettura non
        deve azzerare la vista per un filtro non pertinente al livello corrente)."""
        if not filters:
            return rows
        active_keys = {k: str(v) for k, v in filters.items()
                       if any(k in r for r in rows)}
        if not active_keys:
            return rows
        return [r for r in rows
                if all(str(r.get(k, "")) == want for k, want in active_keys.items())]

    def _apply_search(self, rows: list, level: str, search) -> list:
        """Ricerca testuale case-insensitive (sottostringa) sulle colonne **testuali** del
        livello (nomi evento/partecipanti/mercato/selezione e ID). Salta `active` e
        `last_seen_at`. `search` vuoto/None → nessun filtro."""
        needle = str(search or "").strip().casefold()
        if not needle:
            return rows
        cols = [c for c, _ in _LEVELS[level]["columns"]
                if c not in ("active", "last_seen_at")]
        out = []
        for r in rows:
            for c in cols:
                val = r.get(c)
                if val is not None and needle in str(val).casefold():
                    out.append(r)
                    break
        return out

    def view(self, level: str, sport=None, active_only: bool = False,
             search=None, filters=None) -> dict:
        """Vista tabellare di un livello, pronta per la GUI.

        Ritorna ``{"columns": [...], "rows": [[...], ...], "total": int, "active": int}``:
        `columns` sono le intestazioni; `rows` le celle già formattate (sola lettura);
        `total`/`active` contano le righe **che soddisfano la query** (scope sport +
        `filters` drill-down + `search` testuale), prima dell'eventuale filtro
        `active_only`, così il riepilogo riflette ciò che si sta guardando. Con
        `active_only=True` `rows` contiene solo le righe attive.

        - `sport`: restringe allo sport (event_type_id; per le selezioni via market_id);
          sport non valido/non specificato → nessun filtro.
        - `filters`: dict ``{colonna: valore}`` a corrispondenza esatta (competizione/
          evento/mercato); chiavi non pertinenti al livello ignorate (fail-open).
        - `search`: testo cercato come sottostringa case-insensitive sui campi testuali."""
        spec = _LEVELS[_check_level(level)]
        rows_ = self._scoped_rows(level, sport)
        rows_ = self._apply_filters(rows_, filters)
        rows_ = self._apply_search(rows_, level, search)
        total = len(rows_)
        active = sum(1 for r in rows_ if _is_active(r))
        shown = [r for r in rows_ if _is_active(r)] if active_only else rows_
        cols = spec["columns"]
        rows = [[_format_cell(c, r.get(c)) for c, _ in cols] for r in shown]
        return {"columns": [h for _, h in cols], "rows": rows,
                "total": total, "active": active}

    def counts(self, sport=None) -> dict:
        """Conteggi per livello (in scope sport): ``{level: {"total": n, "active": n}}``.
        Per l'intestazione riassuntiva del viewer."""
        out = {}
        for level in LEVELS:
            scoped = self._scoped_rows(level, sport)
            out[level] = {
                "total": len(scoped),
                "active": sum(1 for r in scoped if _is_active(r)),
            }
        return out


def _is_active(row) -> bool:
    try:
        return int(row.get("active", 0)) == 1
    except (TypeError, ValueError):
        return False


def _check_level(level: str) -> str:
    if level not in _LEVELS:
        raise ValueError(
            f"livello dizionario non valido: {level!r}; ammessi {', '.join(LEVELS)}")
    return level
