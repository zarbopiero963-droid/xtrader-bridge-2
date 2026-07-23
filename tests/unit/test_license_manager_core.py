"""Test hard del License Manager — logica pura (#140 PR 3a).

Esercita le funzioni REALI di `license_manager.core`: generazione keypair, firma licenza (round-trip
verificato con `verify_license` del bridge), validazioni fail-closed, e custodia del file-chiave
(atomica, permessi ristretti, corruzione MAI scartata in silenzio, no-overwrite senza richiesta
esplicita). Nessun segreto reale: il seed usato è un seed di TEST etichettato.
"""

import json
import os
import stat

import pytest

from license_manager import core
from xtrader_bridge.licensing import ed25519
from xtrader_bridge.licensing.hwid import NO_HARDWARE_ID
from xtrader_bridge.licensing import license as lic

# Seed di TEST (NON una chiave reale): 32 byte esadecimali, noto solo ai test.
_TEST_SEED_HEX = "a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00"
_TEST_PUBLIC_HEX = ed25519.public_key(bytes.fromhex(_TEST_SEED_HEX)).hex()
_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_000_000_000
_DAY = 86_400


# ── generate_keypair ────────────────────────────────────────────────────────────────────────
def test_generate_keypair_valida_e_derivabile():
    seed_hex, public_hex = core.generate_keypair()
    assert len(seed_hex) == 64 and len(public_hex) == 64
    # la pubblica deve essere DAVVERO derivata dal seed
    assert ed25519.public_key(bytes.fromhex(seed_hex)).hex() == public_hex


def test_generate_keypair_e_casuale():
    a, _ = core.generate_keypair()
    b, _ = core.generate_keypair()
    assert a != b   # os.urandom → due seed diversi


# ── issue_license: round-trip verificato dal bridge ─────────────────────────────────────────
def test_issue_license_round_trip_valida():
    token = core.issue_license(_TEST_SEED_HEX, "Mario Rossi", 15, _HW, _NOW)
    st = lic.verify_license(token, _HW, _NOW, public_key_hex=_TEST_PUBLIC_HEX)
    assert st.valid is True
    assert st.name == "Mario Rossi"
    assert st.days_left == 15


def test_issue_license_scadenza_rispettata():
    token = core.issue_license(_TEST_SEED_HEX, "Mario Rossi", 15, _HW, _NOW)
    # 14 giorni dopo: ancora valida
    assert lic.verify_license(token, _HW, _NOW + 14 * _DAY,
                              public_key_hex=_TEST_PUBLIC_HEX).valid is True
    # 16 giorni dopo: scaduta
    st = lic.verify_license(token, _HW, _NOW + 16 * _DAY, public_key_hex=_TEST_PUBLIC_HEX)
    assert st.valid is False
    assert st.reason == lic.EXPIRED


def test_issue_license_legata_all_hardware():
    token = core.issue_license(_TEST_SEED_HEX, "Mario Rossi", 15, _HW, _NOW)
    st = lic.verify_license(token, "HW1-AAAA-BBBB-CCCC-DDDD", _NOW,
                            public_key_hex=_TEST_PUBLIC_HEX)
    assert st.valid is False
    assert st.reason == lic.WRONG_HARDWARE


def test_issue_license_pulisce_spazi_nome_e_hw():
    token = core.issue_license(_TEST_SEED_HEX, "  Mario Rossi  ", 15, "  " + _HW + " ", _NOW)
    st = lic.verify_license(token, _HW, _NOW, public_key_hex=_TEST_PUBLIC_HEX)
    assert st.valid is True and st.name == "Mario Rossi"


# ── issue_license: validazioni fail-closed ──────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["", "   ", None, 123])
def test_issue_license_nome_invalido(name):
    with pytest.raises(ValueError):
        core.issue_license(_TEST_SEED_HEX, name, 15, _HW, _NOW)


@pytest.mark.parametrize("days", [0, -1, -100])
def test_issue_license_giorni_non_positivi(days):
    with pytest.raises(ValueError):
        core.issue_license(_TEST_SEED_HEX, "Mario Rossi", days, _HW, _NOW)


@pytest.mark.parametrize("days", [1.5, "15", True, None])
def test_issue_license_giorni_non_interi(days):
    # float / stringa / bool / None non sono un intero-giorni valido (bool è sottoclasse di int
    # ma NON è un conteggio giorni: True→1 sarebbe una licenza forgiata da un flag).
    with pytest.raises(ValueError):
        core.issue_license(_TEST_SEED_HEX, "Mario Rossi", days, _HW, _NOW)


def test_issue_license_giorni_oltre_cap():
    with pytest.raises(ValueError):
        core.issue_license(_TEST_SEED_HEX, "Mario Rossi", core.MAX_LICENSE_DAYS + 1, _HW, _NOW)


@pytest.mark.parametrize("hw", [NO_HARDWARE_ID, "", "   ", None])
def test_issue_license_hardware_non_identificabile(hw):
    # Un hardware cieco/vuoto/sentinella non è legabile: rifiuto (coerente con verify_license).
    with pytest.raises(ValueError):
        core.issue_license(_TEST_SEED_HEX, "Mario Rossi", 15, hw, _NOW)


def test_issue_license_seed_malformato():
    with pytest.raises(ValueError):
        core.issue_license("non-esadecimale", "Mario Rossi", 15, _HW, _NOW)


# ── custodia del file-chiave: save/load round-trip ──────────────────────────────────────────
def test_save_load_round_trip(tmp_path):
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    loaded = core.load_signing_key(path)
    assert loaded["seed"] == _TEST_SEED_HEX
    assert loaded["public"] == _TEST_PUBLIC_HEX
    assert loaded["created"] == _NOW


def test_load_assente_ritorna_none(tmp_path):
    assert core.load_signing_key(core.signing_key_path(str(tmp_path))) is None


def test_save_coppia_incoerente_valueerror(tmp_path):
    # public che NON deriva dal seed → rifiuto (mai salvare una coppia che firmerebbe token
    # non verificabili).
    path = core.signing_key_path(str(tmp_path))
    wrong_public = ed25519.public_key(os.urandom(32)).hex()
    with pytest.raises(ValueError):
        core.save_signing_key(path, _TEST_SEED_HEX, wrong_public, _NOW)
    assert not os.path.exists(path)     # niente scritto


def test_save_permessi_ristretti_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("permessi 0o600 verificabili solo su POSIX")
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_save_overwrite_permessi_ristretti_posix(tmp_path):
    # Fable/Fugu #145: anche il path overwrite=True (temp+replace) crea il seed a 0o600 esplicito,
    # senza finestra a permessi larghi. Verifica il modo finale dopo un rimpiazzo deliberato.
    if os.name != "posix":
        pytest.skip("permessi 0o600 verificabili solo su POSIX")
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    seed2, pub2 = core.generate_keypair()
    core.save_signing_key(path, seed2, pub2, _NOW + 1, overwrite=True)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


# ── regola di sicurezza chiave: no-overwrite, corruzione MAI scartata ───────────────────────
def test_save_non_sovrascrive_senza_flag(tmp_path):
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    # una seconda chiave, senza overwrite → rifiutata, la prima resta intatta
    seed2, pub2 = core.generate_keypair()
    with pytest.raises(core.KeyExistsError):
        core.save_signing_key(path, seed2, pub2, _NOW + 1)
    assert core.load_signing_key(path)["seed"] == _TEST_SEED_HEX


def test_save_sovrascrive_con_flag(tmp_path):
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    seed2, pub2 = core.generate_keypair()
    core.save_signing_key(path, seed2, pub2, _NOW + 1, overwrite=True)
    assert core.load_signing_key(path)["seed"] == seed2


def test_save_o_excl_blocca_overwrite_anche_saltando_il_precheck(tmp_path, monkeypatch):
    # Fable #145 (TOCTOU): l'enforcement no-overwrite è ATOMICO via O_EXCL, non solo il pre-check.
    # Simuliamo la race in cui il pre-check `load_signing_key` vede il file ancora assente (ritorna
    # None) ma il file esiste già al momento della scrittura: O_EXCL deve comunque rifiutare, così
    # una chiave esistente non viene mai sovrascritta/persa.
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)   # chiave già presente
    monkeypatch.setattr(core, "load_signing_key", lambda p: None)          # pre-check "cieco"
    other_seed, other_pub = core.generate_keypair()
    with pytest.raises(core.KeyExistsError):
        core.save_signing_key(path, other_seed, other_pub, _NOW + 1)
    # e il file su disco è ancora la chiave originale (non sovrascritta)
    monkeypatch.undo()
    assert core.load_signing_key(path)["seed"] == _TEST_SEED_HEX


def test_save_overwrite_resta_atomico(tmp_path):
    # overwrite=True usa la sostituzione atomica (temp+replace): la chiave finale è quella nuova,
    # nessun temporaneo orfano rimasto nella cartella.
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    seed2, pub2 = core.generate_keypair()
    core.save_signing_key(path, seed2, pub2, _NOW + 1, overwrite=True)
    assert core.load_signing_key(path)["seed"] == seed2
    leftovers = [n for n in os.listdir(str(tmp_path)) if n.startswith(".signing_key_")]
    assert leftovers == []                                                # nessun temp orfano


def test_save_overwrite_completa_anche_se_chmod_solleva(tmp_path, monkeypatch):
    # GLM/GPT #145: il restringimento permessi è BEST-EFFORT — se `os.chmod` solleva (file aperto su
    # Windows / network drive), il salvataggio della chiave deve comunque COMPLETARE (il temp è già
    # 0o600 via mkstemp su POSIX). Regressione sulla resilienza del path overwrite.
    path = core.signing_key_path(str(tmp_path))
    core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    seed2, pub2 = core.generate_keypair()

    def _boom(*_a, **_k):
        raise OSError("chmod non supportato (simulato)")
    monkeypatch.setattr(core.os, "chmod", _boom)
    core.save_signing_key(path, seed2, pub2, _NOW + 1, overwrite=True)    # non deve sollevare
    # `load_signing_key` non usa `chmod` → la verifica è valida col patch ancora attivo (pytest lo
    # ripristina a fine test); niente "ripristino" fittizio (core.os È os → risettarlo è un no-op).
    assert core.load_signing_key(path)["seed"] == seed2                   # scritta comunque


def test_load_json_corrotto_solleva_non_scarta(tmp_path):
    # Regola chiave: un file-chiave corrotto NON è mai «assente» → solleva, e resta su disco
    # (perdere una chiave = non poter più rinnovare i bridge distribuiti).
    path = core.signing_key_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ questo non e' json valido ")
    with pytest.raises(core.KeyFileCorruptError):
        core.load_signing_key(path)
    assert os.path.exists(path)         # non scartato


def test_load_schema_incompleto_solleva(tmp_path):
    path = core.signing_key_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "created": _NOW}, f)     # manca seed/public
    with pytest.raises(core.KeyFileCorruptError):
        core.load_signing_key(path)


def test_load_public_incoerente_solleva(tmp_path):
    # seed valido ma public manomessa (non deriva dal seed) → corruzione/tamper rilevata.
    path = core.signing_key_path(str(tmp_path))
    wrong_public = ed25519.public_key(os.urandom(32)).hex()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "seed": _TEST_SEED_HEX, "public": wrong_public, "created": _NOW}, f)
    with pytest.raises(core.KeyFileCorruptError):
        core.load_signing_key(path)


def test_save_dopo_corruzione_propaga_non_sovrascrive(tmp_path):
    # Se il file esistente è corrotto, save_signing_key (che chiama load per il check no-overwrite)
    # PROPAGA la corruzione invece di sovrascrivere ciecamente: la decisione resta all'umano.
    path = core.signing_key_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("corrotto")
    with pytest.raises(core.KeyFileCorruptError):
        core.save_signing_key(path, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)


# ── blindatura permessi cartella-dati (#140 PR 3c, rilievo Fugu #146) ─────────────────────────
def test_secure_dir_posix_0700(tmp_path):
    if os.name != "posix":
        pytest.skip("permessi 0o700 verificabili solo su POSIX")
    d = str(tmp_path / "lmdata")
    os.makedirs(d)
    core.secure_dir(d)
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_secure_dir_windows_usa_icacls(tmp_path, monkeypatch):
    # Su Windows chmod non basta (ACL NTFS): secure_dir invoca icacls. Due comandi (review GPT #147):
    # /reset azzera le ACE ESPLICITE pregresse, poi /inheritance:r + /grant al SOLO utente corrente.
    # Verificato via runner iniettato (nessun Windows reale).
    monkeypatch.setattr(core, "_current_user", lambda: "pippo")
    calls = []
    core.secure_dir(str(tmp_path), run=lambda *a, **k: calls.append(a[0]), platform="win32")
    assert len(calls) == 2                              # /reset + /grant
    reset_cmd, grant_cmd = calls
    assert reset_cmd[0] == "icacls" and "/reset" in reset_cmd and str(tmp_path) in reset_cmd
    assert grant_cmd[0] == "icacls" and str(tmp_path) in grant_cmd
    assert "/inheritance:r" in grant_cmd and "/grant:r" in grant_cmd
    assert "pippo:(OI)(CI)F" in grant_cmd


def test_secure_dir_windows_senza_utente_niente_icacls(tmp_path, monkeypatch):
    # Se l'utente corrente non è determinabile, non si invoca icacls (niente comando ambiguo).
    monkeypatch.setattr(core, "_current_user", lambda: "")
    calls = []
    core.secure_dir(str(tmp_path), run=lambda *a, **k: calls.append(a[0]), platform="win32")
    assert calls == []


def test_secure_dir_non_windows_niente_icacls(tmp_path):
    calls = []
    core.secure_dir(str(tmp_path), run=lambda *a, **k: calls.append(a), platform="linux")
    assert calls == []                              # su POSIX solo chmod, nessun icacls


def test_secure_dir_best_effort_non_solleva(tmp_path, monkeypatch):
    # chmod che solleva e run che solleva NON devono propagare (best-effort).
    monkeypatch.setattr(core.os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    def _boom_run(*a, **k):
        raise OSError("icacls assente (simulato)")
    core.secure_dir(str(tmp_path), run=_boom_run, platform="win32")   # non deve sollevare


def test_ensure_secure_dir_crea_e_restringe(tmp_path):
    d = str(tmp_path / "nuova" / "lmdata")
    ret = core.ensure_secure_dir(d)
    assert ret == d and os.path.isdir(d)
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_ensure_secure_dir_makedirs_fallisce_best_effort(tmp_path, monkeypatch):
    # GLM #147: se makedirs fallisce (permessi insufficienti), ensure_secure_dir NON solleva e
    # ritorna comunque il path (best-effort: il tool prosegue, la blindatura non è garantita).
    def _boom(*_a, **_k):
        raise OSError("permesso negato (simulato)")
    monkeypatch.setattr(core.os, "makedirs", _boom)
    d = str(tmp_path / "x")
    assert core.ensure_secure_dir(d) == d              # non solleva


# ── export/backup ───────────────────────────────────────────────────────────────────────────
def test_export_backup_copia_identica(tmp_path):
    src = core.signing_key_path(str(tmp_path))
    core.save_signing_key(src, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    dest = str(tmp_path / "backup" / "signing_key_backup.json")
    core.export_signing_key(src, dest)
    exported = core.load_signing_key(dest)
    assert exported["seed"] == _TEST_SEED_HEX and exported["public"] == _TEST_PUBLIC_HEX


def test_export_e_fedele_byte_per_byte(tmp_path):
    # Fable #145: un backup deve essere FEDELE, non ricostruito — nessun metadato (es. `created`)
    # alterato silenziosamente. Verifica che il backup sia byte-identico alla sorgente.
    src = core.signing_key_path(str(tmp_path))
    core.save_signing_key(src, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    dest = str(tmp_path / "backup" / "b.json")
    core.export_signing_key(src, dest)
    with open(src, "r", encoding="utf-8") as f:
        src_bytes = f.read()
    with open(dest, "r", encoding="utf-8") as f:
        dest_bytes = f.read()
    assert dest_bytes == src_bytes                                   # backup fedele, non ricostruito
    assert core.load_signing_key(dest)["created"] == _NOW           # metadato preservato


def test_export_preserva_created_non_standard(tmp_path):
    # Regressione Fable #145: PRIMA export ricostruiva `created: 0` se il campo non era int valido.
    # Una sorgente con keypair valida ma `created` malformato (manomissione) deve restare FEDELE
    # nel backup, non essere silenziosamente degradata.
    src = str(tmp_path / "src.json")
    tampered = json.dumps({"v": 1, "seed": _TEST_SEED_HEX, "public": _TEST_PUBLIC_HEX,
                           "created": "non-un-int"}, indent=2, sort_keys=True)
    with open(src, "w", encoding="utf-8") as f:
        f.write(tampered)
    dest = str(tmp_path / "b.json")
    core.export_signing_key(src, dest)                               # sorgente valida (keypair ok)
    with open(dest, "r", encoding="utf-8") as f:
        assert json.load(f)["created"] == "non-un-int"              # fedele, NON degradato a 0


def test_export_assente_solleva(tmp_path):
    with pytest.raises(FileNotFoundError):
        core.export_signing_key(core.signing_key_path(str(tmp_path)), str(tmp_path / "b.json"))


def test_export_non_sovrascrive_dest_esistente_senza_flag(tmp_path):
    # CR #145: come save, l'export non deve sovrascrivere in silenzio una chiave valida già
    # presente nella destinazione (un backup di UN'ALTRA keypair non va perso).
    src = core.signing_key_path(str(tmp_path / "src"))
    core.save_signing_key(src, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    dest = str(tmp_path / "dest" / "backup.json")
    other_seed, other_pub = core.generate_keypair()
    core.save_signing_key(dest, other_seed, other_pub, _NOW)     # backup preesistente diverso
    with pytest.raises(core.KeyExistsError):
        core.export_signing_key(src, dest)
    assert core.load_signing_key(dest)["seed"] == other_seed     # backup intatto


def test_export_o_excl_blocca_overwrite_anche_saltando_il_precheck(tmp_path, monkeypatch):
    # GLM #145: parità con save — anche export usa `_persist_key_file(overwrite=False)`, quindi
    # l'enforcement no-overwrite è ATOMICO via O_EXCL pure sul backup. Simuliamo la race (pre-check
    # cieco) e verifichiamo che un backup esistente non venga sovrascritto/perso.
    src = core.signing_key_path(str(tmp_path / "src"))
    core.save_signing_key(src, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    dest = str(tmp_path / "dest" / "backup.json")
    other_seed, other_pub = core.generate_keypair()
    core.save_signing_key(dest, other_seed, other_pub, _NOW)      # backup preesistente diverso
    # pre-check "cieco" solo sulla DEST (ritorna None), ma reale sulla SRC (serve il contenuto).
    monkeypatch.setattr(core, "load_signing_key",
                        lambda p, _r=core.load_signing_key: None if p == dest else _r(p))
    with pytest.raises(core.KeyExistsError):
        core.export_signing_key(src, dest)
    monkeypatch.undo()
    assert core.load_signing_key(dest)["seed"] == other_seed      # backup intatto


def test_export_sovrascrive_dest_con_flag(tmp_path):
    src = core.signing_key_path(str(tmp_path / "src"))
    core.save_signing_key(src, _TEST_SEED_HEX, _TEST_PUBLIC_HEX, _NOW)
    dest = str(tmp_path / "dest" / "backup.json")
    other_seed, other_pub = core.generate_keypair()
    core.save_signing_key(dest, other_seed, other_pub, _NOW)
    core.export_signing_key(src, dest, overwrite=True)
    assert core.load_signing_key(dest)["seed"] == _TEST_SEED_HEX  # ora è la chiave esportata


# ── cartella utente dedicata ────────────────────────────────────────────────────────────────
def test_manager_dir_usa_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", os.path.join("X", "roaming"))
    d = core.manager_dir()
    assert d.endswith(core.APP_DIR_NAME)
    assert "roaming" in d


def test_manager_dir_separata_dal_bridge(monkeypatch):
    # Il License Manager NON deve condividere la cartella del bridge (XTraderBridge).
    from xtrader_bridge import config_store
    monkeypatch.setenv("APPDATA", os.path.join("X", "roaming"))
    assert core.manager_dir() != config_store.config_dir()
