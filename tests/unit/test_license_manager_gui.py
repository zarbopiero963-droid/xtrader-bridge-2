"""Test hard della mini-GUI del License Manager (#140 PR 3b).

La costruzione dei widget richiede un root Tk → qui si esercitano gli **handler puri**
(`_ensure_keypair`, `_current_key_state`, `_evaluate_issue`, `_evaluate_export`) su un `self` FINTO
(stesso pattern dei meta-test GUI del repo, `customtkinter` stubbato), con `core` REALE su una
cartella-chiave temporanea. Nessun segreto reale: il seed è generato al volo o è quello di TEST.
"""

import importlib
import os
import stat
import sys
import types

import pytest

from license_manager import backup, core, publish_store, registry
from xtrader_bridge.licensing import license as lic

_NOW = 1_000_000_000
_HW = "HW1-1234-5678-9ABC-DEF0"


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def gui(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "license_manager.gui", raising=False)
    return importlib.import_module("license_manager.gui")


def _fake(gui, tmp_path, now=_NOW):
    """`self` finto con `core` REALE e cartella-chiave temporanea. Gli helper interni che gli
    handler chiamano via `self` (`_key_path`, `_current_key_state`) sono rilegati alla classe reale
    (stesso pattern dei meta-test GUI del repo)."""
    fake = types.SimpleNamespace(
        _key_dir=str(tmp_path),
        _now=lambda: now,
        _generate_keypair=core.generate_keypair,
        _load_key=core.load_signing_key,
        _save_key=core.save_signing_key,
        _export_key=core.export_signing_key,
        _issue_license=core.issue_license,
        _record_issued=registry.append_record,
        _read_records=registry.read_records,
        _record_revocation=registry.append_revocation,
        _read_revocations=registry.read_revocations,
    )
    fake._reg_query_entry = None
    fake._registry_box = None
    fake._key_path = lambda: core.signing_key_path(fake._key_dir)
    fake._current_key_state = lambda: gui.LicenseManagerApp._current_key_state(fake)
    fake._record_issued_safe = lambda token: gui.LicenseManagerApp._record_issued_safe(fake, token)
    fake._load_key_or_error = lambda: gui.LicenseManagerApp._load_key_or_error(fake)
    fake._parse_days = gui.LicenseManagerApp._parse_days
    fake._sign_and_record = (lambda nome, giorni, hw, *, seed, verb="generata":
                             gui.LicenseManagerApp._sign_and_record(fake, nome, giorni, hw,
                                                                    seed=seed, verb=verb))
    fake._registry_view = lambda query="": gui.LicenseManagerApp._registry_view(fake, query)
    fake._read = lambda entry: gui.LicenseManagerApp._read(fake, entry)
    fake._format_registry_rows = gui.LicenseManagerApp._format_registry_rows
    fake._on_registry_refresh = lambda: gui.LicenseManagerApp._on_registry_refresh(fake)
    fake._token_box = None
    fake._renew_serial_entry = None
    fake._renew_giorni_entry = None
    fake._show_token = lambda tok: gui.LicenseManagerApp._show_token(fake, tok)
    fake._evaluate_renew = lambda s, g: gui.LicenseManagerApp._evaluate_renew(fake, s, g)
    fake._evaluate_resend = lambda s: gui.LicenseManagerApp._evaluate_resend(fake, s)
    fake._build_signed_revocation_list = lambda: gui.LicenseManagerApp._build_signed_revocation_list(fake)
    fake._record_revocation_safe = lambda rec: gui.LicenseManagerApp._record_revocation_safe(fake, rec)
    fake._evaluate_revoke = lambda s: gui.LicenseManagerApp._evaluate_revoke(fake, s)
    fake._evaluate_publish_revocation = lambda d: gui.LicenseManagerApp._evaluate_publish_revocation(fake, d)
    # Pubblicazione automatica (#157): store su file temporaneo REALE, keyring e HTTP FINTI (nessun
    # keyring di sistema toccato, nessun socket aperto).
    fake._load_publish_config = publish_store.load_publish_config
    fake._save_publish_config = publish_store.save_publish_config
    fake._kr_token = None
    fake._load_publish_token = lambda: fake._kr_token
    fake._save_publish_token = lambda tok: (setattr(fake, "_kr_token", tok) or True)
    fake._publish_calls = []
    fake._publish_upload = (lambda content, **kw: (fake._publish_calls.append({"content": content, **kw})
                                                   or {"ok": True, "action": "updated",
                                                       "message": "Lista revoche aggiornata."}))
    fake._publish_after_id = None
    # Stato «ultima pubblicazione riuscita» (#157): store REALE su file temporaneo, così il test
    # esercita davvero la scrittura/rilettura invece di un doppio in memoria che non proverebbe la
    # persistenza. L'etichetta non e' un widget: si registra il testo dipinto, per poterlo asserire.
    fake._load_last_publish = publish_store.load_last_publish
    # Backup/ripristino (#183): moduli REALI su cartella temporanea — il backup automatico deve
    # esercitare la scrittura vera, non un doppio in memoria che non proverebbe la persistenza.
    from license_manager import backup as _backup_mod
    fake._build_backup = _backup_mod.build_backup
    fake._save_backup = _backup_mod.save_backup
    fake._load_backup = _backup_mod.load_backup
    fake._restore_backup = _backup_mod.restore_backup
    fake._auto_backup = _backup_mod.auto_backup
    fake._auto_backup_safe = lambda: gui.LicenseManagerApp._auto_backup_safe(fake)
    fake._evaluate_export_backup = (lambda d, **kw:
                                    gui.LicenseManagerApp._evaluate_export_backup(fake, d, **kw))
    fake._evaluate_restore_backup = (lambda s, **kw:
                                     gui.LicenseManagerApp._evaluate_restore_backup(fake, s, **kw))
    # Conferma delle due azioni distruttive: risposta pilotata dal test + traccia delle domande, così
    # si può asserire *che cosa* è stato chiesto all'utente, non solo che qualcosa è stato chiesto.
    fake._confirm_calls = []
    fake._confirm_answer = False
    fake._confirm_backup = lambda testo: (fake._confirm_calls.append(testo) or fake._confirm_answer)
    fake._public_value = None
    fake._refresh_key_state = lambda: gui.LicenseManagerApp._refresh_key_state(fake)
    fake._dir_secured = True
    fake._save_last_publish = publish_store.save_last_publish
    fake._pub_last_lbl = None
    fake._pub_status_painted = []
    fake._publish_status = lambda: gui.LicenseManagerApp._publish_status(fake)
    fake._refresh_publish_status = lambda: fake._pub_status_painted.append(fake._publish_status())
    fake._closing = False
    fake._msgs = []
    fake._set_msg = fake._msgs.append

    def _fake_after(ms, fn):
        """`after(0, …)` = marshalling verso il thread GUI → esegue SUBITO (come farebbe Tk appena
        libero); `after(>0, …)` = timer → si registra soltanto."""
        if ms == 0:
            fn()
        else:
            fake._timer_calls.append(ms)
        return "after-id"
    fake._timer_calls = []
    fake.after = _fake_after
    fake._evaluate_save_publish_settings = (
        lambda repo, path, branch, interval, enabled, token="":
        gui.LicenseManagerApp._evaluate_save_publish_settings(fake, repo, path, branch, interval,
                                                              enabled, token=token))
    fake._evaluate_publish_now = lambda: gui.LicenseManagerApp._evaluate_publish_now(fake)
    # Il thread di pubblicazione è iniettato come runner INLINE: il test esercita il vero worker
    # (firma + upload finto + marshalling dell'esito) in modo deterministico, senza thread reali.
    fake._publish_inflight = False
    fake._publish_lock = lambda: gui.LicenseManagerApp._publish_lock(fake)
    fake._set_publish_inflight = lambda v: gui.LicenseManagerApp._set_publish_inflight(fake, v)
    fake._spawn_publish_thread = lambda target: target()
    fake._publish_async = lambda: gui.LicenseManagerApp._publish_async(fake)
    fake._publish_worker = lambda: gui.LicenseManagerApp._publish_worker(fake)
    fake._publish_finish = lambda res: gui.LicenseManagerApp._publish_finish(fake, res)
    fake._publish_tick = lambda: gui.LicenseManagerApp._publish_tick(fake)
    fake._schedule_publish_tick = lambda **kw: gui.LicenseManagerApp._schedule_publish_tick(fake, **kw)
    fake._cancel_publish_tick = lambda: gui.LicenseManagerApp._cancel_publish_tick(fake)
    return fake


class _RecBox:
    """Textbox finto che REGISTRA l'ultimo testo inserito (per i test di wiring GUI)."""

    def __init__(self):
        self.text = None

    def delete(self, *_a):
        self.text = None

    def insert(self, _idx, t):
        self.text = t


# ── keypair ────────────────────────────────────────────────────────────────────────────────────
def test_ensure_keypair_genera_se_assente(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    out = gui.LicenseManagerApp._ensure_keypair(fake)
    assert out["created"] is True and out["error"] is None
    # la pubblica mostrata coincide con quella salvata su disco
    saved = core.load_signing_key(core.signing_key_path(str(tmp_path)))
    assert saved["public"] == out["public"]


def test_ensure_keypair_riusa_se_presente(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    first = gui.LicenseManagerApp._ensure_keypair(fake)
    second = gui.LicenseManagerApp._ensure_keypair(fake)
    assert second["created"] is False
    assert second["public"] == first["public"]   # non rigenerata


def test_ensure_keypair_non_sovrascrive_file_corrotto(gui, tmp_path):
    path = core.signing_key_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("non-json")
    out = gui.LicenseManagerApp._ensure_keypair(_fake(gui, tmp_path))
    assert out["public"] is None and out["created"] is False
    assert "corrotto" in out["error"].lower()
    with open(path, encoding="utf-8") as f:
        assert f.read() == "non-json"            # non sovrascritto


def test_current_key_state_assente(gui, tmp_path):
    st = gui.LicenseManagerApp._current_key_state(_fake(gui, tmp_path))
    assert st == {"public": None, "error": None}


def test_secure_data_dir_all_avvio(gui, tmp_path):
    # #140 PR 3c (rilievo Fugu #146): all'avvio la GUI crea e restringe la cartella-dati del tool,
    # così il seed privato non è leggibile da altri account locali. Ritorna l'esito (review GPT/GLM
    # #147): True quando la blindatura è riuscita.
    d = str(tmp_path / "lmdata")
    fake = types.SimpleNamespace(_key_dir=d)
    ok = gui.LicenseManagerApp._secure_data_dir(fake)
    assert ok is True and os.path.isdir(d)
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_refresh_key_state_avvisa_se_cartella_non_blindata(gui, tmp_path):
    # review GPT/GLM #147: se la blindatura della cartella-chiave è fallita (_dir_secured False) e
    # non c'è un errore di chiave, l'avvio mostra un AVVISO invece di dare un falso senso di sicurezza.
    msgs = []
    fake = types.SimpleNamespace(
        _dir_secured=False,
        _public_value=None,
        _current_key_state=lambda: {"public": None, "error": None},
        _set_msg=lambda text: msgs.append(text),
    )
    gui.LicenseManagerApp._refresh_key_state(fake)
    assert msgs and "proteggere la cartella" in msgs[-1].lower()


def test_refresh_key_state_errore_chiave_ha_priorita(gui, tmp_path):
    # Se c'è un errore di chiave (es. corrotta), quello prevale sull'avviso cartella (un solo msg).
    msgs = []
    fake = types.SimpleNamespace(
        _dir_secured=False,
        _public_value=None,
        _current_key_state=lambda: {"public": None, "error": "File-chiave corrotto"},
        _set_msg=lambda text: msgs.append(text),
    )
    gui.LicenseManagerApp._refresh_key_state(fake)
    assert msgs == ["File-chiave corrotto"]


def test_refresh_key_state_cartella_blindata_nessun_avviso(gui, tmp_path):
    # Blindatura riuscita + nessun errore chiave → nessun messaggio (avvio pulito).
    msgs = []
    fake = types.SimpleNamespace(
        _dir_secured=True,
        _public_value=None,
        _current_key_state=lambda: {"public": None, "error": None},
        _set_msg=lambda text: msgs.append(text),
    )
    gui.LicenseManagerApp._refresh_key_state(fake)
    assert msgs == []


def _raise_oserror(_p):
    raise OSError("permesso negato (simulato)")


def test_current_key_state_file_illeggibile(gui, tmp_path):
    # GPT/GLM #146: copertura DIRETTA del ramo OSError di _current_key_state (oltre a quella
    # indiretta via _ensure_keypair) → stato d'errore, mai un crash.
    fake = _fake(gui, tmp_path)
    fake._load_key = _raise_oserror
    st = gui.LicenseManagerApp._current_key_state(fake)
    assert st["public"] is None and "leggere" in st["error"].lower()


def test_ensure_keypair_file_illeggibile_fail_safe(gui, tmp_path):
    # GLM #146: file-chiave ILLEGGIBILE (OSError su %APPDATA%, es. lock/permessi) → la GUI non
    # crasha all'avvio e NON rigenera sopra (fail-safe): stato d'errore, nessuna scrittura.
    fake = _fake(gui, tmp_path)
    fake._load_key = _raise_oserror
    out = gui.LicenseManagerApp._ensure_keypair(fake)
    assert out["public"] is None and out["created"] is False
    assert "leggere" in out["error"].lower()
    assert core.load_signing_key(core.signing_key_path(str(tmp_path))) is None   # niente scritto


def test_evaluate_issue_file_illeggibile_fail_safe(gui, tmp_path):
    # GLM #146: idem in emissione — un OSError sulla lettura chiave non solleva, non emette.
    fake = _fake(gui, tmp_path)
    fake._load_key = _raise_oserror
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    assert out["accepted"] is False and not out["token"]
    assert "leggere" in out["message"].lower()


# ── emissione licenza ────────────────────────────────────────────────────────────────────────
def test_evaluate_issue_senza_chiave(gui, tmp_path):
    out = gui.LicenseManagerApp._evaluate_issue(_fake(gui, tmp_path), "Mario", "Rossi", "15", _HW)
    assert out["accepted"] is False and not out["token"]
    assert "chiave" in out["message"].lower()


def test_evaluate_issue_valida_verifica_col_bridge(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)                        # crea la keypair
    public = core.load_signing_key(core.signing_key_path(str(tmp_path)))["public"]
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    assert out["accepted"] is True and out["token"]
    st = lic.verify_license(out["token"], _HW, _NOW, public_key_hex=public)
    assert st.valid is True
    assert st.name == "Mario Rossi" and st.days_left == 15


@pytest.mark.parametrize("giorni", ["", "abc", "1.5"])
def test_evaluate_issue_giorni_non_interi(gui, tmp_path, giorni):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", giorni, _HW)
    assert out["accepted"] is False and "inter" in out["message"].lower()


def test_evaluate_issue_hardware_non_identificabile(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", "")
    assert out["accepted"] is False and not out["token"]


def test_evaluate_issue_nome_vuoto(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "  ", "  ", "15", _HW)
    assert out["accepted"] is False            # nome completo vuoto → ValueError dal core


# ── backup ─────────────────────────────────────────────────────────────────────────────────────
def test_evaluate_export_senza_chiave(gui, tmp_path):
    out = gui.LicenseManagerApp._evaluate_export(_fake(gui, tmp_path), str(tmp_path / "b.json"))
    assert out["ok"] is False and "nessuna chiave" in out["message"].lower()


def test_evaluate_export_percorso_vuoto(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_export(fake, "")
    assert out["ok"] is False and "percorso" in out["message"].lower()


def test_evaluate_export_ok(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "backup" / "b.json")
    out = gui.LicenseManagerApp._evaluate_export(fake, dest)
    assert out["ok"] is True
    assert core.load_signing_key(dest) is not None    # backup valido


def test_evaluate_export_dest_esistente(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "b.json")
    seed2, pub2 = core.generate_keypair()
    core.save_signing_key(dest, seed2, pub2, _NOW)     # backup preesistente
    out = gui.LicenseManagerApp._evaluate_export(fake, dest)
    assert out["ok"] is False and "già" in out["message"].lower()
    assert core.load_signing_key(dest)["seed"] == seed2   # non sovrascritto


# ── registro licenze (opzione A) ─────────────────────────────────────────────────────────────────
def test_evaluate_issue_registra_nel_registro(gui, tmp_path):
    """Emettere una licenza la registra nel registro locale; la vista la ritrova."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    assert out["accepted"] is True and out["token"]
    recs = registry.read_records(directory=str(tmp_path))
    assert len(recs) == 1
    assert recs[0]["name"] == "Mario Rossi"
    assert recs[0]["hardware_id"] == _HW
    assert recs[0]["serial"] == registry.license_serial(out["token"])
    # la vista la mostra
    rows = fake._registry_view("mario")
    assert [r["name"] for r in rows] == ["Mario Rossi"]


def test_evaluate_issue_registro_fallito_non_blocca(gui, tmp_path):
    """Se la scrittura del registro fallisce, l'emissione riesce comunque (token valido) e il
    messaggio avvisa che il registro non è stato aggiornato (best-effort, non bloccante)."""
    def _boom(record, *, directory=None):
        raise OSError("registro non scrivibile")
    fake = _fake(gui, tmp_path)
    fake._record_issued = _boom
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Anna", "Bianchi", "30", _HW)
    assert out["accepted"] is True and out["token"], "l'emissione non deve fallire per il registro"
    assert "registro non aggiornato" in out["message"].lower()
    assert registry.read_records(directory=str(tmp_path)) == []   # nulla registrato


def test_registry_view_fail_safe_registro_assente(gui, tmp_path):
    """Con registro assente la vista non crasha e ritorna lista vuota."""
    fake = _fake(gui, tmp_path)
    assert fake._registry_view() == []


def test_format_registry_rows_non_mostra_il_token(gui, tmp_path):
    """La resa testuale del registro non contiene mai il token di attivazione."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_issue(fake, "Carla", "Neri", "10", _HW)
    rows = fake._registry_view()
    text = gui.LicenseManagerApp._format_registry_rows(rows)
    assert "Carla Neri" in text and "SCADUTA" not in text  # appena emessa → attiva
    assert out["token"] not in text, "il token non deve comparire nella vista del registro"


def test_format_registry_rows_vuoto_messaggio_esplicito(gui):
    """Registro vuoto → messaggio esplicito (review Sourcery #152), non stringa vuota."""
    assert gui.LicenseManagerApp._format_registry_rows([]) == "(nessuna licenza registrata)"


def test_on_registry_refresh_non_crasha_su_read_error(gui, tmp_path):
    """`_on_registry_refresh` è interamente best-effort (review GPT-5.5 #152): un `read_records`
    che solleva (provider custom non fail-safe) NON deve far crashare l'azione."""
    fake = _fake(gui, tmp_path)
    def _boom(**_k):
        raise OSError("registro illeggibile (simulato)")
    fake._read_records = _boom
    fake._registry_view = lambda query="": gui.LicenseManagerApp._registry_view(fake, query)
    gui.LicenseManagerApp._on_registry_refresh(fake)   # non deve sollevare


def test_record_issued_safe_non_logga_il_messaggio_eccezione(gui, tmp_path, caplog):
    """Regression-guard privacy (review GLM/GPT #152): se la scrittura del registro solleva, il
    warning logga il TIPO eccezione + il path, ma MAI il messaggio grezzo (che un provider custom
    potrebbe riempire di dati)."""
    import logging
    sentinel = "DATO_SENSIBILE_NEL_MESSAGGIO"

    def _boom(record, *, directory=None):
        raise OSError(sentinel)

    fake = _fake(gui, tmp_path)
    fake._record_issued = _boom
    seed, _pub = core.generate_keypair()
    token = core.issue_license(seed, "Tizio", 10, _HW, _NOW)   # token reale → record_from_token ok
    with caplog.at_level(logging.WARNING):
        ok = gui.LicenseManagerApp._record_issued_safe(fake, token)
    assert ok is False
    assert sentinel not in caplog.text, "il messaggio dell'eccezione non deve finire nei log"
    assert "OSError" in caplog.text, "il tipo eccezione sì (diagnostica)"


# ── rinnovo / ri-emissione (opzione B) ───────────────────────────────────────────────────────────
def test_evaluate_renew_riemette_stesso_hw_nuovi_giorni(gui, tmp_path):
    """Rinnovo: dato il serial di una licenza, ri-emette per lo STESSO nome+hardware con nuovi
    giorni → nuovo token/serial; il record vecchio resta (storico)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    first = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    serial0 = registry.license_serial(first["token"])
    out = gui.LicenseManagerApp._evaluate_renew(fake, serial0, "30")
    assert out["accepted"] is True and out["token"] and out["token"] != first["token"]
    assert "rinnovata" in out["message"].lower()
    recs = registry.read_records(directory=str(tmp_path))
    assert len(recs) == 2                                   # storico preservato
    new_rec = registry.find_by_serial(recs, registry.license_serial(out["token"]))
    assert new_rec["name"] == "Mario Rossi" and new_rec["hardware_id"] == _HW
    assert new_rec["days"] == 30


def test_evaluate_renew_serial_non_trovato(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_renew(fake, "LIC-INESISTENTE", "15")
    assert out["accepted"] is False and not out["token"]
    assert "non trovato" in out["message"].lower()
    # non-writing su rifiuto (review CodeRabbit #153): un rinnovo fallito non tocca il registro
    assert registry.read_records(directory=str(tmp_path)) == []


def test_evaluate_renew_giorni_non_validi(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    first = gui.LicenseManagerApp._evaluate_issue(fake, "Anna", "Verdi", "10", _HW)
    out = gui.LicenseManagerApp._evaluate_renew(fake, registry.license_serial(first["token"]), "xx")
    assert out["accepted"] is False and "giorni" in out["message"].lower()
    # non-writing su rifiuto (review CodeRabbit #153): resta solo il record dell'emissione iniziale
    assert len(registry.read_records(directory=str(tmp_path))) == 1


def test_evaluate_resend_ritorna_token_esistente(gui, tmp_path):
    """Ri-mostra: dato il serial, ritorna il token GIÀ emesso (nessuna nuova firma)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    first = gui.LicenseManagerApp._evaluate_issue(fake, "Carla", "Neri", "20", _HW)
    out = gui.LicenseManagerApp._evaluate_resend(fake, registry.license_serial(first["token"]))
    assert out["found"] is True and out["token"] == first["token"]
    # nessun nuovo record creato dalla ri-mostra
    assert len(registry.read_records(directory=str(tmp_path))) == 1


def test_evaluate_resend_serial_non_trovato(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    out = gui.LicenseManagerApp._evaluate_resend(fake, "LIC-NULLA")
    assert out["found"] is False and not out["token"] and "non trovato" in out["message"].lower()


def test_evaluate_resend_record_senza_token(gui, tmp_path):
    """Ramo del record «vecchio» senza campo token (registro pre-opzione-A): found=True ma token
    vuoto + messaggio esplicito che invita a rinnovare (review GLM #153)."""
    fake = _fake(gui, tmp_path)
    rec = {"serial": "LIC-OLD000000000", "name": "Vecchio", "hardware_id": _HW,
           "expiry": _NOW + 10 * 86_400}   # nessun campo "token"
    registry.append_record(rec, directory=str(tmp_path))
    out = gui.LicenseManagerApp._evaluate_resend(fake, "LIC-OLD000000000")
    assert out["found"] is True and out["token"] == ""
    assert "non contiene il token" in out["message"].lower()


def test_evaluate_renew_record_corrotto_fail_closed(gui, tmp_path):
    """Rinnovo su un record corrotto (name o hardware_id vuoti): deve fallire fail-closed
    (issue_license valida nome/hardware), non emettere (review GPT-5.5 #153)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    bad = {"serial": "LIC-CORROTTO0001", "name": "", "hardware_id": "", "expiry": _NOW + 10 * 86_400}
    registry.append_record(bad, directory=str(tmp_path))
    out = gui.LicenseManagerApp._evaluate_renew(fake, "LIC-CORROTTO0001", "15")
    assert out["accepted"] is False and not out["token"]
    # niente nuovo record emesso dal rinnovo fallito
    assert len(registry.read_records(directory=str(tmp_path))) == 1


def test_on_renew_wiring_mostra_nuovo_token(gui, tmp_path):
    """Wiring dell'handler `_on_renew`: legge gli Entry, ri-emette e MOSTRA il nuovo token nel box
    (review GPT-5.5 #153) — copre la glue, non solo `_evaluate_renew`."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    first = gui.LicenseManagerApp._evaluate_issue(fake, "Wire", "Test", "10", _HW)
    serial0 = registry.license_serial(first["token"])
    box = _RecBox()
    fake._token_box = box
    fake._renew_serial_entry = types.SimpleNamespace(get=lambda: serial0)
    fake._renew_giorni_entry = types.SimpleNamespace(get=lambda: "25")
    msgs = []
    fake._set_msg = lambda t: msgs.append(t)
    gui.LicenseManagerApp._on_renew(fake)
    assert box.text and box.text != first["token"], "il box deve mostrare il NUOVO token del rinnovo"
    assert msgs and "rinnovata" in msgs[-1].lower()


def test_on_resend_wiring_mostra_token_esistente(gui, tmp_path):
    """Wiring di `_on_resend`: ri-mostra il token esistente nel box, senza nuovi record."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    first = gui.LicenseManagerApp._evaluate_issue(fake, "Re", "Send", "10", _HW)
    serial0 = registry.license_serial(first["token"])
    box = _RecBox()
    fake._token_box = box
    fake._renew_serial_entry = types.SimpleNamespace(get=lambda: serial0)
    fake._set_msg = lambda _t: None
    gui.LicenseManagerApp._on_resend(fake)
    assert box.text == first["token"]
    assert len(registry.read_records(directory=str(tmp_path))) == 1   # nessun nuovo record


# ── revoca (R3b) ─────────────────────────────────────────────────────────────────────────────────
def test_evaluate_revoke_registra_la_revoca(gui, tmp_path):
    """Revocare un serial esistente scrive UN record nello store revoche (serial + metadati)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    issued = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    serial = registry.license_serial(issued["token"])
    out = gui.LicenseManagerApp._evaluate_revoke(fake, serial)
    assert out["accepted"] is True
    revs = registry.read_revocations(directory=str(tmp_path))
    assert len(revs) == 1
    assert revs[0]["serial"] == serial
    assert revs[0]["hardware_id"] == _HW and revs[0]["name"] == "Mario Rossi"
    assert registry.is_serial_revoked(revs, serial) is True


def test_evaluate_revoke_serial_non_trovato_non_scrive(gui, tmp_path):
    """Serial non nel registro → fail-closed: nessuna scrittura nello store revoche."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    out = gui.LicenseManagerApp._evaluate_revoke(fake, "LIC-DOESNOTEXIST")
    assert out["accepted"] is False and "non trovato" in out["message"].lower()
    assert registry.read_revocations(directory=str(tmp_path)) == []


def test_evaluate_revoke_gia_revocata_nessun_duplicato(gui, tmp_path):
    """Revocare due volte lo stesso serial non aggiunge un secondo record (idempotente)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    issued = gui.LicenseManagerApp._evaluate_issue(fake, "Anna", "Bianchi", "30", _HW)
    serial = registry.license_serial(issued["token"])
    assert gui.LicenseManagerApp._evaluate_revoke(fake, serial)["accepted"] is True
    out2 = gui.LicenseManagerApp._evaluate_revoke(fake, serial)
    assert out2["accepted"] is False and "già revocata" in out2["message"].lower()
    assert len(registry.read_revocations(directory=str(tmp_path))) == 1


def test_evaluate_revoke_store_fallito_non_accetta(gui, tmp_path):
    """Se lo store revoche non è scrivibile, la revoca NON è dichiarata accettata (best-effort)."""
    def _boom(record, *, directory=None):
        raise OSError("store non scrivibile")
    fake = _fake(gui, tmp_path)
    fake._record_revocation = _boom
    gui.LicenseManagerApp._ensure_keypair(fake)
    issued = gui.LicenseManagerApp._evaluate_issue(fake, "Ok", "Ko", "10", _HW)
    serial = registry.license_serial(issued["token"])
    out = gui.LicenseManagerApp._evaluate_revoke(fake, serial)
    assert out["accepted"] is False and "non registrata" in out["message"].lower()


# ── pubblicazione lista revoche firmata (R3b) ────────────────────────────────────────────────────
def test_evaluate_publish_revocation_round_trip(gui, tmp_path):
    """Esporta la lista firmata; `revocation.verify_revocation_list` (R3a) la verifica con la chiave
    pubblica e ritrova il serial revocato → contratto build/verify end-to-end."""
    from xtrader_bridge.licensing import revocation
    fake = _fake(gui, tmp_path)
    key = gui.LicenseManagerApp._ensure_keypair(fake)
    public_hex = key["public"]
    issued = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    serial = registry.license_serial(issued["token"])
    gui.LicenseManagerApp._evaluate_revoke(fake, serial)
    dest = str(tmp_path / "revocation_list.txt")
    out = gui.LicenseManagerApp._evaluate_publish_revocation(fake, dest)
    assert out["ok"] is True
    signed = open(dest, encoding="utf-8").read().strip()
    rev = revocation.verify_revocation_list(signed, public_key_hex=public_hex)
    assert rev is not None
    assert revocation.is_revoked(rev, serial=serial) is True
    # una licenza non revocata NON risulta revocata
    assert revocation.is_revoked(rev, serial="LIC-ALIVE000000") is False


def test_evaluate_publish_revocation_store_vuoto_lista_valida(gui, tmp_path):
    """Store revoche vuoto → lista firmata comunque valida (stato «niente revocato»): l'URL esiste
    sempre, così il bridge fail-closed non si blocca solo perché non c'è nulla da revocare."""
    from xtrader_bridge.licensing import revocation
    fake = _fake(gui, tmp_path)
    key = gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "revocation_list.txt")
    out = gui.LicenseManagerApp._evaluate_publish_revocation(fake, dest)
    assert out["ok"] is True
    rev = revocation.verify_revocation_list(open(dest, encoding="utf-8").read().strip(),
                                            public_key_hex=key["public"])
    assert rev is not None and rev.serials == set() and rev.hardware_ids == set()


def test_evaluate_publish_revocation_senza_percorso_o_chiave_fail_closed(gui, tmp_path):
    """Fail-closed: senza percorso, o senza chiave, non produce nulla."""
    fake = _fake(gui, tmp_path)
    # percorso vuoto (chiave presente)
    gui.LicenseManagerApp._ensure_keypair(fake)
    assert gui.LicenseManagerApp._evaluate_publish_revocation(fake, "")["ok"] is False
    # senza chiave (nuova cartella vuota)
    fake2 = _fake(gui, tmp_path / "vuota")
    out = gui.LicenseManagerApp._evaluate_publish_revocation(fake2, str(tmp_path / "x.txt"))
    assert out["ok"] is False and "chiave" in out["message"].lower()
    assert not os.path.exists(str(tmp_path / "x.txt"))   # niente file prodotto


# ── pubblicazione automatica su GitHub (#157) ────────────────────────────────────────────────────
# L'intervallo di default dei casi «validi» è deliberatamente **sopra il tetto**, DERIVATO da
# `MAX_INTERVAL_HOURS` invece che ricopiato: il tetto a sua volta deriva dalla finestra di freschezza
# del bridge (`MAX_LIST_AGE_S`), quindi un letterale qui smetterebbe di esercitare il clamping appena
# la finestra cambia — è esattamente quello che è successo quando la finestra è passata a 3 giorni e
# il tetto da 8 h a 24 h.
_SOPRA_IL_TETTO = str(publish_store.MAX_INTERVAL_HOURS + 1)
_PUB_OK = dict(repo="tizio/xtrader-revocation", path="revocation_list.txt", branch="main",
               interval=_SOPRA_IL_TETTO)


def test_save_publish_settings_valide_salvano_e_abilitano(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    out = fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"],
                                               _PUB_OK["interval"], True, token="ghp_ABC")
    assert out["ok"] is True
    cfg = publish_store.load_publish_config(directory=str(tmp_path))
    assert cfg == {"enabled": True, "repo": _PUB_OK["repo"], "path": _PUB_OK["path"],
                   "branch": "main", "interval_hours": publish_store.MAX_INTERVAL_HOURS}
    assert fake._kr_token == "ghp_ABC"                       # token nel keyring (finto)
    # ...e MAI su disco
    testo = open(publish_store.publish_config_path(str(tmp_path)), encoding="utf-8").read()
    assert "ghp_ABC" not in testo


def test_save_publish_settings_repo_invalido_non_salva(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    out = fake._evaluate_save_publish_settings("solo-nome", "l.txt", "main", _SOPRA_IL_TETTO, True, token="ghp_X")
    assert out["ok"] is False and "owner/nome" in out["message"]
    assert not os.path.exists(publish_store.publish_config_path(str(tmp_path)))   # niente scritto


def test_save_publish_settings_abilitata_senza_token_rifiutata(gui, tmp_path):
    """Abilitare la pubblicazione senza alcun token nel keyring è fail-closed: non si salva."""
    fake = _fake(gui, tmp_path)
    out = fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"],
                                               _SOPRA_IL_TETTO, True, token="")
    assert out["ok"] is False and "token" in out["message"].lower()
    assert not os.path.exists(publish_store.publish_config_path(str(tmp_path)))


def test_save_publish_settings_keyring_ko_non_salva(gui, tmp_path):
    """Keyring non disponibile → il token NON è salvabile: si rifiuta invece di scriverlo in chiaro."""
    fake = _fake(gui, tmp_path)
    fake._save_publish_token = lambda tok: False
    out = fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"],
                                               _SOPRA_IL_TETTO, True, token="ghp_ABC")
    assert out["ok"] is False and "keyring" in out["message"].lower()
    assert not os.path.exists(publish_store.publish_config_path(str(tmp_path)))


def test_save_publish_settings_token_vuoto_non_cancella_esistente(gui, tmp_path):
    """Ri-salvare lasciando il campo token vuoto NON deve perdere il token già nel keyring."""
    fake = _fake(gui, tmp_path)
    fake._kr_token = "ghp_ESISTENTE"
    out = fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"],
                                               "6", True, token="")
    assert out["ok"] is True and fake._kr_token == "ghp_ESISTENTE"
    assert publish_store.load_publish_config(directory=str(tmp_path))["interval_hours"] == 6


def test_publish_now_carica_la_lista_firmata(gui, tmp_path):
    """`_evaluate_publish_now` firma la lista e la passa all'upload; il messaggio riporta l'URL raw."""
    from xtrader_bridge.licensing import revocation
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    key = core.load_signing_key(core.signing_key_path(str(tmp_path)))
    issued = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "15", _HW)
    serial = registry.license_serial(issued["token"])
    gui.LicenseManagerApp._evaluate_revoke(fake, serial)
    fake._kr_token = "ghp_ABC"
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"], _SOPRA_IL_TETTO, True)
    out = fake._evaluate_publish_now()
    assert out["ok"] is True
    assert "raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt" in out["message"]
    # il contenuto caricato è una lista firmata VERIFICABILE che contiene il serial revocato
    caricato = fake._publish_calls[-1]["content"].strip()
    rev = revocation.verify_revocation_list(caricato, public_key_hex=key["public"])
    assert rev is not None and serial in rev.serials
    assert fake._publish_calls[-1]["repo"] == _PUB_OK["repo"]


def test_publish_now_senza_token_o_config_fail_closed(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    # config non ancora impostata → messaggio di validazione, nessun upload
    assert fake._evaluate_publish_now()["ok"] is False
    assert fake._publish_calls == []
    # config ok ma token assente nel keyring → fail-closed
    publish_store.save_publish_config({"enabled": True, **{k: v for k, v in (
        ("repo", _PUB_OK["repo"]), ("path", _PUB_OK["path"]), ("branch", "main"))}},
        directory=str(tmp_path))
    fake._kr_token = None
    out = fake._evaluate_publish_now()
    assert out["ok"] is False and "token" in out["message"].lower()
    assert fake._publish_calls == []


def test_publish_now_config_con_spazi_bloccata_prima_di_toccare_la_rete(gui, tmp_path):
    """Flusso completo config → pubblicazione con un `path` che contiene spazi (config scritta a mano
    o proveniente da una versione precedente): la validazione ferma TUTTI i percorsi — il pulsante
    «Pubblica ora» e il tick automatico — prima di qualunque chiamata di rete (rilievi GPT-5.5/GLM 5.2
    #158). Meglio un errore leggibile che un file pubblicato a un URL che il bridge non sa scaricare."""
    fake = _fake(gui, tmp_path)
    fake._kr_token = "ghp_X"
    publish_store.save_publish_config({"enabled": True, "repo": _PUB_OK["repo"],
                                       "path": "lista revoche.txt", "branch": _PUB_OK["branch"]},
                                      directory=str(tmp_path))
    out = fake._evaluate_publish_now()
    assert out["ok"] is False and "spazi" in out["message"].lower()
    assert fake._publish_calls == [], "nessun upload con impostazioni non valide"

    # ...e nemmeno il tick automatico pubblica: si limita a ri-armarsi
    gui.LicenseManagerApp._publish_tick(fake)
    assert fake._publish_calls == []
    assert fake._timer_calls, "il ciclo deve comunque restare armato"
    assert fake._publish_inflight is False


def test_publish_now_upload_fallito_riporta_errore(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    fake._kr_token = "ghp_ABC"
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"], _SOPRA_IL_TETTO, True)
    fake._publish_upload = lambda content, **kw: {"ok": False, "action": "",
                                                  "message": "Token non valido o senza permessi."}
    out = fake._evaluate_publish_now()
    assert out["ok"] is False and "permessi" in out["message"]


def test_publish_tick_pubblica_solo_se_abilitata_e_si_riarma(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    fake._kr_token = "ghp_ABC"
    # DISABILITATA → nessun upload, ma il tick si ri-arma comunque
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"], _SOPRA_IL_TETTO, False)
    gui.LicenseManagerApp._publish_tick(fake)
    assert fake._publish_calls == []
    assert fake._timer_calls == [publish_store.MAX_INTERVAL_HOURS * 3_600_000]
    # ABILITATA → pubblica (in background) e si ri-arma
    fake._timer_calls.clear()
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"], "6", True)
    gui.LicenseManagerApp._publish_tick(fake)
    assert len(fake._publish_calls) == 1 and fake._timer_calls == [6 * 3_600_000]
    assert fake._publish_inflight is False, "il lucchetto va liberato a esito applicato"


def test_publish_tick_errore_non_ferma_il_ciclo(gui, tmp_path):
    """Un errore imprevisto nel tick non deve rompere la finestra: si logga e ci si ri-arma."""
    fake = _fake(gui, tmp_path)
    def _boom(**kw):
        raise RuntimeError("errore imprevisto")
    fake._load_publish_config = _boom
    gui.LicenseManagerApp._publish_tick(fake)
    assert fake._timer_calls, "il tick deve ri-armarsi anche dopo un errore"


def test_cancel_publish_tick_e_chiusura(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    cancelled = []
    fake._publish_after_id = "id-1"
    fake.after_cancel = cancelled.append
    gui.LicenseManagerApp._cancel_publish_tick(fake)
    assert cancelled == ["id-1"] and fake._publish_after_id is None
    # in chiusura il tick NON si ri-arma
    fake._closing = True
    after_calls = []
    fake.after = lambda ms, fn: (after_calls.append(ms) or "id")
    gui.LicenseManagerApp._schedule_publish_tick(fake)
    assert after_calls == []


def test_publish_async_non_accavalla_due_upload(gui, tmp_path):
    """Un secondo avvio mentre una pubblicazione è in corso NON parte (lucchetto `_publish_inflight`)."""
    fake = _fake(gui, tmp_path)
    fake._publish_inflight = True                       # simula una pubblicazione già in volo
    assert fake._publish_async() is False
    assert fake._publish_calls == []                    # nessun upload avviato


def test_publish_worker_libera_il_lucchetto_anche_su_errore(gui, tmp_path):
    """Il worker non muore e **libera sempre** il lucchetto: un errore imprevisto diventa un esito
    negativo mostrato all'utente, non una GUI bloccata per sempre in «in corso»."""
    fake = _fake(gui, tmp_path)
    def _boom():
        raise RuntimeError("errore imprevisto")
    fake._evaluate_publish_now = _boom
    fake._publish_inflight = True
    gui.LicenseManagerApp._publish_worker(fake)
    assert fake._publish_inflight is False
    assert fake._msgs and "⚠️" in fake._msgs[-1]


def test_publish_worker_finestra_distrutta_libera_il_lucchetto(gui, tmp_path):
    """Se la finestra è distrutta (`after` solleva) non si tocca la UI, ma il lucchetto va liberato."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    fake._kr_token = "ghp_ABC"
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"], _SOPRA_IL_TETTO, True)
    def _after_ko(ms, fn):
        raise RuntimeError("finestra distrutta")
    fake.after = _after_ko
    fake._publish_inflight = True
    gui.LicenseManagerApp._publish_worker(fake)
    assert fake._publish_inflight is False


def test_on_publish_now_non_blocca_la_gui(gui, tmp_path):
    """`🚀 Pubblica ora` avvia in BACKGROUND: la callback ritorna subito con «in corso…» e l'esito
    arriva dopo (qui il runner è inline, quindi si vede già l'esito finale)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    fake._kr_token = "ghp_ABC"
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"], _SOPRA_IL_TETTO, True)
    spawned = []
    fake._spawn_publish_thread = lambda target: spawned.append(target)   # NON esegue: come un thread vero
    gui.LicenseManagerApp._on_publish_now(fake)
    assert spawned, "l'upload deve girare su un thread, non sul thread Tk"
    assert "in corso" in fake._msgs[-1].lower()
    assert fake._publish_calls == []          # la rete non è ancora partita: la GUI non ha atteso
    spawned[0]()                              # il worker gira "dopo"
    assert len(fake._publish_calls) == 1 and fake._publish_inflight is False


def test_publish_async_thread_non_avviabile_libera_il_lucchetto(gui, tmp_path):
    """Se il thread non parte (risorse esaurite), il lucchetto va liberato e si ritorna `False`,
    altrimenti la pubblicazione resterebbe bloccata per sempre (rilievo GPT-5.5 #158)."""
    fake = _fake(gui, tmp_path)
    tentativi = []

    def _no_thread(_target):
        tentativi.append(1)
        raise RuntimeError("impossibile avviare il thread")
    fake._spawn_publish_thread = _no_thread
    assert fake._publish_async() is False
    assert fake._publish_inflight is False              # lucchetto liberato → si può riprovare
    assert fake._publish_async() is False
    # il secondo tentativo ha DAVVERO rifatto check+start (non è stato rifiutato dal lucchetto
    # rimasto alzato): lo spawner è stato invocato due volte (rilievo GPT-5.5 #158)
    assert len(tentativi) == 2


def test_publish_finish_tollera_risultato_malformato(gui, tmp_path):
    """`_publish_finish` con `None`/dict incompleto non deve sollevare: libera il lucchetto e mostra
    un messaggio (rilievo GLM #158)."""
    fake = _fake(gui, tmp_path)
    for bad in (None, {}, {"ok": True}):
        fake._publish_inflight = True
        gui.LicenseManagerApp._publish_finish(fake, bad)
        assert fake._publish_inflight is False


def test_publish_async_check_and_set_atomico_sotto_lucchetto(gui, tmp_path):
    """Il check-and-set di `_publish_inflight` avviene sotto `Lock`: con un runner che NON esegue il
    worker, la seconda chiamata è rifiutata (nessun accavallamento) — rilievo GLM/GPT #158."""
    fake = _fake(gui, tmp_path)
    fake._spawn_publish_thread = lambda target: None    # simula un thread ancora in volo
    assert fake._publish_async() is True
    assert fake._publish_async() is False               # secondo click: rifiutato
    assert fake._publish_inflight is True
    # il lucchetto è un vero Lock riusato (stesso oggetto a ogni chiamata), non ricreato ogni volta
    assert gui.LicenseManagerApp._publish_lock(fake) is gui.LicenseManagerApp._publish_lock(fake)


def test_spawn_publish_thread_reale_esegue_il_worker(gui, tmp_path):
    """Il **vero** spawner (thread daemon) esegue davvero il target: il worker gira fuori dal thread
    chiamante (rilievo GLM #158 «i test iniettano il runner, non provano il thread reale»)."""
    import threading as _t
    fake = _fake(gui, tmp_path)
    fatto = _t.Event()
    thread_ids = []

    def _target():
        thread_ids.append(_t.get_ident())
        fatto.set()
    gui.LicenseManagerApp._spawn_publish_thread(fake, _target)
    assert fatto.wait(timeout=5), "il worker deve essere eseguito dal thread avviato"
    assert thread_ids and thread_ids[0] != _t.get_ident(), "deve girare su un ALTRO thread"


def test_tick_avvio_pubblica_subito_catch_up(gui, tmp_path):
    """All'avvio il primo tick è **ravvicinato** (catch-up): se il PC è stato spento a lungo la lista
    è già scaduta e i bridge sono bloccati — aspettare l'intero intervallo li terrebbe bloccati per
    ore (rilievo Fugu #158)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._schedule_publish_tick(fake, first=True)
    assert fake._timer_calls == [gui._PUBLISH_STARTUP_MS]
    assert gui._PUBLISH_STARTUP_MS < 60_000, "il catch-up d'avvio dev'essere quasi immediato"


def test_tick_saltato_riprova_a_breve(gui, tmp_path):
    """Se la pubblicazione del giro viene SALTATA (una era già in volo), il tick si ri-arma **fra
    pochi minuti**, non dopo l'intero intervallo: un salto non deve avvicinare la scadenza della
    lista (rilievo Fable #158)."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    fake._kr_token = "ghp_ABC"
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"], "8", True)
    fake._publish_inflight = True          # una pubblicazione è già in volo → questo giro salta
    fake._timer_calls.clear()
    gui.LicenseManagerApp._publish_tick(fake)
    assert fake._publish_calls == []                       # non ha pubblicato
    assert fake._timer_calls == [gui._PUBLISH_RETRY_MS]    # ...ma riprova a breve
    assert gui._PUBLISH_RETRY_MS < publish_store.MAX_INTERVAL_HOURS * 3_600_000


# ── etichetta «ultima pubblicazione riuscita» (#157) ─────────────────────────────────────────────
def _pubblicazione_pronta(gui, fake):
    """Config valida + chiave + token: tutto ciò che serve perché una pubblicazione possa riuscire."""
    gui.LicenseManagerApp._ensure_keypair(fake)
    fake._kr_token = "ghp_ABC"
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"],
                                         "6", True)


def test_pubblicazione_riuscita_registra_l_istante(gui, tmp_path):
    """Il timestamp si scrive **solo** in `_evaluate_publish_now`, che è il passaggio unico di
    entrambe le strade (🚀 «Pubblica ora» e tick automatico) → l'etichetta non può divergere fra le
    due. Qui si verifica che l'istante finisca davvero su disco, non in memoria."""
    fake = _fake(gui, tmp_path)
    _pubblicazione_pronta(gui, fake)
    assert publish_store.load_last_publish(directory=str(tmp_path)) is None

    out = gui.LicenseManagerApp._evaluate_publish_now(fake)

    assert out["ok"] is True
    assert publish_store.load_last_publish(directory=str(tmp_path)) == _NOW


def test_pubblicazione_FALLITA_non_registra_l_istante(gui, tmp_path):
    """Il caso che conta davvero. Se un tentativo fallito aggiornasse l'istante, l'etichetta direbbe
    «tutto a posto» mentre sull'URL c'è ancora la lista vecchia: sarebbe **peggio** di non avere
    l'etichetta, perché rassicurerebbe a torto proprio nel guasto che deve segnalare."""
    fake = _fake(gui, tmp_path)
    _pubblicazione_pronta(gui, fake)
    publish_store.save_last_publish(_NOW - 100_000, directory=str(tmp_path))     # una riuscita vecchia
    fake._publish_upload = lambda content, **kw: {"ok": False, "message": "GitHub irraggiungibile."}

    out = gui.LicenseManagerApp._evaluate_publish_now(fake)

    assert out["ok"] is False
    assert publish_store.load_last_publish(directory=str(tmp_path)) == _NOW - 100_000, \
        "un fallimento non deve spostare in avanti l'istante dell'ultima RIUSCITA"


def test_pubblicazione_senza_token_o_config_non_registra_l_istante(gui, tmp_path):
    """Gli altri due modi di uscire prima dell'upload: nessuno dei due ha pubblicato niente."""
    for prepara in (lambda f: setattr(f, "_kr_token", None),                    # token assente
                    lambda f: publish_store.save_publish_config({}, directory=str(tmp_path))):
        fake = _fake(gui, tmp_path)
        _pubblicazione_pronta(gui, fake)
        prepara(fake)
        assert gui.LicenseManagerApp._evaluate_publish_now(fake)["ok"] is False
        assert publish_store.load_last_publish(directory=str(tmp_path)) is None


def test_etichetta_riflette_lo_stato_su_disco_con_colore_semantico(gui, tmp_path):
    """L'etichetta deve dire la verità di ciò che sta su disco, con il colore che porta il
    significato: verde a posto, arancio un giro saltato, rosso i bridge si bloccano."""
    from xtrader_bridge import ui_theme
    from xtrader_bridge.licensing import revocation_client
    finestra = revocation_client.MAX_LIST_AGE_S
    fake = _fake(gui, tmp_path)

    testo, colore = gui.LicenseManagerApp._publish_status(fake)
    assert "mai" in testo and colore == ui_theme.STATUS_WARN

    publish_store.save_last_publish(_NOW - 3600, directory=str(tmp_path))
    testo, colore = gui.LicenseManagerApp._publish_status(fake)
    assert "1 ora fa" in testo and colore == ui_theme.STATUS_OK

    publish_store.save_last_publish(_NOW - finestra - 60, directory=str(tmp_path))
    testo, colore = gui.LicenseManagerApp._publish_status(fake)
    assert "non si propagano" in testo.lower() and colore == ui_theme.STATUS_ERR


def test_etichetta_ridipinta_anche_dopo_un_tentativo_FALLITO(gui, tmp_path):
    """Dopo un fallimento il refresh deve girare comunque: è proprio allora che serve vedere quanto è
    vecchia l'ultima riuscita, per sapere quanto tempo resta prima del blocco."""
    fake = _fake(gui, tmp_path)
    publish_store.save_last_publish(_NOW - 7200, directory=str(tmp_path))

    gui.LicenseManagerApp._publish_finish(fake, {"ok": False, "message": "rete giù"})

    assert len(fake._pub_status_painted) == 1
    testo, _colore = fake._pub_status_painted[0]
    assert "2 ore fa" in testo


def test_tick_automatico_registra_l_istante_come_il_pulsante(gui, tmp_path):
    """La strada automatica passa per lo stesso metodo: `_publish_tick` → `_publish_async` →
    `_publish_worker` → `_evaluate_publish_now`. Se un domani qualcuno pubblicasse fuori da quel
    passaggio, l'etichetta resterebbe indietro e questo test diventerebbe rosso."""
    fake = _fake(gui, tmp_path)
    _pubblicazione_pronta(gui, fake)

    gui.LicenseManagerApp._publish_tick(fake)

    assert len(fake._publish_calls) == 1
    assert publish_store.load_last_publish(directory=str(tmp_path)) == _NOW
    assert fake._pub_status_painted, "l'etichetta va ridipinta anche dopo una pubblicazione automatica"


def test_build_ui_dipinge_l_etichetta_all_apertura(gui):
    """Guardia sul SORGENTE, non sul comportamento — e va motivata, perché di norma in questo repo è
    il pattern sbagliato.

    L'invariante è: aprendo il License Manager l'etichetta è **già** dipinta. È tutto il punto — il
    guasto che deve segnalare (tick perso dopo una sospensione) non produce nessun evento, quindi lo
    stato dev'essere visibile senza che succeda niente. Ma `_build_ui` costruisce widget
    customtkinter reali e non è eseguibile headless: non esiste un giunto comportamentale da pilotare
    come per gli altri test qui sopra. Verificato con mutazione: togliendo la chiamata da `_build_ui`
    **nessun altro test diventa rosso**, quindi senza questa guardia la regressione passerebbe.

    Resta un test debole per costruzione: prova che la chiamata c'è, non che dipinga davvero. La
    verifica vera è lo smoke manuale documentato nel PR body."""
    import inspect
    sorgente = inspect.getsource(gui.LicenseManagerApp._build_ui)
    assert "_refresh_publish_status()" in sorgente, (
        "l'etichetta dell'ultima pubblicazione dev'essere dipinta alla costruzione della finestra: "
        "senza, resta vuota finché non capita una pubblicazione — e il caso che conta è proprio "
        "quello in cui le pubblicazioni si sono fermate")
    assert "_pub_last_lbl" in sorgente, "il widget dell'etichetta dev'essere creato in _build_ui"


# ── backup completo / ripristino (#183) ─────────────────────────────────────────────────────────
def test_auto_backup_scatta_su_EMISSIONE_e_su_REVOCA(gui, tmp_path):
    """L'automatismo è agganciato ai due momenti in cui lo stato cambia davvero."""
    from license_manager import backup as backup_mod
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    assert not os.path.exists(backup_mod.backup_path(str(tmp_path)))

    out = gui.LicenseManagerApp._evaluate_issue(fake, "Mario", "Rossi", "30", _HW)
    assert out["accepted"] is True
    assert os.path.exists(backup_mod.backup_path(str(tmp_path))), \
        "l'emissione cambia il registro → il backup automatico deve scattare"

    os.remove(backup_mod.backup_path(str(tmp_path)))
    serial = lic.license_serial(out["token"])
    assert fake._evaluate_revoke(serial)["accepted"] is True
    assert os.path.exists(backup_mod.backup_path(str(tmp_path))), \
        "anche la revoca cambia lo stato"


def test_auto_backup_NON_scatta_sulla_pubblicazione(gui, tmp_path):
    """Pubblicare ri-firma e carica, ma **non cambia nulla su disco**: un backup lì riscriverebbe gli
    stessi byte a ogni ciclo, senza proteggere niente. È la correzione al disegno iniziale."""
    from license_manager import backup as backup_mod
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    fake._kr_token = "ghp_ABC"
    fake._evaluate_save_publish_settings(_PUB_OK["repo"], _PUB_OK["path"], _PUB_OK["branch"],
                                         "6", True)
    percorso = backup_mod.backup_path(str(tmp_path))
    if os.path.exists(percorso):
        os.remove(percorso)

    assert gui.LicenseManagerApp._evaluate_publish_now(fake)["ok"] is True

    assert not os.path.exists(percorso), "la pubblicazione non deve generare un backup"


def test_export_backup_avvisa_che_contiene_la_chiave_privata(gui, tmp_path):
    """Il messaggio è l'unico momento in cui l'utente decide **dove** mettere il seed: deve dirgli
    cosa ha in mano, non un generico «salvato»."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "migrazione.json")

    out = gui.LicenseManagerApp._evaluate_export_backup(fake, dest)

    assert out["ok"] is True and os.path.exists(dest)
    assert "CHIAVE PRIVATA" in out["message"]
    assert "offline" in out["message"] and "token" in out["message"].lower()


def test_export_backup_senza_percorso_o_senza_chiave(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    assert gui.LicenseManagerApp._evaluate_export_backup(fake, "")["ok"] is False
    # nessuna keypair generata → fail-closed con messaggio parlante
    out = gui.LicenseManagerApp._evaluate_export_backup(fake, str(tmp_path / "b.json"))
    assert out["ok"] is False and "keypair" in out["message"]


def test_restore_backup_round_trip_dalla_GUI(gui, tmp_path):
    """Il percorso completo dagli handler: esporta da una cartella, ripristina in un'altra."""
    origine = _fake(gui, tmp_path / "origine")
    gui.LicenseManagerApp._ensure_keypair(origine)
    gui.LicenseManagerApp._evaluate_issue(origine, "Mario", "Rossi", "30", _HW)
    dest = str(tmp_path / "b.json")
    assert gui.LicenseManagerApp._evaluate_export_backup(origine, dest)["ok"] is True

    nuova = _fake(gui, tmp_path / "nuova")
    out = gui.LicenseManagerApp._evaluate_restore_backup(nuova, dest)

    assert out["ok"] is True and "signing_key.json" in out["message"]
    assert core.load_signing_key(core.signing_key_path(str(tmp_path / "nuova")))["public"] == \
        core.load_signing_key(core.signing_key_path(str(tmp_path / "origine")))["public"]


def test_restore_backup_su_keypair_diversa_chiede_conferma(gui, tmp_path):
    """L'errore deve **spiegare** cosa succederebbe, non limitarsi a rifiutare."""
    origine = _fake(gui, tmp_path / "origine")
    gui.LicenseManagerApp._ensure_keypair(origine)
    dest = str(tmp_path / "b.json")
    gui.LicenseManagerApp._evaluate_export_backup(origine, dest)

    altra = _fake(gui, tmp_path / "altra")
    gui.LicenseManagerApp._ensure_keypair(altra)          # keypair DIVERSA già presente

    out = gui.LicenseManagerApp._evaluate_restore_backup(altra, dest)
    assert out["ok"] is False and "DIVERSA" in out["message"] and "rinnovare" in out["message"]

    out2 = gui.LicenseManagerApp._evaluate_restore_backup(altra, dest, overwrite_key=True)
    assert out2["ok"] is True


def test_export_backup_su_percorso_non_scrivibile_non_solleva_e_non_logga_il_messaggio(
        gui, tmp_path, caplog):
    """Rilievo GPT-5.5 sulla #184: il ramo `OSError` (permessi negati, disco pieno, path invalido)
    non era esercitato. Deve dare un messaggio parlante invece di far esplodere la GUI, e nel log
    deve finire **solo il tipo** dell'eccezione: il suo testo contiene il percorso scelto
    dall'utente, che su Windows include il nome account.

    L'errore è **iniettato** sul giunto `_save_backup` invece di essere provocato con un `chmod`:
    misurato in questo ambiente, la suite gira come **root**, e root scrive lo stesso in una cartella
    `0o500` — un test basato sui permessi passerebbe verde senza aver mai esercitato il ramo. Il caso
    reale (permessi negati su Windows, file lockato dall'antivirus) resta smoke manuale.
    """
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)

    def nega(dest, contenuto, *, overwrite=False):
        raise PermissionError(13, "Permission denied", r"C:\Users\Piero Rossi\backup.json")
    fake._save_backup = nega

    with caplog.at_level("WARNING"):
        out = gui.LicenseManagerApp._evaluate_export_backup(fake, str(tmp_path / "b.json"))

    assert out["ok"] is False and "non scrivibile" in out["message"]
    assert "PermissionError" in caplog.text, "il TIPO serve a diagnosticare"
    assert "Piero" not in caplog.text and "Permission denied" not in caplog.text, \
        "il messaggio dell'eccezione contiene il percorso utente: non deve finire nel log"


def _finto_tkinter(monkeypatch, *, save="", open_="", askyesno=None):
    """Inietta un finto `tkinter` con `filedialog`/`messagebox`.

    Serve perché in questo ambiente `tkinter` non è installato: senza, gli handler cadono sempre nel
    ramo «nessun percorso» e la strada che conta — dialogo → handler → disco — non verrebbe mai
    esercitata. Il finto modulo NON apre nulla: ritorna i percorsi che decide il test."""
    finto = types.ModuleType("tkinter")
    finto.filedialog = types.SimpleNamespace(
        asksaveasfilename=lambda **kw: save,
        askopenfilename=lambda **kw: open_)
    finto.messagebox = types.SimpleNamespace(
        askyesno=(askyesno if askyesno is not None
                  else (lambda *a, **k: pytest.fail("conferma non attesa"))))
    monkeypatch.setitem(sys.modules, "tkinter", finto)
    return finto


def test_on_export_backup_scrive_il_file_scelto_nel_dialogo(gui, tmp_path, monkeypatch):
    """Il pulsante 📦 dev'essere collegato davvero: dialogo → backup su disco."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "migrazione.json")
    _finto_tkinter(monkeypatch, save=dest)

    gui.LicenseManagerApp._on_export_backup(fake)

    assert os.path.exists(dest), "il backup deve finire nel percorso scelto nel dialogo"
    assert core.SIGNING_KEY_FILE in backup.load_backup(dest)["files"]
    assert fake._confirm_calls == [], "su un percorso nuovo non si chiede nessuna conferma"


def test_on_export_backup_NON_sovrascrive_senza_conferma(gui, tmp_path, monkeypatch):
    """Quel file potrebbe essere il backup di un'ALTRA keypair: sovrascriverlo in silenzio ne
    perderebbe l'unica copia. Il test verifica i **byte**, non solo il messaggio."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "esistente.json")
    with open(dest, "w", encoding="utf-8") as f:
        f.write("BACKUP-DI-UN-ALTRA-CHIAVE")
    _finto_tkinter(monkeypatch, save=dest)
    fake._confirm_answer = False

    gui.LicenseManagerApp._on_export_backup(fake)

    with open(dest, encoding="utf-8") as f:
        assert f.read() == "BACKUP-DI-UN-ALTRA-CHIAVE", "senza conferma il file non si tocca"
    assert len(fake._confirm_calls) == 1
    assert "ALTRA" in fake._confirm_calls[0] and "rinnovare" in fake._confirm_calls[0], \
        "la domanda deve dire cosa si perde, non un generico «sovrascrivere?»"


def test_on_export_backup_sovrascrive_solo_con_conferma(gui, tmp_path, monkeypatch):
    """Controprova: senza, il test qui sopra passerebbe anche con un pulsante che non scrive mai."""
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    dest = str(tmp_path / "esistente.json")
    with open(dest, "w", encoding="utf-8") as f:
        f.write("vecchio")
    _finto_tkinter(monkeypatch, save=dest)
    fake._confirm_answer = True

    gui.LicenseManagerApp._on_export_backup(fake)

    assert core.SIGNING_KEY_FILE in backup.load_backup(dest)["files"]


def test_on_restore_backup_keypair_diversa_senza_conferma_NON_tocca_la_chiave(gui, tmp_path,
                                                                             monkeypatch):
    """Il caso più pericoloso: sul PC nuovo si è già premuto «Genera keypair». Se il ripristino
    sostituisse la chiave senza conferma, le licenze emesse dopo non verificherebbero più contro la
    pubblica compilata nell'EXE distribuito."""
    origine = _fake(gui, tmp_path / "origine")
    gui.LicenseManagerApp._ensure_keypair(origine)
    src = str(tmp_path / "b.json")
    gui.LicenseManagerApp._evaluate_export_backup(origine, src)

    altra = _fake(gui, tmp_path / "altra")
    gui.LicenseManagerApp._ensure_keypair(altra)
    prima = core.load_signing_key(core.signing_key_path(str(tmp_path / "altra")))["public"]
    _finto_tkinter(monkeypatch, open_=src)
    altra._confirm_answer = False

    gui.LicenseManagerApp._on_restore_backup(altra)

    dopo = core.load_signing_key(core.signing_key_path(str(tmp_path / "altra")))["public"]
    assert dopo == prima, "senza conferma la keypair esistente resta quella"
    assert len(altra._confirm_calls) == 1 and "DIVERSA" in altra._confirm_calls[0]


def test_on_restore_backup_sostituisce_la_keypair_con_conferma(gui, tmp_path, monkeypatch):
    """Controprova del test precedente, e strada reale di chi ha generato la chiave per sbaglio."""
    origine = _fake(gui, tmp_path / "origine")
    gui.LicenseManagerApp._ensure_keypair(origine)
    src = str(tmp_path / "b.json")
    gui.LicenseManagerApp._evaluate_export_backup(origine, src)
    attesa = core.load_signing_key(core.signing_key_path(str(tmp_path / "origine")))["public"]

    altra = _fake(gui, tmp_path / "altra")
    gui.LicenseManagerApp._ensure_keypair(altra)
    _finto_tkinter(monkeypatch, open_=src)
    altra._confirm_answer = True

    gui.LicenseManagerApp._on_restore_backup(altra)

    assert core.load_signing_key(core.signing_key_path(str(tmp_path / "altra")))["public"] == attesa


def test_confirm_backup_e_fail_closed_senza_dialogo(gui, tmp_path):
    """`tkinter` assente/rotto (qui è il caso reale: non è installato) → la risposta è **no**.
    Un default «sì» farebbe passare in silenzio proprio le due azioni irreversibili."""
    fake = _fake(gui, tmp_path)
    assert gui.LicenseManagerApp._confirm_backup(fake, "sovrascrivo?") is False


def test_i_pulsanti_backup_sono_collegati_agli_handler(gui):
    """Guardia sul SORGENTE (stessa motivazione dell'analoga sull'etichetta): `_build_ui` costruisce
    widget customtkinter reali e non è eseguibile headless, quindi non esiste un giunto
    comportamentale. Senza questa guardia gli handler potrebbero esistere ed essere **irraggiungibili
    dalla GUI** — cioè la funzione richiesta non esisterebbe per l'utente — e nessun test lo direbbe.
    Verificato con mutazione: togliendo i due `CTkButton` nessun altro test diventa rosso."""
    import inspect
    sorgente = inspect.getsource(gui.LicenseManagerApp._build_ui)
    assert "command=self._on_export_backup" in sorgente
    assert "command=self._on_restore_backup" in sorgente


def test_restore_backup_file_assente_o_rotto(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    assert gui.LicenseManagerApp._evaluate_restore_backup(fake, "")["ok"] is False
    assert gui.LicenseManagerApp._evaluate_restore_backup(
        fake, str(tmp_path / "inesistente.json"))["ok"] is False
    rotto = str(tmp_path / "rotto.json")
    with open(rotto, "w", encoding="utf-8") as f:
        f.write("{non-json")
    out = gui.LicenseManagerApp._evaluate_restore_backup(fake, rotto)
    assert out["ok"] is False and "JSON" in out["message"]
