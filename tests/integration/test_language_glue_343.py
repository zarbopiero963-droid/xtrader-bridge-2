"""Glue #343 slice «selettore lingua»: `_language_chosen` e il gate di apertura.

Esercita i VERI metodi di `App` headless (object.__new__ + sink catturati), col
salvataggio shadowato: la persistenza reale di `save_config` è già coperta dai
test di `config_store`."""

import types


def _app(app_mod, cfg):
    app = object.__new__(app_mod.App)
    app._config = cfg
    app._logs = []
    app._log = app._logs.append
    return app


class _Win:
    def __init__(self):
        self.destroyed = []

    def destroy(self):
        self.destroyed.append(True)


def test_language_chosen_persiste_e_allinea_csv(app_mod, monkeypatch):
    app = _app(app_mod, {"app_language": "", "csv_language": "IT", "chat_id": "-1"})
    salvati = []
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg, path: (salvati.append(cfg) or (cfg, True)))
    win = _Win()
    app._language_chosen("en", win)
    assert salvati and salvati[0]["app_language"] == "EN"
    assert salvati[0]["csv_language"] == "EN"          # lingua CSV ALLINEATA
    assert salvati[0]["chat_id"] == "-1"               # resto della config preservato
    assert app._config["app_language"] == "EN"         # config viva aggiornata
    assert app._save_ok is True
    assert any("🌐" in ln and "EN" in ln for ln in app._logs)
    assert win.destroyed == [True]


def test_language_chosen_codice_invalido_fail_closed(app_mod, monkeypatch):
    app = _app(app_mod, {"app_language": "", "csv_language": "IT"})
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg, path: (_ for _ in ()).throw(
                            AssertionError("save NON deve essere chiamato")))
    win = _Win()
    app._language_chosen("FR", win)                    # non supportata → nessun save
    assert app._config == {"app_language": "", "csv_language": "IT"}
    assert app._logs == []
    assert win.destroyed == [True]                     # il selettore si chiude comunque


def test_language_chosen_save_fallito_niente_falso_successo(app_mod, monkeypatch):
    """Fugu #356 + Fable round 2/3: se `save_config` ritorna ok=False (1) il log NON
    dichiara la lingua impostata, (2) la config VIVA non viene adottata, (3) il
    writer CSV — che `save_config` ha già allineato PRIMA della scrittura fallita —
    torna ESATTAMENTE alla lingua effettiva pre-save (catturata da
    `get_csv_language`, indipendente dalla forma della config: qui la config è
    LEGACY, senza chiave `csv_language` — round 3 GPT/Fable/Fugu)."""
    app = _app(app_mod, {"app_language": ""})      # legacy: NESSUNA csv_language
    monkeypatch.setattr(app_mod, "save_config", lambda cfg, path: (cfg, False))
    monkeypatch.setattr(app_mod.csv_writer, "get_csv_language", lambda: "ES")
    ripristini = []
    monkeypatch.setattr(app_mod.csv_writer, "set_csv_language",
                        lambda v: ripristini.append(v) or v)
    app._language_chosen("EN", _Win())
    assert app._save_ok is False
    assert app._config == {"app_language": ""}                 # NON adottata
    assert ripristini == ["ES"]        # writer → lingua EFFETTIVA pre-save, mai None
    assert not any("impostata:" in ln for ln in app._logs)     # niente falso successo
    assert any("FALLITO" in ln and "riapparirà" in ln for ln in app._logs)


def test_language_chosen_guardia_token_pr08c(app_mod, monkeypatch):
    """CodeRabbit #356 (major): il marker `_token_load_incomplete` va letto PRIMA di
    `save_config` (che lo consuma reidratando il token) e il campo password va
    risincronizzato DOPO — senza, il prossimo «Salva» col campo vuoto cancellerebbe
    il token dal keyring (PR-08c)."""
    marker = app_mod.config_store.TOKEN_LOAD_INCOMPLETE_KEY
    app = _app(app_mod, {"app_language": "", "csv_language": "IT",
                         "bot_token": "", marker: True})
    def _fake_save(cfg, path):
        out = dict(cfg)
        out.pop(marker, None)                      # il save CONSUMA il marker
        out["bot_token"] = "TOK-REIDRATATO"
        return out, True
    monkeypatch.setattr(app_mod, "save_config", _fake_save)
    resync, registrati = [], []
    app._resync_token_field = lambda had=None: resync.append(had)
    app._register_secret_token = registrati.append
    app._language_chosen("IT", _Win())
    assert resync == [True]            # marker catturato PRIMA del save e propagato
    assert registrati and registrati[0]["bot_token"] == "TOK-REIDRATATO"
    assert app._config.get("bot_token") == "TOK-REIDRATATO"


def test_language_chosen_preserva_csv_personalizzata_e_lo_dice(app_mod, monkeypatch):
    """Fable #356 (upgrade): csv_language personalizzata preservata E dichiarata."""
    app = _app(app_mod, {"app_language": "", "csv_language": "EN"})
    salvati = []
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg, path: (salvati.append(cfg) or (cfg, True)))
    app._language_chosen("IT", _Win())
    assert salvati[0]["app_language"] == "IT"
    assert salvati[0]["csv_language"] == "EN"                  # PRESERVATA
    assert any("preservata: EN" in ln for ln in app._logs)


def test_selettore_rimandato_con_autostart_attivo(app_mod, monkeypatch):
    """Fable/Fugu #356: con auto-start attivo NIENTE grab modale sopra un avvio non
    presidiato (STOP resterebbe irraggiungibile mentre il listener scrive il CSV)."""
    aperture = []
    monkeypatch.setattr(app_mod.ctk, "CTkToplevel",
                        lambda *a, **k: aperture.append(True))
    app = _app(app_mod, {"app_language": "", "auto_start_listener": True})
    app._maybe_open_language_selector()
    assert aperture == []                                      # selettore NON aperto
    assert any("rimandato" in ln and "auto-start" in ln for ln in app._logs)


def test_selettore_si_apre_solo_al_primo_avvio(app_mod, monkeypatch):
    aperture = []
    monkeypatch.setattr(app_mod.ctk, "CTkToplevel",
                        lambda *a, **k: aperture.append(True) or (_ for _ in ()).throw(
                            RuntimeError("stop qui: basta sapere che è stata aperta")))
    # Lingua GIÀ scelta → il selettore NON si apre.
    app = _app(app_mod, {"app_language": "IT"})
    app._maybe_open_language_selector()
    assert aperture == []
    # Mai scelta → tentativo di apertura (e l'errore GUI NON propaga: best-effort).
    app2 = _app(app_mod, {"app_language": ""})
    app2._maybe_open_language_selector()
    assert aperture == [True]
