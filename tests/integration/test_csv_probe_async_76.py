"""Follow-up post-audit #76 (blocco 2, nota Fable PR #94) — probe csv_writable
fuori dal thread Tk anche a TTL scaduto.

Bug residuo dopo P3-9: la cache TTL evita l'I/O a raffica, ma quando il TTL scade
il probe REALE (os.access/exists) gira comunque sul thread Tk (percorso
per-messaggio): con lo share di rete degradato la GUI si congela per la durata
del singolo probe, una volta ogni TTL.

Fix testato: a TTL scaduto (stesso path, no force) `_csv_writable_cached` ritorna
SUBITO il risultato stantio in cache e lancia il probe vero su un thread worker
daemon; al completamento la cache viene aggiornata e un refresh del pannello
Salute è schedulato via `_safe_after` (TclError-safe, P3-10).

Aggiornato per A1 audit #114: ORA anche il PRIMO probe di un path (avvio finestra
o cambio `csv_path`) è async (giallo provvisorio + worker) — così la GUI non si
congela mai all'avvio su uno share morto. Qui i test lo usano come SEED della
cache facendo il `join` del worker prima di avanzare il TTL. L'UNICO controllo
ancora sincrono è `force=True` (pulsante «🔄 Aggiorna»): azione utente esplicita
che chiede l'esito vero all'istante (fuori dal percorso per-messaggio).
"""

import re
import threading
from pathlib import Path

_APP_SRC = Path(__file__).resolve().parents[2] / "xtrader_bridge" / "app.py"


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

    r1 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")   # primo probe: ASYNC (A1)
    assert r1[0] == app_mod.health_check.YELLOW                     # giallo provvisorio
    _attendi_worker(a)                                             # seed cache con l'esito vero
    assert a._csv_probe_cache[2] == ("RED", "share degradata")
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1                 # TTL scaduto

    r2 = app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")

    # Risposta IMMEDIATA col valore stantio: il chiamante (thread Tk) non ha
    # eseguito il probe in linea a TTL scaduto.
    assert r2 == ("RED", "share degradata")
    _attendi_worker(a)
    assert len(chiamate) == 2
    # Il probe a TTL scaduto è girato su un thread DIVERSO dal chiamante (worker daemon).
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

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # primo probe async (worker#1)
    blocco.set()                                                    # sblocca worker#1
    _attendi_worker(a)                                             # seed cache, worker#1 finito
    blocco.clear()
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1

    app_mod.App._csv_writable_cached(a, "Z:/share/out.csv")        # kick async (worker#2, appeso)
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


def test_solo_force_resta_sincrono(make_app, app_mod, monkeypatch):
    """Contratto post-A1 #114: SOLO `force=True` (🔄) gira in linea (esito vero subito,
    nessun worker); il primo probe di un path (avvio/cambio path) è ora ASYNC (giallo
    provvisorio + worker), così la finestra non si congela mai all'avvio su share morta.
    (Il primo-probe-async è coperto in dettaglio da `test_csv_probe_first_async_114`.)"""
    a = make_app(running=False)
    _orologio(app_mod, monkeypatch)
    chiamate = []
    monkeypatch.setattr(app_mod.health_check, "csv_writable",
                        lambda path, **_k: chiamate.append(path) or ("GREEN", "ok"))

    # Primo probe di un path: ASYNC (worker), ritorno provvisorio giallo.
    r_primo = app_mod.App._csv_writable_cached(a, "C:/a.csv")
    assert r_primo[0] == app_mod.health_check.YELLOW and "in corso" in r_primo[1]
    t = a.__dict__.get("_csv_probe_thread")
    assert t is not None, "il primo probe di un path deve girare su un worker"
    t.join(timeout=5)
    assert chiamate == ["C:/a.csv"]                                # sonda vera sul worker

    # force=True: SINCRONO, esito vero subito, nessun nuovo worker.
    r_force = app_mod.App._csv_writable_cached(a, "C:/a.csv", force=True)
    assert r_force == ("GREEN", "ok")
    assert chiamate == ["C:/a.csv", "C:/a.csv"]                    # 2° probe sul chiamante
    assert not a.__dict__["_csv_probe_thread"].is_alive(), "force non lancia worker"


def test_cambio_path_con_worker_in_volo_scarta_il_risultato_vecchio(
        make_app, app_mod, monkeypatch):
    """Review GPT/Fable PR #111: se l'utente cambia csv_path mentre un worker sul
    path VECCHIO è in volo, il suo risultato va SCARTATO — non deve sovrascrivere
    la cache del path nuovo (costerebbe un probe sincrono extra sul thread Tk)."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    parti = threading.Event()
    chiamate = []

    def _probe(path, **_k):
        chiamate.append(path)
        if path == "C:/vecchio.csv" and len(chiamate) > 1:
            parti.wait(timeout=5)                # worker sul path vecchio: appeso
        return ("GREEN", f"ok:{path}")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)

    app_mod.App._csv_writable_cached(a, "C:/vecchio.csv")           # primo probe async
    _attendi_worker(a)                                             # seed vecchio
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "C:/vecchio.csv")           # worker VECCHIO appeso
    t_vecchio = a.__dict__["_csv_probe_thread"]
    app_mod.App._csv_writable_cached(a, "C:/nuovo.csv")            # cambio path: async (worker nuovo)
    a.__dict__["_csv_probe_thread"].join(timeout=5)               # worker nuovo completa
    assert a._csv_probe_cache[0] == "C:/nuovo.csv"
    assert a._csv_probe_cache[2] == ("GREEN", "ok:C:/nuovo.csv")

    parti.set()                                                     # worker vecchio completa
    t_vecchio.join(timeout=5)

    # La cache resta del path NUOVO: il worker vecchio ha SCARTATO il suo esito
    # (guardia cambio-path) e la chiamata successiva NON deve rifare un probe.
    assert a._csv_probe_cache[0] == "C:/nuovo.csv"
    assert a._csv_probe_cache[2] == ("GREEN", "ok:C:/nuovo.csv")
    n = len(chiamate)
    app_mod.App._csv_writable_cached(a, "C:/nuovo.csv")           # entro TTL: nessun probe
    assert len(chiamate) == n, "nessun probe extra dopo il worker del path vecchio"


def test_worker_appeso_oltre_stallo_giallo_onesto_poi_recovery(
        make_app, app_mod, monkeypatch):
    """Review Fable PR #111 (bloccante): su share SMB morta il worker può appendersi
    per sempre (os.access senza timeout) col flag inflight alzato — il semaforo
    resterebbe inchiodato sull'ultimo stato noto (magari 🟢) mentre i write CSV
    falliscono. Oltre `_CSV_PROBE_STALL_S` il semaforo deve degradare a GIALLO
    ONESTO senza lanciare altri worker; al ritorno del worker l'esito vero
    riprende il posto (auto-recovery)."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    blocco = threading.Event()
    chiamate = []

    def _probe(path, **_k):
        chiamate.append(path)
        if len(chiamate) > 1:
            blocco.wait(timeout=10)              # worker appeso: share che non risponde
        return ("GREEN", "ok")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)

    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # primo probe async: 🟢
    _attendi_worker(a)                                             # seed cache 🟢
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    r_stantio = app_mod.App._csv_writable_cached(a, "Z:/s.csv")     # worker appeso
    assert r_stantio == ("GREEN", "ok")                             # sotto soglia: stantio

    clock["now"] += app_mod._CSV_PROBE_STALL_S + 0.1                # oltre lo stallo
    r_stallo = app_mod.App._csv_writable_cached(a, "Z:/s.csv")
    assert r_stallo[0] == app_mod.health_check.YELLOW, (
        "worker appeso oltre soglia: MAI un 🟢 stantio spacciato per fresco")
    assert "bloccata" in r_stallo[1]
    assert len(chiamate) == 2, "niente pile-up: nessun nuovo worker mentre uno è appeso"

    blocco.set()                                                    # la share risponde
    _attendi_worker(a)
    assert a._csv_probe_cache[2] == ("GREEN", "ok"), "auto-recovery: esito vero in cache"
    assert not any(t.is_alive() for t, _p, _s in a._csv_probe_threads)


def test_worker_appeso_su_path_vecchio_non_blocca_il_path_nuovo(
        make_app, app_mod, monkeypatch):
    """FAIL-FIRST — review Fable final PR #111: con lo stato inflight GLOBALE un
    worker appeso su un path ABBANDONATO bloccava per sempre i probe del path
    nuovo E il watchdog ingialliva il path nuovo SANO (kick_ts vecchio). Con lo
    stato per-path il path nuovo vive di vita propria."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    blocco = threading.Event()
    chiamate = []

    def _probe(path, **_k):
        chiamate.append(path)
        if path == "C:/vecchio.csv" and len(chiamate) > 1:
            blocco.wait(timeout=10)              # worker sul path vecchio: appeso
        return ("GREEN", f"ok:{path}")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)

    app_mod.App._csv_writable_cached(a, "C:/vecchio.csv")           # primo probe async
    _attendi_worker(a)                                             # seed vecchio
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "C:/vecchio.csv")           # worker VECCHIO appeso
    app_mod.App._csv_writable_cached(a, "C:/nuovo.csv")            # cambio path: async
    a.__dict__["_csv_probe_thread"].join(timeout=5)               # seed nuovo (worker fast)

    # TTL scaduto sul path NUOVO, ben oltre la soglia di stallo del kick VECCHIO:
    clock["now"] += app_mod._CSV_PROBE_STALL_S + 0.1
    r = app_mod.App._csv_writable_cached(a, "C:/nuovo.csv")

    # 1) il watchdog NON ingiallisce il path nuovo per colpa del worker vecchio;
    assert r == ("GREEN", "ok:C:/nuovo.csv")
    # 2) un worker NUOVO è partito per il path nuovo (non bloccato dal vecchio).
    _attendi_worker(a)                            # join dell'ultimo worker (nuovo)
    assert chiamate.count("C:/nuovo.csv") == 2, (
        "il probe del path nuovo deve ripartire anche col worker vecchio appeso")
    assert a._csv_probe_cache[0] == "C:/nuovo.csv"
    blocco.set()                                  # cleanup: sblocca il worker vecchio
    # Join di TUTTI i worker del registro (review Fugu final): niente thread
    # ancora vivi che sopravvivono al test (determinismo, no flakiness CI).
    for t, _p, _s in list(a._csv_probe_threads):
        t.join(timeout=5)
    assert not any(t.is_alive() for t, _p, _s in a._csv_probe_threads)


def test_watchdog_non_sovrascrive_esito_fresco_appena_arrivato(
        make_app, app_mod, monkeypatch):
    """FAIL-FIRST — race Fable final PR #111: il worker scrive l'esito VERO tra la
    lettura della cache in testa e il watchdog — lo stallo non deve sovrascriverlo
    (ri-lettura prima di degradare)."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    monkeypatch.setattr(app_mod.health_check, "csv_writable",
                        lambda path, **_k: ("GREEN", "vecchio"))

    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # sincrono
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # worker (istantaneo)
    _attendi_worker(a)

    # Simula: worker in volo (registro per-path) con avvio oltre soglia, che
    # completa DURANTE la chiamata (il fake kick scrive l'esito fresco come
    # farebbe il worker).
    import types
    clock["now"] += app_mod._CSV_PROBE_STALL_S + 1
    finto_vivo = types.SimpleNamespace(is_alive=lambda: True)
    a._csv_probe_threads = [(finto_vivo, "Z:/s.csv",
                             clock["now"] - app_mod._CSV_PROBE_STALL_S - 1)]

    def _fake_kick(path):
        a._csv_probe_cache = (path, clock["now"], ("GREEN", "FRESCO"))
        return True                               # contratto reale: kick riuscito

    a._kick_csv_probe_async = _fake_kick

    r = app_mod.App._csv_writable_cached(a, "Z:/s.csv")

    assert r == ("GREEN", "FRESCO"), (
        "un esito vero appena scritto dal worker non va MAI sovrascritto col giallo di stallo")
    assert a._csv_probe_cache[2] == ("GREEN", "FRESCO")
    a._csv_probe_threads = []                     # cleanup stato simulato


def test_cap_worker_appesi_su_path_multipli(make_app, app_mod, monkeypatch):
    """FAIL-FIRST — review Fugu PR #111: cambi ripetuti di csv_path su share morte
    non devono accumulare thread appesi senza limite. Oltre `_CSV_PROBE_MAX_WORKERS`
    worker vivi: nessun nuovo worker e degrado a giallo onesto («troppi controlli
    bloccati»)."""
    a = make_app(running=False)
    clock = _orologio(app_mod, monkeypatch)
    blocco = threading.Event()
    visti = {}

    def _probe(path, **_k):
        n = visti.get(path, 0) + 1
        visti[path] = n
        if n > 1:
            blocco.wait(timeout=15)              # il probe async resta appeso
        return ("GREEN", f"ok:{path}")

    monkeypatch.setattr(app_mod.health_check, "csv_writable", _probe)

    cap = app_mod._CSV_PROBE_MAX_WORKERS
    for i in range(cap):                          # un worker appeso per ogni path
        p = f"C:/morto{i}.csv"
        app_mod.App._csv_writable_cached(a, p)                    # primo probe async (n=1)
        _attendi_worker(a)                                       # n=1 completa (fast)
        clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
        app_mod.App._csv_writable_cached(a, p)                    # worker appeso (n=2)

    assert len([t for t, _p, _s in a._csv_probe_threads if t.is_alive()]) == cap

    # Cap saturo di path ABBANDONATI: il path corrente usa lo SLOT RISERVATO
    # (priorità al path attivo, review Fugu) — il suo worker parte comunque.
    app_mod.App._csv_writable_cached(a, "C:/riserva.csv")         # primo probe async (n=1)
    _attendi_worker(a)                                           # n=1 completa (fast)
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    r_ris = app_mod.App._csv_writable_cached(a, "C:/riserva.csv") # worker (appeso, n=2)
    assert r_ris == ("GREEN", "ok:C:/riserva.csv"), (
        "col cap saturo il path corrente deve poter sondare (slot riservato)")
    assert len([t for t, _p, _s in a._csv_probe_threads if t.is_alive()]) == cap + 1

    # Esaurito anche lo slot riservato (cap+1 worker appesi su path abbandonati): il
    # PRIMO probe async di un path nuovo non trova slot → niente worker e GIALLO
    # ONESTO subito (A1 #114: prima il primo probe girava sincrono e partiva).
    r = app_mod.App._csv_writable_cached(a, "C:/extra.csv")

    assert r[0] == app_mod.health_check.YELLOW
    assert "troppi controlli" in r[1]
    assert len([t for t, _p, _s in a._csv_probe_threads if t.is_alive()]) == cap + 1, (
        "oltre il bound duro (cap+1) NESSUN nuovo worker deve partire")

    blocco.set()                                  # le share «rispondono»: cleanup
    for t, _p, _s in list(a._csv_probe_threads):
        t.join(timeout=5)
    assert not any(t.is_alive() for t, _p, _s in a._csv_probe_threads)


def test_guardia_worker_e_scritture_cache_sotto_lock():
    """Review Fable final PR #111 (pin strutturale, pattern #311): la guardia
    cambio-path + scrittura cache del worker devono stare SOTTO `with lock:`
    (niente TOCTOU check→set), e anche le scritture sync/stallo della cache
    devono passare dal lock. Il probe I/O invece NON deve mai girare sotto lock
    (bloccherebbe il kick del thread Tk)."""
    src = _APP_SRC.read_text(encoding="utf-8")
    corpo = src[src.index("def _kick_csv_probe_async"):]
    corpo = corpo[:corpo.index("def _live_health_items")]
    # Nel worker: `with lock:` prima del check `cached[0] != path` e del set.
    i_worker = corpo.index("def _worker():")
    blocco_worker = corpo[i_worker:]
    assert re.search(
        r"with lock:\s*\n\s+cached = self\.__dict__\.get\(\"_csv_probe_cache\"\)",
        blocco_worker), "guardia cambio-path del worker fuori dal lock (TOCTOU)"
    # L'I/O del probe resta FUORI dal lock (prima del `with lock:`).
    assert blocco_worker.index("health_check.csv_writable(path)") < \
        blocco_worker.index("with lock:")
    # TUTTE le altre scritture della cache (sync, stallo watchdog, cap rifiutato)
    # passano dal lock — e nel watchdog la RI-LETTURA anti-race sta nella stessa
    # sezione critica del set (Fable final 2° giro: niente finestra check→set).
    fn_cached = src[src.index("def _csv_writable_cached"):src.index("def _kick_csv_probe_async")]
    assert fn_cached.count('setdefault("_csv_probe_lock"') == 5, (
        "le 5 scritture della cache in _csv_writable_cached devono essere serializzate "
        "dal lock: cap rifiutato + stallo watchdog (rami TTL-scaduto), force (sync), e i "
        "due nuovi rami del primo probe async A1 #114 (provvisorio + cap saturo)")
    dentro_lock = re.findall(
        r"with self\.__dict__\.setdefault\(\"_csv_probe_lock\".*\n(?:\s+#.*\n)*\s+cur = "
        r"self\.__dict__\.get\(\"_csv_probe_cache\"\)", fn_cached)
    assert len(dentro_lock) == 2, (
        "la ri-lettura anti-clobber deve stare DENTRO la sezione critica in ENTRAMBI "
        "i rami di degrado (watchdog di stallo E cap rifiutato — review Fugu)")


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

    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # 1: primo probe async ok
    _attendi_worker(a)                                             # seed (n=1)
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # 2: async, solleva
    _attendi_worker(a)

    # Rilascio NATURALE: il worker morto esce dal registro alla potatura del
    # prossimo kick — nessun thread vivo resta a bloccare il retry.
    assert not any(t.is_alive() for t, _p, _s in a._csv_probe_threads)
    clock["now"] += app_mod._CSV_PROBE_TTL_S + 0.1
    app_mod.App._csv_writable_cached(a, "Z:/s.csv")                 # 3: riprova
    _attendi_worker(a)
    assert esiti["n"] == 3
