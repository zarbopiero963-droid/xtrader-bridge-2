"""Test dell'anagrafica Provider (PR-5): lista pura su dict di config."""

from xtrader_bridge import provider_store as ps


def test_provider_names_pulisce_dedup_ordina():
    cfg = {"providers": ["  MioBot ", "TG_LIVE", "miobot", "", None, "Alfa"]}
    # ripulito, dedup case-insensitive (tiene il primo), ordinato case-insensitive
    assert ps.provider_names(cfg) == ["Alfa", "MioBot", "TG_LIVE"]


def test_provider_names_assente_o_non_lista():
    assert ps.provider_names({}) == []
    assert ps.provider_names({"providers": None}) == []
    assert ps.provider_names({"providers": "MioBot"}) == []   # non lista → vuoto


def test_add_provider_immutabile_e_no_duplicati():
    cfg = {"providers": ["MioBot"], "chat_id": "42"}
    out = ps.add_provider(cfg, "  Pickfair ")
    assert out["providers"] == ["MioBot", "Pickfair"]
    assert out["chat_id"] == "42"                  # resto della config preservato
    assert cfg["providers"] == ["MioBot"]          # originale non mutato
    # duplicato case-insensitive → non aggiunge
    assert ps.add_provider(out, "miobot")["providers"] == ["MioBot", "Pickfair"]
    # nome vuoto → invariato
    assert ps.add_provider(cfg, "   ")["providers"] == ["MioBot"]


def test_remove_provider():
    cfg = {"providers": ["MioBot", "Pickfair"]}
    assert ps.remove_provider(cfg, "miobot")["providers"] == ["Pickfair"]   # case-insensitive
    assert ps.remove_provider(cfg, "assente")["providers"] == ["MioBot", "Pickfair"]
    assert cfg["providers"] == ["MioBot", "Pickfair"]                       # originale intatto
