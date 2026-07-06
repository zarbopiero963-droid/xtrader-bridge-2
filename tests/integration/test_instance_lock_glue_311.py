"""#311-1.1 (glue): `App._acquire_instance_lock` — seconda istanza rifiutata PRIMA di
costruire la GUI, senza listener né tocchi al CSV; release su chiusura pulita.

Usa `app_mod` (stub customtkinter/telegram del conftest) e `object.__new__(App)` per
esercitare i VERI metodi senza costruire widget.
"""

import inspect

import pytest


def test_seconda_istanza_systemexit_prima_della_gui(app_mod, monkeypatch):
    # acquire → None (altra istanza attiva): il metodo REALE mostra l'avviso ed esce
    # con SystemExit — nessuna GUI, nessun listener, nessuna scrittura CSV.
    monkeypatch.setattr(app_mod.instance_lock, "acquire", lambda **k: None)
    a = object.__new__(app_mod.App)
    avvisi = []
    a._notify_already_running = lambda: avvisi.append(1)     # shadow: niente Tk reale
    with pytest.raises(SystemExit):
        a._acquire_instance_lock()
    assert avvisi == [1]                     # l'utente è stato avvisato
    assert a._instance_lock is None


def test_prima_istanza_prosegue_e_conserva_l_handle(app_mod, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(app_mod.instance_lock, "acquire", lambda **k: sentinel)
    a = object.__new__(app_mod.App)
    a._acquire_instance_lock()               # nessuna eccezione: avvio normale
    assert a._instance_lock is sentinel      # handle conservato per il release a chiusura


def test_guard_e_la_prima_cosa_di_init_pin_strutturale(app_mod):
    # PIN di regressione: il guard deve restare la PRIMA cosa di __init__ — prima di
    # super().__init__() (init Tk) e di qualsiasi side-effect. Se qualcuno lo sposta
    # dopo, due istanze costruirebbero entrambe la GUI prima del rifiuto.
    src = inspect.getsource(app_mod.App.__init__)
    assert src.index("_acquire_instance_lock") < src.index("super().__init__")


def test_on_close_rilascia_il_lock(app_mod, monkeypatch):
    # Chiusura pulita: `_on_close` rilascia l'handle (su crash lo fa comunque il SO).
    rilasci = []
    monkeypatch.setattr(app_mod.instance_lock, "release", lambda h: rilasci.append(h))
    a = object.__new__(app_mod.App)
    sentinel = object()
    a._instance_lock = sentinel
    a._stop = lambda: None                   # shadow dei passi di teardown non pertinenti
    a._cancel_expiry_timer = lambda: None
    a._stop_clear_after_id = None
    a._autosync_after_id = None
    a._bot_thread = None
    a.destroy = lambda: None
    a._on_close()
    assert rilasci == [sentinel]


def test_on_close_senza_lock_non_crasha(app_mod, monkeypatch):
    # App costruita in modi non standard (test/oggetti parziali): release(None) è no-op.
    rilasci = []
    monkeypatch.setattr(app_mod.instance_lock, "release", lambda h: rilasci.append(h))
    a = object.__new__(app_mod.App)
    a._stop = lambda: None
    a._cancel_expiry_timer = lambda: None
    a._stop_clear_after_id = None
    a._autosync_after_id = None
    a._bot_thread = None
    a.destroy = lambda: None
    a._on_close()                            # nessun AttributeError (getattr difensivo)
    assert rilasci == [None]
