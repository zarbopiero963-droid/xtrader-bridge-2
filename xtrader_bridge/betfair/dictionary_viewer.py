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
                    ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "competitions": {
        "table": "betfair_competitions",
        "columns": [("competition_id", "ID"), ("name", "Competizione"),
                    ("event_type_id", "Sport ID"), ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "events": {
        "table": "betfair_events",
        "columns": [("event_id", "Event ID"), ("name", "Evento"),
                    ("competition_id", "Comp."), ("open_date", "Data"),
                    ("participant_1", "Casa"), ("participant_2", "Trasferta"),
                    ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "markets": {
        "table": "betfair_markets",
        "columns": [("market_id", "Market ID"), ("event_id", "Event ID"),
                    ("market_name", "Mercato"), ("market_type", "Tipo"),
                    ("active", "Attivo")],
        "scope": "event_type_id",
    },
    "selections": {
        "table": "betfair_selections",
        "columns": [("market_id", "Market ID"), ("selection_id", "Selection ID"),
                    ("runner_name", "Selezione"), ("handicap", "Handicap"),
                    ("active", "Attivo")],
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
    - `None` → "" (cella vuota);
    - tutto il resto → stringa."""
    if col == "active":
        try:
            return "sì" if int(value) == 1 else "no"
        except (TypeError, ValueError):
            return "no"
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

    def view(self, level: str, sport=None, active_only: bool = False) -> dict:
        """Vista tabellare di un livello, pronta per la GUI.

        Ritorna ``{"columns": [...], "rows": [[...], ...], "total": int, "active": int}``:
        `columns` sono le intestazioni; `rows` le celle già formattate (sola lettura);
        `total`/`active` contano le righe **in scope** (prima dell'eventuale filtro
        `active_only`), così il riepilogo mostra sempre quante ce ne sono in totale e
        quante attive. Con `active_only=True` `rows` contiene solo le righe attive."""
        spec = _LEVELS[_check_level(level)]
        scoped = self._scoped_rows(level, sport)
        total = len(scoped)
        active = sum(1 for r in scoped if _is_active(r))
        shown = [r for r in scoped if _is_active(r)] if active_only else scoped
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
