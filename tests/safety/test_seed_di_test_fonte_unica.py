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
workflow invocano `python -m pytest`. Non è un import fragile: è quello che il repository già usa.
"""

import ast
import os

from tests.conftest import LICENSE_TEST_SEED_HEX

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
