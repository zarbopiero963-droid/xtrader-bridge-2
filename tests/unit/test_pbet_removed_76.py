"""P3-15 audit #76 — RIMOZIONE del modulo P.Bet hardcoded (decisione del proprietario).

`xtrader_bridge/parser.py` (~390 righe, `parse_message` + regex P.Bet) era fuori dal
flusso live da CP-09b (senza Parser Personalizzato attivo il messaggio è IGNORATO)
ma restava nel repo «per compatibilità/test»: codice morto attivo, superficie di
manutenzione e ambiguità («quale parser gira?»). Rimosso.

Guardia anti-reintroduzione (fail-first: ROSSA prima della rimozione):
- il modulo NON deve più esistere né essere importabile;
- l'invariante live resta: nessun custom attivo → messaggio ignorato, nessuna riga
  (era già il comportamento CP-09b, qui pinnato dopo la rimozione)."""

import importlib

import pytest

from xtrader_bridge import signal_router


def test_modulo_parser_rimosso():
    """FAIL-FIRST: prima della rimozione l'import riusciva (modulo morto attivo)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("xtrader_bridge.parser")


def test_live_senza_custom_resta_ignorato(tmp_path):
    """L'invariante CP-09b sopravvive alla rimozione: nessun parser custom attivo →
    il messaggio (formato P.Bet reale) NON produce righe — ignorato, non parsato
    da alcun hardcoded."""
    res = signal_router.resolve_row(
        "P.Bet. OVER 2.5 LIVE\nInter v Milan\nQuota 1,85",
        {}, parsers_dir=str(tmp_path))

    assert res.row is None
    assert res.status == signal_router.NO_PARSER
    assert res.detail == "no_active_parser"
