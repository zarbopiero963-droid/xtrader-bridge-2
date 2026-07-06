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
    """Fugu #356: se `save_config` ritorna ok=False il log NON deve dichiarare la
    lingua impostata — la scelta non è persistita e il selettore riapparirà."""
    app = _app(app_mod, {"app_language": "", "csv_language": "IT"})
    monkeypatch.setattr(app_mod, "save_config", lambda cfg, path: (cfg, False))
    app._language_chosen("EN", _Win())
    assert app._save_ok is False
    assert not any("impostata:" in ln for ln in app._logs)     # niente falso successo
    assert any("FALLITO" in ln and "riapparirà" in ln for ln in app._logs)


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
