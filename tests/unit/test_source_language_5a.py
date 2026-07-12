"""Slice 5a (epica multilingua #3): foundation della LINGUA DELLA FONTE (`source_language`)
per il riconoscimento a NOMI.

Foundation-only: chiave di config + campo per-parser + normalizzazione + risoluzione
globale/override. NESSUN cambio al matching (arriva con la slice 5b). I test esercitano
funzioni reali del progetto e coprono i fail-mode pericolosi (fail-closed: una lingua-fonte
mai scelta NON deve mai essere finta, altrimenti restringerebbe il matching a sorpresa).
"""

from xtrader_bridge import config_store, csv_writer, recognition
from xtrader_bridge.custom_parser import CustomParserDef


def test_source_languages_allineate_al_csv():
    # Anti-drift: l'insieme lingue-fonte è lo STESSO del CSV (#342). Il set è duplicato in
    # `recognition` per tenerlo senza import; se qualcuno aggiunge una lingua a
    # `csv_writer.CSV_LANGUAGES` senza allinearla qui (o viceversa), questo test rompe.
    assert recognition.SOURCE_LANGUAGES == csv_writer.CSV_LANGUAGES


def test_normalize_source_language_valide():
    for raw, exp in (("IT", "IT"), ("EN", "EN"), ("ES", "ES"),
                     ("it", "IT"), (" es ", "ES"), ("En", "EN")):
        assert recognition.normalize_source_language(raw) == exp, raw


def test_normalize_source_language_vuoto_o_sporco_fail_closed():
    # Fail-closed: mancante/garbage/tipo non-stringa → "" (non dichiarata = agnostica), MAI IT.
    for bad in ("", "   ", None, "FR", "PT", "ITA", "xyz", 123, [], {}, True):
        assert recognition.normalize_source_language(bad) == "", repr(bad)


def test_effective_source_language_override_poi_globale_poi_vuoto():
    # Override per-parser vince sul globale; senza override si eredita il globale; senza
    # nessuno dei due → "" (agnostica). Specchio di come `recognition_mode` combina i due.
    d_it = CustomParserDef(name="P", source_language="IT")
    assert recognition.effective_source_language({"source_language": "EN"}, d_it) == "IT"
    d_inherit = CustomParserDef(name="P")            # source_language="" → eredita
    assert recognition.effective_source_language({"source_language": "EN"}, d_inherit) == "EN"
    assert recognition.effective_source_language({"source_language": ""}, d_inherit) == ""
    assert recognition.effective_source_language({}, d_inherit) == ""
    assert recognition.effective_source_language({}, None) == ""


def test_effective_source_language_fail_closed_su_sporco():
    # Un override per-parser SPORCO non vince (→ "" → si eredita il globale valido); un globale
    # sporco → "" (agnostica). `defn` è duck-typed: basta l'attributo `.source_language`.
    class _Duck:
        source_language = "FR"
    assert recognition.effective_source_language({"source_language": "ES"}, _Duck()) == "ES"
    assert recognition.effective_source_language(
        {"source_language": "FR"}, CustomParserDef(name="P")) == ""
    # cfg non-dict → "" senza eccezioni.
    assert recognition.effective_source_language(None, None) == ""


def test_custom_parser_roundtrip_source_language():
    d = CustomParserDef(name="P", source_language="EN")
    assert d.to_dict()["source_language"] == "EN"
    back = CustomParserDef.from_dict(d.to_dict())
    assert back.source_language == "EN"


def test_custom_parser_from_dict_retrocompat_e_fail_closed():
    # File salvato PRIMA della 5a (campo assente) → "" (eredita il globale, retro-compatibile).
    assert CustomParserDef.from_dict({"name": "P"}).source_language == ""
    # Valore malformato nel file → "" (fail-closed, mai un IT silenzioso spacciato per scelta).
    for bad in ("FR", "  ", None, 5, "italiano"):
        assert CustomParserDef.from_dict(
            {"name": "P", "source_language": bad}).source_language == "", repr(bad)
    # Case/spazi normalizzati anche in caricamento.
    assert CustomParserDef.from_dict(
        {"name": "P", "source_language": " es "}).source_language == "ES"


def test_effective_source_language_override_non_stringa_fail_closed():
    # GLM #22: un override per-parser con TIPO NON stringa (int/None/bool/list) passa comunque
    # da `normalize_source_language` → "" → si eredita il globale valido, senza propagare un tipo
    # errato e senza AttributeError. Duck-typing preso sul serio.
    class _Duck:
        def __init__(self, v):
            self.source_language = v
    for bad in (123, None, True, [], {}):
        assert recognition.effective_source_language(
            {"source_language": "IT"}, _Duck(bad)) == "IT", repr(bad)
    # override non-stringa + globale assente → "" (agnostica, fail-closed)
    assert recognition.effective_source_language({}, _Duck(123)) == ""


def test_load_config_roundtrip_preserva_altre_chiavi(tmp_path):
    # GPT #22: un `config.json` PREESISTENTE senza `source_language` si carica con la chiave a
    # "" (default, fail-closed) SENZA perdere le altre chiavi; salvando e ricaricando la
    # lingua-fonte persiste normalizzata e le altre chiavi restano intatte (retro-compat reale
    # su disco, non solo `_migrate`).
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"csv_path": r"C:\Custom\segnali.csv",
                             "recognition_mode": "ID_ONLY"}), encoding="utf-8")
    cfg = config_store.load_config(str(p))
    assert cfg["source_language"] == ""                     # default aggiunto (fail-closed)
    assert cfg["csv_path"] == r"C:\Custom\segnali.csv"      # altra chiave preservata
    assert cfg["recognition_mode"] == "ID_ONLY"            # altra chiave preservata (file esistente)
    # imposta la lingua-fonte e persiste; il reload la normalizza e non perde nulla
    cfg["source_language"] = "en"
    config_store.save_config(cfg, str(p))
    reloaded = config_store.load_config(str(p))
    assert reloaded["source_language"] == "EN"              # "en" → "EN" persistito
    assert reloaded["csv_path"] == r"C:\Custom\segnali.csv"
    assert reloaded["recognition_mode"] == "ID_ONLY"


def test_config_default_source_language_vuoto():
    assert config_store.DEFAULTS["source_language"] == ""


def test_config_migrate_normalizza_source_language():
    # `_migrate` normalizza il valore noto: "en" → "EN"; garbage/tipo errato → ""; chiave
    # assente (config vecchia) → "" (default sicuro).
    assert config_store._migrate({"source_language": "en"})["source_language"] == "EN"
    assert config_store._migrate({"source_language": "FR"})["source_language"] == ""
    assert config_store._migrate({"source_language": "  "})["source_language"] == ""
    assert config_store._migrate({"source_language": 123})["source_language"] == ""
    assert config_store._migrate({})["source_language"] == ""
