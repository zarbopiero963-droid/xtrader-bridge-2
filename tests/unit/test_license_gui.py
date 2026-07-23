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


def test_current_status_heartbeat_persiste_quando_avanza(license_gui):
    # CR #144: un check valido con orologio AVANZATO registra il heartbeat anti-rollback.
    fake, saved = _fake_panel(stored=(_valid_token(), _NOW - _DAY), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)   # advanced = now


def test_current_status_heartbeat_non_scrive_se_orologio_non_avanza(license_gui):
    # Fable #144: nessun write se l'orologio non è avanzato → niente os.replace concorrenti.
    fake, saved = _fake_panel(stored=(_valid_token(), _NOW), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved == []                                     # nessun heartbeat scritto


def test_current_status_heartbeat_transitorio_non_invalida(license_gui):
    # Fable #144: un lock TRANSITORIO (un solo save fallito) NON invalida una licenza valida.
    fake = _raising_fake(stored=(_valid_token(), _NOW - _DAY), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True                                # sotto soglia: resta valida


def test_current_status_heartbeat_persistente_fail_closed(license_gui):
    # GPT/Fable #144: fallimenti heartbeat PERSISTENTI (≥ soglia) → fail-CLOSED, così non si può
    # negare la scrittura di last_seen per aggirare la scadenza tenendo l'orologio fermo.
    fake = _raising_fake(stored=(_valid_token(), _NOW - _DAY), now=_NOW)
    fake._heartbeat_failures = 0
    last = None
    for _ in range(license_gui._HEARTBEAT_FAIL_LIMIT):
        last = license_gui.LicensePanel.current_status(fake)
    assert last.valid is False
    assert last.reason == license_status.PERSIST_FAILED


def test_current_status_last_seen_corrotto_non_solleva(license_gui):
    # Fable #144: un `last_seen` NON numerico nello stato (corruzione/provider anomalo) non deve
    # far sollevare `int()`/il confronto in current_status → viene trattato come prev=None e il
    # heartbeat riparte da `now` (belt-and-suspenders oltre alla sanificazione di load_license).
    fake, saved = _fake_panel(stored=(_valid_token(), "non-un-numero"), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)   # prev=None → scrive advanced=now


def test_current_status_heartbeat_reset_dopo_write_riuscito(license_gui):
    # GLM #144: un write RIUSCITO azzera il conto dei fallimenti consecutivi, così due lock
    # transitori sparsi (non consecutivi) non sommano fino alla soglia e non fanno fail-closed.
    seq = {"fail": [True, False, True]}   # fallisce, riesce (reset), fallisce → conto = 1, non 2
    calls = {"i": 0}

    def _save(tok, ls):
        i = calls["i"]
        calls["i"] += 1
        if seq["fail"][i]:
            raise OSError("lock transitorio (simulato)")

    fake = types.SimpleNamespace(
        _hardware_id_provider=lambda: _HW, _now_provider=lambda: _NOW,
        _load_state=lambda: (_valid_token(), _NOW - _DAY), _save_state=_save,
        _heartbeat_failures=0)
    r1 = license_gui.LicensePanel.current_status(fake)   # save #0: fail → conto 1
    r2 = license_gui.LicensePanel.current_status(fake)   # save #1: ok   → conto 0
    r3 = license_gui.LicensePanel.current_status(fake)   # save #2: fail → conto 1 (non 2)
    assert r1.valid is True and r2.valid is True and r3.valid is True
    assert fake._heartbeat_failures == 1


def test_current_status_last_seen_float_tronca_e_avanza(license_gui):
    # GLM/GPT #144: un `last_seen` float (numerico ma non int) è ammesso via int() (tronca), NON
    # sanizzato a None: resta un timestamp valido e l'heartbeat avanza correttamente.
    fake, saved = _fake_panel(stored=(_valid_token(), float(_NOW - _DAY)), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)   # advanced = now


def test_current_status_last_seen_futuro_come_stringa_numerica_blocca_rollback(license_gui):
    # GPT #144: la sanificazione NON deve diventare un bypass. Un `last_seen` FUTURO ma numerico
    # (qui una STRINGA numerica) è convertibile con int() → NON None → l'anti-rollback lo vede
    # ancora nel futuro → CLOCK_ROLLBACK, licenza non valida, nessun heartbeat scritto.
    fake, saved = _fake_panel(stored=(_valid_token(), str(_NOW + 30 * _DAY)), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is False
    assert st.reason == lic.CLOCK_ROLLBACK
    assert saved == []                                     # nessun bypass: niente scrittura


def test_current_status_orologio_retrocede_rollback(license_gui):
    # GLM #144: caso critico anti-rollback — last_seen nel futuro rispetto a now → CLOCK_ROLLBACK,
    # licenza NON valida e nessun heartbeat scritto.
    fake, saved = _fake_panel(stored=(_valid_token(), _NOW + 30 * _DAY), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is False
    assert st.reason == lic.CLOCK_ROLLBACK
    assert saved == []


def test_current_status_senza_save_state_non_scrive(license_gui):
    # GLM #144: ramo _save_state=None → nessun heartbeat, nessun crash, stato valido.
    fake = types.SimpleNamespace(
        _hardware_id_provider=lambda: _HW, _now_provider=lambda: _NOW,
        _load_state=lambda: (_valid_token(), _NOW - _DAY), _save_state=None)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True


def test_current_status_provider_difettoso_stato_neutro(license_gui):
    # Fable #144: un provider che solleva → current_status degrada a stato neutro (non propaga).
    def _boom():
        raise RuntimeError("WMI/registro giù (simulato)")
    fake = types.SimpleNamespace(
        _hardware_id_provider=_boom, _now_provider=lambda: _NOW,
        _load_state=lambda: (None, None), _save_state=lambda *a: None)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is False
    assert st.reason == license_status.NOT_PRESENT


def test_refresh_provider_difettoso_non_propaga(license_gui):
    # Fable #144: di conseguenza refresh_options (che chiama current_status) non si rompe.
    def _boom():
        raise RuntimeError("WMI/registro giù (simulato)")
    fake = types.SimpleNamespace(
        _hardware_id_provider=_boom, _now_provider=lambda: _NOW,
        _load_state=lambda: (None, None), _save_state=lambda *a: None,
        _on_status_change=None)
    fake.current_status = lambda: license_gui.LicensePanel.current_status(fake)
    license_gui.LicensePanel.refresh_options(fake)         # non deve sollevare


def test_refresh_non_inghiotte_errori_del_gate(license_gui):
    # Regressione (review Fable #144): in PR 4 `_on_status_change` sarà il GATE del lock. Un errore
    # nel gate NON deve essere inghiottito silenziosamente (sarebbe fail-OPEN): deve propagare.
    fake, _saved = _fake_panel(stored=(None, None))
    fake.current_status = lambda: license_gui.LicensePanel.current_status(fake)
    fake._on_status_change = lambda _st: (_ for _ in ()).throw(RuntimeError("gate boom"))
    with pytest.raises(RuntimeError):
        license_gui.LicensePanel.refresh_options(fake)
