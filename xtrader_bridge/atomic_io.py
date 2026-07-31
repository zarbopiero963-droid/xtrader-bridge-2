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
  path non si pestano il temporaneo a vicenda;
- la destinazione è **risolta attraverso i link** prima del rename (B7 #194): senza,
  ``os.replace`` sostituiva IL LINK con un file normale e il file puntato — quello che
  XTrader legge davvero — restava indietro col suo contenuto stantio.

Qui vivono anche `risolvi` e `stesso_file`: la **fonte unica** del confronto fra path per
tutte le guardie di sicurezza del bridge (B7/B8 #194). Stanno accanto alla scrittura
perché sono la stessa domanda vista dai due lati — «qual è il file VERO dietro questo
path?» — e tenerle separate è come sono nati B7 e B8.
"""

import json
import os
import tempfile


def risolvi(path) -> str:
    """Il path **reale** dietro `path` — link e junction risolti — normalizzato per il
    confronto. Fonte unica (B7/B8, #194).

    **Non solleva mai.** I chiamanti sono guardie di sicurezza invocate anche su path
    inesistenti (un `csv_path` appena digitato nella GUI), su file lockati da XTrader e su
    stringhe malformate: una guardia che esplode è peggio di una guardia che non scatta,
    perché toglie all'utente anche il rifiuto. Su qualsiasi errore si ricade su
    `abspath`, cioè esattamente il comportamento che c'era prima di questa correzione.

    `normcase` resta perché su Windows `OUT.CSV` e `out.csv` sono lo stesso file; su POSIX
    è un no-op e il confronto resta correttamente case-sensitive.
    """
    testo = str(path or "").strip()
    if not testo:
        return ""
    try:
        return os.path.normcase(os.path.realpath(testo))
    except (OSError, ValueError):
        # ValueError: path con NUL. OSError: loop di link, path troppo lungo, permessi
        # sulla catena di risoluzione. In tutti i casi si degrada al confronto di prima.
        try:
            return os.path.normcase(os.path.abspath(testo))
        except (OSError, ValueError):
            return os.path.normcase(testo)


def stesso_file(a, b) -> bool:
    """`True` se `a` e `b` sono lo **stesso file**, anche raggiunto per strade diverse
    (link, junction, case, forma relativa). Fonte unica (B7/B8, #194).

    Prova prima `os.path.samefile`, che è l'unica risposta autorevole: confronta gli inode
    (POSIX) / gli identificatori di file (Windows) e riconosce anche gli hard link, che
    nessun confronto di stringhe può vedere. Ma `samefile` **solleva** se anche solo uno
    dei due file non esiste — e le guardie del bridge vengono chiamate proprio in quel
    caso: un `csv_path` mai creato, o un file che Windows tiene lockato. Perciò
    l'`OSError` non è un errore ma il caso ordinario, e si ricade sul confronto dei path
    risolti, che è ciò che il codice faceva prima e continua a coprire case e forma
    relativa.

    Input vuoti → `False` (nessuno dei due è un file): stessa convenzione delle guardie
    che questa funzione sostituisce.
    """
    risposta = confronto_autorevole(a, b)
    if risposta is not None:
        return risposta
    if not str(a or "").strip() or not str(b or "").strip():
        return False
    return risolvi(a) == risolvi(b)


def confronto_autorevole(a, b):
    """`True`/`False` se si può stabilire con certezza che `a` e `b` sono lo stesso file,
    oppure **`None` se la domanda non ha avuto risposta** (bloccante Fugu Ultra su #203).

    È `stesso_file` senza il ripiego: tri-stato invece che booleano. La distinzione conta
    perché `stesso_file` collassa il «non lo so» sul confronto dei path — che per gli **hard
    link** risponde «file diversi», visto che `realpath` non li unifica. Su una guardia di
    sicurezza un «no» inventato è la direzione sbagliata: chi deve decidere se **bloccare**
    ha bisogno di sapere che non sa, per poter bloccare lo stesso.

    `os.path.samefile` è l'unica risposta autorevole (confronta gli inode, quindi vede anche
    gli hard link). Solleva quando un file **non esiste** — il caso innocuo di un percorso
    nuovo — ma anche quando esiste e non è ispezionabile (permessi, lock Windows): i
    chiamanti distinguono i due guardando se il file c'è.
    """
    if not str(a or "").strip() or not str(b or "").strip():
        return None
    try:
        return os.path.samefile(str(a), str(b))
    except (OSError, ValueError):
        return None


def _fsync_dir(d):
    """fsync della DIRECTORY contenitore dopo ``os.replace`` (issue #184 H2).

    I dati del file sono già fsync'd, ma POSIX **non** garantisce che la voce di
    directory creata dal rename sia durabile finché non si fsync-a anche la directory:
    su power-loss/crash subito dopo ``os.replace`` il file può tornare al contenuto
    precedente (CSV stantio, stato dedupe/daily/config vecchio). Qui si rende durabile
    anche il rename.

    **Best-effort e non solleva mai**: dove non è supportato (Windows non permette di
    aprire una directory come fd; alcuni filesystem rifiutano l'fsync di una dir) è un
    no-op silenzioso. Importante: viene chiamato DOPO un ``replace`` già riuscito, quindi
    un suo errore non deve propagare né rimuovere il file appena scritto."""
    try:
        dir_fd = os.open(d, os.O_RDONLY)
    except OSError:
        return                              # es. Windows: dir non apribile come fd → no-op
    try:
        os.fsync(dir_fd)
    except OSError:
        pass                                # fs che non supporta l'fsync di una dir → no-op
    finally:
        try:
            os.close(dir_fd)
        except OSError:
            pass                            # anche il close è best-effort: mai propagare
                                            # un errore DOPO un replace già riuscito (CodeRabbit)


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
    # B7 (#194): la destinazione va risolta ATTRAVERSO i link prima del rename. `open()` in
    # lettura segue il link, ma `os.replace(tmp, link)` sostituisce IL LINK con un file
    # normale — così `clear_stale_csv` riportava «ripulito» mentre la riga stantia restava
    # nel file puntato, quello che XTrader legge davvero. Risolvendo qui, il temporaneo
    # nasce nella cartella del file VERO (necessario perché `os.replace` resti un rename
    # atomico sullo stesso filesystem) e il link sopravvive, puntando al contenuto nuovo.
    # `realpath` di un path inesistente non solleva: ritorna il path risolto fin dove può,
    # quindi la creazione di un CSV nuovo continua a funzionare identica.
    #
    # TOCTOU, dichiarato invece che ignorato (rilievo Fable 5 su #203). Fra questa
    # risoluzione e il `replace` finale c'è una finestra: se qualcuno sostituisse il link
    # nel frattempo, si scriverebbe sulla destinazione nuova. Prima il `replace` sostituiva
    # il link senza attraversarlo, quindi la finestra non c'era — la superficie si è
    # allargata, ed è giusto dirlo.
    #
    # Non viene mitigata oltre, e la ragione è il rapporto fra i due rischi. Per sfruttarla
    # serve permesso di **scrittura sulla cartella del CSV** — ma chi ce l'ha può già
    # riscrivere il CSV direttamente, senza alcun link: il segnale che XTrader legge è
    # comunque suo. Non è quindi un'escalation, è lo stesso livello di accesso. Dall'altra
    # parte, NON risolvere è B7: un bug **misurato**, che lasciava una riga stantia sul
    # disco mentre `clear_stale_csv` riportava «ripulito». Si scambia un difetto reale e
    # osservato con una finestra che richiede un accesso già sufficiente a fare peggio.
    #
    # Se un giorno il CSV dovesse vivere in una cartella condivisa e non fidata, la
    # mitigazione giusta non è togliere la risoluzione (torna B7) ma aprire la destinazione
    # con `O_NOFOLLOW`/`FILE_FLAG_OPEN_REPARSE_POINT` e verificarne l'identità dopo il
    # rename — un lavoro che ha senso solo con quel modello di minaccia, che oggi non è
    # quello del bridge (CSV locale, macchina del proprietario).
    #
    # LIMITE DICHIARATO — gli HARD link non sono attraversabili (rilievo Fugu Ultra su
    # #203). `realpath` risolve i link SIMBOLICI e le junction, non gli hard link: quelli
    # non sono un puntatore da seguire, sono due voci di directory per lo stesso inode.
    # `os.replace` ne sostituisce UNA, e l'altro nome resta col contenuto vecchio —
    # misurato: svuotando `a.csv`, un `b.csv` hard-linkato conserva la riga stantia e i due
    # inode divergono. Se XTrader leggesse il secondo nome, continuerebbe a vedere il
    # segnale orfano.
    #
    # Non è una regressione di questa correzione: `os.replace` ha sempre rotto gli hard
    # link. E non si sistema qui, perché l'unico modo di scrivere attraverso un hard link è
    # scrivere IN PLACE (`open`+`truncate`), cioè rinunciare all'atomicità — uno scambio
    # pessimo: un crash a metà scrittura lascerebbe a XTrader un CSV troncato, che è una
    # scommessa malformata invece di una configurazione insolita. Si preferisce la garanzia
    # certa al caso raro, e lo si dichiara.
    #
    # Le GUARDIE, invece, riconoscono gli hard link (`stesso_file` usa `samefile`, che
    # confronta gli inode) — ed è la direzione giusta: bloccano di più, e bloccare è sicuro.
    # L'asimmetria è voluta, non una svista, ed è fissata da un test.
    try:
        path = os.path.realpath(path)
    except (OSError, ValueError):
        pass        # catena di link irrisolvibile: si scrive dove si scriveva prima
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=prefix, suffix=suffix)
    # `mkstemp` restituisce un fd GIA' APERTO: fino a quando `os.fdopen` non ne prende
    # possesso, un errore qui lascerebbe il descrittore orfano (il blocco d'errore in
    # fondo rimuove il file temporaneo ma NON chiuderebbe il fd). L'audit #137 lo
    # chiamava «teorico»; misurato, 20 chiamate fallite perdevano 20 descrittori — e un
    # processo che ne esaurisce la quota non riesce piu' ad aprire il CSV.
    preso_in_carico = False
    try:
        open_kwargs = {}
        if "b" not in mode:
            # `newline`/`encoding` sono argomenti SOLO della modalità testo:
            # passarli in binario solleverebbe ValueError.
            open_kwargs["encoding"] = encoding
            open_kwargs["newline"] = newline
        f = os.fdopen(fd, mode, **open_kwargs)
        preso_in_carico = True           # da qui la chiusura spetta al context manager
        with f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        replace(tmp, path)
        # Rende DURABILE anche la voce di directory del rename (H2). Best-effort e non
        # solleva: il file è già al suo posto, un fallimento qui non deve perderlo.
        _fsync_dir(d)
    except BaseException:
        if not preso_in_carico:
            # `fdopen` non e' arrivato a prendersi il fd: va chiuso a mano, altrimenti resta
            # aperto per tutta la vita del processo.
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def sweep_orphan_temps(directory, prefix, suffix=".tmp"):
    """Rimuove i temporanei ORFANI (`{prefix}…{suffix}`) lasciati in `directory`
    da una scrittura atomica interrotta da crash/blackout TRA ``mkstemp`` e
    ``os.replace`` (issue #184 LOW — `atomic_io.py`).

    ``atomic_write`` rimuove il proprio temporaneo su qualsiasi eccezione *gestita*,
    ma un crash duro del processo (power-loss, kill) tra la creazione del tmp e il
    rename salta quel cleanup: il file FINALE resta intatto (il rename non è ancora
    avvenuto) ma il temporaneo resta su disco e si accumula riavvio dopo riavvio.
    Va chiamata **allo startup**, quando non c'è alcuna scrittura in volo: ogni file
    che combacia con `prefix`+`suffix` è per forza orfano di un processo morto.

    Sicurezza:
    - rimuove SOLO i nomi che iniziano con `prefix` **e** finiscono con `suffix`: i
      file finali (es. il CSV reale, `config.json`) non hanno quel prefisso/suffisso
      e non vengono mai toccati;
    - `prefix` vuoto è un **no-op** (rifiuto di spazzare un'intera cartella per suffisso);
    - **best-effort e non solleva mai**: cartella inesistente/non listabile → 0; un
      singolo `os.remove` fallito (file in uso, permessi) viene saltato. Non deve mai
      impedire l'avvio dell'app.

    Ritorna il numero di temporanei effettivamente rimossi (utile per il log)."""
    if not prefix:
        return 0                                # guardia: mai spazzare per solo suffisso
    d = str(directory or "").strip()
    if not d:
        return 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0                                # cartella assente/non listabile → niente da fare
    removed = 0
    for name in names:
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        full = os.path.join(d, name)
        try:
            if os.path.isfile(full):            # mai rimuovere una sottocartella omonima
                os.remove(full)
                removed += 1
        except OSError:
            pass                                # file in uso/permessi: salta, best-effort
    return removed


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
