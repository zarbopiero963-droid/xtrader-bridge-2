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
    app._rev_state = None          # (lista_verificata, verificata_a) — tupla atomica
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
    revlist = revocation_client.accept_signed(_signed(seed_hex, []), public_key_hex=public_hex)
    app._rev_state = (revlist, _NOW)
    assert App._revocation_gate_ok(app) is True


def test_gate_bloccato_se_serial_revocato(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    serial = lic.license_serial(token)
    app = _rev_app(App, enabled=True, token=token)
    revlist = revocation_client.accept_signed(_signed(seed_hex, [{"serial": serial}]),
                                              public_key_hex=public_hex)
    app._rev_state = (revlist, _NOW)
    assert App._revocation_gate_ok(app) is False


def test_gate_bloccato_se_lista_stantia(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    app = _rev_app(App, enabled=True, token=token,
                   now=_NOW + revocation_client.FRESHNESS_MAX_AGE_S + 1)
    revlist = revocation_client.accept_signed(_signed(seed_hex, []), public_key_hex=public_hex)
    app._rev_state = (revlist, _NOW)      # verificata a _NOW, "adesso" oltre la soglia fetch → stantia
    assert App._revocation_gate_ok(app) is False


def test_gate_fail_closed_se_identity_solleva(App):
    """Qualunque errore nel determinare token/hwid → fail-closed (False), mai aperto."""
    app = _rev_app(App, enabled=True)
    def _boom():
        raise RuntimeError("hwid non determinabile")
    app._revocation_identity = _boom
    app._rev_state = (object(), _NOW)
    assert App._revocation_gate_ok(app) is False


# ── integrazione in _license_is_valid ───────────────────────────────────────────────────────────
def test_license_is_valid_licenza_valida_ma_revocata_e_falso(App):
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    serial = lic.license_serial(token)
    app = _rev_app(App, enabled=True, token=token)
    app._license_panel = types.SimpleNamespace(current_status=lambda: types.SimpleNamespace(valid=True))
    revlist = revocation_client.accept_signed(_signed(seed_hex, [{"serial": serial}]),
                                              public_key_hex=public_hex)
    app._rev_state = (revlist, _NOW)
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
    revlist = revocation_client.accept_signed(_signed(seed_hex, [{"serial": serial}]),
                                              public_key_hex=public_hex)
    app._rev_state = (revlist, _NOW)
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
    app._rev_state = None
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
    assert app._rev_state is not None
    revlist, verified_at = app._rev_state
    assert "LIC-X" in revlist.serials and verified_at == _NOW and app._rev_min_iss == _NOW
    # cache scritta e ricaricabile
    assert revocation_client.load_cached_signed(app._revocation_cache_path()) == signed


def test_supervisor_fetch_fallita_lascia_stato_none(App, tmp_path):
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()
        raise OSError("network down")
    app = _loop_app(App, tmp_path, fetch=fetch)
    App._revocation_loop(app, stop)
    assert app._rev_state is None


def test_supervisor_anti_replay_scarta_iss_vecchio(App, tmp_path):
    """Il floor `min_iss` in memoria fa scartare una lista più vecchia (replay) → stato non aggiornato."""
    signed_old = _signed_default([{"serial": "LIC-OLD"}], now=_NOW - 100)
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()
        return signed_old
    app = _loop_app(App, tmp_path, fetch=fetch, min_iss=_NOW)   # già vista una più recente
    App._revocation_loop(app, stop)
    assert app._rev_state is None           # replay rifiutato → nessun aggiornamento


def test_stop_supervisor_setta_evento(App):
    app = object.__new__(App)
    app._rev_stop_event = threading.Event()
    app._rev_thread = None
    App._stop_revocation_supervisor(app)
    assert app._rev_stop_event.is_set() is True


def test_supervisor_backoff_su_fallimenti_ripetuti(App, tmp_path):
    """Su fallimenti di fetch RIPETUTI il supervisore attende con **backoff crescente**
    (`reconnect_policy.backoff_delay(1..N)`), non a intervallo fisso (decisione 2a)."""
    from xtrader_bridge import reconnect_policy

    class _FakeEvent:
        def __init__(self, max_iters):
            self.iters, self.max, self.delays = 0, max_iters, []

        def is_set(self):
            return self.iters >= self.max

        def wait(self, d):
            self.delays.append(d)
            self.iters += 1
            return False

    def fetch_fails(url, *, timeout):
        raise OSError("network down")
    app = _loop_app(App, tmp_path, fetch=fetch_fails)
    ev = _FakeEvent(3)
    App._revocation_loop(app, ev)
    assert ev.delays == [reconnect_policy.backoff_delay(1),
                         reconnect_policy.backoff_delay(2),
                         reconnect_policy.backoff_delay(3)]
    assert app._rev_state is None            # nessuna lista valida → stato non aggiornato


def test_revocation_enabled_deriva_dall_url(App, monkeypatch):
    """`_revocation_enabled` deriva dall'URL (nessun flag separato): placeholder → disattivo, URL reale
    → attivo (rilievo Fugu/GLM #156)."""
    app = object.__new__(App)
    assert App._revocation_enabled(app) is False       # default placeholder
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", "https://revoke.mysite.com/l.txt")
    assert App._revocation_enabled(app) is True


def test_revocation_hwid_memoizzato(App, monkeypatch):
    """`_revocation_hwid` calcola l'Hardware ID **una sola volta** e lo riusa (niente WMI/subprocess a
    ogni tick sul thread GUI, rilievo Fable #156)."""
    from xtrader_bridge import licensing
    calls = []
    monkeypatch.setattr(licensing, "hardware_id", lambda: (calls.append(1), "HW1-MEMO")[1])
    app = object.__new__(App)
    assert App._revocation_hwid(app) == "HW1-MEMO"
    assert App._revocation_hwid(app) == "HW1-MEMO"
    assert len(calls) == 1


# ── auto-start × revoca online (rilievo Fugu #156) ───────────────────────────────────────────────
def _autostart_app(App, *, enabled=True, token="tok", rev_state=None, waits=0):
    app = _rev_app(App, enabled=enabled, token=token)
    app._rev_state = rev_state
    app._license_panel = types.SimpleNamespace(
        current_status=lambda: types.SimpleNamespace(valid=True))
    app._config = {"auto_start_listener": True}
    app._running = False
    app._closing = False
    app._autostart_rev_waits = waits
    app._autostart_after_id = None
    app.after_calls = []
    app.after = lambda ms, fn: (app.after_calls.append(ms) or "id")
    app.start_calls = []
    app._start = lambda auto=False: app.start_calls.append(auto)
    return app


def test_auto_start_aspetta_la_prima_fetch_revoca(App, app_mod):
    """Revoca ATTIVA + lista non ancora scaricata (`_rev_state` None) + licenza valida: l'auto-start
    NON rinuncia one-shot ma **ri-programma** per aspettare la prima fetch (rilievo Fugu #156)."""
    app = _autostart_app(App, enabled=True, rev_state=None)
    App._maybe_auto_start(app)
    assert app.start_calls == []                                    # non parte ancora
    assert app.after_calls == [app_mod._AUTOSTART_REVOCATION_WAIT_MS]   # ri-programmato
    assert app._autostart_rev_waits == 1


def test_auto_start_parte_quando_lista_arrivata(App, app_mod):
    """Quando la lista è arrivata (fresca, non revocato), l'auto-start parte."""
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    revlist = revocation_client.accept_signed(_signed(seed_hex, []), public_key_hex=public_hex)
    app = _autostart_app(App, enabled=True, token=token, rev_state=(revlist, _NOW))
    App._maybe_auto_start(app)
    assert app.start_calls == [True]                                # lista fresca + non revocato → parte


def test_auto_start_rinuncia_dopo_max_attese(App, app_mod):
    """Oltre il tetto di attese (irraggiungibilità persistente della prima fetch), l'auto-start
    rinuncia fail-closed: niente start, niente altra ri-programmazione."""
    app = _autostart_app(App, enabled=True, rev_state=None,
                         waits=app_mod._AUTOSTART_REVOCATION_MAX_WAITS)
    App._maybe_auto_start(app)
    assert app.start_calls == [] and app.after_calls == []


def test_auto_start_placeholder_non_aspetta(App, app_mod):
    """Con URL placeholder (revoca inattiva) il comportamento è quello storico: licenza valida → parte
    subito, nessuna attesa della fetch."""
    app = _autostart_app(App, enabled=False, rev_state=None)
    App._maybe_auto_start(app)
    assert app.start_calls == [True] and app.after_calls == []


# ── cache avvelenata da una data futura (avvio del supervisore) ──────────────────────────────────
def _boot_app(App, tmp_path, *, now=_NOW):
    """`self` minimale per esercitare `_start_revocation_supervisor` SENZA far partire il thread: il
    percorso che interessa è il bootstrap del floor anti-replay dalla cache su disco."""
    app = object.__new__(App)
    app._revocation_now = lambda: now
    app._rev_min_iss = 0
    app._revocation_cache_path = lambda: str(tmp_path / "revocation_cache.json")
    app._revocation_enabled = lambda: True
    app._dbg = lambda *a, **k: None
    return app


def test_avvio_con_cache_datata_nel_futuro_non_avvelena_il_floor(App, tmp_path, monkeypatch):
    """Il guasto **durevole**: il floor `min_iss` si ri-deriva dalla cache su disco a ogni avvio, quindi
    una lista datata nel futuro finita in cache renderebbe il bridge **non più revocabile** — e il danno
    sopravviverebbe al riavvio. Qui il thread non parte (sostituito): si esercita solo il bootstrap.

    Il floor deve restare 0, così una revoca legittima successiva viene ancora accettata."""
    futura = _signed_default([], now=_NOW + 7 * 86_400)          # datata fra una settimana
    app = _boot_app(App, tmp_path)
    revocation_client.save_cached_signed(app._revocation_cache_path(), futura)
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: types.SimpleNamespace(start=lambda: None))

    App._start_revocation_supervisor(app)

    assert app._rev_min_iss == 0, "una cache datata nel futuro non deve alzare il floor anti-replay"
    legittima = _signed_default([{"serial": "LIC-REVOCATO"}], now=_NOW)
    accolta = revocation_client.accept_signed(legittima, min_iss=app._rev_min_iss, now=_NOW)
    assert accolta is not None and "LIC-REVOCATO" in accolta.serials, \
        "la revoca legittima successiva deve restare accettabile"


def test_avvio_con_cache_legittima_alza_il_floor(App, tmp_path, monkeypatch):
    """Controprova: il bootstrap dalla cache **funziona ancora** per una lista normale — la guardia sul
    futuro non ha rotto il caso buono (senza questo, il test sopra passerebbe anche se `accept_signed`
    rifiutasse tutto)."""
    legittima = _signed_default([{"serial": "LIC-X"}], now=_NOW - 60)
    app = _boot_app(App, tmp_path)
    revocation_client.save_cached_signed(app._revocation_cache_path(), legittima)
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: types.SimpleNamespace(start=lambda: None))

    App._start_revocation_supervisor(app)

    assert app._rev_min_iss == _NOW - 60


def test_supervisor_scarta_lista_datata_nel_futuro(App, tmp_path):
    """Stesso guasto sul percorso di rete: una lista futura scaricata dall'URL non deve aggiornare né
    lo stato né il floor (né finire in cache, da cui rientrerebbe al riavvio)."""
    futura = _signed_default([{"serial": "LIC-X"}], now=_NOW + 7 * 86_400)
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()
        return futura
    app = _loop_app(App, tmp_path, fetch=fetch)
    App._revocation_loop(app, stop)

    assert app._rev_state is None and app._rev_min_iss == 0
    assert revocation_client.load_cached_signed(app._revocation_cache_path()) is None
