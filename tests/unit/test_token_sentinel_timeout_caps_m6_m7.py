"""Test hard AC-M6 + AC-M7 (audit di controllo #114, ondata 2 PR-3).

AC-M6 — sentinel `bot_token_storage` "sporco" o ignoto NON deve mai portare alla
cancellazione del token dal keyring: normalizzazione (case/spazi) al load/save e
fail-preserve sugli stati sconosciuti.

AC-M7 — `confirmation_timeout` ha lo stesso tetto anti-«segnale immortale» di
`clear_delay` (B2 #116): rifiuto fail-closed nel layer GUI e CLAMP difensivo nel
runtime (`timeout_from_config`), ultimo miglio dell'invariante n.5.

Fail-first sul codice precedente:
- sentinel " Keyring " → reidratazione saltata e, al save con campo token vuoto,
  `delete_token` CHIAMATO (credenziale distrutta) → i test M6 fallivano;
- `confirmation_timeout=1_000_000_000` accettato dalla GUI e restituito tale e quale
  dal runtime (~31 anni di riga attiva) → i test M7 fallivano.

Include il micro-test di uguaglianza delle costanti duplicate per design
(AC-B43: `DEFAULT_TIMEOUT`/`MAX_TIMEOUT` tra `settings_validation` e `signal_queue`).
"""

import json

from xtrader_bridge import (
    config_store,
    settings_controller,
    settings_validation,
    signal_queue,
)


def _fake_keyring(monkeypatch, store, available=True):
    """token_store in memoria (stesso pattern di test_config_basic.py)."""
    monkeypatch.setattr(config_store.token_store, "available", lambda: available)
    monkeypatch.setattr(config_store.token_store, "save_token",
                        lambda t: store.__setitem__("t", t) or True)
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: store.get("t"))
    monkeypatch.setattr(config_store.token_store, "load_token_status",
                        lambda: (store.get("t"), True))
    monkeypatch.setattr(config_store.token_store, "delete_token",
                        lambda: store.pop("t", None) is not None)


# ── AC-M6: sentinel sporco/ignoto ───────────────────────────────────────────


def test_sentinel_sporco_viene_normalizzato_e_reidrata(tmp_path, monkeypatch):
    """`" Keyring "` (case+spazi da edit manuale) → il load normalizza e REIDRATA il
    token dal keyring come se il sentinel fosse pulito. Prima del fix: nessuna
    reidratazione e nessun marker → primo save = clear reale."""
    store = {"t": "123:SECRET"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bot_token": "", "bot_token_storage": " Keyring "}),
                 encoding="utf-8")
    cfg = config_store.load_config(str(p))
    assert cfg["bot_token"] == "123:SECRET"
    assert cfg["bot_token_storage"] == "keyring"


def test_flusso_completo_sentinel_sporco_su_disco_token_sopravvive(tmp_path, monkeypatch):
    """Il flusso REALE del bug AC-M6: sentinel sporco su disco → load → save (la GUI
    re-invia i campi caricati). Prima del fix: load senza reidratazione né marker →
    save col campo vuoto = CLEAR reale → `delete_token` chiamato, credenziale distrutta.
    Col fix: il load normalizza e reidrata → il save ri-salva il token → intatto."""
    store = {"t": "123:SECRET"}
    _fake_keyring(monkeypatch, store)
    deleted = []
    real_pop = store.pop
    monkeypatch.setattr(config_store.token_store, "delete_token",
                        lambda: deleted.append(True) or real_pop("t", None) is not None)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bot_token": "", "bot_token_storage": "Keyring ",
                             "provider": "X"}), encoding="utf-8")
    cfg = config_store.load_config(str(p))
    config_store.save_config(dict(cfg), str(p))    # la GUI re-invia i campi caricati
    assert deleted == []                           # MAI cancellato
    assert store.get("t") == "123:SECRET"          # credenziale intatta
    assert config_store.load_config(str(p))["bot_token"] == "123:SECRET"


def test_sentinel_ignoto_fail_preserve_al_save(tmp_path, monkeypatch):
    """Sentinel NON riconosciuto (typo "keyrng") + campo token vuoto: stato di storage
    SCONOSCIUTO → fail-preserve (come post-corruzione): niente delete, token preservato."""
    store = {"t": "123:SECRET"}
    _fake_keyring(monkeypatch, store)
    deleted = []
    monkeypatch.setattr(config_store.token_store, "delete_token",
                        lambda: deleted.append(True) or True)
    p = tmp_path / "config.json"
    config_store.save_config(
        {"bot_token": "", "bot_token_storage": "keyrng", "provider": "X"}, str(p))
    assert deleted == []
    assert store.get("t") == "123:SECRET"


def test_clear_esplicito_con_sentinel_pulito_funziona_ancora(tmp_path, monkeypatch):
    """Regressione inversa: il CLEAR legittimo (sentinel pulito "keyring", load completo,
    keyring leggibile) deve continuare a cancellare davvero."""
    store = {"t": "123:SECRET"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    config_store.save_config(
        {"bot_token": "", "bot_token_storage": "keyring", "provider": "X"}, str(p))
    assert store.get("t") is None              # clear reale eseguito
    assert config_store.load_config(str(p))["bot_token"] == ""


# ── AC-M7: tetto confirmation_timeout (GUI) + clamp runtime ─────────────────


def _form(timeout):
    """Form minimo per `apply_advanced` (gli altri campi restano ai default validi)."""
    return {
        "recognition_mode": "NAME_ONLY",
        "queue_mode": "QUEUE_UNTIL_CONFIRMED",
        "max_per_day": "200",
        "xtrader_notification_chat_id": "",
        "confirmation_timeout": str(timeout),
        "confirmation_keywords": "",
        "rejection_keywords": "",
        "max_signal_age": "120",
        "dry_run": True,
    }


def test_confirmation_timeout_oltre_tetto_rifiutato_dalla_gui():
    """1_000_000_000 s (~31 anni) nel campo «Timeout conferme XTrader» → errore
    fail-closed, config NON aggiornata. Prima del fix: accettato."""
    base = dict(config_store.DEFAULTS)
    out, errors = settings_controller.apply_advanced(dict(base), _form(1_000_000_000))
    assert any("Timeout conferme" in e for e in errors)
    assert out.get("confirmation_timeout") == base.get("confirmation_timeout")


def test_confirmation_timeout_al_tetto_accettato():
    """Il valore massimo legittimo (86400 = 24 h) resta accettato (nessun over-blocking)."""
    out, errors = settings_controller.apply_advanced(
        dict(config_store.DEFAULTS), _form(settings_validation.MAX_TIMEOUT))
    assert errors == []
    assert out["confirmation_timeout"] == settings_validation.MAX_TIMEOUT


def test_runtime_clampa_confirmation_timeout_enorme():
    """Config editata A MANO oltre il tetto GUI: in QUEUE_UNTIL_CONFIRMED il runtime
    clampa a 24 h (mai segnale immortale). Prima del fix: 1e9 restituito tale e quale."""
    cfg = {"queue_mode": signal_queue.QUEUE_UNTIL_CONFIRMED,
           "confirmation_timeout": 1_000_000_000}
    assert signal_queue.timeout_from_config(cfg) == signal_queue.MAX_TIMEOUT


def test_runtime_clampa_clear_delay_enorme():
    """Stesso ultimo-miglio per `clear_delay` (OVERWRITE_LAST): il tetto B2 viveva solo
    nel layer GUI, un valore enorme su disco arrivava intatto al runtime."""
    cfg = {"queue_mode": signal_queue.OVERWRITE_LAST, "clear_delay": 10 ** 9}
    assert signal_queue.timeout_from_config(cfg) == signal_queue.MAX_TIMEOUT


def test_runtime_valori_normali_invariati():
    """Nessuna regressione: valori leciti passano invariati; malformati → default."""
    assert signal_queue.timeout_from_config(
        {"queue_mode": signal_queue.OVERWRITE_LAST, "clear_delay": 90}) == 90.0
    assert signal_queue.timeout_from_config(
        {"queue_mode": signal_queue.OVERWRITE_LAST, "clear_delay": "boom"}) \
        == signal_queue.DEFAULT_TIMEOUT


# ── AC-B43: costanti duplicate per design tenute in lockstep ────────────────


def test_costanti_timeout_in_lockstep_tra_settings_e_queue():
    """`signal_queue` duplica DELIBERATAMENTE le costanti del layer settings per restare
    puro/autocontenuto (commento in codice): questo test blocca il drift silenzioso —
    se una copia cambia senza l'altra, fallisce (AC-B43 + AC-M7)."""
    assert signal_queue.DEFAULT_TIMEOUT == settings_validation.DEFAULT_TIMEOUT
    assert signal_queue.MAX_TIMEOUT == settings_validation.MAX_TIMEOUT
