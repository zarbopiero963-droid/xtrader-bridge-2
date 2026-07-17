"""#94 (Codex P2): applicando un profilo, le schede Strumenti già costruite (Provider, Chat
sorgenti, Mapping) vengono ricaricate dal disco. Un refresh() FALLITO non deve
essere ingoiato in silenzio (`except Exception: pass`): il caricamento del profilo logga
comunque successo, quindi una scheda stantia senza avviso ingannerebbe l'utente. Ora ogni
refresh fallito è LOGGATO (best-effort: il load non crasha).

Test headless via `make_app`: esercita il metodo REALE
`App._refresh_tool_panels_after_profile`. Fail-first: su una `refresh()` che solleva, il
vecchio codice NON loggava nulla; ora deve loggare un warning nominando la scheda.
"""


class _OkPanel:
    """Pannello Strumenti finto: `refresh(cfg)` riesce e registra la config ricevuta
    (contratto P3-7 #76: i pannelli ricevono la config VIVA, non rileggono il disco)."""

    def __init__(self):
        self.refreshed = 0
        self.cfgs = []

    def refresh(self, cfg=None):
        self.refreshed += 1
        self.cfgs.append(cfg)


class _BoomPanel:
    """Pannello Strumenti finto: `refresh()` solleva (dir illeggibile, config corrotta…)."""

    def __init__(self):
        self.refreshed = 0

    def refresh(self, cfg=None):
        self.refreshed += 1
        raise OSError("config illeggibile")


def test_refresh_ok_non_logga_e_chiama_tutti(make_app):
    a = make_app(running=False)
    prov, src, mapp = _OkPanel(), _OkPanel(), _OkPanel()
    panel_refs = {"provider": prov, "sources": src, "mapping": mapp}
    saved = {"source_chats": [{"chat_id": "-100222", "enabled": True}]}
    a._refresh_tool_panels_after_profile(panel_refs, saved)
    assert prov.refreshed == 1 and src.refreshed == 1 and mapp.refreshed == 1
    assert a.logs == []                              # nessun warning se tutto ok
    # P3-7 #76: ogni pannello riceve la config VIVA appena applicata (uguale a `saved`),
    # ma come DEEPCOPY indipendente — mai lo stesso dict annidato condiviso con la config
    # viva o con un altro pannello (una mutazione locale non deve propagarsi).
    for p in (prov, src, mapp):
        assert p.cfgs == [saved]
        assert p.cfgs[0] is not saved
        assert p.cfgs[0]["source_chats"] is not saved["source_chats"]
    assert prov.cfgs[0] is not src.cfgs[0]


def test_refresh_fallito_logga_la_scheda_stantia(make_app):
    """FAIL-FIRST: sul vecchio `except Exception: pass` questo warning NON veniva emesso."""
    a = make_app(running=False)
    prov, src = _BoomPanel(), _OkPanel()             # Provider fallisce, Sorgenti ok
    panel_refs = {"provider": prov, "sources": src, "mapping": None}
    a._refresh_tool_panels_after_profile(panel_refs, {})   # NON deve sollevare
    assert prov.refreshed == 1                        # ci ha provato
    assert src.refreshed == 1                         # una scheda fallita non ferma le altre
    warn = [m for m in a.logs if "Provider non aggiornata" in m]
    assert len(warn) == 1                             # loggato, non ingoiato
    assert "config illeggibile" in warn[0]           # con la causa
    assert not any("Chat sorgenti" in m for m in a.logs)   # la scheda ok non logga


def test_refresh_pannelli_assenti_no_op(make_app):
    """Nessun pannello costruito (panel_refs vuoto): no-op, nessun log."""
    a = make_app(running=False)
    a._refresh_tool_panels_after_profile({}, {})
    assert a.logs == []
