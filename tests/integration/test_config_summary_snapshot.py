"""Glue `App._config_summary_snapshot` (#293 slice 3): stato Betfair best-effort + NON
bloccante durante una sync.

La logica di aggregazione è pura in `config_summary` (test dedicati); qui si verifica la
glue GUI: lo snapshot legge la config viva e lo stato Betfair in modo **fail-soft** (DB
occupato/assente o sessione non inizializzata → False, mai crash) e — punto chiave (Fable
#337) — **non tocca il DB durante una sync** (`is_syncing`), per non far attendere il thread
GUI sul lock del dizionario. `App` è importata con `customtkinter` stubbato (`app_mod`).
"""

import pytest

from xtrader_bridge import config_summary


class _DB:
    def __init__(self, count, *, raises=False):
        self._count = count
        self._raises = raises
        self.calls = []

    def count_active(self, table):
        self.calls.append(table)
        if self._raises:
            raise RuntimeError("db locked")
        return self._count


class _Engine:
    def __init__(self, *, syncing, db):
        self.is_syncing = syncing
        self.db = db


class _Session:
    def __init__(self, logged_in):
        self.is_logged_in = logged_in


def _snapshot(app_mod, *, cfg=None, syncing=False, count=0, db_raises=False,
              logged_in=False, session_raises=False):
    app = object.__new__(app_mod.App)
    db = _DB(count, raises=db_raises)
    app._db = db                                   # esposto per le asserzioni sulle chiamate
    app._load_config = lambda: (cfg or {})
    app._betfair_sync_engine = lambda: _Engine(syncing=syncing, db=db)

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
    assert app._db.calls == ["betfair_events"]     # DB letto (nessuna sync in corso)


def test_snapshot_non_sincronizzato_quando_db_vuoto(app_mod):
    _app, s = _snapshot(app_mod, count=0, logged_in=False)
    assert s.betfair_synced is False and s.betfair_logged_in is False


def test_snapshot_non_legge_il_db_durante_una_sync(app_mod):
    # Fable #337: con una sync in corso lo snapshot NON deve chiamare count_active (niente
    # attesa sul lock del dizionario nel thread GUI) → best-effort «non sincronizzato».
    app, s = _snapshot(app_mod, count=99, syncing=True, logged_in=True)
    assert app._db.calls == []                     # DB MAI toccato durante la sync
    assert s.betfair_synced is False               # degrada, non blocca
    assert s.betfair_logged_in is True             # il login non dipende dal DB


def test_snapshot_fail_soft_su_db_che_solleva(app_mod):
    # DB occupato/assente → count_active solleva → synced degrada a False, nessun crash.
    _app, s = _snapshot(app_mod, count=1, db_raises=True, logged_in=True)
    assert s.betfair_synced is False and s.betfair_logged_in is True


def test_snapshot_fail_soft_su_sessione_assente(app_mod):
    # Sessione non inizializzata → is_logged_in solleva → logged_in degrada a False.
    _app, s = _snapshot(app_mod, count=3, logged_in=True, session_raises=True)
    assert s.betfair_synced is True and s.betfair_logged_in is False


def test_snapshot_riflette_la_config_viva(app_mod):
    # La config viva arriva al riepilogo attraverso la glue: modalità REALE dal cfg.
    _app, s = _snapshot(app_mod, cfg={"dry_run": False}, count=0)
    assert s.real_mode is True
    _app2, s2 = _snapshot(app_mod, cfg={"dry_run": True}, count=0)
    assert s2.real_mode is False
