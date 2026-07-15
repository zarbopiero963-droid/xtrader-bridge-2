"""Test hard veritieri — Issue #76 P2-5 (audit 2026-07-15).

`save_config` proteggeva la scrittura atomica solo con `except OSError`: un errore di
SERIALIZZAZIONE dentro `atomic_write_json` → `json.dumps` (`TypeError` per un valore
non-JSON finito in config in RAM, `ValueError` per un riferimento circolare) propagava
SENZA eseguire il rollback del keyring e senza `SaveResult` — keyring aggiornato col
token nuovo, `config.json` su disco stantio, eccezione non gestita al chiamante GUI.

Fix testato: stesso ramo del disco fallito → rollback keyring + `SaveResult(ok=False,
SAVE_DISK_ERROR)`. I casi usano VALORI REALI non serializzabili (un `set` e un dict
circolare), non un fake che solleva: esercitano davvero `json.dumps`.
"""

import json

from xtrader_bridge import config_store


def _fake_keyring(monkeypatch, store, available=True):
    """Keyring in memoria (stesso helper di test_config_basic, replicato: i file di test
    non sono un package importabile)."""
    monkeypatch.setattr(config_store.token_store, "available", lambda: available)
    monkeypatch.setattr(config_store.token_store, "save_token",
                        lambda t: bool(t) and (store.__setitem__("t", t) or True))
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: store.get("t"))
    monkeypatch.setattr(config_store.token_store, "load_token_status",
                        lambda: (store.get("t"), True) if available else (None, False))

    def _del():
        existed = "t" in store
        store.pop("t", None)
        return existed
    monkeypatch.setattr(config_store.token_store, "delete_token", _del)


def test_valore_non_serializzabile_rollback_keyring_e_esito_falso(tmp_path, monkeypatch):
    # Un `set` (non-JSON) finito in config in RAM → TypeError REALE da json.dumps.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    res = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "provider": {"un", "set"}}, str(p))
    saved, ok = res
    assert ok is False
    assert res.status == config_store.SAVE_DISK_ERROR      # esito strutturato, non eccezione
    assert store["t"] == "OLD:TOKEN"                        # keyring ROLLED BACK
    assert not p.exists()                                   # nessun file parziale su disco


def test_riferimento_circolare_rollback_keyring_e_esito_falso(tmp_path, monkeypatch):
    # Un dict circolare → ValueError REALE («Circular reference detected») da json.dumps.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    circolare = {"bot_token": "NEW:TOKEN"}
    circolare["se_stesso"] = circolare
    p = tmp_path / "config.json"
    saved, ok = config_store.save_config(circolare, str(p))
    assert ok is False
    assert store["t"] == "OLD:TOKEN"                        # keyring ROLLED BACK


def test_config_esistente_su_disco_resta_intatta_su_serializzazione_fallita(tmp_path, monkeypatch):
    # La config PRECEDENTE su disco non viene toccata: atomic_write_json fallisce sul
    # temporaneo, mai sul file vero (invariante «save fallito non corrompe l'esistente»).
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    before = json.dumps({"bot_token": "", "bot_token_storage": "keyring", "provider": "OLD"})
    p.write_text(before, encoding="utf-8")
    saved, ok = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "provider": {"non", "json"}}, str(p))
    assert ok is False
    assert p.read_text(encoding="utf-8") == before          # file su disco intatto
    assert store["t"] == "OLD:TOKEN"


def test_clear_esplicito_con_serializzazione_fallita_ripristina_il_token(tmp_path, monkeypatch):
    # Ramo CLEAR: `bot_token` presente e vuoto cancella dal keyring PRIMA della scrittura;
    # se la serializzazione fallisce, il token cancellato va RIPRISTINATO (rollback del clear).
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    saved, ok = config_store.save_config(
        {"bot_token": "", "provider": {"non", "json"}}, str(p))
    assert ok is False
    assert store.get("t") == "OLD:TOKEN"                    # clear annullato: token ripristinato


def test_oserror_resta_gestito_come_prima(tmp_path, monkeypatch):
    # Regressione: il ramo storico I/O (OSError) resta identico (rollback + ok=False).
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)

    def _boom(*a, **k):
        raise OSError("disco pieno (simulato)")
    monkeypatch.setattr(config_store.atomic_io, "atomic_write_json", _boom)
    saved, ok = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "provider": "X"}, str(tmp_path / "config.json"))
    assert ok is False
    assert store["t"] == "OLD:TOKEN"
