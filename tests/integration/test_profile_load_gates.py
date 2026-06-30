"""Gate di sicurezza su attivazione REALE / coda multi-segnale anche dal CARICAMENTO PROFILO
(#141/#142, audit #241 PR-02).

Prima il caricamento di un profilo (`_profiles_loaded`) chiamava `save_config` direttamente,
SALTANDO le doppie conferme che il bottone Salva applica: un profilo con `dry_run:false`
attivava la modalità REALE senza digitare la frase di conferma, e un profilo con coda
APPEND/QUEUE attivava il multi-segnale senza il warning. La logica è stata centralizzata in
`App._gate_dangerous_transitions`, ora usata SIA dal Salva SIA dal caricamento profilo.

Qui si esercita il metodo REALE `_gate_dangerous_transitions` headless (harness di
`tests/integration/conftest.py`), con i dialog di conferma simulati (accetta/rifiuta).
"""

from xtrader_bridge import signal_queue


def _gate_app(make_app, *, real_ok, multi_ok):
    """App headless col gate pronto: dialog di conferma stubbati a `real_ok`/`multi_ok`."""
    a = make_app()
    a._adv = {}                       # nessun widget form: il gate aggiorna solo la cfg
    a._confirm_real_mode = lambda: real_ok
    a._confirm_multi_signal = lambda max_active: multi_ok
    a._confirms = []                  # traccia le chiamate ai dialog
    real_orig, multi_orig = a._confirm_real_mode, a._confirm_multi_signal
    a._confirm_real_mode = lambda: (a._confirms.append("real"), real_ok)[1]
    a._confirm_multi_signal = lambda max_active: (a._confirms.append("multi"), multi_ok)[1]
    return a


# ── modalità REALE (#141) ─────────────────────────────────────────────────────

def test_profilo_reale_rifiutato_resta_simulazione(make_app):
    # Profilo che porta dry_run:false (REALE) mentre siamo in simulazione, conferma RIFIUTATA
    # → la cfg salvata resta in simulazione (dry_run True), come il bottone Salva.
    a = _gate_app(make_app, real_ok=False, multi_ok=True)
    out = a._gate_dangerous_transitions({"dry_run": True}, {"dry_run": False})
    assert out["dry_run"] is True
    assert "real" in a._confirms                      # il dialog di conferma è stato mostrato


def test_profilo_reale_confermato_attiva_reale(make_app):
    # Stessa transizione ma conferma ACCETTATA → la modalità reale resta attiva.
    a = _gate_app(make_app, real_ok=True, multi_ok=True)
    out = a._gate_dangerous_transitions({"dry_run": True}, {"dry_run": False})
    assert out["dry_run"] is False              # conferma accettata → reale attivo
    assert "real" in a._confirms


def test_profilo_gia_simulazione_non_chiede_conferma(make_app):
    # sim→sim: nessuna transizione pericolosa → nessun dialog, cfg invariata.
    a = _gate_app(make_app, real_ok=False, multi_ok=False)
    out = a._gate_dangerous_transitions({"dry_run": True}, {"dry_run": True})
    assert out["dry_run"] is True
    assert a._confirms == []


# ── coda MULTI-segnale (#142) ─────────────────────────────────────────────────

def test_profilo_multi_segnale_rifiutato_resta_overwrite(make_app):
    # Profilo con coda APPEND_ACTIVE mentre eravamo in OVERWRITE_LAST, warning RIFIUTATO
    # → la cfg salvata torna a un solo segnale attivo (OVERWRITE_LAST).
    a = _gate_app(make_app, real_ok=True, multi_ok=False)
    out = a._gate_dangerous_transitions(
        {"queue_mode": signal_queue.OVERWRITE_LAST},
        {"queue_mode": signal_queue.APPEND_ACTIVE})
    assert out["queue_mode"] == signal_queue.OVERWRITE_LAST
    assert "multi" in a._confirms


def test_profilo_multi_segnale_confermato_resta_append(make_app):
    a = _gate_app(make_app, real_ok=True, multi_ok=True)
    out = a._gate_dangerous_transitions(
        {"queue_mode": signal_queue.OVERWRITE_LAST},
        {"queue_mode": signal_queue.QUEUE_UNTIL_CONFIRMED})
    assert out["queue_mode"] == signal_queue.QUEUE_UNTIL_CONFIRMED   # warning accettato
    assert "multi" in a._confirms


# ── persist del profilo: gate + banner reale (Codex review su PR-02) ─────────

def test_persist_profilo_reale_confermato_aggiorna_banner(make_app, app_mod, monkeypatch):
    # Caricare un profilo che attiva il REALE (conferma accettata) deve persistere reale E
    # aggiornare il banner rosso — come il bottone Salva. Prima il path profilo non lo faceva.
    a = _gate_app(make_app, real_ok=True, multi_ok=True)
    a._config = {"dry_run": True}
    a._banner = []
    a._update_real_mode_banner = a._banner.append
    monkeypatch.setattr(app_mod, "save_config", lambda cfg, path: (dict(cfg), True))
    saved, ok = a._persist_loaded_profile({"dry_run": False})
    assert ok is True and saved["dry_run"] is False        # reale attivo
    assert a._banner == [saved]                            # banner aggiornato col cfg salvato (#141)


def test_persist_profilo_reale_rifiutato_resta_sim_e_banner(make_app, app_mod, monkeypatch):
    # Conferma RIFIUTATA: si persiste la simulazione e il banner viene comunque aggiornato
    # (così mostra lo stato corretto "non reale"), invece di restare stantio.
    a = _gate_app(make_app, real_ok=False, multi_ok=True)
    a._config = {"dry_run": True}
    a._banner = []
    a._update_real_mode_banner = a._banner.append
    monkeypatch.setattr(app_mod, "save_config", lambda cfg, path: (dict(cfg), True))
    saved, ok = a._persist_loaded_profile({"dry_run": False})
    assert saved["dry_run"] is True                        # reale annullato → simulazione
    assert a._banner == [saved]


def test_profilo_combinato_reale_e_multi_entrambi_rifiutati(make_app):
    # Un profilo che attiva ENTRAMBI (reale + multi) con ENTRAMBE le conferme rifiutate
    # → la cfg salvata è sicura su entrambi i fronti.
    a = _gate_app(make_app, real_ok=False, multi_ok=False)
    out = a._gate_dangerous_transitions(
        {"dry_run": True, "queue_mode": signal_queue.OVERWRITE_LAST},
        {"dry_run": False, "queue_mode": signal_queue.APPEND_ACTIVE})
    assert out["dry_run"] is True
    assert out["queue_mode"] == signal_queue.OVERWRITE_LAST
    assert a._confirms == ["real", "multi"]
