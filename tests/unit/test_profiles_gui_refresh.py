"""#60 (Codex P2): `ProfilesPanel._refresh_list` non deve far crashare la callback Tk se
`profile_store.list_profiles()` solleva `OSError` (dir profili non elencabile: ACL AppData,
errore FS). Test headless con customtkinter stubbato se assente."""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo è una classe vuota."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "pack": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


class _FakeFrame:
    def winfo_children(self):
        return []


class _FakeStatus:
    def __init__(self):
        self.text = ""

    def configure(self, text="", **k):
        self.text = text


@pytest.fixture
def pg(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.profiles_gui", raising=False)
    return importlib.import_module("xtrader_bridge.profiles_gui")


def test_refresh_list_oserror_non_crasha(pg, monkeypatch):
    panel = pg.ProfilesPanel.__new__(pg.ProfilesPanel)   # niente __init__/Tk
    panel._list_frame = _FakeFrame()
    panel._status = _FakeStatus()
    monkeypatch.setattr(pg.profile_store, "list_profiles",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("acl negato")))
    # Non deve sollevare: l'errore è mostrato nello status, la finestra resta usabile.
    panel._refresh_list()
    assert "non leggibile" in panel._status.text
    assert "acl negato" in panel._status.text


def test_refresh_list_ok_elenca(pg, monkeypatch):
    panel = pg.ProfilesPanel.__new__(pg.ProfilesPanel)
    panel._list_frame = _FakeFrame()
    panel._status = _FakeStatus()
    monkeypatch.setattr(pg.profile_store, "list_profiles", lambda *a, **k: [])
    panel._refresh_list()          # lista vuota: nessun errore, nessun crash
    assert panel._status.text == ""
