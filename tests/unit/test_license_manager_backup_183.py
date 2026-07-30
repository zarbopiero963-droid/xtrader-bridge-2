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


@pytest.mark.parametrize("nome, contenuto, atteso", [
    (registry.REVOKED_FILE, '{"serial": "LIC-A"}\nnon-json\n', "riga 2 illeggibile"),
    (registry.REVOKED_FILE, '{"serial": "LIC-A"}\n["non", "un", "record"]\n', "riga 2 non è un record"),
    (registry.REGISTRY_FILE, '{"serial": "LIC-A"}\n{"serial": "tronc\n', "riga 2 illeggibile"),
    (publish_store.PUBLISH_CONFIG_FILE, "{non-json", "non è un JSON valido"),
    (publish_store.PUBLISH_STATE_FILE, "[1, 2, 3]", "struttura inattesa"),
])
def test_contenuto_di_stato_corrotto_nel_backup_e_rifiutato(tmp_path, nome, contenuto, atteso):
    """Rilievo CodeRabbit #184 (Major): `load_backup` accettava **qualunque** stringa per i file di
    stato.

    Perché è grave, e non un dettaglio di robustezza: gli store leggono in modo **fail-safe** — una
    riga JSONL illeggibile viene saltata in silenzio. Un `revoked.jsonl` corrotto dentro il backup
    sarebbe quindi passato, avrebbe sostituito uno store valido, e alla prima pubblicazione avrebbe
    prodotto una lista firmata **senza quelle revoche**: lo stesso guasto della migrazione col solo
    seed, ma **senza nemmeno un errore** a segnalarlo. Ora il ripristino si rifiuta di partire."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d)
    valido = backup.build_backup(d, now=_NOW)
    valido["files"][nome] = contenuto
    p = str(tmp_path / "manomesso.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(valido, f)

    with pytest.raises(backup.BackupError) as e:
        backup.load_backup(p)
    assert atteso in str(e.value)


def test_stato_corrotto_NON_arriva_a_scrivere(tmp_path):
    """La controprova che conta: il rifiuto deve avvenire **prima** di toccare il disco, altrimenti
    lo store buono della destinazione sarebbe già stato sostituito."""
    origine = str(tmp_path / "origine")
    os.makedirs(origine)
    seed_hex, public_hex = _tool_configurato(origine, revocati=["LIC-BUONA"])
    manomesso = backup.build_backup(origine, now=_NOW)
    manomesso["files"][registry.REVOKED_FILE] = "spazzatura non-json\n"
    p = str(tmp_path / "manomesso.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(manomesso, f)

    destinazione = str(tmp_path / "dest")
    os.makedirs(destinazione)
    core.save_signing_key(core.signing_key_path(destinazione), seed_hex, public_hex, _NOW)
    registry.append_revocation({"serial": "LIC-SUL-POSTO", "name": "T", "hardware_id": "HW1-X"},
                               directory=destinazione)

    with pytest.raises(backup.BackupError):
        backup.load_backup(p)

    assert _lista_pubblicata(destinazione).serials == {"LIC-SUL-POSTO"}, \
        "lo store della destinazione non deve essere stato toccato"


def test_righe_vuote_nei_jsonl_restano_tollerate(tmp_path):
    """Controprova indispensabile: senza, la validazione nuova passerebbe anche se rifiutasse
    **tutto**, e un backup legittimo (gli store append-only lasciano righe vuote) diventerebbe
    irripristinabile."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d, revocati=["LIC-A"])
    contenuto = backup.build_backup(d, now=_NOW)
    contenuto["files"][registry.REVOKED_FILE] += "\n\n"
    p = str(tmp_path / "b.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(contenuto, f)

    assert backup.load_backup(p)["files"][registry.REVOKED_FILE].endswith("\n\n")


def test_no_overwrite_e_atomico_non_un_controllo_separato(tmp_path):
    """Rilievo CodeRabbit #184 (Major): `os.path.exists()` seguito da scrittura è una finestra TOCTOU
    — un altro processo può creare il file **dopo** il controllo e vederselo sostituire dal rename.

    Il test lo misura senza corse: monkeypatch di `os.path.exists` a «non esiste mai», così un
    controllo separato passerebbe e sovrascriverebbe. Con la creazione esclusiva (`O_EXCL`) il file
    preesistente sopravvive comunque."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d)
    p = str(tmp_path / "occupato.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("BACKUP-DI-UN-ALTRA-CHIAVE")

    contenuto = backup.build_backup(d, now=_NOW)
    vero_exists = os.path.exists
    try:
        os.path.exists = lambda percorso: False if percorso == p else vero_exists(percorso)
        with pytest.raises(backup.BackupExistsError):
            backup.save_backup(p, contenuto)
    finally:
        os.path.exists = vero_exists

    with open(p, encoding="utf-8") as f:
        assert f.read() == "BACKUP-DI-UN-ALTRA-CHIAVE", \
            "il no-overwrite non deve dipendere da un controllo separato"


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


def test_un_backup_VECCHIO_non_fa_sparire_le_revoche_piu_recenti(tmp_path):
    """Bloccante Fugu Ultra #184 — e una **mia affermazione sbagliata**: avevo scritto, qui e in un
    thread di review, «la destinazione può avere più revoche del backup, mai meno».

    Misurato prima della patch, era falso: `revoked.jsonl` è **presente** nel backup, quindi veniva
    sovrascritto. Destinazione R1+R2, backup (più vecchio) R1 → dopo il ripristino restava **solo
    R1**, e alla prima pubblicazione R2 sarebbe tornato attivo. Lo stesso guasto della migrazione col
    solo seed, raggiunto da un'altra strada.

    Ora i due store append-only si **uniscono**: è la semantica giusta per registri monotòni, dove
    una revoca non si annulla e una licenza emessa non si dimentica."""
    destinazione = str(tmp_path / "usata")
    origine = str(tmp_path / "origine")
    os.makedirs(destinazione), os.makedirs(origine)
    seed_hex, public_hex = _tool_configurato(origine, revocati=["R1", "R3"])
    backup_vecchio = backup.build_backup(origine, now=_NOW)

    core.save_signing_key(core.signing_key_path(destinazione), seed_hex, public_hex, _NOW)
    for serial in ("R1", "R2"):     # R2 revocato DOPO il backup, R1 in comune
        registry.append_revocation({"serial": serial, "name": "T", "hardware_id": "HW1-X"},
                                   directory=destinazione)

    backup.restore_backup(backup_vecchio, destinazione)

    serials = _lista_pubblicata(destinazione).serials
    assert "R2" in serials, ("una revoca fatta DOPO il backup non deve sparire: alla prima "
                             "pubblicazione quel cliente tornerebbe attivo")
    assert serials == {"R1", "R2", "R3"}, "unione: destinazione + backup, senza perdite"
    presenti = [r.get("serial") for r in registry.read_revocations(directory=destinazione)]
    assert presenti.count("R1") == 1, "le voci in comune non vanno duplicate"


def test_un_ripristino_INTERROTTO_lascia_il_marcatore_e_blocca_la_firma(tmp_path, monkeypatch):
    """Bloccante Fugu Ultra #184, riprodotto: il ripristino non è una transazione unica, e un guasto
    di I/O **dopo il seed e prima delle revoche** lasciava una cartella con chiave valida e store
    revoche vuoto.

    Misurato prima della patch: da quello stato il tool firmava una lista che dice «nessuno è
    revocato» — valida, firmata, più recente della precedente, quindi accettata da tutti i bridge.
    Il guasto della #183 per una strada nuova, e nessun errore a segnalarlo. Ora il marcatore resta
    su disco e `restore_in_progress` è `True`."""
    origine = str(tmp_path / "origine")
    os.makedirs(origine)
    _tool_configurato(origine, revocati=["R1", "R2"])
    contenuto = backup.build_backup(origine, now=_NOW)
    destinazione = str(tmp_path / "dest")

    vero = backup.atomic_io.atomic_write_text

    def rompi_sui_jsonl(percorso, testo, **kw):
        if percorso.endswith(".jsonl"):
            raise OSError(28, "No space left on device")
        return vero(percorso, testo, **kw)
    monkeypatch.setattr(backup.atomic_io, "atomic_write_text", rompi_sui_jsonl)

    with pytest.raises(OSError):
        backup.restore_backup(contenuto, destinazione)

    assert core.load_signing_key(core.signing_key_path(destinazione)) is not None, \
        "precondizione: il seed è entrato, quindi la cartella sembra utilizzabile"
    assert not registry.read_revocations(directory=destinazione), \
        "precondizione: le revoche NON sono entrate — è lo stato pericoloso"
    assert backup.restore_in_progress(destinazione) is True, (
        "il marcatore deve sopravvivere al guasto: è l'unica cosa che distingue questo stato da uno "
        "legittimo con zero revoche")


def test_se_non_si_riesce_a_leggere_il_marcatore_si_assume_il_PEGGIO(tmp_path):
    """Fail-closed sul dubbio: sbagliare in questo verso costa una pubblicazione rimandata,
    sbagliare nell'altro costa una lista che ri-attiva i revocati.

    ⚠️ **La prima versione di questo test non provava niente** (bloccante GPT-5.5 #184). Faceva
    monkeypatch di `os.path.exists` perché sollevasse — ma `os.path.exists` **inghiotte** gli
    `OSError` e ritorna `False`, quindi quello scenario non esiste: il test forzava un'eccezione
    impossibile, passava, e intanto sul codice reale il gate si **apriva** invece di chiudersi.

    Qui l'errore è **vero e non simulato**: un percorso oltre `PATH_MAX` fa fallire `os.stat` con
    `ENAMETOOLONG`. È lo stesso identico errore che `os.path.exists` nascondeva."""
    percorso_impossibile = str(tmp_path / ("x" * 5000))

    assert backup.restore_in_progress(percorso_impossibile) is True, (
        "un errore di I/O nel leggere il marcatore deve valere «ripristino in corso», non «finito»")


def test_marcatore_assente_significa_davvero_nessun_ripristino(tmp_path):
    """Controprova del fail-closed: senza, la funzione potrebbe rispondere **sempre** `True` e
    bloccherebbe la pubblicazione per sempre, su ogni installazione."""
    assert backup.restore_in_progress(str(tmp_path)) is False
    assert backup.restore_in_progress(str(tmp_path / "cartella_inesistente")) is False


def test_ripristino_COMPLETO_toglie_il_marcatore(tmp_path):
    """Controprova indispensabile: senza, il test qui sopra passerebbe anche con un marcatore che non
    viene rimosso **mai** — e la pubblicazione resterebbe bloccata per sempre."""
    origine = str(tmp_path / "origine")
    os.makedirs(origine)
    _tool_configurato(origine, revocati=["R1"])
    destinazione = str(tmp_path / "dest")

    backup.restore_backup(backup.build_backup(origine, now=_NOW), destinazione)

    assert backup.restore_in_progress(destinazione) is False
    assert not os.path.exists(backup.restore_marker_path(destinazione))


def test_una_revoca_di_un_ALTRO_processo_durante_la_fusione_non_si_perde(tmp_path, monkeypatch):
    """Bloccante Fugu Ultra #184: il lock degli append è **intra-processo**, quindi due License
    Manager aperti insieme possono ancora incrociarsi — e una revoca persa qui è un revocato
    ri-attivato.

    L'append è fatto **a mano sul file**, non con `registry.append_revocation`: quest'ultimo prende
    `_WRITE_LOCK`, che il ripristino sta già tenendo, e il test andrebbe in **deadlock** invece di
    misurare qualcosa (verificato: la prima stesura si è piantata fino al timeout). Un altro processo
    non condivide quel lock — scrivere diretti è la simulazione fedele, non una scorciatoia.

    Il ripristino se ne accorge e si ferma: non elimina la finestra, ma trasforma una perdita
    silenziosa in un errore ripetibile che dice cosa fare."""
    origine = str(tmp_path / "origine")
    destinazione = str(tmp_path / "dest")
    os.makedirs(origine), os.makedirs(destinazione)
    seed_hex, public_hex = _tool_configurato(origine, revocati=["R1"])
    contenuto = backup.build_backup(origine, now=_NOW)
    core.save_signing_key(core.signing_key_path(destinazione), seed_hex, public_hex, _NOW)

    vero_leggi = backup._leggi
    chiamate = {"n": 0}

    def leggi_e_intromettiti(percorso):
        risultato = vero_leggi(percorso)
        if percorso.endswith(registry.REVOKED_FILE):
            chiamate["n"] += 1
            if chiamate["n"] == 1:      # dopo la PRIMA lettura, l'«altra istanza» revoca
                with open(percorso, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"serial": "R-CONCORRENTE", "name": "T",
                                        "hardware_id": "HW1-X"}) + "\n")
        return risultato
    monkeypatch.setattr(backup, "_leggi", leggi_e_intromettiti)

    with pytest.raises(backup.BackupError) as e:
        backup.restore_backup(contenuto, destinazione)
    assert "un'altra istanza" in str(e.value).lower() or "altra istanza" in str(e.value)

    assert any(r.get("serial") == "R-CONCORRENTE"
               for r in registry.read_revocations(directory=destinazione)), \
        "la revoca concorrente deve essere ancora lì: mai persa in silenzio"


def test_la_fusione_avviene_sotto_il_lock_degli_append(tmp_path, monkeypatch):
    """Rilievo GPT-5.5 #184: la fusione è un read-modify-write, quindi una revoca registrata **fra**
    la lettura e la riscrittura andrebbe persa — la de-revoca silenziosa, di nuovo.

    Il test guarda l'invariante direttamente: al momento della scrittura il lock che serializza gli
    append **dev'essere già preso**. Un test a thread veri qui misurerebbe soprattutto la fortuna
    dello scheduler; questo invece è deterministico e fallisce se qualcuno toglie il lock."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d, revocati=["R1"])
    contenuto = backup.build_backup(d, now=_NOW)

    visto = {}
    vero = backup.atomic_io.atomic_write_text

    def sorvegliato(percorso, testo, **kw):
        if percorso.endswith(".jsonl"):
            visto[os.path.basename(percorso)] = registry.WRITE_LOCK.locked()
        return vero(percorso, testo, **kw)
    monkeypatch.setattr(backup.atomic_io, "atomic_write_text", sorvegliato)

    backup.restore_backup(contenuto, str(tmp_path / "dest"))

    assert visto, "precondizione: almeno uno store append-only dev'essere stato scritto"
    assert all(visto.values()), (
        f"la fusione deve tenere il lock degli append mentre riscrive: {visto}")


# Scrittori legittimi degli store append-only, per **percorso relativo** e non per basename: con
# `rglob` un confronto per nome escluderebbe anche un `sotto/backup.py` — falso negativo proprio nel
# caso che `rglob` serve a coprire (rilievo GPT-5.5 #184 su una mia patch precedente).
_SCRITTORI_LEGITTIMI = {"registry.py", "backup.py"}
_TOKEN_STORE = (".jsonl", "REGISTRY_FILE", "REVOKED_FILE", "registry_path", "revoked_registry_path")
_TOKEN_SCRITTURA = ("open(", "atomic_write_text", "atomic_write_json")


def _righe_che_scrivono_gli_store(radice) -> list:
    """Righe che scrivono su uno store append-only fuori dagli scrittori legittimi, come
    ``["sotto/x.py:12", ...]``.

    Estratta dal test perché la **guardia stessa vada testata**: una guardia che non intercetta è
    peggio di nessuna guardia, perché rassicura. Il criterio è per **riga** (non per file) e per
    **percorso relativo** (non per basename)."""
    trovate = []
    for modulo in sorted(radice.rglob("*.py")):
        relativo = modulo.relative_to(radice).as_posix()
        if relativo in _SCRITTORI_LEGITTIMI or "__pycache__" in modulo.parts:
            continue
        for numero, riga in enumerate(modulo.read_text(encoding="utf-8").splitlines(), start=1):
            if any(s in riga for s in _TOKEN_SCRITTURA) and any(t in riga for t in _TOKEN_STORE):
                trovate.append(f"{relativo}:{numero}")
    return trovate


def test_NESSUN_altro_modulo_scrive_gli_store_append_only():
    """Rilievo GPT-5.5 #184: «se qualche `.jsonl` viene scritto da un altro modulo con un lock
    diverso, la protezione è parziale».

    Verificato: gli unici scrittori sono `registry` (i due append, sotto `_WRITE_LOCK`) e `backup`
    (la fusione, sotto lo **stesso** lock via `WRITE_LOCK`). La protezione è quindi **completa**
    dentro il processo, non parziale. Ma è un'invariante che vive nella disciplina di chi scrive
    codice, non nel codice: un modulo nuovo che appendesse per conto suo riaprirebbe il buco in
    silenzio, e nessun altro test se ne accorgerebbe.

    Guardia sul **sorgente**, con i suoi limiti dichiarati: intercetta la scrittura scritta in chiaro
    nel modulo, non una raggiunta per vie indirette. È un allarme, non una dimostrazione.

    Il criterio è **per riga**, non per file: la prima versione guardava il file intero e segnalava
    `gui.py`, che nomina i due percorsi solo dentro due messaggi di log e la cui unica `open(...,"w")`
    scrive la **lista revoche esportata**, un altro file. Un allowlist di comodo avrebbe messo `gui.py`
    fuori sorveglianza per sempre; guardare la riga lo tiene dentro."""
    import pathlib
    colpevoli = _righe_che_scrivono_gli_store(pathlib.Path(registry.__file__).parent)

    assert not colpevoli, (
        f"queste righe scrivono su uno store append-only fuori da registry/backup: {colpevoli}. "
        "Devono farlo sotto `registry.WRITE_LOCK`, altrimenti una revoca può sparire durante un "
        "ripristino.")


@pytest.mark.parametrize("relativo, atteso", [
    ("nuovo.py", True),                 # modulo nuovo, livello piatto
    ("sotto/nuovo.py", True),           # dentro un sottopacchetto: `glob` lo mancava
    ("sotto/backup.py", True),          # STESSO basename di uno scrittore legittimo, ma altro path
    ("backup.py", False),               # lo scrittore legittimo vero: non va segnalato
])
def test_la_guardia_stessa_intercetta_i_casi_che_promette(tmp_path, relativo, atteso):
    """Rilievo GPT-5.5 #184 sulla patch precedente: dopo il passaggio a `rglob`, l'allowlist per
    **basename** avrebbe escluso `sotto/backup.py` — un falso negativo proprio nello scenario che
    `rglob` era stato aggiunto a coprire.

    Qui la guardia viene esercitata su un albero **sintetico**, così i suoi casi limite sono coperti
    in modo permanente invece che da una verifica manuale una tantum. Una guardia che non intercetta
    è peggio di nessuna guardia: rassicura."""
    modulo = tmp_path / relativo
    modulo.parent.mkdir(parents=True, exist_ok=True)
    modulo.write_text('atomic_write_text(registry_path(d), "x")\n', encoding="utf-8")

    trovate = _righe_che_scrivono_gli_store(tmp_path)

    assert bool(trovate) is atteso, f"{relativo} → {trovate}"
    if atteso:
        assert trovate == [f"{relativo}:1"], "il rapporto deve dire path relativo e riga"


def test_il_lock_pubblico_e_lo_STESSO_dei_privati(tmp_path):
    """Un alias che puntasse a un lock **diverso** non serializzerebbe niente, e il test qui sopra
    passerebbe lo stesso: sarebbe sicurezza di facciata."""
    assert registry.WRITE_LOCK is registry._WRITE_LOCK


def test_unione_vale_anche_per_il_registro_delle_licenze_emesse(tmp_path):
    """Stessa logica per `licenses.jsonl`: perdere un record significa che «Rinnova» e «Ri-mostra
    token» smettono di funzionare per quella licenza — uno dei due danni elencati nella #183."""
    destinazione = str(tmp_path / "usata")
    origine = str(tmp_path / "origine")
    os.makedirs(destinazione), os.makedirs(origine)
    seed_hex, public_hex = _tool_configurato(origine, emesse=["LIC-VECCHIA"])
    vecchio = backup.build_backup(origine, now=_NOW)

    core.save_signing_key(core.signing_key_path(destinazione), seed_hex, public_hex, _NOW)
    registry.append_record({"serial": "LIC-NUOVA", "name": "Dopo", "hardware_id": "HW1-X",
                            "issued_at": _NOW, "expires_at": _NOW + 86_400}, directory=destinazione)

    backup.restore_backup(vecchio, destinazione)

    serials = {r.get("serial") for r in registry.read_records(directory=destinazione)}
    assert serials == {"LIC-VECCHIA", "LIC-NUOVA"}


def test_le_IMPOSTAZIONI_invece_si_sovrascrivono(tmp_path):
    """La controprova che l'unione non è stata applicata a tutto: `publish_config.json` è una
    **configurazione**, non un registro append-only. Ripristinarla significa volere quella del
    backup — fondere due configurazioni non vorrebbe dire niente."""
    destinazione = str(tmp_path / "usata")
    origine = str(tmp_path / "origine")
    os.makedirs(destinazione), os.makedirs(origine)
    seed_hex, public_hex = _tool_configurato(origine)          # repo «tizio/x»
    contenuto = backup.build_backup(origine, now=_NOW)

    core.save_signing_key(core.signing_key_path(destinazione), seed_hex, public_hex, _NOW)
    publish_store.save_publish_config({"enabled": False, "repo": "altro/repo"},
                                      directory=destinazione)

    backup.restore_backup(contenuto, destinazione)

    assert publish_store.load_publish_config(directory=destinazione)["repo"] == "tizio/x"


@pytest.mark.skipif(os.name == "nt", reason="permessi POSIX; su Windows il modello è ACL (no-op)")
def test_il_seed_RIPRISTINATO_non_e_leggibile_da_altri(tmp_path):
    """Bloccante Fugu Ultra #184: sospetto di una finestra a umask sul seed ripristinato.

    Misurato: **non c'era** — `atomic_write_text` crea via `mkstemp`, già `0o600`. Il ripristino
    passa comunque ora dallo stesso primitivo di `save_backup` (`core._persist_key_file`), così la
    garanzia è esplicita invece che incidentale e arriva con l'`fsync` di file **e** directory. Il
    test misura l'esito, che è ciò che conta a prescindere da quale strato lo fornisce."""
    import stat as _stat
    origine = str(tmp_path / "origine")
    os.makedirs(origine)
    _tool_configurato(origine)
    destinazione = str(tmp_path / "nuova")
    os.umask(0o022)         # umask larga: se ci fosse una finestra, si vedrebbe qui

    backup.restore_backup(backup.build_backup(origine, now=_NOW), destinazione)

    modo = _stat.S_IMODE(os.stat(core.signing_key_path(destinazione)).st_mode)
    assert modo & (_stat.S_IRWXG | _stat.S_IRWXO) == 0, f"permessi troppo larghi sul seed: {modo:o}"


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


@pytest.mark.parametrize("dove", ["lettura", "scrittura", "serializzazione"])
def test_auto_backup_non_solleva_da_NESSUNA_delle_sue_fonti_di_guasto(tmp_path, monkeypatch, dove):
    """Rilievo Claude Fable 5 #184: il docstring promette «non solleva mai», ma il test che c'era
    copriva **una sola** fonte di guasto (percorso occupato da un file).

    Qui le fonti vengono colpite una per una — errore di lettura dello stato, errore di scrittura del
    backup, contenuto non serializzabile — perché la promessa vale solo se vale per tutte: chi la usa
    (`gui._auto_backup_safe`, agganciato a emissione e revoca) non ha modo di sapere quale ramo
    fallirà."""
    d = str(tmp_path / "tool")
    os.makedirs(d)
    _tool_configurato(d, revocati=["LIC-A"])

    if dove == "lettura":
        def leggi_ko(path):
            raise PermissionError(13, "Permission denied", path)
        monkeypatch.setattr(backup, "_leggi", leggi_ko)
    elif dove == "scrittura":
        def scrivi_ko(path, obj, **kw):
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(backup.atomic_io, "atomic_write_json", scrivi_ko)
    else:
        def serializza_ko(path, obj, **kw):
            raise TypeError("Object of type set is not JSON serializable")
        monkeypatch.setattr(backup.atomic_io, "atomic_write_json", serializza_ko)

    assert backup.auto_backup(d, now=_NOW) is False, \
        "il backup automatico deve dire «non fatto», mai far esplodere emissione o revoca"


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
