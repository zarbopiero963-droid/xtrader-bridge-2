"""#94 (Codex P2): applicando un profilo, le schede Strumenti già costruite (Provider, Chat
sorgenti, Mapping, Betfair Sync) vengono ricaricate dal disco. Un refresh() FALLITO non deve
essere ingoiato in silenzio (`except Exception: pass`): il caricamento del profilo logga
comunque successo, quindi una scheda stantia senza avviso ingannerebbe l'utente. Ora ogni
refresh fallito è LOGGATO (best-effort: il load non crasha).

Test headless via `make_app`: esercita il metodo REALE
`App._refresh_tool_panels_after_profile`. Fail-first: su una `refresh()` che solleva, il
vecchio codice NON loggava nulla; ora deve loggare un warning nominando la scheda.
"""


class _OkPanel:
    """Pannello Strumenti finto: `refresh()` riesce e conta le chiamate."""

    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


class _BoomPanel:
    """Pannello Strumenti finto: `refresh()` solleva (dir illeggibile, config corrotta…)."""

    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1
        raise OSError("config illeggibile")


class _BfBoom:
    """Pannello Betfair finto: `refresh_autosync()` solleva."""

    def refresh_autosync(self, *a, **k):
        raise RuntimeError("db bloccato")


def test_refresh_ok_non_logga_e_chiama_tutti(make_app):
    a = make_app(running=False)
    prov, src, mapp = _OkPanel(), _OkPanel(), _OkPanel()
    panel_refs = {"provider": prov, "sources": src, "mapping": mapp}
    a._betfair_panel = None
    a._refresh_tool_panels_after_profile(panel_refs, {})
    assert prov.refreshed == 1 and src.refreshed == 1 and mapp.refreshed == 1
    assert a.logs == []                              # nessun warning se tutto ok


def test_refresh_fallito_logga_la_scheda_stantia(make_app):
    """FAIL-FIRST: sul vecchio `except Exception: pass` questo warning NON veniva emesso."""
    a = make_app(running=False)
    prov, src = _BoomPanel(), _OkPanel()             # Provider fallisce, Sorgenti ok
    panel_refs = {"provider": prov, "sources": src, "mapping": None}
    a._betfair_panel = None
    a._refresh_tool_panels_after_profile(panel_refs, {})   # NON deve sollevare
    assert prov.refreshed == 1                        # ci ha provato
    assert src.refreshed == 1                         # una scheda fallita non ferma le altre
    warn = [m for m in a.logs if "Provider non aggiornata" in m]
    assert len(warn) == 1                             # loggato, non ingoiato
    assert "config illeggibile" in warn[0]           # con la causa
    assert not any("Chat sorgenti" in m for m in a.logs)   # la scheda ok non logga


def test_refresh_betfair_fallito_logga(make_app):
    a = make_app(running=False)
    a._betfair_panel = _BfBoom()
    a._refresh_tool_panels_after_profile({}, {"betfair_auto_sync": True})  # NON deve sollevare
    warn = [m for m in a.logs if "Betfair Sync non aggiornata" in m]
    assert len(warn) == 1
    assert "db bloccato" in warn[0]


def test_refresh_pannelli_assenti_no_op(make_app):
    """Nessun pannello costruito (panel_refs vuoto, betfair assente): no-op, nessun log."""
    a = make_app(running=False)
    a._betfair_panel = None
    a._refresh_tool_panels_after_profile({}, {})
    assert a.logs == []
