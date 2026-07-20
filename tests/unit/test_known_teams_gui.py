"""Test della glue della scheda «🧹 Nomi Betfair» (`KnownTeamsPanel`, #282 PR 11-bis).

`known_teams_gui` importa `customtkinter` (un display) e non è importabile headless: qui
stubbiamo SEMPRE la libreria GUI con widget no-op (così `_refresh`/`_append_row` che
COSTRUISCONO widget non crashano senza root Tk), ed esercitiamo i VERI metodi del pannello
su un `self` finto (provider/delete simulati). La logica sotto test è quella reale: elenco,
eliminazione + ricarica, fail-fast «Dizionario occupato» (DictionaryBusy), fail-safe senza provider.
"""

import importlib
import sys
import types

import pytest

from xtrader_bridge.betfair.dictionary_viewer import DictionaryBusy


class _Widget:
    # Registra le `command=` dei widget costruiti (per testare il wiring del pulsante 🗑).
    commands = []

    def __init__(self, *a, **k):
        cmd = k.get("command")
        if callable(cmd):
            _Widget.commands.append(cmd)

    def __getattr__(self, _name):
        return lambda *a, **k: _Widget()


class _FakeCtkModule(types.ModuleType):
    def __getattr__(self, name):
        setattr(self, name, _Widget)
        return _Widget


@pytest.fixture(autouse=True)
def _reset_widget_commands():
    # `_Widget.commands` è uno stato di classe condiviso (registra le command dei widget
    # costruiti nei test): azzeralo PRIMA di ogni test così non accumula residui tra test
    # (nessuna flakiness/falso positivo nel test del wiring 🗑) — review GLM/Fable #322.
    _Widget.commands.clear()
    yield
    _Widget.commands.clear()


@pytest.fixture()
def KnownTeamsPanel(monkeypatch):
    # Stub SEMPRE customtkinter (anche se installato): `_refresh` costruisce widget/font Tk
    # che senza root crashano headless. monkeypatch ripristina a fine test.
    monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.known_teams_gui", raising=False)
    mod = importlib.import_module("xtrader_bridge.known_teams_gui")
    # AC-M12 #114: `_on_delete` ora chiede conferma (fail-closed → False headless). Per i test
    # che verificano il percorso di eliminazione, si conferma di default; il test dedicato alla
    # conferma sovrascrive questo stub con `False`.
    monkeypatch.setattr(mod.gui_utils, "ask_confirm", lambda *a, **k: True)
    return mod.KnownTeamsPanel


def _fake_self(*, sport="(tutti gli sport)", teams=None, provider=None, deleter=None):
    counts, deleted = [], []

    def _default_delete(s, n):
        deleted.append((s, n))
        return True                            # successo: come App._delete_betfair_team

    fake = types.SimpleNamespace(
        _sport=types.SimpleNamespace(get=lambda: sport),
        _teams_provider=provider if provider is not None else (
            None if teams is None else (lambda s=None: teams)),
        _delete_team=deleter if deleter is not None else _default_delete,
        _rows_frame=_Widget(),
        _counts=types.SimpleNamespace(configure=lambda **k: counts.append(k)),
    )
    return fake, counts, deleted


def _bind(KnownTeamsPanel, fake):
    for name in ("_selected_sport", "_refresh", "_append_row", "_on_delete"):
        setattr(fake, name, types.MethodType(getattr(KnownTeamsPanel, name), fake))
    fake._clear_rows = lambda: None


# ── elenco ────────────────────────────────────────────────────────────────────

def test_refresh_elenca_i_nomi(KnownTeamsPanel):
    teams = [{"sport": "Calcio", "display_name": "Inter", "normalized_name": "inter"},
             {"sport": "Calcio", "display_name": "Milan", "normalized_name": "milan"}]
    fake, counts, _ = _fake_self(teams=teams)
    _bind(KnownTeamsPanel, fake)
    fake._refresh()
    assert "2 nomi noti" in counts[-1]["text"]


def test_refresh_filtra_per_sport(KnownTeamsPanel):
    seen = {}
    def _provider(sport=None):
        seen["sport"] = sport
        return []
    fake, counts, _ = _fake_self(sport="Calcio", provider=_provider)
    _bind(KnownTeamsPanel, fake)
    fake._refresh()
    assert seen["sport"] == "Calcio"          # filtro passato al provider (non «(tutti)»)


def test_refresh_senza_provider_avvisa(KnownTeamsPanel):
    fake, counts, _ = _fake_self(provider=None, teams=None)
    _bind(KnownTeamsPanel, fake)
    fake._refresh()
    assert "non disponibile" in counts[-1]["text"]


def test_refresh_db_occupato_avvisa(KnownTeamsPanel):
    def _busy(sport=None):
        raise DictionaryBusy()
    fake, counts, _ = _fake_self(provider=_busy)
    _bind(KnownTeamsPanel, fake)
    fake._refresh()
    assert "occupato" in counts[-1]["text"]


# ── eliminazione ────────────────────────────────────────────────────────────────

def test_on_delete_elimina_e_ricarica(KnownTeamsPanel):
    teams = [{"sport": "Calcio", "display_name": "Inter", "normalized_name": "inter"}]
    fake, counts, deleted = _fake_self(teams=teams)
    _bind(KnownTeamsPanel, fake)
    fake._on_delete("Calcio", "inter")
    assert deleted == [("Calcio", "inter")]   # delete chiamato con la chiave giusta
    # dopo la delete il pannello ricarica (refresh → riga conteggi aggiornata)
    assert counts and "nomi noti" in counts[-1]["text"]


def test_on_delete_fallita_db_assente_avvisa_non_ricarica(KnownTeamsPanel):
    # delete_team ritorna False (DB non disponibile): il pannello AVVISA invece di
    # ricaricare «pulito» nascondendo il no-op (CodeRabbit/GPT/Fable #322).
    fake, counts, _ = _fake_self(deleter=lambda s, n: False)
    _bind(KnownTeamsPanel, fake)
    refreshed = []
    fake._refresh = lambda: refreshed.append(True)   # spia: _on_delete NON deve ricaricare
    fake._on_delete("Calcio", "inter")
    assert "non riuscita" in counts[-1]["text"]
    assert refreshed == []                            # niente refresh sul fallimento (GLM #322)


def test_append_row_pulsante_elimina_usa_normalized_name(KnownTeamsPanel):
    # Il pulsante 🗑 deve chiamare _on_delete con la `normalized_name` della riga, NON il
    # `display_name` (il DB elimina per chiave normalizzata: display_name → no-op silenzioso)
    # — review GPT #322.  (`_Widget.commands` è azzerato dalla fixture autouse.)
    fake, counts, deleted = _fake_self()
    _bind(KnownTeamsPanel, fake)
    fake._append_row({"sport": "Calcio", "display_name": "Inter FC",
                      "normalized_name": "inter fc"})
    assert _Widget.commands, "la riga deve creare un pulsante Elimina con una command"
    _Widget.commands[-1]()                      # simula il click sul 🗑
    assert deleted == [("Calcio", "inter fc")]  # normalized_name, NON "Inter FC"


def test_on_delete_db_occupato_avvisa_non_elimina(KnownTeamsPanel):
    def _deleter(s, n):
        raise DictionaryBusy()
    fake, counts, _ = _fake_self(deleter=_deleter)
    _bind(KnownTeamsPanel, fake)
    fake._on_delete("Calcio", "inter")
    assert "occupato" in counts[-1]["text"]


def test_on_delete_richiede_conferma_e_annullo_non_elimina(KnownTeamsPanel, monkeypatch):
    """AC-M12 audit #114: l'eliminazione di un nome PERMANENTE deve chiedere conferma;
    se l'utente ANNULLA (o il dialog è fail-closed headless) NON si elimina nulla e si
    avvisa. Prima del fix: eliminazione a un solo click, senza conferma."""
    import xtrader_bridge.known_teams_gui as kt
    monkeypatch.setattr(kt.gui_utils, "ask_confirm", lambda *a, **k: False)   # annulla
    fake, counts, deleted = _fake_self()
    _bind(KnownTeamsPanel, fake)
    refreshed = []
    fake._refresh = lambda: refreshed.append(True)
    fake._on_delete("Calcio", "inter")
    assert deleted == []                              # NIENTE eliminazione
    assert refreshed == []                            # niente refresh
    assert "annullat" in counts[-1]["text"].lower()   # avviso di annullamento


def test_on_delete_conferma_positiva_elimina(KnownTeamsPanel, monkeypatch):
    """AC-M12: conferma positiva → l'eliminazione procede come prima (la fixture conferma
    già di default; qui esplicito per chiarezza dell'invariante)."""
    import xtrader_bridge.known_teams_gui as kt
    monkeypatch.setattr(kt.gui_utils, "ask_confirm", lambda *a, **k: True)
    fake, counts, deleted = _fake_self()
    _bind(KnownTeamsPanel, fake)
    fake._on_delete("Calcio", "inter")
    assert deleted == [("Calcio", "inter")]


def test_on_delete_senza_callback_avvisa(KnownTeamsPanel):
    fake, counts, _ = _fake_self()
    fake._delete_team = None                   # nessuna callback di eliminazione iniettata
    _bind(KnownTeamsPanel, fake)
    fake._on_delete("Calcio", "inter")
    assert "non disponibile" in counts[-1]["text"]
