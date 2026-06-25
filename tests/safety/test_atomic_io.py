"""Test hard dell'helper di scrittura atomica condiviso (`xtrader_bridge.atomic_io`).

Esercitano le funzioni reali e i failure mode safety-critical: crash a metà
scrittura, crash/power-loss tra write e rename, residui temporanei, fsync,
modalità binaria e `replace` iniettato (retry su lock Windows). L'invariante
chiave: un errore NON deve mai lasciare un file troncato al posto di uno valido.
"""

import json
import os

import pytest

from xtrader_bridge import atomic_io


def _leftovers(d, prefix):
    return [f for f in os.listdir(str(d)) if f.startswith(prefix)]


def test_atomic_write_text_scrive_contenuto(tmp_path):
    p = tmp_path / "out.txt"
    atomic_io.atomic_write_text(str(p), "ciao", prefix=".t_", suffix=".tmp")
    assert p.read_text(encoding="utf-8") == "ciao"
    assert _leftovers(tmp_path, ".t_") == []          # nessun temporaneo residuo


def test_atomic_write_json_con_kwargs(tmp_path):
    p = tmp_path / "out.json"
    atomic_io.atomic_write_json(str(p), {"b": 2, "a": 1}, indent=2, sort_keys=True)
    # indent/sort_keys inoltrati a json.dumps
    assert p.read_text(encoding="utf-8") == json.dumps({"a": 1, "b": 2}, indent=2, sort_keys=True)
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_crash_durante_write_lascia_intatto_il_file_esistente(tmp_path):
    # Power-loss/eccezione DENTRO write_fn: il file preesistente resta valido,
    # nessun temporaneo residuo, l'eccezione propaga.
    p = tmp_path / "data.txt"
    atomic_io.atomic_write_text(str(p), "VECCHIO", prefix=".t_", suffix=".tmp")

    def boom_write(f):
        f.write("PARZIALE")
        raise RuntimeError("crash a metà scrittura")

    with pytest.raises(RuntimeError):
        atomic_io.atomic_write(str(p), boom_write, prefix=".t_", suffix=".tmp")

    assert p.read_text(encoding="utf-8") == "VECCHIO"     # vecchio intatto, non troncato
    assert _leftovers(tmp_path, ".t_") == []              # temporaneo rimosso


def test_crash_tra_write_e_replace_lascia_intatto_il_file(tmp_path, monkeypatch):
    # Crash ESATTAMENTE tra la fine della scrittura del tmp e il rename atomico:
    # il file finale (vecchio) deve restare intatto e il tmp va rimosso.
    p = tmp_path / "data.txt"
    atomic_io.atomic_write_text(str(p), "VECCHIO", prefix=".t_", suffix=".tmp")

    def boom_replace(src, dst):
        raise OSError("rename interrotto (blackout simulato)")

    monkeypatch.setattr(atomic_io.os, "replace", boom_replace)
    with pytest.raises(OSError):
        atomic_io.atomic_write_text(str(p), "NUOVO", prefix=".t_", suffix=".tmp")
    monkeypatch.undo()

    assert p.read_text(encoding="utf-8") == "VECCHIO"     # nessuna sovrascrittura parziale
    assert _leftovers(tmp_path, ".t_") == []              # nessun .tmp lasciato


def test_fsync_viene_chiamato(tmp_path, monkeypatch):
    # La durabilità dipende da fsync: deve essere invocato sul fd del temporaneo
    # PRIMA del rename (altrimenti un blackout subito dopo perderebbe i dati).
    p = tmp_path / "out.txt"
    chiamato = {"fsync": 0, "replace_after_fsync": False}
    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd):
        chiamato["fsync"] += 1
        return real_fsync(fd)

    def spy_replace(src, dst):
        chiamato["replace_after_fsync"] = chiamato["fsync"] > 0
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_io.os, "fsync", spy_fsync)
    monkeypatch.setattr(atomic_io.os, "replace", spy_replace)
    atomic_io.atomic_write_text(str(p), "x", prefix=".t_", suffix=".tmp")

    assert chiamato["fsync"] >= 1
    assert chiamato["replace_after_fsync"] is True


def test_modalita_binaria(tmp_path):
    # mode="wb" + encoding=None: scrive byte grezzi (usato dalla migrazione legacy
    # del config, che copia un file potenzialmente non-UTF-8).
    p = tmp_path / "bin.dat"
    payload = b"\x00\x01\x02ABC\xff"

    def write_bytes(f):
        f.write(payload)

    atomic_io.atomic_write(str(p), write_bytes, prefix=".b_", suffix=".tmp",
                           mode="wb", encoding=None)
    assert p.read_bytes() == payload
    assert _leftovers(tmp_path, ".b_") == []


def test_replace_iniettato_viene_usato(tmp_path):
    # Il `replace` iniettato (es. retry su lock Windows in csv_writer) deve essere
    # usato al posto di os.replace.
    p = tmp_path / "out.txt"
    usato = {"n": 0}

    def my_replace(src, dst):
        usato["n"] += 1
        os.replace(src, dst)

    atomic_io.atomic_write_text(str(p), "z", prefix=".t_", suffix=".tmp", replace=my_replace)
    assert usato["n"] == 1
    assert p.read_text(encoding="utf-8") == "z"


def test_crea_la_cartella_mancante(tmp_path):
    # La cartella di destinazione viene creata se non esiste (makedirs).
    p = tmp_path / "sub" / "dir" / "out.txt"
    atomic_io.atomic_write_text(str(p), "ok", prefix=".t_", suffix=".tmp")
    assert p.read_text(encoding="utf-8") == "ok"


def test_temporaneo_nella_stessa_cartella(tmp_path, monkeypatch):
    # Il temporaneo DEVE stare nella stessa cartella del file finale, altrimenti
    # os.replace sarebbe una copia cross-device non atomica. Lo verifichiamo
    # intercettando il rename e controllando la cartella del src.
    p = tmp_path / "out.txt"
    visti = {}
    real_replace = os.replace

    def spy_replace(src, dst):
        visti["src_dir"] = os.path.dirname(os.path.abspath(src))
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_io.os, "replace", spy_replace)
    atomic_io.atomic_write_text(str(p), "x", prefix=".t_", suffix=".tmp")
    assert visti["src_dir"] == os.path.dirname(os.path.abspath(str(p)))
