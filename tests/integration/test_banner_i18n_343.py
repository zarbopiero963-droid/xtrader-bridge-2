"""Glue #343 slice 4 (banner): `_update_real_mode_banner` rende i banner di SICUREZZA
localizzati a runtime.

Complementa i test di `test_i18n_343.py` (traduzione isolata + wiring statico): qui si
ESERCITA il metodo runtime reale `App._update_real_mode_banner` con la lingua attiva EN/ES e
si verifica il testo EFFETTIVAMENTE passato al widget (`configure(text=...)`), cioè l'intera
catena decisione→traduzione→display. Headless via `object.__new__(App)` + stub del conftest
(GPT-5.5 #29: «test unitario che simuli _update_real_mode_banner() con lingua EN/ES»).

Fail-first: prima della slice 4 il metodo passava `real_mode.BANNER_TEXT` grezzo (solo IT),
quindi in EN/ES il banner sarebbe restato italiano — questi assert fallirebbero.
"""

import pytest

from xtrader_bridge import bridge_mode, i18n, real_mode


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")     # stato di modulo: mai leak verso altri test


class _Lbl:
    """Stub minimale di CTkLabel: cattura il testo e lo stato di pack."""

    def __init__(self):
        self.text = None
        self.packed = False

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]

    def pack(self, **kw):
        self.packed = True

    def pack_forget(self):
        self.packed = False


# Modalità → dry_run resta l'unica fonte del percorso di scrittura; il banner è display puro.
_REAL_CFG = {"dry_run": False, "bridge_mode": "REALE"}
_COLLAUDO_CFG = {"dry_run": False, "bridge_mode": "COLLAUDO"}
_SIM_CFG = {"dry_run": True, "bridge_mode": "SIMULAZIONE"}


def _app(app_mod):
    app = object.__new__(app_mod.App)
    app._real_banner = _Lbl()
    app._collaudo_banner = _Lbl()
    app._tabs = None
    app._running = False
    app._session_mode = ""
    app._config = {}
    return app


def test_banner_reale_localizzato_a_runtime(app_mod):
    # EN/ES: attivando la modalità REALE il banner ROSSO mostra il testo TRADOTTO (non l'IT).
    i18n.set_language("EN")
    app = _app(app_mod)
    app._update_real_mode_banner(_REAL_CFG)
    assert app._real_banner.packed                          # banner mostrato
    assert app._real_banner.text == i18n.tr(real_mode.BANNER_TEXT)
    assert app._real_banner.text.startswith("⚠️ REAL MODE ACTIVE")   # severità conservata
    i18n.set_language("ES")
    app = _app(app_mod)
    app._update_real_mode_banner(_REAL_CFG)
    assert app._real_banner.text.startswith("⚠️ MODO REAL ACTIVO")


def test_banner_collaudo_localizzato_a_runtime(app_mod):
    # ES: modalità COLLAUDO → banner AMBRA col testo tradotto; il ROSSO resta spento (priorità).
    i18n.set_language("ES")
    app = _app(app_mod)
    app._update_real_mode_banner(_COLLAUDO_CFG)
    assert not app._real_banner.packed                      # rosso spento in COLLAUDO
    assert app._collaudo_banner.packed
    assert app._collaudo_banner.text == i18n.tr(bridge_mode.COLLAUDO_BANNER_TEXT)
    assert app._collaudo_banner.text.startswith("🔬 MODO DE PRUEBA XTRADER")


def test_banner_reale_italiano_default(app_mod):
    # IT (fail-safe): con la lingua di riferimento il banner reale resta il testo storico.
    app = _app(app_mod)                                     # lingua IT (default del fixture)
    app._update_real_mode_banner(_REAL_CFG)
    assert app._real_banner.packed
    assert app._real_banner.text == real_mode.BANNER_TEXT


def test_banner_nascosto_in_simulazione(app_mod):
    # In simulazione NESSUN banner acceso: la localizzazione non ha alterato la DECISIONE
    # (dry_run=True → nessun rischio reale, nessun banner), solo il testo mostrato quando attivo.
    i18n.set_language("EN")
    app = _app(app_mod)
    app._update_real_mode_banner(_SIM_CFG)
    assert not app._real_banner.packed
    assert not app._collaudo_banner.packed
