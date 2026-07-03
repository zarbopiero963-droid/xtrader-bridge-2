"""Test del gestore multi-chat (PR-12): risoluzione provider/mode + validazione."""

from xtrader_bridge import source_manager as sm


def _cfg(*sources):
    return {"provider": "TelegramBot", "source_chats": list(sources)}


# ── normalizzazione ──────────────────────────────────────────────────────────

def test_normalizzazione_default():
    cfg = _cfg({"chat_id": "42"})
    s = sm.source_chats(cfg)[0]
    assert s["enabled"] is True          # attiva di default
    assert s["mode"] == "PRE"            # modalità di default
    assert s["provider"] == ""           # nessun provider esplicito
    assert s["chat_id"] == "42"


def test_normalize_mode():
    assert sm.normalize_mode("live") == "LIVE"
    assert sm.normalize_mode("  Pre ") == "PRE"
    assert sm.normalize_mode("boh") == "PRE"     # ignoto → default
    assert sm.normalize_mode(None) == "PRE"


def test_is_valid_mode():
    assert sm.is_valid_mode("LIVE") is True
    assert sm.is_valid_mode(" pre ") is True
    assert sm.is_valid_mode("boh") is False
    assert sm.is_valid_mode("") is False


def test_mode_provider_coerente_con_modes():
    # _MODE_PROVIDER è derivato da MODES: ogni modalità ha un provider TG_<MODE>,
    # così aggiungere una modalità non può desincronizzare la mappa.
    for mode in sm.MODES:
        cfg = _cfg({"chat_id": "1", "mode": mode})
        assert sm.provider_for_chat(cfg, "1") == "TG_" + mode


def test_source_chats_ritorna_copia():
    cfg = _cfg({"chat_id": "42"})
    sm.source_chats(cfg)[0]["chat_id"] = "999"
    assert cfg["source_chats"][0]["chat_id"] == "42"   # config non mutata


# ── provider per chat (PRE/LIVE) ─────────────────────────────────────────────

def test_provider_pre_e_live():
    cfg = _cfg({"chat_id": "1", "mode": "PRE"},
               {"chat_id": "2", "mode": "LIVE"})
    assert sm.provider_for_chat(cfg, "1") == "TG_PRE"
    assert sm.provider_for_chat(cfg, "2") == "TG_LIVE"


def test_provider_esplicito_ha_precedenza():
    cfg = _cfg({"chat_id": "1", "mode": "LIVE", "provider": "MioProvider"})
    assert sm.provider_for_chat(cfg, "1") == "MioProvider"


def test_provider_chat_sconosciuta_usa_default():
    cfg = _cfg({"chat_id": "1", "mode": "PRE"})
    assert sm.provider_for_chat(cfg, "999", default="TelegramBot") == "TelegramBot"


def test_due_chat_simultanee_nessun_conflitto():
    cfg = _cfg({"chat_id": "1", "mode": "PRE"},
               {"chat_id": "2", "mode": "LIVE", "provider": "X"})
    # ogni chat risolve indipendentemente il proprio provider
    assert sm.provider_for_chat(cfg, "1") == "TG_PRE"
    assert sm.provider_for_chat(cfg, "2") == "X"
    assert sm.enabled_chat_ids(cfg) == {"1", "2"}


# ── enabled / ignorata ───────────────────────────────────────────────────────

def test_sorgente_disattivata_ignorata():
    cfg = _cfg({"chat_id": "1", "enabled": False, "mode": "LIVE"})
    assert sm.source_for_chat(cfg, "1") is None
    assert sm.enabled_chat_ids(cfg) == set()
    # provider: nessuna sorgente attiva → default
    assert sm.provider_for_chat(cfg, "1", default="TelegramBot") == "TelegramBot"


def test_enabled_chat_ids_esclude_vuoti_e_disattivati():
    cfg = _cfg({"chat_id": "1"}, {"chat_id": "", "enabled": True},
               {"chat_id": "3", "enabled": False})
    assert sm.enabled_chat_ids(cfg) == {"1"}


# ── validazione: chat_id duplicato bloccato, nome duplicato avvisato ─────────

def test_chat_id_duplicato_bloccato():
    sources = [{"chat_id": "1"}, {"chat_id": "1"}]
    errors = sm.validate_sources(sources)
    assert any("duplicato" in e for e in errors)


def test_chat_id_mancante_bloccato():
    errors = sm.validate_sources([{"name": "senza id"}])
    assert any("chat_id mancante" in e for e in errors)


def test_modalita_non_valida_bloccata():
    errors = sm.validate_sources([{"chat_id": "1", "mode": "BOH"}])
    assert any("modalità non valida" in e for e in errors)


def test_sorgenti_valide_nessun_errore():
    sources = [{"name": "A", "chat_id": "1", "mode": "PRE"},
               {"name": "B", "chat_id": "2", "mode": "LIVE"}]
    assert sm.validate_sources(sources) == []


def test_nome_duplicato_avvisato_non_bloccante():
    sources = [{"name": "Tipster", "chat_id": "1"},
               {"name": "Tipster", "chat_id": "2"}]
    # chat_id diversi → nessun errore bloccante
    assert sm.validate_sources(sources) == []
    # ma il nome duplicato è un avviso
    warnings = sm.duplicate_name_warnings(sources)
    assert any("Tipster" in w for w in warnings)


def test_nomi_unici_nessun_avviso():
    sources = [{"name": "A", "chat_id": "1"}, {"name": "B", "chat_id": "2"}]
    assert sm.duplicate_name_warnings(sources) == []


def test_enabled_malformato_fail_closed():
    """C7 #259: `enabled` malformato NON deve riabilitare una sorgente che l'operatore
    credeva spenta. Prima `_as_bool` era denylist-based: un typo («flase», «disabled»)
    o NaN/inf diventavano True → chat riabilitata di nascosto. Ora vale l'allowlist
    fail-closed (stesso contratto di `autostart.is_enabled`/`as_bool_optin`): solo un
    "sì" esplicito abilita; il default per chiave ASSENTE resta True.

    Fail-first: sul vecchio codice «flase»/«attivo»/NaN producevano enabled=True."""
    for bad in ("flase", "disabled", "spento", "attivo", "enabled",
                float("nan"), float("inf"), [], {}, None):
        cfg = _cfg({"chat_id": "777", "enabled": bad})
        assert sm.source_chats(cfg)[0]["enabled"] is False, f"riabilitata da {bad!r}"
        assert sm.enabled_chat_ids(cfg) == set()
    # Gli esplicitamente-sì restano sì (retro-compatibilità con i valori legittimi).
    for ok in (True, 1, 2, "1", "true", " TRUE ", "yes", "on", "si", "sì"):
        cfg = _cfg({"chat_id": "777", "enabled": ok})
        assert sm.source_chats(cfg)[0]["enabled"] is True, f"spenta da {ok!r}"
    # Gli esplicitamente-no restano no; la chiave assente resta il default attivo.
    for off in (False, 0, 0.0, "0", "false", "no", "off", ""):
        cfg = _cfg({"chat_id": "777", "enabled": off})
        assert sm.source_chats(cfg)[0]["enabled"] is False, f"accesa da {off!r}"
    assert sm.source_chats(_cfg({"chat_id": "777"}))[0]["enabled"] is True


def _nostri(caplog):
    """Solo i record del logger di source_manager (robustezza, review Fable: caplog
    cattura dal root e un warning di una libreria terza non deve falsare gli assert)."""
    return [r for r in caplog.records if r.name == "xtrader_bridge.source_manager"]


def test_enabled_malformato_viene_segnalato_a_log(caplog):
    """Review Fable/Sourcery su #309: il flip fail-closed non deve essere silenzioso.
    Un `enabled` malformato produce un WARNING con chat_id e valore incriminato (mai
    altri campi della config); un "no" ESPLICITO (False/"false"/0/"off"/-0.0) non
    logga. Il messaggio è codificabile in cp1252 (handler Windows legacy, review GPT)."""
    import logging as _logging
    sm._reset_warnings()
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        sm.source_chats(_cfg({"chat_id": "777", "enabled": "flase",
                              "name": "RISERVATO", "provider": "PROV_X"}))
    recs = _nostri(caplog)
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "flase" in msg and "777" in msg
    assert "RISERVATO" not in msg and "PROV_X" not in msg  # mai altri campi della config
    msg.encode("cp1252")                                   # niente char fuori codepage legacy
    caplog.clear()
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        for off in (False, "false", 0, "off", "", "0", "no", -0.0):
            sm.source_chats(_cfg({"chat_id": "777", "enabled": off}))
        sm.source_chats(_cfg({"chat_id": "777"}))                    # default: nessun log
        sm.source_chats(_cfg({"chat_id": "777", "enabled": True}))   # sì esplicito: idem
    assert _nostri(caplog) == []


def test_enabled_malformato_logga_una_sola_volta_per_valore(caplog):
    """Anti-flooding (review GLM/GPT/Fable su #309): `source_chats` può girare in hot
    path — lo STESSO valore malformato per la stessa chat logga UNA volta sola; chat o
    valore diversi loggano di nuovo; None e NaN sono malformati (warning); un valore
    lunghissimo viene TRONCATO nel messaggio (niente righe giganti, niente leak)."""
    import logging as _logging
    sm._reset_warnings()
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        for _ in range(5):                                             # hot path simulato
            sm.source_chats(_cfg({"chat_id": "777", "enabled": "flase"}))
        sm.source_chats(_cfg({"chat_id": "778", "enabled": "flase"}))  # altra chat: logga
        sm.source_chats(_cfg({"chat_id": "777", "enabled": None}))     # None: malformato
        sm.source_chats(_cfg({"chat_id": "777", "enabled": float("nan")}))
        sm.source_chats(_cfg({"chat_id": "777", "enabled": "x" * 500}))
    recs = _nostri(caplog)
    assert len(recs) == 5                                  # 1+1+1+1+1: niente spam
    lungo = [r.getMessage() for r in recs if "xxx" in r.getMessage()]
    assert lungo and len(lungo[0]) < 300                   # valore troncato nel log


def test_enabled_log_sicuro_con_unicode_newline_e_chat_lunga(caplog):
    """Round 3 (GPT/Fable/Fugu #309): `repr()` non escapa gli Unicode stampabili — un
    `enabled` con emoji rompeva l'handler cp1252 (UnicodeEncodeError = warning PERSO)
    e un `chat_id` con newline finiva raw nella riga (log injection); il chat_id non
    era nemmeno troncato. Ora entrambi i segmenti dinamici passano da `ascii()` +
    troncamento: messaggio sempre cp1252-encodabile, su una sola riga, corto.

    Fail-first: sul codice precedente l'emoji restava nel messaggio e la newline
    del chat_id spezzava la riga di log."""
    import logging as _logging
    sm._reset_warnings()
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        sm.source_chats(_cfg({"chat_id": "777", "enabled": "😀attivo"}))
        sm.source_chats(_cfg({"chat_id": "777😀", "enabled": "flase"}))
        sm.source_chats(_cfg({"chat_id": "777\nWARNING finto", "enabled": "flase"}))
        sm.source_chats(_cfg({"chat_id": "9" * 500, "enabled": "flase"}))
    recs = _nostri(caplog)
    assert len(recs) == 4
    for r in recs:
        msg = r.getMessage()
        msg.encode("cp1252")          # codificabile anche con input arbitrario
        assert "\n" not in msg        # niente injection multiriga dal chat_id
        assert len(msg) < 320         # anche il chat_id è troncato, non solo enabled


def test_enabled_valori_lunghi_stesso_prefisso_loggano_entrambi(caplog):
    """Round 3 (GLM/GPT/Fugu #309): il dedup era keyed sul valore TRONCATO — due valori
    distinti con gli stessi primi 57 caratteri collassavano su una chiave sola e il
    secondo warning spariva. Ora la chiave usa l'hash del valore COMPLETO (e resta a
    dimensione fissa in memoria, senza trattenere valori/chat_id giganti).

    Fail-first: sul codice precedente il secondo valore non produceva alcun record."""
    import logging as _logging
    sm._reset_warnings()
    prefisso = "x" * 80
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        sm.source_chats(_cfg({"chat_id": "777", "enabled": prefisso + "A"}))
        sm.source_chats(_cfg({"chat_id": "777", "enabled": prefisso + "B"}))
    assert len(_nostri(caplog)) == 2


def test_warned_enabled_ha_un_cap_assoluto(caplog):
    """Round 3 (Fable/Fugu #309): in un processo 24/7 con config rigenerata e garbage
    variabile il set di dedup cresceva senza limite. Ora c'è un cap assoluto: oltre,
    i warning NUOVI sono soppressi fino al riavvio/reset (solo visibilità: il
    fail-closed resta attivo su ogni sorgente) e la memoria è bounded."""
    import logging as _logging
    sm._reset_warnings()
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        for i in range(sm._WARNED_CAP + 50):
            cfg = _cfg({"chat_id": "777", "enabled": f"garbage-{i}"})
            assert sm.source_chats(cfg)[0]["enabled"] is False   # fail-closed sempre
    assert len(sm._WARNED_ENABLED) == sm._WARNED_CAP             # niente crescita oltre
    assert len(_nostri(caplog)) == sm._WARNED_CAP
    sm._reset_warnings()


def test_is_recognized_off_equality_numerica_esplicita():
    """Review Fable round 3 #309: `-0.0` è un "no" ESPLICITO per equality numerica
    (`-0.0 == 0`), non via stringa; NaN/inf/None/typo NON sono riconosciuti come off
    (→ ramo malformato). Test dedicato, non solo indiretto via assenza di log."""
    for off in (-0.0, 0.0, 0, False, "off", "no", "0", ""):
        assert sm._is_recognized_off(off) is True, off
    for not_off in (float("nan"), float("inf"), None, [], {}, "flase", True, 1):
        assert sm._is_recognized_off(not_off) is False, not_off


def test_malformed_enabled_warnings_per_gui():
    """Codex P2 #309: il warning del logger Python non è visibile nell'app windowed —
    `malformed_enabled_warnings` produce i messaggi che `_start` mostra nel log eventi.
    Solo sorgenti malformate (né sì né no espliciti); valori sanificati/troncati; mai
    altri campi della config."""
    srcs = [{"chat_id": "111", "enabled": "flase", "name": "RISERVATO"},
            {"chat_id": "222", "enabled": False},          # no esplicito: nessun avviso
            {"chat_id": "333", "enabled": True},           # sì esplicito: idem
            {"chat_id": "444"},                            # default: idem
            {"chat_id": "555", "enabled": "😀" + "y" * 200},
            "non-dict-ignorata"]
    warns = sm.malformed_enabled_warnings(srcs)
    assert len(warns) == 2
    assert "111" in warns[0] and "flase" in warns[0] and "RISERVATO" not in warns[0]
    assert "555" in warns[1] and len(warns[1]) < 320
    for w in warns:
        w.encode("cp1252")                                 # anche l'event log è un file
        assert "\n" not in w
    assert sm.malformed_enabled_warnings([]) == []
    assert sm.malformed_enabled_warnings(None) == []


def test_vocabolario_si_allineato_con_autostart():
    """Anti-drift (review GLM/Fable su #309): ogni stringa-sì di `_ENABLED_TRUE` deve
    essere un sì anche per `autostart.is_enabled` (stesso contratto dichiarato)."""
    from xtrader_bridge import autostart
    for v in sm._ENABLED_TRUE:
        assert autostart.is_enabled({"auto_start_listener": v}) is True, v
        assert sm.as_enabled_bool(v) is True, v


def test_enabled_int_enorme_non_crasha():
    """Lezione #299 blindata anche qui: un int fuori range float (10**400) non deve
    sollevare OverflowError — è un numero esplicitamente non-zero → True."""
    assert sm.as_enabled_bool(10**400) is True
    assert sm.as_enabled_bool(-(10**400)) is True
