"""P3-9 audit #76 — sonda `csv_writable` sul thread Tk a ogni messaggio.

Bug: ogni messaggio → `_set_last` (thread Tk) → `_refresh_health` →
`_live_health_items` → `health_check.csv_writable(path)`, che fa I/O filesystem
(`os.access`/`os.path.exists`). Con `csv_path` su uno share di rete degradato ogni
chiamata può bloccare per secondi: GUI congelata a OGNI messaggio in arrivo.

Fix testato: cache TTL per-istanza `_csv_writable_cached` — il probe REALE parte al
più una volta ogni `_CSV_PROBE_TTL_S` per path; path cambiato → probe immediato;
`force=True` (pulsante «🔄 Aggiorna») → probe fresco comunque. `health_check.
csv_writable` resta PURA e invariata (la sua suite esistente non cambia).

Test con `make_app` (App headless, metodi REALI), probe contato via monkeypatch di
`app_mod.health_check.csv_writable` e orologio controllato via `app_mod.time.monotonic`
(mai sleep reali)."""

import re
from pathlib import Path

_APP_SRC = Path(__file__).resolve().parents[2] / "xtrader_bridge" / "app.py"


def _probe_contato(app_mod, monkeypatch, esito=("GREEN", "ok")):
    """Sostituisce la sonda vera con una contata; ritorna la lista delle chiamate."""
    chiamate = []

    def _probe(path, **_k):
        chiamate.append(path)
        return esito

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)
    return chiamate


def _orologio(app_mod, monkeypatch, start=1000.0):
    """`time.monotonic` controllato: ritorna il dict con l'ora corrente mutabile."""
    clock = {"now": start}
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock["now"])
    return clock


def test_nel_ttl_un_solo_probe_reale(make_app, app_mod, monkeypatch):
    """Dentro il TTL il probe REALE parte UNA sola volta. Post-A1 #114: il primo
    probe di un path è async (giallo provvisorio + worker) → join deterministico,
    poi entro il TTL la cache serve l'esito VERO senza rifare l'I/O."""
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    clock = _orologio(app_mod, monkeypatch)

    r1 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")   # primo probe: async
    assert r1[0] == app_mod.health_check.YELLOW and "in corso" in r1[1]
    a.__dict__["_csv_probe_thread"].join(timeout=5)               # worker → esito vero
    clock["now"] += app_mod._CSV_PROBE_TTL_S / 2                  # dentro il TTL
    r2 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")

    assert r2 == ("GREEN", "ok"), "entro il TTL la cache serve l'esito vero del worker"
    assert chiamate == ["Z:/share/out.csv"], "dentro il TTL il probe reale parte UNA volta"


def test_ttl_scaduto_riprova_davvero(make_app, app_mod, monkeypatch):
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    clock = _orologio(app_mod, monkeypatch)

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")   # primo probe: async (A1 #114)
    a.__dict__["_csv_probe_thread"].join(timeout=5)           # worker #1 completato
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1            # TTL scaduto
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")

    # Follow-up #76 (nota Fable PR #94): a TTL scaduto il probe fresco parte su un
    # WORKER in background — join deterministico prima di contare (niente race).
    t = a.__dict__.get("_csv_probe_thread")
    if t is not None:
        t.join(timeout=5)
    assert len(chiamate) == 2, "a TTL scaduto lo stato CSV deve tornare fresco"


def test_probe_lento_timestamp_dopo_il_probe(make_app, app_mod, monkeypatch):
    """Review GPT #94: se la SONDA stessa blocca più del TTL (share morta — proprio lo
    scenario target), il timestamp deve nascere DOPO il probe: preso prima sarebbe già
    scaduto e il refresh successivo rifarebbe subito l'I/O bloccante."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    chiamate = []

    def _probe_lento(path, **_k):
        chiamate.append(path)
        clock["now"] += app_mod._CSV_PROBE_TTL_S + 2      # la sonda blocca oltre il TTL
        return ("RED", "share morta")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe_lento)

    # Post-A1 #114: il primo probe gira sul WORKER (mai sul thread chiamante); il
    # timestamp della cache lo prende il worker DOPO l'I/O → join, poi la 2ª lettura
    # resta fresca senza rifare la sonda bloccante.
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # async: worker esegue la sonda
    a.__dict__["_csv_probe_thread"].join(timeout=5)
    r2 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")   # subito dopo il rientro

    assert chiamate == ["Z:/share/out.csv"], (
        "dopo un probe più lento del TTL la cache deve essere FRESCA: niente secondo "
        "I/O bloccante immediato (timestamp preso dopo il probe)")
    assert r2 == ("RED", "share morta")


def test_cambio_path_probe_immediato(make_app, app_mod, monkeypatch):
    """Il cambio di csv_path (save/profilo) non deve mostrare il semaforo del path
    VECCHIO per il resto del TTL."""
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    _orologio(app_mod, monkeypatch)                       # orologio fermo: TTL mai scaduto

    # Post-A1 #114: il primo probe di OGNI path è async → join dei due worker prima
    # di contare (la sonda appende su `chiamate` dal worker).
    app_mod.App._csv_writable_cached(a, "C:/vecchio.csv")
    a.__dict__["_csv_probe_thread"].join(timeout=5)
    app_mod.App._csv_writable_cached(a, "C:/nuovo.csv")
    a.__dict__["_csv_probe_thread"].join(timeout=5)

    assert chiamate == ["C:/vecchio.csv", "C:/nuovo.csv"]


def test_force_bypassa_la_cache(make_app, app_mod, monkeypatch):
    """Il pulsante «🔄 Aggiorna» chiede lo stato VERO: force=True riprova subito."""
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    _orologio(app_mod, monkeypatch)                       # orologio fermo

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")
    a.__dict__["_csv_probe_thread"].join(timeout=5)       # primo probe (async) completato
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv", force=True)

    assert len(chiamate) == 2


def test_live_health_items_usa_la_cache(make_app, app_mod, monkeypatch):
    """Il percorso REALE per-messaggio (`_live_health_items`) passa dalla cache:
    dopo il primo probe (async, A1 #114) l'esito VERO della sonda si propaga e i
    refresh ravvicinati non rifanno l'I/O (un solo probe reale entro il TTL)."""
    a = make_app(running=False, config={"csv_path": "Z:/share/out.csv"})
    a._last_vals = {}
    a._listener_state = app_mod.health_check.LISTENER_OFFLINE
    chiamate = _probe_contato(app_mod, monkeypatch, esito=("RED", "share morta"))
    _orologio(app_mod, monkeypatch)                       # orologio fermo: stesso TTL

    app_mod.App._live_health_items(a)                     # primo probe: async (giallo provvisorio)
    a.__dict__["_csv_probe_thread"].join(timeout=5)       # worker → esito vero in cache
    items2 = app_mod.App._live_health_items(a)

    assert chiamate == ["Z:/share/out.csv"], "refresh ravvicinati: un solo probe reale"
    csv2 = next(i for i in items2 if i.key == "csv")
    assert csv2.state == "RED"                            # esito della sonda propagato via cache
    # force_probe=True (pulsante 🔄) attraversa tutta la catena e riprova davvero.
    app_mod.App._live_health_items(a, True)
    assert len(chiamate) == 2


def test_pulsante_aggiorna_forza_il_probe():
    """Il pulsante «🔄 Aggiorna» del pannello Salute deve passare force_probe=True
    (sorgente pinnato, pattern #311: la costruzione GUI non è esercitabile headless)."""
    src = _APP_SRC.read_text(encoding="utf-8")
    i = src.index('i18n.tr("🔄 Aggiorna")')
    # Blocco = dall'etichetta fino al PRIMO piazzamento del bottone (`.pack(` o `.grid(` —
    # robusto ai refactor UI che aggiungono proprietà fg/hover/text_color o cambiano layout
    # manager, review GPT/GLM #126): niente più finestra a caratteri fissi. Fallback esplicito
    # se il piazzamento non c'è (errore chiaro invece di ValueError da `str.index`).
    fine_candidates = [src.find(mgr, i) for mgr in (".pack(", ".grid(")]
    fine_candidates = [c for c in fine_candidates if c != -1]
    assert fine_candidates, "app.py: bottone «🔄 Aggiorna» senza .pack()/.grid() dopo l'etichetta"
    blocco = src[i:min(fine_candidates)]
    assert re.search(r"command=lambda: self\._refresh_health\(force_probe=True\)", blocco), (
        "app.py: il refresh esplicito dell'utente deve bypassare la cache TTL (P3-9 #76)")
