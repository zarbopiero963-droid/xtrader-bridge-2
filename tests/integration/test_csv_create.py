"""Test hard: «📄 Crea CSV» → genera un CSV a solo header + imposta+salva csv_path (#286).

Esercita il metodo REALE `App._create_and_save_csv` via l'harness headless (`make_app`), con
la VERA `save_config`/`init_csv` che scrivono su file **temporanei** (`CONFIG_FILE`
monkeypatchato). Verifica: header XTrader byte-esatto, anti data-loss su file estraneo, merge
config, no-op su annullo. Il dialog Tk (`_browse_create_csv`) è GUI-only → smoke test manuale.
"""

import csv
import os

from xtrader_bridge import config_store, csv_writer
from xtrader_bridge.csv_writer import CSV_HEADER


class _FakeEntry:
    """Campo CSV finto con delete/insert/get come una `CTkEntry` reale."""

    def __init__(self, value=""):
        self._v = value

    def delete(self, *_a):
        self._v = ""

    def insert(self, _idx, s):
        self._v = (self._v or "") + str(s)

    def get(self):
        return self._v


def _prep(make_app, app_mod, tmp_path, monkeypatch, *, config, gui_csv="",
          running=False, active=None):
    cfgfile = str(tmp_path / "config.json")
    monkeypatch.setattr(app_mod, "CONFIG_FILE", cfgfile)
    a = make_app(config=dict(config), running=running, csv_path=active)
    a._e_csv = _FakeEntry(gui_csv)
    # Guardia token PR-08c (come gli altri save non-form): stub no-op di default.
    a._had_incomplete_token_load = lambda: False
    a.resync_calls = []
    a._resync_token_field = lambda had=None: a.resync_calls.append(had)
    return a, cfgfile


def test_crea_csv_nuovo_header_only_e_salva_path(make_app, app_mod, tmp_path, monkeypatch):
    cfg = {"csv_path": "vecchio.csv", "chat_id": "42", "dry_run": True}
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config=cfg, gui_csv="vecchio.csv")
    dest = str(tmp_path / "nuovo" / "segnale.csv")
    os.makedirs(os.path.dirname(dest))
    ok = app_mod.App._create_and_save_csv(a, dest)
    assert ok is True
    # file creato con ESATTAMENTE l'header XTrader (BOM utf-8-sig + QUOTE_ALL + CRLF, no dati)
    expected = "\ufeff" + ",".join('"%s"' % c for c in CSV_HEADER) + "\r\n"
    with open(dest, "rb") as f:
        assert f.read().decode("utf-8") == expected
    # csv_path aggiornato (entry + config vivo) e persistito, altri campi INVARIATI (merge)
    assert a._e_csv.get() == dest
    assert a._config["csv_path"] == dest
    assert a._config["chat_id"] == "42"
    assert a._config["dry_run"] is True
    reloaded = config_store.load_config(cfgfile)
    assert reloaded["csv_path"] == dest
    assert reloaded["chat_id"] == "42"


def test_crea_csv_rigenera_bridge_header_only(make_app, app_mod, tmp_path, monkeypatch):
    # Un CSV del bridge già a SOLO header (nessun segnale) → rigenerato (idempotente), no force.
    dest = str(tmp_path / "segnale.csv")
    app_mod.init_csv(dest)                                     # bridge header-only
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": dest})
    ok = app_mod.App._create_and_save_csv(a, dest)
    assert ok is True
    with open(dest, newline="", encoding="utf-8-sig") as f:
        assert list(csv.reader(f)) == [CSV_HEADER]


def test_crea_csv_bridge_con_segnale_attivo_senza_force_rifiuta(make_app, app_mod, tmp_path, monkeypatch):
    # ANTI DATA-LOSS (Fable+Fugu #330): un CSV del bridge con una riga ATTIVA non viene
    # cancellato senza conferma — un segnale non ancora letto da XTrader va protetto.
    dest = str(tmp_path / "segnale.csv")
    csv_writer.write_csv({c: ("X" if c == "EventName" else "") for c in CSV_HEADER}, dest)
    assert csv_writer.has_active_row(dest) is True             # segnale presente PRIMA
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": "vecchio.csv"})
    ok = app_mod.App._create_and_save_csv(a, dest)
    assert ok is False
    assert csv_writer.has_active_row(dest) is True             # riga NON rimossa
    assert a._config["csv_path"] == "vecchio.csv"             # config non toccata
    assert not os.path.exists(cfgfile)                         # nessun salvataggio
    assert any("contiene un segnale attivo" in m for m in a.logs)


def test_crea_csv_bridge_con_segnale_attivo_con_force(make_app, app_mod, tmp_path, monkeypatch):
    # Con conferma esplicita (force=True) → rigenerato a solo header (segnale rimosso).
    dest = str(tmp_path / "segnale.csv")
    csv_writer.write_csv({c: ("X" if c == "EventName" else "") for c in CSV_HEADER}, dest)
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": "vecchio.csv"})
    ok = app_mod.App._create_and_save_csv(a, dest, force=True)
    assert ok is True
    with open(dest, newline="", encoding="utf-8-sig") as f:
        assert list(csv.reader(f)) == [CSV_HEADER]             # riga rimossa
    assert a._config["csv_path"] == dest


def test_crea_csv_sessione_attiva_rifiutata_anche_con_force(make_app, app_mod, tmp_path, monkeypatch):
    # GUARDIA RUNTIME (Fable+Fugu #330): a bridge AVVIATO, ricreare il CSV della sessione
    # attiva è VIETATO (anche con force) — cancellerebbe il segnale in volo + desync runtime.
    dest = str(tmp_path / "segnale.csv")
    csv_writer.write_csv({c: ("X" if c == "EventName" else "") for c in CSV_HEADER}, dest)
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": dest},
                       running=True, active=dest)
    ok = app_mod.App._create_and_save_csv(a, dest, force=True)  # force NON deve bypassare
    assert ok is False
    assert csv_writer.has_active_row(dest) is True             # segnale INTATTO
    assert not os.path.exists(cfgfile)                          # nessun salvataggio
    assert any("bridge è AVVIATO" in m for m in a.logs)
    # invariante: cambiare/creare un ALTRO path a bridge avviato è invece permesso
    other = str(tmp_path / "altro.csv")
    assert app_mod.App._create_and_save_csv(a, other) is True
    assert a._active_csv_path == dest                          # sessione attiva invariata


def test_crea_csv_file_estraneo_senza_force_non_sovrascrive(make_app, app_mod, tmp_path, monkeypatch):
    # ANTI DATA-LOSS: un file NON-bridge scelto per errore NON viene distrutto senza force.
    foreign = tmp_path / "documenti_importanti.csv"
    original = "Nome,Cognome\nMario,Rossi\n"
    foreign.write_text(original, encoding="utf-8")
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": "vecchio.csv"})
    ok = app_mod.App._create_and_save_csv(a, str(foreign))
    assert ok is False
    assert foreign.read_text(encoding="utf-8") == original     # file estraneo INTATTO
    assert a._config["csv_path"] == "vecchio.csv"              # config NON toccata
    assert not os.path.exists(cfgfile)                          # nessun salvataggio
    assert any("NON è un CSV del bridge" in m for m in a.logs)  # avviso chiaro


def test_crea_csv_file_estraneo_con_force_sovrascrive(make_app, app_mod, tmp_path, monkeypatch):
    # Con conferma esplicita (force=True, dato dal GUI dopo askyesno) → rigenerato a header.
    foreign = tmp_path / "vecchio_export.csv"
    foreign.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": "vecchio.csv"})
    ok = app_mod.App._create_and_save_csv(a, str(foreign), force=True)
    assert ok is True
    with open(str(foreign), newline="", encoding="utf-8-sig") as f:
        assert list(csv.reader(f)) == [CSV_HEADER]             # ora è un CSV del bridge
    assert a._config["csv_path"] == str(foreign)


def test_crea_csv_annullato_no_op(make_app, app_mod, tmp_path, monkeypatch):
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": "vecchio.csv"},
                       gui_csv="vecchio.csv")
    assert app_mod.App._create_and_save_csv(a, "") is False        # dialog annullato
    assert app_mod.App._create_and_save_csv(a, "   ") is False     # solo spazi
    assert a._e_csv.get() == "vecchio.csv"                          # entry invariata
    assert a._config["csv_path"] == "vecchio.csv"                  # config invariata
    assert not os.path.exists(cfgfile)                              # nessuna scrittura


def test_crea_csv_errore_scrittura_avvisa_no_save(make_app, app_mod, tmp_path, monkeypatch):
    # Ramo OSError: se la creazione atomica fallisce (permessi/disco), il metodo NON tocca la
    # config, ritorna False e avvisa nel log.
    dest = str(tmp_path / "segnale.csv")
    a, cfgfile = _prep(make_app, app_mod, tmp_path, monkeypatch, config={"csv_path": "vecchio.csv"})

    def _boom(_p, *, force=False):
        raise OSError("disco pieno")
    monkeypatch.setattr(app_mod.csv_writer, "create_header_only_csv", _boom)
    ok = app_mod.App._create_and_save_csv(a, dest)
    assert ok is False
    assert a._config["csv_path"] == "vecchio.csv"             # config non toccata
    assert not os.path.exists(cfgfile)                         # nessun salvataggio
    assert any("Crea CSV» fallito" in m for m in a.logs)


def test_crea_csv_guardia_token_pr08c(make_app, app_mod, tmp_path, monkeypatch):
    # Come «Sfoglia…» (#328): il save non-form cattura il marker load-incompleto PRIMA e
    # risincronizza il token DOPO, così «Crea CSV» col keyring giù al load non fa poi
    # cancellare il token al «Salva Config» seguente.
    dest = str(tmp_path / "segnale.csv")
    a, _ = _prep(make_app, app_mod, tmp_path, monkeypatch,
                 config={"csv_path": "vecchio.csv", "bot_token": "SEGRETO"})
    a._had_incomplete_token_load = lambda: "MARKER"
    monkeypatch.setattr(app_mod, "save_config",
                        lambda cfg_arg, _p: config_store.SaveResult(
                            dict(cfg_arg), True, config_store.SAVE_OK))
    app_mod.App._create_and_save_csv(a, dest)
    assert a.resync_calls == ["MARKER"]                            # guardia token eseguita
