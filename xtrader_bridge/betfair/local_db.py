"""Dizionario Betfair locale multi-sport (issue #86 PR-P5) — SQLite, solo locale.

Tabelle locali del dizionario (tutto sul PC/VPS, **nessun cloud, nessun
export/import**): `betfair_sports`, `betfair_competitions`, `betfair_events`,
`betfair_markets`, `betfair_selections`, `betfair_sync_runs`,
`betfair_local_name_mappings`, `betfair_known_teams`, `betfair_known_market_terms`.

`betfair_known_teams` (#282) e `betfair_known_market_terms` (#283) sono le tabelle
PERMANENTI: accumulano i valori raccolti durante la sync e **non hanno colonna
`active`**, quindi il mark-and-sweep (`deactivate_unseen`, che opera solo sulle tabelle
in `_SCOPED`) non le tocca MAI. `betfair_known_teams` conserva i nomi squadra (→
EventName); `betfair_known_market_terms` conserva i valori universali di
MarketType/MarketName/SelectionName come TUPLA coerente per sport (B3 #259: coerenza
nome mercato↔selezione), «diretti» (nessuna mappatura: il nome Betfair IT è già il nome
canonico XTrader). Gli ID (`MarketId`/`SelectionId`) restano invece effimeri come prima:
nomi/valori sopravvivono alla fine dell'evento, gli ID no.

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

import logging
import os
import sqlite3
import threading

# Fonte UNICA della normalizzazione nomi (case/spazi-insensibile): la stessa usata dal
# dizionario XTrader e dalla mappatura nomi. Riusarla qui garantisce che la chiave dei
# nomi squadra permanenti (#282) coincida ESATTAMENTE con quella con cui la mappatura
# nomi della GUI li cercherà (nessuna implementazione divergente).
from ..dizionario import normalize as _normalize_name

# Quante righe di `betfair_sync_runs` conservare: la tabella registra ~1 riga per
# sync (storico) e altrimenti crescerebbe all'infinito (#184 LOW). 200 run = oltre
# 6 mesi a una sync al giorno, abbastanza per lo storico ma con tabella limitata.
_SYNC_RUNS_KEEP = 200

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
CREATE TABLE IF NOT EXISTS betfair_known_teams (
    sport           TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    display_name    TEXT,
    first_seen_at   INTEGER NOT NULL DEFAULT 0,
    last_seen_at    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sport, normalized_name)
);
CREATE TABLE IF NOT EXISTS betfair_known_market_terms (
    sport                TEXT NOT NULL,
    market_type          TEXT NOT NULL DEFAULT '',
    normalized_market    TEXT NOT NULL,
    market_name          TEXT,
    normalized_selection TEXT NOT NULL DEFAULT '',
    selection_name       TEXT,
    first_seen_at        INTEGER NOT NULL DEFAULT 0,
    last_seen_at         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sport, market_type, normalized_market, normalized_selection)
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


_LOG = logging.getLogger(__name__)


def _norm_handicap(handicap):
    """Handicap normalizzato a float (None/'' → 0.0): rende stabile la chiave della
    selezione (la tripla market_id+selection_id+handicap).

    P3-21 #76: un valore NON numerico («abc») ritorna ``None`` — NON più coercito a
    ``0.0``: l'handicap è parte della **chiave primaria** della selezione, e la
    coercizione faceva collidere la riga malformata con la selezione legittima a
    handicap 0 (upsert che ne sovrascrive il runner_name → dizionario corrotto).
    Il chiamante (`upsert_selection`) SCARTA la riga (fail-closed) con warning."""
    if handicap in (None, ""):
        return 0.0
    try:
        return float(handicap)
    except (TypeError, ValueError):
        return None


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

    def acquire_read(self, *, blocking: bool = False) -> bool:
        """Acquisisce il lock del DB per una LETTURA di sola consultazione (viewer del
        dizionario). Con ``blocking=False`` NON attende: ritorna ``False`` se una sync
        Betfair tiene ora il lock — `transaction()` lo mantiene attraverso le chiamate di
        rete del catalogue — invece di bloccare il chiamante. Il viewer gira sul thread Tk,
        quindi bloccare freezerebbe la GUI finché la sync di rete non finisce (Codex #175).
        Va SEMPRE bilanciato con `release_read()` (vedi
        `DictionaryViewerController.view_if_free`)."""
        return self._lock.acquire(blocking=blocking)

    def release_read(self) -> None:
        """Rilascia il lock preso da `acquire_read` (RLock rientrante: un release per ogni
        acquire)."""
        self._lock.release()

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
        self._migrate_market_terms_pk()

    def _migrate_market_terms_pk(self) -> None:
        """#283/#326: la PK di `betfair_known_market_terms` è passata da 3 a 4 colonne
        (aggiunto `market_type`, così due mercati con lo stesso nome ma tipo diverso non
        collidono). `CREATE TABLE IF NOT EXISTS` NON altera una tabella già creata con la
        vecchia PK a 3 colonne → l'`ON CONFLICT` a 4 colonne solleverebbe `OperationalError`
        a runtime su un DB preesistente. Se troviamo la vecchia forma (colonna `market_type`
        presente ma NON in PK), ricreiamo la tabella copiando i dati (`market_type` NULL →
        ''). La tabella è un cache **permanente ma ri-derivabile** dalla sync: la copia
        preserva comunque `first_seen_at`. No-op su DB nuovi (PK già a 4 colonne) o senza la
        tabella (Fable/GLM/GPT #326)."""
        info = self._conn.execute(
            "PRAGMA table_info(betfair_known_market_terms)").fetchall()
        if not info:
            return                               # tabella non ancora creata → niente da migrare
        mt = next((r for r in info if r["name"] == "market_type"), None)
        if mt is None or int(mt["pk"]) != 0:
            # No-op se: market_type già in PK (nuova forma), OPPURE colonna `market_type`
            # assente. Quest'ultimo caso NON è mai esistito in produzione: la tabella è
            # NUOVA in #283 e ha SEMPRE avuto la colonna `market_type` (la sola forma
            # «legacy» è la PK a 3 colonne del commit intermedio di questa stessa PR, che la
            # colonna ce l'ha). Nessuno schema senza `market_type` da migrare (Fable #326).
            return
        # La tabella non ha indici/trigger secondari (solo la PK inline, ricreata dal
        # CREATE sotto): il by-recreate non perde oggetti di schema (Fugu #326).
        # Migrazione ATOMICA in una singola transazione (SQLite supporta il DDL
        # transazionale): un crash tra RENAME e INSERT fa ROLLBACK all'originale, così non
        # resta un `_bkmt_old` orfano né la tabella live mancante (GLM/GPT #326).
        # `BEGIN IMMEDIATE` prende subito il write-lock: un secondo processo aspetta il
        # busy_timeout invece di correre in parallelo. `executescript` fa un COMMIT implicito
        # iniziale (nessuna transazione pendente), poi esegue lo script transazionale.
        # NB: nessuna collisione possibile nell'INSERT..SELECT — la vecchia PK a 3 colonne
        # garantiva già l'unicità di (sport, normalized_market, normalized_selection);
        # aggiungere market_type può solo rendere le chiavi PIÙ distinte, mai fonderle.
        try:
            self._conn.executescript(
                """
                BEGIN IMMEDIATE;
                DROP TABLE IF EXISTS _bkmt_old;
                ALTER TABLE betfair_known_market_terms RENAME TO _bkmt_old;
                CREATE TABLE betfair_known_market_terms (
                    sport                TEXT NOT NULL,
                    market_type          TEXT NOT NULL DEFAULT '',
                    normalized_market    TEXT NOT NULL,
                    market_name          TEXT,
                    normalized_selection TEXT NOT NULL DEFAULT '',
                    selection_name       TEXT,
                    first_seen_at        INTEGER NOT NULL DEFAULT 0,
                    last_seen_at         INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (sport, market_type, normalized_market, normalized_selection)
                );
                INSERT INTO betfair_known_market_terms
                    (sport, market_type, normalized_market, market_name,
                     normalized_selection, selection_name, first_seen_at, last_seen_at)
                SELECT sport, COALESCE(market_type, ''), normalized_market, market_name,
                       normalized_selection, selection_name, first_seen_at, last_seen_at
                FROM _bkmt_old;
                DROP TABLE _bkmt_old;
                COMMIT;
                """)
        except sqlite3.Error:                    # atomicità: rollback all'originale e rilancia
            self._conn.rollback()
            raise

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
                         handicap=0.0, *, seen_at=0) -> bool:
        """Inserisce/aggiorna una selezione. Ritorna ``True`` se la riga è stata
        scritta, ``False`` se SCARTATA per handicap non numerico (P3-21 #76:
        l'handicap è parte della PK — coercirlo a 0.0 farebbe collidere la riga
        malformata con la selezione legittima a handicap 0, sovrascrivendone il
        runner_name). Fail-closed: meglio una selezione in meno nel dizionario che
        una voce corrotta; il warning dice quale riga è stata saltata."""
        hcap = _norm_handicap(handicap)
        if hcap is None:
            _LOG.warning(
                "betfair_selections: handicap NON numerico %r per market=%s "
                "selection=%s -> riga SCARTATA (fail-closed, P3-21 #76).",
                handicap, market_id, selection_id)
            return False
        self._exec(
            """INSERT INTO betfair_selections
                 (market_id, selection_id, handicap, runner_name, active, last_seen_at)
               VALUES (?, ?, ?, ?, 1, ?)
               ON CONFLICT(market_id, selection_id, handicap) DO UPDATE SET
                 runner_name=excluded.runner_name, active=1,
                 last_seen_at=excluded.last_seen_at""",
            (str(market_id), str(selection_id), hcap,
             runner_name, int(seen_at)))
        return True

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

    def upsert_known_team(self, sport, display_name, *, seen_at: int = 0) -> bool:
        """Accumula un nome squadra **permanente** per `sport` (#282). Ritorna ``True``
        se un nome è stato scritto, ``False`` se saltato (nome vuoto dopo normalizzazione).

        La chiave è `(sport, normalized_name)` con `normalized_name` = normalizzazione
        canonica (case/spazi-insensibile), la **stessa** della mappatura nomi: così un
        nome con maiuscole/spazi diversi NON crea un duplicato. Idempotente: alla
        seconda vista aggiorna `display_name` all'ultima grafia e `last_seen_at`, ma
        **NON** cambia `first_seen_at` (resta la prima volta). La tabella non ha `active`:
        non viene mai disattivata dal mark-and-sweep → nomi **per sempre**."""
        name = str(display_name or "").strip()
        norm = _normalize_name(name) if name else ""
        if not norm:
            return False
        self._exec(
            """INSERT INTO betfair_known_teams
                 (sport, normalized_name, display_name, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(sport, normalized_name) DO UPDATE SET
                 display_name=excluded.display_name,
                 last_seen_at=excluded.last_seen_at""",
            (str(sport), norm, name, int(seen_at), int(seen_at)))
        return True

    def upsert_market_term(self, sport, market_type, market_name,
                           selection_name="", *, seen_at: int = 0) -> bool:
        """Accumula un valore PERMANENTE di mercato/selezione per `sport` (#283), «diretto»
        (nessuna mappatura: il nome Betfair IT è già il nome canonico XTrader). Ritorna
        ``True`` se una riga è stata scritta, ``False`` se saltata (MarketName vuoto).

        Ogni riga è la TUPLA coerente `(sport, market_type, market_name, selection_name)`
        (B3 #259: coerenza nome mercato↔selezione). `selection_name` vuoto = riga «àncora»
        del solo mercato (il mercato esiste ma non contribuisce una selezione universale —
        vedi l'allowlist dell'harvest); una selezione universale (Over/Under, Sì/No, …) è
        una riga con entrambi valorizzati. Chiave `(sport, market_type, normalized_market,
        normalized_selection)` con normalizzazione canonica (case/spazi-insensibile): il
        `market_type` è PARTE della chiave così due mercati con lo STESSO nome ma tipo
        diverso NON collidono (niente last-write-wins sul tipo → tupla sempre coerente,
        Fable/GPT #326). Idempotente: alla re-visione aggiorna le grafie e `last_seen_at`,
        MAI `first_seen_at`. La tabella non ha `active` e resta fuori da `_SCOPED` → il
        mark-and-sweep non la tocca: valori **per sempre**."""
        market = str(market_name or "").strip()
        norm_market = _normalize_name(market) if market else ""
        if not norm_market:
            return False
        selection = str(selection_name or "").strip()
        norm_selection = _normalize_name(selection) if selection else ""
        mtype = str(market_type or "").strip()          # '' (non NULL): fa parte della PK
        self._exec(
            """INSERT INTO betfair_known_market_terms
                 (sport, market_type, normalized_market, market_name,
                  normalized_selection, selection_name, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(sport, market_type, normalized_market, normalized_selection)
               DO UPDATE SET
                 market_name=excluded.market_name,
                 selection_name=excluded.selection_name,
                 last_seen_at=excluded.last_seen_at""",
            (str(sport), mtype, norm_market, market,
             norm_selection, selection or None, int(seen_at), int(seen_at)))
        return True

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
        """Registra una sync run e ritorna il suo `run_id`. Subito dopo **pota** le run
        più vecchie oltre il cap (`_SYNC_RUNS_KEEP`), così `betfair_sync_runs` non cresce
        all'infinito (#184 LOW). Insert + prune stanno sotto lo stesso lock e nello stesso
        commit (se dentro una `transaction()`, vengono committati/rollbackati con essa)."""
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO betfair_sync_runs (started_at, finished_at, status, summary)
                   VALUES (?, ?, ?, ?)""",
                (started_at, finished_at, status, summary))
            run_id = cur.lastrowid
            self._prune_sync_runs_locked(_SYNC_RUNS_KEEP)
            self._commit_if_needed()
            return run_id

    def prune_sync_runs(self, keep: int = _SYNC_RUNS_KEEP) -> int:
        """Elimina le run più vecchie tenendo solo le `keep` più recenti (per `run_id`,
        che è AUTOINCREMENT monotòno). Ritorna quante righe ha eliminato. `keep<=0` non
        elimina nulla (guardia: non svuota la tabella per errore)."""
        with self._lock:
            n = self._prune_sync_runs_locked(keep)
            self._commit_if_needed()
            return n

    def _prune_sync_runs_locked(self, keep: int) -> int:
        """Prune di `betfair_sync_runs` assumendo il lock già tenuto (nessun commit qui:
        lo fa il chiamante, così l'operazione resta atomica con l'insert/la transazione)."""
        if keep is None or keep <= 0:
            return 0
        cur = self._conn.execute(
            """DELETE FROM betfair_sync_runs
               WHERE run_id NOT IN (
                   SELECT run_id FROM betfair_sync_runs ORDER BY run_id DESC LIMIT ?
               )""",
            (int(keep),))
        return cur.rowcount

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

    def known_teams(self, sport=None):
        """Nomi squadra **permanenti** (#282), opzionalmente filtrati per `sport`,
        ordinati per `display_name`. Ritorna una lista di dict
        (`sport`, `normalized_name`, `display_name`, `first_seen_at`, `last_seen_at`).
        Nessun concetto di `active`: sono tutti permanenti. Serve al menù/mappatura nomi
        della GUI (PR 11) e ai test."""
        with self._lock:
            if sport is None:
                rows = self._conn.execute(
                    "SELECT * FROM betfair_known_teams "
                    "ORDER BY sport, display_name").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM betfair_known_teams WHERE sport=? "
                    "ORDER BY display_name", (str(sport),)).fetchall()
            return [dict(r) for r in rows]

    def count_known_teams(self, sport=None) -> int:
        """Quanti nomi squadra permanenti sono salvati (opz. per `sport`)."""
        with self._lock:
            if sport is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM betfair_known_teams").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM betfair_known_teams WHERE sport=?",
                    (str(sport),)).fetchone()
            return int(row["n"])

    def known_market_types(self, sport=None):
        """MarketType permanenti distinti (#283), opz. per `sport`, ordinati. Solo valori
        non vuoti (le righe di un mercato senza market_type sono ignorate). Serve alle
        tendine del Parser (PR 13) e ai test."""
        return self._distinct_market_terms("market_type", sport)

    def known_market_names(self, sport=None):
        """MarketName permanenti distinti (#283), opz. per `sport`, ordinati (solo non vuoti)."""
        return self._distinct_market_terms("market_name", sport)

    def _distinct_market_terms(self, column, sport):
        """Valori DISTINTI non vuoti di una colonna di `betfair_known_market_terms`, opz.
        per `sport`, ordinati. `column` è un nome FISSO scelto dal codice (mai input
        utente): whitelist esplicita per non costruire SQL da input non controllato."""
        if column not in ("market_type", "market_name"):
            raise ValueError(f"colonna non valida: {column!r}")
        with self._lock:
            sql = (f"SELECT DISTINCT {column} AS v FROM betfair_known_market_terms "
                   f"WHERE {column} IS NOT NULL AND {column} <> ''")
            params = []
            if sport is not None:
                sql += " AND sport=?"
                params.append(str(sport))
            sql += " ORDER BY v"
            rows = self._conn.execute(sql, params).fetchall()
            return [r["v"] for r in rows]

    def known_selection_names(self, sport=None, market=None):
        """SelectionName permanenti distinti (#283), opz. per `sport` e per mercato
        (`market`, confrontato sul nome **normalizzato** → resta coerente con il mercato,
        invariante «selezione appartiene al mercato»). Ordinati; esclude le righe àncora
        (selezione vuota)."""
        with self._lock:
            sql = ("SELECT DISTINCT selection_name FROM betfair_known_market_terms "
                   "WHERE selection_name IS NOT NULL AND selection_name <> ''")
            params = []
            if sport is not None:
                sql += " AND sport=?"
                params.append(str(sport))
            if market is not None:
                sql += " AND normalized_market=?"
                params.append(_normalize_name(str(market)))
            sql += " ORDER BY selection_name"
            rows = self._conn.execute(sql, params).fetchall()
            return [r["selection_name"] for r in rows]

    def count_market_terms(self, sport=None) -> int:
        """Quante righe permanenti di mercato/selezione sono salvate (opz. per `sport`)."""
        with self._lock:
            if sport is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM betfair_known_market_terms").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM betfair_known_market_terms WHERE sport=?",
                    (str(sport),)).fetchone()
            return int(row["n"])

    def delete_known_team(self, sport, normalized_name) -> int:
        """Elimina UN nome squadra permanente (#282 ripulitura manuale), per chiave esatta
        (`sport`, `normalized_name`). Ritorna quante righe ha eliminato (0 se non c'era).

        È l'**unico** modo per togliere un nome permanente: il mark-and-sweep non tocca
        `betfair_known_teams`, quindi un nome obsoleto/errato (squadra retrocessa/rinominata)
        resterebbe per sempre finché non lo si elimina qui a mano. Scoping esatto: elimina
        solo quella coppia, mai altri sport o nomi."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM betfair_known_teams WHERE sport=? AND normalized_name=?",
                (str(sport), str(normalized_name)))
            self._commit_if_needed()
            return cur.rowcount

    def fetchall(self, table):
        """Tutte le righe di una tabella del dizionario (whitelist), per il viewer."""
        valid = set(_SCOPED) | {"betfair_selections", "betfair_local_name_mappings",
                                "betfair_known_teams", "betfair_known_market_terms",
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
