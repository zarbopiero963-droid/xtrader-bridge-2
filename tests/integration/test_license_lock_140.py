"""Test hard del **LOCK LICENZA** della GUI del bridge (#140 PR 4).

Headless: esercita i metodi REALI di `App` su un `self` minimale (stesso pattern glue-runtime del
repo — `object.__new__(App)`, GUI/Telegram stubbate dalla conftest di `tests/integration/`). La
logica sotto test è quella vera: gate fail-closed `_license_is_valid`, `_set_operational_lock`,
`_apply_license_lock` (lock/unlock + STOP a sessione viva), il gate di `_start`, il gate di
`_maybe_auto_start` e il tick periodico. Nessuna finestra Tk, nessun segreto.
"""

import ast
import os
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
    """`App` HEADLESS con un pannello licenza fittizio e widget lockable registranti.

    I **seam della revoca online** sono iniettati esplicitamente come «fuori scope»: revoca non
    attiva → gate aperto. Da quando `REVOCATION_LIST_URL` è l'URL reale (#157) la revoca è attiva di
    default, quindi `_license_is_valid` è «licenza valida **e** gate revoca aperto» e l'auto-start
    attende la prima lista: senza questi seam questi test misurerebbero **anche** la revoca, che ha
    la sua suite dedicata (`test_license_lock_r3c.py`). Qui si isola la parte licenza."""
    app = object.__new__(app_mod.App)
    app._revocation_enabled = lambda: False
    app._revocation_gate_ok = lambda: True

    if panel:
        def current_status():
            if raises:
                raise RuntimeError("provider licenza in errore (simulato)")
            return _status(valid)
        app._license_panel = types.SimpleNamespace(current_status=current_status)
    else:
        # `_license_panel = None` ESPLICITO: su un `object.__new__(App)` con tkinter reale (CI), un
        # attributo mancante cadrebbe nel `__getattr__` di Tk e ricorrerebbe (root non pronta). In
        # produzione l'attributo è inizializzato a None in `__init__` prima di `_build_ui`.
        app._license_panel = None

    app._running = running
    app._closing = False
    app._ui_ready = True          # UI "costruita": il lock agisce sui widget (default nei test)
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
        a._running = False           # il vero `_stop` azzera `_running`: qui lo emuliamo
    a._stop = _stop
    locked = App._apply_license_lock(a)
    assert locked is True
    assert a.stop_calls == [True]                 # listener fermato
    assert a._btn_start.state == "disabled"       # e START disabilitato DOPO lo stop (ordine giusto)
    # STOP-race (review CodeRabbit #149): un tick successivo con licenza ANCORA invalida ma sessione
    # GIÀ fermata NON deve richiamare `_stop()` una seconda volta (il ramo locked ri-applica il lock
    # fail-closed, ma `_running` è False → niente secondo STOP).
    a._btn_start.state = "normal"                 # qualcuno riabilita START tra un tick e l'altro
    App._apply_license_lock(a)
    assert a.stop_calls == [True]                 # _stop chiamato UNA sola volta
    assert a._btn_start.state == "disabled"       # …e il lock ri-disabilita START (fail-closed)


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
    App._apply_license_lock(a)                     # was=None + valida → nessun log «sbloccata»
    assert not a.logs
    a._license_panel.current_status = lambda: _status(False)
    App._apply_license_lock(a)                     # valida→bloccata: logga
    assert any("bloccata" in m.lower() for m in a.logs)


def test_apply_lock_non_ritocca_widget_se_valida_invariata(App, app_mod):
    # review Fable #149: con licenza VALIDA invariata il tick NON deve ri-imporre "normal" a ogni
    # giro (scavalcherebbe un disable applicato per altri motivi).
    a = _fake_app(app_mod, valid=True)
    App._apply_license_lock(a)                     # was None→False: applica (widget "normal")
    assert a._w_entry.state == "normal"
    a._w_entry.state = "disabled"                  # qualcun altro lo disabilita
    App._apply_license_lock(a)                     # VALIDA invariata → non ritocca
    assert a._w_entry.state == "disabled"          # lasciato com'era (no override periodico)


def test_apply_lock_riapplica_sempre_se_bloccata(App, app_mod):
    # review Fable/Fugu #149 (fail-closed asimmetrico): con licenza INVALIDA il lock si RI-APPLICA a
    # ogni giro — se un altro percorso riabilita i widget, il tick li ri-blocca.
    a = _fake_app(app_mod, valid=False)
    App._apply_license_lock(a)                     # was None→True: blocca
    assert a._w_entry.state == "disabled" and a._btn_start.state == "disabled"
    a._w_entry.state = "normal"                    # qualcuno riabilita un widget con licenza invalida
    a._btn_start.state = "normal"                  # …e pure START
    App._apply_license_lock(a)                     # ancora INVALIDA → RI-BLOCCA (fail-closed)
    assert a._w_entry.state == "disabled" and a._btn_start.state == "disabled"


def test_apply_lock_non_agisce_se_ui_non_pronta(App, app_mod):
    # review Fable/Fugu #149: durante `_build_ui` i widget non esistono → il lock non deve agire né
    # "consumare" la transizione (altrimenti START resterebbe abilitato con licenza invalida).
    a = _fake_app(app_mod, valid=False)
    a._ui_ready = False
    locked = App._apply_license_lock(a)
    assert locked is True                          # valuta lo stato (invalida)…
    assert a._w_entry.state is None                # …ma NON tocca i widget
    assert a._license_locked is None               # e non "consuma" la transizione


def test_apply_lock_logga_al_primo_avvio_bloccato(App, app_mod):
    # review Fable #149: al PRIMO avvio senza licenza (was is None) l'utente deve vedere PERCHÉ è
    # tutto grigio — il log di blocco compare anche sulla transizione iniziale.
    a = _fake_app(app_mod, valid=False)
    App._apply_license_lock(a)
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


def test_scheda_licenza_mai_lockable(App, app_mod):
    # review Fugu #149 (invariante CRITICA anti-lock-out): la scheda «🔑 Licenza» (campo chiave +
    # «Attiva») NON deve MAI finire tra i widget bloccati — altrimenti, senza licenza, l'utente non
    # potrebbe attivarne una e resterebbe bloccato per SEMPRE. Guard di sorgente (AST): il metodo
    # `_build_license_tab` NON chiama `_register_lockable` (il pannello Licenza costruisce i propri
    # widget, che quindi non sono mai in `_lockable_widgets` e `_set_operational_lock` non li tocca).
    pkg = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "xtrader_bridge")
    with open(os.path.join(pkg, "app.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_build_license_tab"), None)
    # Fallimento LEGGIBILE se il metodo viene rinominato (review Fable/GLM #149): un assert chiaro
    # invece di uno `StopIteration` grezzo. Se sparisce, il guard va aggiornato deliberatamente.
    assert fn is not None, "_build_license_tab non trovato in app.py: aggiornare il guard anti-lock-out"
    lockable_calls = [n for n in ast.walk(fn)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "_register_lockable"]
    assert not lockable_calls, \
        "_build_license_tab NON deve registrare widget lockable (lock-out permanente del tab Licenza)"


# ── Collaudo #12 blocco H (2026-08-01): la revoca deve DIRSI, non solo agire ────────────────────
#
# Trovato dal proprietario al primo collaudo reale: revoca emessa, bridge bloccato correttamente,
# ma il log diceva solo «GUI bloccata: attiva una licenza valida» — per un utente REVOCATO è
# impreciso (la sua licenza è tecnicamente valida: è il fornitore ad averla bloccata) e non gli
# dice l'unica cosa che gli serve: che deve contattare il fornitore, non «riattivare».
# Il design handoff lo annotava come «affinamento UX previsto»; il collaudo lo ha promosso a difetto.

def _fake_app_revocata(app_mod, *, running=False):
    """Come `_fake_app(valid=True)` ma con la revoca ATTIVA e il gate CHIUSO: licenza del pannello
    valida, bloccata dal fornitore. È esattamente lo stato del collaudo H3."""
    app = _fake_app(app_mod, valid=True, running=running)
    app._revocation_enabled = lambda: True
    app._revocation_gate_ok = lambda: False
    return app


def test_lock_da_revoca_dice_REVOCATA_non_il_messaggio_generico(app_mod, App):
    app = _fake_app_revocata(app_mod)
    assert App._apply_license_lock(app) is True
    testo = " ".join(app.logs).lower()
    assert "revocata" in testo, (
        f"l'utente revocato non viene informato della revoca: {app.logs!r}")
    assert "attiva una licenza valida" not in testo, (
        "il messaggio generico suggerisce di «riattivare», che per un revocato è fuorviante")


def test_lock_da_revoca_a_sessione_viva_ferma_e_dice_perche(app_mod, App):
    app = _fake_app_revocata(app_mod, running=True)
    App._apply_license_lock(app)
    assert app.stop_calls, "listener non fermato su licenza revocata (fail-closed violato)"
    testo = " ".join(app.logs).lower()
    assert "revocata" in testo


def test_lock_per_licenza_semplicemente_invalida_resta_generico(app_mod, App):
    """Non-regressione: chi NON è revocato (licenza assente/scaduta) deve continuare a ricevere
    il messaggio che lo manda alla scheda Licenza — quello per lui è giusto."""
    app = _fake_app(app_mod, valid=False)
    App._apply_license_lock(app)
    testo = " ".join(app.logs)
    assert "attiva una licenza valida" in testo
    assert "revocata" not in testo.lower()


def test_la_diagnosi_revoca_e_pigra_nessuna_rilettura_sui_tick_muti(app_mod, App):
    """Nota di Fable 5 e GPT-5.5 (indipendenti) su #212: la diagnosi del PERCHÉ rilegge la licenza
    da disco. Nel ramo bloccato si passa a OGNI tick (il lock si ri-applica sempre, fail-closed),
    ma il messaggio esce solo su transizione o STOP: diagnosticare per un messaggio che non verrà
    mai loggato è I/O inutile sul thread Tk. Qui si pretende che su un tick MUTO — già bloccata,
    nessuna sessione viva — la diagnosi NON venga chiamata."""
    app = _fake_app_revocata(app_mod)
    chiamate = []
    app._license_bloccata_da_revoca = lambda: chiamate.append(1) or True
    app._license_locked = True          # già bloccata: il tick ri-applica ma non logga
    App._apply_license_lock(app)
    assert chiamate == [], (
        "la diagnosi revoca è stata eseguita su un tick muto: I/O disco senza messaggio")


def test_la_diagnosi_revoca_si_calcola_UNA_volta_su_stop_piu_transizione(app_mod, App):
    """Sessione viva + transizione a bloccata: escono DUE messaggi (STOP + lock) ma la diagnosi
    va calcolata una volta sola — due letture disco per lo stesso stato sono una in più."""
    app = _fake_app_revocata(app_mod, running=True)
    chiamate = []
    app._license_bloccata_da_revoca = lambda: chiamate.append(1) or True
    App._apply_license_lock(app)
    assert len(chiamate) == 1, f"diagnosi calcolata {len(chiamate)} volte invece di 1"
