"""Test hard della «Modalità Collaudo» esplicita (#311 §3.1) — `bridge_mode` puro +
coercion config + settings controller. Il principio sotto test: `dry_run` resta l'UNICA
fonte del percorso di scrittura; la modalità nominata è stato derivato fail-closed, e il
gate REALE è mode-aware (chiude il buco COLLAUDO→REALE invisibile al check su dry_run)."""

import pytest

from xtrader_bridge import bridge_mode as bm
from xtrader_bridge import config_store, real_mode, safety_guard
from xtrader_bridge import settings_controller as sc

SIM, COL, RE = bm.SIMULAZIONE, bm.COLLAUDO, bm.REALE


# ── mode_from_cfg: dry_run autoritativo, fail-closed ─────────────────────────

def test_dry_run_true_vince_su_bridge_mode_incoerente():
    # Config manomessa: bridge_mode "REALE" ma dry_run True → SIMULAZIONE (l'etichetta
    # sporca non accende la scrittura). Il write-path legge comunque solo is_dry_run.
    cfg = {"dry_run": True, "bridge_mode": "REALE"}
    assert bm.mode_from_cfg(cfg) == SIM
    assert safety_guard.is_dry_run(cfg) is True


def test_legacy_reale_senza_bridge_mode_resta_reale():
    # Config pre-tristato col reale confermato: nessun declassamento silenzioso.
    assert bm.mode_from_cfg({"dry_run": False}) == RE
    assert bm.mode_from_cfg({"dry_run": False, "bridge_mode": "boh"}) == RE


def test_collaudo_dichiarato_e_riconosciuto():
    assert bm.mode_from_cfg({"dry_run": False, "bridge_mode": "COLLAUDO"}) == COL
    assert bm.mode_from_cfg({"dry_run": False, "bridge_mode": " collaudo "}) == COL


def test_cfg_vuota_o_malformata_fail_closed_sim():
    assert bm.mode_from_cfg({}) == SIM
    assert bm.mode_from_cfg(None) == SIM
    assert bm.mode_from_cfg({"dry_run": "garbage"}) == SIM   # is_dry_run fail-closed


def test_apply_mode_coerente_e_fail_closed():
    cfg = {}
    bm.apply_mode(cfg, COL)
    assert cfg == {"bridge_mode": COL, "dry_run": False}
    bm.apply_mode(cfg, "sconosciuto")
    assert cfg == {"bridge_mode": SIM, "dry_run": True}      # fail-closed → simulazione


# ── gate mode-aware: il buco COLLAUDO→REALE ──────────────────────────────────

def test_collaudo_to_reale_richiede_conferma_dove_real_mode_non_vede():
    old = {"dry_run": False, "bridge_mode": COL}
    new = {"dry_run": False, "bridge_mode": RE}
    # Il check storico su dry_run NON scatta (False→False): è il buco.
    assert real_mode.requires_confirmation(old, new) is False
    # Il gate mode-aware SÌ: attivare il reale richiede sempre la frase.
    assert bm.requires_real_confirmation(old, new) is True


def test_gate_reale_su_sim_to_reale_e_mai_su_uscita():
    assert bm.requires_real_confirmation({"dry_run": True}, {"dry_run": False}) is True
    assert bm.requires_real_confirmation({"dry_run": False}, {"dry_run": False}) is False
    assert bm.requires_real_confirmation(
        {"dry_run": False}, {"dry_run": False, "bridge_mode": COL}) is False  # REALE→COLLAUDO
    assert bm.requires_real_confirmation({"dry_run": False}, {"dry_run": True}) is False


def test_gate_collaudo_solo_da_simulazione():
    sim, col = {"dry_run": True}, {"dry_run": False, "bridge_mode": COL}
    reale = {"dry_run": False, "bridge_mode": RE}
    assert bm.requires_collaudo_confirmation(sim, col) is True
    assert bm.requires_collaudo_confirmation(reale, col) is False   # rischio non aumenta
    assert bm.requires_collaudo_confirmation(col, col) is False


# ── banner collaudo: sticky di sessione, priorità decisa dal chiamante ───────

def test_collaudo_banner_live_e_sticky_di_sessione():
    col = {"dry_run": False, "bridge_mode": COL}
    assert bm.collaudo_banner_active(col) is True
    # Sessione partita in collaudo, config viva tornata in simulazione: il CSV viene
    # ancora scritto fino a STOP → il banner resta.
    assert bm.collaudo_banner_active({"dry_run": True}, session_active=True,
                                     session_mode=COL) is True
    assert bm.collaudo_banner_active({"dry_run": True}, session_active=False,
                                     session_mode=COL) is False
    assert bm.collaudo_banner_active({"dry_run": True}) is False


# ── form mapping ─────────────────────────────────────────────────────────────

def test_mode_for_form_value_label_canonico_e_sconosciuto():
    for mode in bm.VALID_MODES:
        assert bm.mode_for_form_value(bm.LABELS[mode]) == mode
        assert bm.mode_for_form_value(mode.lower()) == mode
    assert bm.mode_for_form_value("qualcosa") is None
    assert bm.mode_for_form_value(None) is None


# ── coercion config_store: self-heal, dry_run autoritativo ───────────────────

def test_coercion_config_sana_bridge_mode_incoerente(tmp_path, monkeypatch):
    path = str(tmp_path / "config.json")
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"dry_run": True, "bridge_mode": "REALE"}, f)
    cfg = config_store.load_config(path)
    assert cfg["bridge_mode"] == SIM and cfg["dry_run"] is True


def test_coercion_config_legacy_reale_e_collaudo(tmp_path):
    import json
    p1 = str(tmp_path / "c1.json")
    with open(p1, "w", encoding="utf-8") as f:
        json.dump({"dry_run": False}, f)                       # legacy reale confermato
    assert config_store.load_config(p1)["bridge_mode"] == RE
    p2 = str(tmp_path / "c2.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump({"dry_run": False, "bridge_mode": "collaudo"}, f)
    assert config_store.load_config(p2)["bridge_mode"] == COL


# ── settings_controller: form → coppia coerente ──────────────────────────────

def test_apply_advanced_bridge_mode_deriva_dry_run():
    base = dict(config_store.DEFAULTS)
    form = _form_valida(bridge_mode=bm.LABELS[COL])
    cfg, errors = sc.apply_advanced(base, form)
    assert errors == []
    assert cfg["bridge_mode"] == COL and cfg["dry_run"] is False
    cfg2, _ = sc.apply_advanced(base, _form_valida(bridge_mode="SIMULAZIONE"))
    assert cfg2["bridge_mode"] == SIM and cfg2["dry_run"] is True


def test_apply_advanced_bridge_mode_sconosciuta_errore_senza_merge():
    base = dict(config_store.DEFAULTS)
    cfg, errors = sc.apply_advanced(base, _form_valida(bridge_mode="TURBO"))
    assert any("Modalità bridge non valida" in e for e in errors)
    assert cfg == base                                          # o tutto valido, o niente


def test_apply_advanced_form_legacy_solo_dry_run_invariato():
    base = dict(config_store.DEFAULTS)
    form = _form_valida()
    form.pop("bridge_mode", None)
    form["dry_run"] = False
    cfg, errors = sc.apply_advanced(base, form)
    assert errors == [] and cfg["dry_run"] is False
    # Coerenza IMMEDIATA (Fable/GLM #349): il path legacy ri-deriva bridge_mode dalla
    # coppia risultante — niente `dry_run=false` + `bridge_mode:"SIMULAZIONE"` persistiti.
    assert cfg["bridge_mode"] == RE          # legacy reale: nessun declassamento
    form["dry_run"] = True
    cfg2, _ = sc.apply_advanced(base, form)
    assert cfg2["bridge_mode"] == SIM and cfg2["dry_run"] is True
    # COLLAUDO già dichiarato in base + form legacy dry_run=false → preservato.
    base_col = dict(config_store.DEFAULTS, bridge_mode=COL, dry_run=False)
    form["dry_run"] = False
    cfg3, _ = sc.apply_advanced(base_col, form)
    assert cfg3["bridge_mode"] == COL


def test_current_values_mostra_etichetta_del_modo_effettivo():
    vals = sc.current_values({"dry_run": False, "bridge_mode": COL})
    assert vals["bridge_mode"] == bm.LABELS[COL]
    # incoerente → etichetta Simulazione (fail-closed, ciò che il bridge farebbe davvero)
    vals2 = sc.current_values({"dry_run": True, "bridge_mode": RE})
    assert vals2["bridge_mode"] == bm.LABELS[SIM]


def _form_valida(**over):
    form = {
        "recognition_mode": "NAME_ONLY", "queue_mode": "OVERWRITE_LAST",
        "bridge_mode": bm.LABELS[SIM], "max_per_day": "10",
        "max_active_signals": "1", "xtrader_notification_chat_id": "",
        "confirmation_timeout": "120", "confirmation_keywords": "",
        "rejection_keywords": "", "auto_start_listener": False,
        "debug_message_payload": False,
    }
    form.update(over)
    return form


# ── banner ROSSO mode-aware (Fugu #349): il COLLAUDO non deve accenderlo ─────

def test_real_banner_spento_in_collaudo_e_acceso_solo_in_reale():
    col = {"dry_run": False, "bridge_mode": COL}
    reale = {"dry_run": False, "bridge_mode": RE}
    # In COLLAUDO dry_run è False ma il banner ROSSO deve restare spento (si accende
    # l'AMBRA): col vecchio criterio su dry_run mostrerebbe «MODALITÀ REALE ATTIVA»
    # durante il collaudo, sopprimendo l'avviso «XTrader in simulazione».
    assert bm.real_banner_active(col) is False
    assert bm.collaudo_banner_active(col) is True
    assert bm.real_banner_active(reale) is True
    assert bm.collaudo_banner_active(reale) is False


def test_real_banner_sticky_di_sessione_per_modo():
    sim = {"dry_run": True}
    # Sessione partita in REALE, config viva tornata in sim → rosso resta.
    assert bm.real_banner_active(sim, session_active=True, session_mode=RE) is True
    # Sessione partita in COLLAUDO → rosso NO (resta l'ambra, già testata sopra).
    assert bm.real_banner_active(sim, session_active=True, session_mode=COL) is False
    assert bm.real_banner_active(sim) is False


def test_banners_for_priorita_e_mutua_esclusione():
    # (rosso, ambra) con input concreti: mai entrambi accesi, il rosso vince.
    assert bm.banners_for({"dry_run": False, "bridge_mode": RE}) == (True, False)
    assert bm.banners_for({"dry_run": False, "bridge_mode": COL}) == (False, True)
    assert bm.banners_for({"dry_run": True}) == (False, False)
    # Caso limite: config viva REALE + sessione partita in COLLAUDO → SOLO rosso.
    assert bm.banners_for({"dry_run": False, "bridge_mode": RE},
                          session_active=True, session_mode=COL) == (True, False)
    # Sessione REALE sticky con config tornata in sim → solo rosso.
    assert bm.banners_for({"dry_run": True},
                          session_active=True, session_mode=RE) == (True, False)
