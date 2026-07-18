"""P3-2 + P3-3 audit #76 — lingua CSV congelata a START e auto-start multi-parser.

- **P3-2**: `set_csv_language` è chiamata da `config_store.load_config`/`save_config`
  anche quando si carica un PROFILO a sessione ATTIVA: il separatore decimale del CSV
  cambiava a metà sessione (righe «1.85» in un file che XTrader stava leggendo come
  virgola). Fix: `freeze_csv_language()` a START — la sessione scrive SEMPRE con la
  lingua dello snapshot; `unfreeze_csv_language()` a STOP riabilita la lingua base.
- **P3-3**: `autostart._has_admitted_chat` ignorava `parser_list_by_chat` (router
  multi-parser PR-2): config valida SOLO via lista multi-parser → auto-start rifiutato
  in silenzio («nessuna chat sorgente attiva») mentre lo START manuale partiva.

Funzioni REALI (csv_writer, config_store su file tmp, autostart); wiring `_start`/`_stop`
pinnato in modo strutturale sul sorgente (pattern #311 per codice non headless)."""

import json
import re

import pytest

from xtrader_bridge import autostart, config_store, csv_writer


@pytest.fixture(autouse=True)
def _lingua_pulita():
    """Ripristina lingua base e freeze dopo ogni test (stato di modulo condiviso)."""
    prev = csv_writer.get_csv_language()
    yield
    csv_writer.unfreeze_csv_language()
    csv_writer.set_csv_language(prev)


# ── P3-2: freeze della lingua di sessione ────────────────────────────────────────────

def test_lingua_congelata_ignora_il_cambio_a_meta_sessione():
    """FAIL-FIRST: pre-patch non esisteva il freeze — un set a metà sessione cambiava
    subito il separatore decimale delle scritture."""
    csv_writer.set_csv_language("IT")
    csv_writer.freeze_csv_language()                       # START

    csv_writer.set_csv_language("EN")                      # profilo caricato a metà sessione

    assert csv_writer.get_csv_language() == "IT"           # la sessione resta IT
    riga = csv_writer.localize_row({"Price": "1.85"})
    assert riga["Price"] == "1,85"                         # virgola: separatore di sessione


def test_unfreeze_riapplica_la_lingua_base():
    csv_writer.set_csv_language("IT")
    csv_writer.freeze_csv_language()
    csv_writer.set_csv_language("EN")

    csv_writer.unfreeze_csv_language()                     # STOP

    assert csv_writer.get_csv_language() == "EN"           # dal prossimo START vale EN
    assert csv_writer.localize_row({"Price": "1.85"})["Price"] == "1.85"


def test_load_config_reale_non_buca_il_freeze(tmp_path):
    """Il percorso REALE del bug: `config_store.load_config` (profilo/tools) chiama
    `set_csv_language` — con la sessione attiva NON deve toccare le scritture."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"csv_language": "EN"}), encoding="utf-8")
    csv_writer.set_csv_language("IT")
    csv_writer.freeze_csv_language()                       # sessione attiva in IT

    config_store.load_config(str(cfg_file))                # carica profilo EN a metà sessione

    assert csv_writer.get_csv_language() == "IT"           # sessione intatta
    csv_writer.unfreeze_csv_language()
    assert csv_writer.get_csv_language() == "EN"           # base aggiornata: prossimo START


def test_freeze_idempotente_e_riallineato():
    csv_writer.set_csv_language("ES")
    assert csv_writer.freeze_csv_language() == "ES"
    csv_writer.set_csv_language("EN")
    assert csv_writer.freeze_csv_language() == "EN"        # ri-freeze = nuovo snapshot
    csv_writer.unfreeze_csv_language()
    csv_writer.unfreeze_csv_language()                     # doppio unfreeze: nessun errore


def _corpo_metodo(sorgente: str, nome: str) -> str:
    """Corpo del metodo `nome` dal testo di app.py (senza importare la GUI: app
    richiede tkinter, assente in CI unit — pattern sorgente-pinnato #311)."""
    m = re.search(rf"\n    def {nome}\(self.*?(?=\n    def )", sorgente, re.DOTALL)
    assert m, f"metodo {nome} non trovato in app.py"
    return m.group(0)


def test_wiring_start_stop_pinnato_nel_sorgente():
    """Wiring app (#311, codice non headless): `_start` congela DOPO lo snapshot di
    modalità e PRIMA del thread bot; `_stop` scongela. Regressione bloccata: rimuovere
    una delle due chiamate fa fallire qui."""
    import pathlib
    import xtrader_bridge
    sorgente = (pathlib.Path(xtrader_bridge.__path__[0]) / "app.py").read_text(encoding="utf-8")
    src_start = _corpo_metodo(sorgente, "_start")
    src_stop = _corpo_metodo(sorgente, "_stop")

    assert "csv_writer.freeze_csv_language()" in src_start
    # ordine: snapshot modalità → freeze → thread bot
    assert (src_start.index("_session_mode")
            < src_start.index("freeze_csv_language")
            < src_start.index("_bot_thread"))
    assert "csv_writer.unfreeze_csv_language()" in src_stop


# ── P3-3: auto-start con sola lista multi-parser ─────────────────────────────────────

def _cfg_multi(lista):
    return {"auto_start_listener": True, "bot_token": "123:abc",
            "parser_list_by_chat": lista}


def test_autostart_parte_con_sola_lista_multiparser():
    """FAIL-FIRST: pre-patch questa config (valida per lo START manuale: il router
    approva le chat di parser_list_by_chat) veniva rifiutata in silenzio."""
    ok, reason = autostart.can_auto_start(_cfg_multi({"-100123": ["ParserA", "ParserB"]}))
    assert ok is True and reason == ""


def test_autostart_lista_malformata_resta_fail_closed():
    """Config manomessa: voci non-lista o liste vuote sono scartate dall'accessor —
    non devono bastare per l'avvio automatico."""
    for lista in ({}, {"-100123": "non-una-lista"}, {"-100123": []},
                  {"-100123": ["", "  "]}, "non-un-dict"):
        ok, reason = autostart.can_auto_start(_cfg_multi(lista))
        assert ok is False
        assert reason == "nessuna chat sorgente attiva configurata"


def test_autostart_criteri_esistenti_invariati():
    """Regressione bloccata: chat singola / override single-parser / sorgente attiva
    continuano ad ammettere come prima."""
    base = {"auto_start_listener": True, "bot_token": "123:abc"}
    assert autostart.can_auto_start({**base, "chat_id": "-100"})[0] is True
    assert autostart.can_auto_start({**base, "parser_by_chat": {"-100": "P"}})[0] is True
    assert autostart.can_auto_start(base)[0] is False      # nessun criterio → rifiuto
