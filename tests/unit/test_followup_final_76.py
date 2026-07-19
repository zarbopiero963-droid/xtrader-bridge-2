"""Follow-up finali post-audit #76 (#6 + #8) — ordine del proprietario.

#6 (nota Fable PR #83): lock CROSS-PROCESS su `config_store.save_config` — due
istanze dell'app che salvano insieme non devono intrecciare le sequenze
keyring↔disco. Lock esclusivo OS su `<config>.lock` (msvcrt/fcntl), FAIL-OPEN
dopo timeout (mai GUI bloccata da un lock orfano: la scrittura resta atomica).

#8 (nota Fugu PR #96): l'avviso «profilo ancora selezionato in N parser» viene
calcolato PRIMA della conferma di eliminazione e integrato NEL testo del dialogo
(⚽ nomi e 🎯 mercati) — l'utente decide sapendolo, non lo scopre a cose fatte.
"""

import importlib
import os
import subprocess
import sys
import time
import types

import pytest

from xtrader_bridge import config_store


# ── #6: lock cross-process su save_config ───────────────────────────────────────


def test_lock_esclusivo_tra_processi_reali(tmp_path):
    """FAIL-FIRST: pre-patch `_acquire_config_lock` non esisteva. Prova CROSS-PROCESS
    vera: un figlio tiene il lock → il padre non lo acquisisce (fail-open None);
    figlio uscito → il padre lo acquisisce."""
    cfg_path = str(tmp_path / "config.json")
    ready = cfg_path + ".ready"
    child = subprocess.Popen([sys.executable, "-c", (
        "import sys, time\n"
        "from xtrader_bridge import config_store\n"
        "h = config_store._acquire_config_lock(sys.argv[1], timeout_s=5)\n"
        "assert h is not None\n"
        "open(sys.argv[1] + '.ready', 'w').write('ok')\n"
        "time.sleep(1.5)\n"
        "config_store._release_config_lock(h)\n"
    ), cfg_path], cwd=os.getcwd())
    try:
        scadenza = time.monotonic() + 10
        while not os.path.exists(ready):
            assert time.monotonic() < scadenza, "il figlio non ha mai preso il lock"
            time.sleep(0.05)
        # Lock tenuto dall'ALTRO processo → qui niente lock (fail-open, mai blocco).
        assert config_store._acquire_config_lock(cfg_path, timeout_s=0.3) is None
    finally:
        child.wait(timeout=15)
    # Figlio terminato → il lock è libero e si acquisisce davvero.
    h = config_store._acquire_config_lock(cfg_path, timeout_s=5)
    assert h is not None
    config_store._release_config_lock(h)


def test_lock_esclusivo_su_secondo_handle(tmp_path):
    """Anche nello stesso processo (secondo file handle) il lock è esclusivo:
    il secondo tentativo va in fail-open, dopo il rilascio si riacquisisce."""
    cfg_path = str(tmp_path / "config.json")
    h1 = config_store._acquire_config_lock(cfg_path, timeout_s=1)
    assert h1 is not None
    assert config_store._acquire_config_lock(cfg_path, timeout_s=0.2) is None
    config_store._release_config_lock(h1)
    h2 = config_store._acquire_config_lock(cfg_path, timeout_s=1)
    assert h2 is not None
    config_store._release_config_lock(h2)


def test_save_config_gira_sotto_lock_e_lo_rilascia(tmp_path, monkeypatch):
    """`save_config` deve TENERE il lock mentre gira il corpo (`_save_config_locked`)
    e rilasciarlo alla fine — verificato provando ad acquisirlo DENTRO il corpo."""
    cfg_path = str(tmp_path / "config.json")
    dentro = {}

    def _corpo_spia(cfg, path=config_store.CONFIG_FILE):
        dentro["lock_occupato"] = (
            config_store._acquire_config_lock(cfg_path, timeout_s=0.2) is None)
        return config_store.SaveResult({}, True, config_store.SAVE_OK)

    monkeypatch.setattr(config_store, "_save_config_locked", _corpo_spia)
    saved, ok = config_store.save_config({}, cfg_path)

    assert ok is True
    assert dentro["lock_occupato"] is True, "il corpo deve girare col lock TENUTO"
    h = config_store._acquire_config_lock(cfg_path, timeout_s=1)
    assert h is not None, "dopo save_config il lock deve essere RILASCIATO"
    config_store._release_config_lock(h)


def test_lock_rilasciato_anche_su_eccezione(tmp_path, monkeypatch):
    """Il rilascio sta in un finally: un corpo che solleva non lascia il lock appeso."""
    cfg_path = str(tmp_path / "config.json")

    def _corpo_rotto(cfg, path=config_store.CONFIG_FILE):
        raise RuntimeError("crash a metà save")

    monkeypatch.setattr(config_store, "_save_config_locked", _corpo_rotto)
    with pytest.raises(RuntimeError):
        config_store.save_config({}, cfg_path)

    h = config_store._acquire_config_lock(cfg_path, timeout_s=1)
    assert h is not None, "lock rilasciato anche dopo l'eccezione (finally)"
    config_store._release_config_lock(h)


def test_fail_open_salva_comunque_con_lock_occupato(tmp_path, monkeypatch):
    """Lock tenuto da 'un'altra istanza' + timeout scaduto → FAIL-OPEN: il save
    procede comunque (scrittura atomica) invece di bloccare la GUI per sempre."""
    cfg_path = str(tmp_path / "config.json")
    monkeypatch.setattr(config_store, "_CONFIG_LOCK_TIMEOUT_S", 0.2)
    h_altrui = config_store._acquire_config_lock(cfg_path, timeout_s=1)
    assert h_altrui is not None
    try:
        saved, ok = config_store.save_config({"dry_run": True}, cfg_path)
        assert ok is True                        # salvato comunque (fail-open)
        assert os.path.exists(cfg_path)
    finally:
        config_store._release_config_lock(h_altrui)


# ── #8: avviso «ancora usato da N parser» NEL dialogo di conferma ───────────────


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


class _Status:
    text = ""
    color = ""

    def configure(self, **k):
        self.text = k.get("text", self.text)
        self.color = k.get("text_color", self.color)


def _mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    return importlib.import_module("xtrader_bridge.name_mapping_gui")


_CASI = [("NameMappingPanel", "parsers_using_mapping_profile", "MAPPING_MISSING"),
         ("MarketMappingPanel", "parsers_using_market_mapping_profile",
          "MARKET_MAPPING_MISSING")]


def _panel_delete(mod, cls_name, monkeypatch, api, affected):
    panel = getattr(mod, cls_name).__new__(getattr(mod, cls_name))
    panel._status = _Status()
    panel._current = "PROF"
    panel._load_cfg = lambda: {}
    monkeypatch.setattr(mod.custom_parser, api, lambda name: list(affected))
    dialoghi = []

    def _confirm(title, text):
        dialoghi.append(text)
        return False                              # l'utente ANNULLA

    monkeypatch.setattr(mod.gui_utils, "ask_confirm", _confirm)
    return panel, dialoghi


@pytest.mark.parametrize("cls_name,api,codice", _CASI)
def test_avviso_parser_dentro_il_dialogo_di_conferma(monkeypatch, cls_name, api, codice):
    """FAIL-FIRST: pre-patch il dialogo conteneva solo la domanda; l'avviso
    «ancora selezionato in N parser» appariva SOLO DOPO l'eliminazione."""
    mod = _mod(monkeypatch)
    panel, dialoghi = _panel_delete(mod, cls_name, monkeypatch, api, ["Alfa", "Beta"])
    panel._persist = lambda *a, **k: pytest.fail("annullato: MAI salvare")

    panel._delete_profile()

    assert len(dialoghi) == 1
    testo = dialoghi[0]
    assert "Eliminare il profilo «PROF»" in testo         # la domanda resta
    assert "ancora selezionato in 2 parser" in testo      # avviso PRIMA della scelta
    assert "Alfa, Beta" in testo
    assert codice in testo                                # conseguenza esplicita
    assert "annullata" in panel._status.text.lower()      # e l'annullo resta annullo


@pytest.mark.parametrize("cls_name,api,codice", _CASI)
def test_dialogo_pulito_senza_parser_coinvolti(monkeypatch, cls_name, api, codice):
    """Con NESSUN parser coinvolto il dialogo resta la semplice domanda storica."""
    mod = _mod(monkeypatch)
    panel, dialoghi = _panel_delete(mod, cls_name, monkeypatch, api, [])
    panel._persist = lambda *a, **k: pytest.fail("annullato: MAI salvare")

    panel._delete_profile()

    assert len(dialoghi) == 1
    assert "ancora selezionato" not in dialoghi[0]
    assert codice not in dialoghi[0]


@pytest.mark.parametrize("cls_name,api,codice", _CASI)
def test_conferma_procede_e_avviso_post_delete_resta(monkeypatch, cls_name, api, codice):
    """Confermando, l'eliminazione procede e l'avviso AMBRA post-eliminazione
    (comportamento storico) resta — il dialogo lo ANTICIPA, non lo sostituisce."""
    mod = _mod(monkeypatch)
    panel, dialoghi = _panel_delete(mod, cls_name, monkeypatch, api, ["Alfa"])
    monkeypatch.setattr(mod.gui_utils, "ask_confirm",
                        lambda title, text: dialoghi.append(text) or True)
    salvate = []
    panel._persist = lambda cfg, **k: salvate.append(cfg) or True

    panel._delete_profile()

    assert len(salvate) == 1                              # eliminazione salvata
    assert "ancora selezionato in 1 parser" in panel._status.text
    assert codice in panel._status.text
