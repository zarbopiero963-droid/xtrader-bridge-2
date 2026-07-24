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

from license_manager import core, registry
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
    return fake


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


def test_evaluate_renew_giorni_non_validi(gui, tmp_path):
    fake = _fake(gui, tmp_path)
    gui.LicenseManagerApp._ensure_keypair(fake)
    first = gui.LicenseManagerApp._evaluate_issue(fake, "Anna", "Verdi", "10", _HW)
    out = gui.LicenseManagerApp._evaluate_renew(fake, registry.license_serial(first["token"]), "xx")
    assert out["accepted"] is False and "giorni" in out["message"].lower()


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
