"""#97: la sentinella "nessun override" del pannello Chat sorgenti non deve collidere col
valore di una riga (Codex P2). Logica pura testata headless (customtkinter stubbato se assente):
il modulo GUI di per sé non gira in CI, ma `_none_sentinel`/`_no_parser_label` sono pure."""

import importlib
import sys
import types

import pytest


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo è una classe vuota, così il modulo GUI si
    importa headless e si possono esercitare le funzioni pure."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture
def scg(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.source_chats_gui", raising=False)
    return importlib.import_module("xtrader_bridge.source_chats_gui")


def test_no_parser_label_evita_override_danglante(scg):
    P = scg.SourceChatsPanel
    # Collapse (#97): il parser reale "(predefinito)" è stato cancellato, ma una riga lo tiene
    # ancora come override → la sentinella NON deve collidere col suo valore (altrimenti al
    # salvataggio l'override verrebbe scambiato per "nessun override" e azzerato).
    label = P._no_parser_label(["MapParser"], ["(predefinito)"])
    assert label != "(predefinito)"
    # Nessun override → sentinella base.
    assert P._no_parser_label(["MapParser"], []) == "(predefinito)"
    # Valori vuoti (= nessun override) sono ignorati.
    assert P._no_parser_label(["MapParser"], ["", "  "]) == "(predefinito)"
    # Forward (thread già risolto): esiste un parser reale "(predefinito)" → sentinella disambiguata.
    assert P._no_parser_label(["(predefinito)"], []) != "(predefinito)"


def test_no_parser_label_stabile_senza_collisioni(scg):
    P = scg.SourceChatsPanel
    # Nessun nome/override collide con la base → resta esattamente "(predefinito)" (nessuno
    # spazio superfluo che confonderebbe l'utente).
    assert P._no_parser_label(["Alpha", "Beta"], ["Alpha"]) == "(predefinito)"


def test_parsers_summary_lista(scg):
    # PR-2: riassunto della lista di parser per il bottone di riga (puro/testabile).
    f = scg._parsers_summary
    assert f([], "(predefinito)") == "(predefinito)"              # vuota → sentinella
    assert f(["A"], "(predefinito)") == "1. A"                    # un parser numerato
    assert f(["A", "B"], "(predefinito)") == "1. A · 2. B"        # ordine di priorità
    assert f([" A ", "", "A", "B"], "(predefinito)") == "1. A · 2. B"   # pulizia + dedup
