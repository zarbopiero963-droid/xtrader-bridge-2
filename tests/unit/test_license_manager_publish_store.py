"""Test hard delle **impostazioni di pubblicazione** del License Manager (#157).

Esercitano la logica reale di `license_manager.publish_store`: normalizzazione/validazione,
persistenza atomica fail-safe e keyring (con backend FINTO, nessun keyring reale nei test).
Invariante centrale verificata: **il token non finisce MAI su disco**."""

import json
import types

import pytest

from license_manager import publish_store


# ── normalizzazione ──────────────────────────────────────────────────────────────────────────────
def test_normalize_config_default_su_input_vuoto_o_sporco():
    for bad in ({}, None, "non-dict", 123, []):
        norm = publish_store.normalize_config(bad)
        assert norm == publish_store.normalize_config({})
        assert norm["enabled"] is False              # default fail-closed: spenta
        assert norm["path"] == "revocation_list.txt"
        assert norm["branch"] == "main"


def test_normalize_config_pulisce_spazi_e_tipi():
    norm = publish_store.normalize_config({
        "enabled": True, "repo": "  tizio/xtrader-revocation  ",
        "path": "  lista.txt ", "branch": " main ", "interval_hours": "6",
    })
    assert norm == {"enabled": True, "repo": "tizio/xtrader-revocation",
                    "path": "lista.txt", "branch": "main", "interval_hours": 6}


def test_normalize_config_enabled_solo_bool_true():
    """`enabled` si attiva SOLO con un vero `True`: una stringa non deve accendere la pubblicazione."""
    for truthy in ("on", "true", 1, "yes"):
        assert publish_store.normalize_config({"enabled": truthy})["enabled"] is False
    assert publish_store.normalize_config({"enabled": True})["enabled"] is True


def test_normalize_config_intervallo_limitato():
    assert publish_store.normalize_config({"interval_hours": 0})["interval_hours"] == \
        publish_store.MIN_INTERVAL_HOURS
    assert publish_store.normalize_config({"interval_hours": 99_999})["interval_hours"] == \
        publish_store.MAX_INTERVAL_HOURS
    # non numerico / bool → default (True non è "1 ora")
    assert publish_store.normalize_config({"interval_hours": "x"})["interval_hours"] == \
        publish_store.DEFAULTS["interval_hours"]
    assert publish_store.normalize_config({"interval_hours": True})["interval_hours"] == \
        publish_store.DEFAULTS["interval_hours"]


def test_normalize_config_scarta_campi_segreti():
    """Un eventuale `token` nel dict NON deve sopravvivere alla normalizzazione (mai su disco)."""
    norm = publish_store.normalize_config({"repo": "a/b", "token": "ghp_SEGRETO"})
    assert "token" not in norm
    assert "ghp_SEGRETO" not in json.dumps(norm)


# ── validazione ──────────────────────────────────────────────────────────────────────────────────
def test_validate_config_repo():
    assert publish_store.validate_config({"repo": "tizio/xtrader-revocation"}) is None
    for bad in ("", "solo-nome", "a/b/c", "tizio /x", "/x", "x/"):
        assert publish_store.validate_config({"repo": bad}) is not None


def test_validate_config_repo_solo_caratteri_ammessi_da_github():
    """Il `repo` finisce **grezzo** in due URL (Contents API e raw): un `%`, `?` o `#` li deformerebbe
    entrambi (query-string/fragment al posto del path) → 404 → nessuna lista pubblicata e bridge
    bloccati fail-closed (rilievo Fable #158). Nessun repository GitHub legittimo li contiene."""
    for cattivo in ("owner/na%me", "owner/na?me", "owner/na#me", "owner/na me", "owner/na\tme",
                    "own er/x", "owner/", "/nome", "owner/x:y", "owner/x@y"):
        assert publish_store.validate_config({"repo": cattivo}) is not None, cattivo
    # ...e tutto ciò che GitHub ammette davvero resta valido
    for buono in ("Owner-1/repo_name.v2", "a/b", "zarbopiero963-droid/xtrader-revocation"):
        assert publish_store.validate_config({"repo": buono}) is None, buono


# ── persistenza (atomica, fail-safe) ────────────────────────────────────────────────────────────
def test_save_e_load_round_trip(tmp_path):
    cfg = {"enabled": True, "repo": "tizio/x", "path": "l.txt", "branch": "main", "interval_hours": 8}
    publish_store.save_publish_config(cfg, directory=str(tmp_path))
    assert publish_store.load_publish_config(directory=str(tmp_path)) == cfg


def test_save_non_scrive_mai_il_token(tmp_path):
    """Anche passando un `token` nel dict, il file su disco NON deve contenerlo (invariante #157)."""
    publish_store.save_publish_config(
        {"repo": "tizio/x", "token": "ghp_SUPERSEGRETO", "enabled": True}, directory=str(tmp_path))
    testo = open(publish_store.publish_config_path(str(tmp_path)), encoding="utf-8").read()
    assert "ghp_SUPERSEGRETO" not in testo and "token" not in testo


def test_load_file_assente_o_corrotto_default(tmp_path):
    assert publish_store.load_publish_config(directory=str(tmp_path)) == \
        publish_store.normalize_config({})                      # assente
    path = publish_store.publish_config_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("{non-json")                                    # corrotto
    assert publish_store.load_publish_config(directory=str(tmp_path))["enabled"] is False


# ── keyring (backend FINTO: nessun keyring reale nei test) ──────────────────────────────────────
class _FakeKeyring:
    def __init__(self, *, broken=False):
        self.store, self.broken = {}, broken

    def get_password(self, service, account):
        if self.broken:
            raise RuntimeError("backend non disponibile")
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        if self.broken:
            raise RuntimeError("backend non disponibile")
        self.store[(service, account)] = value

    def delete_password(self, service, account):
        if self.broken:
            raise RuntimeError("backend non disponibile")
        self.store.pop((service, account), None)


@pytest.fixture()
def fake_kr(monkeypatch):
    kr = _FakeKeyring()
    monkeypatch.setattr(publish_store, "_keyring", lambda: kr)
    return kr


def test_token_round_trip_nel_keyring(fake_kr):
    assert publish_store.keyring_available() is True
    assert publish_store.save_publish_token("ghp_ABC") is True
    assert publish_store.load_publish_token() == "ghp_ABC"
    # salvato nello spazio dei nomi DEDICATO al License Manager (non quello del bridge)
    assert fake_kr.store[(publish_store.SERVICE, publish_store.ACCOUNT_TOKEN)] == "ghp_ABC"
    assert publish_store.SERVICE != "XTraderBridge"
    assert publish_store.delete_publish_token() is True
    assert publish_store.load_publish_token() is None


def test_token_vuoto_non_si_salva(fake_kr):
    for vuoto in ("", "   ", None):
        assert publish_store.save_publish_token(vuoto) is False
    assert publish_store.load_publish_token() is None


def test_keyring_assente_o_rotto_fail_safe(monkeypatch):
    """Senza backend (o con backend che solleva): niente crash, tutto ritorna «non disponibile»."""
    monkeypatch.setattr(publish_store, "_keyring", lambda: None)
    assert publish_store.keyring_available() is False
    assert publish_store.save_publish_token("x") is False
    assert publish_store.load_publish_token() is None
    assert publish_store.delete_publish_token() is False
    monkeypatch.setattr(publish_store, "_keyring", lambda: _FakeKeyring(broken=True))
    assert publish_store.keyring_available() is False
    assert publish_store.save_publish_token("x") is False
    assert publish_store.load_publish_token() is None


def test_keyring_import_fallito_non_rompe(monkeypatch):
    """`_keyring()` inghiotte un import rotto (dipendenza opzionale) → `None`, mai eccezione."""
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "keyring":
            raise ImportError("keyring non installato")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _boom)
    assert publish_store._keyring() is None
    assert isinstance(types.SimpleNamespace(), object)      # sanity: il test non ha rotto l'import


# ── vincolo cadenza ↔ finestra di freschezza del bridge (rilievo CodeRabbit/Fable/Fugu #158) ─────
def test_intervallo_massimo_derivato_dalla_finestra_del_bridge():
    """Il cap NON è un numero ricopiato: è **derivato** da `MAX_LIST_AGE_S` del bridge, e resta con
    margine sotto la finestra — così anche **saltando un giro** la lista è ancora fresca."""
    from xtrader_bridge.licensing import revocation_client
    finestra_h = revocation_client.MAX_LIST_AGE_S // 3600
    assert publish_store.MAX_INTERVAL_HOURS < finestra_h, "una cadenza ≥ finestra garantisce il lockout"
    assert 2 * publish_store.MAX_INTERVAL_HOURS < finestra_h, "un tick saltato non deve far scadere"
    assert publish_store.DEFAULTS["interval_hours"] <= publish_store.MAX_INTERVAL_HOURS


def test_cap_assoluto_ventiquattro_ore_con_finestra_di_tre_giorni():
    """Pin **assoluto** del cap, accanto a quello relativo qui sopra (rilievo CodeRabbit #180).

    Le asserzioni relative confrontano il cap con la finestra: restano vere anche se la coppia
    regredisse *insieme* (finestra 24 h + cap 8 h). Questo test fissa il valore che la decisione del
    proprietario implica — finestra di 3 giorni → cap di 24 h — così una regressione della finestra o
    della formula di derivazione diventa rossa qui, non silenziosa."""
    from xtrader_bridge.licensing import revocation_client
    assert revocation_client.MAX_LIST_AGE_S == 3 * 24 * 3600
    assert publish_store.MAX_INTERVAL_HOURS == 24


def test_intervallo_oltre_la_finestra_viene_limitato():
    """Chiedere 48 h (oltre il cap di 24 h) non può passare: viene limitato al cap sicuro,
    invece di salvare una configurazione che bloccherebbe tutti i bridge."""
    assert publish_store.normalize_config({"interval_hours": 48})["interval_hours"] == \
        publish_store.MAX_INTERVAL_HOURS
    assert publish_store.normalize_config({"interval_hours": 168})["interval_hours"] == \
        publish_store.MAX_INTERVAL_HOURS


def test_validate_config_rifiuta_spazi_in_path_e_branch():
    """Spazi in `path`/`branch` finiscono in DUE URL diversi (API e raw): meglio rifiutarli subito
    che produrre un URL non scaricabile dal bridge → lockout (rilievo Fugu #158)."""
    base = {"repo": "tizio/x"}
    assert publish_store.validate_config({**base, "path": "lista revoche.txt"}) is not None
    assert publish_store.validate_config({**base, "branch": "main dev"}) is not None
    assert publish_store.validate_config({**base, "path": "sub/lista.txt", "branch": "main"}) is None


def test_validate_config_rifiuta_anche_tab_newline_e_spazi_unicode():
    """Il controllo usa `isspace()`, quindi non copre solo lo spazio semplice (rilievo GPT-5.5 #158):
    tab, a-capo e spazi Unicode (NBSP) romperebbero i due URL allo stesso modo. `strip()` toglie solo
    quelli **ai bordi**: questi stanno in mezzo e devono essere rifiutati esplicitamente."""
    base = {"repo": "tizio/x"}
    for cattivo in ("lista\trevoche.txt", "lista\nrevoche.txt", "lista\u00a0revoche.txt"):
        assert publish_store.validate_config({**base, "path": cattivo}) is not None, cattivo
    for cattivo in ("main\tdev", "main\ndev", "main\u00a0dev"):
        assert publish_store.validate_config({**base, "branch": cattivo}) is not None, cattivo
    # un branch con `/` (es. `feature/x`) NON è whitespace: resta valido
    assert publish_store.validate_config({**base, "branch": "feature/x"}) is None


# ── stato «ultima pubblicazione riuscita» (#157) ─────────────────────────────────────────────────
_T0 = 1_700_000_000


def test_last_publish_round_trip(tmp_path):
    """Scritto e riletto: è la persistenza che rende l'etichetta utile dopo aver chiuso il programma."""
    assert publish_store.load_last_publish(directory=str(tmp_path)) is None      # mai pubblicato
    publish_store.save_last_publish(_T0, directory=str(tmp_path))
    assert publish_store.load_last_publish(directory=str(tmp_path)) == _T0


def test_last_publish_file_assente_corrotto_o_valore_assurdo_none(tmp_path):
    """**Fail-safe nella direzione sicura**: qualunque anomalia → «mai pubblicato», che mostra una
    situazione peggiore del reale e porta a controllare. Il contrario (fingere freschezza) sarebbe il
    guasto muto che questa etichetta esiste per eliminare."""
    d = str(tmp_path)
    path = publish_store.publish_state_path(d)
    assert publish_store.load_last_publish(directory=d) is None                  # assente
    for contenuto in ("{non-json", '{"altro": 1}', '{"last_publish_ok": "ieri"}',
                      '{"last_publish_ok": 0}', '{"last_publish_ok": -5}',
                      '{"last_publish_ok": true}', '[1, 2, 3]'):
        with open(path, "w", encoding="utf-8") as f:
            f.write(contenuto)
        assert publish_store.load_last_publish(directory=d) is None, contenuto


def test_save_last_publish_non_solleva_su_percorso_non_scrivibile(tmp_path):
    """La pubblicazione è già riuscita: non deve diventare un fallimento perché il file di stato non
    si scrive. Si passa una cartella occupata da un FILE, così `makedirs` non può crearla."""
    ostacolo = tmp_path / "occupato"
    ostacolo.write_text("non sono una cartella", encoding="utf-8")
    publish_store.save_last_publish(_T0, directory=str(ostacolo))    # non deve sollevare
    assert publish_store.load_last_publish(directory=str(ostacolo)) is None


def test_freshness_soglie_derivate_dalla_finestra_del_bridge():
    """Le soglie NON sono numeri ricopiati: `expired` alla finestra (da lì il bridge blocca), `warn` a
    un terzo (la cadenza massima ammessa → un giro saltato). Si derivano dalla costante, così non
    possono divergere se la finestra cambia."""
    from xtrader_bridge.licensing import revocation_client
    finestra = revocation_client.MAX_LIST_AGE_S
    terzo = finestra // 3

    def stato(eta):
        return publish_store.publish_freshness(_T0, _T0 + eta)["state"]

    assert stato(0) == publish_store.FRESHNESS_OK
    assert stato(terzo - 1) == publish_store.FRESHNESS_OK
    assert stato(terzo) == publish_store.FRESHNESS_WARN          # limite incluso
    assert stato(finestra - 1) == publish_store.FRESHNESS_WARN
    assert stato(finestra) == publish_store.FRESHNESS_EXPIRED    # limite incluso
    assert publish_store.publish_freshness(None, _T0)["state"] == publish_store.FRESHNESS_NEVER


def test_freshness_orologio_spostato_indietro_non_finge_freschezza():
    """`age` negativo (orologio riportato indietro) è trattato come 0: non si inventa un futuro, ma
    nemmeno si allarma per un aggiustamento d'orario."""
    fresh = publish_store.publish_freshness(_T0, _T0 - 5000)
    assert fresh["age_s"] == 0 and fresh["state"] == publish_store.FRESHNESS_OK


def test_format_last_publish_dice_la_conseguenza_negli_stati_di_allarme():
    """«3 giorni fa» da solo non dice a chi legge che cosa comporta: negli stati di allarme il testo
    deve nominare la conseguenza, altrimenti l'etichetta informa senza far agire."""
    from xtrader_bridge.licensing import revocation_client
    finestra = revocation_client.MAX_LIST_AGE_S

    mai, stato_mai = publish_store.format_last_publish(None, _T0)
    assert stato_mai == publish_store.FRESHNESS_NEVER and "mai" in mai

    ok, stato_ok = publish_store.format_last_publish(_T0 - 7200, _T0)
    assert stato_ok == publish_store.FRESHNESS_OK
    assert "2 ore fa" in ok and "⛔" not in ok and "⚠️" not in ok

    warn, stato_warn = publish_store.format_last_publish(_T0 - (finestra // 3) - 60, _T0)
    assert stato_warn == publish_store.FRESHNESS_WARN and "⚠️" in warn and "saltato" in warn

    scaduto, stato_scaduto = publish_store.format_last_publish(_T0 - finestra - 60, _T0)
    assert stato_scaduto == publish_store.FRESHNESS_EXPIRED
    assert "⛔" in scaduto and "non si propagano" in scaduto.lower(), (
        "il testo deve dire la conseguenza VERA: col fail-open (2026-07-30) una lista scaduta non "
        "blocca più i bridge, ma ferma la propagazione delle revoche")


def test_eta_leggibile_singolari_e_plurali():
    """Piccolo ma reale: «1 ore fa» o «1 giorni fa» in un'etichetta permanente si notano."""
    casi = {0: "meno di un'ora fa", 3599: "meno di un'ora fa", 3600: "1 ora fa",
            2 * 3600: "2 ore fa", 24 * 3600: "1 giorno fa", 25 * 3600: "1 giorno e 1 ora fa",
            50 * 3600: "2 giorni e 2 ore fa", 48 * 3600: "2 giorni fa"}
    for secondi, atteso in casi.items():
        assert publish_store._eta_leggibile(secondi) == atteso, secondi


def test_stato_e_impostazioni_restano_file_separati(tmp_path):
    """Lo stato non deve inquinare le impostazioni: `normalize_config` scarterebbe la chiave, e un
    utente non deve poter scrivere a mano «ho pubblicato adesso» dentro la configurazione."""
    d = str(tmp_path)
    assert publish_store.publish_state_path(d) != publish_store.publish_config_path(d)
    publish_store.save_last_publish(_T0, directory=d)
    publish_store.save_publish_config({"repo": "tizio/x", "enabled": True}, directory=d)
    assert "last_publish_ok" not in publish_store.load_publish_config(directory=d)
    assert publish_store.load_last_publish(directory=d) == _T0      # non travolto dal salvataggio


def test_timestamp_assurdo_non_lascia_l_etichetta_vuota():
    """`localtime` solleva `OSError` per valori enormi (e su **Windows** l'intervallo è più stretto
    che su Linux). Se l'eccezione arrivasse al chiamante, `_refresh_publish_status` la catturerebbe e
    l'etichetta resterebbe **vuota** — cioè silenzio, il guasto stesso che questa etichetta elimina.

    Deve invece degradare a un messaggio parlante, nello stato più grave (rosso), che porta a
    guardare. Rilievo Fugu #181, declassato da lui a non bloccante ma reale."""
    import time as _t
    assurdo = 2 ** 63 - 1
    # La precondizione accetta l'INTERA tupla del contratto del codice, non una sola eccezione:
    # quale delle tre sollevi `localtime` per un valore fuori range dipende dalla piattaforma
    # (Linux tipicamente `OSError`, Windows può dare `OverflowError`). Fissarne una sola renderebbe
    # il test rosso su Windows **pur essendo il codice corretto** (rilievo GPT-5.5 #181).
    with pytest.raises((OSError, OverflowError, ValueError)):
        _t.localtime(assurdo)

    testo, stato = publish_store.format_last_publish(assurdo, _T0)

    assert testo, "l'etichetta non deve MAI restare vuota"
    assert "non leggibile" in testo
    assert "Pubblica ora" in testo, "deve dire COSA fare, non solo che c'è un problema"
    assert stato == publish_store.FRESHNESS_EXPIRED


@pytest.mark.parametrize("errore", [OSError, OverflowError, ValueError])
def test_ogni_errore_di_localtime_degrada_senza_svuotare_l_etichetta(errore, monkeypatch):
    """Verifica DETERMINISTICA dello stesso contratto, indipendente dalla piattaforma: si forza
    `localtime` a sollevare ciascuna delle tre eccezioni catturate. Il test sopra dipende da come si
    comporta il sistema operativo reale; questo pinna il contratto e basta."""
    def esplode(_ts):
        raise errore("fuori range")
    monkeypatch.setattr(publish_store._time, "localtime", esplode)

    testo, stato = publish_store.format_last_publish(_T0 - 3600, _T0)

    assert "non leggibile" in testo and stato == publish_store.FRESHNESS_EXPIRED
