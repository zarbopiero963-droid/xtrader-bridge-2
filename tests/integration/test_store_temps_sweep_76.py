"""P3-17 audit #76 — sweep dei tmp orfani degli STORE all'avvio (comportamentale).

Vedi `tests/unit/test_store_temps_warn_dedup_76.py` per il contesto: qui i due test
che esercitano il metodo REALE di `App` (via `__new__`, senza GUI: stub tkinter del
conftest integration) su file veri in tmp."""

import pytest


def _app_stub():
    from xtrader_bridge import app as app_mod
    a = app_mod.App.__new__(app_mod.App)
    logs = []
    a._log = logs.append
    return app_mod, a, logs


def test_sweep_store_rimuove_orfani_e_risparmia_i_file_veri(tmp_path, monkeypatch):
    """FAIL-FIRST: pre-patch il metodo non esisteva e gli orfani restavano su disco."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    orfani = [tmp_path / ".config_abc.tmp", tmp_path / ".dedupe_x.tmp",
              tmp_path / ".guard_y.tmp", tmp_path / "tmp_z.tmp",
              profiles / ".profile_w.json"]
    veri = [tmp_path / "config.json", profiles / "Mio_Profilo.json"]
    for f in orfani + veri:
        f.write_text("{}", encoding="utf-8")

    app_mod, a, logs = _app_stub()
    monkeypatch.setattr(app_mod, "config_dir", lambda: str(tmp_path))
    from xtrader_bridge import profile_store
    monkeypatch.setattr(profile_store, "profiles_dir", lambda: str(profiles))

    app_mod.App._sweep_orphan_store_temps(a)

    assert not any(f.exists() for f in orfani), "tutti gli orfani rimossi"
    assert all(f.exists() for f in veri), "i file VERI non si toccano mai"
    assert logs and "5" in logs[0]                       # conteggio nel log


def test_sweep_store_avvio_pulito_silenzioso(tmp_path, monkeypatch):
    """Nessun orfano → nessun log (niente rumore a ogni avvio pulito)."""
    (tmp_path / "profiles").mkdir()
    app_mod, a, logs = _app_stub()
    monkeypatch.setattr(app_mod, "config_dir", lambda: str(tmp_path))
    from xtrader_bridge import profile_store
    monkeypatch.setattr(profile_store, "profiles_dir",
                        lambda: str(tmp_path / "profiles"))

    app_mod.App._sweep_orphan_store_temps(a)

    assert logs == []


