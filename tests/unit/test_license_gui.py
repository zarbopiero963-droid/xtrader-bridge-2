"""Test hard della schermata Licenza (#140 PR 2).

La costruzione reale dei widget richiede un root Tk → qui si esercita la **logica di attivazione**
(`_evaluate_activation`, `current_status`) su un `self` FINTO, stesso pattern dei meta-test GUI del
repo (`customtkinter` stubbato, nessun widget reale). Più un guard a sorgente sul cablaggio in app.
"""

import importlib
import sys
import types

import pytest

from xtrader_bridge import license_status
from xtrader_bridge.licensing import license as lic

_TEST_SEED = bytes.fromhex("a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00")
_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_000_000_000
_DAY = 86_400


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def license_gui(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.license_gui", raising=False)
    return importlib.import_module("xtrader_bridge.license_gui")


def _valid_token(hw=_HW, exp=_NOW + 15 * _DAY, name="Mario Rossi"):
    return lic.build_license(_TEST_SEED, name, hw, _NOW, exp)


def _fake_panel(stored=(None, None), hwid=_HW, now=_NOW):
    """`self` finto coi soli attributi usati dagli handler puri, più un registratore di save."""
    saved = []
    fake = types.SimpleNamespace(
        _hardware_id_provider=lambda: hwid,
        _now_provider=lambda: now,
        _load_state=lambda: stored,
        _save_state=lambda tok, ls: saved.append((tok, ls)),
    )
    return fake, saved


def test_attivazione_valida_persiste(license_gui):
    fake, saved = _fake_panel()
    out = license_gui.LicensePanel._evaluate_activation(fake, _valid_token())
    assert out["accepted"] is True
    assert "Mario Rossi" in out["message"]
    assert saved == [(_valid_token(), _NOW)]   # persistito con last_seen = now


def test_attivazione_campo_vuoto_non_persiste(license_gui):
    fake, saved = _fake_panel()
    out = license_gui.LicensePanel._evaluate_activation(fake, "")
    assert out["accepted"] is False
    assert saved == []


def test_attivazione_hardware_diverso_rifiutata_non_persiste(license_gui):
    fake, saved = _fake_panel()
    token = _valid_token(hw="HW1-AAAA-BBBB-CCCC-DDDD")
    out = license_gui.LicensePanel._evaluate_activation(fake, token)
    assert out["accepted"] is False
    assert saved == []
    assert "hardware" in out["message"].lower()


def test_attivazione_chiave_malformata_rifiutata(license_gui):
    fake, saved = _fake_panel()
    out = license_gui.LicensePanel._evaluate_activation(fake, "chiave-a-caso")
    assert out["accepted"] is False
    assert saved == []


def test_attivazione_last_seen_monotono_blocca_rollback(license_gui):
    # storico con last_seen nel futuro rispetto a now → CLOCK_ROLLBACK: non accetta, non persiste.
    fake, saved = _fake_panel(stored=("vecchio", _NOW + 5 * _DAY))
    out = license_gui.LicensePanel._evaluate_activation(fake, _valid_token(exp=_NOW + 30 * _DAY))
    assert out["accepted"] is False
    assert saved == []


def test_current_status_da_storico_valido(license_gui):
    fake, _saved = _fake_panel(stored=(_valid_token(), _NOW))
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True


def test_current_status_senza_licenza_e_not_present(license_gui):
    fake, _saved = _fake_panel(stored=(None, None))
    st = license_gui.LicensePanel.current_status(fake)
    assert st.reason == license_status.NOT_PRESENT


def _raising_fake(stored, hwid=_HW, now=_NOW):
    """Fake il cui `_save_state` solleva (disco/permessi simulati)."""
    def _boom(tok, ls):
        raise OSError("disco pieno (simulato)")
    return types.SimpleNamespace(
        _hardware_id_provider=lambda: hwid,
        _now_provider=lambda: now,
        _load_state=lambda: stored,
        _save_state=_boom,
    )


def test_attivazione_persistenza_fallita_non_riuscita(license_gui):
    # CR #144: se save_license solleva (disco/permessi), l'attivazione NON riesce ma NON propaga.
    fake = _raising_fake(stored=(None, None))
    out = license_gui.LicensePanel._evaluate_activation(fake, _valid_token())
    assert out["accepted"] is False
    assert "salvare" in out["message"].lower() or "disco" in out["message"].lower()


def test_current_status_heartbeat_persiste_last_seen(license_gui):
    # CR #144: un check valido registra il heartbeat anti-rollback (next_last_seen).
    fake, saved = _fake_panel(stored=(_valid_token(), _NOW))
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)   # heartbeat persistito


def test_current_status_heartbeat_non_persistibile_fail_closed(license_gui):
    # CR #144: se il heartbeat non è persistibile → fail-CLOSED (licenza NON valida).
    fake = _raising_fake(stored=(_valid_token(), _NOW))
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is False
    assert st.reason == license_status.PERSIST_FAILED


def test_refresh_non_inghiotte_errori_del_gate(license_gui):
    # Regressione (review Fable #144): in PR 4 `_on_status_change` sarà il GATE del lock. Un errore
    # nel gate NON deve essere inghiottito silenziosamente (sarebbe fail-OPEN): deve propagare.
    fake, _saved = _fake_panel(stored=(None, None))
    fake.current_status = lambda: license_gui.LicensePanel.current_status(fake)
    fake._on_status_change = lambda _st: (_ for _ in ()).throw(RuntimeError("gate boom"))
    with pytest.raises(RuntimeError):
        license_gui.LicensePanel.refresh_options(fake)
