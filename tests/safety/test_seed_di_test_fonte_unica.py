"""Il seed di TEST della licenza esiste in più file: qui si impedisce che divergano.

Rilievo bloccante di Fable 5 sulla PR #209 (scambio della chiave pubblica reale). Il seed di test
è ripetuto in vari file di test — precede quella PR, ma da quando `tests/conftest.py` espone
`LICENSE_TEST_SEED_HEX` per la fixture `chiave_pubblica_di_test`, una divergenza avrebbe una
conseguenza nuova e sgradevole: la fixture deploierebbe la pubblica di UN seed mentre i test
firmerebbero con un ALTRO, e i round-trip fallirebbero con `INVALID_SIGNATURE` — un errore che
sembra un difetto del prodotto e invece è un disallineamento fra due costanti.

Perché una guardia e non un import condiviso: `tests/` **non è un package** (nessun `__init__.py`)
e `conftest.py` è un plugin pytest, non un modulo da importare. Far dipendere sei file da un
import fragile sarebbe peggio del problema. Questa guardia ottiene la stessa garanzia — una sola
verità sul valore — rendendo la divergenza **rumorosa e immediata** invece che silenziosa.
"""

import ast
import os

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# I nomi con cui il seed di test compare nel repository.
_NOMI = ("_TEST_SEED", "_TEST_SEED_HEX", "LICENSE_TEST_SEED_HEX", "_SEED_HEX")


def _valore_esadecimale(nodo):
    """L'esadecimale assegnato a un nome, sia `= "…"` sia `= bytes.fromhex("…")`. `None` se il
    nodo non è una di queste due forme (es. una costante derivata)."""
    valore = nodo.value
    if isinstance(valore, ast.Constant) and isinstance(valore.value, str):
        return valore.value.lower()
    # bytes.fromhex("…")
    if (isinstance(valore, ast.Call) and isinstance(valore.func, ast.Attribute)
            and valore.func.attr == "fromhex" and valore.args
            and isinstance(valore.args[0], ast.Constant)
            and isinstance(valore.args[0].value, str)):
        return valore.args[0].value.lower()
    return None


def _seed_dichiarati():
    """Tutte le assegnazioni del seed di test nella suite: `[(file, nome, esadecimale), …]`."""
    trovati = []
    for radice, _dirs, files in os.walk(TESTS_DIR):
        if "__pycache__" in radice:
            continue
        for nome_file in files:
            if not nome_file.endswith(".py"):
                continue
            percorso = os.path.join(radice, nome_file)
            try:
                albero = ast.parse(open(percorso, encoding="utf-8").read())
            except SyntaxError:                     # pragma: no cover — file rotto: lo dicono altri test
                continue
            for nodo in ast.walk(albero):
                if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
                    continue
                bersaglio = nodo.targets[0]
                if not (isinstance(bersaglio, ast.Name) and bersaglio.id in _NOMI):
                    continue
                hexval = _valore_esadecimale(nodo)
                if hexval and len(hexval) == 64:
                    trovati.append((os.path.relpath(percorso, TESTS_DIR), bersaglio.id, hexval))
    return trovati


def test_tutti_i_seed_di_test_sono_lo_stesso_valore():
    """Se due copie divergono, il fallimento dev'essere QUI e leggibile — non venti
    `INVALID_SIGNATURE` sparsi che sembrano un difetto del prodotto."""
    dichiarati = _seed_dichiarati()
    assert dichiarati, "guardia cieca: nessun seed di test trovato (rinominata la costante?)"

    valori = {hexval for _f, _n, hexval in dichiarati}
    assert len(valori) == 1, (
        "il seed di TEST diverge fra i file — la fixture `chiave_pubblica_di_test` deploierebbe "
        "la pubblica di un seed mentre i test firmano con un altro:\n"
        + "\n".join(f"  {f}:{n} = {h[:16]}…" for f, n, h in sorted(dichiarati)))


def test_la_costante_del_conftest_e_fra_quelle_allineate():
    """Controprova: la guardia sopra sarebbe soddisfatta anche se il conftest non comparisse
    affatto. Qui si pretende che ci sia — è il valore da cui la fixture deriva la pubblica."""
    dichiarati = _seed_dichiarati()
    da_conftest = [h for f, n, h in dichiarati
                   if n == "LICENSE_TEST_SEED_HEX" and f.endswith("conftest.py")]
    assert da_conftest, "LICENSE_TEST_SEED_HEX non trovata in tests/conftest.py"
    altri = {h for _f, n, h in dichiarati if n != "LICENSE_TEST_SEED_HEX"}
    assert altri, "nessun seed hardcoded nei file di test: la guardia non sta confrontando nulla"
    assert set(da_conftest) == altri
