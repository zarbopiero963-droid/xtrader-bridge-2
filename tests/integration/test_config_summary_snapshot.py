"""Glue `App._config_summary_snapshot` (#293 slice 3): config VIVA + stato Betfair
best-effort NON bloccante durante una sync.

La logica di aggregazione è pura in `config_summary` (test dedicati); qui si verifica la
glue GUI:
- legge la config **viva** `self._config` (autoritativa dopo un save fallito), non il disco;
- lo stato Betfair usa il probe **non bloccante** `db.acquire_read(blocking=False)` (stesso
  pattern di `_known_betfair_teams`): se una sync tiene il lock → si salta la lettura
  (best-effort «non sincronizzato»), senza attesa sul thread GUI (CodeRabbit/Fable #337);
- fail-soft su DB che solleva / sessione assente.
`App` è importata con `customtkinter` stubbato (`app_mod`).
"""

from xtrader_bridge import config_summary


class _DB:
    def __init__(self, count, *, raises=False, busy=False):
        self._count = count
        self._raises = raises
        self._busy = busy
        self.calls = []
        self.acquired = 0
        self.released = 0

    def acquire_read(self, *, blocking=False):
        # Non bloccante: durante una sync (busy) il lock non è ottenibile → False.
        if self._busy:
            return False
        self.acquired += 1
        return True

    def release_read(self):
        self.released += 1

    def count_active(self, table):
        self.calls.append(table)
        if self._raises:
            raise RuntimeError("db locked")
        return self._count


class _Engine:
    def __init__(self, db):
        self.db = db


class _Session:
    def __init__(self, logged_in):
        self.is_logged_in = logged_in


def _snapshot(app_mod, *, cfg=None, count=0, busy=False, db_raises=False, db_none=False,
              logged_in=False, session_raises=False, live_config=True):
    app = object.__new__(app_mod.App)
    db = None if db_none else _DB(count, raises=db_raises, busy=busy)
    app._db = db
    # Config viva autoritativa: la glue deve leggere self._config, non il disco.
    if live_config:
        app._config = (cfg or {})
        app._load_config = lambda: (_ for _ in ()).throw(
            AssertionError("non deve leggere il disco quando c'è config viva"))
    else:
        app._config = None                         # forza il fallback su _load_config
        app._load_config = lambda: (cfg or {})
    app._betfair_sync_engine = lambda: _Engine(db)

    def _sess():
        if session_raises:
            raise RuntimeError("no session")
        return _Session(logged_in)

    app._betfair_session_obj = _sess
    return app, app_mod.App._config_summary_snapshot(app)


def test_snapshot_sincronizzato_e_login(app_mod):
    app, s = _snapshot(app_mod, count=5, logged_in=True)
    assert isinstance(s, config_summary.ConfigSummary)
    assert s.betfair_synced is True and s.betfair_logged_in is True
    assert app._db.calls == ["betfair_events"]
    assert app._db.acquired == app._db.released == 1     # lock bilanciato (acquire/release)


def test_snapshot_non_sincronizzato_quando_db_vuoto(app_mod):
    _app, s = _snapshot(app_mod, count=0, logged_in=False)
    assert s.betfair_synced is False and s.betfair_logged_in is False


def test_snapshot_non_legge_il_db_durante_una_sync(app_mod):
    # CodeRabbit/Fable #337: con una sync in corso `acquire_read` fallisce (non bloccante)
    # → count_active NON viene chiamato e non si tiene alcun lock → «non sincronizzato».
    app, s = _snapshot(app_mod, count=99, busy=True, logged_in=True)
    assert app._db.calls == []                          # DB MAI letto durante la sync
    assert app._db.acquired == 0 and app._db.released == 0
    assert s.betfair_synced is False
    assert s.betfair_logged_in is True                  # il login non dipende dal DB


def test_snapshot_rilascia_il_lock_anche_se_count_solleva(app_mod):
    # DB occupato/assente → count_active solleva → synced degrada a False MA il lock preso
    # va comunque rilasciato (finally), senza crash.
    app, s = _snapshot(app_mod, count=1, db_raises=True, logged_in=True)
    assert s.betfair_synced is False and s.betfair_logged_in is True
    assert app._db.acquired == 1 and app._db.released == 1


def test_snapshot_fail_soft_su_db_none(app_mod):
    # engine costruito ma DB non aperto (None) → nessuna lettura, synced False, nessun crash.
    _app, s = _snapshot(app_mod, db_none=True, logged_in=True)
    assert s.betfair_synced is False and s.betfair_logged_in is True


def test_snapshot_fail_soft_su_sessione_assente(app_mod):
    _app, s = _snapshot(app_mod, count=3, logged_in=True, session_raises=True)
    assert s.betfair_synced is True and s.betfair_logged_in is False


def test_snapshot_usa_la_config_viva_non_il_disco(app_mod):
    # La modalità arriva dalla config VIVA self._config; _load_config solleverebbe se toccato.
    _app, s = _snapshot(app_mod, cfg={"dry_run": False}, count=0)
    assert s.real_mode is True


def test_snapshot_fallback_al_disco_senza_config_viva(app_mod):
    # Senza config viva (self._config non-dict) si ricade su _load_config.
    _app, s = _snapshot(app_mod, cfg={"dry_run": True}, count=0, live_config=False)
    assert s.real_mode is False
