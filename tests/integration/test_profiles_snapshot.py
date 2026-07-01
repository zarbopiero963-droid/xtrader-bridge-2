"""#60 (Codex/CodeRabbit P2/Major): salvare un profilo NON deve persistere config.json né
avere effetti collaterali prima che la scrittura del profilo riesca.

`App._save_config(persist=False)` (esposto come `App._profiles_snapshot`) è uno SNAPSHOT
PURO del form: NON scrive config.json, NON muta i campi GUI (`_resync_token_field`), NON
esegue i gate di transizione pericolosa (`_gate_dangerous_transitions`, che PROMPTano e
scrivono l'audit `REAL_MODE_ENABLED`) e NON logga. La persistenza + gate + logging restano
tutti sul percorso `persist=True`. Se lo snapshot avesse quegli effetti, salvare un profilo
in modalità reale registrerebbe "reale attivo" nell'audit mentre il config vivo resta
dry-run: audit trail fuorviante.

Test headless via il fixture `make_app`: esercita il metodo REALE `_save_config` e usa spie
che CONTANO le chiamate ai collaboratori side-effecting (niente no-op ciechi), così un
ritorno degli effetti collaterali su `persist=False` fa fallire il test (regressione bloccata).
"""


class _E:
    """Stand-in di un campo GUI: `.get()` ritorna il valore."""

    def __init__(self, v=""):
        self._v = v

    def get(self):
        return self._v


def _prep_form(a):
    """Popola l'App headless coi widget minimi che `_save_config` legge e installa SPIE
    (contatori di chiamata) sui collaboratori side-effecting, invece di no-op ciechi."""
    a._config = {}
    a._running = False
    a._e_token = _E("tok")
    a._e_chat = _E("111")
    a._e_csv = _E("out.csv")
    a._e_delay = _E("30")
    a._e_provider = _E("TG")
    a._adv = {}
    # Sentinella su `self._adv_errors`: `App` sottoclassa il vero `ctk.CTk` in CI, quindi
    # `hasattr(a, "_adv_errors")` su un'istanza headless (senza `self.tk`) ricorre all'infinito
    # nel `__getattr__` di tkinter. Presettiamo un valore-sentinella e asseriamo che lo snapshot
    # NON lo tocchi (persist=False non deve mutare `self._adv_errors`), mentre persist=True sì.
    a._adv_errors = "SENTINEL"
    a._had_incomplete_token_load = lambda *x, **k: False
    # Spie: registrano ogni chiamata così possiamo asserire NON-chiamata su persist=False.
    a.calls = {"resync": 0, "gate": 0}

    def _resync(*x, **k):
        a.calls["resync"] += 1

    def _gate(old, new):
        a.calls["gate"] += 1
        return new

    a._resync_token_field = _resync
    a._gate_dangerous_transitions = _gate
    a._register_secret_token = lambda *x, **k: None
    a._update_real_mode_banner = lambda *x, **k: None
    a._update_active_indicator = lambda *x, **k: None
    a._refresh_listened_chats = lambda *x, **k: None
    a._dbg = lambda *x, **k: None


def test_save_config_snapshot_non_persiste_e_senza_effetti(make_app, app_mod, monkeypatch):
    a = make_app(running=False)
    _prep_form(a)
    persisted = []
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg, path: (persisted.append(dict(cfg)), (dict(cfg), True))[1])

    # SNAPSHOT PURO: legge il form ma NON scrive su disco, NON muta self._config, e soprattutto
    # NON chiama i collaboratori side-effecting (resync campo GUI, gate transizioni pericolose).
    snap = a._save_config(persist=False)
    assert persisted == []                          # nessuna persistenza
    assert snap["csv_path"] == "out.csv"            # ma legge il form
    assert snap["chat_id"] == "111"
    assert a._config == {}                          # self._config invariato dallo snapshot
    assert a.calls["resync"] == 0                   # NESSUNA mutazione del campo token
    assert a.calls["gate"] == 0                     # NESSUN gate/prompt/audit REAL_MODE_ENABLED
    assert a.logs == []                             # NESSUN log dallo snapshot puro
    assert a._adv_errors == "SENTINEL"              # NESSUNA mutazione di self._adv_errors

    # PERSIST: ora scrive davvero, aggiorna self._config ED esegue i side-effect (gate+resync).
    saved = a._save_config(persist=True)
    assert len(persisted) == 1                       # persistito una volta
    assert saved["csv_path"] == "out.csv"
    assert a._config == saved
    assert a.calls["gate"] == 1                      # il gate gira SOLO su persist=True
    assert a.calls["resync"] >= 1                    # il resync gira SOLO su persist=True
    assert a._adv_errors != "SENTINEL"               # self._adv_errors ripopolato su persist=True
    assert isinstance(a._adv_errors, list)


def test_profiles_snapshot_delega_a_save_config_persist_false(make_app):
    """`_profiles_snapshot` (callback `get_current_cfg` del pannello Profili) deve essere il
    puro snapshot: stesso risultato di `_save_config(persist=False)` e nessun side-effect."""
    a = make_app(running=False)
    _prep_form(a)
    snap = a._profiles_snapshot()
    assert snap["csv_path"] == "out.csv"
    assert snap["chat_id"] == "111"
    assert snap["bot_token"] == "tok"                # snapshot con token (base per il profilo)
    assert a._config == {}                           # nessuna mutazione
    assert a.calls == {"resync": 0, "gate": 0}       # nessun side-effect
    assert a.logs == []


def test_profiles_tab_wiring_usa_snapshot_non_persistente(app_mod):
    """Regressione (CodeRabbit #60): la scheda "📁 Profili" DEVE ricevere lo snapshot NON
    persistente come `get_current_cfg`, non un salvataggio che scrive config.json. Costruire
    la scheda richiede widget CTk reali (non headless), quindi si ispeziona la sorgente REALE
    di `_open_tools`: deve cablare `_profiles_snapshot` e non un `_save_config()` persistente.
    Combinato con i test sopra (che provano che `_profiles_snapshot` NON persiste), garantisce
    che il pannello riceva un callback senza effetti su disco."""
    import inspect

    src = inspect.getsource(app_mod.App._open_tools)
    assert "get_current_cfg=self._profiles_snapshot" in src   # cablato allo snapshot
    # NON deve regredire a un salvataggio persistente (chiamata senza persist=False).
    assert "get_current_cfg=lambda: self._save_config()" not in src
    assert "get_current_cfg=self._save_config" not in src
