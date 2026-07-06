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
    src = inspect.getsource(app_mod.App._update_real_mode_banner)
    assert "collaudo_banner_active" in src
    assert "(not active)" in src
    assert "_session_mode" in src
