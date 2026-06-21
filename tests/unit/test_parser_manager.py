"""Test della gestione del Parser Personalizzato attivo (CP-07)."""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_manager as pm
from xtrader_bridge.config_store import DEFAULTS


def _save_parser(name, dir_path):
    defn = cp.CustomParserDef(name=name, rules=[cp.FieldRule(target="Price", required=True)])
    return cp.save_parser(defn, dir_path)


# ── default di config ──────────────────────────────────────────────────────

def test_defaults_hanno_le_chiavi():
    assert DEFAULTS["active_parser"] == ""
    assert DEFAULTS["parser_by_chat"] == {}


def test_parser_by_chat_normalizza_chiavi_a_str():
    # Codex P2: una chiave non-stringa (es. int da config a mano) è normalizzata a str
    # ALLA FONTE, così il lookup per-chat è coerente con is_chat_allowed (che ammette
    # str(chat)) e il messaggio custom non viene perso/degradato all'hardcoded.
    cfg = {"parser_by_chat": {123: "PerChat"}}
    assert pm.parser_by_chat(cfg) == {"123": "PerChat"}
    assert pm.resolve_parser_name(cfg, "123") == "PerChat"   # lookup trova l'override
    assert pm.parser_by_chat({"parser_by_chat": "non-dict"}) == {}


# ── risoluzione del nome ─────────────────────────────────────────────────────

def test_resolve_nessuno_di_default():
    assert pm.resolve_parser_name({}) == ""
    assert pm.resolve_parser_name({"active_parser": ""}) == ""


def test_resolve_attivo_globale():
    assert pm.resolve_parser_name({"active_parser": "Yangon"}) == "Yangon"
    assert pm.resolve_parser_name({"active_parser": "Yangon"}, chat_id="123") == "Yangon"


def test_resolve_override_per_chat():
    cfg = {"active_parser": "Globale", "parser_by_chat": {"123": "PerChat"}}
    assert pm.resolve_parser_name(cfg, chat_id="123") == "PerChat"   # override
    assert pm.resolve_parser_name(cfg, chat_id="999") == "Globale"   # nessun override → globale
    assert pm.resolve_parser_name(cfg) == "Globale"


# ── set_active / set_for_chat (immutabili) ──────────────────────────────────

def test_set_active_non_muta_originale():
    cfg = {"active_parser": ""}
    out = pm.set_active(cfg, "  Yangon  ")
    assert out["active_parser"] == "Yangon"
    assert cfg["active_parser"] == ""        # originale invariato


def test_set_for_chat_aggiunge_e_rimuove():
    cfg = {}
    out = pm.set_for_chat(cfg, "123", "PerChat")
    assert out["parser_by_chat"] == {"123": "PerChat"}
    cleared = pm.set_for_chat(out, "123", "")   # nome vuoto → rimuove
    assert cleared["parser_by_chat"] == {}


# ── elenco e caricamento ─────────────────────────────────────────────────────

def test_available_parser_names(tmp_path):
    _save_parser("Alfa", str(tmp_path))
    _save_parser("Beta", str(tmp_path))
    assert pm.available_parser_names(str(tmp_path)) == ["Alfa", "Beta"]


def test_available_parser_names_esclude_invalidi(tmp_path):
    import json
    _save_parser("Buono", str(tmp_path))
    # File deserializzabile ma invalido (target duplicato): non deve comparire.
    bad = {"name": "Cattivo", "rules": [
        {"target": "BetType", "fixed_value": "PUNTA"},
        {"target": "BetType", "fixed_value": "BANCA"},
    ]}
    (tmp_path / "Cattivo.json").write_text(json.dumps(bad), encoding="utf-8")
    assert pm.available_parser_names(str(tmp_path)) == ["Buono"]


def test_available_parser_names_esclude_file_rinominato(tmp_path):
    import json
    # File il cui nome interno NON ri-mappa al filename: load_active non lo
    # troverebbe → non va offerto nel menu.
    good = {"name": "Shown", "rules": [{"target": "Price", "required": True}]}
    (tmp_path / "Wrong.json").write_text(json.dumps(good), encoding="utf-8")
    assert pm.available_parser_names(str(tmp_path)) == []


def test_available_parser_names_esclude_nome_con_spazi(tmp_path):
    import json
    # Nome con spazi iniziali/finali: invalido → non offerto (eviterebbe un
    # fallback silenzioso, perché la selezione viene strippata).
    spazi = {"name": " Foo ", "rules": [{"target": "Price", "required": True}]}
    (tmp_path / "Foo.json").write_text(json.dumps(spazi), encoding="utf-8")
    assert pm.available_parser_names(str(tmp_path)) == []


def test_validate_rifiuta_nome_con_spazi():
    d = cp.CustomParserDef(name=" Foo ", rules=[cp.FieldRule(target="Price", required=True)])
    assert any("spazi iniziali" in e for e in cp.validate_parser_def(d))


def test_set_active_copia_parser_by_chat():
    cfg = {"active_parser": "", "parser_by_chat": {"123": "X"}}
    out = pm.set_active(cfg, "Nuovo")
    out["parser_by_chat"]["999"] = "Y"          # muto la copia
    assert cfg["parser_by_chat"] == {"123": "X"}  # originale invariato


def test_load_active_none_se_non_selezionato(tmp_path):
    assert pm.load_active({}, dir_path=str(tmp_path)) is None


def test_load_active_none_se_file_mancante(tmp_path):
    assert pm.load_active({"active_parser": "NonEsiste"}, dir_path=str(tmp_path)) is None


def test_load_active_carica_il_parser(tmp_path):
    _save_parser("Yangon", str(tmp_path))
    defn = pm.load_active({"active_parser": "Yangon"}, dir_path=str(tmp_path))
    assert defn is not None and defn.name == "Yangon"


def test_load_config_non_condivide_parser_by_chat(tmp_path):
    # deepcopy dei DEFAULTS: mutare la config restituita non deve toccare DEFAULTS
    # né i load successivi.
    from xtrader_bridge import config_store
    missing = str(tmp_path / "non_esiste.json")
    cfg1 = config_store.load_config(missing)
    cfg1["parser_by_chat"]["123"] = "X"
    cfg2 = config_store.load_config(missing)
    assert cfg2["parser_by_chat"] == {}
    assert config_store.DEFAULTS["parser_by_chat"] == {}


def test_load_active_file_non_oggetto_e_none(tmp_path):
    # File JSON valido ma non-oggetto (es. "[]"): fail-safe → None, non crash.
    bad = tmp_path / "Rotto.json"
    bad.write_text("[]", encoding="utf-8")
    assert pm.load_active({"active_parser": "Rotto"}, dir_path=str(tmp_path)) is None


def test_load_active_rifiuta_nome_che_collide(tmp_path):
    # Esiste solo il parser "AB"; richiedere "A/B" (che si sanitizza ad AB.json)
    # NON deve caricare "AB": fail-closed → None.
    _save_parser("AB", str(tmp_path))
    assert pm.load_active({"active_parser": "A/B"}, dir_path=str(tmp_path)) is None


def test_load_active_rifiuta_parser_invalido(tmp_path):
    # File scritto a mano, valido come JSON ma semanticamente invalido (target
    # duplicato): load_active deve ritornare None, non un parser ambiguo.
    import json
    bad = {"name": "Dup", "rules": [
        {"target": "BetType", "fixed_value": "PUNTA"},
        {"target": "BetType", "fixed_value": "BANCA"},
    ]}
    (tmp_path / "Dup.json").write_text(json.dumps(bad), encoding="utf-8")
    assert pm.load_active({"active_parser": "Dup"}, dir_path=str(tmp_path)) is None


def test_load_active_rules_malformato_none(tmp_path):
    # rules:null non deve crashare (TypeError) ma fallire chiuso.
    (tmp_path / "Nullo.json").write_text('{"name":"Nullo","rules":null}', encoding="utf-8")
    # rules None → [] → parser senza regole → invalido → None.
    assert pm.load_active({"active_parser": "Nullo"}, dir_path=str(tmp_path)) is None


def test_load_active_override_per_chat(tmp_path):
    _save_parser("Globale", str(tmp_path))
    _save_parser("PerChat", str(tmp_path))
    cfg = {"active_parser": "Globale", "parser_by_chat": {"123": "PerChat"}}
    assert pm.load_active(cfg, chat_id="123", dir_path=str(tmp_path)).name == "PerChat"
    assert pm.load_active(cfg, chat_id="999", dir_path=str(tmp_path)).name == "Globale"
