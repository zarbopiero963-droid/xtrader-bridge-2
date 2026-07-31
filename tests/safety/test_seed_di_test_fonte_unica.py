"""Il seed di TEST della licenza deve esistere in UN SOLO posto: `tests/conftest.py`.

Rilievo bloccante di Fable 5 e Major di CodeRabbit sulla PR #209 (scambio della chiave pubblica
reale). Il seed di test era ripetuto in **sette** file — precede quella PR, ma da quando
`tests/conftest.py` espone `LICENSE_TEST_SEED_HEX` per la fixture `chiave_pubblica_di_test` una
divergenza avrebbe una conseguenza nuova e sgradevole: la fixture deploierebbe la pubblica di UN
seed mentre i test firmerebbero con un ALTRO, e i round-trip fallirebbero con `INVALID_SIGNATURE`
— un errore che sembra un difetto del prodotto e invece è un disallineamento fra due costanti.

La prima versione di questa guardia si limitava a pretendere che le copie **combaciassero**.
CodeRabbit ha osservato, correttamente, che così le fonti duplicate restano — e che una guardia
basata su un elenco di NOMI (`_TEST_SEED`, `_TEST_SEED_HEX`, …) non vede una copia battezzata
diversamente. Entrambe le obiezioni sono chiuse qui: le copie non esistono più (regola 3, fonte
unica) e la guardia confronta il **valore**, non il nome, quindi vede qualunque re-introduzione.

Perché un import e non un package: `tests/` non ha `__init__.py`, ma il repo root finisce in
`sys.path` per mano dello stesso `tests/conftest.py`, che pytest carica prima di qualsiasi modulo
di test. `from tests.conftest import …` è già il modo in cui `tests/safety/test_path_link_194.py`
e `tests/integration/test_path_link_app_194.py` condividono le loro sonde, e tutti e sei i
workflow invocano `python -m pytest`.

Con un limite reale, segnalato da GPT-5.5 e verificato: essendo `tests/` un **namespace** package,
un package **regolare** omonimo installato in `site-packages` lo scavalcherebbe e quegli import
leggerebbero un altro progetto. Non è ipotetico — riprodotto, rompe la collection, e colpiva già i
due file citati sopra. La difesa sta in `tests/conftest.py`
(`_verifica_nessuno_shadowing_di_tests`), esercitata più sotto: l'import resta quello che il
repository già usa, ma ora fallisce dicendo **perché**.
"""

import ast
import os

import pytest

from tests.conftest import LICENSE_TEST_SEED_HEX, crea_symlink, richiede_link

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# I file che hanno bisogno del seed per firmare: devono prenderlo dalla fonte unica.
_FILE_CHE_FIRMANO = {
    "conftest.py",
    "unit/test_licensing_license.py",
    "unit/test_license_status.py",
    "unit/test_license_gui.py",
    "unit/test_license_manager_core.py",
    "integration/test_license_lock_r3c.py",
    "safety/test_revocation_release_gate_159.py",
}


def _file_di_test():
    """Percorsi relativi a `tests/` di ogni `.py` della suite, con l'albero già parsato."""
    for radice, _dirs, files in os.walk(TESTS_DIR):
        if "__pycache__" in radice:
            continue
        for nome_file in sorted(files):
            if not nome_file.endswith(".py"):
                continue
            percorso = os.path.join(radice, nome_file)
            with open(percorso, encoding="utf-8") as fh:
                sorgente = fh.read()
            try:
                albero = ast.parse(sorgente)
            except SyntaxError:                 # pragma: no cover — file rotto: lo dicono altri test
                continue
            yield os.path.relpath(percorso, TESTS_DIR).replace("\\", "/"), albero


def _file_col_literal_del_seed():
    """`{file: [righe]}` per ogni file in cui il seed compare come **literal**, sotto qualunque nome.

    Il confronto è sul VALORE, non sul nome della costante: una copia battezzata `_MIO_SEED`, o
    passata inline a `bytes.fromhex("a1b2…")`, viene vista lo stesso. È il punto che la versione
    precedente della guardia — un elenco di nomi noti — lasciava scoperto.
    """
    trovati = {}
    for relativo, albero in _file_di_test():
        righe = sorted(nodo.lineno for nodo in ast.walk(albero)
                       if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
                       and nodo.value.lower() == LICENSE_TEST_SEED_HEX)
        if righe:
            trovati[relativo] = righe
    return trovati


def _file_che_importano_la_fonte_unica():
    """I file che fanno `from tests.conftest import LICENSE_TEST_SEED_HEX` (anche con alias)."""
    trovati = set()
    for relativo, albero in _file_di_test():
        for nodo in ast.walk(albero):
            if (isinstance(nodo, ast.ImportFrom) and nodo.module == "tests.conftest"
                    and any(alias.name == "LICENSE_TEST_SEED_HEX" for alias in nodo.names)):
                trovati.add(relativo)
    return trovati


def test_il_seed_di_test_e_dichiarato_in_un_solo_file():
    """Regola 3: se il valore va scritto in due posti, il posto giusto è zero.

    Una copia in più non è un difetto estetico: è la premessa del disallineamento silenzioso fra
    la pubblica che la fixture deploya e il seed con cui i test firmano.
    """
    trovati = _file_col_literal_del_seed()
    assert set(trovati) == {"conftest.py"}, (
        "il seed di TEST compare come literal fuori da tests/conftest.py — importalo invece di "
        "ricopiarlo (`from tests.conftest import LICENSE_TEST_SEED_HEX`):\n"
        + "\n".join(f"  {f}: righe {r}" for f, r in sorted(trovati.items())))


def test_chi_firma_prende_il_seed_dalla_fonte_unica():
    """Controprova: la guardia sopra è soddisfatta anche da un file che ha semplicemente
    cancellato la sua copia e ha smesso di firmare del tutto. Qui si pretende il contrario —
    che chi ha bisogno del seed lo prenda dalla fonte unica, non che se ne sia liberato."""
    importano = _file_che_importano_la_fonte_unica()
    mancanti = _FILE_CHE_FIRMANO - importano - {"conftest.py"}   # conftest È la fonte: non si importa
    assert not mancanti, (
        "questi file firmano licenze ma non importano più il seed condiviso — o hanno ripreso "
        f"una copia locale, o hanno smesso di esercitare la firma: {sorted(mancanti)}")


def test_la_fonte_unica_e_un_seed_ed25519_plausibile():
    """Controprova finale: tutto il resto confronta il valore con sé stesso, quindi resterebbe
    verde anche se la costante diventasse una stringa vuota. Un seed Ed25519 è 32 byte esadecimali."""
    assert len(LICENSE_TEST_SEED_HEX) == 64
    bytes.fromhex(LICENSE_TEST_SEED_HEX)                      # solleva se non è esadecimale
    assert LICENSE_TEST_SEED_HEX == LICENSE_TEST_SEED_HEX.lower()


# ── Robustezza dell'import condiviso (rilievi GPT-5.5 su #209) ─────────────────────────────────

def test_la_guardia_anti_shadowing_riconosce_un_tests_estraneo(monkeypatch):
    """Primo rilievo GPT-5.5: `tests/` è un namespace package e perde contro un package REGOLARE
    omonimo installato in `site-packages`. Verificato in adversariale — con un
    `site-packages/tests/__init__.py` finto la collection muore con `ModuleNotFoundError`, e
    colpisce anche i due file che già usavano questo import prima della #209.

    Qui si esercita la guardia che rende quella diagnosi esplicita: le si passa un percorso atteso
    diverso da quello a cui `tests` risolve davvero — la stessa condizione dello shadowing — e si
    pretende che sollevi, nominando la causa. Senza il `percorso_atteso` iniettabile servirebbe
    installare davvero un package ostile per coprire questo ramo.
    """
    import importlib.util

    import tests.conftest as ct

    ct._verifica_nessuno_shadowing_di_tests()                 # ambiente sano: non solleva

    # I percorsi finti si costruiscono con `os.path.join(os.sep, …)` e si confrontano dopo
    # `os.path.abspath`, mai come stringhe letterali: la guardia normalizza, e su Windows
    # "/altro/progetto" diventa "C:\\altro\\progetto" (rilievo GPT-5.5 — il test com'era scritto
    # sarebbe stato rosso solo sul runner Windows). Niente `match=`, che è una regex e sui
    # backslash di Windows si comporterebbe da sequenza di escape.
    altrove = os.path.join(os.sep, "percorso", "che", "non", "e", "questo.py")
    with pytest.raises(RuntimeError) as errore:
        ct._verifica_nessuno_shadowing_di_tests(percorso_atteso=altrove)
    messaggio = str(errore.value)
    assert "NON risolve al conftest di questo repository" in messaggio
    assert "`tests/__init__.py`" in messaggio                 # deve dire COSA cercare
    assert os.path.abspath(altrove) in messaggio              # dice QUALE percorso si attendeva

    # La guardia interroga `tests.conftest`, non il solo package `tests`: un namespace può avere
    # più porzioni e sapere che la nostra è *fra* quelle non dice che sia la PRIMA, cioè quella che
    # vince. Controprova: una porzione estranea davanti alla nostra deve essere vista.
    estraneo = os.path.join(os.sep, "altro", "progetto", "tests", "conftest.py")

    def _spec_finta(nome):
        # Risponde anche per il package `tests`, che la guardia interroga per la diagnostica:
        # facendola fallire si otterrebbe «non determinabile» e il messaggio verrebbe esercitato
        # a metà.
        if nome == "tests.conftest":
            return importlib.util.spec_from_file_location(nome, estraneo)
        return None

    monkeypatch.setattr(ct.importlib.util, "find_spec", _spec_finta)
    with pytest.raises(RuntimeError) as errore:
        ct._verifica_nessuno_shadowing_di_tests()
    assert os.path.abspath(estraneo) in str(errore.value)


@richiede_link
def test_la_guardia_non_da_falsi_allarmi_su_percorsi_equivalenti(tmp_path):
    """L'altra metà del rilievo Windows, ed è la metà pericolosa: la guardia gira all'**import**
    del conftest, quindi un falso allarme non fa fallire un test — **spegne l'intera suite**.

    Su Windows due percorsi validi per lo stesso file possono differire per maiuscole (`C:\\` vs
    `c:\\`), per nome corto 8.3 o per un link, e un confronto con `abspath` li direbbe diversi.
    Per questo la guardia confronta con `normcase(realpath(...))`.

    Il caso si esercita con un **symlink**, non con un `..`: la prima versione di questo test
    usava `tests/unit/../conftest.py` e passava anche neutralizzando la normalizzazione — perché
    `abspath` collassa i `..` da sé, quindi non distingueva `realpath` da `abspath`. Era un test
    decorativo. Un link invece `abspath` non lo risolve e `realpath` sì: è la differenza vera.

    Resta scoperto qui il solo ramo maiuscole/minuscole, che su Linux `normcase` non esercita
    (è l'identità): quello lo copre il runner Windows.
    """
    import tests.conftest as ct

    reale = os.path.join(TESTS_DIR, "conftest.py")
    link = str(tmp_path / "conftest_via_link.py")
    crea_symlink(reale, link)

    assert os.path.abspath(link) != os.path.abspath(reale), (
        "il link non è un percorso distinto: il test non starebbe verificando nulla")
    ct._verifica_nessuno_shadowing_di_tests(percorso_atteso=link)          # non deve sollevare


def test_il_doppio_caricamento_del_conftest_non_diverge(chiave_pubblica_di_test):
    """Secondo rilievo GPT-5.5: pytest carica `tests/conftest.py` per conto suo, mentre
    `from tests.conftest import …` ne crea una **seconda** copia sotto il nome `tests.conftest`.
    Misurato: sono due oggetti distinti (`is` → False), quindi il corpo del modulo viene eseguito
    due volte.

    Oggi è innocuo — l'unico effetto collaterale all'import è `sys.path.insert`, protetto da
    `if _REPO_ROOT not in sys.path`, quindi idempotente; fixture e hook della seconda copia non
    sono registrati come plugin e non girano. Ma «oggi è innocuo» non è una garanzia: il giorno in
    cui il conftest acquisisse uno stato all'import (un registry, una cartella temporanea, un
    contatore) la doppia esecuzione sarebbe silenziosa.

    Il confronto NON passa da `sys.modules["conftest"]`, che sembra la strada ovvia e non lo è:
    `tests/integration/conftest.py` ha lo stesso basename e nel run completo **sovrascrive**
    quella chiave (misurato — nel run completo l'unica voce che punta a `tests/conftest.py` è
    `tests.conftest`, cioè l'import di questo file; nel run della sola `tests/unit` è `conftest`).
    Un test costruito su quel nome passa da solo e fallisce in suite, indicando per giunta la
    causa sbagliata.

    Si esercita invece la **conseguenza** che conta: la fixture arriva dalla copia caricata da
    pytest e deriva la pubblica dalla costante di QUELLA copia; qui la si confronta con la
    pubblica derivata dalla costante della copia **importata**. Se le due divergessero, questo
    test lo direbbe — che è esattamente il rilievo.
    """
    import tests.conftest as importato
    from xtrader_bridge.licensing import ed25519

    assert os.path.abspath(importato.__file__) == os.path.join(TESTS_DIR, "conftest.py"), (
        "`tests.conftest` non è il conftest di questo repository: è lo shadowing del package "
        "`tests` descritto nella guardia di `tests/conftest.py`")

    pub_dalla_copia_importata = ed25519.public_key(
        bytes.fromhex(importato.LICENSE_TEST_SEED_HEX)).hex()
    assert chiave_pubblica_di_test == pub_dalla_copia_importata, (
        "la copia del conftest caricata da pytest e quella importata derivano pubbliche DIVERSE: "
        "i test firmerebbero con un seed e verificherebbero con l'altro")
    assert importato.LICENSE_TEST_SEED_HEX == LICENSE_TEST_SEED_HEX
