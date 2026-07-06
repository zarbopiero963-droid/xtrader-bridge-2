"""#311-1.1: single-instance lock — il guardiano anti DOPPIA ISTANZA (= anti doppia
scommessa: due processi bridge hanno tracker/limiter/coda separati in RAM).

Esercita il modulo REALE `instance_lock` sul percorso POSIX (flock), che ha le stesse
proprietà del mutex Windows rilevanti per la sicurezza: esclusività tra acquisizioni
concorrenti e auto-rilascio a morte del processo. Il ramo Windows (ctypes) è smoke
manuale documentato (doppio avvio su PC reale).
"""

import pytest

from xtrader_bridge import instance_lock


def test_acquire_esclusivo_seconda_acquisizione_rifiutata(tmp_path):
    # Prima istanza: lock acquisito. Seconda (stesso nome/cartella): RIFIUTATA (None).
    a = instance_lock.acquire("TestBridge", str(tmp_path))
    assert a is not None and a.kind == "flock"
    b = instance_lock.acquire("TestBridge", str(tmp_path))
    assert b is None                          # altra "istanza" → rifiuto certo
    instance_lock.release(a)


def test_release_permette_la_riacquisizione(tmp_path):
    a = instance_lock.acquire("TestBridge", str(tmp_path))
    instance_lock.release(a)
    b = instance_lock.acquire("TestBridge", str(tmp_path))
    assert b is not None                      # dopo il rilascio si può ripartire
    instance_lock.release(b)


def test_release_stantia_non_sblocca_il_nuovo_detentore(tmp_path):
    # SAFETY: un release DOPPIO su un handle già rilasciato (es. atexit + _on_close)
    # non deve MAI sbloccare il lock della NUOVA istanza (il SO può riusare lo stesso
    # fd). Il flag `released` rende il release idempotente. Fail-first: senza il flag,
    # il release stantio farebbe LOCK_UN sull'fd riusato dalla nuova istanza.
    a = instance_lock.acquire("TestBridge", str(tmp_path))
    instance_lock.release(a)
    b = instance_lock.acquire("TestBridge", str(tmp_path))   # può riusare lo stesso fd
    assert b is not None
    instance_lock.release(a)                  # release STANTIA (handle già rilasciato)
    c = instance_lock.acquire("TestBridge", str(tmp_path))
    assert c is None                          # b detiene ANCORA il lock: nessuna doppia istanza
    instance_lock.release(b)


def test_release_none_e_noop_sono_innocui(tmp_path):
    instance_lock.release(None)                                   # nessun crash
    instance_lock.release(instance_lock.InstanceLockHandle("noop", None))


def test_errore_imprevisto_fail_open_con_handle_noop(tmp_path, monkeypatch):
    # Un guasto RARO del SO nella CREAZIONE del lock non deve rendere il bridge
    # inavviabile: acquire ritorna un handle no-op (≠ None → l'avvio procede),
    # loggando il warning. Il rifiuto (None) resta SOLO per «lock già posseduto».
    monkeypatch.setattr(instance_lock, "_acquire_posix",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    h = instance_lock.acquire("TestBridge", str(tmp_path))
    assert h is not None and h.kind == "noop"


def test_lockfile_non_cancellato_al_release(tmp_path):
    # Il release NON cancella il file (rimuoverlo sarebbe raceabile con un'istanza in
    # avvio): è il flock, non l'esistenza del file, a fare da lock.
    a = instance_lock.acquire("TestBridge", str(tmp_path))
    path = a.path
    instance_lock.release(a)
    import os
    assert os.path.exists(path)


def test_lock_dir_creata_se_mancante(tmp_path):
    # Primo avvio assoluto: la cartella dati può non esistere ancora (viene creata
    # da load_config DOPO il lock) → acquire la crea da sé.
    nested = str(tmp_path / "non" / "esiste")
    a = instance_lock.acquire("TestBridge", nested)
    assert a is not None
    instance_lock.release(a)
