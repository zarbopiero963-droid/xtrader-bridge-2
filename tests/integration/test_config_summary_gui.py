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
from xtrader_bridge import i18n


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    """Ripristina la lingua a IT dopo ogni test (il teardown post-`yield` gira anche se il test
    fallisce), così lo stato di modulo di `i18n` non trapela verso altri test."""
    yield
    i18n.set_language("IT")


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


# ── Localizzazione EN/ES (#343 slice 4u): gli helper puri rendono la lingua UI corrente ──

def test_mode_label_localizzato(gui_mod):
    """La riga modalità (REALE/Simulazione) si rende nella lingua UI corrente (EN/ES)."""
    i18n.set_language("EN")
    assert gui_mod.mode_label(True) == "🔴 REAL MODE"
    assert gui_mod.mode_label(False) == "🧪 Simulation (DRY_RUN)"
    i18n.set_language("ES")
    assert gui_mod.mode_label(True) == "🔴 MODO REAL"
    assert gui_mod.mode_label(False) == "🧪 Simulación (DRY_RUN)"


def test_betfair_label_localizzato(gui_mod):
    """Lo stato del dizionario locale (presente/vuoto) è tradotto in EN e ES su ENTRAMBI i rami."""
    i18n.set_language("EN")
    assert gui_mod.betfair_label(True) == "Local dictionary: present"
    assert gui_mod.betfair_label(False) == "Local dictionary: empty"
    i18n.set_language("ES")
    assert gui_mod.betfair_label(True) == "Diccionario local: presente"
    assert gui_mod.betfair_label(False) == "Diccionario local: vacío"


def test_translations_label_prefissi_localizzati(gui_mod):
    """I prefissi «Nomi»/«Mercati» si traducono; i simboli ✓/—/· e i conteggi restano."""
    ch = _channel(names=cs.TranslationSummary(resolved=("N1", "N2")),
                  markets=cs.TranslationSummary())
    i18n.set_language("EN")
    assert gui_mod.translations_label(ch) == "Names ✓2 · Markets —"
    i18n.set_language("ES")
    assert gui_mod.translations_label(ch) == "Nombres ✓2 · Mercados —"


def test_readiness_e_conteggi_localizzati(gui_mod):
    """«✅ Pronto», la riga conteggi, il segnaposto canale e lo stato vuoto sono localizzati."""
    i18n.set_language("EN")
    assert gui_mod.readiness_label(_channel(ready=True, reason="")) == "✅ Ready"
    assert gui_mod.ready_count_label(_summary(2, 3)) == "Ready channels: 2/3"
    assert gui_mod.channel_title(_channel(name="", chat_id="")) == "(channel without chat_id)"
    assert gui_mod.no_channels_label() == "No channel configured (no source / chat)."
    i18n.set_language("ES")
    assert gui_mod.ready_count_label(_summary(0, 0)) == "Canales listos: 0/0"
    assert gui_mod.no_channels_label() == "Ningún canal configurado (sin fuente / chat)."


def test_render_inline_keys_localizzate(gui_mod):
    """Le stringhe inline di `_render` (titolo pannello, «Nessun dato …», errore di lettura config
    con `{exc}`) sono chiavi di catalogo tradotte in EN/ES; il template `{exc}` conserva il
    segnaposto e il valore interpolato non viene ri-parsato. La resa dei WIDGET veri di `_render`
    richiede un display → verifica manuale (smoke): aprire 🧰 Strumenti → 📋 Riepilogo in EN/ES e,
    simulando un provider che solleva, controllare il messaggio d'errore tradotto multilinea."""
    for lang, title, nodata, err_prefix in (
            ("EN", "📋 Configuration summary", "No configuration data.",
             "⚠️ Unable to read the configuration:\n"),
            ("ES", "📋 Resumen de configuración", "Sin datos de configuración.",
             "⚠️ No se puede leer la configuración:\n")):
        i18n.set_language(lang)
        assert i18n.tr("📋 Riepilogo configurazione") == title
        assert i18n.tr("Nessun dato di configurazione.") == nodata
        rendered = i18n.tr("⚠️ Impossibile leggere la configurazione:\n{exc}").format(
            exc="PermissionError")
        assert rendered == err_prefix + "PermissionError"


def test_esclusioni_dominio_restano_it(gui_mod):
    """RESTANO IT anche in EN: la riga «Parser: …» (termine prodotto + nomi di dominio) e il MOTIVO
    di «⚠ <motivo>» (testo di dominio da config_summary). I nomi canale/chat_id sono domìnio."""
    i18n.set_language("EN")
    # riga parser: invariata (nessuna parola da tradurre, solo prodotto + nomi)
    assert gui_mod.parser_label(_channel(parser_name="P1", parser_loaded=True)) == "Parser: P1"
    assert gui_mod.parser_label(_channel(parser_name="")) == "Parser: —"
    # motivo bubblato dal layer puro: resta IT (solo «✅ Pronto» è tradotto)
    notready = _channel(ready=False, reason=cs.REASON_NO_PARSER)
    assert gui_mod.readiness_label(notready) == f"⚠ {cs.REASON_NO_PARSER}"
    # nome canale = valore di dominio, non tradotto
    assert gui_mod.channel_title(_channel(name="Canale A", chat_id="100")) == "Canale A (100)"
