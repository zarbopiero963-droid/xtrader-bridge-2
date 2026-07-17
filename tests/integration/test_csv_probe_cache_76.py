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
    """FAIL-FIRST: pre-patch ogni chiamata colpiva il filesystem (niente cache,
    niente `_csv_writable_cached`)."""
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    clock = _orologio(app_mod, monkeypatch)

    r1 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")
    clock["now"] += app_mod._CSV_PROBE_TTL_S / 2          # dentro il TTL
    r2 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")

    assert r1 == r2 == ("GREEN", "ok")
    assert chiamate == ["Z:/share/out.csv"], "dentro il TTL il probe reale parte UNA volta"


def test_ttl_scaduto_riprova_davvero(make_app, app_mod, monkeypatch):
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    clock = _orologio(app_mod, monkeypatch)

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1        # TTL scaduto
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")

    assert len(chiamate) == 2, "a TTL scaduto lo stato CSV deve tornare fresco"


def test_cambio_path_probe_immediato(make_app, app_mod, monkeypatch):
    """Il cambio di csv_path (save/profilo) non deve mostrare il semaforo del path
    VECCHIO per il resto del TTL."""
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    _orologio(app_mod, monkeypatch)                       # orologio fermo: TTL mai scaduto

    app_mod.App._csv_writable_cached(a, "C:/vecchio.csv")
    app_mod.App._csv_writable_cached(a, "C:/nuovo.csv")

    assert chiamate == ["C:/vecchio.csv", "C:/nuovo.csv"]


def test_force_bypassa_la_cache(make_app, app_mod, monkeypatch):
    """Il pulsante «🔄 Aggiorna» chiede lo stato VERO: force=True riprova subito."""
    a = make_app(running=False)
    chiamate = _probe_contato(app_mod, monkeypatch)
    _orologio(app_mod, monkeypatch)                       # orologio fermo

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv", force=True)

    assert len(chiamate) == 2


def test_live_health_items_usa_la_cache(make_app, app_mod, monkeypatch):
    """Il percorso REALE per-messaggio (`_live_health_items`) passa dalla cache:
    due refresh ravvicinati = un solo I/O filesystem."""
    a = make_app(running=False, config={"csv_path": "Z:/share/out.csv"})
    a._last_vals = {}
    a._listener_state = app_mod.health_check.LISTENER_OFFLINE
    chiamate = _probe_contato(app_mod, monkeypatch, esito=("YELLOW", "share lenta"))
    _orologio(app_mod, monkeypatch)                       # orologio fermo: stesso TTL

    items1 = app_mod.App._live_health_items(a)
    items2 = app_mod.App._live_health_items(a)

    assert chiamate == ["Z:/share/out.csv"], "refresh ravvicinati: un solo probe reale"
    csv1 = next(i for i in items1 if i.key == "csv")
    csv2 = next(i for i in items2 if i.key == "csv")
    assert csv1.state == csv2.state == "YELLOW"           # esito della sonda propagato
    # force_probe=True (pulsante 🔄) attraversa tutta la catena e riprova davvero.
    app_mod.App._live_health_items(a, True)
    assert len(chiamate) == 2


def test_pulsante_aggiorna_forza_il_probe():
    """Il pulsante «🔄 Aggiorna» del pannello Salute deve passare force_probe=True
    (sorgente pinnato, pattern #311: la costruzione GUI non è esercitabile headless)."""
    src = _APP_SRC.read_text(encoding="utf-8")
    i = src.index('i18n.tr("🔄 Aggiorna")')
    blocco = src[i:i + 400]
    assert re.search(r"command=lambda: self\._refresh_health\(force_probe=True\)", blocco), (
        "app.py: il refresh esplicito dell'utente deve bypassare la cache TTL (P3-9 #76)")
