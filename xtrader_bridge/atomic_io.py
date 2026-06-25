"""Scrittura atomica unica e condivisa (audit #105 — helper trasversale).

Tutti i salvataggi safety-critical del bridge (config, CSV segnali, stato
dedupe/daily, parser, profili) devono essere ATOMICI: un crash/blackout o un
errore a metà scrittura non deve mai lasciare un file troncato al posto di uno
valido — altrimenti XTrader leggerebbe un CSV parziale o l'app ripartirebbe dai
default per un `config.json` mezzo scritto.

La sequenza corretta (``mkstemp`` nella STESSA cartella del file finale →
scrivi → ``flush`` → ``os.fsync`` → ``os.replace``, con rimozione del
temporaneo su QUALSIASI errore) era duplicata in 7 moduli, con rischio di drift
fra le copie. Qui è centralizzata una volta sola: i moduli delegano a queste
funzioni invece di re-implementare lo schema.

Garanzie:
- il temporaneo sta nella stessa cartella del file finale, così ``os.replace``
  è un rename atomico sullo stesso filesystem (niente copy cross-device);
- su qualsiasi eccezione (scrittura o rename) il temporaneo viene rimosso e
  l'eccezione ri-sollevata: il file preesistente resta intatto;
- ``mkstemp`` dà un nome unico, quindi due scritture concorrenti sullo stesso
  path non si pestano il temporaneo a vicenda.
"""

import json
import os
import tempfile


def atomic_write(path, write_fn, *, prefix="tmp_", suffix=".tmp", mode="w",
                 encoding="utf-8", newline=None, replace=None):
    """Scrive `path` in modo atomico eseguendo ``write_fn(f)`` su un file
    temporaneo nella STESSA cartella, poi ``flush`` + ``os.fsync`` e infine
    ``replace(tmp, path)``.

    Su qualsiasi eccezione (anche dentro ``write_fn``, anche nel rename) il
    temporaneo viene rimosso e l'eccezione ri-sollevata, lasciando il file
    preesistente intatto.

    Parametri:
    - ``write_fn``: callback che riceve il file aperto e ci scrive il contenuto.
    - ``prefix``/``suffix``: nome del temporaneo. Alcuni chiamanti/test filtrano
      i file per prefisso (es. ``.segnali_`` del CSV, ``.parser_``), quindi va
      preservato per sito.
    - ``mode``/``encoding``/``newline``: passati a ``os.fdopen``. Per la modalità
      binaria (``"wb"``) usare ``encoding=None``: ``newline`` non viene passato.
    - ``replace``: rename finale. Iniettabile per il retry su lock Windows
      (``csv_writer._replace_with_retry``). ``None`` (default) usa ``os.replace``
      risolto a CALL-TIME, così un test può patchare ``atomic_io.os.replace``.
    """
    if replace is None:
        replace = os.replace
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=prefix, suffix=suffix)
    try:
        open_kwargs = {}
        if "b" not in mode:
            # `newline`/`encoding` sono argomenti SOLO della modalità testo:
            # passarli in binario solleverebbe ValueError.
            open_kwargs["encoding"] = encoding
            open_kwargs["newline"] = newline
        with os.fdopen(fd, mode, **open_kwargs) as f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path, text, *, prefix="tmp_", suffix=".tmp",
                      encoding="utf-8", newline=None, replace=None):
    """Scrive la stringa `text` su `path` in modo atomico (vedi `atomic_write`)."""
    atomic_write(path, lambda f: f.write(text), prefix=prefix, suffix=suffix,
                 encoding=encoding, newline=newline, replace=replace)


def atomic_write_json(path, obj, *, prefix="tmp_", suffix=".tmp",
                      encoding="utf-8", replace=None, **dump_kwargs):
    """Serializza `obj` in JSON e lo scrive su `path` in modo atomico.

    ``dump_kwargs`` è inoltrato a ``json.dumps`` (es. ``indent=2``,
    ``ensure_ascii=False``)."""
    atomic_write_text(path, json.dumps(obj, **dump_kwargs), prefix=prefix,
                      suffix=suffix, encoding=encoding, replace=replace)
