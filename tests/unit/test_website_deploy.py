"""Invarianti dell'immagine del sito — l'unica cosa del progetto esposta su internet.

Il bridge gira sul PC di casa dell'utente; il sito gira su un server pubblico, e con lui la
`ANTHROPIC_API_KEY`. Le tre regole qui sotto sono quelle che, se saltano, non producono un test
rosso ma un incidente: un segreto dentro l'immagine pubblicata, un container che non parte, o un
deploy che installa da solo una versione di libreria che nessuno ha visto.

Sono nate dai rilievi di Claude Fable 5, Fugu Ultra e GPT-5.5 sulla PR #277. Nessuno di questi
test può accorgersi se il `docker build` fallisce — Docker non esiste nell'ambiente agente — ma
tutti e tre bloccano la regressione del *contenuto* dei file, che è dove sta il rischio.
"""

import importlib
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_WEB = _ROOT / "website"
_DOCKERFILE = _WEB / "Dockerfile"
_DOCKERIGNORE = _WEB / ".dockerignore"
_REQS = _WEB / "requirements.txt"


def _righe_utili(path: Path) -> list:
    """Righe non vuote e non di commento."""
    return [r.strip() for r in path.read_text(encoding="utf-8").splitlines()
            if r.strip() and not r.strip().startswith("#")]


def test_il_dockerignore_esiste():
    """Il Dockerfile fa `COPY . .`: senza `.dockerignore`, tutto ciò che si trova in `website/`
    al momento del build finisce nell'immagine pubblicata."""
    assert _DOCKERIGNORE.is_file(), (
        "manca website/.dockerignore: con `COPY . .` qualunque file locale entra nell'immagine")


@pytest.mark.parametrize("pattern", [".env", "__pycache__/", "*.key", "*.pem"])
def test_il_dockerignore_esclude_le_categorie_pericolose(pattern):
    """`.env` è il caso che conta: un file di prova dimenticato dopo una sessione locale
    porterebbe una API key dentro un'immagine che gira su internet."""
    assert pattern in _righe_utili(_DOCKERIGNORE), \
        "«%s» non è più escluso dall'immagine" % pattern


def test_la_porta_ha_un_default_anche_se_la_variabile_e_vuota():
    """`--port ${PORT}` con `PORT` esistente ma VUOTA passa a uvicorn un argomento vuoto e il
    container non parte — con un errore che non nomina la causa. `:-8000` copre il caso."""
    testo = _DOCKERFILE.read_text(encoding="utf-8")
    assert "${PORT:-" in testo, \
        "il CMD usa ${PORT} senza default: una PORT vuota impedisce l'avvio"
    assert re.search(r'CMD .*uvicorn main:app .*--host 0\.0\.0\.0', testo), \
        "il CMD non avvia più uvicorn sull'interfaccia pubblica del container"


def test_il_container_non_gira_come_root():
    """Un servizio esposto su internet non ha motivo di essere root nel proprio container: la
    riga `USER` deve restare, e dopo l'installazione delle dipendenze."""
    testo = _DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^USER\s+(?!root)\w+", testo, re.M), "il container gira come root"
    assert testo.index("pip install") < testo.index("\nUSER "), \
        "USER prima di pip install: l'installazione delle dipendenze fallirebbe"


def test_il_build_context_e_documentato_dove_serve():
    """`COPY requirements.txt .` funziona solo col context su `website/`. Se il Root Directory
    di Railway non è impostato, il build fallisce — e senza questa nota nessuno sa perché."""
    assert "Root Directory" in _DOCKERFILE.read_text(encoding="utf-8")
    assert "Root Directory" in (_WEB / "README.md").read_text(encoding="utf-8")


def test_le_dipendenze_del_sito_sono_pinnate():
    """`>=` significa che due deploy identici possono installare librerie diverse: la versione
    che va in produzione non è quella che è stata collaudata, e nessuno se ne accorge."""
    righe = _righe_utili(_REQS)
    assert righe, "requirements.txt vuoto"
    for riga in righe:
        assert "==" in riga, "dipendenza non pinnata: «%s»" % riga
        assert ">=" not in riga and "~=" not in riga, "vincolo non esatto: «%s»" % riga


@pytest.mark.parametrize("riga", _righe_utili(_REQS))
def test_ogni_pin_corrisponde_alla_versione_installata_dove_c_e(riga):
    """Il pin deve corrispondere a ciò con cui il sito è stato davvero eseguito, non a un numero
    scritto a memoria.

    Le dipendenze del **sito** non stanno in `requirements-dev.txt`: la CI del bridge non le
    installa, e importarle qui a secco renderebbe rossa tutta la suite del bridge per una
    libreria che non c'entra col bridge (rilievo Claude Fable 5 sulla #277). Quindi si salta
    dove non sono installate — come già fanno gli altri test del sito — e si controlla dove ci
    sono, cioè nell'ambiente in cui il sito viene davvero eseguito e collaudato.
    """
    nome, versione = riga.split("==")
    try:
        modulo = importlib.import_module(nome.split("[")[0])
    except ImportError:
        # `pytest.importorskip` salta solo su ModuleNotFoundError: un ImportError di altra
        # natura (installazione parziale, estensione C incompatibile) lo lascerebbe passare
        # come FALLIMENTO della suite del bridge, per una libreria che il bridge non usa.
        pytest.skip("dipendenza del sito non importabile qui: il pin si verifica dove il "
                    "sito gira davvero")
    installata = getattr(modulo, "__version__", None)
    assert installata is not None, (
        "%s non espone __version__: il confronto col pin non è verificabile" % nome)
    assert installata == versione, (
        "%s pinnato a %s ma qui gira %s: il pin non è quello collaudato"
        % (nome, versione, installata))
