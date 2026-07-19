"""Follow-up post-audit #76 (blocco 2, nota Fable PR #94) — probe csv_writable
fuori dal thread Tk anche a TTL scaduto.

Bug residuo dopo P3-9: la cache TTL evita l'I/O a raffica, ma quando il TTL scade
il probe REALE (os.access/exists) gira comunque sul thread Tk (percorso
per-messaggio): con lo share di rete degradato la GUI si congela per la durata
del singolo probe, una volta ogni TTL.

Fix testato: a TTL scaduto (stesso path, no force) `_csv_writable_cached` ritorna
SUBITO il risultato stantio in cache e lancia il probe vero su un thread worker
daemon; al completamento la cache viene aggiornata e un refresh del pannello
Salute è schedulato via `_safe_after` (TclError-safe, P3-10). Il primo probe di
un path (avvio/cambio path) e `force=True` (pulsante «🔄 Aggiorna») restano
sincroni: lì serve un esito vero subito e non è il percorso per-messaggio.
"""

import threading


def _orologio(app_mod, monkeypatch, start=1000.0):
    clock = {"now": start}
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock["now"])
    return clock


def _attendi_worker(a):
    """Join del thread probe (esposto per i test come `_csv_probe_thread`)."""
    t = a.__dict__.get("_csv_probe_thread")
    if t is not None:
        t.join(timeout=5)
        assert not t.is_alive(), "il worker del probe deve terminare"


def test_ttl_scaduto_ritorna_stantio_subito_e_aggiorna_in_background(
        make_app, app_mod, monkeypatch):
    """FAIL-FIRST: pre-patch a TTL scaduto il probe girava SINCRONO sul chiamante
    (thread Tk) — qui un probe bloccante avrebbe bloccato la chiamata stessa."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    in_probe = threading.Event()
    chiamate = []

    def _probe(path, **_k):
        chiamate.append((path, threading.current_thread().name))
        in_probe.set()
        return ("RED", "share degradata")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)

    r1 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")   # primo: sincrono
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1                 # TTL scaduto

    r2 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")

    # Risposta IMMEDIATA col valore stantio: il chiamante (thread Tk) non ha
    # eseguito il secondo probe in linea.
    assert r1 == r2 == ("RED", "share degradata")
    _attendi_worker(a)
    assert len(chiamate) == 2
    # Il secondo probe è girato su un thread DIVERSO dal chiamante (worker daemon).
    assert chiamate[1][1] != threading.current_thread().name
    # La cache ora è fresca: la chiamata successiva non rilancia niente.
    r3 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")
    assert r3 == ("RED", "share degradata")
    assert len(chiamate) == 2


def test_ttl_scaduto_niente_pileup_di_worker(make_app, app_mod, monkeypatch):
    """Con un probe LENTO in volo, i refresh successivi non accodano altri worker
    (flag inflight): al massimo UN probe in background alla volta."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    blocco = threading.Event()
    chiamate = []

    def _probe_lento(path, **_k):
        chiamate.append(path)
        blocco.wait(timeout=5)                    # simula share morta
        return ("RED", "lenta")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe_lento)

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # sincrono
    blocco.set()                                                    # sblocca il primo
    blocco.clear()
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # kick async
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # NON accoda
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # NON accoda

    assert len(chiamate) == 2, "un solo worker in volo, niente pile-up"
    blocco.set()
    _attendi_worker(a)


def test_worker_completo_schedula_refresh_salute(make_app, app_mod, monkeypatch):
    """Al completamento il worker aggiorna la cache E schedula il refresh del
    pannello Salute via `_safe_after` (senza aspettare il prossimo messaggio)."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    monkeypatch.setattr(app_mod.health_check, "csv_writable",
                        lambda path, **_k: ("GREEN", "ok"))
    schedulati = []
    a._safe_after = lambda delay, func: schedulati.append((delay, func))

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # sincrono: NO refresh
    assert schedulati == []
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # async
    _attendi_worker(a)

    assert len(schedulati) == 1
    assert schedulati[0][1] == a._refresh_health


def test_primo_probe_e_force_restano_sincroni(make_app, app_mod, monkeypatch):
    """Contratto invariato dove serve l'esito vero subito: primo probe di un path
    (avvio/cambio path) e force=True (🔄) girano in linea, nessun worker."""
    a = make_app(running=False)
    _orologio(app_mod, monkeypatch)
    chiamate = []
    monkeypatch.setattr(app_mod.health_check, "csv_writable",
                        lambda path, **_k: chiamate.append(path) or ("GREEN", "ok"))

    app_mod.App._csv_writable_cached(a, "C:/a.csv")                 # primo path
    app_mod.App._csv_writable_cached(a, "C:/b.csv")                 # cambio path
    app_mod.App._csv_writable_cached(a, "C:/b.csv", force=True)     # 🔄

    assert chiamate == ["C:/a.csv", "C:/b.csv", "C:/b.csv"]
    assert a.__dict__.get("_csv_probe_thread") is None, "nessun worker lanciato"


def test_worker_probe_che_solleva_non_uccide_niente(make_app, app_mod, monkeypatch):
    """Fail-safe: un probe che solleva nel worker non propaga (thread daemon) e
    sblocca il flag inflight — il giro successivo può riprovare."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    esiti = {"n": 0}

    def _probe(path, **_k):
        esiti["n"] += 1
        if esiti["n"] == 2:
            raise OSError("share esplosa a metà probe")
        return ("GREEN", "ok")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)

    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # 1: sincrono ok
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # 2: async, solleva
    _attendi_worker(a)

    assert a.__dict__.get("_csv_probe_inflight") is False           # flag sbloccato
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # 3: riprova
    _attendi_worker(a)
    assert esiti["n"] == 3
