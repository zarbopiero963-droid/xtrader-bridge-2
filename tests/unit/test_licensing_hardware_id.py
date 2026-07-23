"""Test hard dell'impronta Hardware ID (#140 PR 1).

`fingerprint` è puro → si testa con componenti iniettati (deterministico, formato stabile);
`hardware_id()` sulla macchina reale deve essere stabile tra due chiamate e ben formato.
"""

import re

# Il modulo si chiama `hwid` (la funzione pubblica è `licensing.hardware_id()`): il nome del
# modulo è distinto dalla funzione per non ombreggiarsi a vicenda nel package.
import xtrader_bridge.licensing.hwid as hw

_PATTERN = re.compile(r"^HW1-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$")


def test_fingerprint_formato_atteso():
    fid = hw.fingerprint(["mguid=abc", "vol=12345678", "mac=aabbccddeeff"])
    assert _PATTERN.match(fid), fid


def test_fingerprint_deterministico():
    parts = ["mguid=abc", "vol=12345678"]
    assert hw.fingerprint(parts) == hw.fingerprint(list(parts))


def test_fingerprint_cambia_con_i_componenti():
    a = hw.fingerprint(["mguid=AAA"])
    b = hw.fingerprint(["mguid=BBB"])
    assert a != b


def test_fingerprint_ordine_conta():
    # L'ordine dei componenti fa parte dell'impronta (le sorgenti sono raccolte in ordine fisso).
    assert hw.fingerprint(["a", "b"]) != hw.fingerprint(["b", "a"])


def test_fingerprint_lista_vuota_resta_valida():
    fid = hw.fingerprint([])
    assert _PATTERN.match(fid), fid
    # deterministica anche nel caso "nessuna sorgente"
    assert fid == hw.fingerprint([])


def test_hardware_id_stabile_e_ben_formato():
    a = hw.hardware_id()
    b = hw.hardware_id()
    assert a == b                      # stessa macchina → stessa impronta
    assert _PATTERN.match(a), a


def test_components_non_solleva():
    # La raccolta delle sorgenti reali è best-effort: non deve mai sollevare (ritorna una lista).
    parts = hw.components()
    assert isinstance(parts, list)
