"""Test hard PR-2: ROUTER MULTI-PARSER per chat.

Una chat può avere PIÙ parser (in ordine); ogni messaggio è passato a tutti e scattano TUTTI
quelli le cui condizioni/estrazione combaciano («tutti quelli che combaciano», scelta del
proprietario). Le righe dei parser che scattano sono unite in ordine di priorità e **deduplicate
per-riga** (due parser che producono la STESSA riga = una sola scommessa; righe diverse = bet
diversi voluti).

Esercitano il codice reale end-to-end:
- `parser_manager`: `parser_list_by_chat`, `resolve_parser_names`, `resolve_parser_name`,
  `load_active_list`, `set_list_for_chat`;
- `signal_router.resolve_row` con più parser salvati su disco;
- invarianti di sicurezza: filtro chat non indebolito, retro-compat single-parser, no doppia
  scommessa accidentale (dedup per-riga).

Niente GUI, niente rete.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_io, parser_manager, signal_router


# ── helper: salva varianti di example_parser su disco ─────────────────────────

def _mk(dir_path, name, conditions=None, mode="all", market_type=None, selection_name=None):
    """Salva una variante di `example_parser` con condizioni e, opzionalmente, MarketType/
    SelectionName FISSI diversi (così due parser producono righe DIVERSE)."""
    defn = parser_io.example_parser()
    defn.name = name
    defn.conditions = list(conditions or [])
    defn.conditions_mode = mode
    for r in defn.rules:
        if r.target == "MarketType" and market_type is not None:
            r.fixed_value = market_type
        if r.target == "SelectionName" and selection_name is not None:
            r.start_after = ""
            r.end_before = ""
            r.value_map = ""
            r.fixed_value = selection_name
    return cp.save_parser(defn, dir_path)


def _cfg_list(chat, names):
    return {"provider": "TG", "chat_id": chat, "recognition_mode": "NAME_ONLY",
            "parser_list_by_chat": {chat: list(names)}}


# ── parser_manager: modello lista multi-parser ────────────────────────────────

def test_parser_list_by_chat_normalizza_e_deduplica():
    cfg = {"parser_list_by_chat": {"42": ["  A ", "B", "A", "", "  "], 7: ["C"]}}
    out = parser_manager.parser_list_by_chat(cfg)
    assert out == {"42": ["A", "B"], "7": ["C"]}          # trim, dedup ordine, chiave a str


def test_parser_list_by_chat_failsafe_su_valore_non_lista():
    cfg = {"parser_list_by_chat": {"42": "A", "7": ["X"]}}   # "A" non è una lista
    assert parser_manager.parser_list_by_chat(cfg) == {"7": ["X"]}
    assert parser_manager.parser_list_by_chat({"parser_list_by_chat": "boh"}) == {}


def test_resolve_parser_names_precedenza_lista_poi_singolo_poi_globale():
    # lista multi vince sull'override singolo e sul globale
    cfg = {"parser_list_by_chat": {"42": ["A", "B"]},
           "parser_by_chat": {"42": "C"}, "active_parser": "G"}
    assert parser_manager.resolve_parser_names(cfg, "42") == ["A", "B"]
    # senza lista per la chat → override singolo
    cfg2 = {"parser_by_chat": {"42": "C"}, "active_parser": "G"}
    assert parser_manager.resolve_parser_names(cfg2, "42") == ["C"]
    # senza override → globale
    assert parser_manager.resolve_parser_names({"active_parser": "G"}, "42") == ["G"]
    # niente configurato → []
    assert parser_manager.resolve_parser_names({}, "42") == []


def test_resolve_parser_name_singolo_e_primo_della_lista():
    cfg = {"parser_list_by_chat": {"42": ["A", "B"]}}
    assert parser_manager.resolve_parser_name(cfg, "42") == "A"      # primo della lista
    assert parser_manager.resolve_parser_name({}, "42") == ""


def test_set_list_for_chat_scrive_lista_e_sincronizza_singolo():
    out = parser_manager.set_list_for_chat({}, "42", ["A", "B", "A", ""])
    assert out["parser_list_by_chat"]["42"] == ["A", "B"]            # dedup ordine
    assert out["parser_by_chat"]["42"] == "A"                        # singolo sincronizzato al primo
    # lista vuota → rimuove entrambe le voci per la chat
    cleared = parser_manager.set_list_for_chat(out, "42", [])
    assert "42" not in cleared.get("parser_list_by_chat", {})
    assert "42" not in cleared.get("parser_by_chat", {})


def test_load_active_list_salta_nomi_non_caricabili(tmp_path):
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    cfg = _cfg_list("42", ["A", "MANCANTE", "A"])              # "MANCANTE" non esiste; "A" duplicato
    defns = parser_manager.load_active_list(cfg, "42", str(tmp_path))
    assert [d.name for d in defns] == ["A"]                    # solo i caricabili, deduplicati


# ── signal_router: routing multi-parser end-to-end ────────────────────────────

def test_multi_parser_solo_quello_che_combacia_scatta(tmp_path):
    # A combacia ("GG" nella fixture), B no ("ZZZ") → scatta solo A → una riga (legacy single).
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    _mk(str(tmp_path), "B", [cp.Condition(text="ZZZ_ASSENTE")],
        market_type="OVER_UNDER_25", selection_name="Over 2.5")
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg_list("42", ["A", "B"]),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert len(res.all_rows()) == 1
    assert res.all_rows()[0]["MarketType"] == "BOTH_TEAMS_TO_SCORE"   # la riga di A


def test_multi_parser_all_match_unisce_righe_diverse(tmp_path):
    # A e B combaciano entrambi (GG e BACK nella fixture) e producono righe DIVERSE →
    # entrambe presenti, in ordine di priorità (A prima di B). «Tutti quelli che combaciano».
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    _mk(str(tmp_path), "B", [cp.Condition(text="BACK")],
        market_type="OVER_UNDER_25", selection_name="Over 2.5")
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg_list("42", ["A", "B"]),
                                    chat_id="42", parsers_dir=str(tmp_path))
    rows = res.all_rows()
    assert res.placeable is True
    assert len(rows) == 2
    assert [r["MarketType"] for r in rows] == ["BOTH_TEAMS_TO_SCORE", "OVER_UNDER_25"]  # ordine
    assert res.rows is not None                                       # provenienza multi (dedup per-riga)


def test_multi_parser_righe_identiche_deduplicate_no_doppia_scommessa(tmp_path):
    # A e B IDENTICI (stessa riga) e combaciano entrambi → UNA sola riga (no doppia scommessa
    # accidentale). Invariante di sicurezza chiave del routing all-match.
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    _mk(str(tmp_path), "B", [cp.Condition(text="BACK")])              # stessa riga di A
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg_list("42", ["A", "B"]),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert len(res.all_rows()) == 1                                   # riga identica → deduplicata


def test_multi_parser_nessuno_combacia_scarta(tmp_path):
    # Né A né B combaciano → NO_CONTENT_MATCH, nessuna riga.
    _mk(str(tmp_path), "A", [cp.Condition(text="ZZZ")])
    _mk(str(tmp_path), "B", [cp.Condition(text="WWW")],
        market_type="OVER_UNDER_25", selection_name="Over 2.5")
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg_list("42", ["A", "B"]),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.status == signal_router.NO_CONTENT_MATCH
    assert res.placeable is False
    assert res.all_rows() == []


def test_single_parser_via_lista_resta_legacy_single_row(tmp_path):
    # Un SOLO parser single-row nella lista → RouteResult legacy (rows=None), identico a prima.
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg_list("42", ["A"]),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.rows is None                                           # provenienza single legacy
    assert res.row["MarketType"] == "BOTH_TEAMS_TO_SCORE"


def test_multi_parser_ordine_priorita_rispettato(tmp_path):
    # Invertendo l'ordine in config, cambia l'ordine delle righe generate.
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    _mk(str(tmp_path), "B", [cp.Condition(text="BACK")],
        market_type="OVER_UNDER_25", selection_name="Over 2.5")
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg_list("42", ["B", "A"]),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert [r["MarketType"] for r in res.all_rows()] == ["OVER_UNDER_25", "BOTH_TEAMS_TO_SCORE"]


# ── invarianti di sicurezza: filtro chat non indebolito ───────────────────────

def test_chat_solo_in_lista_e_approvata_e_ammessa():
    # Una chat presente SOLO in parser_list_by_chat (config a mano, senza parser_by_chat) è
    # comunque approvata e ammessa (robustezza), ma nessuna ALTRA chat lo diventa.
    cfg = {"parser_list_by_chat": {"42": ["A", "B"]}}
    assert signal_router._chat_approved_for_custom(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert "42" in signal_router.allowed_chats(cfg)
    assert signal_router.has_chat_filter(cfg) is True                 # NON "ammetti tutte"
    assert signal_router.is_chat_allowed(cfg, "999") is False         # altra chat non ammessa
    assert signal_router.has_active_parser_config(cfg) is True


def test_chat_non_in_lista_non_processata(tmp_path):
    # La lista è per la chat "42"; un messaggio dalla chat "999" non è processato.
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    cfg = _cfg_list("42", ["A"])
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="999", parsers_dir=str(tmp_path))
    assert res.placeable is False
    assert res.source == signal_router.NO_PARSER


def test_dedup_e_su_riga_completa_non_solo_mercato(tmp_path):
    # Nota GLM #391 (safety, doppia-scommessa): la dedup è sulla RIGA COMPLETA (tutti i campi),
    # NON solo sul mercato. Due parser che producono lo STESSO mercato ma SELEZIONE diversa sono
    # due bet distinti → entrambe le righe restano (non deduplicate).
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")],
        market_type="OVER_UNDER_25", selection_name="Over 2.5")
    _mk(str(tmp_path), "B", [cp.Condition(text="BACK")],
        market_type="OVER_UNDER_25", selection_name="Under 2.5")
    res = signal_router.resolve_row(parser_io.fixture_message(), _cfg_list("42", ["A", "B"]),
                                    chat_id="42", parsers_dir=str(tmp_path))
    rows = res.all_rows()
    assert len(rows) == 2                                             # stesso mercato, selezioni diverse
    assert all(r["MarketType"] == "OVER_UNDER_25" for r in rows)
    assert {r["SelectionName"] for r in rows} == {"Over 2.5", "Under 2.5"}


def test_set_for_chat_rimuove_lista_multi_stantia():
    # Codex #391 P2: tornare a UN solo parser (o azzerare) via set_for_chat deve RIMUOVERE la
    # lista multi stantia, che altrimenti vincerebbe in resolve_parser_names (precedenza lista).
    cfg = {"parser_list_by_chat": {"42": ["A", "B"]}, "parser_by_chat": {"42": "A"}}
    out = parser_manager.set_for_chat(cfg, "42", "C")
    assert "42" not in out.get("parser_list_by_chat", {})           # lista stantia rimossa
    assert out["parser_by_chat"]["42"] == "C"
    assert parser_manager.resolve_parser_names(out, "42") == ["C"]  # ora routing su C, non ["A","B"]
    # azzerando il singolo, sparisce tutto per la chat
    cleared = parser_manager.set_for_chat(cfg, "42", "")
    assert "42" not in cleared.get("parser_list_by_chat", {})
    assert "42" not in cleared.get("parser_by_chat", {})
    assert parser_manager.resolve_parser_names(cleared, "42") == []


def test_gate_condizioni_prima_della_diagnostica_validazione(tmp_path):
    # CodeRabbit #391: se le condizioni NON combaciano, il motivo è NO_CONTENT_MATCH — non un
    # errore di validazione (campi mancanti) su un messaggio che il parser non doveva gestire.
    _mk(str(tmp_path), "A", [cp.Condition(text="ZZZ_ASSENTE")])
    msg = "Match: Inter v Milan\nEsito: GG\nLato: BACK"        # manca "Quota:" → Price mancante
    res = signal_router.resolve_row(msg, _cfg_list("42", ["A"]), chat_id="42",
                                    parsers_dir=str(tmp_path))
    assert res.status == signal_router.NO_CONTENT_MATCH        # non uno status di validazione
    assert res.placeable is False


def test_condizioni_ok_ma_campo_mancante_mantiene_diagnostica(tmp_path):
    # Controprova: condizioni soddisfatte ("GG" c'è) ma Price mancante → resta la diagnostica di
    # validazione (NON NO_CONTENT_MATCH): il parser DOVEVA gestirlo, va detto cosa manca.
    _mk(str(tmp_path), "A", [cp.Condition(text="GG")])
    msg = "Match: Inter v Milan\nEsito: GG\nLato: BACK"        # "GG" presente, ma manca Quota
    res = signal_router.resolve_row(msg, _cfg_list("42", ["A"]), chat_id="42",
                                    parsers_dir=str(tmp_path))
    assert res.placeable is False
    assert res.status != signal_router.NO_CONTENT_MATCH        # diagnostica di validazione preservata


def test_set_for_chat_e_set_list_non_mutano_input():
    # Fable/GLM/Fugu #391: gli helper non mutano la cfg di input (i getter ritornano copie nuove).
    import copy
    cfg = {"parser_list_by_chat": {"42": ["A", "B"]}, "parser_by_chat": {"42": "A"}}
    snapshot = copy.deepcopy(cfg)
    parser_manager.set_for_chat(cfg, "42", "C")
    parser_manager.set_list_for_chat(cfg, "42", ["X", "Y"])
    assert cfg == snapshot                                    # input invariato (nessun aliasing)


def test_set_list_for_chat_sovrascrive_primario_preesistente():
    # GLM #391: con un parser_by_chat preesistente, set_list_for_chat sovrascrive il primario col
    # primo della nuova lista, senza residui.
    out = parser_manager.set_list_for_chat({"parser_by_chat": {"42": "OLD"}}, "42", ["A", "B"])
    assert out["parser_by_chat"]["42"] == "A"                 # primario = primo nuovo
    assert out["parser_list_by_chat"]["42"] == ["A", "B"]


def test_allowed_chats_fail_fast_esclude_disattivata_include_solo_lista():
    # Fable #391: il fail-fast chat-notifiche usa allowed_chats. Una sorgente DISATTIVATA non è
    # processata → NON in allowed_chats (correttamente non un conflitto); una chat solo-in-lista sì.
    cfg = {"source_chats": [{"chat_id": "111", "enabled": False, "mode": "PRE"}],
           "parser_list_by_chat": {"222": ["P"]}}
    allowed = signal_router.allowed_chats(cfg)
    assert "111" not in allowed                               # disattivata → non ammessa
    assert "222" in allowed                                   # solo-in-lista → il fail-fast la vede


def test_allowed_chats_disattivata_vince_anche_su_parser_list_by_chat():
    # CodeRabbit #391 (sicurezza filtro chat): se la STESSA chat è sia DISATTIVATA in source_chats
    # sia presente in parser_list_by_chat, la deny-list deve vincere su ENTRAMBE le mappe (non solo
    # su parser_by_chat). Altrimenti una chat disattivata resterebbe processabile via la lista
    # multi → buco nel filtro chat.
    cfg = {"source_chats": [{"chat_id": "333", "enabled": False, "mode": "PRE"}],
           "parser_list_by_chat": {"333": ["P"]}}
    allowed = signal_router.allowed_chats(cfg)
    assert "333" not in allowed                               # deny-list vince sulla lista multi
    assert signal_router.is_chat_allowed(cfg, "333") is False  # e non è processata
