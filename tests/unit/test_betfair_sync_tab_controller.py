"""Test hard del controller della tab Betfair Sync (issue #86 PR-P3).

Esercita la logica reale con un keyring fake iniettato: abilitazione pulsanti,
salva/cancella credenziali, e in particolare che il **logout cancella solo la
sessione, non le credenziali** (regola dell'issue). Nessun widget, nessun display.
"""

import pytest

from xtrader_bridge import token_store
from xtrader_bridge.betfair import credential_store as cs
from xtrader_bridge.betfair import log_safety
from xtrader_bridge.betfair.credential_store import BetfairCredentials
from xtrader_bridge.betfair.session import BetfairSession
from xtrader_bridge.betfair.sync_tab_controller import (
    SPORTS,
    BetfairSyncController,
    normalize_days_ahead,
    normalize_sport,
)


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, account, password):
        self.store[(service, account)] = password

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
        if (service, account) not in self.store:
            raise KeyError("voce inesistente")
        del self.store[(service, account)]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    log_safety.clear_secrets()
    fake = FakeKeyring()                      # UNA sola istanza condivisa: lo store persiste
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    yield
    log_safety.clear_secrets()


def _creds():
    return BetfairCredentials(
        app_key="DelayedAppKey123", username="utente",
        password="PwSegreta!", cert_path="/c/cert.crt", key_path="/c/cert.key")


# ── normalizzazione campi ─────────────────────────────────────────────────────

def test_normalize_days_ahead():
    assert normalize_days_ahead(5) == 5
    assert normalize_days_ahead("7") == 7
    assert normalize_days_ahead(0) == 3        # <1 → default
    assert normalize_days_ahead(-2) == 3
    assert normalize_days_ahead("abc") == 3
    assert normalize_days_ahead(None) == 3
    assert normalize_days_ahead(True) == 3     # bool non valido
    assert normalize_days_ahead(999) == 30     # cap


def test_normalize_sport():
    assert normalize_sport("calcio") == "Calcio"
    assert normalize_sport("  RUGBY union ") == "Rugby Union"
    assert normalize_sport("Cricket") is None
    assert set(SPORTS) == {"Calcio", "Tennis", "Basket", "Rugby Union"}


# ── abilitazione pulsanti ─────────────────────────────────────────────────────

def test_buttons_senza_credenziali():
    c = BetfairSyncController(session=BetfairSession())
    st = c.button_states()
    assert st["save_credentials"] is True
    assert st["login"] is False            # niente credenziali complete
    assert st["sync_now"] is False         # non loggati
    assert st["logout"] is False
    assert st["delete_credentials"] is False


def test_login_abilitato_con_credenziali_complete():
    c = BetfairSyncController(session=BetfairSession())
    c.save_credentials(_creds())
    st = c.button_states()
    assert st["login"] is True
    assert st["delete_credentials"] is True
    assert st["sync_now"] is False         # ancora non loggati


def test_sync_abilitato_solo_dopo_login_e_non_in_corso():
    sess = BetfairSession()
    c = BetfairSyncController(session=sess)
    c.save_credentials(_creds())
    sess.set_token("token-ram")            # simulazione login (auth vera in PR-P4)
    st = c.button_states()
    assert st["sync_now"] is True
    assert st["logout"] is True
    assert st["login"] is False            # già loggati
    # con una sync in corso, «Sincronizza» è disabilitato
    assert c.button_states(sync_in_progress=True)["sync_now"] is False


def test_credentials_complete_dal_form_override():
    # La GUI può passare lo stato del form: login abilitato anche prima del save.
    c = BetfairSyncController(session=BetfairSession())
    assert c.button_states(credentials_complete=True)["login"] is True


# ── logout NON cancella le credenziali ────────────────────────────────────────

def test_logout_cancella_solo_la_sessione():
    sess = BetfairSession()
    c = BetfairSyncController(session=sess)
    c.save_credentials(_creds())
    sess.set_token("token-ram")
    c.logout()
    assert c.is_logged_in is False
    # le credenziali salvate restano (regola dell'issue)
    assert c.has_saved_credentials() is True
    assert cs.load_credentials().is_complete() is True


def test_delete_cancella_credenziali_e_sessione():
    sess = BetfairSession()
    c = BetfairSyncController(session=sess)
    c.save_credentials(_creds())
    sess.set_token("token-ram")
    assert c.delete_saved_credentials() is True
    assert c.is_logged_in is False
    assert c.has_saved_credentials() is False
    assert cs.load_credentials() == BetfairCredentials()


# ── masking alla riapertura ───────────────────────────────────────────────────

def test_load_masked_nasconde_segreti():
    c = BetfairSyncController(session=BetfairSession())
    c.save_credentials(_creds())
    view = c.load_masked()
    assert view["app_key"] == "••••••"
    assert view["password"] == "••••••"
    assert view["cert_path"] == "/c/cert.crt"


# ── resolve_credentials: la maschera non sovrascrive i segreti (Codex P2) ──────

def test_resolve_segreto_mascherato_usa_il_valore_reale_salvato():
    c = BetfairSyncController(session=BetfairSession())
    c.save_credentials(_creds())
    # il form alla riapertura mostra la maschera nei campi segreti
    form = BetfairCredentials(app_key=cs.MASK, username=cs.MASK, password=cs.MASK,
                              cert_path="/c/cert.crt", key_path="/c/cert.key")
    resolved = c.resolve_credentials(form)
    # i segreti tornano ai valori reali, non alla maschera
    assert resolved == _creds()


def test_resolve_segreto_ridigitato_usa_il_nuovo_valore():
    c = BetfairSyncController(session=BetfairSession())
    c.save_credentials(_creds())
    form = BetfairCredentials(app_key="NuovaKey999", username=cs.MASK,
                              password=cs.MASK, cert_path="/c/cert.crt",
                              key_path="/c/cert.key")
    resolved = c.resolve_credentials(form)
    assert resolved.app_key == "NuovaKey999"      # nuovo valore digitato
    assert resolved.username == "utente"          # mascherato → reale
    assert resolved.password == "PwSegreta!"


def test_resolve_segreto_svuotato_resta_vuoto():
    # Svuotare un campo (non mascherato, stringa vuota) deve restare vuoto → su save
    # cancella la voce. La maschera non è una stringa vuota, quindi è distinta.
    c = BetfairSyncController(session=BetfairSession())
    c.save_credentials(_creds())
    form = BetfairCredentials(app_key="", username=cs.MASK, password=cs.MASK,
                              cert_path="/c/cert.crt", key_path="/c/cert.key")
    resolved = c.resolve_credentials(form)
    assert resolved.app_key == ""


def test_save_di_form_mascherato_non_corrompe_il_keyring():
    # Regressione del bug Codex: Salva senza ridigitare NON deve scrivere ••••••.
    c = BetfairSyncController(session=BetfairSession())
    c.save_credentials(_creds())
    view = c.load_masked()                          # come lo vede la GUI alla riapertura
    form = BetfairCredentials(**view)              # i segreti sono "••••••"
    c.save_credentials(c.resolve_credentials(form))  # salva risolto, come fa la GUI
    # il keyring conserva i valori reali, non la maschera
    assert cs.load_credentials() == _creds()
