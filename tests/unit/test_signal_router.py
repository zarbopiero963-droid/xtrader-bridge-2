"""Test dell'instradamento del segnale (CP-09): custom attivo vs hardcoded."""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline, parser_io, signal_router


def _save_example(dir_path, name="Esempio P.Bet."):
    defn = parser_io.example_parser()
    defn.name = name
    return cp.save_parser(defn, dir_path)


# ── nessun custom attivo: parser automatico DISATTIVATO (CP-09b) ─────────────

def test_nessun_custom_ignora_il_messaggio():
    # Config senza active_parser → nessun parser custom → il messaggio è ignorato
    # (parser automatico P.Bet disattivato), anche un P.Bet. perfettamente valido.
    cfg = {"provider": "TG", "recognition_mode": "NAME_ONLY"}
    text = ("🔔 P.Bet.\nYangon City v Rakhine\nMercato: 1X2\nEsito: 1\n"
            "Quota 1,85\nProbabilità 72%")
    res = signal_router.resolve_row(text, cfg)
    assert res.source == signal_router.NO_PARSER
    assert res.status == signal_router.NO_PARSER
    assert res.placeable is False


def test_senza_custom_scarta_messaggio_non_valido():
    cfg = {"provider": "TG", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row("ciao non sono un segnale", cfg)
    assert res.source == signal_router.NO_PARSER
    assert res.placeable is False


# ── custom attivo (autoritativo) ────────────────────────────────────────────

def test_custom_attivo_produce_riga(tmp_path):
    _save_example(str(tmp_path), "Yangon")
    # chat_id configurato e combaciante: chat approvata per il custom globale.
    cfg = {"provider": "TG", "active_parser": "Yangon", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
    assert res.row["SelectionName"] == "Sì"
    assert res.row["BetType"] == "PUNTA"
    assert res.row["Price"] == "1.85"


def test_custom_attivo_non_pronto_scarta_senza_fallback(tmp_path):
    # Custom attivo ma messaggio incompleto: scarto, NON si ripiega sull'hardcoded.
    _save_example(str(tmp_path), "Yangon")
    cfg = {"provider": "TG", "active_parser": "Yangon", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row("Match: solo questo", cfg,
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is False


def test_chat_non_approvata_non_usa_parser_globale(tmp_path):
    # active_parser globale ma chat_id vuoto: una chat arbitraria NON deve usare
    # il parser globale (sicurezza: niente scommesse per chat non approvate). Senza
    # parser approvato il messaggio è ignorato (parser automatico disattivato).
    _save_example(str(tmp_path), "Yangon")
    cfg = {"provider": "TG", "active_parser": "Yangon", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="999", parsers_dir=str(tmp_path))
    assert res.source == signal_router.NO_PARSER
    assert res.placeable is False


def _mapping_parser(name="Map", profiles=("Premier",), separator="v"):
    return cp.CustomParserDef(
        name=name, mode="NAME_ONLY",
        name_mapping_profiles=list(profiles), team_separator=separator,
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
            cp.FieldRule(target="SelectionName", start_after="Sel:", end_before="\n", required=True),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype", required=True),
        ])


_MAP_MSG = "Match: Liverpool FC v Leeds Utd\nSel: Sì\nQuota: 1,85\nLato: BACK"


def _map_cfg(name="Map"):
    return {"provider": "TG", "active_parser": name, "chat_id": "42",
            "recognition_mode": "NAME_ONLY",
            "name_mappings": {"Premier": [
                {"betfair": "Liverpool", "provider": "Liverpool FC"},
                {"betfair": "Leeds", "provider": "Leeds Utd"},
            ]}}


def test_router_traduce_eventname_coi_profili(tmp_path):
    cp.save_parser(_mapping_parser(), str(tmp_path))
    res = signal_router.resolve_row(_MAP_MSG, _map_cfg(),
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
    assert res.row["EventName"] == "Liverpool - Leeds"   # nomi provider → Betfair/XTrader


def test_router_scarta_se_squadra_non_mappata(tmp_path):
    cp.save_parser(_mapping_parser(), str(tmp_path))
    msg = "Match: Liverpool FC v Arsenal\nSel: Sì\nQuota: 1,85\nLato: BACK"
    res = signal_router.resolve_row(msg, _map_cfg(), chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is False                        # fail-closed: niente riga CSV
    assert res.status == custom_pipeline.MAPPING_MISSING


def test_custom_solo_fixed_non_scrive_su_messaggio_arbitrario(tmp_path):
    # Parser con TUTTI gli obbligatori a fixed_value: build_validated_row sarebbe
    # piazzabile su qualsiasi testo. Il gate di contenuto lo scarta: senza
    # estrazione dal messaggio non è un segnale → niente riga (anti doppia scommessa).
    defn = cp.CustomParserDef(name="SoloFissi", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ])
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "SoloFissi", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    # messaggio non pertinente e messaggio vuoto: entrambi scartati, NON piazzabili.
    for text in ("ciao come stai", ""):
        res = signal_router.resolve_row(text, cfg, chat_id="42", parsers_dir=str(tmp_path))
        assert res.source == signal_router.CUSTOM
        assert res.placeable is False
        assert res.status == signal_router.NO_CONTENT_MATCH


def test_custom_estrazione_opzionale_non_basta_serve_obbligatoria(tmp_path):
    # A10: campi scommessa tutti FISSI + un'estrazione OPZIONALE NON deve rendere
    # piazzabile un messaggio che attiva solo quell'opzionale (anti-bet-spurio). Serve
    # un'estrazione OBBLIGATORIA come gate di contenuto.
    base = [
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ]
    cfg = {"provider": "TG", "active_parser": "P", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}

    # (a) estrazione OPZIONALE: anche col delimitatore presente → scartato dal gate (A10).
    opt = cp.CustomParserDef(name="P", rules=[
        *base, cp.FieldRule(target="MarketName", start_after="Mkt:", end_before="\n")])
    cp.save_parser(opt, str(tmp_path))
    res = signal_router.resolve_row("Mkt: 1X2\n", cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is False
    assert res.status == signal_router.NO_CONTENT_MATCH

    # (b) la STESSA estrazione resa OBBLIGATORIA diventa il gate: scrive col delimitatore,
    # scarta senza (è il contenuto vero del segnale a decidere).
    req = cp.CustomParserDef(name="P", rules=[
        *base, cp.FieldRule(target="MarketName", start_after="Mkt:", end_before="\n", required=True)])
    cp.save_parser(req, str(tmp_path))
    ok = signal_router.resolve_row("Mkt: 1X2\n", cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert ok.placeable is True
    assert ok.row["EventName"] == "Inter v Milan"
    ko = signal_router.resolve_row("messaggio qualsiasi", cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert ko.placeable is False                      # MarketName obbligatorio vuoto + gate


def test_quota_governata_dalla_riga_price_del_parser(tmp_path):
    # Unico comando della quota: il gate require_price è guidato dalla riga Price del
    # parser (price_required), NON più da una chiave globale di config.
    base = [
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
    ]
    cfg = {"provider": "TG", "active_parser": "Q", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    msg = "Match: Inter v Milan\n"            # nessuna quota nel messaggio

    # (a) Price NON obbligatorio → quota opzionale: scrive la riga col Price vuoto.
    opt = cp.CustomParserDef(name="Q", mode="NAME_ONLY", rules=[
        *base, cp.FieldRule(target="Price", start_after="Quota:", end_before="\n")])
    cp.save_parser(opt, str(tmp_path))
    res = signal_router.resolve_row(msg, cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert res.placeable is True
    assert res.row["Price"] == ""

    # (b) STESSO parser con Price OBBLIGATORIO → quota richiesta: senza quota è scartato.
    req = cp.CustomParserDef(name="Q", mode="NAME_ONLY", rules=[
        *base, cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True)])
    cp.save_parser(req, str(tmp_path))
    ko = signal_router.resolve_row(msg, cfg, chat_id="42", parsers_dir=str(tmp_path))
    assert ko.placeable is False
    # Scartato proprio per la quota mancante (Price obbligatorio vuoto), non per altro.
    assert ko.status == custom_pipeline.NOT_READY
    assert "Price" in ko.missing_required


def test_custom_inesistente_ignora_il_messaggio(tmp_path):
    # active_parser punta a un parser non salvato → load_active None → nessun parser
    # custom → messaggio ignorato (niente fallback automatico).
    cfg = {"provider": "TG", "active_parser": "NonEsiste", "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row("qualsiasi", cfg, parsers_dir=str(tmp_path))
    assert res.source == signal_router.NO_PARSER
    assert res.placeable is False


def test_has_active_parser_config():
    # Codex P2: rileva se è configurato almeno un parser (per l'avviso di avvio).
    assert signal_router.has_active_parser_config({}) is False
    assert signal_router.has_active_parser_config({"chat_id": "42"}) is False  # chat, ma 0 parser
    assert signal_router.has_active_parser_config({"active_parser": "X"}) is True
    assert signal_router.has_active_parser_config(
        {"active_parser": "   "}) is False                                     # solo spazi → vuoto
    assert signal_router.has_active_parser_config(
        {"parser_by_chat": {"1": "X"}}) is True
    assert signal_router.has_active_parser_config(
        {"parser_by_chat": {"1": ""}}) is False                                # override vuoto


def test_parser_configurato_ma_mancante_non_sparisce_in_silenzio(tmp_path):
    # Codex P2: una chat APPROVATA con un parser CONFIGURATO il cui file è mancante
    # non deve far sparire i segnali senza traccia. should_process resta True (così
    # resolve_row gira) e resolve_row segnala il fallimento col nome del parser, invece
    # di un drop silenzioso prima del log.
    cfg = {"provider": "TG", "active_parser": "Mancante", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    assert signal_router.should_process(
        cfg, "42", "qualsiasi", parsers_dir=str(tmp_path)) is True
    res = signal_router.resolve_row("qualsiasi", cfg, chat_id="42",
                                    parsers_dir=str(tmp_path))
    assert res.source == signal_router.NO_PARSER
    assert res.placeable is False
    assert "Mancante" in str(res.detail)


def test_chat_id_esplicito_attiva_override(tmp_path):
    # parser_by_chat senza chat_id singolo in config: il chat id del messaggio
    # (passato esplicitamente, come fa il live) attiva l'override per-chat.
    _save_example(str(tmp_path), "PerChat")
    cfg = {"provider": "TG", "parser_by_chat": {"123": "PerChat"},
           "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="123", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True
    # senza chat id → nessun override → nessun parser → messaggio ignorato
    res2 = signal_router.resolve_row("qualsiasi", cfg, parsers_dir=str(tmp_path))
    assert res2.source == signal_router.NO_PARSER
    assert res2.placeable is False


def test_override_per_chat(tmp_path):
    _save_example(str(tmp_path), "PerChat")
    cfg = {"provider": "TG", "chat_id": "123",
           "parser_by_chat": {"123": "PerChat"}, "recognition_mode": "NAME_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg, parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is True


# ── is_chat_allowed: guardia unica live (CP-09) ─────────────────────────────

def test_is_chat_allowed_nulla_configurato_tutte_ammesse():
    # Nessun chat_id e nessuna mappa → comportamento legacy: tutte ammesse.
    cfg = {"provider": "TG"}
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "999") is True


def test_is_chat_allowed_solo_chat_configurata():
    # chat_id impostato → solo quella chat è ammessa.
    cfg = {"provider": "TG", "chat_id": "42"}
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "999") is False


def test_is_chat_allowed_override_per_chat_ammesso_anche_con_chat_id():
    # Con chat_id singolo impostato, le voci parser_by_chat restano ammesse
    # (l'override per-chat non deve essere bloccato dalla guardia).
    cfg = {"provider": "TG", "chat_id": "42",
           "parser_by_chat": {"123": "PerChat"}}
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "123") is True
    assert signal_router.is_chat_allowed(cfg, "999") is False


def test_is_chat_allowed_solo_mappa_per_chat():
    # Solo parser_by_chat (nessun chat_id): ammesse solo le chat mappate.
    cfg = {"provider": "TG", "parser_by_chat": {"123": "PerChat"}}
    assert signal_router.is_chat_allowed(cfg, "123") is True
    assert signal_router.is_chat_allowed(cfg, "42") is False


def test_is_chat_allowed_strip_simmetrico_sul_chat_runtime():
    """#184 M2: il chat in ingresso va confrontato in modo SIMMETRICO all'allowlist
    (`allowed_chats` strippa l'ID configurato). Un chat con whitespace/newline ai bordi
    (es. una sorgente che lo formatta con padding) deve comunque matchare la chat
    configurata — prima era confrontato grezzo e veniva scartato (fail-closed, non un
    bypass). Stesso confronto di `is_notification_chat`.

    Fail-first: sul vecchio `is_chat_allowed` (`str(chat or "")` senza `.strip()`) un chat
    con padding NON matchava la chat ammessa."""
    cfg = {"provider": "TG", "chat_id": "42"}
    assert signal_router.is_chat_allowed(cfg, " 42 ") is True       # padding ai bordi → match
    assert signal_router.is_chat_allowed(cfg, "\t42\n") is True     # tab/newline → match
    # Lo strip NON è un over-admit: un altro chat resta NON ammesso.
    assert signal_router.is_chat_allowed(cfg, " 999 ") is False
    # Né un chat di SOLI whitespace diventa ammesso (strip → "" non è in nessuna allowlist):
    # niente percorso "admit-all" mascherato dallo strip (review Sourcery).
    assert signal_router.is_chat_allowed(cfg, "   \n\t") is False
    # Coerenza con la mappa per-chat: anche una chiave parser_by_chat matcha con padding.
    cfg2 = {"provider": "TG", "parser_by_chat": {"123": "PerChat"}}
    assert signal_router.is_chat_allowed(cfg2, "  123  ") is True
    assert signal_router.is_chat_allowed(cfg2, "  124  ") is False


def test_should_process_chat_con_padding_passa_tutto_il_gate_live():
    """#184 M2 (Codex P2): la normalizzazione del chat runtime deve valere per TUTTO il gate
    live, non solo `is_chat_allowed`. `should_process` chiama anche `_chat_approved_for_custom`:
    se restasse grezzo, una chat ammessa con padding (`" 42 "`) sarebbe approvata da
    `is_chat_allowed` ma scartata dall'approvazione custom → `should_process` False
    (IGNORE_NOT_RELEVANT), lasciando il fix M2 monco.

    Fail-first: con `_chat_approved_for_custom` ancora grezzo, `should_process(cfg, " 42 ", …)`
    ritorna False nonostante `is_chat_allowed` sia True."""
    cfg = {"provider": "TG", "chat_id": "42", "active_parser": "MioParser"}
    assert signal_router.should_process(cfg, "42", "msg") is True        # baseline senza padding
    assert signal_router.should_process(cfg, " 42 ", "msg") is True      # con padding → ancora processata
    assert signal_router.should_process(cfg, "\t42\n", "msg") is True    # tab/newline → idem
    # Fail-closed preservato: un chat diverso (anche con padding) NON viene processato.
    assert signal_router.should_process(cfg, " 99 ", "msg") is False


def test_chat_approved_for_custom_strip_simmetrico_su_parser_by_chat_e_denylist():
    """#184 M2 (Codex P2): `_chat_approved_for_custom` normalizza il chat runtime per i lookup
    `parser_by_chat`/sorgenti e la deny-list. Una chat con padding che mappa un parser per-chat
    è approvata; una sorgente disattivata resta negata anche con padding."""
    cfg = {"provider": "TG", "parser_by_chat": {"123": "PerChat"}}
    assert signal_router._chat_approved_for_custom(cfg, "  123  ") is True
    assert signal_router._chat_approved_for_custom(cfg, "  124  ") is False
    # Deny-list sorgenti: una sorgente DISATTIVATA non è approvata, neanche con padding.
    cfg_dis = {"provider": "TG",
               "source_chats": [{"name": "S", "chat_id": "555", "enabled": False}]}
    assert signal_router._chat_approved_for_custom(cfg_dis, " 555 ") is False


# ── multi-chat (PR-24): source_chats attive ammesse, disattivate ignorate ────

def test_is_chat_allowed_sorgenti_multichat():
    cfg = {"source_chats": [
        {"chat_id": "111", "enabled": True,  "mode": "PRE"},
        {"chat_id": "222", "enabled": False, "mode": "LIVE"},   # disattivata
    ]}
    assert signal_router.is_chat_allowed(cfg, "111") is True    # attiva → ammessa
    assert signal_router.is_chat_allowed(cfg, "222") is False   # disattivata → no
    assert signal_router.is_chat_allowed(cfg, "999") is False   # non configurata → no


def test_provider_sorgente_vince_su_parser_custom(tmp_path):
    # PR-24 (finding Codex): per una chat che è una SORGENTE attiva, il provider
    # della sorgente (qui mode LIVE → TG_LIVE) VINCE sul Provider fisso del parser
    # custom (l'esempio fissa TG_CUSTOM). Per una chat NON-sorgente il Provider
    # del parser resta invariato.
    _save_example(str(tmp_path), "Esempio P.Bet.")
    cfg = {"provider": "GLOBAL",
           "parser_by_chat": {"111": "Esempio P.Bet.", "222": "Esempio P.Bet."},
           "source_chats": [{"chat_id": "111", "enabled": True, "mode": "LIVE"}]}
    msg = parser_io.fixture_message()
    r_src = signal_router.resolve_row(msg, cfg, chat_id="111", parsers_dir=str(tmp_path))
    assert r_src.placeable and r_src.row["Provider"] == "TG_LIVE"      # sorgente vince
    r_nosrc = signal_router.resolve_row(msg, cfg, chat_id="222", parsers_dir=str(tmp_path))
    assert r_nosrc.placeable and r_nosrc.row["Provider"] == "TG_CUSTOM"  # parser resta


def test_sorgente_attiva_approvata_per_parser_globale(tmp_path):
    # Setup source_chats-only con active_parser GLOBALE: una sorgente attiva è
    # approvata per il custom (non cade sull'hardcoded perdendo i messaggi custom).
    _save_example(str(tmp_path), "Glob")
    cfg = {"provider": "GLOBAL", "active_parser": "Glob",
           "source_chats": [{"chat_id": "111", "enabled": True, "mode": "LIVE"}]}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="111", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM and res.placeable is True
    # una chat NON sorgente non è approvata per il custom globale
    assert signal_router.active_custom_parser(cfg, "999", str(tmp_path)) is None


def test_sorgente_disattivata_e_denylist_anche_con_override():
    # Una sorgente disattivata NON deve essere riammessa da un parser_by_chat o da
    # un chat_id coincidente: disattivarla la ferma davvero (deny-list, Codex P1).
    cfg = {"chat_id": "111", "parser_by_chat": {"111": "X"},
           "source_chats": [{"chat_id": "111", "enabled": False}]}
    assert signal_router.is_chat_allowed(cfg, "111") is False
    assert signal_router.active_custom_parser(cfg, "111") is None


def test_is_chat_allowed_sole_sorgenti_disattivate_blocca_tutte():
    # Sorgenti configurate ma tutte disattivate (nessun chat_id/parser_by_chat):
    # NON si torna a "ammetti tutte" — disattivarle blocca ogni chat.
    cfg = {"source_chats": [{"chat_id": "111", "enabled": False}]}
    assert signal_router.is_chat_allowed(cfg, "111") is False
    assert signal_router.is_chat_allowed(cfg, "999") is False


def test_is_chat_allowed_union_chatid_e_sorgenti():
    # chat_id globale + una sorgente attiva: ammesse entrambe (retro-compatibile).
    cfg = {"chat_id": "42", "source_chats": [{"chat_id": "111", "enabled": True}]}
    assert signal_router.is_chat_allowed(cfg, "42") is True
    assert signal_router.is_chat_allowed(cfg, "111") is True
    assert signal_router.is_chat_allowed(cfg, "999") is False


def test_has_chat_filter_config_vuota_e_falso():
    # PR-25: nessun criterio di ammissione → has_chat_filter False (e is_chat_allowed
    # ammetterebbe TUTTE le chat). app._start blocca l'avvio in questo caso.
    assert signal_router.has_chat_filter({}) is False
    assert signal_router.has_chat_filter({"chat_id": "", "parser_by_chat": {},
                                          "source_chats": []}) is False
    assert signal_router.is_chat_allowed({}, "qualsiasi") is True  # coerenza: aperto


def test_has_chat_filter_vero_con_chatid_parser_o_sorgente():
    # Basta UNO dei tre criteri (anche una sorgente DISATTIVATA) per attivare il filtro.
    assert signal_router.has_chat_filter({"chat_id": "42"}) is True
    assert signal_router.has_chat_filter({"parser_by_chat": {"111": "X"}}) is True
    assert signal_router.has_chat_filter(
        {"source_chats": [{"chat_id": "111", "enabled": False}]}) is True


# ── allowed_chats: allowlist esplicita (A2, modello "solo queste chat") ──────

def test_allowed_chats_unione_chatid_parser_sorgenti_attive():
    cfg = {"chat_id": "42",
           "parser_by_chat": {"123": "PerChat"},
           "source_chats": [
               {"chat_id": "111", "enabled": True},
               {"chat_id": "222", "enabled": False},   # disattivata → esclusa
           ]}
    assert signal_router.allowed_chats(cfg) == {"42", "123", "111"}


def test_allowed_chats_sorgente_disattivata_e_denylist():
    # La sorgente disattivata vince su chat_id/parser_by_chat coincidenti → esclusa.
    cfg = {"chat_id": "111", "parser_by_chat": {"111": "X"},
           "source_chats": [{"chat_id": "111", "enabled": False}]}
    assert signal_router.allowed_chats(cfg) == set()


def test_allowed_chats_vuoto_se_nulla_configurato():
    # Senza criteri l'allowlist è vuota (NON significa "tutte": vedi has_chat_filter).
    assert signal_router.allowed_chats({}) == set()
    assert signal_router.has_chat_filter({}) is False


def test_allowed_chats_normalizza_chiavi_non_stringa():
    # bug_risk (Sourcery): una chiave parser_by_chat int non deve dare mismatch con
    # il confronto str(chat) di is_chat_allowed → normalizzata a str nell'allowlist.
    cfg = {"parser_by_chat": {123: "PerChat"}}
    assert signal_router.allowed_chats(cfg) == {"123"}
    assert signal_router.is_chat_allowed(cfg, "123") is True
    assert signal_router.is_chat_allowed(cfg, "999") is False


def test_listened_chats_nomi_da_source_chats_e_ordine():
    # Vista leggibile (B1): nome da source_chats quando c'è, altrimenti ""; i nomi
    # vuoti vanno in fondo, gli altri ordinati case-insensitive per nome.
    cfg = {"chat_id": "42",
           "source_chats": [
               {"chat_id": "111", "enabled": True, "name": "Zeta Tips"},
               {"chat_id": "222", "enabled": True, "name": "alfa tips"},
               {"chat_id": "333", "enabled": False, "name": "Disattivata"},  # esclusa
           ]}
    rows = signal_router.listened_chats(cfg)
    assert rows == [
        {"chat_id": "222", "name": "alfa tips"},
        {"chat_id": "111", "name": "Zeta Tips"},
        {"chat_id": "42", "name": ""},          # senza nome → in fondo
    ]


def test_listened_chats_tiebreak_nome_uguale_case_e_senza_nome():
    # Nomi uguali a meno del case → tiebreak per chat_id; due chat senza nome →
    # ordinate per chat_id e sempre DOPO quelle con nome.
    cfg = {"parser_by_chat": {"900": "X", "800": "Y"},          # senza nome
           "source_chats": [
               {"chat_id": "111", "enabled": True, "name": "Tips"},
               {"chat_id": "222", "enabled": True, "name": "tips"},   # stesso nome, case diverso
           ]}
    assert signal_router.listened_chats(cfg) == [
        {"chat_id": "111", "name": "Tips"},
        {"chat_id": "222", "name": "tips"},
        {"chat_id": "800", "name": ""},
        {"chat_id": "900", "name": ""},
    ]


def test_listened_chats_coerente_con_allowed_chats():
    # L'insieme degli ID mostrati == allowed_chats (nessuna chat in più o in meno).
    cfg = {"chat_id": "42",
           "parser_by_chat": {"123": "X"},
           "source_chats": [{"chat_id": "111", "enabled": True, "name": "A"},
                            {"chat_id": "222", "enabled": False, "name": "B"}]}
    ids = {r["chat_id"] for r in signal_router.listened_chats(cfg)}
    assert ids == signal_router.allowed_chats(cfg) == {"42", "123", "111"}


def test_listened_chats_vuoto_se_niente_configurato():
    assert signal_router.listened_chats({}) == []


def test_allowed_chats_coerente_con_is_chat_allowed():
    # Invariante: con un filtro attivo, is_chat_allowed(cfg, c) ⇔ c ∈ allowed_chats(cfg).
    cfg = {"chat_id": "42",
           "parser_by_chat": {"123": "PerChat"},
           "source_chats": [
               {"chat_id": "111", "enabled": True},
               {"chat_id": "222", "enabled": False},
           ]}
    allow = signal_router.allowed_chats(cfg)
    for chat in ("42", "123", "111", "222", "999", ""):
        assert signal_router.is_chat_allowed(cfg, chat) is (chat in allow), chat


def test_resolve_row_provider_per_chat_da_modalita(tmp_path):
    # La riga di una sorgente LIVE (senza provider esplicito) usa TG_LIVE; una con
    # provider esplicito quello; una chat senza sorgente attiva usa il provider globale.
    # Si parte dal parser d'esempio SENZA la sua regola Provider, così il provider
    # per-chat (provider_for_chat) finisce davvero nella colonna Provider.
    defn = parser_io.example_parser()
    defn.name = "NoProv"
    defn.rules = [r for r in defn.rules if r.target != "Provider"]
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "GLOBAL",
           "parser_by_chat": {"111": "NoProv", "222": "NoProv", "333": "NoProv"},
           "source_chats": [
               {"chat_id": "111", "enabled": True, "mode": "LIVE"},
               {"chat_id": "222", "enabled": True, "mode": "PRE", "provider": "MioProv"},
           ]}
    msg = parser_io.fixture_message()
    r1 = signal_router.resolve_row(msg, cfg, chat_id="111", parsers_dir=str(tmp_path))
    assert r1.placeable and r1.row["Provider"] == "TG_LIVE"     # da modalità LIVE
    r2 = signal_router.resolve_row(msg, cfg, chat_id="222", parsers_dir=str(tmp_path))
    assert r2.placeable and r2.row["Provider"] == "MioProv"     # provider esplicito
    r3 = signal_router.resolve_row(msg, cfg, chat_id="333", parsers_dir=str(tmp_path))
    assert r3.placeable and r3.row["Provider"] == "GLOBAL"      # nessuna sorgente → globale


# ── should_process: gate di instradamento live (PR-11) ──────────────────────

def test_should_process_chat_non_ammessa_mai():
    # chat_id configurato: una chat diversa non viene mai processata, nemmeno
    # con un marker legacy valido (non si indebolisce il filtro chat).
    cfg = {"provider": "TG", "chat_id": "42"}
    assert signal_router.should_process(cfg, "999", "🔔 P.Bet. ...") is False


def test_should_process_senza_custom_mai():
    # chat ammessa ma nessun parser custom attivo: non si processa più nulla, nemmeno
    # con un marker legacy P.Bet./📊 (parser automatico disattivato, CP-09b).
    cfg = {"provider": "TG", "chat_id": "42"}
    assert signal_router.should_process(cfg, "42", "P.Bet. OVER 2.5") is False
    assert signal_router.should_process(cfg, "42", "📊 segnale") is False
    assert signal_router.should_process(cfg, "42", "messaggio qualsiasi") is False
    assert signal_router.should_process(cfg, "42", "") is False


def test_should_process_custom_attivo_passa_qualsiasi_testo(tmp_path):
    # chat approvata con custom attivo: ogni messaggio passa (i formati custom
    # non hanno i marker legacy), così non si scartano i loro segnali.
    _save_example(str(tmp_path), "Yangon")
    cfg = {"provider": "TG", "active_parser": "Yangon", "chat_id": "42"}
    assert signal_router.should_process(
        cfg, "42", "Match: Inter v Milan", parsers_dir=str(tmp_path)) is True


def test_should_process_senza_config_e_senza_custom_mai():
    # Nessun chat_id e nessuna mappa → tutte le chat ammesse (legacy), ma senza un
    # Parser Personalizzato attivo nulla viene processato (parser automatico off).
    cfg = {"provider": "TG"}
    assert signal_router.should_process(cfg, "777", "P.Bet. ...") is False
    assert signal_router.should_process(cfg, "777", "ciao") is False


def test_modalita_e_per_parser_non_globale(tmp_path):
    # PR-4: la Modalità è quella DEL PARSER, non `recognition_mode` globale. Un parser
    # ID_ONLY valida per ID: il fixture (solo nomi) → INVALID_MISSING_FIELDS anche se la
    # config globale dice NAME_ONLY.
    defn = parser_io.example_parser()
    defn.name = "PerId"
    defn.mode = "ID_ONLY"
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "PerId", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}        # globale diverso: deve essere ignorato
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.source == signal_router.CUSTOM
    assert res.placeable is False
    assert res.status == "INVALID_MISSING_FIELDS"   # mancano MarketId/SelectionId (ID_ONLY)


def test_parser_legacy_senza_mode_eredita_globale(tmp_path):
    # Codex P1: un parser salvato SENZA `mode` (file pre-feature) deve ereditare la
    # modalità globale `recognition_mode`, non essere forzato a NAME_ONLY. Qui il
    # parser (solo nomi) con globale ID_ONLY → scartato per ID mancanti (eredita ID_ONLY).
    defn = parser_io.example_parser()
    defn.name = "Legacy"
    defn.mode = ""                                  # non impostata = file legacy
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "Legacy", "chat_id": "42",
           "recognition_mode": "ID_ONLY"}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    chat_id="42", parsers_dir=str(tmp_path))
    assert res.status == "INVALID_MISSING_FIELDS"   # eredita ID_ONLY dal globale
