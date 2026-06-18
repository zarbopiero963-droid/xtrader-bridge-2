"""PR-13b: test del controller dell'editor sorgenti multi-chat (logica pura)."""

from xtrader_bridge import source_manager
from xtrader_bridge.source_editor import SourceEditor


def test_carica_dalle_sorgenti_di_config():
    cfg = {"source_chats": [
        {"name": "Canale A", "chat_id": "111", "enabled": True, "mode": "PRE"},
        {"name": "Canale B", "chat_id": "222", "enabled": False, "mode": "live"},
    ]}
    ed = SourceEditor(cfg)
    assert len(ed.sources) == 2
    assert ed.sources[0]["chat_id"] == "111"
    assert ed.sources[1]["enabled"] is False
    assert ed.sources[1]["mode"] == "LIVE"   # normalizzata


def test_mode_options_da_source_manager():
    assert SourceEditor().mode_options() == list(source_manager.MODES)


def test_add_update_remove():
    ed = SourceEditor()
    ed.add_source(name="  X ", chat_id=" 42 ", enabled=True, mode="pre", provider=" TG_VIP ")
    assert ed.sources[0] == {"name": "X", "chat_id": "42", "enabled": True,
                             "mode": "PRE", "provider": "TG_VIP"}
    ed.update_source(0, enabled=False, mode="LIVE")
    assert ed.sources[0]["enabled"] is False
    assert ed.sources[0]["mode"] == "LIVE"
    assert ed.sources[0]["chat_id"] == "42"   # campo non toccato preservato
    ed.remove_source(0)
    assert ed.sources == []


def test_mode_ignota_normalizzata_a_default():
    ed = SourceEditor()
    ed.add_source(chat_id="1", mode="PINCO")
    assert ed.sources[0]["mode"] == source_manager.DEFAULT_MODE   # PRE


def test_apply_valido_setta_source_chats_preservando_altre_chiavi():
    ed = SourceEditor()
    ed.add_source(name="A", chat_id="111", mode="PRE")
    ed.add_source(name="B", chat_id="222", mode="LIVE")
    cfg = {"bot_token": "T", "chat_id": "999"}
    new_cfg, errors, warnings = ed.apply(cfg)
    assert errors == [] and warnings == []
    assert [s["chat_id"] for s in new_cfg["source_chats"]] == ["111", "222"]
    assert new_cfg["bot_token"] == "T" and new_cfg["chat_id"] == "999"


def test_apply_chat_id_duplicato_blocca_senza_salvare():
    ed = SourceEditor()
    ed.add_source(name="A", chat_id="111")
    ed.add_source(name="B", chat_id="111")   # duplicato → errore bloccante
    cfg = {"source_chats": [{"chat_id": "vecchio"}]}
    new_cfg, errors, warnings = ed.apply(cfg)
    assert errors, "chat_id duplicato deve produrre un errore"
    # Config invariata (niente salvataggio parziale).
    assert new_cfg["source_chats"] == [{"chat_id": "vecchio"}]


def test_apply_chat_id_mancante_blocca():
    ed = SourceEditor()
    ed.add_source(name="SenzaId", chat_id="")
    new_cfg, errors, warnings = ed.apply({})
    assert errors
    assert "source_chats" not in new_cfg


def test_nome_duplicato_e_solo_avviso_non_blocca():
    ed = SourceEditor()
    ed.add_source(name="Uguale", chat_id="111")
    ed.add_source(name="Uguale", chat_id="222")   # nome dup, chat_id diversi
    new_cfg, errors, warnings = ed.apply({})
    assert errors == []
    assert warnings, "nome duplicato deve dare un avviso non bloccante"
    assert len(new_cfg["source_chats"]) == 2


def test_apply_non_muta_la_config_originale():
    ed = SourceEditor()
    ed.add_source(name="A", chat_id="111")
    cfg = {"source_chats": [{"chat_id": "old"}], "keep": "me"}
    new_cfg, errors, _ = ed.apply(cfg)
    assert errors == []
    assert cfg["source_chats"] == [{"chat_id": "old"}]   # originale intatto
    assert new_cfg["keep"] == "me"
