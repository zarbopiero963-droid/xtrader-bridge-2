"""Test hard del **gate REVOCA online** integrato nel lock del bridge (#140 R3c).

Headless (stesso pattern di `test_license_lock_140.py`): metodi REALI di `App` su un `self` minimale
(`object.__new__`), con la logica di revoca vera (`revocation_client`) e keypair generata al volo.
Copre: bypass su URL placeholder, fail-closed no-grace senza lista fresca, revoca per serial, staleness,
integrazione in `_license_is_valid`/`_apply_license_lock`/`_start`, e un ciclo del supervisore
(fetch→verifica→anti-replay→cache) con probe iniettabile (nessun socket reale)."""

import threading
import types

import pytest

from xtrader_bridge.licensing import license as lic
from xtrader_bridge.licensing import revocation, revocation_client

_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_700_000_000
# Seed di TEST corrispondente a `LICENSE_PUBLIC_KEY_HEX` incorporata (stesso delle altre suite
# licenza): serve dove il codice verifica con la chiave DI DEFAULT (il supervisore, che non riceve
# una public key esplicita).
_TEST_SEED_HEX = "a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00"


def _signed_default(entries, *, now=_NOW):
    """Lista firmata col seed di TEST → verificabile con la chiave DI DEFAULT (`LICENSE_PUBLIC_KEY_HEX`),
    come farà il supervisore in produzione con l'URL reale."""
    return revocation.build_revocation_list(bytes.fromhex(_TEST_SEED_HEX), entries, now=now)


def _keypair():
    from license_manager import core
    return core.generate_keypair()


def _token(seed_hex, *, name="Mario Rossi", hw=_HW):
    return lic.build_license(bytes.fromhex(seed_hex), name, hw, _NOW, _NOW + 30 * 86_400)


def _signed(seed_hex, entries, *, now=_NOW):
    return revocation.build_revocation_list(bytes.fromhex(seed_hex), entries, now=now)


@pytest.fixture
def App(app_mod):    # noqa: N802 — nome-classe come fixture
    return app_mod.App


def _rev_app(App, *, enabled=True, token="tok", hwid=_HW, now=_NOW):
    """`App` headless con i soli seam di revoca cablati (gate sincrono)."""
    app = object.__new__(App)
    app._revocation_enabled = lambda: enabled
    app._revocation_identity = lambda: (token, hwid)
    app._revocation_now = lambda: now
    app._rev_list = None
    app._rev_verified_at = None
    app._rev_min_iss = 0
    return app


# ── _revocation_gate_ok ───────────────────────────────────────────────────────────────────────────
def test_gate_bypassato_su_url_placeholder(App):
    """URL placeholder (dev) → gate revoca BYPASSATO (True) senza alcuna lista (come chiave di TEST)."""
    app = _rev_app(App, enabled=False)
    assert App._revocation_gate_ok(app) is True


def test_gate_fail_closed_senza_lista_fresca(App):
    """Revoca attiva ma nessuna lista verificata → fail-closed no-grace (False)."""
    app = _rev_app(App, enabled=True)
    assert App._revocation_gate_ok(app) is False


def test_gate_ok_con_lista_fresca_non_revocata(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    app = _rev_app(App, enabled=True, token=token)
    app._rev_list = revocation_client.accept_signed(_signed(seed_hex, []), public_key_hex=public_hex)
    app._rev_verified_at = _NOW
    assert App._revocation_gate_ok(app) is True


def test_gate_bloccato_se_serial_revocato(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    serial = lic.license_serial(token)
    app = _rev_app(App, enabled=True, token=token)
    app._rev_list = revocation_client.accept_signed(_signed(seed_hex, [{"serial": serial}]),
                                                    public_key_hex=public_hex)
    app._rev_verified_at = _NOW
    assert App._revocation_gate_ok(app) is False


def test_gate_bloccato_se_lista_stantia(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    app = _rev_app(App, enabled=True, token=token,
                   now=_NOW + revocation_client.FRESHNESS_MAX_AGE_S + 1)
    app._rev_list = revocation_client.accept_signed(_signed(seed_hex, []), public_key_hex=public_hex)
    app._rev_verified_at = _NOW           # verificata a _NOW, "adesso" oltre la soglia → stantia
    assert App._revocation_gate_ok(app) is False


def test_gate_fail_closed_se_identity_solleva(App):
    """Qualunque errore nel determinare token/hwid → fail-closed (False), mai aperto."""
    app = _rev_app(App, enabled=True)
    def _boom():
        raise RuntimeError("hwid non determinabile")
    app._revocation_identity = _boom
    app._rev_list = object()
    app._rev_verified_at = _NOW
    assert App._revocation_gate_ok(app) is False


# ── integrazione in _license_is_valid ───────────────────────────────────────────────────────────
def test_license_is_valid_licenza_valida_ma_revocata_e_falso(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    serial = lic.license_serial(token)
    app = _rev_app(App, enabled=True, token=token)
    app._license_panel = types.SimpleNamespace(current_status=lambda: types.SimpleNamespace(valid=True))
    app._rev_list = revocation_client.accept_signed(_signed(seed_hex, [{"serial": serial}]),
                                                    public_key_hex=public_hex)
    app._rev_verified_at = _NOW
    assert App._license_is_valid(app) is False       # licenza ok ma revocata → gate chiude


def test_license_is_valid_placeholder_non_blocca(App):
    """Con URL placeholder il gate revoca non interferisce: una licenza valida resta valida."""
    app = _rev_app(App, enabled=False)
    app._license_panel = types.SimpleNamespace(current_status=lambda: types.SimpleNamespace(valid=True))
    assert App._license_is_valid(app) is True


# ── integrazione in _apply_license_lock (stop a sessione viva) ───────────────────────────────────
def test_apply_lock_ferma_sessione_se_revocata(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    serial = lic.license_serial(token)
    app = _rev_app(App, enabled=True, token=token)
    app._license_panel = types.SimpleNamespace(current_status=lambda: types.SimpleNamespace(valid=True))
    app._rev_list = revocation_client.accept_signed(_signed(seed_hex, [{"serial": serial}]),
                                                    public_key_hex=public_hex)
    app._rev_verified_at = _NOW
    app._running = True
    app._ui_ready = True
    app._closing = False
    app._license_locked = None
    app.logs = []
    app._log = app.logs.append
    app._lockable_widgets = []
    app._btn_start = types.SimpleNamespace(configure=lambda **k: None)
    stop_calls = []
    app._stop = lambda: stop_calls.append(True)
    locked = App._apply_license_lock(app)
    assert locked is True and stop_calls == [True]   # revocata a sessione viva → STOP fail-closed


# ── supervisore (_revocation_loop) con probe iniettabile ─────────────────────────────────────────
def _loop_app(App, tmp_path, *, fetch, now=_NOW, min_iss=0):
    app = object.__new__(App)
    app._revocation_fetch = fetch
    app._revocation_now = lambda: now
    app._rev_list = None
    app._rev_verified_at = None
    app._rev_min_iss = min_iss
    app._revocation_cache_path = lambda: str(tmp_path / "revocation_cache.json")
    app.after = lambda *a, **k: None      # marshaling GUI noop in headless
    return app


def test_supervisor_ciclo_ok_aggiorna_stato_e_cache(App, tmp_path):
    signed = _signed_default([{"serial": "LIC-X"}], now=_NOW)   # firmata col seed della chiave default
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()          # un solo ciclo poi esce
        return signed
    app = _loop_app(App, tmp_path, fetch=fetch)
    App._revocation_loop(app, stop)
    assert app._rev_list is not None and "LIC-X" in app._rev_list.serials
    assert app._rev_verified_at == _NOW and app._rev_min_iss == _NOW
    # cache scritta e ricaricabile
    assert revocation_client.load_cached_signed(app._revocation_cache_path()) == signed


def test_supervisor_fetch_fallita_lascia_stato_none(App, tmp_path):
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()
        raise OSError("network down")
    app = _loop_app(App, tmp_path, fetch=fetch)
    App._revocation_loop(app, stop)
    assert app._rev_list is None and app._rev_verified_at is None


def test_supervisor_anti_replay_scarta_iss_vecchio(App, tmp_path):
    """Il floor `min_iss` in memoria fa scartare una lista più vecchia (replay) → stato non aggiornato."""
    signed_old = _signed_default([{"serial": "LIC-OLD"}], now=_NOW - 100)
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()
        return signed_old
    app = _loop_app(App, tmp_path, fetch=fetch, min_iss=_NOW)   # già vista una più recente
    App._revocation_loop(app, stop)
    assert app._rev_list is None            # replay rifiutato → nessun aggiornamento


def test_stop_supervisor_setta_evento(App):
    app = object.__new__(App)
    app._rev_stop_event = threading.Event()
    app._rev_thread = None
    App._stop_revocation_supervisor(app)
    assert app._rev_stop_event.is_set() is True
