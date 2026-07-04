"""Test di sicurezza dei segnaposto d'aiuto nei campi (#288 Delta 2).

I `placeholder_text` sono **additivi**: testo grigio mostrato solo a campo vuoto, NON un valore
(`entry.get()` su un campo intatto resta `""`). Invariante SAFETY-CRITICAL: sui campi **sensibili**
(token / app key / password) il segnaposto NON deve mai sembrare un valore reale — è mostrato in
chiaro anche sui campi mascherati, quindi un segnaposto tipo un token plausibile confonderebbe o
suggerirebbe un segreto. Verifica i dizionari REALI `_FIELD_PLACEHOLDERS` di `app.py` e
`betfair/sync_tab_gui.py`.
"""

import importlib
import re
import sys
import types

import pytest


def _assert_placeholders_safe(placeholders, sensitive):
    # Tutti i segnaposto sono stringhe utili (non vuote).
    for key, text in placeholders.items():
        assert isinstance(text, str) and text.strip(), f"{key}: segnaposto vuoto/non stringa"
    # Sui campi sensibili: una FRASE istruttiva (ha spazi) e NESSUN blob alfanumerico lungo
    # (≥12 char) che possa sembrare un token/chiave/password reale.
    for key in sensitive:
        text = placeholders[key]
        assert " " in text.strip(), f"{key}: segnaposto sensibile deve essere una frase istruttiva"
        assert all(len(re.sub(r"[^A-Za-z0-9]", "", w)) < 12 for w in text.split()), \
            f"{key}: segnaposto sembra un valore reale ({text!r})"


def test_app_placeholders_sicuri(app_mod):
    ph = app_mod._FIELD_PLACEHOLDERS
    _assert_placeholders_safe(ph, sensitive=("bot_token",))
    assert set(ph) >= {"bot_token", "chat_id", "csv_path", "clear_delay", "provider"}
    # il campo token NON deve suggerire un token plausibile
    assert "token" in ph["bot_token"].lower()


@pytest.fixture
def sync_mod(monkeypatch):
    """Importa `betfair.sync_tab_gui` con `customtkinter` stubbato (modulo GUI, no display)."""
    fake = types.ModuleType("customtkinter")
    fake.__getattr__ = lambda _n: object
    monkeypatch.setitem(sys.modules, "customtkinter", fake)
    monkeypatch.delitem(sys.modules, "xtrader_bridge.betfair.sync_tab_gui", raising=False)
    return importlib.import_module("xtrader_bridge.betfair.sync_tab_gui")


def test_sync_placeholders_sicuri(sync_mod):
    ph = sync_mod._FIELD_PLACEHOLDERS
    _assert_placeholders_safe(ph, sensitive=("app_key", "password"))
    assert set(ph) >= {"app_key", "username", "password", "cert_path", "key_path"}


def test_helper_smaschera_un_segnaposto_tipo_segreto():
    # Contro-prova: un segnaposto che SEMBRA un valore reale deve far fallire il check safety.
    with pytest.raises(AssertionError):
        _assert_placeholders_safe(
            {"bot_token": "123456:ABCdefGhIjKlmNoPqrStuv"}, sensitive=("bot_token",))
