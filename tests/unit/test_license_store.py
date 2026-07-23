"""Test hard della persistenza licenza (#140 PR 2): round-trip atomico + lettura fail-safe."""

import os

from xtrader_bridge import license_store


def test_round_trip(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    license_store.save_license(p, "tok.abc", 1_700_000_000)
    assert license_store.load_license(p) == ("tok.abc", 1_700_000_000)


def test_path_dentro_config_dir(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    assert os.path.dirname(p) == str(tmp_path)
    assert p.endswith("license_state.json")


def test_file_assente_ritorna_none(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    assert license_store.load_license(p) == (None, None)


def test_file_corrotto_fail_safe_e_backup(tmp_path):
    # JSON corrotto → (None, None) MA il file viene messo in backup .bak prima (recuperabile).
    p = license_store.license_state_path(str(tmp_path))
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ questo non è json valido …")
    assert license_store.load_license(p) == (None, None)
    assert os.path.exists(p + ".bak")               # backup creato
    assert not os.path.exists(p)                     # l'originale corrotto è stato spostato
    with open(p + ".bak", encoding="utf-8") as f:
        assert "non è json valido" in f.read()       # contenuto corrotto conservato


def test_json_non_dict_fail_safe_e_backup(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    with open(p, "w", encoding="utf-8") as f:
        f.write('["lista", "non", "dict"]')
    assert license_store.load_license(p) == (None, None)
    assert os.path.exists(p + ".bak")               # schema errato = corruzione → backup


def test_file_valido_non_viene_backuppato(tmp_path):
    # Regressione: un file VALIDO non deve mai essere rinominato in .bak.
    p = license_store.license_state_path(str(tmp_path))
    license_store.save_license(p, "tok", 100)
    assert license_store.load_license(p) == ("tok", 100)
    assert not os.path.exists(p + ".bak")
    assert os.path.exists(p)


def test_campi_mancanti_o_tipi_errati(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"token": 123, "last_seen": "non-numero"}')
    # token non-stringa → None; last_seen non numerico → None (fail-safe, non crash)
    assert license_store.load_license(p) == (None, None)


def test_token_vuoto_trattato_come_assente(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"token": "", "last_seen": 100}')
    token, last_seen = license_store.load_license(p)
    assert token is None
    assert last_seen == 100


def test_clear(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    license_store.save_license(p, "tok", 1)
    assert os.path.exists(p)
    license_store.clear_license(p)
    assert not os.path.exists(p)
    # idempotente: clear su file assente non solleva
    license_store.clear_license(p)


def test_sovrascrittura_atomica_nessun_residuo(tmp_path):
    p = license_store.license_state_path(str(tmp_path))
    license_store.save_license(p, "a", 1)
    license_store.save_license(p, "b", 2)
    assert license_store.load_license(p) == ("b", 2)
    # nessun temporaneo orfano lasciato accanto
    leftovers = [n for n in os.listdir(str(tmp_path)) if n.endswith(".tmp")]
    assert leftovers == []
