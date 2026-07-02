"""Test della configurazione (PR-02 → PR-04).

`load`/`save`/`migrate` sono funzioni pure in `xtrader_bridge.config_store`,
testabili headless con path temporanei. PR-04: cartella utente persistente
(`%APPDATA%`), migrazione del config legacy, backup di config corrotta.
"""

import json
import os

from xtrader_bridge import config_store


def _fake_keyring(monkeypatch, store, available=True):
    """Sostituisce `token_store` con un dizionario in memoria (deterministico, offline):
    `available`/`save`/`load`/`delete` operano su `store["t"]`."""
    monkeypatch.setattr(config_store.token_store, "available", lambda: available)
    monkeypatch.setattr(config_store.token_store, "save_token",
                        lambda t: bool(t) and (store.__setitem__("t", t) or True))
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: store.get("t"))
    # `load_token_status` (#140): la lettura riesce quando il backend è disponibile; in quel
    # caso ritorna `(valore, True)` (None se assente), altrimenti `(None, False)` (lettura fallita).
    monkeypatch.setattr(config_store.token_store, "load_token_status",
                        lambda: (store.get("t"), True) if available else (None, False))

    def _del():
        existed = "t" in store
        store.pop("t", None)
        return existed
    monkeypatch.setattr(config_store.token_store, "delete_token", _del)


def test_save_config_token_va_nel_keyring_non_in_chiaro(tmp_path, monkeypatch):
    # Audit #105 P1: con keyring disponibile il bot_token NON va in chiaro sul disco,
    # ma resta nella config in memoria (per il runtime) e viene re-iniettato al load.
    store = {}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    saved, ok = config_store.save_config({"bot_token": "123:SECRET", "provider": "X"}, str(p))
    assert ok is True
    assert saved["bot_token"] == "123:SECRET"               # in memoria: presente (runtime)
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token"] == ""                       # su disco: NON in chiaro
    assert on_disk["bot_token_storage"] == "keyring"        # sentinel di stato esplicito
    assert store["t"] == "123:SECRET"                       # nel keyring
    # load: sentinel "keyring" + chiave vuota → re-iniezione dal keyring.
    loaded = config_store.load_config(str(p))
    assert loaded["bot_token"] == "123:SECRET"


def test_clear_con_delete_fallito_non_risuscita_il_token_al_load(tmp_path, monkeypatch):
    # CodeRabbit (Major): un clear con delete keyring FALLITO non deve far risorgere il
    # token al load successivo. Il sentinel "none" impedisce la reidratazione anche se un
    # vecchio valore resta orfano nel keyring.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    monkeypatch.setattr(config_store.token_store, "delete_token", lambda: False)  # delete fallisce
    p = tmp_path / "config.json"
    config_store.save_config({"bot_token": "", "provider": "X"}, str(p))   # clear esplicito
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "none"           # stato: cancellato
    assert store["t"] == "OLD:TOKEN"                         # orfano nel keyring (delete fallito)
    # load: sentinel "none" → NON reidrata, il token resta cancellato (niente resurrezione).
    assert config_store.load_config(str(p))["bot_token"] == ""


def test_save_config_fallback_plaintext_se_keyring_assente(tmp_path, monkeypatch):
    # Senza backend keyring (`available()` → False) si RIPIEGA sul comportamento storico:
    # token in chiaro nel config (il bridge resta usabile), nessun crash.
    _fake_keyring(monkeypatch, {}, available=False)
    p = tmp_path / "config.json"
    saved, ok = config_store.save_config({"bot_token": "123:SECRET"}, str(p))
    assert ok is True
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token"] == "123:SECRET"             # fallback: plaintext
    assert saved["bot_token"] == "123:SECRET"


def test_save_config_parziale_senza_bot_token_non_tocca_il_keyring(tmp_path, monkeypatch):
    # Codex P1: un save che OMETTE `bot_token` (save parziale) NON deve cancellare il
    # token migrato nel keyring.
    store = {"t": "LIVE:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    config_store.save_config({"provider": "X", "chat_id": "1"}, str(p))   # niente bot_token
    assert store.get("t") == "LIVE:TOKEN"                   # credenziale preservata (non cancellata)


def test_save_full_poi_save_che_conserva_il_sentinel_reidrata(tmp_path, monkeypatch):
    # Flusso realistico: un save completo migra il token nel keyring e scrive sentinel
    # "keyring"; un save successivo che PORTA quel sentinel (come fa `self._config`) mantiene
    # la chiave vuota su disco e il load reidrata.
    store = {}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    saved, _ = config_store.save_config({"bot_token": "123:SECRET"}, str(p))
    # `saved` (config in memoria) ha il token; un re-save tipico parte da lì.
    config_store.save_config({**saved, "provider": "Y"}, str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token"] == "" and on_disk["bot_token_storage"] == "keyring"
    assert config_store.load_config(str(p))["bot_token"] == "123:SECRET"


def test_save_config_disco_fallito_rollback_del_keyring(tmp_path, monkeypatch):
    # Codex P2: se la scrittura del config fallisce, il keyring viene riportato allo stato
    # precedente (rollback) — una save "fallita" non persiste il cambio credenziale.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)

    def _boom(*a, **k):
        raise OSError("disco pieno (simulato)")
    monkeypatch.setattr(config_store.atomic_io, "atomic_write_json", _boom)
    p = tmp_path / "config.json"
    saved, ok = config_store.save_config({"bot_token": "NEW:TOKEN", "provider": "X"}, str(p))
    assert ok is False
    assert store["t"] == "OLD:TOKEN"                        # keyring ROLLED BACK al valore prima
    assert saved["bot_token"] == "NEW:TOKEN"                # in memoria resta il nuovo


def test_save_config_pre_read_keyring_fallita_non_sovrascrive_ne_perde(tmp_path, monkeypatch):
    """#140 (PR-08a, Codex): se la PRE-LETTURA del keyring fallisce (`load_token_status` →
    read_ok False) non si può garantire un rollback sicuro → NON si sovrascrive il keyring (un
    save fallito cambierebbe la credenziale in modo irreversibile) e NON si cancella nulla. Il
    token NON è persistito → il save è riportato NON riuscito (`ok=False`); il keyring resta intatto.

    Fail-first: prima si chiamava comunque `save_token` (sovrascrivendo il keyring) e si ritornava
    `ok=True` pur senza un rollback possibile."""
    store = {"t": "PREEXISTING:TOKEN"}      # c'è un token, ma non è leggibile ORA
    saved_calls = {"n": 0}
    deleted = {"n": 0}
    monkeypatch.setattr(config_store.token_store, "available", lambda: True)

    def _save(t):
        saved_calls["n"] += 1
        store["t"] = t
        return True
    monkeypatch.setattr(config_store.token_store, "save_token", _save)
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: None)
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (None, False))  # read FALLITA

    def _del():
        deleted["n"] += 1
        store.pop("t", None)
        return True
    monkeypatch.setattr(config_store.token_store, "delete_token", _del)

    # Config GIÀ su disco (install keyring-backed): provider "OLD". Il save differito NON deve
    # toccarla — né il token né il provider cambiato (Codex P2: `ok=False` = niente su disco).
    p = tmp_path / "config.json"
    before = json.dumps({"bot_token": "", "bot_token_storage": "keyring", "provider": "OLD"}, indent=2)
    p.write_text(before, encoding="utf-8")
    saved, ok = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "bot_token_storage": "keyring", "provider": "NEW"}, str(p))
    assert ok is False                          # token non persistito → save NON riuscito
    assert saved_calls["n"] == 0                # keyring NON sovrascritto (nessun rollback possibile)
    assert deleted["n"] == 0                    # né cancellato
    assert store["t"] == "PREEXISTING:TOKEN"    # token preesistente intatto
    raw = p.read_text(encoding="utf-8")
    assert raw == before                        # disco INVARIATO: né token né provider "NEW" scritti
    assert "NEW:TOKEN" not in raw
    assert json.loads(raw)["provider"] == "OLD"   # il cambio non-token NON è atterrato su disco


def test_save_token_fallito_con_stato_keyring_non_declassa_a_plaintext(tmp_path, monkeypatch):
    """#140 (PR-08a, Codex): `available()` True ma `save_token` fallito e stato precedente
    "keyring": NON declassare a plaintext (esporrebbe in chiaro un segreto prima protetto).
    Si preserva "keyring", non si scrive alcun token in chiaro su disco, e il save è riportato
    NON riuscito (il token nuovo non è stato persistito).

    Fail-first: col vecchio fallback la chiave `bot_token` restava col valore in chiaro e il
    sentinel diventava "plaintext"; e il save riportava successo."""
    store = {"t": "OLD:KEYRING:TOKEN"}
    monkeypatch.setattr(config_store.token_store, "available", lambda: True)
    monkeypatch.setattr(config_store.token_store, "save_token", lambda t: False)   # set FALLISCE
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: store.get("t"))
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (store.get("t"), True))
    p = tmp_path / "config.json"
    before = json.dumps({"bot_token": "", "bot_token_storage": "keyring", "provider": "OLD"}, indent=2)
    p.write_text(before, encoding="utf-8")
    saved, ok = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "bot_token_storage": "keyring", "provider": "NEW"}, str(p))
    raw = p.read_text(encoding="utf-8")
    assert ok is False                                      # token non persistito → save NON riuscito
    assert raw == before                                    # disco INVARIATO (abort atomico)
    assert "NEW:TOKEN" not in raw                           # il token nuovo non finisce in chiaro
    assert json.loads(raw)["provider"] == "OLD"             # cambio non-token NON persistito
    assert store["t"] == "OLD:KEYRING:TOKEN"                # vecchio token keyring intatto


def test_save_token_fallito_senza_stato_keyring_resta_plaintext(tmp_path, monkeypatch):
    """#140 (PR-08a) contro-prova: `save_token` fallito SENZA stato keyring precedente (prima
    installazione) mantiene il fallback storico al plaintext — il comportamento non keyring non
    regredisce."""
    monkeypatch.setattr(config_store.token_store, "available", lambda: True)
    monkeypatch.setattr(config_store.token_store, "save_token", lambda t: False)
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: None)
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (None, True))
    p = tmp_path / "config.json"
    config_store.save_config({"bot_token": "NEW:TOKEN", "provider": "X"}, str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "plaintext"      # nessuno stato keyring → fallback storico
    assert on_disk["bot_token"] == "NEW:TOKEN"


def test_keyring_non_disponibile_con_stato_keyring_segnala_save_non_riuscito(tmp_path, monkeypatch):
    """#140 (PR-08a, Codex P2 / CodeRabbit Major): stato precedente "keyring" + keyring NON
    disponibile ORA (outage transitorio) — il token NUOVO non può essere persistito né nel keyring
    né (per non esporlo) in chiaro. Il save deve riportare `ok=False`: la GUI non deve mostrare
    "salvato" mentre il token nuovo è fuori sia da keyring sia da disco. Il vecchio token resta
    reidratabile (sentinel "keyring", nessun declassamento a plaintext).

    Fail-first: prima questo ramo NON impostava `token_not_persisted`, quindi ritornava `ok=True`
    pur avendo scartato il token nuovo."""
    _fake_keyring(monkeypatch, {"t": "OLD:KEYRING:TOKEN"}, available=False)   # keyring giù ORA
    p = tmp_path / "config.json"
    before = json.dumps({"bot_token": "", "bot_token_storage": "keyring", "provider": "OLD"}, indent=2)
    p.write_text(before, encoding="utf-8")
    saved, ok = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "bot_token_storage": "keyring", "provider": "NEW"}, str(p))
    raw = p.read_text(encoding="utf-8")
    assert ok is False                                      # token non persistito → save NON riuscito
    assert raw == before                                    # disco INVARIATO (abort atomico)
    assert "NEW:TOKEN" not in raw                           # il token nuovo non finisce in chiaro
    assert json.loads(raw)["provider"] == "OLD"             # cambio non-token NON persistito
    assert saved["bot_token"] == "NEW:TOKEN"                # in memoria resta (runtime), ma non persistito


def test_pre_read_fallita_su_install_plaintext_non_perde_il_token_in_chiaro(tmp_path, monkeypatch):
    """#140 (PR-08a, Codex P2 line 478): install PLAINTEXT (`bot_token_storage="plaintext"`) +
    keyring probe OK ma `load_token_status` fallita (read_ok False). Non c'è alcuna credenziale
    migrata nel keyring da proteggere e il token è già su disco in chiaro: azzerarlo lo
    CANCELLEREBBE (una GUI re-invia sempre il campo token, anche cambiando un'altra impostazione).
    Si deve PRESERVARE il token in chiaro, sentinel "plaintext", save RIUSCITO.

    Fail-first: prima questo ramo scriveva `bot_token=""` + sentinel "none" → token in chiaro
    perso dopo il riavvio."""
    monkeypatch.setattr(config_store.token_store, "available", lambda: True)
    monkeypatch.setattr(config_store.token_store, "save_token", lambda t: True)
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: None)
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (None, False))  # read FALLITA
    monkeypatch.setattr(config_store.token_store, "delete_token", lambda: True)
    p = tmp_path / "config.json"
    saved, ok = config_store.save_config(
        {"bot_token": "PLAIN:TOKEN", "bot_token_storage": "plaintext", "provider": "X"}, str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert ok is True                                       # token già su disco → save riuscito
    assert on_disk["bot_token"] == "PLAIN:TOKEN"            # token in chiaro PRESERVATO (non cancellato)
    assert on_disk["bot_token_storage"] == "plaintext"     # resta plaintext (nessun "none")
    assert config_store.load_config(str(p))["bot_token"] == "PLAIN:TOKEN"   # riavvio: ancora presente


def test_token_differito_non_persiste_parzialmente_impostazioni_non_token(tmp_path, monkeypatch):
    """#140 (PR-08a, Codex P2 line 658): quando il token è DIFFERITO (`token_not_persisted`) il
    save ritorna `ok=False`, e i chiamanti lo interpretano come "niente persistito su disco". Se
    `save_config` avesse comunque scritto le ALTRE impostazioni e poi tornato `ok=False`, un cambio
    safety-critical come `dry_run` (reale↔test) sopravvivrebbe al riavvio pur essendo segnalato come
    fallito. L'esito deve essere ATOMICO: disco INVARIATO, `ok=False`.

    Fail-first: prima dell'abort il ramo differito scriveva `to_save` su disco (incluso il nuovo
    `dry_run`) e tornava `ok=False` → l'impostazione non-token persisteva di nascosto."""
    _fake_keyring(monkeypatch, {"t": "OLD:KEYRING:TOKEN"}, available=False)   # keyring giù → token differito
    p = tmp_path / "config.json"
    before = json.dumps({"bot_token": "", "bot_token_storage": "keyring", "dry_run": True}, indent=2)
    p.write_text(before, encoding="utf-8")
    saved, ok = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "bot_token_storage": "keyring", "dry_run": False}, str(p))
    assert ok is False                                      # token differito → save NON riuscito
    assert p.read_text(encoding="utf-8") == before         # disco INVARIATO
    assert json.loads(p.read_text(encoding="utf-8"))["dry_run"] is True   # dry_run NON declassato su disco
    assert saved["dry_run"] is False                       # in memoria la modifica c'è (runtime), ma non su disco


def test_save_config_keyring_first_token_nel_keyring_prima_del_disco(tmp_path, monkeypatch):
    # Codex P2 (crash-safe): `save_token` deve avvenire PRIMA della scrittura su disco, così
    # un crash tra le due non perde il token (il keyring ha già il valore quando il disco
    # dice "keyring"). Verifichiamo l'ordine delle chiamate.
    order = []
    store = {}
    _fake_keyring(monkeypatch, store)
    real_save = config_store.token_store.save_token
    monkeypatch.setattr(config_store.token_store, "save_token",
                        lambda t: order.append("keyring") or real_save(t))
    real_write = config_store.atomic_io.atomic_write_json
    monkeypatch.setattr(config_store.atomic_io, "atomic_write_json",
                        lambda *a, **k: order.append("disk") or real_write(*a, **k))
    config_store.save_config({"bot_token": "123:SECRET"}, str(tmp_path / "config.json"))
    assert order == ["keyring", "disk"]                     # keyring prima del disco


def test_save_config_miss_transiente_keyring_non_declassa_il_sentinel(tmp_path, monkeypatch, caplog):
    # Codex P2: se al load il keyring era TEMPORANEAMENTE non disponibile (available() False),
    # la config in memoria ha bot_token="" ma bot_token_storage="keyring". Salvare un'altra
    # impostazione NON deve declassare il sentinel a "none" (altrimenti, tornato il keyring,
    # il token non verrebbe più reidratato e andrebbe perso). Si avvisa che un eventuale clear
    # è differito.
    store = {"t": "STILL:THERE"}   # token ancora memorizzato, ma keyring non leggibile ora
    _fake_keyring(monkeypatch, store, available=False)
    p = tmp_path / "config.json"
    import logging
    with caplog.at_level(logging.WARNING):
        config_store.save_config(
            {"bot_token": "", "bot_token_storage": "keyring", "provider": "X"}, str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "keyring"        # sentinel PRESERVATO
    assert store["t"] == "STILL:THERE"                      # keyring non toccato
    assert any("keyring" in r.message.lower() for r in caplog.records)


def test_save_config_mirror_sentinel_in_memoria(tmp_path, monkeypatch):
    # Codex P2: la config restituita (poi tenuta come self._config) deve avere il sentinel
    # COERENTE col disco, altrimenti un save successivo riscriverebbe uno stato sbagliato.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store, available=True)
    p = tmp_path / "config.json"
    saved, _ = config_store.save_config({"bot_token": "", "bot_token_storage": "keyring"}, str(p))
    assert saved["bot_token_storage"] == "none"            # in memoria rispecchia il disco
    # E un re-save che parte da `saved` non resuscita il token.
    config_store.save_config({**saved, "provider": "Y"}, str(p))
    assert json.loads(p.read_text(encoding="utf-8"))["bot_token_storage"] == "none"


def test_save_config_outage_transiente_non_declassa_a_plaintext(tmp_path, monkeypatch):
    # Codex P2: token in memoria + stato precedente "keyring" + keyring NON disponibile ORA
    # (outage transiente) NON deve riscrivere il token in chiaro su disco (downgrade silenzioso).
    # Con l'abort del path differito (Codex P2 line 658) il disco resta INVARIATO e `ok=False`.
    _fake_keyring(monkeypatch, {}, available=False)
    p = tmp_path / "config.json"
    before = json.dumps({"bot_token": "", "bot_token_storage": "keyring", "provider": "OLD"}, indent=2)
    p.write_text(before, encoding="utf-8")
    saved, ok = config_store.save_config(
        {"bot_token": "REHYDRATED:TOKEN", "bot_token_storage": "keyring", "provider": "X"}, str(p))
    raw = p.read_text(encoding="utf-8")
    assert ok is False                                     # token differito → save NON riuscito
    assert raw == before                                   # disco INVARIATO (niente downgrade a plaintext)
    assert "REHYDRATED:TOKEN" not in raw                   # mai in chiaro su disco


def test_save_config_rollback_fallito_logga_errore(tmp_path, monkeypatch, caplog):
    # Codex P2: se il disco fallisce E il rollback del keyring fallisce (save_token → False),
    # va loggato un ERRORE esplicito (keyring/disco potenzialmente incoerenti).
    store = {"t": "OLD:TOKEN"}   # stato precedente → il rollback userà save_token(prior)
    _fake_keyring(monkeypatch, store, available=True)
    # save_token: 1ª chiamata (set del nuovo token) riesce, 2ª (rollback) fallisce.
    calls = {"n": 0}

    def _save(t):
        calls["n"] += 1
        if calls["n"] == 1:
            store["t"] = t
            return True
        return False                                       # rollback fallisce
    monkeypatch.setattr(config_store.token_store, "save_token", _save)

    def _boom(*a, **k):
        raise OSError("disco pieno (simulato)")
    monkeypatch.setattr(config_store.atomic_io, "atomic_write_json", _boom)
    p = tmp_path / "config.json"
    import logging
    with caplog.at_level(logging.ERROR):
        _, ok = config_store.save_config({"bot_token": "NEW:TOKEN"}, str(p))
    assert ok is False
    assert any("rollback del keyring" in r.message.lower() for r in caplog.records)


def test_save_config_clear_reale_con_keyring_disponibile(tmp_path, monkeypatch):
    # Keyring LEGGIBILE + campo vuoto = clear reale (se ci fosse un token sarebbe stato
    # reidratato al load). Il sentinel diventa "none" e il token viene rimosso.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store, available=True)
    p = tmp_path / "config.json"
    config_store.save_config({"bot_token": "", "bot_token_storage": "keyring"}, str(p))
    assert json.loads(p.read_text(encoding="utf-8"))["bot_token_storage"] == "none"
    assert "t" not in store                                 # token rimosso dal keyring


def test_save_config_parziale_preserva_il_sentinel_dal_disco(tmp_path, monkeypatch):
    # Codex P2: un save PARZIALE (senza bot_token) dopo che il token è stato migrato deve
    # preservare bot_token/bot_token_storage già su disco, così il load continua a reidratare.
    store = {}
    _fake_keyring(monkeypatch, store, available=True)
    p = tmp_path / "config.json"
    config_store.save_config({"bot_token": "123:SECRET"}, str(p))   # migra: disco ha storage=keyring
    # Save parziale: solo provider, niente bot_token.
    config_store.save_config({"provider": "X"}, str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "keyring"        # sentinel preservato
    assert on_disk["bot_token"] == ""                       # ancora nel keyring, non in chiaro
    assert on_disk["provider"] == "X"                       # l'impostazione parziale è salvata
    assert config_store.load_config(str(p))["bot_token"] == "123:SECRET"   # reidrata ancora


def test_save_config_parziale_su_disco_corrotto_fail_closed_non_orfana_ne_resuscita(tmp_path, monkeypatch):
    """#184 M3 (rivisto dopo Codex P1): un save PARZIALE (senza bot_token né sentinel in
    memoria) quando il `config.json` è CORROTTO è FAIL-CLOSED: NON scrive. Scrivere
    orfanerebbe il token (sentinel perso); "recuperare" dal keyring lo RESUSCITEREBBE se era
    stato cancellato con un delete fallito (keyring ambiguo). Quindi: disco corrotto intatto,
    keyring intatto, `ok=False`. L'utente reinserisce il token in sicurezza.

    Fail-first: sul vecchio codice (pre-M3) la scrittura proseguiva e `on_disk` finiva senza
    `bot_token_storage` (token orfano)."""
    store = {"t": "123:SECRET"}                       # un valore è nel keyring (status AMBIGUO)
    _fake_keyring(monkeypatch, store, available=True)
    p = tmp_path / "config.json"
    corrotto = "{ questo non e' json valido ,,, "
    p.write_text(corrotto, encoding="utf-8")

    out, ok = config_store.save_config({"provider": "X"}, str(p))   # parziale, niente bot_token/sentinel

    assert ok is False                                          # fail-closed: non salvato
    assert out["provider"] == "X"                               # best-effort: config in memoria restituita
    assert p.read_text(encoding="utf-8") == corrotto            # disco NON sovrascritto (corrotto intatto)
    assert store.get("t") == "123:SECRET"                       # keyring NON toccato (né orfano né resuscitato)


def test_save_config_parziale_disco_corrotto_con_sentinel_in_memoria_prosegue(tmp_path, monkeypatch):
    """#184 M3: se il puntatore è già IN MEMORIA (`bot_token_storage` nel cfg passato, es. da
    `self._config` reidratato), c'è evidenza in memoria del backing keyring (Codex P1) → il save
    parziale PROSEGUE preservando il sentinel dalla RAM, senza affidarsi al disco corrotto."""
    store = {"t": "123:SECRET"}
    _fake_keyring(monkeypatch, store, available=True)
    p = tmp_path / "config.json"
    p.write_text("{ corrotto ,,, ", encoding="utf-8")

    # cfg PARZIALE ma con il sentinel in memoria (niente chiave bot_token).
    out, ok = config_store.save_config(
        {"provider": "Z", "bot_token_storage": "keyring"}, str(p))

    assert ok is True
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["provider"] == "Z"
    assert on_disk["bot_token_storage"] == "keyring"            # sentinel preservato dalla MEMORIA
    assert config_store.load_config(str(p))["bot_token"] == "123:SECRET"   # reidrata


def test_save_config_parziale_disco_corrotto_senza_token_keyring_fail_closed(tmp_path, monkeypatch):
    """#184 M3 — controprova: anche senza token nel keyring, un save parziale su config corrotto
    senza sentinel in memoria è fail-closed (non si può sapere se il file corrotto conteneva un
    token plaintext; non si sovrascrive un config corrotto alla cieca)."""
    store = {}                                                  # keyring vuoto
    _fake_keyring(monkeypatch, store, available=True)
    p = tmp_path / "config.json"
    corrotto = "{ corrotto ,,, "
    p.write_text(corrotto, encoding="utf-8")

    out, ok = config_store.save_config({"provider": "Y"}, str(p))

    assert ok is False                                          # fail-closed
    assert p.read_text(encoding="utf-8") == corrotto            # disco corrotto intatto


def test_save_config_fallback_write_fallita_ritorna_ok_false(tmp_path, monkeypatch):
    # Codex P2: keyring `available()` ma `save_token` fallisce → fallback plaintext in UNA
    # sola scrittura; se ANCHE quella fallisce, deve ritornare ok=False (niente falso "salvato").
    monkeypatch.setattr(config_store.token_store, "available", lambda: True)
    monkeypatch.setattr(config_store.token_store, "save_token", lambda t: False)
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: None)

    def _boom(*a, **k):
        raise OSError("disco pieno (simulato)")
    monkeypatch.setattr(config_store.atomic_io, "atomic_write_json", _boom)
    saved, ok = config_store.save_config({"bot_token": "NEW:TOKEN"}, str(tmp_path / "config.json"))
    assert ok is False


def test_save_config_clear_con_delete_fallito_avvisa(tmp_path, monkeypatch, caplog):
    # Codex P2: clear esplicito ma delete dal keyring fallito → warning (non un clear "finto").
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    monkeypatch.setattr(config_store.token_store, "delete_token", lambda: False)  # delete fallisce
    p = tmp_path / "config.json"
    import logging
    with caplog.at_level(logging.WARNING):
        config_store.save_config({"bot_token": "", "provider": "X"}, str(p))
    assert any("rimuovere il bot token" in r.message.lower() or "keyring" in r.message.lower()
               for r in caplog.records)


def test_save_config_token_vuoto_rimuove_dal_keyring(tmp_path, monkeypatch):
    # Azzerare il token (es. l'utente lo cancella) deve rimuovere anche la voce keyring.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    config_store.save_config({"bot_token": "", "provider": "X"}, str(p))
    assert "t" not in store                                 # voce keyring rimossa
    assert json.loads(p.read_text(encoding="utf-8"))["bot_token"] == ""


def test_load_config_token_in_chiaro_preesistente_resta(tmp_path, monkeypatch):
    # Config vecchia con token in chiaro e keyring vuoto: il token si usa com'è
    # (verrà migrato nel keyring al prossimo save). Nessuna re-iniezione che lo sovrascrive.
    store = {}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bot_token": "PLAIN:TOKEN", "provider": "X"}), encoding="utf-8")
    loaded = config_store.load_config(str(p))
    assert loaded["bot_token"] == "PLAIN:TOKEN"


def test_config_file_e_config_json():
    assert config_store.CONFIG_FILE.endswith("config.json")
    assert os.path.isabs(config_store.CONFIG_FILE)


def test_load_config_default_senza_file(tmp_path):
    cfg = config_store.load_config(str(tmp_path / "assente.json"))
    for k in ("bot_token", "chat_id", "csv_path", "clear_delay", "provider"):
        assert k in cfg
    assert isinstance(cfg["clear_delay"], int)
    assert cfg["provider"]                       # default non vuoto


def test_as_bool_optin_allowlist_fail_closed():
    # Helper ALLOWLIST fail-closed per i flag opt-in (privacy/sicurezza): True SOLO per
    # un "sì" esplicito riconosciuto; QUALSIASI altro valore → False (Codex P1).
    assert config_store.as_bool_optin(None) is False
    assert config_store.as_bool_optin("") is False
    assert config_store.as_bool_optin(0) is False
    assert config_store.as_bool_optin(False) is False
    # Falsey espliciti E stringhe non riconosciute / refusi → False (fail-closed).
    for off in ("0", "false", "no", "off", "FALSE", "  off  ",
                "flase", "disabled", "null", "none", "garbage"):
        assert config_store.as_bool_optin(off) is False, off
    # Solo un truthy ESPLICITO riconosciuto → True.
    for on in (True, 1, "1", "true", "TRUE", "  yes  ", "on", "y", "t"):
        assert config_store.as_bool_optin(on) is True, on
    # NaN/Infinity (config.json corrotto o editato a mano) NON sono un "sì" esplicito:
    # fail-closed come `autostart.is_enabled` (#258/#259, finding C8). Prima della patch
    # `value != 0` li faceva passare per True, accendendo opt-in di privacy/Betfair.
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert config_store.as_bool_optin(bad) is False, repr(bad)
    # Int FUORI range float (10**400, JSON li ammette): niente OverflowError da
    # `math.isfinite` (Codex P2 su #299) — un int esplicito ≠ 0 resta True, 0 resta False.
    assert config_store.as_bool_optin(10**400) is True
    assert config_store.as_bool_optin(-(10**400)) is True
    assert config_store.as_bool_optin(0) is False


def test_debug_message_payload_default_off_e_migrazione(tmp_path):
    # Privacy log (audit #105 P1): chiave presente nei default e OFF (privacy on)
    # quando il file non la contiene.
    assert config_store.DEFAULTS["debug_message_payload"] is False
    cfg = config_store.load_config(str(tmp_path / "assente.json"))
    assert cfg["debug_message_payload"] is False
    # Config che NON ha la chiave → resta OFF.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "X"}))
    assert config_store.load_config(str(p))["debug_message_payload"] is False
    # Solo un valore truthy ESPLICITO attiva il log completo (coerce via as_bool).
    p.write_text(json.dumps({"debug_message_payload": True}))
    assert config_store.load_config(str(p))["debug_message_payload"] is True
    p.write_text(json.dumps({"debug_message_payload": "1"}))
    assert config_store.load_config(str(p))["debug_message_payload"] is True
    # Valori falsey, refusi e stringhe non riconosciute → fail-closed a False (privacy on).
    for bad in ("", "0", "false", "no", "off", "flase", "disabled", "null"):
        p.write_text(json.dumps({"debug_message_payload": bad}))
        assert config_store.load_config(str(p))["debug_message_payload"] is False, bad


def test_load_config_merge_con_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "TG_PRE", "chat_id": "-100123"}))
    cfg = config_store.load_config(str(p))
    assert cfg["provider"] == "TG_PRE"
    assert cfg["chat_id"] == "-100123"
    assert "csv_path" in cfg                      # default preservato


def test_load_config_json_malformato_usa_default_e_backup(tmp_path):
    # File presente ma JSON non valido: nessuna eccezione, default preservati,
    # e il file corrotto viene messo da parte come .bak.
    p = tmp_path / "config.json"
    p.write_text("{ questo non e' json valido ,,, ")
    cfg = config_store.load_config(str(p))
    assert cfg["csv_path"] == config_store.DEFAULTS["csv_path"]
    assert cfg["provider"] == config_store.DEFAULTS["provider"]
    assert os.path.exists(str(p) + ".bak")        # backup creato
    assert not os.path.exists(str(p))             # originale rimosso


def test_load_config_json_non_dict_usa_default_e_backup(tmp_path):
    # JSON valido ma non dizionario (es. lista): trattato come corrotto.
    p = tmp_path / "config.json"
    p.write_text("[]")
    cfg = config_store.load_config(str(p))
    assert cfg["provider"] == config_store.DEFAULTS["provider"]
    assert os.path.exists(str(p) + ".bak")        # backup creato
    assert not os.path.exists(str(p))             # originale rimosso


def test_backup_sovrascrive_bak_preesistente(tmp_path):
    # Se esiste già un .bak, il backup non deve fallire (robustezza Windows).
    p = tmp_path / "config.json"
    p.write_text("non json {")
    (tmp_path / "config.json.bak").write_text("vecchio backup")
    config_store.load_config(str(p))              # non deve sollevare
    assert os.path.exists(str(p) + ".bak")
    assert not os.path.exists(str(p))


def test_backup_corrotto_fallito_logga_warning(tmp_path, caplog, monkeypatch):
    # audit #105 P2: se il backup di una config corrotta fallisce (permessi/lock), prima era
    # un `except OSError: pass` SILENZIOSO → ora si logga un warning con path+errore (niente
    # contenuto della config). L'app resta best-effort: load_config ritorna comunque i default.
    p = tmp_path / "config.json"
    p.write_text("{ json corrotto ,,,")

    def boom(src, dst):
        raise OSError("rename del backup non permessa (simulato)")

    monkeypatch.setattr(config_store.os, "replace", boom)
    with caplog.at_level("WARNING", logger="xtrader_bridge.config_store"):
        cfg = config_store.load_config(str(p))    # non deve sollevare
    assert cfg["provider"] == config_store.DEFAULTS["provider"]   # best-effort: default
    assert any("Backup della config corrotta fallito" in r.getMessage() and str(p) in r.getMessage()
               for r in caplog.records)


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    # Forziamo l'assenza del keyring per un roundtrip deterministico: il token resta in
    # chiaro su disco e il sentinel di stato vale "plaintext".
    monkeypatch.setattr(config_store.token_store, "available", lambda: False)
    p = str(tmp_path / "config.json")
    data = {"bot_token": "X", "chat_id": "-1", "csv_path": "/tmp/s.csv",
            "clear_delay": 30, "provider": "TG_LIVE"}
    config_store.save_config(data, p)
    assert config_store.load_config(p) == {**config_store.DEFAULTS, **data,
                                           "bot_token_storage": "plaintext"}


def test_roundtrip_csv_path_windows_backslash_spazi_unicode(tmp_path, monkeypatch):
    # #109/28: un csv_path "Windows-like" (backslash, spazi, unicode) deve sopravvivere
    # al round-trip save→load senza alterazioni. Keyring assente per determinismo.
    monkeypatch.setattr(config_store.token_store, "available", lambda: False)
    p = str(tmp_path / "config.json")
    win_path = r"C:\Users\Pippo Baudo\Segnàli XTrader\bridge.csv"
    data = {"bot_token": "X", "chat_id": "-1", "csv_path": win_path,
            "clear_delay": 30, "provider": "TG_LIVE"}
    config_store.save_config(data, p)
    loaded = config_store.load_config(p)
    assert loaded["csv_path"] == win_path        # backslash/spazi/unicode intatti


def test_defaults_non_contengono_segreti():
    assert config_store.DEFAULTS["bot_token"] == ""
    assert config_store.DEFAULTS["chat_id"] == ""


def test_default_recognition_mode_name_only():
    assert config_store.DEFAULTS["recognition_mode"] == "NAME_ONLY"


# ── #184 M1: _migrate strippa i campi stringa noti (filtro chat non "diventa sordo") ──

def test_migrate_strip_chat_id_evita_filtro_sordo():
    """#184 M1: un `chat_id` con whitespace/newline (config editata a mano o copia-incolla
    da Telegram) deve essere strippato in `_migrate`. Altrimenti `signal_router` confronta
    col valore strippato in ingresso e il filtro single-chat non matcha più → il bridge
    "diventa sordo" su quella chat (fail-closed: nessuna bet sbagliata, ma smette di
    ascoltare). Fail-first: il vecchio `_migrate` salvava il valore non strippato."""
    assert config_store._migrate({"chat_id": "  -100123\n"})["chat_id"] == "-100123"
    assert config_store._migrate({"chat_id": "\t999 "})["chat_id"] == "999"
    # Boundary fail-closed (review Sourcery/CodeRabbit): un chat_id di SOLI whitespace/newline
    # si normalizza a "" — cioè "nessun filtro configurato", non un filtro-fantasma che
    # matcherebbe nulla mascherato da valore valido. Vedi il lock-in a valle qui sotto.
    assert config_store._migrate({"chat_id": " \n\t "})["chat_id"] == ""


def test_migrate_chat_id_solo_whitespace_resta_fail_closed_a_valle():
    """#184 M1 (review Sourcery/CodeRabbit): un `chat_id` di soli whitespace, dopo `_migrate`,
    è `""` e a valle vale "NESSUN filtro configurato" (`has_chat_filter` False), NON un percorso
    "admit-all" nascosto. L'admit-all legacy resta comunque bloccato dal fail-fast d'avvio
    (`app._start`) e dal dispatch `IGNORE_NO_FILTER`. Un id reale (anche con padding), invece,
    resta un filtro valido che ammette SOLO quella chat."""
    from xtrader_bridge import signal_router

    # Soli whitespace → "" → nessun filtro configurato (non un filtro-fantasma).
    vuoto = config_store._migrate({"chat_id": " \n\t "})
    assert vuoto["chat_id"] == ""
    assert signal_router.has_chat_filter(vuoto) is False

    # Id reale con padding → normalizzato → filtro valido che ammette SOLO quella chat.
    reale = config_store._migrate({"chat_id": "  -100123  "})
    assert reale["chat_id"] == "-100123"
    assert signal_router.has_chat_filter(reale) is True
    assert signal_router.is_chat_allowed(reale, "-100123") is True   # la chat configurata passa
    assert signal_router.is_chat_allowed(reale, "-999") is False     # nessun'altra è ammessa


def test_migrate_strip_campi_stringa_noti():
    """#184 M1: tutta l'allowlist `_STRIP_STR_KEYS` viene normalizzata (no padding ai bordi),
    così i valori-modalità e i chat-id combaciano col valore atteso a valle."""
    cfg = config_store._migrate({
        "provider": " TelegramBot ",
        "recognition_mode": "NAME_ONLY\n",
        "queue_mode": "\tOVERWRITE_LAST",
        "active_parser": "  MioParser  ",
        "xtrader_notification_chat_id": " 999 ",
    })
    assert cfg["provider"] == "TelegramBot"
    assert cfg["recognition_mode"] == "NAME_ONLY"
    assert cfg["queue_mode"] == "OVERWRITE_LAST"
    assert cfg["active_parser"] == "MioParser"
    assert cfg["xtrader_notification_chat_id"] == "999"


def test_migrate_strip_e_allowlist_non_tocca_csv_path_ne_bot_token():
    """#184 M1: la strip è una ALLOWLIST mirata. `csv_path` (un path può legittimamente
    contenere spazi; la validazione è un finding separato) e `bot_token` (segreto, gestito
    da `token_store`/keyring, fuori scope) NON vengono toccati da `_migrate`."""
    cfg = config_store._migrate({"csv_path": r"  C:\X T\s.csv  ", "bot_token": "  tok  "})
    assert cfg["csv_path"] == r"  C:\X T\s.csv  "     # path invariato (spazi preservati)
    assert cfg["bot_token"] == "  tok  "              # segreto invariato (gestito altrove)


def test_migrate_strip_dopo_coercizione_di_un_valore_non_stringa():
    """#184 M1: un `chat_id` numerico (JSON `-100123`) viene prima coerciti a stringa e poi
    strippato, senza crash (la strip si applica dopo `str(val)`)."""
    assert config_store._migrate({"chat_id": -100123})["chat_id"] == "-100123"


def test_load_config_strippa_chat_id_da_file(tmp_path):
    """#184 M1 end-to-end: un `config.json` con `chat_id`/`provider` con padding viene
    normalizzato al caricamento (path reale `load_config` → `_migrate`)."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"chat_id": " -100999\n", "provider": "TG_PRE "}))
    cfg = config_store.load_config(str(p))
    assert cfg["chat_id"] == "-100999"
    assert cfg["provider"] == "TG_PRE"


def test_load_config_coercisce_e_strippa_chat_id_numerico_da_file(tmp_path):
    """#184 M1 end-to-end (review Sourcery): un `config.json` con `chat_id` NUMERICO
    (`-100123` come numero JSON, input malformato ma realistico) viene coerciuto a stringa e
    normalizzato via `load_config` → `_migrate`, senza crash."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"chat_id": -100123, "provider": "TG_PRE "}))
    cfg = config_store.load_config(str(p))
    assert cfg["chat_id"] == "-100123"
    assert cfg["provider"] == "TG_PRE"


def test_require_price_non_e_piu_chiave_globale(tmp_path):
    # La quota obbligatoria sì/no NON è più un default globale: la governa la riga
    # Price di ogni Parser Personalizzato (CustomParserDef.price_required).
    assert "require_price" not in config_store.DEFAULTS
    # Una chiave custom arbitraria sopravvive comunque a save→load (config non la perde).
    p = str(tmp_path / "config.json")
    config_store.save_config({"provider": "TG", "custom_flag": False}, p)
    assert config_store.load_config(p)["custom_flag"] is False
    # Compat: una vecchia config con `require_price` NON va in crash e la chiave legacy
    # sopravvive (semplicemente ignorata a runtime, governata ora dalla riga Price).
    p2 = str(tmp_path / "legacy.json")
    config_store.save_config({"provider": "TG", "require_price": False}, p2)
    loaded = config_store.load_config(p2)
    assert loaded["require_price"] is False        # non rimossa, non causa errori
    assert loaded["provider"] == "TG"


# ── PR-04: cartella utente, migrazione, versione ──

def test_config_dir_usa_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", os.path.join("X", "Roaming"))
    d = config_store.config_dir()
    assert d.endswith(config_store.APP_DIR_NAME)
    assert os.path.join("X", "Roaming") in d


def test_config_path_dentro_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = config_store.config_path()
    assert p == os.path.join(str(tmp_path), config_store.APP_DIR_NAME, "config.json")


def test_config_version_presente_nei_default():
    cfg = config_store.load_config(str("/percorso/inesistente/config.json"))
    assert cfg["config_version"] == config_store.CONFIG_VERSION


def test_config_version_aggiunto_e_persistito_da_config_legacy(tmp_path):
    # Config legacy senza config_version: load lo aggiunge, save lo persiste.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "TG_PRE", "csv_path": "x.csv"}))
    cfg = config_store.load_config(str(p))
    assert cfg["config_version"] == config_store.CONFIG_VERSION
    config_store.save_config(cfg, str(p))
    on_disk = json.loads(p.read_text())
    assert on_disk["config_version"] == config_store.CONFIG_VERSION


def test_legacy_path_da_executable_se_frozen(monkeypatch, tmp_path):
    # Nell'EXE PyInstaller il legacy config va cercato accanto a sys.executable.
    exe = tmp_path / "app" / "XTrader-Signal-Bridge.exe"
    monkeypatch.setattr(config_store.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_store.sys, "executable", str(exe), raising=False)
    p = config_store.legacy_config_path()
    assert p == str(tmp_path / "app" / "config.json")


def test_legacy_path_dev_non_frozen(monkeypatch):
    monkeypatch.setattr(config_store.sys, "frozen", False, raising=False)
    p = config_store.legacy_config_path()
    assert p.endswith("config.json") and os.path.isabs(p)


def test_config_version_su_disco_preservato(tmp_path):
    # Se il file porta un config_version diverso (futuro v2), NON viene sovrascritto.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"config_version": 99, "provider": "X"}))
    cfg = config_store.load_config(str(p))
    assert cfg["config_version"] == 99            # skew su disco preservato


def test_migrate_legacy_copia_quando_nuovo_assente(tmp_path):
    legacy = tmp_path / "legacy" / "config.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"provider": "VECCHIO"}))
    new = tmp_path / "appdata" / "XTraderBridge" / "config.json"

    migrated = config_store.migrate_legacy_config(str(new), str(legacy))
    assert migrated is True
    assert new.exists()                           # creato nella nuova posizione
    assert legacy.exists()                        # legacy NON rimosso (non distruttivo)
    assert config_store.load_config(str(new))["provider"] == "VECCHIO"


def test_migrate_legacy_e_atomico_non_lascia_temporanei(tmp_path):
    # audit L3: la migrazione del config legacy ora è ATOMICA (tmp + os.replace, come
    # save_config). Dopo la copia il contenuto è corretto e NON resta alcun temporaneo
    # `.config_*` nella cartella di destinazione (scrittura completata o niente).
    legacy = tmp_path / "legacy" / "config.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"provider": "VECCHIO", "chat_id": "-100"}))
    new = tmp_path / "appdata" / "config.json"
    assert config_store.migrate_legacy_config(str(new), str(legacy)) is True
    assert new.exists()
    assert config_store.load_config(str(new))["provider"] == "VECCHIO"
    # Nessun temporaneo residuo nella cartella di destinazione.
    assert not [f for f in os.listdir(new.parent) if f.startswith(config_store.TMP_PREFIX)]


def test_migrate_legacy_skip_se_nuovo_esiste(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"provider": "VECCHIO"}))
    new = tmp_path / "config.json"
    new.write_text(json.dumps({"provider": "NUOVO"}))

    migrated = config_store.migrate_legacy_config(str(new), str(legacy))
    assert migrated is False
    assert config_store.load_config(str(new))["provider"] == "NUOVO"  # non sovrascritto


def test_migrate_legacy_skip_se_nessun_legacy(tmp_path):
    new = tmp_path / "config.json"
    assert config_store.migrate_legacy_config(str(new), str(tmp_path / "assente.json")) is False
    assert not new.exists()


def test_save_config_logga_errore_io_ma_resta_best_effort(tmp_path, caplog):
    # Persistenza fallita (qui il path è una DIRECTORY → os.replace solleva OSError):
    # l'app prosegue (ritorna la config in memoria) MA ora l'errore è LOGGATO,
    # non più silenzioso (`except: pass`), e `ok` è False (A1: niente falso "salvato").
    target = tmp_path / "sono_una_cartella"
    target.mkdir()
    with caplog.at_level("ERROR", logger="xtrader_bridge.config_store"):
        out, ok = config_store.save_config({"provider": "X"}, str(target))
    assert out["provider"] == "X"                  # best-effort preservato
    assert ok is False                             # A1: la GUI non deve dire "salvato"
    assert any("Salvataggio config fallito" in r.getMessage() for r in caplog.records)
    # Nessun temporaneo lasciato in giro dopo il fallimento.
    assert not [f for f in os.listdir(target.parent) if f.startswith(config_store.TMP_PREFIX)]


def test_save_config_successo_ritorna_ok_e_persiste(tmp_path):
    # Percorso normale: ritorna ok=True, il file è rileggibile con i valori salvati e
    # non resta alcun temporaneo `.config_*` (scrittura atomica completata).
    p = tmp_path / "cfg" / "config.json"
    out, ok = config_store.save_config({"provider": "TG", "chat_id": "123"}, str(p))
    assert ok is True
    assert out["provider"] == "TG"
    reread = config_store.load_config(str(p))
    assert reread["provider"] == "TG" and reread["chat_id"] == "123"
    assert not [f for f in os.listdir(p.parent) if f.startswith(config_store.TMP_PREFIX)]


def test_save_config_atomico_non_distrugge_il_file_esistente_su_errore(tmp_path, monkeypatch):
    # Una scrittura interrotta (os.replace fallisce) NON deve troncare/cancellare il
    # config già presente: il vecchio file resta intatto (invariante 7).
    p = tmp_path / "config.json"
    config_store.save_config({"provider": "BUONO"}, str(p))     # stato valido iniziale

    real_replace = os.replace
    def _boom(src, dst):
        raise OSError("rename interrotto")
    monkeypatch.setattr(config_store.os, "replace", _boom)
    out, ok = config_store.save_config({"provider": "NUOVO"}, str(p))
    monkeypatch.setattr(config_store.os, "replace", real_replace)

    assert ok is False
    # Il file su disco è ancora quello valido precedente, non corrotto/troncato.
    assert config_store.load_config(str(p))["provider"] == "BUONO"
    assert not [f for f in os.listdir(p.parent) if f.startswith(config_store.TMP_PREFIX)]


# ── audit C5: migrazione/coercizione tipi noti su load ──

def test_load_config_coerce_intero_da_stringa(tmp_path):
    # Config editata a mano: "90" stringa dove serve un intero (clear_delay/timeout).
    # _migrate deve riportarlo a int, non propagare la stringa ai consumer (audit C5).
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"clear_delay": "30", "confirmation_timeout": "45",
                             "max_per_day": "10", "max_signal_age": "60"}))
    cfg = config_store.load_config(str(p))
    assert cfg["clear_delay"] == 30 and isinstance(cfg["clear_delay"], int)
    assert cfg["confirmation_timeout"] == 45 and isinstance(cfg["confirmation_timeout"], int)
    assert cfg["max_per_day"] == 10 and isinstance(cfg["max_per_day"], int)
    assert cfg["max_signal_age"] == 60 and isinstance(cfg["max_signal_age"], int)


def test_load_config_intero_illeggibile_torna_al_default(tmp_path):
    # Valore non interpretabile come intero → default sicuro, niente crash/typo runtime.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"clear_delay": "non-un-numero", "max_signal_age": True}))
    cfg = config_store.load_config(str(p))
    assert cfg["clear_delay"] == config_store.DEFAULTS["clear_delay"]
    # `True` (JSON true) NON deve diventare 1 secondo di età massima: torna al default.
    assert cfg["max_signal_age"] == config_store.DEFAULTS["max_signal_age"]


def test_load_config_dry_run_resta_simulazione_su_valore_sporco(tmp_path):
    # Sicurezza: dry_run (simulazione) di default True. Un valore sporco non interpretabile
    # come falsey deve restare True (simulazione), MAI cadere a "scommetti davvero".
    # La migrazione delega a safety_guard.is_dry_run (stessi insiemi falsey del consumer).
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"dry_run": "boh"}))
    assert config_store.load_config(str(p))["dry_run"] is True
    # Stringa VUOTA (config editata a mano): fail-closed → simulazione (finding Codex P1).
    # `as_bool("")` darebbe False (modalità reale!): la delega a is_dry_run lo impedisce.
    p.write_text(json.dumps({"dry_run": ""}))
    assert config_store.load_config(str(p))["dry_run"] is True
    # Mentre un esplicito falsey (scelta dell'utente) viene onorato.
    p.write_text(json.dumps({"dry_run": "false"}))
    assert config_store.load_config(str(p))["dry_run"] is False


def test_load_config_auto_start_listener_fail_closed_su_valore_sporco(tmp_path):
    # Sicurezza speculare a dry_run (finding Codex P1 / CodeRabbit Major):
    # auto_start_listener default False, semantica TRUTHY-only. Un valore sporco/vuoto
    # NON deve auto-avviare il listener. `as_bool("boh")` darebbe True (auto-start!):
    # la delega a autostart.is_enabled lo tiene a False.
    p = tmp_path / "config.json"
    for sporco in ("boh", "", "maybe"):
        p.write_text(json.dumps({"auto_start_listener": sporco}))
        assert config_store.load_config(str(p))["auto_start_listener"] is False
    # Un esplicito truthy (scelta dell'utente) viene onorato.
    for vero in ("true", "1", "si", "yes"):
        p.write_text(json.dumps({"auto_start_listener": vero}))
        assert config_store.load_config(str(p))["auto_start_listener"] is True


def test_load_config_float_non_intero_torna_al_default(tmp_path):
    # Finding Codex P2: un float NON intero su un campo intero di sicurezza non deve
    # troncare. `max_signal_age: 0.5` → 0 disattiverebbe il filtro anti-stale: deve
    # invece tornare al default. Un float INTERO (2.0) è accettato come 2.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"max_signal_age": 0.5}))
    cfg = config_store.load_config(str(p))
    assert cfg["max_signal_age"] == config_store.DEFAULTS["max_signal_age"]
    assert cfg["max_signal_age"] > 0                  # filtro anti-stale resta attivo
    p.write_text(json.dumps({"clear_delay": 2.0}))    # float intero → accettato
    assert config_store.load_config(str(p))["clear_delay"] == 2
    # inf/nan (json Python li rilegge): non finiti → default, mai 0/troncamento.
    p.write_text('{"max_signal_age": Infinity}')
    assert config_store.load_config(str(p))["max_signal_age"] == config_store.DEFAULTS["max_signal_age"]


def test_load_config_lista_e_dict_sbagliati_tornano_al_default(tmp_path):
    # source_chats/keywords devono essere liste e parser_by_chat un dict: un tipo
    # sbagliato (file editato male) viene riportato al default sicuro, non propagato.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"source_chats": "non-una-lista",
                             "confirmation_keywords": 5,
                             "parser_by_chat": ["non", "un", "dict"]}))
    cfg = config_store.load_config(str(p))
    assert cfg["source_chats"] == config_store.DEFAULTS["source_chats"]
    assert cfg["confirmation_keywords"] == config_store.DEFAULTS["confirmation_keywords"]
    assert cfg["parser_by_chat"] == config_store.DEFAULTS["parser_by_chat"]


def test_load_config_keyword_stringa_preservata_non_azzerata(tmp_path):
    # Finding Codex P2: una STRINGA singola è un formato supportato per le keyword
    # conferma/rifiuto (config a mano). NON va azzerata a [] (perderebbe i custom XTrader
    # words → segnale chiuso solo a timeout): va normalizzata a lista canonica.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"confirmation_keywords": "accepted",
                             "rejection_keywords": "declined"}))
    cfg = config_store.load_config(str(p))
    assert cfg["confirmation_keywords"] == ["accepted"]
    assert cfg["rejection_keywords"] == ["declined"]
    # Una lista già valida resta tale; un tipo davvero inatteso (numero) → [] (default modulo).
    p.write_text(json.dumps({"confirmation_keywords": ["ok", "fatto"],
                             "rejection_keywords": 5}))
    cfg = config_store.load_config(str(p))
    assert cfg["confirmation_keywords"] == ["ok", "fatto"]
    assert cfg["rejection_keywords"] == []


def test_load_config_lista_valida_preservata(tmp_path):
    # Una lista già del tipo giusto NON va toccata (no falsi reset).
    p = tmp_path / "config.json"
    chats = [{"name": "A", "chat_id": "-100", "enabled": True}]
    p.write_text(json.dumps({"source_chats": chats}))
    assert config_store.load_config(str(p))["source_chats"] == chats


def test_load_config_chiavi_sconosciute_non_toccate_da_migrate(tmp_path):
    # _migrate itera solo le chiavi note (DEFAULTS): una chiave futura/legacy con
    # qualunque tipo sopravvive intatta (forward-compat).
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"chiave_ignota": {"nested": [1, 2]}, "config_version": 99}))
    cfg = config_store.load_config(str(p))
    assert cfg["chiave_ignota"] == {"nested": [1, 2]}
    assert cfg["config_version"] == 99    # skew su disco preservato come intero


# ── audit C7: save_config ritorna una copia profonda (no aliasing nested) ──

def test_save_config_ritorna_deepcopy_senza_aliasing(tmp_path):
    # La config restituita non deve condividere i nested mutabili con quella passata:
    # mutare uno NON deve alterare l'altro (audit C7). Il chiamante fa self._config=saved.
    p = str(tmp_path / "config.json")
    cfg_in = {"provider": "TG", "source_chats": [{"name": "A"}], "parser_by_chat": {"-1": "px"}}
    saved, ok = config_store.save_config(cfg_in, p)
    assert ok is True
    # Muto la copia restituita: l'input originale resta invariato.
    saved["source_chats"].append({"name": "B"})
    saved["parser_by_chat"]["-2"] = "py"
    assert cfg_in["source_chats"] == [{"name": "A"}]
    assert cfg_in["parser_by_chat"] == {"-1": "px"}
    # E viceversa: muto l'input dopo il save, la copia salvata non cambia.
    cfg_in["source_chats"].append({"name": "C"})
    assert saved["source_chats"] == [{"name": "A"}, {"name": "B"}]


def test_migrate_legacy_logga_errore_ma_non_crasha(tmp_path, caplog):
    # Migrazione fallita (la dir di destinazione è in realtà un FILE → makedirs
    # solleva): ritorna False senza crashare, e ora logga il motivo.
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"provider": "VECCHIO"}))
    blocker = tmp_path / "afile"
    blocker.write_text("non sono una cartella")    # un file dove servirebbe una dir
    new = blocker / "config.json"                  # dirname(new) è un FILE → makedirs fallisce
    with caplog.at_level("WARNING", logger="xtrader_bridge.config_store"):
        migrated = config_store.migrate_legacy_config(str(new), str(legacy))
    assert migrated is False
    assert any("Migrazione config legacy fallita" in r.getMessage() for r in caplog.records)


def test_max_active_signals_default_e_floor(tmp_path):
    # #136 p5: tetto presente nei default (2) e forzato a >= 1 in migrazione.
    assert config_store.DEFAULTS["max_active_signals"] == 2
    assert config_store.load_config(str(tmp_path / "assente.json"))["max_active_signals"] == 2
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"max_active_signals": 5}))
    assert config_store.load_config(str(p))["max_active_signals"] == 5
    # 0 / negativo / malformato → torna al default (niente tetto disattivato per sbaglio).
    for bad in (0, -3, "abc"):
        p.write_text(json.dumps({"max_active_signals": bad}))
        assert config_store.load_config(str(p))["max_active_signals"] == 2, bad


# ── #184 low-csvpath-validate: diagnostica del csv_path a START ───────────────

def test_csv_path_problem(tmp_path):
    """#184 low-csvpath-validate: `csv_path_problem` segnala (con messaggio) una cartella mancante,
    un path vuoto o un path che è una cartella; ritorna "" se il file è plausibilmente scrivibile.
    Non crea nulla e non apre il file (l'I/O reale resta a `init_csv`)."""
    # path valido: cartella esistente + nome file → nessun problema
    ok = str(tmp_path / "segnali.csv")
    assert config_store.csv_path_problem(ok) == ""
    # path vuoto / solo spazi → problema
    assert config_store.csv_path_problem("") != ""
    assert config_store.csv_path_problem("   ") != ""
    assert config_store.csv_path_problem(None) != ""
    # cartella padre INESISTENTE (es. il default C:\XTrader\ assente) → problema
    missing = str(tmp_path / "non_esiste" / "segnali.csv")
    prob = config_store.csv_path_problem(missing)
    assert prob and "non esiste" in prob
    # il path è esso stesso una cartella → problema
    assert config_store.csv_path_problem(str(tmp_path)) != ""
    # non ha creato nulla (diagnostica pura)
    assert not os.path.exists(missing)
    assert not (tmp_path / "non_esiste").exists()


# ── #199 (M3 P2 follow-up): config corrotto NON deve cancellare il token keyring ──

def test_clear_post_corruzione_non_cancella_il_token_keyring(tmp_path, monkeypatch):
    # Scenario data-loss: config.json corrotto → load fa il .bak e torna bot_token="" (sentinel
    # perso) ma il keyring ha ancora il token valido. La GUI ripopola il campo con "" e salva
    # → ramo CLEAR. Il token NON deve essere cancellato: deriva dalla corruzione, non da un clear.
    store = {"t": "VALID:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    p.write_text("{ questo non è json valido ", encoding="utf-8")     # config corrotto

    loaded = config_store.load_config(str(p))
    assert loaded.get(config_store.POST_CORRUPTION_KEY) is True        # marker post-corruzione (RAM)
    assert (tmp_path / "config.json.bak").exists()                     # corrotto messo da parte

    loaded["bot_token"] = ""                                           # la GUI ha il campo vuoto
    saved, ok = config_store.save_config(loaded, str(p))
    assert ok is True
    assert store["t"] == "VALID:TOKEN"                                 # KEYRING PRESERVATO (no delete)
    assert saved["bot_token"] == "VALID:TOKEN"                         # runtime riusa il token reale
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "keyring"                   # sentinel → reidratazione
    assert config_store.POST_CORRUPTION_KEY not in on_disk             # marker MAI su disco
    assert config_store.POST_CORRUPTION_KEY not in saved              # marker consumato in memoria
    # load successivo: il token valido viene reidratato dal keyring
    assert config_store.load_config(str(p))["bot_token"] == "VALID:TOKEN"


def test_clear_deliberato_dopo_config_risanato_cancella_ancora(tmp_path, monkeypatch):
    # Dopo che un save post-corruzione ha risanato il config (marker consumato), un clear
    # DELIBERATO (bot_token="" senza marker) deve ancora cancellare il token dal keyring.
    store = {"t": "VALID:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    p.write_text("{ corrotto ", encoding="utf-8")

    loaded = config_store.load_config(str(p))
    loaded["bot_token"] = ""
    saved, _ = config_store.save_config(loaded, str(p))                # 1° save: preserva (post-corruzione)
    assert store["t"] == "VALID:TOKEN"
    assert config_store.POST_CORRUPTION_KEY not in saved              # marker consumato

    # 2° save: clear DELIBERATO su config ora integro → cancella davvero
    saved["bot_token"] = ""
    config_store.save_config(saved, str(p))
    assert "t" not in store                                            # token cancellato dal keyring
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "none"
    assert config_store.load_config(str(p))["bot_token"] == ""         # non risorge


def test_post_corruzione_con_token_reinserito_lo_salva_normalmente(tmp_path, monkeypatch):
    # Se dopo la corruzione l'utente RE-INSERISCE un token (campo non vuoto), il marker non
    # interferisce: il token nuovo va nel keyring come un set normale.
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    p.write_text("xxx non json", encoding="utf-8")
    loaded = config_store.load_config(str(p))
    assert loaded.get(config_store.POST_CORRUPTION_KEY) is True
    loaded["bot_token"] = "NEW:TOKEN"
    saved, ok = config_store.save_config(loaded, str(p))
    assert ok is True
    assert store["t"] == "NEW:TOKEN"                                   # token nuovo salvato
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token"] == ""                                  # non in chiaro
    assert on_disk["bot_token_storage"] == "keyring"


def test_post_corruzione_pre_read_fallita_non_declassa_a_plaintext(tmp_path, monkeypatch):
    """#140 (PR-08a, Codex P2 line 482): dopo una corruzione recuperata il sentinel è perso
    (stato di storage SCONOSCIUTO). Se l'utente re-inserisce un token e `load_token_status`
    fallisce (read_ok False) col keyring disponibile, NON si deve declassare a plaintext una
    credenziale forse keyring-backed: si tratta il marker post-corruzione come stato ignoto e si
    DIFFERISCE (ok=False, abort atomico, niente token in chiaro su disco).

    Fail-first: prima il ramo `not prior_read_ok` (sentinel vuoto, post-corruzione ignorato)
    cadeva nel fallback plaintext, scrivendo il token in chiaro e tornando ok=True."""
    saved_calls = {"n": 0}
    monkeypatch.setattr(config_store.token_store, "available", lambda: True)

    def _save(t):
        saved_calls["n"] += 1
        return True
    monkeypatch.setattr(config_store.token_store, "save_token", _save)
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: None)
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (None, False))  # read FALLITA
    monkeypatch.setattr(config_store.token_store, "delete_token", lambda: True)
    p = tmp_path / "config.json"
    p.write_text("xxx non json", encoding="utf-8")
    loaded = config_store.load_config(str(p))               # corrotto → marker, sentinel perso, p→.bak
    assert loaded.get(config_store.POST_CORRUPTION_KEY) is True
    assert not loaded.get("bot_token_storage")              # sentinel SCONOSCIUTO (vuoto)
    loaded["bot_token"] = "NEW:TOKEN"                        # l'utente re-inserisce il token
    saved, ok = config_store.save_config(loaded, str(p))
    assert ok is False                                      # stato ignoto + read fallita → differito
    assert saved_calls["n"] == 0                            # keyring NON sovrascritto (nessun downgrade)
    assert not p.exists()                                   # abort atomico: nessuna scrittura su disco
    assert saved["bot_token"] == "NEW:TOKEN"                # in memoria resta (runtime), ma non persistito


def test_post_corruzione_retry_keyring_giu_non_declassa_a_plaintext(tmp_path, monkeypatch):
    """#140 (PR-08a, Codex P2 line 638 / CodeRabbit Major): il path differito deve MIRRORARE il
    sentinel "keyring" in `in_memory`. Il chiamante fa `self._config = saved` anche su `ok=False`
    e `POST_CORRUPTION_KEY` è già consumato: senza il mirror, un SECONDO save col keyring ancora
    giù vedrebbe `prior_sentinel` vuoto e ripiegherebbe sul plaintext, scrivendo il token in
    chiaro. Col mirror la protezione "stato keyring/ignoto -> differisci" sopravvive ai retry.

    Fail-first: senza il mirror il 2° save tornava `ok=True` scrivendo il token in chiaro su disco."""
    _fake_keyring(monkeypatch, {}, available=False)        # keyring giù
    p = tmp_path / "config.json"
    p.write_text("xxx non json", encoding="utf-8")
    loaded = config_store.load_config(str(p))              # corrotto -> marker, sentinel perso, p->.bak
    assert loaded.get(config_store.POST_CORRUPTION_KEY) is True
    loaded["bot_token"] = "NEW:TOKEN"                       # utente re-inserisce il token
    saved1, ok1 = config_store.save_config(loaded, str(p))  # 1° save: differito (keyring giù)
    assert ok1 is False
    assert saved1.get("bot_token_storage") == "keyring"     # sentinel fail-safe MIRRORATO in memoria
    assert config_store.POST_CORRUPTION_KEY not in saved1   # marker consumato
    # 2° save col config restituito (come fa `self._config = saved`), keyring ANCORA giù:
    saved2, ok2 = config_store.save_config(saved1, str(p))
    assert ok2 is False                                     # ancora differito (nessun downgrade a plaintext)
    raw = p.read_text(encoding="utf-8") if p.exists() else ""
    assert "NEW:TOKEN" not in raw                           # token MAI in chiaro su disco
    assert "plaintext" not in raw


# ── PR-08b #140: clear vs miss-transiente — keyring illeggibile al load ────────────

def test_load_config_keyring_illeggibile_segna_load_incompleto(tmp_path, monkeypatch):
    """#140 (PR-08b): `load_config` marca `_token_load_incomplete` SOLO quando sentinel "keyring",
    token su disco vuoto e keyring ILLEGGIBILE (read_ok False). Con keyring leggibile e
    genuinamente vuoto NON marca (campo vuoto = stato reale); col token presente reidrata."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bot_token": "", "bot_token_storage": "keyring"}), encoding="utf-8")
    # keyring ILLEGGIBILE → marker
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (None, False))
    loaded = config_store.load_config(str(p))
    assert loaded.get(config_store.TOKEN_LOAD_INCOMPLETE_KEY) is True
    assert loaded["bot_token"] == ""
    # keyring leggibile e GENUINAMENTE vuoto → nessun marker
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (None, True))
    loaded2 = config_store.load_config(str(p))
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in loaded2
    # keyring leggibile col token → reidrata, nessun marker
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: ("LIVE:TOKEN", True))
    loaded3 = config_store.load_config(str(p))
    assert loaded3["bot_token"] == "LIVE:TOKEN"
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in loaded3


def test_clear_dopo_load_keyring_illeggibile_non_cancella_il_token(tmp_path, monkeypatch):
    """#140 (PR-08b): se il keyring era ILLEGGIBILE al load (sentinel "keyring", token non
    reidratato), `load_config` marca `_token_load_incomplete`. Un save successivo NON deve
    trattare il `bot_token` vuoto come un clear voluto: deve PRESERVARE il token (ancora nel
    keyring), non cancellarlo.

    Fail-first: prima `load_config` usava `load_token()` (None su lettura fallita, nessun marker)
    e il save trattava il campo vuoto come clear REALE → `delete_token` cancellava il token."""
    state = {"token": "LIVE:TOKEN", "readable": False}     # token c'è ma keyring illeggibile ORA
    deleted = {"n": 0}
    monkeypatch.setattr(config_store.token_store, "available", lambda: state["readable"])
    monkeypatch.setattr(config_store.token_store, "load_token_status",
                        lambda: ((state["token"], True) if state["readable"] else (None, False)))
    monkeypatch.setattr(config_store.token_store, "load_token",
                        lambda: state["token"] if state["readable"] else None)
    monkeypatch.setattr(config_store.token_store, "save_token",
                        lambda t: state.__setitem__("token", t) or True)

    def _del():
        deleted["n"] += 1
        state["token"] = None
        return True
    monkeypatch.setattr(config_store.token_store, "delete_token", _del)

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bot_token": "", "bot_token_storage": "keyring", "provider": "X"}),
                 encoding="utf-8")
    loaded = config_store.load_config(str(p))               # LOAD col keyring illeggibile → marker
    assert loaded.get(config_store.TOKEN_LOAD_INCOMPLETE_KEY) is True
    assert loaded["bot_token"] == ""
    state["readable"] = True                                # keyring TORNA leggibile
    saved, ok = config_store.save_config(loaded, str(p))    # save (campo token ancora vuoto)
    assert ok is True                                       # save riuscito (esito GUI-visibile coperto)
    assert deleted["n"] == 0                                # il token NON è stato cancellato
    assert state["token"] == "LIVE:TOKEN"                   # ancora nel keyring
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "keyring"        # niente "none": reidrata ancora
    assert saved["bot_token"] == "LIVE:TOKEN"               # reidratato in memoria (runtime)
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in saved   # marker consumato (load ora completo)
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in on_disk


def test_load_incompleto_persiste_se_keyring_ancora_giu(tmp_path, monkeypatch):
    """#140 (PR-08b): se al save il keyring è ANCORA illeggibile, il marker load-incompleto va
    RE-MANTENUTO in memoria, così la protezione "non cancellare" sopravvive al save successivo
    (stesso principio del mirror sentinel di 08a). Un 2° save col keyring tornato leggibile non
    deve cancellare il token."""
    state = {"token": "LIVE:TOKEN", "readable": False}
    deleted = {"n": 0}
    monkeypatch.setattr(config_store.token_store, "available", lambda: state["readable"])
    monkeypatch.setattr(config_store.token_store, "load_token_status",
                        lambda: ((state["token"], True) if state["readable"] else (None, False)))
    monkeypatch.setattr(config_store.token_store, "load_token",
                        lambda: state["token"] if state["readable"] else None)
    monkeypatch.setattr(config_store.token_store, "save_token", lambda t: True)

    def _del():
        deleted["n"] += 1
        state["token"] = None
        return True
    monkeypatch.setattr(config_store.token_store, "delete_token", _del)

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bot_token": "", "bot_token_storage": "keyring"}), encoding="utf-8")
    loaded = config_store.load_config(str(p))               # keyring giù → marker
    assert loaded.get(config_store.TOKEN_LOAD_INCOMPLETE_KEY) is True
    saved1, ok1 = config_store.save_config(loaded, str(p))  # keyring ANCORA giù
    assert ok1 is True                                      # save riuscito (clear differito, non un fallimento)
    assert deleted["n"] == 0
    assert saved1.get(config_store.TOKEN_LOAD_INCOMPLETE_KEY) is True   # marker RE-MANTENUTO
    state["readable"] = True                                # keyring torna leggibile
    saved2, ok2 = config_store.save_config(saved1, str(p))  # 2° save non deve cancellare
    assert ok2 is True
    assert deleted["n"] == 0
    assert state["token"] == "LIVE:TOKEN"
    assert saved2["bot_token"] == "LIVE:TOKEN"              # reidratato (runtime)
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in saved2   # marker consumato dalla reidratazione
    on_disk2 = json.loads(p.read_text(encoding="utf-8"))
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in on_disk2


def test_clear_reale_con_keyring_leggibile_cancella(tmp_path, monkeypatch):
    """#140 (PR-08b) contro-prova: un clear REALE (load completo, keyring leggibile, nessun marker)
    cancella ancora il token e mette sentinel "none" — il comportamento di clear non regredisce."""
    store = {"t": "OLD:TOKEN"}
    _fake_keyring(monkeypatch, store)
    p = tmp_path / "config.json"
    saved, ok = config_store.save_config({"bot_token": "", "bot_token_storage": "keyring"}, str(p))
    assert ok is True
    assert "t" not in store                                 # token cancellato (clear reale)
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "none"           # niente reidratazione futura


def test_load_incompleto_keyring_leggibile_vuoto_non_lascia_puntatore_stantio(tmp_path, monkeypatch):
    """#140 (PR-08b, CodeRabbit Major): col marker load-incompleto attivo, se al save il keyring è
    leggibile e GENUINAMENTE vuoto (load_token_status → (None, True)), NON c'è token da preservare:
    il sentinel deve diventare "none", non "keyring". Un puntatore "keyring" stantio resusciterebbe
    un eventuale orphan token futuro.

    Fail-first: prima il ramo scriveva sempre "keyring", lasciando un puntatore di reidratazione."""
    deleted = {"n": 0}
    monkeypatch.setattr(config_store.token_store, "available", lambda: True)
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: (None, True))  # leggibile, VUOTO
    monkeypatch.setattr(config_store.token_store, "load_token", lambda: None)
    monkeypatch.setattr(config_store.token_store, "save_token", lambda t: True)

    def _del():
        deleted["n"] += 1
        return True
    monkeypatch.setattr(config_store.token_store, "delete_token", _del)

    p = tmp_path / "config.json"
    cfg = {"bot_token": "", "bot_token_storage": "keyring",
           config_store.TOKEN_LOAD_INCOMPLETE_KEY: True}     # marker load-incompleto attivo
    saved, ok = config_store.save_config(cfg, str(p))
    assert ok is True
    assert deleted["n"] == 0                                 # niente da cancellare (keyring già vuoto)
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token_storage"] == "none"           # sentinel "none": nessun puntatore stantio
    assert saved["bot_token_storage"] == "none"             # runtime coerente col disco (no "keyring" stantio)
    assert on_disk["bot_token"] == ""
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in on_disk   # marker MAI su disco
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in saved     # consumato in memoria
    # load successivo: sentinel "none" → niente reidratazione anche se un orphan comparisse nel keyring
    monkeypatch.setattr(config_store.token_store, "load_token_status", lambda: ("ORPHAN:TOKEN", True))
    assert config_store.load_config(str(p))["bot_token"] == ""     # NON resuscita l'orphan


def test_save_parziale_non_consuma_il_marker_load_incompleto(tmp_path, monkeypatch):
    """#256 (CodeRabbit Major): un save PARZIALE (chiave `bot_token` ASSENTE) non deve consumare il
    marker `_token_load_incomplete` da `in_memory`: il ramo del token non gira, quindi la guardia
    deve sopravvivere per il clear successivo. Su disco/profilo il marker non finisce comunque mai.

    Fail-first: prima il marker veniva `pop`-ato incondizionatamente → un save parziale lo perdeva e
    un clear successivo sarebbe stato scambiato per un clear reale."""
    _fake_keyring(monkeypatch, {"t": "LIVE:TOKEN"})
    p = tmp_path / "config.json"
    # config esistente keyring-backed su disco (così il save parziale ha cosa preservare)
    p.write_text(json.dumps({"bot_token": "", "bot_token_storage": "keyring"}), encoding="utf-8")
    cfg = {"provider": "X", "chat_id": "1",                  # NIENTE chiave bot_token → save PARZIALE
           config_store.TOKEN_LOAD_INCOMPLETE_KEY: True}
    saved, ok = config_store.save_config(cfg, str(p))
    assert ok is True
    assert saved.get(config_store.TOKEN_LOAD_INCOMPLETE_KEY) is True   # marker PRESERVATO in memoria
    assert saved["bot_token_storage"] == "keyring"                    # puntatore keyring preservato (runtime)
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["bot_token"] == ""                                 # token migrato resta fuori dal disco
    assert on_disk["bot_token_storage"] == "keyring"                  # ...ma il puntatore keyring è preservato
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in on_disk       # ma MAI su disco


# ── Contratto a STATI ESPLICITI di save_config (#255 line-647) ──────────────────────────────
#
# `save_config` ora torna un `SaveResult` (retro-compatibile con `(config, ok)`) che porta anche
# `.status`, così la GUI dà il messaggio GIUSTO invece di un generico "FALLITO su disco" anche
# quando la causa è il keyring o un config corrotto.

def test_save_result_retrocompatibile_unpacking_indexing_ed_uguaglianza():
    """`SaveResult` si comporta come la tupla storica `(config, ok)`: unpacking, indexing,
    `len`, e uguaglianza con una tupla semplice (così i test/chiamanti esistenti restano validi)."""
    r = config_store.SaveResult({"k": 1}, True, config_store.SAVE_OK)
    saved, ok = r                                   # unpacking storico
    assert saved == {"k": 1} and ok is True
    assert r[0] == {"k": 1} and r[1] is True        # indexing
    assert len(r) == 2 and isinstance(r, tuple)
    assert r == ({"k": 1}, True)                    # uguaglianza con tupla semplice
    assert r.config == {"k": 1} and r.ok is True and r.status == config_store.SAVE_OK


def test_save_status_message_per_stato():
    """`save_status_message` mappa ogni stato NON-ok al suo messaggio; "" per OK/sconosciuto.
    Niente segreti nei messaggi."""
    assert config_store.save_status_message(config_store.SAVE_OK) == ""
    assert config_store.save_status_message("stato_inesistente") == ""
    assert "disco" in config_store.save_status_message(config_store.SAVE_DISK_ERROR).lower()
    assert "keyring" in config_store.save_status_message(config_store.SAVE_TOKEN_DEFERRED).lower()
    assert "corrotto" in config_store.save_status_message(config_store.SAVE_CONFIG_CORRUPT).lower()


def test_save_config_status_ok_su_successo(tmp_path, monkeypatch):
    """Save riuscito → `status == SAVE_OK`, `ok True`, messaggio vuoto."""
    _fake_keyring(monkeypatch, {})
    p = tmp_path / "config.json"
    result = config_store.save_config({"bot_token": "NEW:TOKEN", "provider": "X"}, str(p))
    assert result.ok is True
    assert result.status == config_store.SAVE_OK
    assert config_store.save_status_message(result.status) == ""


def test_save_config_status_disk_error_su_oserror(tmp_path, monkeypatch):
    """Scrittura atomica fallita (OSError) → `status == SAVE_DISK_ERROR` (non più accorpato).

    Fail-first: sul vecchio contratto `save_config` tornava una tupla senza `.status`."""
    _fake_keyring(monkeypatch, {"t": "OLD:TOKEN"})

    def _boom(*a, **k):
        raise OSError("disco pieno (simulato)")
    monkeypatch.setattr(config_store.atomic_io, "atomic_write_json", _boom)
    p = tmp_path / "config.json"
    result = config_store.save_config({"bot_token": "NEW:TOKEN", "provider": "X"}, str(p))
    assert result.ok is False
    assert result.status == config_store.SAVE_DISK_ERROR
    assert "disco" in config_store.save_status_message(result.status).lower()


def test_save_config_status_token_deferred_su_keyring_giu(tmp_path, monkeypatch):
    """Token non persistibile per keyring giù (stato precedente "keyring") → niente scritto e
    `status == SAVE_TOKEN_DEFERRED`: la GUI mostra il messaggio "keyring", non "disco".

    Fail-first: prima `ok=False` non distingueva il differimento dal fallimento disco."""
    _fake_keyring(monkeypatch, {"t": "OLD:KEYRING:TOKEN"}, available=False)   # keyring giù ORA
    p = tmp_path / "config.json"
    before = json.dumps({"bot_token": "", "bot_token_storage": "keyring", "provider": "OLD"}, indent=2)
    p.write_text(before, encoding="utf-8")
    result = config_store.save_config(
        {"bot_token": "NEW:TOKEN", "bot_token_storage": "keyring", "provider": "NEW"}, str(p))
    assert result.ok is False
    assert result.status == config_store.SAVE_TOKEN_DEFERRED
    assert p.read_text(encoding="utf-8") == before               # disco invariato (abort atomico)
    assert "keyring" in config_store.save_status_message(result.status).lower()


def test_save_config_status_config_corrupt_su_parziale_su_disco_corrotto(tmp_path, monkeypatch):
    """Save PARZIALE (senza bot_token/sentinel) su `config.json` corrotto → fail-closed con
    `status == SAVE_CONFIG_CORRUPT` (messaggio dedicato), non un generico errore disco.

    Fail-first: prima questo path tornava `ok=False` indistinguibile dagli altri."""
    store = {"t": "123:SECRET"}
    _fake_keyring(monkeypatch, store, available=True)
    p = tmp_path / "config.json"
    corrotto = "{ questo non e' json valido ,,, "
    p.write_text(corrotto, encoding="utf-8")
    result = config_store.save_config({"provider": "X"}, str(p))   # parziale: niente bot_token/sentinel
    assert result.ok is False
    assert result.status == config_store.SAVE_CONFIG_CORRUPT
    assert p.read_text(encoding="utf-8") == corrotto               # disco corrotto NON sovrascritto
    assert "corrotto" in config_store.save_status_message(result.status).lower()
