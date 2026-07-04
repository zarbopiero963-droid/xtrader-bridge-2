"""Test della glue «📁 Sfoglia…» per cert_path/key_path del tab Betfair Sync (#285).

`sync_tab_gui` importa `customtkinter` (un display) e non è testato in CI: qui stubbiamo la GUI
ed esercitiamo il VERO `_browse_path` su un `self` finto. Il punto SAFETY-CRITICAL: il
salvataggio immediato del percorso riusa `_save()`, che **risolve** i secret mascherati prima di
salvare — perché `credential_store.save_credentials` **cancella i campi vuoti**, quindi un
salvataggio path-only ingenuo perderebbe App Key/Password. Il test verifica che, salvando il nuovo
percorso, i secret arrivino RISOLTI (reali), non vuoti né maschera. `filedialog` è monkeypatchato.
"""

import importlib
import sys
import types

import pytest

from xtrader_bridge.betfair.credential_store import BetfairCredentials


class _FakeEntry:
    def __init__(self, value=""):
        self._v = value

    def delete(self, *_a):
        self._v = ""

    def insert(self, _idx, s):
        self._v = (self._v or "") + str(s)

    def get(self):
        return self._v

    def grid(self, *a, **k):
        return self

    def bind(self, *a, **k):
        return None


class _Noop:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: _Noop()


class _FakeCtk(types.ModuleType):
    def __getattr__(self, name):
        return _Noop


@pytest.fixture()
def gui_mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtk("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.betfair.sync_tab_gui", raising=False)
    return importlib.import_module("xtrader_bridge.betfair.sync_tab_gui")


class _FakeController:
    """Controller finto: `resolve_credentials` simula l'anti-maschera (secret mascherati →
    valori reali); `save_credentials` registra ciò che riceve."""

    def __init__(self):
        self.saved = []

    def resolve_credentials(self, creds):
        return BetfairCredentials(
            app_key=("REAL_appkey" if creds.app_key else ""),
            username=creds.username,
            password=("REAL_pass" if creds.password else ""),
            cert_path=creds.cert_path, key_path=creds.key_path)

    def save_credentials(self, creds):
        self.saved.append(creds)
        return True


def _entries(**over):
    base = {"app_key": "••••", "username": "user", "password": "••••",
            "cert_path": "", "key_path": ""}
    base.update(over)
    return {k: _FakeEntry(v) for k, v in base.items()}


def _fake_self(gui_mod, entries):
    ctrl = _FakeController()
    fake = types.SimpleNamespace(
        _entries=entries, controller=ctrl, _action_status=_Noop(),
        _reload=lambda: None, _refresh_buttons=lambda: None)
    Panel = gui_mod.BetfairSyncPanel
    for name in ("_browse_path", "_save", "_form_credentials"):
        setattr(fake, name, types.MethodType(getattr(Panel, name), fake))
    return fake, ctrl


def _patch_dialog(monkeypatch, ret):
    fake_fd = types.ModuleType("tkinter.filedialog")
    fake_fd.askopenfilename = lambda **k: ret
    fake_tk = types.ModuleType("tkinter")
    fake_tk.filedialog = fake_fd
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_fd)


def test_browse_cert_salva_percorso_preservando_secret(gui_mod, monkeypatch):
    ents = _entries()
    fake, ctrl = _fake_self(gui_mod, ents)
    _patch_dialog(monkeypatch, "/etc/betfair/client.crt")
    fake._browse_path("cert_path")
    assert ents["cert_path"].get() == "/etc/betfair/client.crt"   # entry aggiornata
    assert ctrl.saved, "deve salvare subito"
    saved = ctrl.saved[-1]
    assert saved.cert_path == "/etc/betfair/client.crt"
    # SAFETY: i secret sono RISOLTI (reali), non cancellati né lasciati come maschera
    assert saved.app_key == "REAL_appkey"
    assert saved.password == "REAL_pass"
    assert saved.key_path == ""            # l'altro percorso invariato (era vuoto)


def test_browse_key_salva_percorso(gui_mod, monkeypatch):
    ents = _entries()
    fake, ctrl = _fake_self(gui_mod, ents)
    _patch_dialog(monkeypatch, "/etc/betfair/client.key")
    fake._browse_path("key_path")
    assert ents["key_path"].get() == "/etc/betfair/client.key"
    assert ctrl.saved[-1].key_path == "/etc/betfair/client.key"
    assert ctrl.saved[-1].app_key == "REAL_appkey"    # secret preservati


def test_browse_annullato_no_op(gui_mod, monkeypatch):
    ents = _entries(cert_path="vecchio.crt")
    fake, ctrl = _fake_self(gui_mod, ents)
    _patch_dialog(monkeypatch, "")             # dialog annullato
    fake._browse_path("cert_path")
    assert ents["cert_path"].get() == "vecchio.crt"   # invariato
    assert ctrl.saved == []                            # nessun salvataggio


def test_browse_solo_percorso_mai_contenuto_chiave(gui_mod, monkeypatch):
    # Si legge/salva SOLO il percorso: il metodo non apre né legge il file della chiave.
    ents = _entries()
    fake, ctrl = _fake_self(gui_mod, ents)
    opened = []
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(a))
    _patch_dialog(monkeypatch, "/etc/betfair/client.key")
    fake._browse_path("key_path")
    assert opened == []                        # nessuna lettura del contenuto file
