"""#60 (Codex P2): l'elenco dei profili non deve far crashare la GUI se
`profile_store.list_profiles()` solleva `OSError` (dir non elencabile: ACL AppData, errore FS).

La logica I/O + gestione errore è estratta in `ProfilesPanel._safe_list_profiles` (PURA, senza
widget) proprio per essere testabile in CI: `_refresh_list` crea widget CTk reali che
richiederebbero un display, quindi si testa l'helper puro (non la creazione delle etichette).
customtkinter è stubbato SOLO se assente (in CI è reale: l'import funziona, e l'helper puro no)."""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture
def pg(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.profiles_gui", raising=False)
    return importlib.import_module("xtrader_bridge.profiles_gui")


def test_safe_list_profiles_oserror_non_solleva(pg, monkeypatch):
    monkeypatch.setattr(pg.profile_store, "list_profiles",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("acl negato")))
    names, err = pg.ProfilesPanel._safe_list_profiles()   # NON deve sollevare
    assert names == []
    assert "non leggibile" in err and "acl negato" in err


def test_safe_list_profiles_ok(pg, monkeypatch):
    monkeypatch.setattr(pg.profile_store, "list_profiles", lambda *a, **k: ["Prematch", "Live"])
    names, err = pg.ProfilesPanel._safe_list_profiles()
    assert names == ["Prematch", "Live"]
    assert err == ""
