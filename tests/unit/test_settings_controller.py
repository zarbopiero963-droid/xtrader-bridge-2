"""PR-13: test del controller delle impostazioni avanzate (logica pura)."""

from xtrader_bridge import settings_controller as sc
from xtrader_bridge import recognition, safety_guard, signal_queue


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
    assert v["confirmation_timeout"] == 120
    assert v["xtrader_notification_chat_id"] == ""


def test_current_values_legge_la_config():
    cfg = {
        "recognition_mode": "both", "queue_mode": "APPEND_ACTIVE",
        "require_price": False, "dry_run": False, "max_per_day": 50,
        "confirmation_timeout": 30, "xtrader_notification_chat_id": "  -100777  ",
    }
    v = sc.current_values(cfg)
    assert v["recognition_mode"] == "BOTH"
    assert v["queue_mode"] == "APPEND_ACTIVE"
    assert v["require_price"] is False
    assert v["dry_run"] is False
    assert v["max_per_day"] == 50
    assert v["confirmation_timeout"] == 30
    assert v["xtrader_notification_chat_id"] == "-100777"


def test_current_values_int_invalido_ricade_su_default():
    v = sc.current_values({"max_per_day": "abc", "confirmation_timeout": -5})
    assert v["max_per_day"] == safety_guard.DEFAULT_MAX_PER_DAY
    assert v["confirmation_timeout"] == 120


def test_apply_valido_fonde_preservando_le_altre_chiavi():
    cfg = {"bot_token": "T", "chat_id": "42", "source_chats": [{"chat_id": "1"}]}
    form = {
        "recognition_mode": "ID_ONLY", "queue_mode": "QUEUE_UNTIL_CONFIRMED",
        "require_price": False, "dry_run": False, "max_per_day": "10",
        "confirmation_timeout": "45", "xtrader_notification_chat_id": "-100999",
    }
    new_cfg, errors = sc.apply_advanced(cfg, form)
    assert errors == []
    # Chiavi gestite aggiornate...
    assert new_cfg["recognition_mode"] == "ID_ONLY"
    assert new_cfg["queue_mode"] == "QUEUE_UNTIL_CONFIRMED"
    assert new_cfg["require_price"] is False
    assert new_cfg["dry_run"] is False
    assert new_cfg["max_per_day"] == 10
    assert new_cfg["confirmation_timeout"] == 45
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
        "require_price": True, "dry_run": True,
        "max_per_day": "10", "confirmation_timeout": "10",
    }
    new_cfg, errors = sc.apply_advanced(cfg, form)
    assert len(errors) == 2     # entrambe le modalità invalide
    # Nessun merge parziale: config invariata.
    assert new_cfg == cfg


def test_apply_interi_invalidi_bloccano():
    base_form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
        "require_price": True, "dry_run": True,
        "max_per_day": "10", "confirmation_timeout": "10",
    }
    for field in ("max_per_day", "confirmation_timeout"):
        for bad in ("", "0", "-3", "abc", "1.5"):
            form = dict(base_form, **{field: bad})
            new_cfg, errors = sc.apply_advanced({}, form)
            assert errors, f"{field}={bad!r} doveva fallire"
            assert new_cfg == {}


def test_apply_chat_notifiche_vuota_ammessa():
    form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
        "require_price": True, "dry_run": True,
        "max_per_day": "200", "confirmation_timeout": "120",
        "xtrader_notification_chat_id": "",
    }
    new_cfg, errors = sc.apply_advanced({}, form)
    assert errors == []
    assert new_cfg["xtrader_notification_chat_id"] == ""


def test_apply_require_price_e_dry_run_da_stringhe():
    # I checkbox danno bool, ma una config/stringa può arrivare come testo.
    form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
        "require_price": "false", "dry_run": "off",
        "max_per_day": "200", "confirmation_timeout": "120",
    }
    new_cfg, errors = sc.apply_advanced({}, form)
    assert errors == []
    assert new_cfg["require_price"] is False
    assert new_cfg["dry_run"] is False
