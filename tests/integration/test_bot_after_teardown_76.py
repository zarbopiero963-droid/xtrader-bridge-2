"""P3-10 audit #76 — `after()` cross-thread dal thread bot + `loop.close()` saltato.

Bug: le notifiche UI del listener (`_run_bot`: handler messaggi + supervisor di
riconnessione) usano `self.after(...)` DAL THREAD DEL BOT. `Tk.after` da un altro
thread non è garantito: con la root già distrutta (`_on_close`) solleva `TclError`
(o `RuntimeError` a interprete in teardown). Nei rami del supervisor l'eccezione
usciva dal `while` e SALTAVA `loop.close()` + l'azzeramento di `self._loop`: leak
di selector/fd a ogni ciclo START/STOP con chiusura "sfortunata".

Fix testato:
- `_safe_after(delay, func)`: `self.after` protetto da `except (tk.TclError,
  RuntimeError)` — eccezioni SPECIFICHE (nessun blind-except): la notifica verso una
  UI che non esiste più si perde in silenzio, ogni altro errore resta visibile;
- dentro `_run_bot` NESSUN `self.after(` nudo: tutte le notifiche passano da
  `_safe_after` (vincolo strutturale, pattern #311);
- il supervisor è avvolto in `try/finally`: `loop.close()` e l'azzeramento di
  `self._loop` sono garantiti su QUALSIASI uscita, anche eccezioni impreviste."""

import re
from pathlib import Path

import pytest

_APP_SRC = Path(__file__).resolve().parents[2] / "xtrader_bridge" / "app.py"


# ── _safe_after: comportamento reale ─────────────────────────────────────────────────

def test_safe_after_inoltra_la_chiamata_normale(make_app, app_mod):
    a = make_app(running=False)
    eseguite = []
    a.after = lambda delay, func=None: eseguite.append((delay, func))
    app_mod.App._safe_after(a, 0, "cb")
    assert eseguite == [(0, "cb")]


def test_safe_after_inghiotte_root_distrutta(make_app, app_mod):
    """FAIL-FIRST: pre-patch `_safe_after` non esisteva e il TclError propagava fino a
    far saltare la chiusura del loop."""
    a = make_app(running=False)

    def _root_morta(_delay, _func=None):
        # La classe viene dal MODULO SOTTO TEST (stub headless con TclError-eccezione
        # reale dal conftest; su Windows è il vero tkinter.TclError).
        raise app_mod.tk.TclError("application has been destroyed")

    a.after = _root_morta
    app_mod.App._safe_after(a, 0, lambda: None)      # non deve sollevare

    def _teardown(_delay, _func=None):
        raise RuntimeError("main thread is not in main loop")

    a.after = _teardown
    app_mod.App._safe_after(a, 0, lambda: None)      # non deve sollevare


def test_safe_after_non_maschera_altri_errori(make_app, app_mod):
    """Niente blind-except: un bug vero (es. TypeError) deve restare visibile."""
    a = make_app(running=False)

    def _bug(_delay, _func=None):
        raise TypeError("firma sbagliata")

    a.after = _bug
    with pytest.raises(TypeError):
        app_mod.App._safe_after(a, 0, lambda: None)


# ── vincoli strutturali su _run_bot (pattern #311) ───────────────────────────────────

def _run_bot_src():
    src = _APP_SRC.read_text(encoding="utf-8")
    return src[src.index("def _run_bot"):src.index("def _safe_shutdown_tg")]


def test_run_bot_senza_after_nudi():
    """Tutte le notifiche UI del thread bot devono passare da _safe_after: un solo
    `self.after(` nudo reintrodurrebbe il salto di `loop.close()` su root distrutta."""
    corpo = _run_bot_src()
    nudi = re.findall(r"self\.after\(", corpo)
    assert nudi == [], (
        f"_run_bot contiene {len(nudi)} self.after( nudi: usare self._safe_after (P3-10)")
    assert corpo.count("self._safe_after(") >= 14    # i 14 siti censiti dall'audit


def test_loop_close_dentro_finally():
    """`loop.close()` + azzeramento `self._loop` devono stare in un `finally`:
    garantiti anche su eccezioni impreviste del supervisor."""
    corpo = _run_bot_src()
    m = re.search(r"finally:\s*\n(.*?)def ", corpo, re.S)
    finale = m.group(1) if m else corpo[corpo.index("finally:"):]
    assert "loop.close()" in finale, "_run_bot: loop.close() deve stare nel finally (P3-10)"
    assert "self._loop = None" in finale
    # e il while del supervisor deve stare DENTRO il try corrispondente
    assert re.search(r"try:\s*\n\s+while _is_current\(\):", corpo), (
        "_run_bot: il supervisor deve essere avvolto dal try del finally")
