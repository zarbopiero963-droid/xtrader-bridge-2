"""A8: le cache lazy globali (`mapping._index`, `custom_pipeline._default_registry`)
devono costruirsi UNA sola volta anche sotto uso concorrente.

I test forzano la corsa: più thread chiamano la funzione nello stesso istante
(`Barrier`), con la build resa lenta e contata. Senza lock la build partirebbe
più volte; col double-checked locking deve partire esattamente una volta e tutti
i thread devono ricevere lo STESSO oggetto in cache.
"""

import threading

from xtrader_bridge import custom_pipeline, mapping


def _run_concurrently(fn, n=8):
    """Lancia `fn` in `n` thread che partono insieme (Barrier) e raccoglie i
    risultati nell'ordine di completamento."""
    barrier = threading.Barrier(n)
    results = [None] * n

    def worker(i):
        barrier.wait()           # sincronizza la partenza → massimizza la corsa
        results[i] = fn()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_index_costruito_una_sola_volta_sotto_concorrenza(monkeypatch):
    # Reset della cache + build lenta e contata, così la finestra di corsa è reale.
    monkeypatch.setattr(mapping, "_INDEX", None)
    calls = []
    real_load = mapping.load_dizionario

    def slow_load():
        calls.append(1)
        # piccola attesa: senza lock altri thread entrerebbero nella build
        threading.Event().wait(0.02)
        return real_load()

    monkeypatch.setattr(mapping, "load_dizionario", slow_load)

    results = _run_concurrently(mapping._index, n=8)

    assert len(calls) == 1                         # costruito UNA sola volta
    first = results[0]
    assert all(r is first for r in results)        # stesso identico oggetto cache
    assert mapping._index() is first               # chiamate successive: stessa cache
    assert first  # l'indice reale non è vuoto


def test_default_registry_costruito_una_sola_volta_sotto_concorrenza(monkeypatch):
    monkeypatch.setattr(custom_pipeline, "_DEFAULT_REGISTRY", None)
    calls = []
    real_registry = custom_pipeline.value_maps.registry

    def slow_registry(*args, **kwargs):
        calls.append(1)
        threading.Event().wait(0.02)
        return real_registry(*args, **kwargs)

    monkeypatch.setattr(custom_pipeline.value_maps, "registry", slow_registry)

    results = _run_concurrently(custom_pipeline._default_registry, n=8)

    assert len(calls) == 1                          # registro costruito una volta sola
    first = results[0]
    assert all(r is first for r in results)
    assert custom_pipeline._default_registry() is first
    assert "bettype" in first                       # registro reale popolato
