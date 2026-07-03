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


def test_enabled_malformato_viene_segnalato_a_log(caplog):
    """Review Fable/Sourcery su #309: il flip fail-closed non deve essere silenzioso.
    Un `enabled` malformato produce un WARNING con chat_id e valore incriminato (mai
    altri campi della config); un "no" ESPLICITO (False/"false"/0/"off") non logga."""
    import logging as _logging
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        sm.source_chats(_cfg({"chat_id": "777", "enabled": "flase"}))
    assert any("flase" in r.message and "777" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.source_manager"):
        for off in (False, "false", 0, "off", "", "0", "no"):
            sm.source_chats(_cfg({"chat_id": "777", "enabled": off}))
        sm.source_chats(_cfg({"chat_id": "777"}))                    # default: nessun log
        sm.source_chats(_cfg({"chat_id": "777", "enabled": True}))   # sì esplicito: idem
    assert caplog.records == []


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
