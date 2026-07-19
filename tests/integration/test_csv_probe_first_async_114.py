"""A1 audit #114 — il PRIMO probe `csv_writable` di un path non blocca il thread Tk.

Bug: il ramo "primo probe di un path" (avvio finestra + ogni cambio `csv_path`)
eseguiva `health_check.csv_writable(path)` SINCRONO sul thread chiamante (Tk).
Con `csv_path` su uno share di rete morto, `os.access`/`exists` bloccano per il
timeout del SO → finestra CONGELATA all'avvio (dentro `_build_ui`→`_refresh_health`)
e a ogni cambio path. La macchina async esisteva già ma copriva solo il caso
"TTL scaduto, stesso path".

Fix testato: primo probe automatico → stato PROVVISORIO in cache + probe VERO su
worker in background (mai I/O sul thread chiamante); `force=True` (pulsante 🔄,
azione utente esplicita) resta sincrono.
"""

import threading


def _orologio(app_mod, monkeypatch, start=1000.0):
    clock = {"now": start}
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock["now"])
    return clock


def test_primo_probe_automatico_e_asincrono(make_app, app_mod, monkeypatch):
    """FAIL-FIRST: pre-patch il primo probe girava SINCRONO sul thread chiamante
    (`r` era il risultato vero, la `csv_writable` girava sul thread principale)."""
    a = make_app(running=False)
    _orologio(app_mod, monkeypatch)
    principale = threading.current_thread().name
    chiamate = []

    def _probe(path, **_k):
        chiamate.append((path, threading.current_thread().name))
        return ("GREEN", "ok")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)

    r = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")   # primo probe, non force

    # Ritorno IMMEDIATO provvisorio (giallo «in corso»), NON il risultato vero:
    # il thread chiamante non ha eseguito l'I/O in linea.
    assert r[0] == app_mod.health_check.YELLOW
    assert "in corso" in r[1]
    # Il probe VERO è girato su un worker (thread diverso dal chiamante).
    t = a.__dict__.get("_csv_probe_thread")
    assert t is not None
    t.join(timeout=5)
    assert chiamate == [("Z:/share/out.csv", t.name)]
    assert chiamate[0][1] != principale
    # A worker completato, la cache porta l'esito VERO (aggiornato via _safe_after).
    assert a._csv_probe_cache[2] == ("GREEN", "ok")


def test_force_resta_sincrono(make_app, app_mod, monkeypatch):
    """Il pulsante «🔄 Aggiorna» (force=True) è azione utente esplicita → resta
    SINCRONO: esito vero subito, probe sul thread chiamante."""
    a = make_app(running=False)
    _orologio(app_mod, monkeypatch)
    principale = threading.current_thread().name
    chiamate = []
    monkeypatch.setattr(app_mod.health_check, "csv_writable",
                        lambda p, **k: chiamate.append((p, threading.current_thread().name))
                        or ("GREEN", "ok"))

    r = app_mod.App._csv_writable_cached(a, "Z:/s.csv", force=True)

    assert r == ("GREEN", "ok")                        # esito vero subito
    assert chiamate == [("Z:/s.csv", principale)]      # sul thread chiamante
    assert a.__dict__.get("_csv_probe_thread") is None  # nessun worker


def test_cambio_path_primo_probe_async_per_ogni_path(make_app, app_mod, monkeypatch):
    """Anche il cambio `csv_path` (save/profilo) non blocca: il primo probe del path
    NUOVO è async (provvisorio + worker), come quello del vecchio."""
    a = make_app(running=False)
    _orologio(app_mod, monkeypatch)
    chiamate = []
    monkeypatch.setattr(app_mod.health_check, "csv_writable",
                        lambda p, **k: chiamate.append(p) or ("GREEN", f"ok:{p}"))

    r1 = app_mod.App._csv_writable_cached(a, "C:/vecchio.csv")
    t1 = a.__dict__.get("_csv_probe_thread")
    t1.join(timeout=5)
    r2 = app_mod.App._csv_writable_cached(a, "C:/nuovo.csv")      # cambio path
    t2 = a.__dict__.get("_csv_probe_thread")
    t2.join(timeout=5)

    assert r1[0] == r2[0] == app_mod.health_check.YELLOW          # entrambi provvisori
    assert chiamate == ["C:/vecchio.csv", "C:/nuovo.csv"]         # probe di entrambi (su worker)
    assert a._csv_probe_cache[0] == "C:/nuovo.csv"
