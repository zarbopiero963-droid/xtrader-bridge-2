"""Test hard dello storage sicuro delle credenziali Betfair (issue #86 PR-P2).

Esercita la logica reale con un backend keyring **fake** iniettato (offline,
deterministico): salvataggio, ricarica con campi mascherati, cancellazione, e il
caso "backend assente" → fail-safe senza crash. Nessun segreto reale nei test.
"""

import pytest

from xtrader_bridge import token_store
from xtrader_bridge.betfair import credential_store as cs
from xtrader_bridge.betfair import log_safety


class FakeKeyring:
    """Keyring in memoria che imita l'API set/get/delete_password di `keyring`.

    `fail_delete`: insieme di account il cui `delete_password` solleva e **lascia la
    voce** (simula un errore reale del backend: la cancellazione non avviene)."""

    def __init__(self, fail_delete=None):
        self.store = {}
        self.fail_delete = set(fail_delete or ())

    def set_password(self, service, account, password):
        self.store[(service, account)] = password

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
        if account in self.fail_delete:
            raise RuntimeError("delete fallita (backend, simulato)")  # voce resta
        if (service, account) not in self.store:
            raise KeyError("voce inesistente")
        del self.store[(service, account)]


@pytest.fixture(autouse=True)
def _clean_registry():
    log_safety.clear_secrets()
    yield
    log_safety.clear_secrets()


def _use(monkeypatch, fake):
    # credential_store legge il keyring tramite token_store._keyring.
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)


def _sample():
    return cs.BetfairCredentials(
        app_key="DelayedAppKey123", username="utenteBetfair",
        password="PasswordSegreta!", cert_path="/c/cert.crt", key_path="/c/cert.key")


# ── round-trip salvataggio/caricamento ────────────────────────────────────────

def test_save_e_load_round_trip(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    assert cs.save_credentials(_sample()) is True
    loaded = cs.load_credentials()
    assert loaded == _sample()
    # i segreti sono davvero nel keyring sotto account prefissati
    assert fake.store[(cs.SERVICE, "betfair_app_key")] == "DelayedAppKey123"
    assert fake.store[(cs.SERVICE, "betfair_password")] == "PasswordSegreta!"


def test_secret_salvati_registrati_per_redazione(monkeypatch):
    _use(monkeypatch, FakeKeyring())
    cs.save_credentials(_sample())
    # App key e password non devono comparire in chiaro nei log
    assert "DelayedAppKey123" not in log_safety.redact("dbg DelayedAppKey123")
    assert "PasswordSegreta!" not in log_safety.redact("dbg PasswordSegreta!")


# ── riapertura con campi mascherati ───────────────────────────────────────────

def test_masked_nasconde_i_segreti_mostra_i_path(monkeypatch):
    _use(monkeypatch, FakeKeyring())
    cs.save_credentials(_sample())
    view = cs.masked(cs.load_credentials())
    assert view["app_key"] == "••••••"
    assert view["username"] == "••••••"
    assert view["password"] == "••••••"
    # i percorsi file sono mostrati in chiaro (per far vedere quale file è scelto)
    assert view["cert_path"] == "/c/cert.crt"
    assert view["key_path"] == "/c/cert.key"


def test_masked_campo_assente_e_vuoto(monkeypatch):
    _use(monkeypatch, FakeKeyring())
    view = cs.masked(cs.BetfairCredentials())
    assert view["app_key"] == ""        # niente maschera se non c'è nulla
    assert view["cert_path"] == ""


# ── cancellazione e svuotamento campo ─────────────────────────────────────────

def test_delete_rimuove_tutte_le_voci(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    cs.save_credentials(_sample())
    assert cs.delete_credentials() is True
    assert cs.load_credentials() == cs.BetfairCredentials()
    assert fake.store == {}


def test_campo_svuotato_viene_cancellato_dal_keyring(monkeypatch):
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    cs.save_credentials(_sample())
    # nuovo save con password vuota → la voce password deve sparire
    creds = _sample()
    creds.password = ""
    assert cs.save_credentials(creds) is True
    assert (cs.SERVICE, "betfair_password") not in fake.store
    assert (cs.SERVICE, "betfair_app_key") in fake.store     # gli altri restano


# ── cancellazione fallita NON deve sembrare riuscita (Codex P2) ───────────────

def test_delete_fallita_ritorna_false_e_lascia_la_voce(monkeypatch):
    # Il backend fallisce la delete dell'app_key e la voce resta memorizzata.
    fake = FakeKeyring(fail_delete={"betfair_app_key"})
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    cs.save_credentials(_sample())
    assert cs.delete_credentials() is False               # non dichiara successo
    # il segreto è ancora lì: la GUI deve segnalare il fallimento
    assert fake.store.get((cs.SERVICE, "betfair_app_key")) == "DelayedAppKey123"


def test_save_con_clear_fallito_ritorna_false(monkeypatch):
    # L'utente svuota la password ma la delete del backend fallisce: il vecchio
    # segreto resta → il save deve risultare FALLITO, non riuscito.
    fake = FakeKeyring(fail_delete={"betfair_password"})
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    cs.save_credentials(_sample())
    creds = _sample()
    creds.password = ""                                   # clear del campo password
    assert cs.save_credentials(creds) is False
    # la vecchia password è ancora memorizzata (clear non avvenuto)
    assert fake.store.get((cs.SERVICE, "betfair_password")) == "PasswordSegreta!"


class FailSetKeyring(FakeKeyring):
    """Come FakeKeyring ma `set_password` solleva per gli account in `fail_set`
    (simula un errore reale del backend a metà salvataggio)."""

    def __init__(self, fail_set=None, **kw):
        super().__init__(**kw)
        self.fail_set = set(fail_set or ())

    def set_password(self, service, account, password):
        if account in self.fail_set:
            raise RuntimeError("set fallita (backend, simulato)")
        super().set_password(service, account, password)


def test_save_rollback_su_scrittura_fallita_ripristina_lo_stato(monkeypatch):
    """Audit #259 D2: se una scrittura fallisce a METÀ, i campi già scritti devono
    tornare allo stato PRECEDENTE — niente keyring incoerente (App Key nuova +
    username/password vecchi). Prima il save proseguiva lasciando lo stato misto.

    Fail-first: sul vecchio codice `app_key` restava col valore NUOVO."""
    # Stato iniziale coerente (credenziali vecchie).
    fake = FailSetKeyring(fail_set={"betfair_password"})
    fake.store = {
        (cs.SERVICE, "betfair_app_key"): "OLD_APP",
        (cs.SERVICE, "betfair_username"): "OLD_USER",
        (cs.SERVICE, "betfair_password"): "OLD_PASS",
        (cs.SERVICE, "betfair_cert_path"): "/old/cert.crt",
        (cs.SERVICE, "betfair_key_path"): "/old/cert.key",
    }
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    nuove = cs.BetfairCredentials(
        app_key="NEW_APP", username="NEW_USER", password="NEW_PASS",
        cert_path="/new/cert.crt", key_path="/new/cert.key")
    # app_key e username vengono scritti (NEW), poi password FALLISCE → rollback.
    assert cs.save_credentials(nuove) is False
    # Nessuno stato misto: i campi già toccati sono tornati ai valori VECCHI.
    assert fake.store[(cs.SERVICE, "betfair_app_key")] == "OLD_APP"
    assert fake.store[(cs.SERVICE, "betfair_username")] == "OLD_USER"
    assert fake.store[(cs.SERVICE, "betfair_password")] == "OLD_PASS"


def test_save_rollback_cancella_campo_prima_assente(monkeypatch):
    """D2: se il campo toccato prima del fallimento NON esisteva, il rollback lo
    CANCELLA (non lascia il valore nuovo orfano)."""
    fake = FailSetKeyring(fail_set={"betfair_username"})
    # keyring vuoto: nessun campo pre-esistente.
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    nuove = cs.BetfairCredentials(app_key="NEW_APP", username="NEW_USER")
    assert cs.save_credentials(nuove) is False
    # app_key era assente e scritto come NEW → il rollback lo rimuove.
    assert fake.store.get((cs.SERVICE, "betfair_app_key")) is None


class FailGetKeyring(FailSetKeyring):
    """`get_password` solleva per gli account in `fail_get` (snapshot non leggibile)."""

    def __init__(self, fail_get=None, **kw):
        super().__init__(**kw)
        self.fail_get = set(fail_get or ())

    def get_password(self, service, account):
        if account in self.fail_get:
            raise RuntimeError("get fallita (backend instabile, simulato)")
        return super().get_password(service, account)


def test_save_rollback_non_cancella_un_campo_con_snapshot_illeggibile(monkeypatch, caplog):
    """Review GPT #313: se lo snapshot di un campo NON è leggibile (keyring instabile)
    e poi una scrittura successiva fallisce, il rollback NON deve cancellare quel
    campo — cancellare un valore preesistente IGNOTO sarebbe una perdita di
    credenziali. Lo snapshot illeggibile è distinto da "campo assente".

    Fail-first: prima lo snapshot fallito diventava None e il rollback cancellava."""
    import logging as _logging
    # get di app_key fallisce (snapshot illeggibile), ma il valore c'è davvero;
    # username viene scritto (NEW) e poi password FALLISCE → rollback.
    fake = FailGetKeyring(fail_get={"betfair_app_key"}, fail_set={"betfair_password"})
    fake.store = {
        (cs.SERVICE, "betfair_app_key"): "OLD_APP_PREESISTENTE",
        (cs.SERVICE, "betfair_username"): "OLD_USER",
    }
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    nuove = cs.BetfairCredentials(app_key="NEW_APP", username="NEW_USER",
                                  password="NEW_PASS")
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.betfair.credential_store"):
        assert cs.save_credentials(nuove) is False
    # app_key aveva snapshot ILLEGGIBILE → il rollback NON l'ha toccata: il valore
    # scritto (NEW_APP) resta, ma il dato preesistente NON è andato perso in un delete.
    assert fake.store.get((cs.SERVICE, "betfair_app_key")) == "NEW_APP"
    # username aveva snapshot leggibile → ripristinato al valore VECCHIO.
    assert fake.store.get((cs.SERVICE, "betfair_username")) == "OLD_USER"
    # Il campo _UNREAD committato (app_key, resta NEW) NON è invisibile: warning lo cita
    # come possibilmente incoerente (review Fugu #313), senza mai i valori nel log.
    recs = [r for r in caplog.records
            if r.name == "xtrader_bridge.betfair.credential_store"]
    assert len(recs) == 1 and "app_key" in recs[0].getMessage()
    assert "NEW_APP" not in recs[0].getMessage()


def test_save_rollback_parziale_fallito_logga_warning(monkeypatch, caplog):
    """Review GLM/GPT #313: se il rollback stesso fallisce (doppio-guasto), lo stato
    incoerente non deve restare invisibile — un WARNING elenca i campi non
    ripristinati (solo i NOMI, mai i valori)."""
    import logging as _logging

    # Fake mirato: `betfair_username` fa fallire il SAVE (fail_set), e il RESTORE di
    # `betfair_app_key` fallisce (la 2ª scrittura di quel campo, cioè il ripristino).
    class RollbackFails(FailSetKeyring):
        def __init__(self):
            super().__init__(fail_set={"betfair_username"})
            self.calls = 0
        def set_password(self, service, account, password):
            # app_key: ok alla prima scrittura, FALLISCE al ripristino (2ª volta).
            if account == "betfair_app_key":
                self.calls += 1
                if self.calls >= 2:
                    raise RuntimeError("restore di app_key fallito (simulato)")
            super().set_password(service, account, password)
    fake = RollbackFails()
    fake.store = {(cs.SERVICE, "betfair_app_key"): "OLD_APP"}
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    nuove = cs.BetfairCredentials(app_key="NEW_APP", username="NEW_USER")
    with caplog.at_level(_logging.WARNING, logger="xtrader_bridge.betfair.credential_store"):
        assert cs.save_credentials(nuove) is False
    recs = [r for r in caplog.records
            if r.name == "xtrader_bridge.betfair.credential_store"]
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "app_key" in msg
    assert "NEW_APP" not in msg and "OLD_APP" not in msg      # mai i valori nel log


def test_save_riuscito_resta_true_e_atomico(monkeypatch):
    """Contro-campo D2: senza fallimenti il save scrive tutto e ritorna True."""
    fake = FailSetKeyring()                                # nessun fail
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    assert cs.save_credentials(_sample()) is True
    assert cs.load_credentials() == _sample()


def test_delete_di_voce_assente_e_successo(monkeypatch):
    # Cancellare quando non c'è nulla NON è un errore: ritorna True (niente da fare).
    fake = FakeKeyring()
    monkeypatch.setattr(token_store, "_keyring", lambda: fake)
    assert cs.delete_credentials() is True


# ── fail-safe: backend keyring assente ────────────────────────────────────────

def test_backend_assente_non_crasha(monkeypatch):
    monkeypatch.setattr(token_store, "_keyring", lambda: None)
    assert cs.available() is False
    assert cs.save_credentials(_sample()) is False
    assert cs.delete_credentials() is False
    assert cs.load_credentials() == cs.BetfairCredentials()


# ── #166: repr SAFE (mai segreti in chiaro) ───────────────────────────────────

def test_repr_non_espone_i_segreti():
    """#166 (Codex): `repr(BetfairCredentials(...))` non deve rivelare App Key/username/password.
    Fail-first: con il repr generato dal dataclass i valori segreti comparivano in chiaro."""
    creds = _sample()
    r = repr(creds)
    assert "DelayedAppKey123" not in r
    assert "utenteBetfair" not in r
    assert "PasswordSegreta!" not in r
    # i segreti presenti sono mostrati mascherati, i percorsi file in chiaro.
    assert cs.MASK in r
    assert "/c/cert.crt" in r and "/c/cert.key" in r
    # str() (che ricade su __repr__ per un dataclass) è altrettanto safe.
    assert "PasswordSegreta!" not in str(creds)


def test_repr_campi_segreti_vuoti_non_mascherati():
    # Un segreto ASSENTE non mostra la maschera (niente falso "presente").
    creds = cs.BetfairCredentials(cert_path="/c/x.crt")
    r = repr(creds)
    assert "app_key=''" in r and cs.MASK not in r
    assert "/c/x.crt" in r


# ── #166: il valore salvato è ESATTO (niente strip che altera la password) ─────

def test_save_preserva_il_valore_esatto_con_spazi(monkeypatch):
    """#166 (Codex): una password con spazi iniziali/finali intenzionali deve essere salvata
    INALTERATA. Fail-first: `save_credentials` applicava `.strip()` al valore scritto."""
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    creds = _sample()
    creds.password = "  pw con spazi  "                     # spazi intenzionali
    assert cs.save_credentials(creds) is True
    # il keyring contiene il valore ESATTO, non strippato
    assert fake.store[(cs.SERVICE, "betfair_password")] == "  pw con spazi  "
    # ricaricata, la password è identica (round-trip senza alterazioni)
    assert cs.load_credentials().password == "  pw con spazi  "
    # il valore esatto (con spazi) è registrato per la redazione log
    assert "  pw con spazi  " not in log_safety.redact("dbg   pw con spazi  ")


def test_save_campo_di_soli_spazi_e_trattato_come_vuoto(monkeypatch):
    # Un campo di SOLI spazi non è una credenziale: è trattato come vuoto (voce cancellata),
    # coerente con `is_complete`/`masked` che usano `.strip()` per decidere la presenza.
    fake = FakeKeyring()
    _use(monkeypatch, fake)
    cs.save_credentials(_sample())
    creds = _sample()
    creds.password = "   "                                  # solo spazi → vuoto
    assert cs.save_credentials(creds) is True
    assert (cs.SERVICE, "betfair_password") not in fake.store


# ── completezza ───────────────────────────────────────────────────────────────

def test_is_complete():
    assert _sample().is_complete() is True
    incompleto = _sample()
    incompleto.key_path = ""
    assert incompleto.is_complete() is False
