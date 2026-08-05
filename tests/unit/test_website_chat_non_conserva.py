"""La privacy dice «le conversazioni non vengono salvate sul nostro server». Qui si verifica.

Non è un dettaglio di stile: è un'**affermazione pubblica** su una pagina legale. Se un giorno
qualcuno aggiungesse un `logging.info(message)` per debuggare, o una lista globale per contare
le domande più frequenti, la pagina `/privacy` diventerebbe **falsa** — e nessun test del sito
se ne accorgerebbe, perché il sito continuerebbe a funzionare benissimo.

Il rilievo è di GPT-5.5 sulla PR #284: «attenzione al claim *non conservate*: se hosting,
observability o provider conservano dati, il testo può diventare fuorviante». La parte che
dipende da noi — il codice di `website/main.py` — la si può bloccare con un test; il resto
(log di connessione di Railway, ritenzione di Anthropic) è dichiarato in pagina come tale.

Due livelli, di proposito:

* i controlli **sul sorgente** (AST) girano ovunque, anche dove `fastapi` non è installato —
  ed è il caso della CI del bridge, che non ha le dipendenze del sito;
* il controllo **a runtime** chiama davvero l'endpoint e cerca il messaggio dell'utente nei log
  e nello stato del modulo. Salta dove `fastapi` manca, quindi non può essere l'unico.
"""

import ast
import importlib.util
import logging
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MAIN = _ROOT / "website" / "main.py"


def _albero() -> ast.Module:
    return ast.parse(_MAIN.read_text(encoding="utf-8"), filename=str(_MAIN))


def _funzione(nome: str) -> ast.AST:
    for nodo in ast.walk(_albero()):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nome:
            return nodo
    raise AssertionError("in website/main.py non esiste più la funzione «%s»" % nome)


def _nome_chiamata(nodo: ast.Call) -> str:
    """Il nome leggibile della cosa chiamata: `print`, `open`, `logger.info`, `f.write`…"""
    func = nodo.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        radice = func.value
        prefisso = radice.id if isinstance(radice, ast.Name) else "<expr>"
        return "%s.%s" % (prefisso, func.attr)
    return "<expr>"


def test_il_sito_non_importa_logging():
    """Il modulo non ha un logger applicativo, e non deve averlo di soppiatto.

    `uvicorn` registra metodo e URL delle richieste, non il **corpo** del POST: il testo della
    chat non passa dai suoi access log. Un logger scritto nel modulo, invece, ci passerebbe.
    """
    for nodo in ast.walk(_albero()):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                assert alias.name.split(".")[0] != "logging", (
                    "website/main.py importa `logging`: la privacy dichiara che le "
                    "conversazioni non vengono salvate — un logger applicativo le scriverebbe")
        if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").split(".")[0] == "logging":
            raise AssertionError("website/main.py importa da `logging` (vedi sopra)")


def test_la_chat_non_stampa_e_non_scrive_su_disco():
    """Dentro `chat()` non ci può essere nessun `print`, nessun `open`, nessuna `write`.

    `print` finisce nello stdout del container, che Railway raccoglie e conserva: sarebbe
    conservazione a tutti gli effetti, solo fatta senza accorgersene.
    """
    vietate = {"print", "open"}
    for nodo in ast.walk(_funzione("chat")):
        if not isinstance(nodo, ast.Call):
            continue
        nome = _nome_chiamata(nodo)
        assert nome not in vietate, (
            "`chat()` chiama `%s`: il messaggio dell'utente non deve finire né nei log né su "
            "disco (lo dichiara /privacy)" % nome)
        assert not nome.endswith((".write", ".write_text", ".writelines")), (
            "`chat()` chiama `%s`: il messaggio dell'utente non deve essere scritto da nessuna "
            "parte" % nome)


def _globali() -> set:
    nomi = set()
    for nodo in _albero().body:
        if isinstance(nodo, ast.Assign):
            nomi.update(t.id for t in nodo.targets if isinstance(t, ast.Name))
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            nomi.add(nodo.target.id)
    return nomi


def test_l_unico_stato_che_sopravvive_alla_richiesta_e_il_conteggio_per_ip():
    """Nessuna funzione può accumulare in una variabile globale, tranne `_hits`.

    È la forma che avrebbe la regressione vera: non un file, ma un `_TRANSCRIPTS.append(...)`
    o un `global _ultime_domande` messi lì per curiosità statistica. Entrambi renderebbero
    falsa la frase «le conversazioni non vengono salvate sul nostro server».
    """
    globali, colpevoli = _globali(), []
    for nodo in ast.walk(_albero()):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for interno in ast.walk(nodo):
            if isinstance(interno, ast.Global):
                colpevoli += ["%s: `global %s`" % (nodo.name, n) for n in interno.names
                              if n != "_hits"]
            if isinstance(interno, ast.Call) and isinstance(interno.func, ast.Attribute):
                base = interno.func.value
                if (isinstance(base, ast.Name) and base.id in globali and base.id != "_hits"
                        and interno.func.attr in ("append", "add", "update", "extend",
                                                  "insert", "setdefault", "write")):
                    colpevoli.append("%s: `%s.%s(...)`" % (nodo.name, base.id,
                                                           interno.func.attr))
            bersagli = []
            if isinstance(interno, ast.Assign):
                bersagli = interno.targets
            elif isinstance(interno, (ast.AugAssign, ast.AnnAssign)):
                bersagli = [interno.target]
            for bersaglio in bersagli:
                if (isinstance(bersaglio, ast.Subscript)
                        and isinstance(bersaglio.value, ast.Name)
                        and bersaglio.value.id in globali and bersaglio.value.id != "_hits"):
                    colpevoli.append("%s: `%s[...] = ...`" % (nodo.name, bersaglio.value.id))
    assert not colpevoli, (
        "in website/main.py qualcosa accumula in una globale diversa da `_hits`: %s — se "
        "conserva testo dell'utente, /privacy va riscritta prima" % "; ".join(colpevoli))


def test_l_errore_del_provider_non_rimanda_indietro_il_messaggio():
    """Il ramo `except` risponde con un testo fisso: non deve rileggere `req`, `message` o il
    payload. Un messaggio d'errore che cita l'input è il modo più comune di far uscire dati che
    si credevano interni (e finirebbe nella scheda del browser, magari condivisa)."""
    for nodo in ast.walk(_funzione("chat")):
        if not isinstance(nodo, ast.Try):
            continue
        for gestore in nodo.handlers:
            citati = {n.id for n in ast.walk(ast.Module(body=gestore.body, type_ignores=[]))
                      if isinstance(n, ast.Name)}
            for vietato in ("req", "message", "messages", "payload", "history"):
                assert vietato not in citati, (
                    "il gestore d'errore di `chat()` usa `%s`: la risposta d'errore deve essere "
                    "un testo fisso, non l'eco dell'input" % vietato)


def test_il_browser_non_conserva_la_conversazione():
    """L'altra metà della stessa frase, quella lato client.

    `/privacy` promette due cose distinte: che la chat non resta sul **server**, e che la
    cronologia «vive solo nella scheda del tuo browser finché non la chiudi». La seconda la
    decide `chat.js`: se un giorno salvasse la conversazione in `localStorage` per ripristinarla
    al ritorno, resterebbe sul disco dell'utente — comodo, ma diverso da quanto dichiarato,
    e su un PC condiviso è esattamente la differenza che conta.

    L'unica chiave ammessa in `localStorage` in tutto il sito è la lingua (`site_lang`).
    """
    chat_js = (_ROOT / "website" / "static" / "chat.js").read_text(encoding="utf-8")
    for magazzino in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert magazzino not in chat_js, (
            "chat.js usa `%s`: la privacy dice che la cronologia vive solo nella scheda aperta"
            % magazzino)
    i18n = (_ROOT / "website" / "static" / "i18n.js").read_text(encoding="utf-8")
    chiavi = set(re.findall(r"localStorage\.(?:get|set|remove)Item\(\s*[\"']([^\"']+)", i18n))
    assert chiavi <= {"site_lang"}, (
        "il sito salva nel browser chiavi non dichiarate in /privacy: %s" % sorted(chiavi))


# ---------------------------------------------------------------------------
# Livello 2: l'endpoint chiamato davvero. Salta dove mancano le dipendenze del sito.
# ---------------------------------------------------------------------------

_MARCATORE = "zzz-marcatore-privacy-284-zzz"
_NOME_MODULO = "betrelay_site_main"


@pytest.fixture(autouse=True)
def _pulisci_sys_modules():
    """Il sito viene caricato sotto un nome sintetico: va tolto da `sys.modules` a fine test,
    o il prossimo caricamento riuserebbe l'istanza vecchia (con il suo `_hits` già popolato)."""
    yield
    sys.modules.pop(_NOME_MODULO, None)


def _carica_sito():
    pytest.importorskip("fastapi", reason="dipendenze del sito assenti: il controllo a runtime "
                                          "gira dove il sito gira davvero")
    pytest.importorskip("starlette.testclient")
    spec = importlib.util.spec_from_file_location(_NOME_MODULO, _MAIN)
    modulo = importlib.util.module_from_spec(spec)
    # in `sys.modules` PRIMA di eseguirlo: `main.py` usa `from __future__ import annotations`,
    # e pydantic risolve le annotazioni di `ChatRequest` cercando il modulo per nome. Senza
    # questa riga il modello resta «not fully defined» e l'endpoint solleva a ogni chiamata.
    # La registrazione la disfa `_pulisci_sys_modules`, anche se l'import qui sotto solleva.
    sys.modules[_NOME_MODULO] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_a_runtime_il_messaggio_non_finisce_nei_log_ne_nello_stato(caplog):
    """Il test che chiude il cerchio: si manda una stringa riconoscibile e la si cerca ovunque.

    In modalità demo (nessuna API key) niente esce verso Anthropic, quindi tutto ciò che
    resta del messaggio è ciò che il sito stesso ne fa: qui, nulla.
    """
    from starlette.testclient import TestClient

    sito = _carica_sito()
    sito.ANTHROPIC_API_KEY = ""  # modalità demo: nessuna chiamata di rete
    caplog.set_level(logging.DEBUG)

    with TestClient(sito.app) as client:
        risposta = client.post("/api/chat", json={"message": _MARCATORE, "lang": "it"})
    assert risposta.status_code == 200, risposta.text
    assert risposta.json()["demo"] is True

    assert _MARCATORE not in caplog.text, \
        "il messaggio dell'utente è finito nei log: /privacy dice che non viene conservato"

    tracce = [nome for nome, valore in vars(sito).items()
              if _MARCATORE in repr(valore)]
    assert not tracce, (
        "dopo la richiesta il messaggio è ancora nello stato del modulo (%s): la chat "
        "conserverebbe le conversazioni" % ", ".join(sorted(tracce)))


def test_a_runtime_il_conteggio_per_ip_tiene_solo_numeri():
    """`_hits` è l'unica cosa che resta fra una richiesta e l'altra. La privacy promette che
    contenga un conteggio, non contenuti: qui si guarda cosa c'è dentro davvero."""
    sito = _carica_sito()
    sito.ANTHROPIC_API_KEY = ""
    from starlette.testclient import TestClient

    with TestClient(sito.app) as client:
        client.post("/api/chat", json={"message": _MARCATORE, "lang": "it"})

    assert sito._hits, "nessun conteggio registrato: il rate limit non starebbe funzionando"
    for ip, istanti in sito._hits.items():
        assert isinstance(ip, str)
        for istante in istanti:
            assert isinstance(istante, float), (
                "in `_hits` c'è qualcosa che non è un timestamp: %r" % (istante,))
