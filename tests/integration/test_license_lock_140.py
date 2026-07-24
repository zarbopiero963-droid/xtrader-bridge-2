"""Test hard del **LOCK LICENZA** della GUI del bridge (#140 PR 4).

Headless: esercita i metodi REALI di `App` su un `self` minimale (stesso pattern glue-runtime del
repo — `object.__new__(App)`, GUI/Telegram stubbate dalla conftest di `tests/integration/`). La
logica sotto test è quella vera: gate fail-closed `_license_is_valid`, `_set_operational_lock`,
`_apply_license_lock` (lock/unlock + STOP a sessione viva), il gate di `_start`, il gate di
`_maybe_auto_start` e il tick periodico. Nessuna finestra Tk, nessun segreto.
"""

import types

import pytest


class _RecWidget:
    """Widget che registra l'ultimo `state` passato a `configure()` (Entry/Button/OptionMenu…)."""

    def __init__(self):
        self.state = None

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class _NoStateWidget:
    """Widget senza `state` (es. un `CTkLabel`): `configure(state=...)` solleva → il lock lo tollera."""

    def configure(self, **kwargs):
        raise RuntimeError("questo widget non accetta 'state'")


def _status(valid):
    return types.SimpleNamespace(valid=valid)


def _fake_app(app_mod, *, valid=True, running=False, raises=False, panel=True):
    """`App` HEADLESS con un pannello licenza fittizio e widget lockable registranti."""
    app = object.__new__(app_mod.App)

    if panel:
        def current_status():
            if raises:
                raise RuntimeError("provider licenza in errore (simulato)")
            return _status(valid)
        app._license_panel = types.SimpleNamespace(current_status=current_status)

    app._running = running
    app._closing = False
    app.logs = []
    app._log = app.logs.append
    app._license_locked = None

    app._w_entry = _RecWidget()
    app._w_option = _RecWidget()
    app._lockable_widgets = [app._w_entry, app._w_option]
    app._btn_start = _RecWidget()

    app.stop_calls = []
    app._stop = lambda: app.stop_calls.append(True)
    return app


@pytest.fixture
def App(app_mod):    # noqa: N802 — nome-classe come fixture (leggibilità dei test)
    return app_mod.App


# ── _license_is_valid: gate FAIL-CLOSED ──────────────────────────────────────────────────────
def test_valid_true_solo_se_licenza_valida(App, app_mod):
    assert App._license_is_valid(_fake_app(app_mod, valid=True)) is True
    assert App._license_is_valid(_fake_app(app_mod, valid=False)) is False


def test_valid_false_se_pannello_assente(App, app_mod):
    # Chiamato prima che la scheda Licenza sia costruita → fail-closed (bloccato).
    assert App._license_is_valid(_fake_app(app_mod, panel=False)) is False


def test_valid_false_se_current_status_solleva(App, app_mod):
    # Un errore imprevisto nel calcolo stato NON deve aprire: fail-closed.
    assert App._license_is_valid(_fake_app(app_mod, raises=True)) is False


# ── _set_operational_lock: disabilita/abilita i widget registrati ─────────────────────────────
def test_set_lock_disabilita_e_riabilita(App, app_mod):
    a = _fake_app(app_mod)
    App._set_operational_lock(a, locked=True)
    assert a._w_entry.state == "disabled" and a._w_option.state == "disabled"
    App._set_operational_lock(a, locked=False)
    assert a._w_entry.state == "normal" and a._w_option.state == "normal"


def test_set_lock_tollera_widget_senza_state(App, app_mod):
    a = _fake_app(app_mod)
    a._lockable_widgets = [a._w_entry, _NoStateWidget(), a._w_option]
    App._set_operational_lock(a, locked=True)     # non deve sollevare
    assert a._w_entry.state == "disabled" and a._w_option.state == "disabled"


# ── _apply_license_lock: lock/unlock + STOP a sessione viva ───────────────────────────────────
def test_apply_lock_blocca_se_invalida(App, app_mod):
    a = _fake_app(app_mod, valid=False)
    locked = App._apply_license_lock(a)
    assert locked is True
    assert a._w_entry.state == "disabled" and a._btn_start.state == "disabled"
    assert a.stop_calls == []                     # nessuna sessione viva → niente STOP


def test_apply_lock_sblocca_se_valida(App, app_mod):
    a = _fake_app(app_mod, valid=True)
    locked = App._apply_license_lock(a)
    assert locked is False
    assert a._w_entry.state == "normal" and a._btn_start.state == "normal"


def test_apply_lock_ferma_sessione_viva_se_scade(App, app_mod):
    # Scadenza/invalidazione a sessione VIVA → STOP fail-closed + lock.
    a = _fake_app(app_mod, valid=False, running=True)
    # Il vero `_stop` rimette START a "normal": qui lo emuliamo, così il test verifica che il lock
    # disabiliti START DOPO lo _stop (ordine corretto), non prima (bug: START resterebbe attivo).
    def _stop():
        a.stop_calls.append(True)
        a._btn_start.state = "normal"
    a._stop = _stop
    locked = App._apply_license_lock(a)
    assert locked is True
    assert a.stop_calls == [True]                 # listener fermato
    assert a._btn_start.state == "disabled"       # e START disabilitato DOPO lo stop (ordine giusto)


def test_apply_lock_valida_e_running_non_forza_start(App, app_mod):
    # Licenza valida MENTRE una sessione è in corso: NON rimettere START a "normal"
    # (lo governa la macchina START/STOP); resta com'è.
    a = _fake_app(app_mod, valid=True, running=True)
    a._btn_start.state = "disabled"               # come lo lascia _start
    App._apply_license_lock(a)
    assert a._btn_start.state == "disabled"       # non toccato
    assert a.stop_calls == []


def test_apply_lock_logga_solo_sulle_transizioni(App, app_mod):
    a = _fake_app(app_mod, valid=True)
    App._apply_license_lock(a)                     # was=None → nessun log di transizione
    assert not a.logs
    a._license_panel.current_status = lambda: _status(False)
    App._apply_license_lock(a)                     # valida→bloccata: logga
    assert any("bloccata" in m.lower() for m in a.logs)


# ── _on_license_status: callback del pannello → rivaluta il lock ──────────────────────────────
def test_on_status_change_rivaluta(App, app_mod):
    a = _fake_app(app_mod, valid=False)
    App._on_license_status(a, _status(False))
    assert a._w_entry.state == "disabled"          # bloccato via callback


# ── gate di _start ────────────────────────────────────────────────────────────────────────────
def test_start_bloccato_senza_licenza(App, app_mod):
    a = _fake_app(app_mod, valid=False)
    a._cancel_pending_autostart = lambda: None
    App._start(a)                                  # se proseguisse oltre il gate → AttributeError
    assert any("avvio bloccato" in m.lower() for m in a.logs)
    assert a._w_entry.state == "disabled"          # gate ha anche riapplicato il lock


def test_start_supera_gate_con_licenza_valida(App, app_mod):
    # Con licenza valida il gate licenza NON blocca: _start prosegue (poi si ferma su
    # telegram/token, log diverso). Verifica che NON compaia il blocco licenza.
    a = _fake_app(app_mod, valid=True)
    a._cancel_pending_autostart = lambda: None
    a._resync_token_field = lambda: None
    a._e_token = types.SimpleNamespace(get=lambda: "")
    a._e_csv = types.SimpleNamespace(get=lambda: "")
    a._e_delay = types.SimpleNamespace(get=lambda: "")
    App._start(a)
    assert a.logs                                  # ha proceduto oltre il gate (ha loggato qualcosa)
    assert not any("avvio bloccato" in m.lower() for m in a.logs)


# ── gate di _maybe_auto_start ─────────────────────────────────────────────────────────────────
def _auto_app(app_mod, *, valid):
    a = _fake_app(app_mod, valid=valid)
    a._config = {"auto_start_listener": True}      # is_enabled True
    a._autostart_after_id = "pending"
    a.start_calls = []
    a._start = lambda auto=False: a.start_calls.append(auto)
    return a


def test_auto_start_bloccato_senza_licenza(App, app_mod):
    a = _auto_app(app_mod, valid=False)
    App._maybe_auto_start(a)
    assert a.start_calls == []                     # niente auto-start senza licenza valida


def test_auto_start_parte_con_licenza_valida(App, app_mod):
    a = _auto_app(app_mod, valid=True)
    App._maybe_auto_start(a)
    assert a.start_calls == [True]                 # auto-start (auto=True) chiamato


# ── tick periodico ────────────────────────────────────────────────────────────────────────────
def test_tick_rivaluta_e_si_riarma(App, app_mod):
    a = _fake_app(app_mod, valid=False)
    after_calls = []
    a.after = lambda ms, func: (after_calls.append(ms) or "id")
    App._license_tick(a)
    assert a._w_entry.state == "disabled"          # ha rivalutato (bloccato)
    assert after_calls == [app_mod._LICENSE_TICK_MS]   # si è ri-armato col periodo giusto


def test_tick_non_si_riarma_in_chiusura(App, app_mod):
    a = _fake_app(app_mod, valid=True)
    a._closing = True
    after_calls = []
    a.after = lambda ms, func: (after_calls.append(ms) or "id")
    App._schedule_license_tick(a)
    assert after_calls == []                       # in chiusura non si riprogramma


def test_register_lockable_accumula(App, app_mod):
    a = object.__new__(app_mod.App)
    App._register_lockable(a, "w1")
    App._register_lockable(a, "w2")
    assert a._lockable_widgets == ["w1", "w2"]
