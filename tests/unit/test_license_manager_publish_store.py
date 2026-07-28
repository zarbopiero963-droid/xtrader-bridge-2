"""Test hard delle **impostazioni di pubblicazione** del License Manager (#157).

Esercitano la logica reale di `license_manager.publish_store`: normalizzazione/validazione,
persistenza atomica fail-safe e keyring (con backend FINTO, nessun keyring reale nei test).
Invariante centrale verificata: **il token non finisce MAI su disco**."""

import json
import types

import pytest

from license_manager import publish_store


# ── normalizzazione ──────────────────────────────────────────────────────────────────────────────
def test_normalize_config_default_su_input_vuoto_o_sporco():
    for bad in ({}, None, "non-dict", 123, []):
        norm = publish_store.normalize_config(bad)
        assert norm == publish_store.normalize_config({})
        assert norm["enabled"] is False              # default fail-closed: spenta
        assert norm["path"] == "revocation_list.txt"
        assert norm["branch"] == "main"


def test_normalize_config_pulisce_spazi_e_tipi():
    norm = publish_store.normalize_config({
        "enabled": True, "repo": "  tizio/xtrader-revocation  ",
        "path": "  lista.txt ", "branch": " main ", "interval_hours": "6",
    })
    assert norm == {"enabled": True, "repo": "tizio/xtrader-revocation",
                    "path": "lista.txt", "branch": "main", "interval_hours": 6}


def test_normalize_config_enabled_solo_bool_true():
    """`enabled` si attiva SOLO con un vero `True`: una stringa non deve accendere la pubblicazione."""
    for truthy in ("on", "true", 1, "yes"):
        assert publish_store.normalize_config({"enabled": truthy})["enabled"] is False
    assert publish_store.normalize_config({"enabled": True})["enabled"] is True


def test_normalize_config_intervallo_limitato():
    assert publish_store.normalize_config({"interval_hours": 0})["interval_hours"] == \
        publish_store.MIN_INTERVAL_HOURS
    assert publish_store.normalize_config({"interval_hours": 99_999})["interval_hours"] == \
        publish_store.MAX_INTERVAL_HOURS
    # non numerico / bool → default (True non è "1 ora")
    assert publish_store.normalize_config({"interval_hours": "x"})["interval_hours"] == \
        publish_store.DEFAULTS["interval_hours"]
    assert publish_store.normalize_config({"interval_hours": True})["interval_hours"] == \
        publish_store.DEFAULTS["interval_hours"]


def test_normalize_config_scarta_campi_segreti():
    """Un eventuale `token` nel dict NON deve sopravvivere alla normalizzazione (mai su disco)."""
    norm = publish_store.normalize_config({"repo": "a/b", "token": "ghp_SEGRETO"})
    assert "token" not in norm
    assert "ghp_SEGRETO" not in json.dumps(norm)


# ── validazione ──────────────────────────────────────────────────────────────────────────────────
def test_validate_config_repo():
    assert publish_store.validate_config({"repo": "tizio/xtrader-revocation"}) is None
    for bad in ("", "solo-nome", "a/b/c", "tizio /x", "/x", "x/"):
        assert publish_store.validate_config({"repo": bad}) is not None


# ── persistenza (atomica, fail-safe) ────────────────────────────────────────────────────────────
def test_save_e_load_round_trip(tmp_path):
    cfg = {"enabled": True, "repo": "tizio/x", "path": "l.txt", "branch": "main", "interval_hours": 8}
    publish_store.save_publish_config(cfg, directory=str(tmp_path))
    assert publish_store.load_publish_config(directory=str(tmp_path)) == cfg


def test_save_non_scrive_mai_il_token(tmp_path):
    """Anche passando un `token` nel dict, il file su disco NON deve contenerlo (invariante #157)."""
    publish_store.save_publish_config(
        {"repo": "tizio/x", "token": "ghp_SUPERSEGRETO", "enabled": True}, directory=str(tmp_path))
    testo = open(publish_store.publish_config_path(str(tmp_path)), encoding="utf-8").read()
    assert "ghp_SUPERSEGRETO" not in testo and "token" not in testo


def test_load_file_assente_o_corrotto_default(tmp_path):
    assert publish_store.load_publish_config(directory=str(tmp_path)) == \
        publish_store.normalize_config({})                      # assente
    path = publish_store.publish_config_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("{non-json")                                    # corrotto
    assert publish_store.load_publish_config(directory=str(tmp_path))["enabled"] is False


# ── keyring (backend FINTO: nessun keyring reale nei test) ──────────────────────────────────────
class _FakeKeyring:
    def __init__(self, *, broken=False):
        self.store, self.broken = {}, broken

    def get_password(self, service, account):
        if self.broken:
            raise RuntimeError("backend non disponibile")
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        if self.broken:
            raise RuntimeError("backend non disponibile")
        self.store[(service, account)] = value

    def delete_password(self, service, account):
        if self.broken:
            raise RuntimeError("backend non disponibile")
        self.store.pop((service, account), None)


@pytest.fixture()
def fake_kr(monkeypatch):
    kr = _FakeKeyring()
    monkeypatch.setattr(publish_store, "_keyring", lambda: kr)
    return kr


def test_token_round_trip_nel_keyring(fake_kr):
    assert publish_store.keyring_available() is True
    assert publish_store.save_publish_token("ghp_ABC") is True
    assert publish_store.load_publish_token() == "ghp_ABC"
    # salvato nello spazio dei nomi DEDICATO al License Manager (non quello del bridge)
    assert fake_kr.store[(publish_store.SERVICE, publish_store.ACCOUNT_TOKEN)] == "ghp_ABC"
    assert publish_store.SERVICE != "XTraderBridge"
    assert publish_store.delete_publish_token() is True
    assert publish_store.load_publish_token() is None


def test_token_vuoto_non_si_salva(fake_kr):
    for vuoto in ("", "   ", None):
        assert publish_store.save_publish_token(vuoto) is False
    assert publish_store.load_publish_token() is None


def test_keyring_assente_o_rotto_fail_safe(monkeypatch):
    """Senza backend (o con backend che solleva): niente crash, tutto ritorna «non disponibile»."""
    monkeypatch.setattr(publish_store, "_keyring", lambda: None)
    assert publish_store.keyring_available() is False
    assert publish_store.save_publish_token("x") is False
    assert publish_store.load_publish_token() is None
    assert publish_store.delete_publish_token() is False
    monkeypatch.setattr(publish_store, "_keyring", lambda: _FakeKeyring(broken=True))
    assert publish_store.keyring_available() is False
    assert publish_store.save_publish_token("x") is False
    assert publish_store.load_publish_token() is None


def test_keyring_import_fallito_non_rompe(monkeypatch):
    """`_keyring()` inghiotte un import rotto (dipendenza opzionale) → `None`, mai eccezione."""
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "keyring":
            raise ImportError("keyring non installato")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _boom)
    assert publish_store._keyring() is None
    assert isinstance(types.SimpleNamespace(), object)      # sanity: il test non ha rotto l'import


# ── vincolo cadenza ↔ finestra di freschezza del bridge (rilievo CodeRabbit/Fable/Fugu #158) ─────
def test_intervallo_massimo_derivato_dalla_finestra_del_bridge():
    """Il cap NON è un numero ricopiato: è **derivato** da `MAX_LIST_AGE_S` del bridge, e resta con
    margine sotto la finestra — così anche **saltando un giro** la lista è ancora fresca."""
    from xtrader_bridge.licensing import revocation_client
    finestra_h = revocation_client.MAX_LIST_AGE_S // 3600
    assert publish_store.MAX_INTERVAL_HOURS < finestra_h, "una cadenza ≥ finestra garantisce il lockout"
    assert 2 * publish_store.MAX_INTERVAL_HOURS < finestra_h, "un tick saltato non deve far scadere"
    assert publish_store.DEFAULTS["interval_hours"] <= publish_store.MAX_INTERVAL_HOURS


def test_intervallo_oltre_la_finestra_viene_limitato():
    """Chiedere 48 h (oltre la finestra di 24 h) non può passare: viene limitato al cap sicuro,
    invece di salvare una configurazione che bloccherebbe tutti i bridge."""
    assert publish_store.normalize_config({"interval_hours": 48})["interval_hours"] == \
        publish_store.MAX_INTERVAL_HOURS
    assert publish_store.normalize_config({"interval_hours": 168})["interval_hours"] == \
        publish_store.MAX_INTERVAL_HOURS


def test_validate_config_rifiuta_spazi_in_path_e_branch():
    """Spazi in `path`/`branch` finiscono in DUE URL diversi (API e raw): meglio rifiutarli subito
    che produrre un URL non scaricabile dal bridge → lockout (rilievo Fugu #158)."""
    base = {"repo": "tizio/x"}
    assert publish_store.validate_config({**base, "path": "lista revoche.txt"}) is not None
    assert publish_store.validate_config({**base, "branch": "main dev"}) is not None
    assert publish_store.validate_config({**base, "path": "sub/lista.txt", "branch": "main"}) is None


def test_validate_config_rifiuta_anche_tab_newline_e_spazi_unicode():
    """Il controllo usa `isspace()`, quindi non copre solo lo spazio semplice (rilievo GPT-5.5 #158):
    tab, a-capo e spazi Unicode (NBSP) romperebbero i due URL allo stesso modo. `strip()` toglie solo
    quelli **ai bordi**: questi stanno in mezzo e devono essere rifiutati esplicitamente."""
    base = {"repo": "tizio/x"}
    for cattivo in ("lista\trevoche.txt", "lista\nrevoche.txt", "lista\u00a0revoche.txt"):
        assert publish_store.validate_config({**base, "path": cattivo}) is not None, cattivo
    for cattivo in ("main\tdev", "main\ndev", "main\u00a0dev"):
        assert publish_store.validate_config({**base, "branch": cattivo}) is not None, cattivo
    # un branch con `/` (es. `feature/x`) NON è whitespace: resta valido
    assert publish_store.validate_config({**base, "branch": "feature/x"}) is None
