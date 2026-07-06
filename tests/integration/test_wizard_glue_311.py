"""Glue #311 §3.4: navigazione del Wizard (gate «Avanti») + consegna finale all'app.

La finestra è vista sottile: qui si esercitano i VERI metodi di navigazione/esito su
istanza nuda (stub ctk) e il vero `App._wizard_finish` (applica al form + salva via
percorso esistente coi gate)."""

import importlib
import sys
import types

import pytest

from xtrader_bridge import wizard


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


class _Lbl:
    def __init__(self):
        self.kw = {}

    def configure(self, **kw):
        self.kw.update(kw)


def _gui_mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.wizard_gui", raising=False)
    return importlib.import_module("xtrader_bridge.wizard_gui")


def _bare_window(mod):
    win = mod.WizardWindow.__new__(mod.WizardWindow)
    win._step = 0
    win._passed = [False] * 5
    win._verified = {}
    win._probe_running = False
    win._result_lbl = _Lbl()
    win._renders = []
    win._render = lambda: win._renders.append(win._step)
    win._e_token = types.SimpleNamespace(get=lambda: "")
    win._e_chat = types.SimpleNamespace(get=lambda: "")
    win._e_csv = types.SimpleNamespace(get=lambda: "")
    win._msg_box = types.SimpleNamespace(get=lambda *_a: "")
    return win


def test_avanti_bloccato_finche_lo_step_non_e_verificato(monkeypatch):
    mod = _gui_mod(monkeypatch)
    win = _bare_window(mod)
    win._go_next()                                    # step 0 non superato
    assert win._step == 0 and "⛔" in win._result_lbl.kw["text"]
    win._show(0, wizard.StepResult(True, "ok"), snapshot="")   # flusso reale: ✅
    win._go_next()
    assert win._step == 1 and win._renders == [1]     # avanzato e ridisegnato
    win._go_back()
    assert win._step == 0


def test_avanti_bloccato_se_il_valore_cambia_dopo_la_verifica(monkeypatch):
    """CodeRabbit #354 (major): un edit dopo il ✅ invalida l'esito — mai avanzare
    (e quindi mai salvare) su un valore MAI verificato."""
    mod = _gui_mod(monkeypatch)
    win = _bare_window(mod)
    valore = {"tok": "TOK-VERIFICATO"}
    win._e_token = types.SimpleNamespace(get=lambda: valore["tok"])
    win._show(0, wizard.StepResult(True, "ok"), snapshot="TOK-VERIFICATO")
    valore["tok"] = "TOK-EDITATO"          # l'utente modifica DOPO la verifica
    win._go_next()
    assert win._step == 0                  # bloccato sullo step
    assert win._passed[0] is False         # esito invalidato
    assert "✏️" in win._result_lbl.kw["text"]
    valore["tok"] = "TOK-VERIFICATO"       # torna al valore già verificato…
    win._go_next()
    assert win._step == 0                  # …ma ormai serve una NUOVA verifica
    win._show(0, wizard.StepResult(True, "ok"), snapshot="TOK-VERIFICATO")
    win._go_next()
    assert win._step == 1                  # verifica fresca → avanza


def test_show_marca_lo_step_e_colora(monkeypatch):
    mod = _gui_mod(monkeypatch)
    win = _bare_window(mod)
    win._show(0, wizard.StepResult(True, "Bot connesso: @x"))
    assert win._passed[0] is True and win._result_lbl.kw["text"].startswith("✅")
    win._show(1, wizard.StepResult(False, "niente"))
    assert win._passed[1] is False and win._result_lbl.kw["text"].startswith("⛔")


def test_fine_consegna_i_valori_e_chiude(monkeypatch):
    mod = _gui_mod(monkeypatch)
    win = _bare_window(mod)
    consegnati, distrutta = {}, []
    win._e_token = types.SimpleNamespace(get=lambda: " TOK ")
    win._e_chat = types.SimpleNamespace(get=lambda: "-100123")
    win._e_csv = types.SimpleNamespace(get=lambda: "C:/x/segnali.csv")
    win._on_finish = consegnati.update
    win.destroy = lambda: distrutta.append(True)
    win._step = 4
    win._passed[4] = True
    win._go_next()                                    # «Fine ✔»
    assert consegnati == {"bot_token": "TOK", "chat_id": "-100123",
                          "csv_path": "C:/x/segnali.csv"}
    assert distrutta == [True]


class _SyncThread:
    """Thread finto SINCRONO: un'eccezione che nel daemon thread reale morirebbe in
    silenzio (lasciando `_probe_running` bloccato) qui PROPAGA e fa fallire il test."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def test_sonda_che_solleva_fail_closed_e_flag_rilasciato(monkeypatch):
    """Fable #354 (1): la sonda che solleva NON deve lasciare ⏳ eterna: esito
    fail-closed con la sola CLASSE dell'errore e `_probe_running` rilasciato."""
    mod = _gui_mod(monkeypatch)
    win = _bare_window(mod)
    win.after = lambda _ms, cb: cb()
    win.winfo_exists = lambda: True
    monkeypatch.setattr(mod.threading, "Thread", _SyncThread)
    esiti = []

    def sonda_rotta():
        raise RuntimeError("boom con token 123:SEGRETO dentro")

    win._run_async(sonda_rotta, esiti.append)
    assert win._probe_running is False               # flag SEMPRE rilasciato
    assert esiti and esiti[0].ok is False            # esito fail-closed consegnato
    assert "RuntimeError" in esiti[0].message
    assert "SEGRETO" not in esiti[0].message         # mai il messaggio grezzo (token)
    win._run_async(lambda: wizard.StepResult(True, "ok"), esiti.append)
    assert esiti[-1].ok is True                      # la sonda successiva NON è bloccata


def test_finestra_chiusa_durante_la_sonda_non_tocca_widget(monkeypatch):
    """Fable #354 (2): finestra distrutta mentre la sonda (10s) è in corso."""
    mod = _gui_mod(monkeypatch)
    monkeypatch.setattr(mod.threading, "Thread", _SyncThread)
    # a) `after` che solleva (Tk smontato): il worker non deve propagare.
    win = _bare_window(mod)

    def after_esplosivo(_ms, _cb):
        raise RuntimeError("main thread is not in main loop")

    win.after = after_esplosivo
    win._run_async(lambda: wizard.StepResult(True, "ok"), lambda res: None)
    # b) callback `after` consegnato DOPO la distruzione (pende sull'interprete,
    #    non sul widget): winfo_exists False → on_done NON chiamato.
    win2 = _bare_window(mod)
    win2._probe_running = True
    win2.winfo_exists = lambda: False
    chiamate = []
    win2._probe_done(wizard.StepResult(True, "ok"), chiamate.append)
    assert win2._probe_running is False and chiamate == []
    # c) winfo_exists che SOLLEVA (interprete già smontato) = finestra chiusa.
    win3 = _bare_window(mod)
    win3._probe_running = True

    def winfo_esplosivo():
        raise RuntimeError("application has been destroyed")

    win3.winfo_exists = winfo_esplosivo
    win3._probe_done(wizard.StepResult(True, "ok"), chiamate.append)
    assert win3._probe_running is False and chiamate == []


def _app_per_wizard(app_mod):
    class _Entry:
        def get(self):
            return ""

    app = object.__new__(app_mod.App)
    app._config = {}
    app._logs = []
    app._log = app._logs.append
    app._e_token = app._e_chat = app._e_csv = _Entry()
    return app


def _fake_gui_mod(monkeypatch, window_factory):
    """Installa un `xtrader_bridge.wizard_gui` finto per `from . import wizard_gui`
    (in CI customtkinter è assente: la vista reale non è importabile headless)."""
    import xtrader_bridge

    fake = types.ModuleType("xtrader_bridge.wizard_gui")
    fake.WizardWindow = window_factory
    monkeypatch.setitem(sys.modules, "xtrader_bridge.wizard_gui", fake)
    monkeypatch.setattr(xtrader_bridge, "wizard_gui", fake, raising=False)
    return fake


def test_open_wizard_singleton_riporta_davanti(app_mod, monkeypatch):
    """Fable #354 (3): click ripetuti su «Wizard» NON creano più Toplevel modali
    (grab_set in conflitto): il secondo click riporta davanti quello aperto."""
    app = _app_per_wizard(app_mod)
    created, lifted = [], []

    class _FakeWin:
        def __init__(self, *a, **k):
            created.append(self)
            self._alive = True

        def grab_set(self):
            pass

        def winfo_exists(self):
            return self._alive

        def lift(self):
            lifted.append(self)

        def focus_force(self):
            pass

    _fake_gui_mod(monkeypatch, _FakeWin)
    app._open_wizard()
    app._open_wizard()                       # secondo click: NIENTE seconda finestra
    assert len(created) == 1 and lifted == [created[0]]
    created[0]._alive = False                # wizard chiuso → si può riaprire
    app._open_wizard()
    assert len(created) == 2

    class _Stantio:                          # riferimento stantio: winfo_exists solleva
        def winfo_exists(self):
            raise RuntimeError("Tk smontato")

    app._wizard_win = _Stantio()
    app._open_wizard()                       # non crasha: riapre da zero
    assert len(created) == 3


def test_open_wizard_grab_fallita_niente_doppione(app_mod, monkeypatch):
    """Fable #354 round 2: se `grab_set` solleva la finestra è comunque creata e
    visibile — il riferimento va tenuto PRIMA del grab, o il click dopo apre un
    doppione. E un errore di lift/focus su finestra viva non deve degradare in un
    secondo Toplevel (GPT #354)."""
    app = _app_per_wizard(app_mod)
    created = []

    class _GrabKo:
        def __init__(self, *a, **k):
            created.append(self)

        def grab_set(self):
            raise RuntimeError("grab failed: another application has grab")

        def winfo_exists(self):
            return True

        def lift(self):
            raise RuntimeError("focus race")   # anche il focus fallisce: irrilevante

        def focus_force(self):
            pass

    _fake_gui_mod(monkeypatch, _GrabKo)
    app._open_wizard()                       # grab fallisce ma la finestra esiste
    app._open_wizard()                       # secondo click: NIENTE doppione
    app._open_wizard()                       # nemmeno con lift che solleva
    assert len(created) == 1


def test_builder_factory_usa_la_chat_live_del_wizard(app_mod, monkeypatch):
    """CodeRabbit #354: il parser dello step 3 è risolto PER-CHAT — va cercato per
    la chat inserita nel wizard (o per la config VIVA), non per lo snapshot
    catturato all'apertura."""
    app = _app_per_wizard(app_mod)
    app._config = {"chat_id": "-100VECCHIA"}
    captured = {}

    class _Win:
        def __init__(self, *a, **k):
            captured.update(k)

        def grab_set(self):
            pass

    _fake_gui_mod(monkeypatch, _Win)
    chieste = []
    monkeypatch.setattr(app_mod.parser_manager, "load_active",
                        lambda cfg, cid: chieste.append((cfg, cid)) or None)
    app._open_wizard()
    factory = captured["builder_factory"]
    assert factory("-100NUOVA") is None       # defn None → builder None (fail-closed)
    assert chieste[-1][1] == "-100NUOVA"      # chat LIVE del wizard, non lo snapshot
    assert factory("") is None
    assert chieste[-1][1] == "-100VECCHIA"    # fallback: chat della config
    app._config = {"chat_id": "-100AGGIORNATA"}
    assert factory("") is None
    assert chieste[-1] == ({"chat_id": "-100AGGIORNATA"}, "-100AGGIORNATA")  # config VIVA


def test_open_wizard_fallita_logga_solo_la_classe(app_mod, monkeypatch):
    """Fugu/GPT #354: `initial` contiene il token → su errore va loggata SOLO la
    classe dell'eccezione, mai il messaggio grezzo."""
    app = _app_per_wizard(app_mod)

    def esplode(*a, **k):
        raise RuntimeError("boom con token 123:SEGRETO dentro")

    _fake_gui_mod(monkeypatch, esplode)
    app._open_wizard()                       # best-effort: nessun crash
    assert any("Apertura wizard fallita" in ln and "RuntimeError" in ln
               for ln in app._logs)
    assert all("SEGRETO" not in ln for ln in app._logs)


def test_app_wizard_finish_applica_al_form_e_salva(app_mod):
    class _Entry:
        def __init__(self, v=""):
            self.v = v

        def get(self):
            return self.v

        def delete(self, *_a):
            self.v = ""

        def insert(self, _i, s):
            self.v = s

    app = object.__new__(app_mod.App)
    app._e_token, app._e_chat, app._e_csv = _Entry("vecchio"), _Entry(), _Entry("old.csv")
    app._logs, app._save_ok = [], True
    app._log = app._logs.append
    saved = []
    app._save_config = lambda: saved.append(True)
    app._wizard_finish({"bot_token": "NUOVO", "chat_id": "-1", "csv_path": ""})
    assert app._e_token.v == "NUOVO" and app._e_chat.v == "-1"
    assert app._e_csv.v == "old.csv"           # valore vuoto dal wizard NON cancella
    assert saved == [True]                     # salvataggio via percorso esistente (gate)
    assert any("Wizard completato" in ln for ln in app._logs)
