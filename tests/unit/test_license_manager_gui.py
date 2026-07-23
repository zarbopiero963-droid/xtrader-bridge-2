"""Test hard della mini-GUI del License Manager (#140 PR 3b).

La costruzione dei widget richiede un root Tk → qui si esercitano gli **handler puri**
(`_ensure_keypair`, `_current_key_state`, `_evaluate_issue`, `_evaluate_export`) su un `self` FINTO
(stesso pattern dei meta-test GUI del repo, `customtkinter` stubbato), con `core` REALE su una
cartella-chiave temporanea. Nessun segreto reale: il seed è generato al volo o è quello di TEST.
"""

import importlib
import sys
import types

import pytest

from license_manager import core
from xtrader_bridge.licensing import license as lic

_NOW = 1_000_000_000
_HW = "HW1-1234-5678-9ABC-DEF0"


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def gui(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "license_manager.gui", raising=False)
    return importlib.import_module("license_manager.gui")


def _fake(gui, tmp_path, now=_NOW):
    """`self` finto con `core` REALE e cartella-chiave temporanea. Gli helper interni che gli
    handler chiamano via `self` (`_key_path`, `_current_key_state`) sono rilegati alla classe reale
    (stesso pattern dei meta-test GUI del repo)."""
    fake = types.SimpleNamespace(
        _key_dir=str(tmp_path),
        _now=lambda: now,
        _generate_keypair=core.generate_keypair,
        _load_key=core.load_signing_key,
        _save_key=core.save_signing_key,
        _export_key=core.export_signing_key,
        _issue_license=core.issue_license,
    )
    fake._key_path = lambda: core.signing_key_path(fake._key_dir)
    fake._current_key_state = lambda: gui.LicenseManagerApp._current_key_state(fake)
    return fake


# ── keypair ────────────────────────────────────────────────────────────────────────────────────
def test_ensure_keypair_genera_se_assente(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    out = gui.LicenseManagerApp._ensure_keypair(fake)
    assert out["created"] is True and out["error"] is None
    # la pubblica mostrata coincide con quella salvata su disco
    saved = core.load_signing_key(core.signing_key_path(str(tmp_path)))
    assert saved["public"] == out["public"]


def test_ensure_keypair_riusa_se_presente(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    first = gui.LicenseManagerApp._ensure_keypair(fake)
    second = gui.LicenseManagerApp._ensure_keypair(fake)
    assert second["created"] is False
    assert second["public"] == first["public"]   # non rigenerata


def test_ensure_keypair_non_sovrascrive_file_corrotto(gui, tmp_path):
    path = core.signing_key_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("non-json")
    out = gui.LicenseManagerApp._ensure_keypair(_fake(gui, tmp_path))
    assert out["public"] is None and out["created"] is False
    assert "corrotto" in out["error"].lower()
    with open(path, encoding="utf-8") as f:
        assert f.read() == "non-json"            # non sovrascritto


def test_current_key_state_assente(gui, tmp_path):
    st = gui.LicenseManagerApp._current_key_state(_fake(gui, tmp_path))
    assert st == {"public": None, "error": None}


def _raise_oserror(_p):
    raise OSError("permesso negato (simulato)")


def test_ensure_keypair_file_illeggibile_fail_safe(gui, tmp_path):
    # GLM #146: file-chiave ILLEGGIBILE (OSError su %APPDATA%, es. lock/permessi) → la GUI non
    # crasha all'avvio e NON rigenera sopra (fail-safe): stato d'errore, nessuna scrittura.
    fake = _fake(gui, tmp_path)
    fake._load_key = _raise_oserror
    out = gui.LicenseManagerApp._ensure_keypair(fake)
    assert out["public"] is None and out["created"] is False
    assert "leggere" in out["error"].lower()
    assert core.load_signing_key(core.signing_key_path(str(tmp_path))) is None   # niente scritto


def test_evaluate_issue_file_illeggibile_fail_safe(gui, tmp_path):
    # GLM #146: idem in emissione — un OSError sulla lettura chiave non solleva, non emette.
    fake = _fake(gui, tmp_path)
    fake._load_key = _raise_oserror
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    assert out["accepted"] is False and not out["token"]
    assert "leggere" in out["message"].lower()


# ── emissione licenza ────────────────────────────────────────────────────────────────────────
def test_evaluate_issue_senza_chiave(gui, tmp_path):
    out = gui.LicenseManagerApp._evaluate_issue(_fake(gui, tmp_path), "Mario", "Rossi", "15", _HW)
    assert out["accepted"] is False and not out["token"]
    assert "chiave" in out["message"].lower()


def test_evaluate_issue_valida_verifica_col_bridge(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)                        # crea la keypair
    public = core.load_signing_key(core.signing_key_path(str(tmp_path)))["public"]
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    assert out["accepted"] is True and out["token"]
    st = lic.verify_license(out["token"], _HW, _NOW, public_key_hex=public)
    assert st.valid is True
    assert st.name == "Mario Rossi" and st.days_left == 15


@pytest.mark.parametrize("giorni", ["", "abc", "1.5"])
def test_evaluate_issue_giorni_non_interi(gui, tmp_path, giorni):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", giorni, _HW)
    assert out["accepted"] is False and "inter" in out["message"].lower()


def test_evaluate_issue_hardware_non_identificabile(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", "")
    assert out["accepted"] is False and not out["token"]


def test_evaluate_issue_nome_vuoto(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "  ", "  ", "15", _HW)
    assert out["accepted"] is False            # nome completo vuoto → ValueError dal core


# ── backup ─────────────────────────────────────────────────────────────────────────────────────
def test_evaluate_export_senza_chiave(gui, tmp_path):
    out = gui.LicenseManagerApp._evaluate_export(_fake(gui, tmp_path), str(tmp_path / "b.json"))
    assert out["ok"] is False and "nessuna chiave" in out["message"].lower()


def test_evaluate_export_percorso_vuoto(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_export(fake, "")
    assert out["ok"] is False and "percorso" in out["message"].lower()


def test_evaluate_export_ok(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "backup" / "b.json")
    out = gui.LicenseManagerApp._evaluate_export(fake, dest)
    assert out["ok"] is True
    assert core.load_signing_key(dest) is not None    # backup valido


def test_evaluate_export_dest_esistente(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "b.json")
    seed2, pub2 = core.generate_keypair()
    core.save_signing_key(dest, seed2, pub2, _NOW)     # backup preesistente
    out = gui.LicenseManagerApp._evaluate_export(fake, dest)
    assert out["ok"] is False and "già" in out["message"].lower()
    assert core.load_signing_key(dest)["seed"] == seed2   # non sovrascritto
