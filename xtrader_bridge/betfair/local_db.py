"""Dizionario Betfair locale multi-sport (issue #86 PR-P5) — SQLite, solo locale.

Tabelle locali del dizionario (tutto sul PC/VPS, **nessun cloud, nessun
export/import**): `betfair_sports`, `betfair_competitions`, `betfair_events`,
`betfair_markets`, `betfair_selections`, `betfair_sync_runs`,
`betfair_local_name_mappings`.

Chiavi corrette (dall'issue), che evitano i falsi duplicati:
- Sport → `event_type_id`
- Competizione → `competition_id`
- Evento → `event_id`
- Mercato → `market_id` (cambia per evento/mercato)
- Selezione → (`market_id`, `selection_id`, `handicap`)  ← `selection_id` da solo NON basta
- Partecipante/mapping → (`sport`, `normalized_name`)

Regole: l'upsert non duplica (chiave naturale), lo stesso nome squadra in eventi
diversi NON viene scartato (gli eventi sono chiavati per `event_id`, le selezioni
per la tripla), e i record non più visti in una sync vengono marcati
`active=0` (`deactivate_unseen`). Usa solo la **stdlib** (`sqlite3`): nessuna nuova
dipendenza. Nessun dato sensibile/credenziale finisce qui.
"""

import os
import sqlite3
import threading

# Busy timeout della connessione SQLite (secondi). Il default di sqlite3 è 5s: un
# accesso concorrente al file (es. il viewer del dizionario aperto mentre una sync
# scrive, o un secondo processo) può sbattere su "database is locked" troppo presto.
# Con 30s la connessione ASPETTA che il lock si liberi invece di fallire subito
# (#184 LOW). Applicato sia via `timeout=` (copre l'apertura) sia via PRAGMA esplicito.
_BUSY_TIMEOUT_S = 30

# Whitelist delle tabelle che espongono active/last_seen_at e la loro colonna di
# scoping opzionale (per deactivate_unseen). Fonte unica: evita SQL costruito da
# input non controllato (i nomi tabella/colonna passano SOLO da qui).
# NB: anche `betfair_sports` è scopabile per `event_type_id` (la sua stessa PK), così
# una sync di un solo sport può ripulire SOLO quel record e non disattivare gli altri
# sport visti in precedenti sync (invariante multi-sport, Codex).
_SCOPED = {
    "betfair_sports": "event_type_id",
    "betfair_competitions": "event_type_id",
    "betfair_events": "event_type_id",
    "betfair_markets": "event_type_id",
    "betfair_selections": "market_id",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS betfair_sports (
    event_type_id TEXT PRIMARY KEY,
    name          TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    last_seen_at  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS betfair_competitions (
    competition_id TEXT PRIMARY KEY,
    event_type_id  TEXT,
    name           TEXT,
    active         INTEGER NOT NULL DEFAULT 1,
    last_seen_at   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS betfair_events (
    event_id       TEXT PRIMARY KEY,
    event_type_id  TEXT,
    competition_id TEXT,
    name           TEXT,
    open_date      TEXT,
    participant_1  TEXT,
    participant_2  TEXT,
    active         INTEGER NOT NULL DEFAULT 1,
    last_seen_at   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS betfair_markets (
    market_id     TEXT PRIMARY KEY,
    event_id      TEXT,
    event_type_id TEXT,
    market_name   TEXT,
    market_type   TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    last_seen_at  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS betfair_selections (
    market_id     TEXT NOT NULL,
    selection_id  TEXT NOT NULL,
    handicap      REAL NOT NULL DEFAULT 0,
    runner_name   TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    last_seen_at  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (market_id, selection_id, handicap)
);
CREATE TABLE IF NOT EXISTS betfair_local_name_mappings (
    sport           TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    mapped_name     TEXT,
    entity_type     TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    last_seen_at    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sport, normalized_name)
);
CREATE TABLE IF NOT EXISTS betfair_sync_runs (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER,
    finished_at INTEGER,
    status     TEXT,
    summary    TEXT
);
CREATE TABLE IF NOT EXISTS betfair_meta (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


def _norm_handicap(handicap) -> float:
    """Handicap normalizzato a float (None/'' → 0.0): rende stabile la chiave della
    selezione (la tripla market_id+selection_id+handicap)."""
    if handicap in (None, ""):
        return 0.0
    try:
        return float(handicap)
    except (TypeError, ValueError):
        return 0.0


class BetfairLocalDB:
    """Dizionario Betfair locale su SQLite. `db_path` può essere un file o
    ``":memory:"`` (test). Crea lo schema all'apertura (idempotente)."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        # Su un'installazione nuova la cartella AppData potrebbe non esistere ancora:
        # crearla PRIMA di connettere, altrimenti sqlite solleva "unable to open
        # database file" al primo uso del dizionario (Codex). Non per ":memory:".
        if db_path and db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        # check_same_thread=False: la sync può girare in un worker; le scritture sono
        # serializzate dal lock sottostante. `timeout`: busy timeout esteso (vedi
        # `_BUSY_TIMEOUT_S`) per non fallire subito su "database is locked" concorrente.
        self._conn = sqlite3.connect(db_path, check_same_thread=False,
                                     timeout=_BUSY_TIMEOUT_S)
        self._conn.row_factory = sqlite3.Row
        # PRAGMA busy_timeout esplicito (ms): ridondante con `timeout=` ma rende l'intento
        # durevole e ispezionabile, e copre il caso in cui il valore venga reimpostato
        # da un PRAGMA successivo (#184 LOW).
        self._conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_S * 1000}")
        # RLock (rientrante): `transaction()` tiene il lock mentre i metodi di scrittura
        # lo riacquisiscono. `_tx_depth>0` differisce i commit fino a fine transazione.
        self._lock = threading.RLock()
        self._tx_depth = 0
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.commit()

    def _commit_if_needed(self) -> None:
        """Commit solo se NON siamo dentro una `transaction()` (altrimenti il commit
        è rimandato alla fine, così un fallimento a metà sync fa rollback di tutto)."""
        if self._tx_depth == 0:
            self._conn.commit()

    def transaction(self):
        """Context manager: raggruppa più scritture in UNA transazione. Se il blocco
        solleva, fa `rollback` (il dizionario non resta in uno stato parziale); se
        completa, fa `commit`. Rientrante (nesting → un solo commit esterno)."""
        db = self

        class _Tx:
            def __enter__(self_):
                db._lock.acquire()
                db._tx_depth += 1
                return db

            def __exit__(self_, exc_type, exc, tb):
                try:
                    if db._tx_depth == 1:
                        if exc_type is None:
                            db._conn.commit()
                        else:
                            db._conn.rollback()
                finally:
                    db._tx_depth -= 1
                    db._lock.release()
                return False

        return _Tx()

    def _migrate(self) -> None:
        """Migrazioni idempotenti per DB creati da versioni precedenti dello schema.

        `CREATE TABLE IF NOT EXISTS` non aggiunge colonne nuove a una tabella già
        esistente: qui aggiungiamo le colonne mancanti con `ALTER TABLE ADD COLUMN`
        (no-op se già presenti). PR-P6: `participant_1`/`participant_2` su eventi."""
        cols = {r["name"] for r in
                self._conn.execute("PRAGMA table_info(betfair_events)").fetchall()}
        for col in ("participant_1", "participant_2"):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE betfair_events ADD COLUMN {col} TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── upsert (l'upsert NON duplica: chiave naturale + ON CONFLICT) ──────────

    def upsert_sport(self, event_type_id, name, *, seen_at: int = 0) -> None:
        self._exec(
            """INSERT INTO betfair_sports (event_type_id, name, active, last_seen_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(event_type_id) DO UPDATE SET
                 name=excluded.name, active=1, last_seen_at=excluded.last_seen_at""",
            (str(event_type_id), name, int(seen_at)))

    def upsert_competition(self, competition_id, event_type_id, name, *, seen_at=0):
        self._exec(
            """INSERT INTO betfair_competitions
                 (competition_id, event_type_id, name, active, last_seen_at)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(competition_id) DO UPDATE SET
                 event_type_id=excluded.event_type_id, name=excluded.name,
                 active=1, last_seen_at=excluded.last_seen_at""",
            (str(competition_id), str(event_type_id), name, int(seen_at)))

    def upsert_event(self, event_id, event_type_id, competition_id, name,
                     open_date=None, participant_1=None, participant_2=None, *,
                     seen_at=0):
        self._exec(
            """INSERT INTO betfair_events
                 (event_id, event_type_id, competition_id, name, open_date,
                  participant_1, participant_2, active, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(event_id) DO UPDATE SET
                 event_type_id=excluded.event_type_id,
                 competition_id=excluded.competition_id, name=excluded.name,
                 open_date=excluded.open_date,
                 participant_1=excluded.participant_1,
                 participant_2=excluded.participant_2, active=1,
                 last_seen_at=excluded.last_seen_at""",
            (str(event_id), str(event_type_id), str(competition_id), name,
             open_date, participant_1, participant_2, int(seen_at)))

    def upsert_market(self, market_id, event_id, event_type_id, market_name,
                      market_type=None, *, seen_at=0):
        self._exec(
            """INSERT INTO betfair_markets
                 (market_id, event_id, event_type_id, market_name, market_type,
                  active, last_seen_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(market_id) DO UPDATE SET
                 event_id=excluded.event_id, event_type_id=excluded.event_type_id,
                 market_name=excluded.market_name, market_type=excluded.market_type,
                 active=1, last_seen_at=excluded.last_seen_at""",
            (str(market_id), str(event_id), str(event_type_id), market_name,
             market_type, int(seen_at)))

    def upsert_selection(self, market_id, selection_id, runner_name,
                         handicap=0.0, *, seen_at=0):
        self._exec(
            """INSERT INTO betfair_selections
                 (market_id, selection_id, handicap, runner_name, active, last_seen_at)
               VALUES (?, ?, ?, ?, 1, ?)
               ON CONFLICT(market_id, selection_id, handicap) DO UPDATE SET
                 runner_name=excluded.runner_name, active=1,
                 last_seen_at=excluded.last_seen_at""",
            (str(market_id), str(selection_id), _norm_handicap(handicap),
             runner_name, int(seen_at)))

    def upsert_name_mapping(self, sport, normalized_name, mapped_name,
                            entity_type=None, *, seen_at=0):
        self._exec(
            """INSERT INTO betfair_local_name_mappings
                 (sport, normalized_name, mapped_name, entity_type, active, last_seen_at)
               VALUES (?, ?, ?, ?, 1, ?)
               ON CONFLICT(sport, normalized_name) DO UPDATE SET
                 mapped_name=excluded.mapped_name, entity_type=excluded.entity_type,
                 active=1, last_seen_at=excluded.last_seen_at""",
            (str(sport), str(normalized_name), mapped_name, entity_type, int(seen_at)))

    # ── marker di sync (unico e monotòno, persistito) ────────────────────────

    def new_sync_marker(self) -> int:
        """Ritorna un marker di sync **strettamente crescente** e persistito.

        I chiamanti DEVONO usare questo valore come `seen_at` degli upsert di una
        sync (NON il wall-clock): due run non condivideranno mai lo stesso marker —
        nemmeno un retry nello stesso secondo — quindi `deactivate_unseen` distingue
        sempre le righe della run corrente da quelle delle run precedenti (Codex).
        Il contatore vive in `betfair_meta` e sopravvive ai riavvii."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO betfair_meta(key, value) VALUES('run_counter', 0) "
                "ON CONFLICT(key) DO NOTHING")
            self._conn.execute(
                "UPDATE betfair_meta SET value = value + 1 WHERE key='run_counter'")
            row = self._conn.execute(
                "SELECT value FROM betfair_meta WHERE key='run_counter'").fetchone()
            self._commit_if_needed()
            return int(row["value"])

    # ── sync run ─────────────────────────────────────────────────────────────

    def record_sync_run(self, started_at, finished_at, status, summary="") -> int:
        """Registra una sync run e ritorna il suo `run_id`."""
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO betfair_sync_runs (started_at, finished_at, status, summary)
                   VALUES (?, ?, ?, ?)""",
                (started_at, finished_at, status, summary))
            self._commit_if_needed()
            return cur.lastrowid

    # ── deattivazione dei record non più visti ───────────────────────────────

    def deactivate_unseen(self, table, seen_at: int, *, scope_value=None) -> int:
        """Marca `active=0` i record della tabella **non visti** in questa sync, cioè
        con `last_seen_at < seen_at`. Ritorna il numero di righe disattivate.

        `seen_at` DEVE essere il marker della sync corrente ottenuto da
        `new_sync_marker()` (strettamente crescente): così i record stampati da run
        precedenti hanno `last_seen_at < seen_at` e vengono disattivati, mentre quelli
        rivisti in questa run (stampati con `seen_at`) restano attivi.

        `scope_value` (opzionale) restringe alla colonna di scoping della tabella
        (es. `event_type_id` per eventi/competizioni, `event_id` per i mercati,
        `market_id` per le selezioni): così sincronizzare un solo sport non disattiva
        i record degli altri. Il nome tabella è validato contro una whitelist."""
        if table not in _SCOPED:
            raise ValueError(f"tabella non valida per deactivate_unseen: {table!r}")
        scope_col = _SCOPED[table]
        sql = f"UPDATE {table} SET active=0 WHERE active=1 AND last_seen_at < ?"
        params = [int(seen_at)]
        if scope_value is not None:
            if scope_col is None:
                raise ValueError(f"{table} non supporta uno scope")
            sql += f" AND {scope_col} = ?"
            params.append(str(scope_value))
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._commit_if_needed()
            return cur.rowcount

    # ── letture (per viewer/test) ────────────────────────────────────────────

    def count_active(self, table) -> int:
        if table not in _SCOPED and table != "betfair_selections":
            raise ValueError(f"tabella non valida: {table!r}")
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE active=1").fetchone()
            return int(row["n"])

    def market_ids_for_sports(self, event_type_ids):
        """Tutti i `market_id` (anche inattivi) dei mercati che appartengono agli
        sport dati: serve al sync per disattivare le selezioni dei mercati spariti,
        non solo di quelli rivisti (Codex)."""
        ids = [str(x) for x in (event_type_ids or ())]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT market_id FROM betfair_markets WHERE event_type_id IN ({placeholders})",
                ids).fetchall()
            return [r["market_id"] for r in rows]

    def get_selections(self, market_id):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM betfair_selections WHERE market_id=? ORDER BY selection_id",
                (str(market_id),)).fetchall()
            return [dict(r) for r in rows]

    def get_events(self):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM betfair_events ORDER BY event_id").fetchall()
            return [dict(r) for r in rows]

    def fetchall(self, table):
        """Tutte le righe di una tabella del dizionario (whitelist), per il viewer."""
        valid = set(_SCOPED) | {"betfair_selections", "betfair_local_name_mappings",
                                "betfair_sync_runs"}
        if table not in valid:
            raise ValueError(f"tabella non valida: {table!r}")
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
            return [dict(r) for r in rows]

    # ── interno ──────────────────────────────────────────────────────────────

    def _exec(self, sql, params):
        with self._lock:
            self._conn.execute(sql, params)
            self._commit_if_needed()
