"""Helper puri di presentazione del pannello «📋 Riepilogo» (#293 slice 3).

Il pannello GUI vero richiede un display (verifica manuale su Windows), ma le decisioni di
testo/colore vivono in helper puri a livello di modulo: qui si importano con `customtkinter`
stubbato e si esercitano su `ConfigSummary`/`ChannelSummary` reali. Ancora anti-regressione
sull'etichetta modalità/Betfair/traduzioni/«Pronto?».
"""

import importlib
import sys
import types

import pytest

from xtrader_bridge import config_summary as cs


@pytest.fixture
def gui_mod(monkeypatch):
    fake = types.ModuleType("customtkinter")
    fake.__getattr__ = lambda _n: object
    monkeypatch.setitem(sys.modules, "customtkinter", fake)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.config_summary_gui", raising=False)
    return importlib.import_module("xtrader_bridge.config_summary_gui")


def _channel(**kw):
    base = dict(chat_id="100", name="Canale A", enabled=True, parser_name="P1",
                parser_loaded=True, names=cs.TranslationSummary(), markets=cs.TranslationSummary(),
                ready=True, reason="")
    base.update(kw)
    return cs.ChannelSummary(**base)


def test_mode_label_e_colore(gui_mod):
    assert gui_mod.mode_label(True) == "🔴 MODALITÀ REALE"
    assert "Simulazione" in gui_mod.mode_label(False)
    # Colori distinti reale vs simulazione (theme-aware tuple).
    assert gui_mod.mode_color(True) != gui_mod.mode_color(False)


def test_betfair_label(gui_mod):
    assert gui_mod.betfair_label(True) == "Dizionario locale: presente"
    assert gui_mod.betfair_label(False) == "Dizionario locale: vuoto"


def test_translations_label(gui_mod):
    ch = _channel(names=cs.TranslationSummary(resolved=("N1", "N2")),
                  markets=cs.TranslationSummary())
    assert gui_mod.translations_label(ch) == "Nomi ✓2 · Mercati —"
    ch2 = _channel(names=cs.TranslationSummary(),
                   markets=cs.TranslationSummary(resolved=("M1",)))
    assert gui_mod.translations_label(ch2) == "Nomi — · Mercati ✓1"


def test_readiness_label_e_colore(gui_mod):
    ready = _channel(ready=True, reason="")
    notready = _channel(ready=False, reason=cs.REASON_NO_PARSER)
    assert gui_mod.readiness_label(ready) == "✅ Pronto"
    assert gui_mod.readiness_label(notready) == f"⚠ {cs.REASON_NO_PARSER}"
    assert gui_mod.readiness_color(ready) != gui_mod.readiness_color(notready)


def test_channel_title(gui_mod):
    assert gui_mod.channel_title(_channel(name="A", chat_id="100")) == "A (100)"
    assert gui_mod.channel_title(_channel(name="", chat_id="100")) == "100"
    assert gui_mod.channel_title(_channel(name="", chat_id="")) == "(canale senza chat_id)"


def test_parser_label(gui_mod):
    assert gui_mod.parser_label(_channel(parser_name="P1", parser_loaded=True)) == "Parser: P1"
    assert gui_mod.parser_label(_channel(parser_name="")) == "Parser: —"
    # CodeRabbit #337: parser risolto ma NON caricabile → ⚠ sulla riga parser stessa.
    assert gui_mod.parser_label(
        _channel(parser_name="P1", parser_loaded=False)) == "Parser: P1 ⚠"
    # PR-2 (router multi-parser): più parser sulla chat → lista numerata per priorità.
    assert gui_mod.parser_label(
        _channel(parser_name="A", parser_names=("A", "B"), parser_loaded=True)) == "Parser (2): A, B"
    # ⚠ sul primario anche in multi (primario non caricabile).
    assert gui_mod.parser_label(
        _channel(parser_name="A", parser_names=("A", "B"), parser_loaded=False)) == "Parser (2): A, B ⚠"
    # Fable #391: ⚠ anche se il primario carica ma un SECONDARIO no (bet persi in silenzio).
    assert gui_mod.parser_label(_channel(
        parser_name="A", parser_names=("A", "B"), parser_loaded=True,
        parser_names_unloaded=("B",))) == "Parser (2): A, B ⚠"


def _summary(ready, total):
    chans = tuple(
        cs.ChannelSummary(chat_id=str(i), name="", enabled=True, parser_name="P",
                          parser_loaded=True, ready=(i < ready))
        for i in range(total))
    return cs.ConfigSummary(real_mode=False, betfair_synced=False, channels=chans)


def test_ready_count_label(gui_mod):
    assert gui_mod.ready_count_label(_summary(2, 3)) == "Canali pronti: 2/3"
    assert gui_mod.ready_count_label(_summary(0, 0)) == "Canali pronti: 0/0"


def test_no_channels_label(gui_mod):
    assert gui_mod.no_channels_label() == "Nessun canale configurato (nessuna sorgente / chat)."
