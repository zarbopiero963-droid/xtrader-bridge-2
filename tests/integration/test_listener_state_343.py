"""Glue #343 slice 4b: stato CANONICO del listener (niente text-parsing della label).

Il semaforo 🚦 Salute leggeva il TESTO di `_status_lbl`: con la label localizzata
(«⬤  ACTIVE» in EN) il substring-match su «ATTIVO» si sarebbe rotto. Ora la logica
usa `_listener_state` (health_check.LISTENER_*) e la label è solo display."""

import pytest

from xtrader_bridge import health_check, i18n


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


class _Lbl:
    def __init__(self):
        self.kw = {}

    def configure(self, **kw):
        self.kw.update(kw)


def _app(app_mod):
    app = object.__new__(app_mod.App)
    app._status_lbl = _Lbl()
    return app


def test_listener_texts_attributo_di_classe_completo(app_mod):
    """GLM/Fable/Fugu #359: `_LISTENER_TEXTS` è un attributo di CLASSE (nel class
    dict, NON assegnato in `__init__`), quindi è disponibile in `_build_ui` prima di
    qualsiasi `_set_listener_state` — la label OFFLINE iniziale ne deriva
    (CodeRabbit #358), e un buco qui darebbe KeyError all'avvio. Copre i 3 stati
    canonici con testo non vuoto."""
    texts = app_mod.App.__dict__["_LISTENER_TEXTS"]      # dal CLASS dict, non da istanza
    for state in (health_check.LISTENER_ACTIVE, health_check.LISTENER_RECONNECTING,
                  health_check.LISTENER_OFFLINE):
        assert state in texts, f"stato canonico non mappato in _LISTENER_TEXTS: {state}"
        assert texts[state].strip(), f"testo vuoto per {state}"
    assert texts[health_check.LISTENER_OFFLINE] == "⬤  OFFLINE"


def test_set_listener_state_canonico_piu_display_localizzato(app_mod):
    app = _app(app_mod)
    i18n.set_language("EN")
    app._set_listener_state(health_check.LISTENER_ACTIVE, "green")
    assert app._listener_state == health_check.LISTENER_ACTIVE   # canonico: MAI tradotto
    assert app._status_lbl.kw["text"] == "⬤  ACTIVE"             # display: tradotto
    app._set_listener_state(health_check.LISTENER_RECONNECTING, "orange")
    assert app._listener_state == health_check.LISTENER_RECONNECTING
    assert app._status_lbl.kw["text"] == "⬤  RECONNECTING…"
    i18n.set_language("IT")
    app._set_listener_state(health_check.LISTENER_OFFLINE, "red")
    assert app._status_lbl.kw["text"] == "⬤  OFFLINE"


def test_refresh_health_usa_lo_stato_canonico_non_il_testo(app_mod, monkeypatch):
    """Fail-first sul vecchio codice (cget del testo): con label in EN e stato
    ATTIVO, il semaforo deve ricevere il CANONICO — il testo tradotto non
    matcherebbe «ATTIVO» e il pannello mostrerebbe OFFLINE con listener vivo."""
    app = _app(app_mod)
    app._config = {}
    app._last_vals = {}
    i18n.set_language("EN")
    app._set_listener_state(health_check.LISTENER_ACTIVE, "green")
    assert "ATTIVO" not in app._status_lbl.kw["text"]            # il testo NON basta più
    catturato = {}

    def _fake_evaluate(**kw):
        catturato.update(kw)
        return []

    monkeypatch.setattr(app_mod.health_check, "evaluate", _fake_evaluate)
    app._refresh_health_inner({})
    assert catturato["listener_status"] == health_check.LISTENER_ACTIVE


def test_semaforo_verde_in_inglese_end_to_end(app_mod):
    """Con lingua EN e listener attivo il semaforo Telegram resta VERDE: lo stato
    canonico attraversa evaluate() senza dipendere dalla lingua della label."""
    app = _app(app_mod)
    i18n.set_language("EN")
    app._set_listener_state(health_check.LISTENER_ACTIVE, "green")
    items = health_check.evaluate(listener_status=app._listener_state)
    telegram = next(it for it in items if it.key == "telegram")
    assert telegram.state == health_check.GREEN
