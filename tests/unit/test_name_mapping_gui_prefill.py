"""Test della glue `NameMappingPanel._prefill_betfair_names` (#282 PR 11).

Il pannello «⚽ Calcio» del Mapping può precompilare la colonna Betfair coi nomi squadra
PERMANENTI raccolti dalla sync Betfair (#319): una riga per nome noto, Betfair FISSO
scritto nel campo, Sport impostato, tipo `team`, Provider vuoto (lo compila l'utente).

`name_mapping_gui` richiede `customtkinter` (un display) e NON è importabile headless:
qui stubbiamo SOLO la libreria GUI con classi reali vuote, così il modulo si importa e
possiamo esercitare il VERO metodo su un `self` finto (widget/provider simulati), senza
creare widget veri. La logica sotto test è quella reale del pannello (dedup normalizzato,
fail-safe senza dizionario, righe aggiunte non distruttive).
"""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def NameMappingPanel(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.name_mapping_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.name_mapping_gui")
    return mod.NameMappingPanel


def _row(sport_label, betfair):
    """Riga finta come quelle in `_row_widgets`: `["sport"].get()` = etichetta tendina,
    `["betfair"].get()` = testo del campo Betfair."""
    return {"sport": types.SimpleNamespace(get=lambda: sport_label),
            "betfair": types.SimpleNamespace(get=lambda: betfair)}


def _fake_self(*, current="profilo1", teams=None, rows=None):
    added, status = [], []
    fake = types.SimpleNamespace(
        _current=current,
        _row_widgets=list(rows or []),
        _known_teams_provider=(None if teams is None else (lambda: teams)),
        _append_row_widget=lambda **k: added.append(k),
        _status=types.SimpleNamespace(configure=lambda **k: status.append(k)),
    )
    return fake, added, status


def _call(NameMappingPanel, fake):
    NameMappingPanel._prefill_betfair_names(fake)


# ── caso base: precompila i nomi noti ─────────────────────────────────────────

def test_prefill_aggiunge_una_riga_per_nome(NameMappingPanel):
    teams = [{"sport": "Calcio", "display_name": "Inter"},
             {"sport": "Calcio", "display_name": "Milan"}]
    fake, added, status = _fake_self(teams=teams)
    _call(NameMappingPanel, fake)
    # una riga per nome: Betfair FISSO, Sport impostato, tipo team, Provider NON passato (vuoto)
    assert added == [
        {"betfair": "Inter", "sport": "Calcio", "entity_type": "team"},
        {"betfair": "Milan", "sport": "Calcio", "entity_type": "team"},
    ]
    assert "provider" not in added[0]                      # l'alias lo scrive l'utente
    assert "Aggiunti 2" in status[-1]["text"]


def test_prefill_dedup_normalizzato_non_duplica(NameMappingPanel):
    # Una riga esiste già con "Inter" (Calcio): un nome noto che normalizza uguale è saltato.
    teams = [{"sport": "Calcio", "display_name": "  inter  "},   # stesso nome, grafia diversa
             {"sport": "Calcio", "display_name": "Milan"}]
    fake, added, status = _fake_self(teams=teams, rows=[_row("Calcio", "Inter")])
    _call(NameMappingPanel, fake)
    assert [a["betfair"] for a in added] == ["Milan"]      # Inter saltato (già presente)
    assert "Aggiunti 1" in status[-1]["text"] and "1 già presenti" in status[-1]["text"]


def test_prefill_stesso_nome_altro_sport_non_e_duplicato(NameMappingPanel):
    # "Napoli" esiste per Calcio; un ipotetico "Napoli" di altro sport NON è lo stesso
    # (chiave = sport + nome), quindi verrebbe aggiunto.
    teams = [{"sport": "Basket", "display_name": "Napoli"}]
    fake, added, _ = _fake_self(teams=teams, rows=[_row("Calcio", "Napoli")])
    _call(NameMappingPanel, fake)
    assert added == [{"betfair": "Napoli", "sport": "Basket", "entity_type": "team"}]


# ── fail-safe ─────────────────────────────────────────────────────────────────

def test_prefill_senza_profilo_non_aggiunge(NameMappingPanel):
    fake, added, status = _fake_self(current=None, teams=[{"sport": "Calcio", "display_name": "Inter"}])
    _call(NameMappingPanel, fake)
    assert added == []
    assert "profilo" in status[-1]["text"].lower()


def test_prefill_senza_provider_avvisa(NameMappingPanel):
    fake, added, status = _fake_self(teams=None)           # provider assente (None)
    _call(NameMappingPanel, fake)
    assert added == []
    assert "non disponibile" in status[-1]["text"]


def test_prefill_dizionario_vuoto_avvisa(NameMappingPanel):
    fake, added, status = _fake_self(teams=[])             # sync mai fatta / nessun nome
    _call(NameMappingPanel, fake)
    assert added == []
    assert "vuoto" in status[-1]["text"] or "Nessun nuovo" in status[-1]["text"]


def test_prefill_provider_che_solleva_non_crasha(NameMappingPanel):
    fake, added, status = _fake_self()
    def _boom():
        raise RuntimeError("db locked")
    fake._known_teams_provider = _boom
    _call(NameMappingPanel, fake)                          # nessuna eccezione propagata
    assert added == []
    assert "non leggibili" in status[-1]["text"]


def test_prefill_nome_vuoto_saltato(NameMappingPanel):
    teams = [{"sport": "Calcio", "display_name": "   "},
             {"sport": "Calcio", "display_name": "Roma"}]
    fake, added, _ = _fake_self(teams=teams)
    _call(NameMappingPanel, fake)
    assert [a["betfair"] for a in added] == ["Roma"]        # il nome vuoto non genera riga


# ── busy durante sync + contratto reale known_teams (#321) ────────────────────

def test_prefill_sync_in_corso_avvisa(NameMappingPanel):
    # Se il provider segnala una sync in corso (DictionaryBusy), il pannello avvisa
    # «riprova» invece di congelarsi o dire «vuoto» (fix freeze GUI, CodeRabbit #321).
    from xtrader_bridge.betfair.dictionary_viewer import DictionaryBusy
    fake, added, status = _fake_self()
    def _busy():
        raise DictionaryBusy()
    fake._known_teams_provider = _busy
    _call(NameMappingPanel, fake)
    assert added == []
    assert "in corso" in status[-1]["text"]


def test_prefill_consuma_contratto_reale_known_teams(NameMappingPanel):
    # Seam PR10↔PR11 (review GLM/GPT): i record REALI di BetfairLocalDB.known_teams()
    # hanno le chiavi che _prefill consuma (sport + display_name) e lo `sport` è il NOME
    # canonico accettato dalla tendina Sport della GUI (`sports.SPORTS`).
    from xtrader_bridge.betfair.local_db import BetfairLocalDB
    from xtrader_bridge import sports
    db = BetfairLocalDB(":memory:")
    db.upsert_known_team("Calcio", "Inter", seen_at=1)
    db.upsert_known_team("Basket", "Lakers", seen_at=1)
    teams = db.known_teams()
    db.close()
    fake, added, _ = _fake_self(teams=teams)
    _call(NameMappingPanel, fake)
    for a in added:
        assert a["sport"] in sports.SPORTS           # sport valido per la tendina GUI
        assert a["entity_type"] == "team"
    assert {(a["sport"], a["betfair"]) for a in added} == {("Calcio", "Inter"), ("Basket", "Lakers")}
