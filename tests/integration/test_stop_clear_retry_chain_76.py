"""P3-8 audit #76 — after-id del retry post-STOP sovrascritto senza `after_cancel`.

Bug: `_schedule_stop_clear_retry` faceva `self._stop_clear_after_id = self.after(...)`
senza cancellare un timer già pendente. Con due STOP falliti ravvicinati (stesso path)
o con lo STOP su un path B mentre pende ancora il retry del path A abbandonato,
l'id veniva sovrascritto: DUE catene retry vive, una sola tracciata — `_on_close`
cancellava solo l'ultima e la catena orfana poteva rifirare dopo il destroy (parata
solo dal gate `_closing`), producendo in sessione retry/log doppi.

Fix testato: registro PER PATH `_stop_clear_after_ids` (chiave normcase+abspath, la
stessa normalizzazione di `_same_csv_path`):
- ri-arm dello STESSO path (anche con case/forma diversa, Windows) → `after_cancel`
  del timer precedente, mai doppia catena sullo stesso file;
- path DIVERSI → catene indipendenti tutte tracciate (il path abbandonato continua
  il suo retry in-sessione: nessuna regressione sul recovery);
- il firing consuma il proprio slot (pop) — registro pulito se il retry muore;
- `_on_close` cancella TUTTI gli id pendenti (sorgente pinnato, pattern #311).

Test con `make_app` (App headless, metodi REALI) e `after`/`after_cancel` contati."""

import re
from pathlib import Path

_APP_SRC = Path(__file__).resolve().parents[2] / "xtrader_bridge" / "app.py"


def _conta_timer(a):
    """Installa after/after_cancel contati sull'istanza; ritorna (armati, cancellati)."""
    armati, cancellati = [], []

    def _after(_ms, cb=None, *args):
        armati.append(cb)
        return f"id{len(armati)}"

    a.after = _after
    a.after_cancel = cancellati.append
    return armati, cancellati


def test_riarm_stesso_path_cancella_il_timer_precedente(make_app, app_mod, tmp_path):
    """FAIL-FIRST: pre-patch nessun after_cancel e nessun registro — l'id veniva
    sovrascritto e la prima catena restava viva e non tracciata."""
    a = make_app(running=False)
    _armati, cancellati = _conta_timer(a)
    p = str(tmp_path / "out.csv")
    # Stesso file in forma diversa: `abspath` normalizza `sub/..` su OGNI piattaforma
    # (il case-folding `OUT.CSV`≡`out.csv` è in più solo su Windows via `normcase`,
    # coerente con `_same_csv_path` — qui non lo si testa perché su POSIX è no-op).
    alias = str(tmp_path / "sub" / ".." / "out.csv")

    app_mod.App._schedule_stop_clear_retry(a, p)
    app_mod.App._schedule_stop_clear_retry(a, alias)

    assert cancellati == ["id1"], "il ri-arm dello stesso file deve cancellare il timer vecchio"
    assert list(a._stop_clear_after_ids.values()) == ["id2"]   # una sola catena tracciata


def test_path_diversi_catene_indipendenti_tutte_tracciate(make_app, app_mod, tmp_path):
    """Il retry del path ABBANDONATO (STOP precedente) non va perso quando un nuovo
    STOP arma il retry su un path diverso — entrambe le catene restano tracciate."""
    a = make_app(running=False)
    _armati, cancellati = _conta_timer(a)

    app_mod.App._schedule_stop_clear_retry(a, str(tmp_path / "vecchio.csv"))
    app_mod.App._schedule_stop_clear_retry(a, str(tmp_path / "nuovo.csv"))

    assert cancellati == []                                    # nessuna catena uccisa
    assert sorted(a._stop_clear_after_ids.values()) == ["id1", "id2"]


def test_firing_consuma_il_proprio_slot(make_app, app_mod, tmp_path, monkeypatch):
    """Retry riuscito: la chiave del path esce dal registro (niente id stantii da
    cancellare in chiusura) e il marker dirty (P3-6) viene rimosso."""
    a = make_app(running=False, csv_path=None)
    p = str(tmp_path / "out.csv")
    a._stop_clear_after_ids = {app_mod.App._stop_clear_key(p): "idX"}
    monkeypatch.setattr(app_mod, "clear_stale_csv", lambda _p, on_mismatch=None: True)
    puliti = []
    monkeypatch.setattr(app_mod.dirty_csv_store, "clear_dirty", puliti.append)
    a._journal_csv_cleared_if_had_row = lambda *x, **k: None

    app_mod.App._retry_stop_clear(a, p)

    assert a._stop_clear_after_ids == {}
    assert puliti == [p]


def test_mismatch_consuma_lo_slot_senza_riarmo_e_conserva_il_marker(make_app, app_mod,
                                                                    tmp_path, monkeypatch):
    """Ramo `cleared=False` (review GLM #93): file ESTRANEO sul path — il clear non tocca
    nulla e la catena muore. Lo slot è consumato (registro pulito, niente id stantii),
    NIENTE ri-arm, e il marker dirty (P3-6) NON viene rimosso: se il file estraneo un
    giorno sparisce, la recovery d'avvio potrà ancora ripassare il path."""
    a = make_app(running=False, csv_path=None)
    _armati, cancellati = _conta_timer(a)
    p = str(tmp_path / "out.csv")
    a._stop_clear_after_ids = {app_mod.App._stop_clear_key(p): "idX"}
    monkeypatch.setattr(app_mod, "clear_stale_csv",
                        lambda _p, on_mismatch=None: False)          # estraneo: non toccato
    puliti = []
    monkeypatch.setattr(app_mod.dirty_csv_store, "clear_dirty", puliti.append)

    app_mod.App._retry_stop_clear(a, p)

    assert a._stop_clear_after_ids == {}       # slot consumato, nessuna catena viva
    assert _armati == [] and cancellati == []  # niente ri-arm, niente cancel
    assert puliti == []                        # marker P3-6 conservato (non era pulito)


def test_oserror_riarma_e_resta_tracciato(make_app, app_mod, tmp_path, monkeypatch):
    """File ancora lockato (OSError): il ri-arm passa dal registro — la nuova catena
    è tracciata sotto la stessa chiave, senza doppioni."""
    a = make_app(running=False, csv_path=None)
    _armati, cancellati = _conta_timer(a)
    p = str(tmp_path / "out.csv")
    key = app_mod.App._stop_clear_key(p)
    a._stop_clear_after_ids = {key: "idVecchio"}

    def _boom(_p, on_mismatch=None):
        raise OSError("lockato da XTrader")

    monkeypatch.setattr(app_mod, "clear_stale_csv", _boom)
    app_mod.App._retry_stop_clear(a, p)      # firing: pop del proprio slot, poi ri-arm

    assert list(a._stop_clear_after_ids) == [key]              # una sola entry
    assert a._stop_clear_after_ids[key] == "id1"               # il timer NUOVO
    assert cancellati == []       # lo slot era già stato consumato dal firing: niente cancel


def test_on_close_cancella_tutti_gli_id_pendenti():
    """`_on_close` non è esercitabile headless (destroy Tk reale): vincolo sul sorgente
    pinnato (pattern #311) — deve iterare TUTTI i valori del registro, non un id singolo."""
    src = _APP_SRC.read_text(encoding="utf-8")
    corpo = src[src.index("def _on_close"):]
    assert re.search(r"for \w+ in list\(\s*\(self\.__dict__\.get\(\"_stop_clear_after_ids\"\)"
                     r" or \{\}\)\.values\(\)\)", corpo), (
        "app.py/_on_close: deve cancellare TUTTI i retry post-stop pendenti (P3-8 #76)")
    assert re.search(r"_stop_clear_after_id\b", src) is None, (
        "residuo dell'id singolo pre-P3-8: il tracking è ora solo per-path")
