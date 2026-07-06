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
    win._probe_running = False
    win._result_lbl = _Lbl()
    win._renders = []
    win._render = lambda: win._renders.append(win._step)
    return win


def test_avanti_bloccato_finche_lo_step_non_e_verificato(monkeypatch):
    mod = _gui_mod(monkeypatch)
    win = _bare_window(mod)
    win._go_next()                                    # step 0 non superato
    assert win._step == 0 and "⛔" in win._result_lbl.kw["text"]
    win._passed[0] = True
    win._go_next()
    assert win._step == 1 and win._renders == [1]     # avanzato e ridisegnato
    win._go_back()
    assert win._step == 0


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
