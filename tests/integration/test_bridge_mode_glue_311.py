"""Glue #311 §3.1: gate mode-aware in `App._gate_dangerous_transitions` + banner.

Esercita il VERO metodo su un'istanza nuda (pattern dei glue test esistenti): niente
widget, i dialog sono stub deterministici. Il caso critico è COLLAUDO→REALE annullato:
il bridge deve TORNARE a COLLAUDO (dry_run resta False), non a simulazione — e
soprattutto la conferma deve ESSERE chiesta (il check storico su dry_run non la vede)."""

import inspect

import pytest

from xtrader_bridge import bridge_mode as bm
from xtrader_bridge import real_mode

SIM, COL, RE = bm.SIMULAZIONE, bm.COLLAUDO, bm.REALE


def _bare_app(app_mod, *, confirm_real=False, confirm_collaudo=False):
    app = object.__new__(app_mod.App)
    app._adv = {}
    app._logs = []
    app._log = app._logs.append
    app._confirm_real_mode = lambda: confirm_real
    app._confirm_collaudo_mode = lambda: confirm_collaudo
    return app


def test_collaudo_annullato_torna_alla_simulazione(app_mod):
    app = _bare_app(app_mod, confirm_collaudo=False)
    old = {"dry_run": True, "bridge_mode": SIM}
    cfg = app._gate_dangerous_transitions(old, {"dry_run": False, "bridge_mode": COL})
    assert cfg["dry_run"] is True and cfg["bridge_mode"] == SIM
    assert any("COLLAUDO ANNULLATA" in ln for ln in app._logs)


def test_collaudo_confermato_passa(app_mod):
    app = _bare_app(app_mod, confirm_collaudo=True)
    cfg = app._gate_dangerous_transitions(
        {"dry_run": True}, {"dry_run": False, "bridge_mode": COL})
    assert cfg["dry_run"] is False and cfg["bridge_mode"] == COL


def test_collaudo_to_reale_chiede_la_frase_e_su_annullo_resta_collaudo(app_mod):
    # IL caso che il check storico su dry_run non vede (False→False): la conferma frase
    # DEVE essere chiesta; su annullo si torna a COLLAUDO (non a simulazione: il bridge
    # stava già scrivendo il CSV di collaudo e deve continuare a farlo, non di più).
    asked = []
    app = _bare_app(app_mod)
    app._confirm_real_mode = lambda: (asked.append(1), False)[1]
    old = {"dry_run": False, "bridge_mode": COL}
    cfg = app._gate_dangerous_transitions(old, {"dry_run": False, "bridge_mode": RE})
    assert asked, "la conferma REALE non è stata chiesta su COLLAUDO→REALE"
    assert cfg["bridge_mode"] == COL and cfg["dry_run"] is False
    assert any("REALE ANNULLATA" in ln and "COLLAUDO" in ln for ln in app._logs)


def test_reale_confermato_logga_audit(app_mod):
    app = _bare_app(app_mod, confirm_real=True)
    cfg = app._gate_dangerous_transitions(
        {"dry_run": True}, {"dry_run": False, "bridge_mode": RE})
    assert cfg["bridge_mode"] == RE and cfg["dry_run"] is False
    assert any(real_mode.AUDIT_MARKER in ln for ln in app._logs)


def test_reale_to_collaudo_senza_conferme(app_mod):
    # Uscire dal reale verso il collaudo non aumenta il rischio: nessun prompt.
    app = _bare_app(app_mod)   # entrambi i confirm stub tornano False: se venissero
    old = {"dry_run": False, "bridge_mode": RE}          # chiesti, il gate annullerebbe
    cfg = app._gate_dangerous_transitions(old, {"dry_run": False, "bridge_mode": COL})
    assert cfg["bridge_mode"] == COL and cfg["dry_run"] is False


def test_banner_collaudo_subordinato_al_rosso(app_mod):
    # Pin strutturale (widget non istanziabili headless): il banner COLLAUDO è gestito
    # da _update_real_mode_banner, si accende SOLO se il rosso non è attivo (priorità
    # al rischio maggiore) e usa la decisione pura collaudo_banner_active.
    # La PRIORITÀ è logica pura testata con input concreti (bridge_mode.banners_for,
    # CodeRabbit #349): qui si pinna solo che la vista la usi davvero (mode-aware,
    # niente criterio dry_run) e le passi lo stato di sessione.
    src = inspect.getsource(app_mod.App._update_real_mode_banner)
    assert "bridge_mode.banners_for" in src
    assert "_session_mode" in src
    assert "real_mode.banner_active" not in src


def test_form_legacy_verso_reale_passa_comunque_dal_gate(app_mod):
    # Fable #349: un form legacy (solo dry_run=false, niente bridge_mode) che porta la
    # config in REALE NON bypassa la conferma frase — _gate_dangerous_transitions gira
    # DOPO apply_advanced su ogni save/caricamento profilo e confronta i MODI effettivi.
    from xtrader_bridge import config_store as cs
    from xtrader_bridge import settings_controller as sc
    base = dict(cs.DEFAULTS)                       # SIMULAZIONE
    form_legacy = {"recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
                   "dry_run": False, "max_per_day": "10", "max_active_signals": "1",
                   "xtrader_notification_chat_id": "", "confirmation_timeout": "120",
                   "confirmation_keywords": "", "rejection_keywords": "",
                   "auto_start_listener": False, "debug_message_payload": False}
    cfg, errors = sc.apply_advanced(base, form_legacy)
    assert errors == [] and bm.mode_from_cfg(cfg) == RE
    asked = []
    app = _bare_app(app_mod)
    app._confirm_real_mode = lambda: (asked.append(1), False)[1]
    gated = app._gate_dangerous_transitions(base, cfg)
    assert asked, "gate REALE non chiesto sul path legacy"
    assert gated["dry_run"] is True and gated["bridge_mode"] == SIM   # annullo → torna a sim
