"""Test hard veritieri — Issue #76 P2-8 (audit 2026-07-15): wizard step 3 col contesto runtime.

`wizard.check_parser` chiamava `builder.batch_report(text)` NUDO: senza profili di
mappatura nomi/mercati (parser che li richiede → `MAPPING_MISSING` perenne → step 3
sempre ⛔ → **wizard incompletabile** con una config funzionante), senza la modalità
globale (parser legacy `mode=""` valutato in NAME_ONLY → **falso ✅** con globale
ID_ONLY), senza provider/lingua sorgente.

Fix testato: `check_parser(builder, message, *, cfg=None, chat="")` risolve il contesto
dalla config VIVA con la stessa risoluzione verbatim del runtime
(`signal_router._resolve_one` / GUI «Prova messaggio» / assistente); `cfg=None` preserva
il comportamento storico. Wiring: `WizardWindow(cfg_provider=...)` da `app._open_wizard`.
"""



from xtrader_bridge import parser_builder as pb
from xtrader_bridge import wizard


def _builder(*, mode="NAME_ONLY", name_profiles=()):
    b = pb.ParserBuilder()
    b.name = "Wiz"
    b.mode = mode
    b.name_mapping_profiles = list(name_profiles)
    b.add_rule(target="Provider", fixed_value="PBet")
    b.add_rule(target="EventName", start_after="🆚", end_before="\n", required=True)
    b.add_rule(target="Price", fixed_value="1.50", required=True)
    b.add_rule(target="BetType", fixed_value="PUNTA", required=True)
    b.add_rule(target="MarketType", fixed_value="MATCH_ODDS", required=True)
    b.add_rule(target="SelectionName", fixed_value="Casa", required=True)
    return b


_MSG = "x\n🆚Inter v Milan\n⌚ 1m"


# ── scenario A (fail-first): profili nomi configurati → lo step 3 deve PASSARE ──────────────

def test_step3_con_profili_nomi_configurati_passa():
    # Parser che RICHIEDE la mappatura nomi + config con il profilo popolato (setup standard):
    # prima del fix `batch_report` nudo riceveva profili None → MAPPING_MISSING → ⛔ perenne.
    cfg = {"provider": "PBet", "recognition_mode": "NAME_ONLY",
           "name_mappings": {"Serie A": [
               {"provider": "Inter", "betfair": "FC Internazionale", "entity_type": "team"},
               {"provider": "Milan", "betfair": "AC Milan", "entity_type": "team"},
           ]}}
    b = _builder(name_profiles=["Serie A"])
    res = wizard.check_parser(b, _MSG, cfg=cfg, chat="42")
    assert res.ok is True                                     # wizard COMPLETABILE
    assert "FC Internazionale" in str(res.data["rows"][0].row["EventName"])


def test_step3_profili_richiesti_ma_vuoti_resta_fail_closed():
    # Il contesto non “regala” il pass: profilo richiesto ma senza righe in config →
    # MAPPING_MISSING resta (fail-closed identico al runtime).
    cfg = {"provider": "PBet", "recognition_mode": "NAME_ONLY",
           "name_mappings": {"Serie A": []}}
    res = wizard.check_parser(_builder(name_profiles=["Serie A"]), _MSG, cfg=cfg)
    assert res.ok is False


# ── scenario B (fail-first): parser legacy mode="" + globale ID_ONLY → niente falso ✅ ───────

def test_step3_parser_legacy_eredita_id_only_dal_globale():
    cfg = {"provider": "PBet", "recognition_mode": "ID_ONLY"}
    res = wizard.check_parser(_builder(mode=""), _MSG, cfg=cfg)
    assert res.ok is False                                    # come il runtime: niente falso ✅


def test_step3_mode_esplicito_del_parser_vince_sul_globale():
    cfg = {"provider": "PBet", "recognition_mode": "ID_ONLY"}
    res = wizard.check_parser(_builder(mode="NAME_ONLY"), _MSG, cfg=cfg)
    assert res.ok is True                                     # precedenza defn.mode (runtime)


# ── retro-compatibilità: cfg assente → comportamento storico invariato ───────────────────────

def test_step3_senza_cfg_comportamento_storico():
    assert wizard.check_parser(_builder(), _MSG).ok is True
    assert wizard.check_parser(_builder(), "ciao come va").ok is False
    assert wizard.check_parser(_builder(), "  ").ok is False


def test_step3_cfg_non_dict_degrada_al_comportamento_storico():
    assert wizard.check_parser(_builder(), _MSG, cfg="rotto").ok is True


# ── wiring (strutturale, pattern #311/#309: GUI non istanziabile headless) ───────────────────

def test_wizard_gui_passa_il_cfg_provider_a_check_parser():
    # wizard_gui importa customtkinter (assente/incompleto senza Tk reale): si pinna il
    # SORGENTE su file, come per app.py qui sotto.
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2].joinpath(
        "xtrader_bridge", "wizard_gui.py").read_text(encoding="utf-8")
    idx = src.index("def _run_parser_check")
    blocco = src[idx:idx + 800]
    assert "_cfg_provider" in blocco
    assert "cfg=cfg" in blocco and "chat=" in blocco          # contesto passato allo step 3
    assert "check_parser" in blocco


def test_app_open_wizard_fornisce_la_config_viva():
    # app.py importa customtkinter/telegram a modulo: si pinna il SORGENTE su file (stesso
    # esito del test strutturale via inspect: il wiring c'è o non c'è), senza import fragili.
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2].joinpath(
        "xtrader_bridge", "app.py").read_text(encoding="utf-8")
    idx = src.index("cfg_provider=")
    assert "self._config" in src[idx:idx + 200]               # config VIVA, non snapshot disco