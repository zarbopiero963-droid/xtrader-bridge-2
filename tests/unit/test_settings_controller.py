"""PR-13: test del controller delle impostazioni avanzate (logica pura)."""

from xtrader_bridge import settings_controller as sc
from xtrader_bridge import config_store, recognition, safety_guard, signal_queue


def test_options_dalle_fonti_uniche():
    # Le opzioni dei menu vengono dalle costanti già testate, non duplicate.
    assert sc.recognition_mode_options() == list(recognition.VALID_MODES)
    assert sc.queue_mode_options() == list(signal_queue.MODES)


def test_current_values_default_sicuri_su_config_vuota():
    v = sc.current_values({})
    assert v["recognition_mode"] == recognition.DEFAULT_MODE   # NAME_ONLY
    assert v["queue_mode"] == signal_queue.DEFAULT_MODE         # OVERWRITE_LAST
    assert v["require_price"] is True                           # default sicuro
    assert v["dry_run"] is True                                 # default sicuro (simulazione)
    assert v["max_per_day"] == safety_guard.DEFAULT_MAX_PER_DAY
    assert v["xtrader_notification_chat_id"] == ""
    # PR-17c: timeout conferma dal default unico; keyword vuote come stringa CSV vuota.
    assert v["confirmation_timeout"] == config_store.DEFAULTS["confirmation_timeout"]
    assert v["confirmation_keywords"] == ""
    assert v["rejection_keywords"] == ""


def test_current_values_legge_la_config():
    cfg = {
        "recognition_mode": "both", "queue_mode": "APPEND_ACTIVE",
        "require_price": False, "dry_run": False, "max_per_day": 50,
        "xtrader_notification_chat_id": "  -100777  ",
    }
    v = sc.current_values(cfg)
    assert v["recognition_mode"] == "BOTH"
    assert v["queue_mode"] == "APPEND_ACTIVE"
    assert v["require_price"] is False
    assert v["dry_run"] is False
    assert v["max_per_day"] == 50
    assert v["xtrader_notification_chat_id"] == "-100777"


def test_current_values_int_invalido_ricade_su_default():
    v = sc.current_values({"max_per_day": "abc"})
    assert v["max_per_day"] == safety_guard.DEFAULT_MAX_PER_DAY


def test_current_values_non_intero_non_viene_troncato():
    # Codex P2: 1.5 NON deve diventare 1 (limite valido diverso) — ricade sul default,
    # come fa il DailyLimiter runtime sui valori malformati.
    assert sc.current_values({"max_per_day": 1.5})["max_per_day"] == safety_guard.DEFAULT_MAX_PER_DAY
    assert sc.current_values({"max_per_day": "1.5"})["max_per_day"] == safety_guard.DEFAULT_MAX_PER_DAY
    assert sc.current_values({"max_per_day": 0})["max_per_day"] == safety_guard.DEFAULT_MAX_PER_DAY
    assert sc.current_values({"max_per_day": True})["max_per_day"] == safety_guard.DEFAULT_MAX_PER_DAY
    # Un intero valido (anche come float intero o stringa) passa.
    assert sc.current_values({"max_per_day": 10})["max_per_day"] == 10
    assert sc.current_values({"max_per_day": "10"})["max_per_day"] == 10
    assert sc.current_values({"max_per_day": 10.0})["max_per_day"] == 10


def test_apply_valido_fonde_preservando_le_altre_chiavi():
    cfg = {"bot_token": "T", "chat_id": "42", "source_chats": [{"chat_id": "1"}]}
    form = {
        "recognition_mode": "ID_ONLY", "queue_mode": "QUEUE_UNTIL_CONFIRMED",
        "require_price": False, "dry_run": False, "max_per_day": "10",
        "xtrader_notification_chat_id": "-100999", "confirmation_timeout": "45",
    }
    new_cfg, errors = sc.apply_advanced(cfg, form)
    assert errors == []
    assert new_cfg["confirmation_timeout"] == 45
    # Chiavi gestite aggiornate...
    assert new_cfg["recognition_mode"] == "ID_ONLY"
    assert new_cfg["queue_mode"] == "QUEUE_UNTIL_CONFIRMED"
    assert new_cfg["require_price"] is False
    assert new_cfg["dry_run"] is False
    assert new_cfg["max_per_day"] == 10
    assert new_cfg["xtrader_notification_chat_id"] == "-100999"
    # ...e tutto il resto preservato.
    assert new_cfg["bot_token"] == "T"
    assert new_cfg["chat_id"] == "42"
    assert new_cfg["source_chats"] == [{"chat_id": "1"}]


def test_apply_non_muta_la_config_originale():
    cfg = {"recognition_mode": "NAME_ONLY", "keep": "me"}
    form = sc.current_values(cfg)
    form["recognition_mode"] = "BOTH"
    new_cfg, errors = sc.apply_advanced(cfg, form)
    assert errors == []
    assert new_cfg["recognition_mode"] == "BOTH"
    assert cfg["recognition_mode"] == "NAME_ONLY"   # originale intatto


def test_apply_modalita_non_valide_bloccano_senza_merge():
    cfg = {"recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST"}
    form = {
        "recognition_mode": "PINCO", "queue_mode": "PALLINO",
        "require_price": True, "dry_run": True, "max_per_day": "10",
        "confirmation_timeout": "90",
    }
    new_cfg, errors = sc.apply_advanced(cfg, form)
    assert len(errors) == 2     # entrambe le modalità invalide
    # Nessun merge parziale: config invariata.
    assert new_cfg == cfg


def test_apply_max_per_day_invalido_blocca():
    base_form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
        "require_price": True, "dry_run": True, "max_per_day": "10",
        "confirmation_timeout": "90",
    }
    for bad in ("", "0", "-3", "abc", "1.5"):
        form = dict(base_form, max_per_day=bad)
        new_cfg, errors = sc.apply_advanced({}, form)
        assert errors, f"max_per_day={bad!r} doveva fallire"
        assert new_cfg == {}


def test_apply_chat_notifiche_vuota_ammessa():
    form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
        "require_price": True, "dry_run": True, "max_per_day": "200",
        "xtrader_notification_chat_id": "", "confirmation_timeout": "90",
    }
    new_cfg, errors = sc.apply_advanced({}, form)
    assert errors == []
    assert new_cfg["xtrader_notification_chat_id"] == ""


def test_apply_require_price_e_dry_run_da_stringhe():
    # I checkbox danno bool, ma una config/stringa può arrivare come testo.
    form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
        "require_price": "false", "dry_run": "off", "max_per_day": "200",
        "confirmation_timeout": "90",
    }
    new_cfg, errors = sc.apply_advanced({}, form)
    assert errors == []
    assert new_cfg["require_price"] is False
    assert new_cfg["dry_run"] is False


# ── PR-17c: timeout conferma + parole chiave conferma/rifiuto ───────────────
def _valid_form(**over):
    """Form valido di base per i test sulle conferme XTrader."""
    form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "QUEUE_UNTIL_CONFIRMED",
        "require_price": True, "dry_run": True, "max_per_day": "200",
        "xtrader_notification_chat_id": "", "confirmation_timeout": "90",
        "confirmation_keywords": "", "rejection_keywords": "",
    }
    form.update(over)
    return form


def test_current_values_keyword_da_lista_a_stringa_csv():
    # La config tiene le keyword come LISTA; la GUI le mostra come stringa CSV.
    v = sc.current_values({
        "confirmation_keywords": ["piazzata", "  ok  ", "", "matchata"],
        "rejection_keywords": ["annullata"],
        "confirmation_timeout": 30,
    })
    assert v["confirmation_keywords"] == "piazzata, ok, matchata"   # strip + niente vuoti
    assert v["rejection_keywords"] == "annullata"
    assert v["confirmation_timeout"] == 30


def test_current_values_keyword_stringa_csv_normalizzata():
    # Anche una stringa CSV salvata a mano viene ripulita (strip, niente vuoti).
    v = sc.current_values({"confirmation_keywords": " piazzata , , ok "})
    assert v["confirmation_keywords"] == "piazzata, ok"


def test_current_values_timeout_invalido_ricade_su_default():
    default = config_store.DEFAULTS["confirmation_timeout"]
    assert sc.current_values({"confirmation_timeout": "abc"})["confirmation_timeout"] == default
    assert sc.current_values({"confirmation_timeout": 0})["confirmation_timeout"] == default
    assert sc.current_values({"confirmation_timeout": 1.5})["confirmation_timeout"] == default
    assert sc.current_values({"confirmation_timeout": True})["confirmation_timeout"] == default


def test_apply_keyword_da_stringa_csv_a_lista():
    # Round-trip inverso: il campo GUI (stringa CSV) torna LISTA pulita in config.
    form = _valid_form(
        confirmation_keywords="piazzata,  ok , , matchata",
        rejection_keywords="  annullata , rifiutata ",
    )
    new_cfg, errors = sc.apply_advanced({}, form)
    assert errors == []
    assert new_cfg["confirmation_keywords"] == ["piazzata", "ok", "matchata"]
    assert new_cfg["rejection_keywords"] == ["annullata", "rifiutata"]


def test_apply_keyword_vuote_diventano_lista_vuota():
    new_cfg, errors = sc.apply_advanced({}, _valid_form())
    assert errors == []
    assert new_cfg["confirmation_keywords"] == []
    assert new_cfg["rejection_keywords"] == []


def test_apply_timeout_invalido_blocca_senza_merge():
    for bad in ("", "0", "-5", "abc", "1.5"):
        new_cfg, errors = sc.apply_advanced({}, _valid_form(confirmation_timeout=bad))
        assert errors, f"confirmation_timeout={bad!r} doveva fallire"
        assert new_cfg == {}   # nessun merge parziale


def test_apply_timeout_valido_fuso():
    new_cfg, errors = sc.apply_advanced({}, _valid_form(confirmation_timeout="240"))
    assert errors == []
    assert new_cfg["confirmation_timeout"] == 240


def test_auto_start_listener_default_off_e_round_trip():
    # Default sicuro: assente in config → False.
    assert sc.current_values({})["auto_start_listener"] is False
    assert sc.current_values({"auto_start_listener": True})["auto_start_listener"] is True
    # Fail-closed coerente col runtime: un valore malformato (None) NON mostra il
    # toggle come attivo (CodeRabbit: default-off safety).
    assert sc.current_values({"auto_start_listener": None})["auto_start_listener"] is False
    # apply: il form lo gestisce come bool (default False se assente).
    new_cfg, errors = sc.apply_advanced({}, _valid_form(auto_start_listener=True))
    assert errors == []
    assert new_cfg["auto_start_listener"] is True
    new_cfg, errors = sc.apply_advanced({}, _valid_form())
    assert errors == []
    assert new_cfg["auto_start_listener"] is False
