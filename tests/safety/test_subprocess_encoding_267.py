"""#267 — `text=True` senza `encoding` decodifica col codepage del sistema, non in UTF-8.

`subprocess.run(..., text=True)` senza `encoding=` decodifica l'output del figlio con
`locale.getpreferredencoding(False)`. Su Linux con locale UTF-8 è UTF-8 e non si nota nulla; su
Windows è il **codepage ANSI** (cp1252 in Italia) e su un ambiente con locale POSIX è **ASCII**.

Misurato in questo repository, con l'accento presente **solo nei byte emessi** (riga di comando
pura ASCII, così l'errore non può venire dall'exec):

    ambiente non-UTF8, senza encoding=    → UnicodeDecodeError
    ambiente non-UTF8, encoding="utf-8"   → 'caffè', corretto

Il sito che conta di più è `tools/forbidden_paths.py::_git`, perché gira nel check CI
`forbidden-files`: è la guardia che impedisce di committare `config.json`, `.env`, CSV generati o
segreti. Una guardia che non riesce a **leggere** l'elenco dei file tracciati è una guardia che
non guarda.

Nota onesta sulla portata reale: `git` di default (`core.quotepath=true`) **cita** i percorsi non
ASCII in escape ottali, quindi l'output è ASCII puro e il difetto non si manifesta. Diventa
raggiungibile con `core.quotepath=false`, che molti impostano proprio per vedere gli accenti nei
nomi di file. Non è quindi un guasto quotidiano — è una dipendenza silenziosa da una
configurazione di git e dal locale della macchina, e sono esattamente le condizioni che cambiano
senza che nessuno se ne accorga.

`errors=` **non** si usa: `errors="replace"` trasformerebbe un percorso illeggibile in uno
storpiato, che poi non combacia più con `PERCORSI_VIETATI` — un file vietato passerebbe in
silenzio. Per una guardia il fallimento rumoroso è la direzione sicura.
"""

import ast
import os
import pathlib
import subprocess
import sys

import pytest

_RADICE = pathlib.Path(__file__).resolve().parents[2]

# Chiamate che accettano `text=`/`universal_newlines=` e quindi decodificano.
_CHIAMATE_TESTUALI = {"run", "check_output", "Popen", "check_call", "call"}


def _file_python_tracciati() -> list:
    """I `.py` tracciati da git. `-z` + split su NUL: i percorsi con spazi non si spezzano."""
    try:
        res = subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=_RADICE,
                             capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:      # NON blind: `git` assente/non eseguibile, niente altro
        pytest.fail(f"`git` non disponibile ({exc}): la guardia non può enumerare i file.")
    assert res.returncode == 0, f"git ls-files fallito: {res.stderr[:400]}"
    return [p for p in res.stdout.split("\0") if p]


def _siti_senza_encoding() -> list:
    """`(percorso, riga)` di ogni chiamata subprocess testuale **priva** di `encoding=`.

    Analisi su **AST**, non su testo: un `text=True` dentro un commento o una docstring non deve
    contare, e una chiamata scritta su più righe deve contare lo stesso.
    """
    siti = []
    for rel in _file_python_tracciati():
        percorso = _RADICE / rel
        try:
            albero = ast.parse(percorso.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue        # file illeggibile o non parsabile: se ne occupano altri gate
        for nodo in ast.walk(albero):
            if not isinstance(nodo, ast.Call):
                continue
            f = nodo.func
            nome = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if nome not in _CHIAMATE_TESTUALI:
                continue
            chiavi = {k.arg for k in nodo.keywords}
            if ("text" in chiavi or "universal_newlines" in chiavi) and "encoding" not in chiavi:
                siti.append((rel, nodo.lineno))
    return sorted(siti)


def test_267_nessuna_chiamata_subprocess_decodifica_col_codepage_di_sistema():
    """La guardia di classe: **zero** siti, su tutto il repository.

    Non un elenco di eccezioni ammesse. Un `text=True` senza `encoding` è sempre una dipendenza
    dal locale della macchina che esegue, e questo repository ha Windows come bersaglio primario —
    cioè proprio l'ambiente in cui il default non è UTF-8.
    """
    siti = _siti_senza_encoding()
    assert siti == [], (
        "chiamate subprocess che decodificano col codepage di sistema invece che in UTF-8:\n"
        + "\n".join(f"  {p}:{r}" for p, r in siti)
        + "\n\nAggiungi encoding=\"utf-8\". NON aggiungere errors=: mascherare un output "
          "illeggibile è peggio del fallimento."
    )


def test_267_la_guardia_vede_davvero_un_sito_senza_encoding(tmp_path):
    """Contro-guardia della guardia: senza questo, un `_siti_senza_encoding` rotto — che torna
    sempre `[]` — renderebbe il test qui sopra verde per sempre e cieco per sempre.

    È già successo in questo repository (#224: il gate blind-except contava, ma non sapeva dove;
    #263: era verde perché non guardava `license_manager/`).
    """
    sorgente = (
        "import subprocess\n"
        "subprocess.run(['x'], text=True)\n"                       # ← va trovato
        "subprocess.run(['y'], text=True, encoding='utf-8')\n"     # ← NON va trovato
        "subprocess.run(['z'])\n"                                  # ← binario: NON va trovato
        "# subprocess.run(['w'], text=True)  commento\n"           # ← invisibile all'AST
    )
    albero = ast.parse(sorgente)
    trovati = []
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            nome = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            chiavi = {k.arg for k in nodo.keywords}
            if nome in _CHIAMATE_TESTUALI and "text" in chiavi and "encoding" not in chiavi:
                trovati.append(nodo.lineno)

    assert trovati == [2], f"il rilevatore deve trovare SOLO la riga 2, ha trovato {trovati}"


def test_267_git_legge_un_percorso_accentato_anche_con_locale_non_utf8(tmp_path):
    """Il test **comportamentale**: `tools.forbidden_paths._git` sul codice reale.

    Gira in un processo figlio con il locale forzato a POSIX e la coercizione di Python
    disattivata (`PYTHONCOERCECLOCALE=0`, `PYTHONUTF8=0`), cioè un ambiente in cui
    `locale.getpreferredencoding(False)` è ASCII — la simulazione più vicina, su Linux, al
    codepage ANSI di Windows.

    Il repository di prova ha `core.quotepath=false` e un file con accento: è la configurazione
    in cui `git ls-files` emette byte UTF-8 grezzi invece degli escape ottali.

    **Rosso prima della patch** con `UnicodeDecodeError`, verde dopo.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    ambiente_git = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig-vuoto"),
                    "GIT_CONFIG_SYSTEM": os.devnull}
    for args in (["init", "-q", "."],
                 ["config", "core.quotepath", "false"],
                 ["config", "user.email", "t@e.st"],
                 ["config", "user.name", "T"]):
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                           text=True, encoding="utf-8", env=ambiente_git)
        assert r.returncode == 0, f"git {args[0]} fallito: {r.stderr[:300]}"
    (repo / "caffè.txt").write_text("x", encoding="utf-8")
    r = subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True,
                       text=True, encoding="utf-8", env=ambiente_git)
    assert r.returncode == 0, r.stderr[:300]

    # Il figlio stampa SOLO ASCII: il verdetto non deve dipendere dalla codifica del suo stdout,
    # altrimenti si misura il print invece del codice sotto test.
    programma = (
        "import os, sys\n"
        "os.chdir(sys.argv[1])\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from tools import forbidden_paths\n"
        "try:\n"
        "    righe = forbidden_paths._righe(forbidden_paths._git(['ls-files']))\n"
        "except UnicodeDecodeError as exc:\n"
        "    print('DECODE_ERROR:' + type(exc).__name__)\n"
        "    raise SystemExit(0)\n"
        "atteso = 'caff\\u00e8.txt'\n"
        "print('OK' if righe == [atteso] else 'SBAGLIATO:' + repr(righe).encode("
        "'ascii', 'backslashreplace').decode('ascii'))\n"
    )
    figlio = subprocess.run(
        [sys.executable, "-c", programma, str(repo), str(_RADICE)],
        capture_output=True, text=True, encoding="utf-8",
        env={**ambiente_git, "LC_ALL": "C", "LANG": "C",
             "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"})

    assert figlio.returncode == 0, f"il figlio è morto: {figlio.stderr[-600:]}"
    esito = figlio.stdout.strip()
    assert esito == "OK", (
        f"`_git` non ha letto il percorso accentato in un ambiente non-UTF8: {esito}\n"
        "È la guardia `forbidden-files`: se non riesce a leggere l'elenco dei file tracciati, "
        "non può accorgersi di un segreto committato."
    )


def test_267_l_ambiente_del_test_precedente_e_DAVVERO_non_utf8():
    """Contro-guardia dell'ambiente, non del codice — e serve.

    Se un domani Python cambiasse il default (PEP 686: UTF-8 mode acceso di serie) o se la
    coercizione del locale non fosse disattivabile, il test qui sopra resterebbe **verde senza
    dimostrare nulla**: passerebbe perché l'ambiente è UTF-8, non perché `encoding=` c'è.

    È il difetto che questa serie di PR continua a incontrare — un controllo che sembra guardare
    e non guarda — quindi qui si verifica esplicitamente che il locale sia davvero degradato.
    """
    figlio = subprocess.run(
        [sys.executable, "-c",
         "import locale; print(locale.getpreferredencoding(False))"],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "LC_ALL": "C", "LANG": "C",
             "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"})

    codifica = figlio.stdout.strip().lower()
    assert "utf" not in codifica, (
        f"l'ambiente di prova è ancora UTF-8 ({codifica!r}): il test comportamentale "
        "passerebbe senza dimostrare nulla. Va rivisto il modo di degradare il locale."
    )
