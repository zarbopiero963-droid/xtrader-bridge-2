"""P2-9 audit #76 — il «🌳 Mapping guidato» NON deve perdere gli alias digitati allo switch.

Bug: `_on_profile_change` faceva subito `_prefill_aliases()` (StringVar sovrascritte),
`_on_sport_change` azzerava `_team_vars` e `_load_teams` lo ricreava: qualunque cambio di
profilo/sport/competizione buttava via l'input non salvato, senza conferma — contro il
pattern auto-save di `NameMappingPanel` («⚽ Calcio»).

Fix testato: foto `_baseline` a ogni precompilazione/salvataggio; `_dirty()` la confronta col
modello; `_autosave_leaving(sport)` fa lo STESSO merge di «💾 Salva nel profilo»
(`merge_team_aliases`) nel profilo che si sta lasciando; save fallito/config illeggibile →
switch ANNULLATO con alias a schermo; senza profilo: cambio profilo mantiene gli alias (come
«🆕 Nuovo»), cambio sport/competizione è annullato; ri-selezione della stessa competizione
con alias digitati = no-op.

I test esercitano i VERI metodi del pannello sul pattern `__new__` + ctk finto
(`test_parser_tester_311`): niente widget, ma `config_store`/`name_mapping_store`/
`merge_team_aliases` REALI su un `CONFIG_FILE` temporaneo — il round-trip su disco è vero.
"""

import importlib
import sys
import types

import pytest

from xtrader_bridge import config_store, name_mapping_store, sports
from xtrader_bridge.betfair.guided_mapping import existing_aliases_for_teams

SPORT = sports.SPORTS[0]


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None,
                                     "__getattr__": lambda self, _n: (lambda *a, **k: None)})
        setattr(self, name, cls)
        return cls


class _Var:
    """StringVar senza Tk: get/set reali (il modello del pannello è fatto di queste)."""

    def __init__(self, value="", **_k):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _Status:
    text = ""
    color = ""

    def configure(self, **k):
        self.text = k.get("text", self.text)
        self.color = k.get("text_color", self.color)


def _gui_mod(monkeypatch):
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.guided_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.guided_mapping_gui")
    # le StringVar create da _load_teams devono avere get/set veri, non il ctk finto.
    monkeypatch.setattr(mod.ctk, "StringVar", _Var, raising=False)
    return mod


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """CONFIG_FILE temporaneo con i profili P1 e P2 già salvati (store/save REALI)."""
    path = str(tmp_path / "config.json")
    monkeypatch.setattr(config_store, "CONFIG_FILE", path)
    cfg = name_mapping_store.add_profile({}, "P1")
    cfg = name_mapping_store.add_profile(cfg, "P2")
    _saved, ok = config_store.save_config(cfg, path)
    assert ok
    return path


def _panel(mod, *, profile="P1", teams=("Inter", "Milan"), typed=None):
    """Pannello nudo (nessun widget): modello con `typed` sopra una baseline vuota."""
    p = mod.GuidedMappingPanel.__new__(mod.GuidedMappingPanel)
    p._on_saved = None
    p._current = profile
    p._team_vars = {t: _Var((typed or {}).get(t, "")) for t in teams}
    p._baseline = {t: "" for t in teams}
    p._status = _Status()
    p._profile_var = _Var(profile or mod._NO_PROFILE)
    p._sport_var = _Var(SPORT)
    p._comp_var = _Var("Comp A")
    p._comp_by_label = {"Comp A": "cid-a", "Comp B": "cid-b"}
    p._comp_menu = _Status()
    p._last_sport = SPORT
    p._last_comp = "Comp A"
    p._competitions_provider = lambda _s: []
    p._teams_provider = lambda _cid: []
    p._render_team_rows = lambda: None
    return p


def _saved_aliases(profile, teams):
    cfg = config_store.load_config(config_store.CONFIG_FILE)
    return existing_aliases_for_teams(
        name_mapping_store.get_entries(cfg, profile), SPORT, list(teams))


def _seed_alias(profile, team_aliases):
    """Scrive su disco (store REALI) alias già esistenti nel profilo, fuori dal pannello —
    simula righe salvate in precedenza o da un'altra scheda («⚽ Calcio», assistente)."""
    from xtrader_bridge.betfair.guided_mapping import merge_team_aliases
    cfg = config_store.load_config(config_store.CONFIG_FILE)
    merged = merge_team_aliases(
        name_mapping_store.get_entries(cfg, profile), SPORT, team_aliases)
    cfg = name_mapping_store.set_entries(cfg, profile, merged)
    _saved, ok = config_store.save_config(cfg, config_store.CONFIG_FILE)
    assert ok


# ── cambio profilo ────────────────────────────────────────────────────────────

def test_cambio_profilo_dirty_autosalva_nel_profilo_lasciato(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})

    p._on_profile_change("P2")

    # il merge è finito su DISCO nel profilo LASCIATO (P1), non in P2.
    assert _saved_aliases("P1", ["Inter", "Milan"]) == {"Inter": "inter fc"}
    assert _saved_aliases("P2", ["Inter", "Milan"]) == {}
    # lo switch è avvenuto e la precompilazione (P2 vuoto) ha azzerato il dirty.
    assert p._current == "P2"
    assert p._dirty() is False


def test_cambio_profilo_pulito_non_scrive(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod)                                  # nessun input: non dirty
    scritture = []
    vero_save = config_store.save_config
    monkeypatch.setattr(config_store, "save_config",
                        lambda *a, **k: (scritture.append(1), vero_save(*a, **k))[1])

    p._on_profile_change("P2")

    assert p._current == "P2"
    assert scritture == []                           # switch pulito: zero save


def test_cambio_profilo_save_fallito_annulla_lo_switch(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    monkeypatch.setattr(config_store, "save_config", lambda cfg, path: (cfg, False))

    p._on_profile_change("P2")

    assert p._current == "P1"                        # switch ANNULLATO
    assert p._profile_var.get() == "P1"              # tendina riportata indietro
    assert p._team_vars["Inter"].get() == "inter fc"  # input ancora a schermo
    assert "❌" in p._status.text


def test_cambio_profilo_config_illeggibile_annulla(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    monkeypatch.setattr(config_store, "load_config",
                        lambda _p: (_ for _ in ()).throw(OSError("boom")))

    p._on_profile_change("P2")

    assert p._current == "P1"
    assert p._team_vars["Inter"].get() == "inter fc"


def test_cambio_profilo_da_nessun_profilo_mantiene_gli_alias(cfg_file, monkeypatch):
    """Nessuna destinazione da auto-salvare: il profilo scelto viene precompilato e il delta
    digitato RI-APPLICATO sopra (CodeRabbit #83) — l'input non è mai azzerato in silenzio e
    lo schermo mostra disco + modifiche."""
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile=None, typed={"Inter": "inter fc"})

    p._on_profile_change("P2")

    assert p._current == "P2"
    assert p._team_vars["Inter"].get() == "inter fc"   # delta digitato ri-applicato
    assert p._dirty() is True                          # ancora da salvare
    assert _saved_aliases("P2", ["Inter"]) == {}       # e niente scritture implicite


def test_da_nessun_profilo_config_illeggibile_annulla_lo_switch(cfg_file, monkeypatch):
    """Fable #83 round 2 (bloccante): nel ramo nessun-profilo un prefill con config
    illeggibile precompilerebbe tutto a VUOTO (schermo senza i mapping esistenti del
    profilo scelto) → «💾 Salva» distruttivo. Come gli altri percorsi: switch ANNULLATO."""
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile=None, typed={"Inter": "inter fc"})
    monkeypatch.setattr(config_store, "load_config",
                        lambda _p: (_ for _ in ()).throw(OSError("boom")))

    p._on_profile_change("P2")

    assert p._current is None                           # switch ANNULLATO
    assert p._profile_var.get() == mod._NO_PROFILE      # tendina riportata indietro
    assert p._team_vars["Inter"].get() == "inter fc"    # input ancora a schermo
    assert "❌" in p._status.text


def test_da_nessun_profilo_prefill_usa_lo_snapshot_del_guard(cfg_file, monkeypatch):
    """Fable #83 round 3 (check-then-use): se il config diventa illeggibile TRA il guard e
    il prefill (lock/antivirus su Windows), la seconda lettura fallita precompilerebbe a
    VUOTO (schermo senza i mapping del profilo → «💾 Salva» distruttivo). Il prefill deve
    riusare lo SNAPSHOT già validato dal guard: una sola lettura."""
    mod = _gui_mod(monkeypatch)
    _seed_alias("P2", {"Milan": "ac milan"})
    p = _panel(mod, profile=None, typed={"Inter": "inter fc"})
    vero_load = config_store.load_config
    esiti = iter([vero_load])                        # 1ª lettura ok, poi il file «si rompe»

    def load_una_volta(path):
        try:
            return next(esiti)(path)
        except StopIteration:
            raise OSError("file lockato")

    monkeypatch.setattr(config_store, "load_config", load_una_volta)

    p._on_profile_change("P2")

    assert p._current == "P2"                        # switch riuscito col solo snapshot
    assert p._team_vars["Milan"].get() == "ac milan"  # prefill DAL guard, non riletto
    assert p._team_vars["Inter"].get() == "inter fc"  # delta ri-applicato


def test_da_nessun_profilo_il_save_non_cancella_i_mapping_esistenti(cfg_file, monkeypatch):
    """CodeRabbit #83 (Major): P2 ha già Milan→«ac milan» su disco. Digito Inter SENZA profilo,
    scelgo P2 e premo «💾 Salva»: il mapping esistente di Milan deve SOPRAVVIVERE (il prefill
    del ramo nessun-profilo lo porta a schermo; senza, il vuoto lo cancellerebbe)."""
    mod = _gui_mod(monkeypatch)
    _seed_alias("P2", {"Milan": "ac milan"})
    p = _panel(mod, profile=None, typed={"Inter": "inter fc"})

    p._on_profile_change("P2")
    assert p._team_vars["Milan"].get() == "ac milan"   # precompilato dal profilo scelto
    p._save()

    assert _saved_aliases("P2", ["Inter", "Milan"]) == {"Inter": "inter fc",
                                                        "Milan": "ac milan"}


def test_autosave_delta_preserva_aggiornamenti_esterni(cfg_file, monkeypatch):
    """CodeRabbit #83 (Major): dopo il prefill un'ALTRA scheda salva Milan→«esterno» in P1.
    L'auto-save allo switch deve scrivere SOLO il delta digitato (Inter): l'istantanea
    completa, col vuoto stantio di Milan, cancellerebbe l'aggiornamento esterno."""
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})   # baseline: tutte vuote
    _seed_alias("P1", {"Milan": "esterno"})                      # scrittura esterna post-prefill

    p._on_profile_change("P2")

    assert _saved_aliases("P1", ["Inter", "Milan"]) == {"Inter": "inter fc",
                                                        "Milan": "esterno"}


def test_autosave_persiste_la_cancellazione_di_un_alias(cfg_file, monkeypatch):
    """Svuotare un alias esistente È un edit (var ≠ baseline): l'auto-save delta-only deve
    persistere la rimozione, come farebbe «💾 Salva nel profilo»."""
    mod = _gui_mod(monkeypatch)
    _seed_alias("P1", {"Inter": "vecchio"})
    p = _panel(mod, profile="P1")
    p._baseline = {"Inter": "vecchio", "Milan": ""}
    p._team_vars["Inter"].set("vecchio")
    p._team_vars["Inter"].set("")                    # l'utente svuota l'alias

    p._on_profile_change("P2")

    assert _saved_aliases("P1", ["Inter"]) == {}     # rimozione persistita


def test_autosave_riuscito_aggiorna_la_baseline(cfg_file, monkeypatch):
    """Fugu/Fable #83: dopo un auto-save riuscito la foto va aggiornata subito — un secondo
    switch prima del prossimo prefill non deve ri-mergiare lo stesso delta."""
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})

    assert p._autosave_leaving(SPORT) is True
    assert p._dirty() is False                       # foto = schermo appena salvato


# ── cambio sport ──────────────────────────────────────────────────────────────

def test_cambio_sport_dirty_salva_con_lo_sport_lasciato(cfg_file, monkeypatch):
    """Quando il `command` scatta la tendina è GIÀ sul nuovo sport: il merge deve usare
    lo sport sotto cui gli alias erano stati digitati (`_last_sport`), non il nuovo."""
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    p._sport_var.set("SportNuovo")                   # menu già cambiato

    p._on_sport_change()

    assert _saved_aliases("P1", ["Inter"]) == {"Inter": "inter fc"}   # sport = SPORT (lasciato)
    assert p._last_sport == "SportNuovo"


def test_cambio_sport_senza_profilo_annullato(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile=None, typed={"Inter": "inter fc"})
    p._sport_var.set("SportNuovo")

    p._on_sport_change()

    assert p._sport_var.get() == SPORT               # tendina riportata allo sport lasciato
    assert p._team_vars["Inter"].get() == "inter fc"
    assert "⛔" in p._status.text


def test_cambio_sport_save_fallito_annullato(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    p._sport_var.set("SportNuovo")
    monkeypatch.setattr(config_store, "save_config", lambda cfg, path: (cfg, False))

    p._on_sport_change()

    assert p._sport_var.get() == SPORT
    assert p._last_sport == SPORT                    # niente avanzamento di stato
    assert p._team_vars["Inter"].get() == "inter fc"
    assert "❌" in p._status.text


def test_cambio_sport_senza_last_sport_fail_closed(cfg_file, monkeypatch):
    """Final review Fable #83: `_last_sport=None` con alias dirty è irraggiungibile nel
    ciclo di vita reale, ma il vecchio fallback avrebbe fatto il merge sotto lo sport
    NUOVO (tendina già cambiata) corrompendo il mapping per-sport. Fail-closed: switch
    annullato, NESSUNA scrittura con sport indovinato."""
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    p._last_sport = None                             # stato anomalo simulato
    p._sport_var.set("SportNuovo")
    scritture = []
    monkeypatch.setattr(config_store, "save_config",
                        lambda cfg, path: (scritture.append(1), (cfg, True))[1])

    p._on_sport_change()

    assert scritture == []                           # nessun merge con sport indovinato
    assert p._team_vars["Inter"].get() == "inter fc"  # input intatto
    assert "❌" in p._status.text


# ── cambio competizione ───────────────────────────────────────────────────────

def test_cambio_competizione_dirty_autosalva_poi_carica(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    p._comp_var.set("Comp B")
    p._teams_provider = lambda cid: ["Juve"] if cid == "cid-b" else []

    p._load_teams()

    assert _saved_aliases("P1", ["Inter"]) == {"Inter": "inter fc"}   # salvato PRIMA del reload
    assert list(p._team_vars) == ["Juve"]                             # poi il nuovo modello
    assert p._last_comp == "Comp B"


def test_riselezione_stessa_competizione_dirty_e_noop(cfg_file, monkeypatch):
    """Ri-selezionare la stessa voce ricaricava e azzerava gli alias: ora è un no-op."""
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    chiamate = []
    p._teams_provider = lambda cid: chiamate.append(cid) or []

    p._load_teams()                                  # _comp_var == _last_comp == "Comp A"

    assert p._team_vars["Inter"].get() == "inter fc"  # modello intatto
    assert chiamate == []                             # nessun reload distruttivo
    assert "ℹ️" in p._status.text


def test_cambio_competizione_senza_profilo_annullato(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile=None, typed={"Inter": "inter fc"})
    p._comp_var.set("Comp B")

    p._load_teams()

    assert p._comp_var.get() == "Comp A"             # tendina riportata indietro
    assert p._team_vars["Inter"].get() == "inter fc"
    assert "⛔" in p._status.text


# ── baseline: prefill e salvataggio esplicito ────────────────────────────────

def test_save_esplicito_azzera_il_dirty(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    assert p._dirty() is True

    p._save()

    assert "💾" in p._status.text
    assert p._dirty() is False                       # baseline aggiornata al salvato
    assert _saved_aliases("P1", ["Inter"]) == {"Inter": "inter fc"}


def test_prefill_scatta_la_foto_baseline(cfg_file, monkeypatch):
    mod = _gui_mod(monkeypatch)
    p = _panel(mod, profile="P1", typed={"Inter": "inter fc"})
    p._save()                                        # su disco: Inter → inter fc

    p._team_vars = {"Inter": _Var(""), "Milan": _Var("")}
    p._prefill_aliases()

    assert p._team_vars["Inter"].get() == "inter fc"  # precompilato dal profilo
    assert p._dirty() is False                        # foto = precompilato
    p._team_vars["Milan"].set("ac milan")
    assert p._dirty() is True                         # input nuovo rilevato
