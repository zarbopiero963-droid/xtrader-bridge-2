"""Test della configurazione (PR-02 → PR-04).

`load`/`save`/`migrate` sono funzioni pure in `xtrader_bridge.config_store`,
testabili headless con path temporanei. PR-04: cartella utente persistente
(`%APPDATA%`), migrazione del config legacy, backup di config corrotta.
"""

import json
import os

from xtrader_bridge import config_store


def test_config_file_e_config_json():
    assert config_store.CONFIG_FILE.endswith("config.json")
    assert os.path.isabs(config_store.CONFIG_FILE)


def test_load_config_default_senza_file(tmp_path):
    cfg = config_store.load_config(str(tmp_path / "assente.json"))
    for k in ("bot_token", "chat_id", "csv_path", "clear_delay", "provider"):
        assert k in cfg
    assert isinstance(cfg["clear_delay"], int)
    assert cfg["provider"]                       # default non vuoto


def test_load_config_merge_con_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "TG_PRE", "chat_id": "-100123"}))
    cfg = config_store.load_config(str(p))
    assert cfg["provider"] == "TG_PRE"
    assert cfg["chat_id"] == "-100123"
    assert "csv_path" in cfg                      # default preservato


def test_load_config_json_malformato_usa_default_e_backup(tmp_path):
    # File presente ma JSON non valido: nessuna eccezione, default preservati,
    # e il file corrotto viene messo da parte come .bak.
    p = tmp_path / "config.json"
    p.write_text("{ questo non e' json valido ,,, ")
    cfg = config_store.load_config(str(p))
    assert cfg["csv_path"] == config_store.DEFAULTS["csv_path"]
    assert cfg["provider"] == config_store.DEFAULTS["provider"]
    assert os.path.exists(str(p) + ".bak")        # backup creato
    assert not os.path.exists(str(p))             # originale rimosso


def test_load_config_json_non_dict_usa_default_e_backup(tmp_path):
    # JSON valido ma non dizionario (es. lista): trattato come corrotto.
    p = tmp_path / "config.json"
    p.write_text("[]")
    cfg = config_store.load_config(str(p))
    assert cfg["provider"] == config_store.DEFAULTS["provider"]
    assert os.path.exists(str(p) + ".bak")        # backup creato
    assert not os.path.exists(str(p))             # originale rimosso


def test_backup_sovrascrive_bak_preesistente(tmp_path):
    # Se esiste già un .bak, il backup non deve fallire (robustezza Windows).
    p = tmp_path / "config.json"
    p.write_text("non json {")
    (tmp_path / "config.json.bak").write_text("vecchio backup")
    config_store.load_config(str(p))              # non deve sollevare
    assert os.path.exists(str(p) + ".bak")
    assert not os.path.exists(str(p))


def test_save_then_load_roundtrip(tmp_path):
    p = str(tmp_path / "config.json")
    data = {"bot_token": "X", "chat_id": "-1", "csv_path": "/tmp/s.csv",
            "clear_delay": 30, "provider": "TG_LIVE"}
    config_store.save_config(data, p)
    assert config_store.load_config(p) == {**config_store.DEFAULTS, **data}


def test_defaults_non_contengono_segreti():
    assert config_store.DEFAULTS["bot_token"] == ""
    assert config_store.DEFAULTS["chat_id"] == ""


def test_default_recognition_mode_name_only():
    assert config_store.DEFAULTS["recognition_mode"] == "NAME_ONLY"


def test_require_price_non_e_piu_chiave_globale(tmp_path):
    # La quota obbligatoria sì/no NON è più un default globale: la governa la riga
    # Price di ogni Parser Personalizzato (CustomParserDef.price_required).
    assert "require_price" not in config_store.DEFAULTS
    # Una chiave custom arbitraria sopravvive comunque a save→load (config non la perde).
    p = str(tmp_path / "config.json")
    config_store.save_config({"provider": "TG", "custom_flag": False}, p)
    assert config_store.load_config(p)["custom_flag"] is False
    # Compat: una vecchia config con `require_price` NON va in crash e la chiave legacy
    # sopravvive (semplicemente ignorata a runtime, governata ora dalla riga Price).
    p2 = str(tmp_path / "legacy.json")
    config_store.save_config({"provider": "TG", "require_price": False}, p2)
    loaded = config_store.load_config(p2)
    assert loaded["require_price"] is False        # non rimossa, non causa errori
    assert loaded["provider"] == "TG"


# ── PR-04: cartella utente, migrazione, versione ──

def test_config_dir_usa_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", os.path.join("X", "Roaming"))
    d = config_store.config_dir()
    assert d.endswith(config_store.APP_DIR_NAME)
    assert os.path.join("X", "Roaming") in d


def test_config_path_dentro_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = config_store.config_path()
    assert p == os.path.join(str(tmp_path), config_store.APP_DIR_NAME, "config.json")


def test_config_version_presente_nei_default():
    cfg = config_store.load_config(str("/percorso/inesistente/config.json"))
    assert cfg["config_version"] == config_store.CONFIG_VERSION


def test_config_version_aggiunto_e_persistito_da_config_legacy(tmp_path):
    # Config legacy senza config_version: load lo aggiunge, save lo persiste.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "TG_PRE", "csv_path": "x.csv"}))
    cfg = config_store.load_config(str(p))
    assert cfg["config_version"] == config_store.CONFIG_VERSION
    config_store.save_config(cfg, str(p))
    on_disk = json.loads(p.read_text())
    assert on_disk["config_version"] == config_store.CONFIG_VERSION


def test_legacy_path_da_executable_se_frozen(monkeypatch, tmp_path):
    # Nell'EXE PyInstaller il legacy config va cercato accanto a sys.executable.
    exe = tmp_path / "app" / "XTrader-Signal-Bridge.exe"
    monkeypatch.setattr(config_store.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_store.sys, "executable", str(exe), raising=False)
    p = config_store.legacy_config_path()
    assert p == str(tmp_path / "app" / "config.json")


def test_legacy_path_dev_non_frozen(monkeypatch):
    monkeypatch.setattr(config_store.sys, "frozen", False, raising=False)
    p = config_store.legacy_config_path()
    assert p.endswith("config.json") and os.path.isabs(p)


def test_config_version_su_disco_preservato(tmp_path):
    # Se il file porta un config_version diverso (futuro v2), NON viene sovrascritto.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"config_version": 99, "provider": "X"}))
    cfg = config_store.load_config(str(p))
    assert cfg["config_version"] == 99            # skew su disco preservato


def test_migrate_legacy_copia_quando_nuovo_assente(tmp_path):
    legacy = tmp_path / "legacy" / "config.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"provider": "VECCHIO"}))
    new = tmp_path / "appdata" / "XTraderBridge" / "config.json"

    migrated = config_store.migrate_legacy_config(str(new), str(legacy))
    assert migrated is True
    assert new.exists()                           # creato nella nuova posizione
    assert legacy.exists()                        # legacy NON rimosso (non distruttivo)
    assert config_store.load_config(str(new))["provider"] == "VECCHIO"


def test_migrate_legacy_skip_se_nuovo_esiste(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"provider": "VECCHIO"}))
    new = tmp_path / "config.json"
    new.write_text(json.dumps({"provider": "NUOVO"}))

    migrated = config_store.migrate_legacy_config(str(new), str(legacy))
    assert migrated is False
    assert config_store.load_config(str(new))["provider"] == "NUOVO"  # non sovrascritto


def test_migrate_legacy_skip_se_nessun_legacy(tmp_path):
    new = tmp_path / "config.json"
    assert config_store.migrate_legacy_config(str(new), str(tmp_path / "assente.json")) is False
    assert not new.exists()


def test_save_config_logga_errore_io_ma_resta_best_effort(tmp_path, caplog):
    # Persistenza fallita (qui il path è una DIRECTORY → os.replace solleva OSError):
    # l'app prosegue (ritorna la config in memoria) MA ora l'errore è LOGGATO,
    # non più silenzioso (`except: pass`), e `ok` è False (A1: niente falso "salvato").
    target = tmp_path / "sono_una_cartella"
    target.mkdir()
    with caplog.at_level("ERROR", logger="xtrader_bridge.config_store"):
        out, ok = config_store.save_config({"provider": "X"}, str(target))
    assert out["provider"] == "X"                  # best-effort preservato
    assert ok is False                             # A1: la GUI non deve dire "salvato"
    assert any("Salvataggio config fallito" in r.getMessage() for r in caplog.records)
    # Nessun temporaneo lasciato in giro dopo il fallimento.
    assert not [f for f in os.listdir(target.parent) if f.startswith(config_store.TMP_PREFIX)]


def test_save_config_successo_ritorna_ok_e_persiste(tmp_path):
    # Percorso normale: ritorna ok=True, il file è rileggibile con i valori salvati e
    # non resta alcun temporaneo `.config_*` (scrittura atomica completata).
    p = tmp_path / "cfg" / "config.json"
    out, ok = config_store.save_config({"provider": "TG", "chat_id": "123"}, str(p))
    assert ok is True
    assert out["provider"] == "TG"
    reread = config_store.load_config(str(p))
    assert reread["provider"] == "TG" and reread["chat_id"] == "123"
    assert not [f for f in os.listdir(p.parent) if f.startswith(config_store.TMP_PREFIX)]


def test_save_config_atomico_non_distrugge_il_file_esistente_su_errore(tmp_path, monkeypatch):
    # Una scrittura interrotta (os.replace fallisce) NON deve troncare/cancellare il
    # config già presente: il vecchio file resta intatto (invariante 7).
    p = tmp_path / "config.json"
    config_store.save_config({"provider": "BUONO"}, str(p))     # stato valido iniziale

    real_replace = os.replace
    def _boom(src, dst):
        raise OSError("rename interrotto")
    monkeypatch.setattr(config_store.os, "replace", _boom)
    out, ok = config_store.save_config({"provider": "NUOVO"}, str(p))
    monkeypatch.setattr(config_store.os, "replace", real_replace)

    assert ok is False
    # Il file su disco è ancora quello valido precedente, non corrotto/troncato.
    assert config_store.load_config(str(p))["provider"] == "BUONO"
    assert not [f for f in os.listdir(p.parent) if f.startswith(config_store.TMP_PREFIX)]


# ── audit C5: migrazione/coercizione tipi noti su load ──

def test_load_config_coerce_intero_da_stringa(tmp_path):
    # Config editata a mano: "90" stringa dove serve un intero (clear_delay/timeout).
    # _migrate deve riportarlo a int, non propagare la stringa ai consumer (audit C5).
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"clear_delay": "30", "confirmation_timeout": "45",
                             "max_per_day": "10", "max_signal_age": "60"}))
    cfg = config_store.load_config(str(p))
    assert cfg["clear_delay"] == 30 and isinstance(cfg["clear_delay"], int)
    assert cfg["confirmation_timeout"] == 45 and isinstance(cfg["confirmation_timeout"], int)
    assert cfg["max_per_day"] == 10 and isinstance(cfg["max_per_day"], int)
    assert cfg["max_signal_age"] == 60 and isinstance(cfg["max_signal_age"], int)


def test_load_config_intero_illeggibile_torna_al_default(tmp_path):
    # Valore non interpretabile come intero → default sicuro, niente crash/typo runtime.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"clear_delay": "non-un-numero", "max_signal_age": True}))
    cfg = config_store.load_config(str(p))
    assert cfg["clear_delay"] == config_store.DEFAULTS["clear_delay"]
    # `True` (JSON true) NON deve diventare 1 secondo di età massima: torna al default.
    assert cfg["max_signal_age"] == config_store.DEFAULTS["max_signal_age"]


def test_load_config_dry_run_resta_simulazione_su_valore_sporco(tmp_path):
    # Sicurezza: dry_run (simulazione) di default True. Un valore sporco non interpretabile
    # come falsey deve restare True (simulazione), MAI cadere a "scommetti davvero".
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"dry_run": "boh"}))
    assert config_store.load_config(str(p))["dry_run"] is True
    # Mentre un esplicito falsey (scelta dell'utente) viene onorato.
    p.write_text(json.dumps({"dry_run": "false"}))
    assert config_store.load_config(str(p))["dry_run"] is False


def test_load_config_lista_e_dict_sbagliati_tornano_al_default(tmp_path):
    # source_chats/keywords devono essere liste e parser_by_chat un dict: un tipo
    # sbagliato (file editato male) viene riportato al default sicuro, non propagato.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"source_chats": "non-una-lista",
                             "confirmation_keywords": 5,
                             "parser_by_chat": ["non", "un", "dict"]}))
    cfg = config_store.load_config(str(p))
    assert cfg["source_chats"] == config_store.DEFAULTS["source_chats"]
    assert cfg["confirmation_keywords"] == config_store.DEFAULTS["confirmation_keywords"]
    assert cfg["parser_by_chat"] == config_store.DEFAULTS["parser_by_chat"]


def test_load_config_lista_valida_preservata(tmp_path):
    # Una lista già del tipo giusto NON va toccata (no falsi reset).
    p = tmp_path / "config.json"
    chats = [{"name": "A", "chat_id": "-100", "enabled": True}]
    p.write_text(json.dumps({"source_chats": chats}))
    assert config_store.load_config(str(p))["source_chats"] == chats


def test_load_config_chiavi_sconosciute_non_toccate_da_migrate(tmp_path):
    # _migrate itera solo le chiavi note (DEFAULTS): una chiave futura/legacy con
    # qualunque tipo sopravvive intatta (forward-compat).
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"chiave_ignota": {"nested": [1, 2]}, "config_version": 99}))
    cfg = config_store.load_config(str(p))
    assert cfg["chiave_ignota"] == {"nested": [1, 2]}
    assert cfg["config_version"] == 99    # skew su disco preservato come intero


# ── audit C7: save_config ritorna una copia profonda (no aliasing nested) ──

def test_save_config_ritorna_deepcopy_senza_aliasing(tmp_path):
    # La config restituita non deve condividere i nested mutabili con quella passata:
    # mutare uno NON deve alterare l'altro (audit C7). Il chiamante fa self._config=saved.
    p = str(tmp_path / "config.json")
    cfg_in = {"provider": "TG", "source_chats": [{"name": "A"}], "parser_by_chat": {"-1": "px"}}
    saved, ok = config_store.save_config(cfg_in, p)
    assert ok is True
    # Muto la copia restituita: l'input originale resta invariato.
    saved["source_chats"].append({"name": "B"})
    saved["parser_by_chat"]["-2"] = "py"
    assert cfg_in["source_chats"] == [{"name": "A"}]
    assert cfg_in["parser_by_chat"] == {"-1": "px"}
    # E viceversa: muto l'input dopo il save, la copia salvata non cambia.
    cfg_in["source_chats"].append({"name": "C"})
    assert saved["source_chats"] == [{"name": "A"}, {"name": "B"}]


def test_migrate_legacy_logga_errore_ma_non_crasha(tmp_path, caplog):
    # Migrazione fallita (la dir di destinazione è in realtà un FILE → makedirs
    # solleva): ritorna False senza crashare, e ora logga il motivo.
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"provider": "VECCHIO"}))
    blocker = tmp_path / "afile"
    blocker.write_text("non sono una cartella")    # un file dove servirebbe una dir
    new = blocker / "config.json"                  # dirname(new) è un FILE → makedirs fallisce
    with caplog.at_level("WARNING", logger="xtrader_bridge.config_store"):
        migrated = config_store.migrate_legacy_config(str(new), str(legacy))
    assert migrated is False
    assert any("Migrazione config legacy fallita" in r.getMessage() for r in caplog.records)
