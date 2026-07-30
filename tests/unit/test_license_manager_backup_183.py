"""Test hard di **backup completo e ripristino** del License Manager (#183).

Il test centrale è `test_migrare_col_SOLO_seed_DE_REVOCA_tutti`: riproduce il guasto che questa
funzione esiste per impedire, e dimostra che il backup completo lo evita. Gli altri coprono
validazione fail-closed, protezione della keypair esistente, e l'invariante che il **token non entra
mai** nel backup.
"""

import json
import os

import pytest

from license_manager import backup, core, publish_store, registry
from xtrader_bridge.licensing import revocation

_NOW = 1_700_000_000


def _tool_configurato(d, *, revocati=(), emesse=()):
    """Una cartella-tool realistica: keypair vera + registro + revoche + impostazioni."""
    seed_hex, public_hex = core.generate_keypair()
    core.save_signing_key(core.signing_key_path(d), seed_hex, public_hex, _NOW)
    for serial in emesse:
        registry.append_record({"serial": serial, "name": "Tizio", "hardware_id": "HW1-X",
                                "issued_at": _NOW, "expires_at": _NOW + 86_400}, directory=d)
    for serial in revocati:
        registry.append_revocation({"serial": serial, "name": "Tizio", "hardware_id": "HW1-X"},
                                   directory=d)
    publish_store.save_publish_config({"enabled": True, "repo": "tizio/x"}, directory=d)
    return seed_hex, public_hex


def _lista_pubblicata(d, *, now=_NOW):
    """La lista firmata che il tool pubblicherebbe ADESSO, con lo stato presente in `d`.

    Riusa le stesse funzioni della GUI (`registry.revocation_entries` +
    `revocation.build_revocation_list`), così il test misura la catena vera e non una sua imitazione.
    """
    chiave = core.load_signing_key(core.signing_key_path(d))
    entries = registry.revocation_entries(registry.read_revocations(directory=d))
    firmata = revocation.build_revocation_list(bytes.fromhex(chiave["seed"]), entries, now=now)
    return revocation.verify_revocation_list(firmata, public_key_hex=chiave["public"])


# ── IL test: il guasto che questa funzione esiste per impedire ───────────────────────────────────
def test_migrare_col_SOLO_seed_DE_REVOCA_tutti(tmp_path):
    """Riproduce il guasto, e dimostra che il backup completo lo evita.

    Migrando col solo seed (cioè con `core.export_signing_key`, il backup che esisteva prima di
    questa fetta), sul nuovo PC `revoked.jsonl` è vuoto. La prima pubblicazione produce una lista
    **valida e firmata** che dice «nessuno è revocato», con `iss` più recente: l'anti-replay del
    bridge — che rifiuta solo le liste più VECCHIE — la accetta, e **tutti i revocati tornano
    attivi**. Nessun errore, nessun avviso.

    Il test asserisce sui **serial effettivamente presenti nella lista pubblicabile**, non sul
    contenuto dei file: è quello che i bridge vedrebbero davvero."""
    vecchio = str(tmp_path / "pc-vecchio")
    os.makedirs(vecchio)
    _tool_configurato(vecchio, revocati=["LIC-CATTIVO1", "LIC-CATTIVO2"])
    assert _lista_pubblicata(vecchio).serials == {"LIC-CATTIVO1", "LIC-CATTIVO2"}

    # --- migrazione col SOLO seed (il backup che esisteva prima): il guasto ---
    solo_seed = str(tmp_path / "pc-nuovo-solo-seed")
    os.makedirs(solo_seed)
    core.export_signing_key(core.signing_key_path(vecchio), core.signing_key_path(solo_seed))

    dopo_migrazione_parziale = _lista_pubblicata(solo_seed)
    assert dopo_migrazione_parziale.serials == set(), (
        "riproduzione del guasto: col solo seed la lista pubblicabile è VUOTA → pubblicandola si "
        "de-revocano tutti")

    # --- migrazione col backup COMPLETO: i revocati restano revocati ---
    completo = str(tmp_path / "pc-nuovo-completo")
    os.makedirs(completo)
    file_backup = str(tmp_path / "migrazione.json")
    backup.save_backup(file_backup, backup.build_backup(vecchio, now=_NOW))
    backup.restore_backup(backup.load_backup(file_backup), completo)

    assert _lista_pubblicata(completo).serials == {"LIC-CATTIVO1", "LIC-CATTIVO2"}, \
        "col backup completo la migrazione deve preservare le revoche"


def test_round_trip_completo_byte_a_byte(tmp_path):
    """Esporta → cartella vergine → ripristina: ogni file deve tornare **identico**. Se il registro
    o le revoche si alterassero per strada (riserializzazione, encoding), la migrazione sembrerebbe
    riuscita ma i dati sarebbero diversi."""
    origine = str(tmp_path / "origine")
    os.makedirs(origine)
    _tool_configurato(origine, revocati=["LIC-A"], emesse=["LIC-A", "LIC-B"])
    file_backup = str(tmp_path / "b.json")
    backup.save_backup(file_backup, backup.build_backup(origine, now=_NOW))

    destinazione = str(tmp_path / "destinazione")
    esito = backup.restore_backup(backup.load_backup(file_backup), destinazione)

    assert set(esito["scritti"]) == {backup.KEY_FILE, registry.REGISTRY_FILE,
                                     registry.REVOKED_FILE, publish_store.PUBLISH_CONFIG_FILE}
    for nome in esito["scritti"]:
        with open(os.path.join(origine, nome), encoding="utf-8") as a, \
             open(os.path.join(destinazione, nome), encoding="utf-8") as b:
            assert a.read() == b.read(), nome


def test_il_backup_NON_contiene_mai_il_token(tmp_path, monkeypatch):
    """Invariante, come `test_save_non_scrive_mai_il_token`: il token GitHub vive nel keyring, non in
    un file. Se finisse nel backup, un segreto di scrittura viaggerebbe su chiavette e cartelle
    insieme al resto."""
    class _Kr:
        store = {(publish_store.SERVICE, publish_store.ACCOUNT_TOKEN): "ghp_SUPERSEGRETO"}

        def get_password(self, s, a):
            return self.store.get((s, a))
    monkeypatch.setattr(publish_store, "_keyring", lambda: _Kr())
    assert publish_store.load_publish_token() == "ghp_SUPERSEGRETO"     # precondizione

    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d)
    file_backup = str(tmp_path / "b.json")
    backup.save_backup(file_backup, backup.build_backup(d, now=_NOW))

    testo = open(file_backup, encoding="utf-8").read()
    assert "ghp_SUPERSEGRETO" not in testo and "token" not in testo


# ── validazione fail-closed: un backup rotto non deve toccare nulla ──────────────────────────────
@pytest.mark.parametrize("contenuto,atteso", [
    ("{non-json", "JSON"),
    ('{"v": 99, "files": {"signing_key.json": "x"}}', "versione"),
    ('{"v": 1, "files": {}}', "senza contenuti"),
    ('{"v": 1, "files": {"passwd": "x"}}', "non riconosciuto"),
    ('{"v": 1, "files": {"signing_key.json": 123}}', "non testuale"),
    ('[1, 2, 3]', "struttura"),
])
def test_backup_malformato_rifiutato(tmp_path, contenuto, atteso):
    p = str(tmp_path / "b.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(contenuto)
    with pytest.raises(backup.BackupError) as e:
        backup.load_backup(p)
    assert atteso in str(e.value)


def test_backup_rotto_NON_scrive_nulla(tmp_path):
    """La validazione sta tutta **prima** della scrittura: una cartella vergine deve restare vergine."""
    destinazione = str(tmp_path / "vergine")
    os.makedirs(destinazione)
    p = str(tmp_path / "b.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"v": 1, "files": {"passwd": "x"}}')

    with pytest.raises(backup.BackupError):
        backup.restore_backup(backup.load_backup(p), destinazione)

    assert os.listdir(destinazione) == [], "nessun file deve essere stato creato"


def test_seed_e_pubblica_incoerenti_rifiutati(tmp_path):
    """Un backup manomesso in cui la pubblica non deriva dal seed è rifiutato: il campo `public` è
    dichiarativo, la verità è il seed."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d)
    contenuto = backup.build_backup(d, now=_NOW)
    chiave = json.loads(contenuto["files"][backup.KEY_FILE])
    chiave["public"] = "00" * 32                       # pubblica che NON deriva dal seed
    contenuto["files"][backup.KEY_FILE] = json.dumps(chiave)

    with pytest.raises(backup.BackupError) as e:
        backup.restore_backup(contenuto, str(tmp_path / "dest"))
    assert "coerenti" in str(e.value)


# ── protezione della keypair esistente ──────────────────────────────────────────────────────────
def test_ripristino_su_keypair_DIVERSA_e_rifiutato(tmp_path):
    """Il danno irreversibile: sovrascrivere una keypair diversa significa non poter più rinnovare le
    licenze emesse con quella. Va rifiutato senza conferma esplicita, e lo stato deve restare
    invariato."""
    origine = str(tmp_path / "origine")
    altra = str(tmp_path / "altra")
    os.makedirs(origine), os.makedirs(altra)
    _tool_configurato(origine)
    _, pubblica_altra = _tool_configurato(altra)        # keypair DIVERSA già presente
    contenuto = backup.build_backup(origine, now=_NOW)

    # Il TIPO è parte del contratto, non un dettaglio: la GUI distingue «non si può fare» da «si può,
    # con una conferma consapevole» proprio sulla sottoclasse. Con un `BackupError` generico il
    # ripristino non offrirebbe più la via d'uscita a chi ha generato la chiave per sbaglio.
    with pytest.raises(backup.BackupKeyMismatchError) as e:
        backup.restore_backup(contenuto, altra)
    assert "DIVERSA" in str(e.value) and "rinnovare" in str(e.value)
    assert core.load_signing_key(core.signing_key_path(altra))["public"] == pubblica_altra, \
        "la keypair esistente non deve essere stata toccata"

    # con conferma esplicita passa
    backup.restore_backup(contenuto, altra, overwrite_key=True)
    assert core.load_signing_key(core.signing_key_path(altra))["public"] != pubblica_altra


def test_ripristino_sulla_STESSA_keypair_non_chiede_conferma(tmp_path):
    """Se la chiave è la stessa non c'è nulla da decidere: è il caso normale di un ripristino sullo
    stesso PC (recupero del registro), e chiedere conferma sarebbe rumore."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d, revocati=["LIC-X"])
    contenuto = backup.build_backup(d, now=_NOW)
    os.remove(os.path.join(d, registry.REVOKED_FILE))          # simula perdita del solo store revoche

    backup.restore_backup(contenuto, d)                        # nessun overwrite_key richiesto

    assert registry.read_revocations(directory=d), "le revoche devono essere tornate"


@pytest.mark.skipif(os.name == "nt", reason="permessi POSIX; su Windows il modello è ACL (no-op)")
def test_il_file_di_backup_e_leggibile_solo_dall_utente(tmp_path):
    """Rilievo GPT-5.5 sulla #184: il docstring promette `0o600`, e la promessa va **misurata** —
    contiene il seed, un backup leggibile da altri account su un PC condiviso è una perdita di
    chiave. Su Windows il modello è ACL e `chmod` è un no-op dichiarato: lì vale lo smoke manuale.

    Onestà su cosa misura: verificato con mutazione, togliere il solo `_restrict_perms` **non** lo fa
    diventare rosso — la garanzia vera viene da `atomic_write_text`, che scrive via `mkstemp` (già
    `0o600`, senza finestra a umask largo); `_restrict_perms` è la cintura oltre alle bretelle. Il
    test ha comunque denti: sostituendo la scrittura atomica con un `open()` normale il file esce
    `0o644` con umask 022 e il test fallisce."""
    import stat as _stat
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d)
    p = str(tmp_path / "b.json")

    backup.save_backup(p, backup.build_backup(d, now=_NOW))

    modo = _stat.S_IMODE(os.stat(p).st_mode)
    assert modo & (_stat.S_IRWXG | _stat.S_IRWXO) == 0, f"permessi troppo larghi: {modo:o}"


def test_ripristino_NON_cancella_lo_stato_assente_dal_backup(tmp_path):
    """Rilievo GPT-5.5 sulla #184: su una destinazione **già usata**, i file che il backup non
    contiene restano quelli di prima — «stato misto».

    È il comportamento **voluto**, e va nella direzione conservativa: l'unico caso possibile è che la
    destinazione abbia **più** revoche del backup (se il backup ce l'ha, sovrascrive). Cancellare i
    file assenti dal backup produrrebbe invece esattamente il guasto che questa PR esiste per
    impedire: ripristinare un backup fatto **prima** delle revoche azzererebbe `revoked.jsonl`, e la
    prima pubblicazione ri-attiverebbe tutti i revocati. Meglio uno stato che revoca **di più** che
    uno che revoca **di meno**.

    Il test lo fissa: se un domani qualcuno aggiungesse la cancellazione, diventa rosso."""
    destinazione = str(tmp_path / "usata")
    os.makedirs(destinazione)
    seed_hex, public_hex = _tool_configurato(destinazione, revocati=["LIC-REVOCATO-QUI"])

    # Backup della STESSA keypair ma senza revoche (fatto prima che quella revoca esistesse).
    origine = str(tmp_path / "origine")
    os.makedirs(origine)
    core.save_signing_key(core.signing_key_path(origine), seed_hex, public_hex, _NOW)
    contenuto = backup.build_backup(origine, now=_NOW)
    assert registry.REVOKED_FILE not in contenuto["files"], "precondizione: il backup non ha revoche"

    esito = backup.restore_backup(contenuto, destinazione)

    assert registry.REVOKED_FILE not in esito["scritti"]
    assert _lista_pubblicata(destinazione).serials == {"LIC-REVOCATO-QUI"}, (
        "la revoca già presente sulla destinazione deve sopravvivere al ripristino: cancellarla "
        "ri-attiverebbe un revocato alla prima pubblicazione")


def test_un_backup_validato_scrive_sempre_almeno_un_file(tmp_path):
    """Rilievo GPT-5.5 (secondo giro): il messaggio della GUI concatena `", ".join(esito["scritti"])`
    e con una lista vuota leggerebbe «Ripristinati: .».

    Misurato: è **irraggiungibile** oggi, perché `load_backup` rifiuta un backup con `files` vuoto e
    accetta solo nomi dell'allowlist — quindi `scritti` non può essere vuoto. Il test **fissa quel
    legame**: se un domani qualcuno allentasse la validazione, il messaggio degenere diventerebbe
    raggiungibile e questo test se ne accorgerebbe prima dell'utente."""
    p = str(tmp_path / "vuoto.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"v": backup.BACKUP_FORMAT_VERSION, "created": _NOW, "public": None, "files": {}}, f)

    with pytest.raises(backup.BackupError) as e:
        backup.load_backup(p)
    assert "senza contenuti" in str(e.value)

    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d)
    assert backup.restore_backup(backup.build_backup(d, now=_NOW), str(tmp_path / "dest"))["scritti"], \
        "un backup valido ripristina sempre almeno il file-chiave"


def test_backup_senza_keypair_e_un_errore(tmp_path):
    """Un backup «completo» senza seed non consente di ripartire: meglio fallire che dare una falsa
    sicurezza."""
    with pytest.raises(backup.BackupError) as e:
        backup.build_backup(str(tmp_path), now=_NOW)
    assert "keypair" in str(e.value)


# ── backup automatico: aggancio e perimetro ─────────────────────────────────────────────────────
def test_auto_backup_NON_contiene_il_seed(tmp_path):
    """Il perimetro che conta: l'automatismo salva ciò che **cambia**, mai il seed. Ogni copia del
    seed è un posto in più da cui può uscire, e il seed va salvato una volta, consapevolmente."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    seed_hex, _pub = _tool_configurato(d, revocati=["LIC-X"])

    assert backup.auto_backup(d, now=_NOW) is True

    testo = open(backup.backup_path(d), encoding="utf-8").read()
    assert seed_hex not in testo
    assert backup.KEY_FILE not in json.loads(testo)["files"]
    assert registry.REVOKED_FILE in json.loads(testo)["files"]


def test_auto_backup_e_best_effort(tmp_path):
    """Non deve mai far fallire l'operazione che protegge: emettere una licenza non può rompersi
    perché il backup non si scrive. Percorso occupato da un FILE → nessuna eccezione."""
    ostacolo = tmp_path / "occupato"
    ostacolo.write_text("non sono una cartella", encoding="utf-8")
    assert backup.auto_backup(str(ostacolo), now=_NOW) is False


def test_auto_backup_su_cartella_vuota_non_scrive(tmp_path):
    """Niente da salvare → `False`, senza creare un file vuoto che sembrerebbe un backup valido."""
    d = str(tmp_path / "vuota")
    os.makedirs(d)
    assert backup.auto_backup(d, now=_NOW) is False
    assert not os.path.exists(backup.backup_path(d))


def test_save_backup_non_sovrascrive_senza_conferma(tmp_path):
    """Stessa cautela di `export_signing_key`: un backup esistente potrebbe essere di un'ALTRA
    keypair, e perderlo significherebbe non poter più rinnovare quelle licenze."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d)
    p = str(tmp_path / "b.json")
    contenuto = backup.build_backup(d, now=_NOW)
    backup.save_backup(p, contenuto)

    with pytest.raises(backup.BackupExistsError) as e:     # sottoclasse: vedi nota sul tipo sopra
        backup.save_backup(p, contenuto)
    assert "esiste già" in str(e.value)
    assert isinstance(e.value, backup.BackupError), "resta gestibile da chi cattura la base"

    backup.save_backup(p, contenuto, overwrite=True)          # con conferma passa
