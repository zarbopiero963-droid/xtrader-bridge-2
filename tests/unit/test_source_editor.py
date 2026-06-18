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
                             "mode": "PRE", "provider": "TG_VIP", "parser": ""}
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


# ── PR-13c: override parser per chat (parser_by_chat) ───────────────────────

def test_prefill_parser_per_chat_dalla_config():
    cfg = {
        "source_chats": [{"chat_id": "111"}, {"chat_id": "222"}],
        "parser_by_chat": {"111": "Esempio", "999": "Orfano"},
    }
    ed = SourceEditor(cfg)
    assert ed.sources[0]["parser"] == "Esempio"   # 111 prefillato
    assert ed.sources[1]["parser"] == ""          # 222 nessun override


def test_apply_setta_parser_by_chat_e_preserva_orfani():
    cfg = {"parser_by_chat": {"999": "Orfano"}}   # 999 non è una riga → orfano
    ed = SourceEditor()
    ed.add_source(chat_id="111", parser="Esempio")
    ed.add_source(chat_id="222", parser="")        # nessun override per 222
    new_cfg, errors, _ = ed.apply(cfg)
    assert errors == []
    assert new_cfg["parser_by_chat"] == {"999": "Orfano", "111": "Esempio"}
    # 222 senza override non compare; 999 (orfano) preservato.


def test_apply_azzera_override_quando_parser_vuoto():
    cfg = {"parser_by_chat": {"111": "Vecchio"}}
    ed = SourceEditor(cfg)                          # 111 non è una sorgente → resta orfano
    # Aggiungo 111 come sorgente SENZA parser → l'override va rimosso.
    ed = SourceEditor()
    ed.add_source(chat_id="111", parser="")
    new_cfg, errors, _ = ed.apply(cfg)
    assert errors == []
    assert "111" not in new_cfg["parser_by_chat"]


def test_apply_errore_non_tocca_parser_by_chat():
    cfg = {"parser_by_chat": {"111": "X"}}
    ed = SourceEditor()
    ed.add_source(chat_id="")                       # chat_id mancante → errore
    new_cfg, errors, _ = ed.apply(cfg)
    assert errors
    assert new_cfg["parser_by_chat"] == {"111": "X"}   # invariato


def test_apply_rimuove_override_di_sorgente_eliminata():
    # Safety (Codex P1 / CodeRabbit): se rimuovo una sorgente che aveva un override,
    # la sua voce parser_by_chat va eliminata, altrimenti la chat resterebbe
    # autorizzata via is_chat_allowed. Le voci NON-sorgente restano.
    cfg = {
        "source_chats": [{"chat_id": "111"}],          # 111 era una sorgente...
        "parser_by_chat": {"111": "X", "999": "Manuale"},
    }
    ed = SourceEditor()                                 # ...ora NESSUNA riga (111 rimossa)
    new_cfg, errors, _ = ed.apply(cfg)
    assert errors == []
    assert "111" not in new_cfg["parser_by_chat"]       # override della sorgente rimossa eliminato
    assert new_cfg["parser_by_chat"]["999"] == "Manuale"  # voce non-sorgente preservata


def test_apply_rinomina_chat_id_sposta_override():
    # Rename: la vecchia chat (sorgente) sparisce dagli override, la nuova li riceve.
    cfg = {"source_chats": [{"chat_id": "111"}], "parser_by_chat": {"111": "X"}}
    ed = SourceEditor()
    ed.add_source(chat_id="222", parser="X")            # 111 -> 222 (con stesso parser)
    new_cfg, errors, _ = ed.apply(cfg)
    assert errors == []
    assert "111" not in new_cfg["parser_by_chat"]       # vecchia chat non più autorizzata
    assert new_cfg["parser_by_chat"]["222"] == "X"


def test_apply_preserva_override_della_chat_globale_se_sorgente_rimossa():
    # Codex P2-a: la chat è sia chat_id globale sia una sorgente; rimuovendo la
    # sorgente, l'override NON va perso (la chat resta autorizzata via chat_id).
    cfg = {"chat_id": "111", "source_chats": [{"chat_id": "111"}],
           "parser_by_chat": {"111": "X"}}
    ed = SourceEditor()                       # nessuna riga: 111 rimossa come sorgente
    new_cfg, errors, _ = ed.apply(cfg)
    assert errors == []
    assert new_cfg["parser_by_chat"]["111"] == "X"   # preservato (è il chat_id globale)


def test_apply_riga_disattivata_non_scrive_override():
    # Codex P2-b: una sorgente disattivata non deve lasciare una chiave parser_by_chat
    # (altrimenti il check chat-notifiche di _start la conterebbe come sorgente).
    ed = SourceEditor()
    ed.add_source(chat_id="222", enabled=False, parser="X")
    new_cfg, errors, _ = ed.apply({})
    assert errors == []
    assert "222" not in new_cfg.get("parser_by_chat", {})
