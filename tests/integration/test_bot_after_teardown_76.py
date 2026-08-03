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
import socket
import types
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
    assert "self._async_stop_event = None" in finale, (
        "CodeRabbit #95: l'evento di stop della sessione morta va azzerato col loop — "
        "altrimenti uno STOP nella finestra del prossimo START accoppia il loop NUOVO "
        "con l'evento STANTIO e non sveglia il supervisor nuovo")
    # e il while del supervisor deve stare DENTRO il try corrispondente
    assert re.search(r"try:\s*\n\s+while _is_current\(\):", corpo), (
        "_run_bot: il supervisor deve essere avvolto dal try del finally")
    # Guardia d'IDENTITÀ nel finally (follow-up #76, nota Fugu PR #95): gli handle
    # condivisi vanno azzerati SOLO se appartengono ancora a QUESTA sessione —
    # il finally tardivo di un run vecchio non deve azzerare loop/evento di un
    # nuovo START che nel frattempo li ha riassegnati (audit C1).
    # Ancorata a riga intera (review Sourcery PR #112): una guardia COMMENTATA o
    # inglobata in altro testo non deve far passare il pin — solo istruzione reale.
    # E gli azzeramenti devono stare DENTRO il blocco guardato (review CodeRabbit
    # PR #112): si cattura il blocco indentato sotto la guardia e si verifica che
    # ENTRAMBI i reset avvengano lì — un azzeramento incondizionato con una
    # guardia scollegata altrove non deve passare.
    m_guardia = re.search(
        r"(?m)^(\s*)if self\._loop is loop:\s*\n((?:\1[ \t]+\S.*\n|\s*\n)+)", finale)
    assert m_guardia, (
        "_run_bot: il finally deve azzerare gli handle solo sotto la guardia "
        "`if self._loop is loop` (niente teardown cross-sessione)")
    blocco_guardia = m_guardia.group(2)
    assert "self._loop = None" in blocco_guardia, (
        "_run_bot: `self._loop = None` deve stare DENTRO la guardia d'identità")
    assert "self._async_stop_event = None" in blocco_guardia, (
        "_run_bot: `self._async_stop_event = None` deve stare DENTRO la guardia")


def test_evento_di_stop_pubblicato_prima_del_loop():
    """Review Fable/Fugu #95 (2° round): l'evento di stop nasce nel PROLOGO di `_run_bot`
    ed è PUBBLICATO PRIMA di `self._loop`. La guardia di `_stop` richiede ENTRAMBI: col
    loop pubblicato per ULTIMO, uno STOP concorrente non può mai osservare la coppia
    incoerente "loop NUOVO + evento VECCHIO" — è l'ordine di pubblicazione, non un lock,
    a garantire la coerenza."""
    corpo = _run_bot_src()
    prologo = corpo[:corpo.index("def _is_current")]
    i_evt = prologo.index("self._async_stop_event = stop_evt")
    i_loop = prologo.index("self._loop = loop")
    assert i_evt < i_loop, (
        "l'evento va PUBBLICATO PRIMA del loop: pubblicare prima il loop riapre la "
        "finestra 'loop nuovo + evento stantio' per uno STOP concorrente (P3-10 #95)")
    dentro_async = corpo[corpo.index("async def _async_run"):corpo.index("while _is_current")]
    assert "asyncio.Event()" not in dentro_async, (
        "_async_run non deve più creare un proprio evento: userebbe di nuovo la finestra")


# ── comportamento REALE del teardown (_run_bot eseguito davvero, CodeRabbit #95) ─────

class _TgAppFinta:
    """App Telegram finta: `initialize()` fallisce con un errore PERMANENTE.

    Il resto è teardown inerte, perché `_safe_shutdown_tg` chiama comunque
    `updater.stop` → `stop` → `shutdown` prima di decidere se ritentare."""

    def __init__(self):
        self.updater = types.SimpleNamespace(stop=self._niente)

    async def _niente(self):
        return None

    def add_handler(self, _h):
        """`_run_bot` registra il MessageHandler: qui irrilevante."""

    def add_error_handler(self, _h):
        """`_run_bot` registra l'error handler PTB: qui irrilevante."""

    async def initialize(self):
        # Errore NON transitorio per `reconnect_policy` (non è NetworkError/TimedOut/
        # RetryAfter) → il supervisor NON riprova e si arriva subito al `finally` sotto
        # test. Un errore transitorio manderebbe il test nel backoff, cioè in stallo.
        raise RuntimeError("initialize finta: nessuna rete in questo test")

    async def start(self):
        return None

    async def stop(self):
        return None

    async def shutdown(self):
        return None


def _pronta_per_run_bot(make_app, app_mod, monkeypatch, *, running):
    """App headless pronta a eseguire il VERO `_run_bot` in modo ERMETICO.

    `ApplicationBuilder` è sostituito esplicitamente (#211 R1): senza, `_run_bot`
    costruiva una `Application` VERA e apriva una connessione di rete: il test finiva
    per dipendere da COME la rete falliva — token rifiutato (permanente) → passava;
    rete assente → `NetworkError` transitorio → backoff, cioè stallo. Lo stub del
    conftest non copre il caso, perché esiste solo se PTB NON è installato.

    Ritorna (app, loop_creati)."""
    a = make_app(running=running)
    a._set_last = lambda *x, **k: None
    a._stop = lambda: None
    # i veri accettano epoch=; uno stub a 0 argomenti fa esplodere _run_bot con TypeError
    # e maschera il comportamento sotto test (#211 R1).
    a._set_status_reconnecting = lambda *_a, **_k: None
    a._set_status_connected = lambda *_a, **_k: None
    creati = []
    vero_new_loop = app_mod.asyncio.new_event_loop

    def _registra():
        loop = vero_new_loop()
        creati.append(loop)
        return loop

    monkeypatch.setattr(app_mod.asyncio, "new_event_loop", _registra)

    class _Builder:
        def token(self, _t):
            return self

        def build(self):
            return _TgAppFinta()

    monkeypatch.setattr(app_mod, "ApplicationBuilder", _Builder)
    monkeypatch.setattr(app_mod, "MessageHandler", lambda *a_, **k_: ("MH", a_, k_))
    return a, creati


def test_run_bot_eccezione_imprevista_chiude_loop_e_handle(make_app, app_mod, monkeypatch):
    """Esecuzione REALE del supervisor: l'errore permanente dentro `_async_run` deve
    finire nel `finally` — loop chiuso, `self._loop` e `self._async_stop_event`
    entrambi azzerati (nessun handle stantio per lo START successivo)."""
    a, creati = _pronta_per_run_bot(make_app, app_mod, monkeypatch, running=True)

    app_mod.App._run_bot(a, {"bot_token": "finto", "chat_id": "-1"}, 1)   # epoch corrente

    assert len(creati) == 1 and creati[0].is_closed(), "il loop della sessione va CHIUSO"
    assert a._loop is None
    assert a._async_stop_event is None, (
        "l'evento della sessione morta è rimasto appeso: uno STOP successivo lo "
        "accoppierebbe al loop del nuovo START (CodeRabbit #95)")


def test_run_bot_sessione_non_corrente_chiude_comunque(make_app, app_mod, monkeypatch):
    """STOP/START rapido: la sessione parte già NON corrente (`_running` False — stesso
    esito di un epoch superato) → il supervisor non entra nemmeno nel while, ma il
    `finally` chiude comunque il loop e azzera gli handle."""
    a, creati = _pronta_per_run_bot(make_app, app_mod, monkeypatch, running=False)
    a._async_stop_event = object()          # residuo simulato di una vita precedente

    app_mod.App._run_bot(a, {"bot_token": "finto", "chat_id": "-1"}, 1)

    assert len(creati) == 1 and creati[0].is_closed()
    assert a._loop is None and a._async_stop_event is None


def test_run_bot_non_apre_NESSUNA_socket(make_app, app_mod, monkeypatch):
    """#211 R1 — «un test che verifichi l'assenza di traffico».

    Il gate strutturale in `tests/safety/test_stub_fedeli_211.py` verifica che il
    builder sia sostituito; questo verifica il FATTO: con un tripwire su
    `socket.socket.connect`, eseguire il vero `_run_bot` non deve tentare NEMMENO una
    connessione.

    Fail-first, misurato per mutazione — e con un limite da conoscere:

    - rimuovendo ENTRAMBE le sostituzioni di `_pronta_per_run_bot` (lo stato PRE-fix)
      il test **fallisce**: `initialize()` va sulla rete vera, il tripwire la fa
      diventare `NetworkError` → transitorio → il supervisor entra nel backoff e
      pytest-timeout lo uccide a `app.py:3842`. Fallisce per TIMEOUT, non con un
      assert pulito: è la natura del difetto, un errore di rete è ritentabile.
    - rimuovendo SOLO `ApplicationBuilder` il test **passa lo stesso**: lo stub di
      `MessageHandler` fa fallire `add_handler` con un `TypeError` permanente prima
      che si arrivi a `initialize()`. Quindi questo test da solo NON pinna la
      sostituzione del builder — quella la pinna il gate strutturale. I due si
      coprono a vicenda: non rimuovere l'uno pensando che l'altro basti."""
    a, creati = _pronta_per_run_bot(make_app, app_mod, monkeypatch, running=True)

    tentate = []

    def _tripwire(self, indirizzo):
        tentate.append(indirizzo)
        raise AssertionError(f"connessione di rete VERA verso {indirizzo}")

    monkeypatch.setattr(socket.socket, "connect", _tripwire)

    app_mod.App._run_bot(a, {"bot_token": "finto", "chat_id": "-1"}, 1)

    assert tentate == [], f"il test ha aperto socket reali: {tentate}"
    assert len(creati) == 1 and creati[0].is_closed()
