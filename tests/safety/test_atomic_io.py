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


# ── H2 (#184): fsync della DIRECTORY dopo il rename (durabilità del crash) ────

def test_fsync_della_directory_dopo_il_replace(tmp_path, monkeypatch):
    # Dopo `os.replace`, la directory padre deve essere fsync'd: altrimenti un
    # power-loss subito dopo il rename può far ricomparire il contenuto precedente.
    order = []
    real_replace = os.replace
    real_fsync_dir = atomic_io._fsync_dir

    def spy_replace(src, dst):
        order.append("replace")
        return real_replace(src, dst)

    def spy_fsync_dir(d):
        order.append(("fsync_dir", os.path.abspath(d)))
        return real_fsync_dir(d)

    monkeypatch.setattr(atomic_io.os, "replace", spy_replace)
    monkeypatch.setattr(atomic_io, "_fsync_dir", spy_fsync_dir)

    p = tmp_path / "out.txt"
    atomic_io.atomic_write_text(str(p), "x", prefix=".t_", suffix=".tmp")

    assert p.read_text(encoding="utf-8") == "x"
    # il fsync della dir avviene DOPO il replace, sulla cartella giusta
    assert order[0] == "replace"
    assert order[1] == ("fsync_dir", os.path.dirname(os.path.abspath(str(p))))


def test_fsync_dir_e_no_op_su_dir_non_apribile(tmp_path):
    # Su Windows (o dir inesistente) non si può aprire la dir come fd: deve essere un
    # no-op silenzioso, mai un'eccezione.
    atomic_io._fsync_dir(str(tmp_path / "non_esiste"))     # non deve sollevare


def test_fsync_dir_errore_di_fsync_non_propaga(tmp_path, monkeypatch):
    # Un filesystem che rifiuta l'fsync di una directory non deve far fallire la scrittura.
    def boom_fsync(fd):
        raise OSError("EINVAL: fsync su directory non supportato")

    monkeypatch.setattr(atomic_io.os, "fsync", boom_fsync)
    atomic_io._fsync_dir(str(tmp_path))                    # OSError swallowed, niente raise


# ── LOW (#184): sweep dei temporanei orfani allo startup ─────────────────────

def test_sweep_rimuove_solo_i_temporanei_combacianti(tmp_path):
    # Orfani `{prefix}…{suffix}` lasciati da un crash tra mkstemp e replace: rimossi.
    # Il file finale e altri file NON combacianti restano intatti.
    (tmp_path / ".segnali_aaa.tmp").write_text("orfano1")
    (tmp_path / ".segnali_bbb.tmp").write_text("orfano2")
    (tmp_path / "segnali.csv").write_text("CSV REALE")          # file finale: non combacia
    (tmp_path / ".dedupe_x.tmp").write_text("altro prefix")     # prefisso diverso
    (tmp_path / ".segnali_keep.json").write_text("suffix div")  # suffisso diverso

    removed = atomic_io.sweep_orphan_temps(str(tmp_path), ".segnali_", ".tmp")

    assert removed == 2
    assert not (tmp_path / ".segnali_aaa.tmp").exists()
    assert not (tmp_path / ".segnali_bbb.tmp").exists()
    assert (tmp_path / "segnali.csv").read_text() == "CSV REALE"   # CSV reale intatto
    assert (tmp_path / ".dedupe_x.tmp").exists()                   # altro prefix non toccato
    assert (tmp_path / ".segnali_keep.json").exists()              # altro suffix non toccato


def test_sweep_prefix_vuoto_e_no_op(tmp_path):
    # Prefisso vuoto: rifiuto di spazzare un'intera cartella per solo suffisso.
    (tmp_path / "qualsiasi.tmp").write_text("x")
    assert atomic_io.sweep_orphan_temps(str(tmp_path), "", ".tmp") == 0
    assert (tmp_path / "qualsiasi.tmp").exists()


def test_sweep_cartella_inesistente_non_solleva(tmp_path):
    # Cartella assente/non listabile → 0, mai un'eccezione (best-effort allo startup).
    assert atomic_io.sweep_orphan_temps(str(tmp_path / "non_esiste"), ".segnali_") == 0
    assert atomic_io.sweep_orphan_temps("", ".segnali_") == 0


def test_sweep_non_rimuove_una_sottocartella_omonima(tmp_path):
    # Una *cartella* che combacia col pattern non deve essere rimossa (solo file).
    d = tmp_path / ".segnali_dir.tmp"
    d.mkdir()
    assert atomic_io.sweep_orphan_temps(str(tmp_path), ".segnali_", ".tmp") == 0
    assert d.is_dir()


def test_sweep_salta_il_file_non_rimovibile_e_continua(tmp_path, monkeypatch):
    # Un os.remove che fallisce (file in uso/permessi) non deve fermare lo sweep:
    # gli altri orfani vengono comunque rimossi, nessuna eccezione propaga.
    (tmp_path / ".segnali_a.tmp").write_text("1")
    (tmp_path / ".segnali_b.tmp").write_text("2")
    real_remove = os.remove

    def flaky_remove(p):
        if p.endswith(".segnali_a.tmp"):
            raise OSError("file in uso (XTrader)")
        return real_remove(p)

    monkeypatch.setattr(atomic_io.os, "remove", flaky_remove)
    removed = atomic_io.sweep_orphan_temps(str(tmp_path), ".segnali_", ".tmp")
    assert removed == 1                                  # solo b rimosso, a saltato
    assert (tmp_path / ".segnali_a.tmp").exists()        # non rimovibile: resta
    assert not (tmp_path / ".segnali_b.tmp").exists()


def test_dir_fsync_fallito_non_perde_il_file(tmp_path, monkeypatch):
    # Esercita il path di FALLIMENTO del fsync della dir attraverso il codice reale: si
    # forza `os.close(dir_fd)` (nel finally di `_fsync_dir`) a sollevare, DOPO un replace
    # già riuscito. Il contratto best-effort/non-raising deve reggere: il file resta
    # scritto e non c'è temporaneo residuo (CodeRabbit). In atomic_write l'unico `os.close`
    # è quello di `_fsync_dir` (il temporaneo è chiuso dal `with os.fdopen`).
    real_close = os.close

    def boom_close(fd):
        real_close(fd)                                     # chiudi davvero il fd (no leak)…
        raise OSError("EIO: close della directory fallita")  # …poi simula l'errore

    monkeypatch.setattr(atomic_io.os, "close", boom_close)
    p = tmp_path / "out.txt"
    atomic_io.atomic_write_text(str(p), "NUOVO", prefix=".t_", suffix=".tmp")
    assert p.read_text(encoding="utf-8") == "NUOVO"        # file integro nonostante il close fallito
    assert _leftovers(tmp_path, ".t_") == []               # nessun temporaneo residuo
