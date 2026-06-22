"""Test dell'instradamento del segnale (CP-09): custom attivo vs hardcoded."""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_io, signal_router


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


def test_custom_fixed_con_estrazione_attiva_scrive_solo_se_match(tmp_path):
    # Obbligatori tutti fissi (riga sempre piazzabile) + un'estrazione OPZIONALE:
    # è il gate di contenuto a decidere. La riga si scrive SOLO se il messaggio
    # contiene il delimitatore dell'estrazione opzionale (contenuto che attiva
    # davvero il parser); altrimenti → NO_CONTENT_MATCH, niente scrittura.
    defn = cp.CustomParserDef(name="FissiPiuEstrazione", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="BOTH_TEAMS_TO_SCORE", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Sì", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        cp.FieldRule(target="MarketName", start_after="Mkt:", end_before="\n"),  # opzionale
    ])
    cp.save_parser(defn, str(tmp_path))
    cfg = {"provider": "TG", "active_parser": "FissiPiuEstrazione", "chat_id": "42",
           "recognition_mode": "NAME_ONLY"}
    # messaggio con il delimitatore "Mkt:" → estrazione opzionale attiva → piazzabile
    ok = signal_router.resolve_row("Mkt: 1X2\n", cfg,
                                   chat_id="42", parsers_dir=str(tmp_path))
    assert ok.source == signal_router.CUSTOM
    assert ok.placeable is True
    assert ok.row["EventName"] == "Inter v Milan"
    # messaggio senza "Mkt:" → nessuna estrazione attivata → scartato dal gate
    ko = signal_router.resolve_row("messaggio qualsiasi", cfg,
                                   chat_id="42", parsers_dir=str(tmp_path))
    assert ko.source == signal_router.CUSTOM
    assert ko.placeable is False
    assert ko.status == signal_router.NO_CONTENT_MATCH


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
