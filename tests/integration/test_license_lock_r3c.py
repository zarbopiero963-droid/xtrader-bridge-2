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
    # Il gate logga in `_dbg` quando cade nel ramo fail-open per errore imprevisto (#159): si
    # REGISTRA invece di ignorarlo, così un test può asserire che quel percorso non sia muto.
    app.dbg_msgs = []
    app._dbg = app.dbg_msgs.append
    return app


# ── _revocation_gate_ok ───────────────────────────────────────────────────────────────────────────
def test_gate_bypassato_su_url_placeholder(App):
    """URL placeholder (dev) → gate revoca BYPASSATO (True) senza alcuna lista (come chiave di TEST)."""
    app = _rev_app(App, enabled=False)
    assert App._revocation_gate_ok(app) is True


def test_gate_senza_lista_NON_blocca(App):
    """Revoca attiva ma nessuna lista verificata → **NON blocca** (decisione proprietario 2026-07-30).

    È il ribaltamento del vecchio «fail-closed no-grace»: prima un URL irraggiungibile fermava i bridge
    a sessione viva — utenti legittimi puniti per un disservizio dell'hosting o una dimenticanza del
    proprietario. Ora l'unico blocco possibile è una revoca **esplicita e dimostrata**."""
    app = _rev_app(App, enabled=True)
    assert App._revocation_gate_ok(app) is True


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


def test_gate_lista_STANTIA_non_blocca(App):
    """Una lista vecchia — fetch non più fresco, o contenuto firmato oltre la finestra — **non blocca**.

    Le finestre restano la misura di *quanto in fretta una revoca si propaga*, non una condizione di
    avvio. Un proprietario che non ri-pubblica per una settimana rallenta la propagazione; non deve
    fermare chi sta lavorando."""
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    molto_dopo = _NOW + revocation_client.MAX_LIST_AGE_S + 10 * 86_400
    app = _rev_app(App, enabled=True, token=token, now=molto_dopo)
    revlist = revocation_client.accept_signed(_signed(seed_hex, []), public_key_hex=public_hex)
    app._rev_state = (revlist, _NOW)      # verificata tantissimo tempo fa
    assert App._revocation_gate_ok(app) is True


def test_gate_errore_imprevisto_NON_blocca(App):
    """Un errore nel determinare token/hwid **non deve fermare** un utente legittimo.

    Prima era fail-closed: un bug nostro diventava un fermo per chi non c'entrava niente. Con la policy
    del 2026-07-30 l'unico blocco ammesso è quello dimostrato da una lista firmata, quindi anche
    l'`except` è fail-open."""
    app = _rev_app(App, enabled=True)

    def _boom():
        raise RuntimeError("hwid non determinabile")
    app._revocation_identity = _boom
    app._rev_state = (object(), _NOW)
    assert App._revocation_gate_ok(app) is True

    # ...ma NON in silenzio (rilievo bloccante Fable #159): un bug qui disattiverebbe l'enforcement
    # della revoca per sempre, e senza traccia nessuno potrebbe accorgersene. Si logga il solo TIPO
    # dell'eccezione — mai il messaggio, che potrebbe contenere token o Hardware ID.
    assert app.dbg_msgs, "il ramo fail-open per errore imprevisto non deve essere muto"
    traccia = " ".join(app.dbg_msgs)
    assert "RuntimeError" in traccia and "fail-open" in traccia
    assert "hwid non determinabile" not in traccia, \
        "solo il tipo dell'eccezione: il messaggio potrebbe contenere dati sensibili"


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
    """`_revocation_enabled` deriva dall'URL (nessun flag separato): URL reale → attivo, placeholder
    → disattivo (rilievo Fugu/GLM #156). Dall'attivazione (#157) il default è l'URL **reale**, quindi
    la revoca è **attiva** senza bisogno di toccare altro."""
    app = object.__new__(App)
    assert App._revocation_enabled(app) is True        # default: URL reale → revoca ATTIVA
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", revocation_client._PLACEHOLDER_URL)
    assert App._revocation_enabled(app) is False
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
def _autostart_app(App, *, enabled=True, token="tok", rev_state=None):
    app = _rev_app(App, enabled=enabled, token=token)
    app._rev_state = rev_state
    app._license_panel = types.SimpleNamespace(
        current_status=lambda: types.SimpleNamespace(valid=True))
    app._config = {"auto_start_listener": True}
    app._running = False
    app._closing = False
    app._autostart_after_id = None
    app.after_calls = []
    app.after = lambda ms, fn: (app.after_calls.append(ms) or "id")
    app.start_calls = []
    app._start = lambda auto=False: app.start_calls.append(auto)
    return app


def test_auto_start_NON_aspetta_la_prima_fetch_revoca(App, app_mod):
    """Revoca ATTIVA + lista non ancora scaricata + licenza valida → l'auto-start **parte subito**.

    Ribalta il comportamento del #156: l'attesa esisteva perché una lista non ancora arrivata BLOCCAVA,
    e rinunciare sarebbe stato ingiusto verso chi aveva solo la rete lenta. Con il fail-open (2026-07-30)
    una lista assente non blocca, quindi non c'è più niente da aspettare: far attendere un utente
    legittimo per una lista che comunque non lo fermerebbe sarebbe solo un ritardo gratuito.

    Un utente davvero revocato che parte in questa finestra viene fermato dal ri-controllo periodico
    (`_apply_license_lock`, STOP a sessione viva) appena la lista arriva."""
    app = _autostart_app(App, enabled=True, rev_state=None)
    App._maybe_auto_start(app)
    assert app.start_calls == [True], "senza lista l'auto-start deve partire, non attendere"
    assert app.after_calls == [], "nessuna ri-programmazione: non c'è più niente da aspettare"


def test_auto_start_parte_quando_lista_arrivata(App, app_mod):
    """Quando la lista è arrivata (fresca, non revocato), l'auto-start parte."""
    seed_hex, public_hex = _keypair()
    token = _token(seed_hex)
    revlist = revocation_client.accept_signed(_signed(seed_hex, []), public_key_hex=public_hex)
    app = _autostart_app(App, enabled=True, token=token, rev_state=(revlist, _NOW))
    App._maybe_auto_start(app)
    assert app.start_calls == [True]                                # lista fresca + non revocato → parte


def test_auto_start_con_URL_IRRAGGIUNGIBILE_parte_comunque(App, app_mod):
    """Il caso che la decisione del proprietario mette al centro: l'URL non si raggiunge (GitHub giù,
    rete assente, DNS rotto) e la licenza è valida e non revocata → **il bridge parte**.

    Prima, oltre il tetto di attese, l'auto-start rinunciava fail-closed. Era il guasto peggiore
    possibile: l'utente accende il PC la mattina, il bridge non parte, e non c'è nulla che lui possa
    fare — il problema è sul server di qualcun altro."""
    app = _autostart_app(App, enabled=True, rev_state=None)
    App._maybe_auto_start(app)
    assert app.start_calls == [True], "un URL irraggiungibile non deve impedire l'avvio"
    assert app.after_calls == [], "e nemmeno ri-programmare un'attesa che non serve più"


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


# ── `_start` onorato dal gate REVOCA (l'interruttore acceso da #157/#159) ────────────────────────
def _app_start_con_licenza_valida(App, app_mod, *, gate_aperto):
    """`App` headless con **licenza valida** e gate revoca pilotabile: isola l'unica variabile che
    interessa qui, cioè la revoca."""
    a = object.__new__(App)
    a._license_panel = types.SimpleNamespace(
        current_status=lambda: types.SimpleNamespace(valid=True, reason="", days_left=30))
    a._revocation_enabled = lambda: True
    a._revocation_gate_ok = lambda: gate_aperto
    a.logs = []
    a._log = a.logs.append
    a._cancel_pending_autostart = lambda: None
    a._apply_license_lock = lambda: None
    a._resync_token_field = lambda: None
    a._e_token = types.SimpleNamespace(get=lambda: "")
    a._e_csv = types.SimpleNamespace(get=lambda: "")
    a._e_delay = types.SimpleNamespace(get=lambda: "")
    return a


def test_start_bloccato_da_revoca_anche_con_licenza_VALIDA(App, app_mod):
    """L'end-to-end che manca altrove. `_start` si ferma perché `_license_is_valid` è «licenza valida
    **E** gate revoca aperto»: qui la licenza è valida e a bloccare è **solo** la revoca.

    Serve perché è esattamente il comportamento che l'attivazione dell'URL reale (#157) accende: da
    bypassato a fail-closed. Le altre suite lo coprono a pezzi — `_revocation_gate_ok` da solo,
    `_license_is_valid` da solo, e i test di `_start` in `test_license_lock_140.py` iniettano i seam
    della revoca per isolare la licenza. Nessuno dimostra la composizione sul percorso di avvio: se
    un domani `_start` smettesse di consultare il gate revoca, tutti resterebbero verdi."""
    a = _app_start_con_licenza_valida(App, app_mod, gate_aperto=False)

    App._start(a)

    assert any("avvio bloccato" in m.lower() for m in a.logs), \
        f"con gate revoca CHIUSO l'avvio deve essere rifiutato; log: {a.logs}"


def test_start_prosegue_con_gate_revoca_APERTO(App, app_mod):
    """Controprova indispensabile: senza, il test sopra passerebbe anche se `_start` rifiutasse
    **sempre** — e non dimostrerebbe che a bloccare è la revoca."""
    a = _app_start_con_licenza_valida(App, app_mod, gate_aperto=True)

    App._start(a)

    assert a.logs, "_start deve aver proceduto oltre il gate (si ferma più avanti, senza Telegram)"
    assert not any("avvio bloccato" in m.lower() for m in a.logs), \
        f"con gate revoca APERTO il blocco licenza/revoca non deve scattare; log: {a.logs}"


# ── ciò che il fail-open NON concede: una revoca arrivata è permanente ───────────────────────────
def test_una_revoca_ARRIVATA_resta_dopo_il_riavvio_e_non_si_riavvolge(App, tmp_path, monkeypatch):
    """La garanzia che regge l'intero disegno fail-open, verificata end-to-end.

    Rinunciare a bloccare su irraggiungibilità sarebbe indifendibile se bastasse poi staccare la rete
    per «de-revocarsi». Non basta, e questo test lo dimostra sui percorsi reali:

    1. la lista che revoca l'utente arriva e viene **scritta in cache** dal supervisore;
    2. al **riavvio** il bridge la ricarica dalla cache → il gate blocca ancora, senza rete;
    3. un **replay** di una lista più vecchia (che non lo revoca) viene **rifiutato** dall'anti-replay
       monotòno → lo stato resta quello revocato.

    ⚠️ Attenzione al perimetro: questo dimostra la persistenza **a cache intatta**. Il bypass per
    cancellazione della cache è pinnato dal test subito sotto — i due vanno letti insieme."""
    seed = _TEST_SEED_HEX
    token = lic.build_license(bytes.fromhex(seed), "Mario Rossi", _HW, _NOW, _NOW + 30 * 86_400)
    serial = lic.license_serial(token)
    cache = str(tmp_path / "revocation_cache.json")

    # 1. la lista che revoca arriva: un ciclo del supervisore la verifica e la mette in cache
    revocante = _signed_default([{"serial": serial}], now=_NOW)
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()
        return revocante
    sup = _loop_app(App, tmp_path, fetch=fetch)
    App._revocation_loop(sup, stop)
    assert revocation_client.load_cached_signed(cache) == revocante, "la lista dev'essere in cache"

    # 2. RIAVVIO: nuova App, nessuna rete — il floor e la lista vengono dalla cache su disco
    riavviata = object.__new__(App)
    riavviata._revocation_now = lambda: _NOW + 5 * 86_400      # giorni dopo, lista ormai "stantia"
    riavviata._rev_min_iss = 0
    riavviata._revocation_cache_path = lambda: cache
    riavviata._revocation_enabled = lambda: True
    riavviata._revocation_identity = lambda: (token, _HW)
    riavviata._dbg = lambda *a, **k: None
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: types.SimpleNamespace(start=lambda: None))
    App._start_revocation_supervisor(riavviata)
    dalla_cache = revocation_client.accept_signed(
        revocation_client.load_cached_signed(cache), now=riavviata._revocation_now())
    riavviata._rev_state = (dalla_cache, _NOW)
    assert App._revocation_gate_ok(riavviata) is False, \
        "una revoca già arrivata deve bloccare anche dopo il riavvio e senza rete"

    # 3. REPLAY di una lista precedente alla revoca: rifiutata dal floor monotòno
    precedente = _signed_default([], now=_NOW - 3600)          # firmata PRIMA della revoca
    assert revocation_client.accept_signed(
        precedente, min_iss=riavviata._rev_min_iss, now=_NOW) is None, \
        "una lista più vecchia non deve poter de-revocare"


def test_utente_NON_revocato_non_e_toccato_da_una_lista_che_revoca_altri(App):
    """Controprova: la lista blocca **solo** chi c'è dentro. Senza, il test sopra passerebbe anche con
    un gate che blocca chiunque appena esiste una lista."""
    seed = _TEST_SEED_HEX
    mio = lic.build_license(bytes.fromhex(seed), "Mario Rossi", _HW, _NOW, _NOW + 30 * 86_400)
    app = _rev_app(App, enabled=True, token=mio)
    app._rev_state = (revocation_client.accept_signed(
        _signed_default([{"serial": "LIC-DI-UN-ALTRO"}], now=_NOW), now=_NOW), _NOW)
    assert App._revocation_gate_ok(app) is True


def test_cache_cancellata_e_URL_irraggiungibile_apre_il_gate(App, tmp_path, monkeypatch):
    """Il limite REALE della revoca, pinnato per quello che è (rilievi bloccanti Fable 5 e Fugu Ultra
    #159, arrivati indipendentemente alla stessa conclusione).

    La documentazione affermava che de-revocarsi richiedesse «una lista firmata più recente, cioè il
    seed privato». **Era falso.** Cache e floor anti-replay vivono in `config_dir()`, sul disco
    dell'utente: chi cancella `revocation_cache.json` e si rende irraggiungibile l'URL riparte con
    `revlist=None` e `min_iss=0`, e sotto fail-open il gate apre. Basta cancellare un file.

    Questo test **non descrive un difetto da correggere**: nessuna protezione lato client regge contro
    chi controlla il filesystem, e tentare di nasconderlo sarebbe teatro. Esiste per impedire che la
    documentazione torni a promettere una garanzia che il codice non dà: se qualcuno un domani
    riscrivesse «la revoca è permanente», questo test resterebbe lì a dire il contrario."""
    seed = _TEST_SEED_HEX
    token = lic.build_license(bytes.fromhex(seed), "Mario Rossi", _HW, _NOW, _NOW + 30 * 86_400)
    serial = lic.license_serial(token)
    cache = tmp_path / "revocation_cache.json"

    # la revoca è arrivata ed è in cache: a questo punto il bridge blocca
    stop = threading.Event()

    def fetch(url, *, timeout):
        stop.set()
        return _signed_default([{"serial": serial}], now=_NOW)
    App._revocation_loop(_loop_app(App, tmp_path, fetch=fetch), stop)
    assert cache.exists(), "precondizione: la revoca dev'essere in cache"

    # l'utente cancella la cache e rende l'URL irraggiungibile
    cache.unlink()

    ripartito = object.__new__(App)
    ripartito._revocation_now = lambda: _NOW + 86_400
    ripartito._rev_min_iss = 0
    ripartito._revocation_cache_path = lambda: str(cache)
    ripartito._revocation_enabled = lambda: True
    ripartito._revocation_identity = lambda: (token, _HW)
    ripartito._dbg = lambda *a, **k: None
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: types.SimpleNamespace(start=lambda: None))
    App._start_revocation_supervisor(ripartito)
    ripartito._rev_state = None                      # URL irraggiungibile: nessuna lista

    assert ripartito._rev_min_iss == 0, "senza cache il floor anti-replay riparte da zero"
    assert App._revocation_gate_ok(ripartito) is True, (
        "questo è il comportamento REALE e voluto sotto fail-open: senza lista non si blocca. "
        "Documentarlo come 'permanenza crittografica' sarebbe una promessa falsa")


def test_un_log_ROTTO_non_puo_trasformare_il_fail_open_in_un_blocco(App):
    """Il fail-open non deve dipendere dal fatto che il **logging diagnostico** funzioni.

    Rilievo bloccante di Fable 5 **e** GPT-5.5, indipendenti e concordi. La traccia aggiunta nel ramo
    `except` sta *dentro* l'except: se `_dbg` a sua volta solleva — GUI non ancora inizializzata,
    attributo assente su un'istanza parziale — l'eccezione **esce dal gate**. E il chiamante
    (`_license_is_valid`) non la assorbe: la propaga.

    Risultato: una riga di diagnostica aggiunta per *osservabilità* trasformerebbe il fail-open in un
    crash del chiamante — cioè esattamente il blocco che il proprietario ha vietato. La cura non può
    essere peggiore della malattia."""
    app = _rev_app(App, enabled=True)

    def identity_rotta():
        raise RuntimeError("hwid non determinabile")

    def dbg_rotto(*_a, **_k):
        raise RuntimeError("log non disponibile (GUI non inizializzata)")

    app._revocation_identity = identity_rotta
    app._dbg = dbg_rotto
    app._rev_state = (object(), _NOW)

    assert App._revocation_gate_ok(app) is True, \
        "nemmeno un logger rotto deve poter bloccare un utente legittimo"


def test_gate_senza_attributo_dbg_non_solleva(App):
    """Variante: `_dbg` **assente del tutto** (istanza parziale). Stesso invariante — nessun blocco."""
    app = _rev_app(App, enabled=True)

    def identity_rotta():
        raise RuntimeError("hwid non determinabile")

    app._revocation_identity = identity_rotta
    del app._dbg
    app._rev_state = (object(), _NOW)

    assert App._revocation_gate_ok(app) is True
