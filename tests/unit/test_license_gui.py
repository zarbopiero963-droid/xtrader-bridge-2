"""Test hard della schermata Licenza (#140 PR 2).

La costruzione reale dei widget richiede un root Tk → qui si esercita la **logica di attivazione**
(`_evaluate_activation`, `current_status`) su un `self` FINTO, stesso pattern dei meta-test GUI del
repo (`customtkinter` stubbato, nessun widget reale). Più un guard a sorgente sul cablaggio in app.
"""

import importlib
import sys
import types

import pytest

from tests.conftest import LICENSE_TEST_SEED_HEX
from xtrader_bridge import license_status
from xtrader_bridge.licensing import license as lic

# Seed di TEST, dalla fonte unica (regola 3, rilievo CodeRabbit #209).
_TEST_SEED = bytes.fromhex(LICENSE_TEST_SEED_HEX)
_HW = "HW1-1234-5678-9ABC-DEF0"
_NOW = 1_000_000_000
_DAY = 86_400


class _FakeCtkModule(types.ModuleType):
    """Finto `customtkinter`: ogni attributo richiesto è una classe reale vuota."""

    def __getattr__(self, name):
        cls = type(name, (object,), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, cls)
        return cls


@pytest.fixture()
def license_gui(monkeypatch):
    try:
        import customtkinter  # noqa: F401
    except ModuleNotFoundError:
        monkeypatch.setitem(sys.modules, "customtkinter", _FakeCtkModule("customtkinter"))
    monkeypatch.delitem(sys.modules, "xtrader_bridge.license_gui", raising=False)
    return importlib.import_module("xtrader_bridge.license_gui")


def _valid_token(hw=_HW, exp=_NOW + 15 * _DAY, name="Mario Rossi"):
    return lic.build_license(_TEST_SEED, name, hw, _NOW, exp)


def _fake_panel(stored=(None, None), hwid=_HW, now=_NOW):
    """`self` finto coi soli attributi usati dagli handler puri, più un registratore di save."""
    saved = []
    fake = types.SimpleNamespace(
        _hardware_id_provider=lambda: hwid,
        _now_provider=lambda: now,
        _load_state=lambda: stored,
        _save_state=lambda tok, ls: saved.append((tok, ls)),
    )
    return fake, saved


# Dal 2026-07-31 il modulo porta la chiave pubblica REALE del proprietario (#12 PARTE 0). Questo
# file esercita la logica di licenza con una keypair di TEST, quindi qui la chiave "deployata"
# dev'essere quella di test: senza, si verificherebbero firme che nessun test di questo file può
# produrre. Un `pytestmark` invece di una fixture autouse ripetuta in ogni file (rilievo Sourcery):
# una riga sola, e il comportamento non può divergere fra i file.
pytestmark = pytest.mark.usefixtures("chiave_pubblica_di_test")


def test_attivazione_valida_persiste(license_gui):
    fake, saved = _fake_panel()
    out = license_gui.LicensePanel._evaluate_activation(fake, _valid_token())
    assert out["accepted"] is True
    assert "Mario Rossi" in out["message"]
    assert saved == [(_valid_token(), _NOW)]   # persistito con last_seen = now


def test_attivazione_campo_vuoto_non_persiste(license_gui):
    fake, saved = _fake_panel()
    out = license_gui.LicensePanel._evaluate_activation(fake, "")
    assert out["accepted"] is False
    assert saved == []


def test_attivazione_hardware_diverso_rifiutata_non_persiste(license_gui):
    fake, saved = _fake_panel()
    token = _valid_token(hw="HW1-AAAA-BBBB-CCCC-DDDD")
    out = license_gui.LicensePanel._evaluate_activation(fake, token)
    assert out["accepted"] is False
    assert saved == []
    assert "hardware" in out["message"].lower()


def test_attivazione_chiave_malformata_rifiutata(license_gui):
    fake, saved = _fake_panel()
    out = license_gui.LicensePanel._evaluate_activation(fake, "chiave-a-caso")
    assert out["accepted"] is False
    assert saved == []


def test_attivazione_last_seen_monotono_blocca_rollback(license_gui):
    # storico con last_seen nel futuro rispetto a now → CLOCK_ROLLBACK: non accetta, non persiste.
    fake, saved = _fake_panel(stored=("vecchio", _NOW + 5 * _DAY))
    out = license_gui.LicensePanel._evaluate_activation(fake, _valid_token(exp=_NOW + 30 * _DAY))
    assert out["accepted"] is False
    assert saved == []


def test_current_status_da_storico_valido(license_gui):
    fake, _saved = _fake_panel(stored=(_valid_token(), _NOW))
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True


def test_current_status_senza_licenza_e_not_present(license_gui):
    fake, _saved = _fake_panel(stored=(None, None))
    st = license_gui.LicensePanel.current_status(fake)
    assert st.reason == license_status.NOT_PRESENT


def _raising_fake(stored, hwid=_HW, now=_NOW):
    """Fake il cui `_save_state` solleva (disco/permessi simulati)."""
    def _boom(tok, ls):
        raise OSError("disco pieno (simulato)")
    return types.SimpleNamespace(
        _hardware_id_provider=lambda: hwid,
        _now_provider=lambda: now,
        _load_state=lambda: stored,
        _save_state=_boom,
    )


def test_attivazione_persistenza_fallita_non_riuscita(license_gui):
    # CR #144: se save_license solleva (disco/permessi), l'attivazione NON riesce ma NON propaga.
    fake = _raising_fake(stored=(None, None))
    out = license_gui.LicensePanel._evaluate_activation(fake, _valid_token())
    assert out["accepted"] is False
    assert "salvare" in out["message"].lower() or "disco" in out["message"].lower()


def test_current_status_heartbeat_persiste_quando_avanza(license_gui):
    # CR #144: un check valido con orologio AVANZATO registra il heartbeat anti-rollback.
    fake, saved = _fake_panel(stored=(_valid_token(), _NOW - _DAY), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)   # advanced = now


def test_current_status_heartbeat_non_scrive_se_orologio_non_avanza(license_gui):
    # Fable #144: nessun write se l'orologio non è avanzato → niente os.replace concorrenti.
    fake, saved = _fake_panel(stored=(_valid_token(), _NOW), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved == []                                     # nessun heartbeat scritto


def test_current_status_heartbeat_transitorio_non_invalida(license_gui):
    # Fable #144: un lock TRANSITORIO (un solo save fallito) NON invalida una licenza valida.
    fake = _raising_fake(stored=(_valid_token(), _NOW - _DAY), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True                                # sotto soglia: resta valida


def test_current_status_heartbeat_persistente_fail_closed(license_gui):
    # GPT/Fable #144: fallimenti heartbeat PERSISTENTI (≥ soglia) → fail-CLOSED, così non si può
    # negare la scrittura di last_seen per aggirare la scadenza tenendo l'orologio fermo.
    fake = _raising_fake(stored=(_valid_token(), _NOW - _DAY), now=_NOW)
    fake._heartbeat_failures = 0
    last = None
    for _ in range(license_gui._HEARTBEAT_FAIL_LIMIT):
        last = license_gui.LicensePanel.current_status(fake)
    assert last.valid is False
    assert last.reason == license_status.PERSIST_FAILED


def test_current_status_last_seen_corrotto_non_solleva(license_gui):
    # Fable #144: un `last_seen` NON numerico nello stato (corruzione/provider anomalo) non deve
    # far sollevare `int()`/il confronto in current_status → viene trattato come prev=None e il
    # heartbeat riparte da `now` (belt-and-suspenders oltre alla sanificazione di load_license).
    fake, saved = _fake_panel(stored=(_valid_token(), "non-un-numero"), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)   # prev=None → scrive advanced=now


def test_current_status_heartbeat_reset_dopo_write_riuscito(license_gui):
    # GLM #144: un write RIUSCITO azzera il conto dei fallimenti consecutivi, così due lock
    # transitori sparsi (non consecutivi) non sommano fino alla soglia e non fanno fail-closed.
    seq = {"fail": [True, False, True]}   # fallisce, riesce (reset), fallisce → conto = 1, non 2
    calls = {"i": 0}

    def _save(tok, ls):
        i = calls["i"]
        calls["i"] += 1
        if seq["fail"][i]:
            raise OSError("lock transitorio (simulato)")

    fake = types.SimpleNamespace(
        _hardware_id_provider=lambda: _HW, _now_provider=lambda: _NOW,
        _load_state=lambda: (_valid_token(), _NOW - _DAY), _save_state=_save,
        _heartbeat_failures=0)
    r1 = license_gui.LicensePanel.current_status(fake)   # save #0: fail → conto 1
    r2 = license_gui.LicensePanel.current_status(fake)   # save #1: ok   → conto 0
    r3 = license_gui.LicensePanel.current_status(fake)   # save #2: fail → conto 1 (non 2)
    assert r1.valid is True and r2.valid is True and r3.valid is True
    assert fake._heartbeat_failures == 1


def test_current_status_last_seen_lungo_non_inonda_i_log(license_gui, caplog):
    # GPT #144: un `last_seen` non numerico ABNORME (file di stato locale non attendibile) non deve
    # inondare i log: il valore loggato è troncato. La licenza resta valida (prev=None → heartbeat).
    import logging
    fake, saved = _fake_panel(stored=(_valid_token(), "X" * 10_000), now=_NOW)
    with caplog.at_level(logging.WARNING, logger="xtrader_bridge.license_gui"):
        st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)
    warnings = [r.getMessage() for r in caplog.records if "last_seen non numerico" in r.getMessage()]
    assert warnings and all(len(m) < 200 for m in warnings)   # troncato, non 10k caratteri


def test_current_status_last_seen_float_tronca_e_avanza(license_gui):
    # GLM/GPT #144: un `last_seen` float (numerico ma non int) è ammesso via int() (tronca), NON
    # sanizzato a None: resta un timestamp valido e l'heartbeat avanza correttamente.
    fake, saved = _fake_panel(stored=(_valid_token(), float(_NOW - _DAY)), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True
    assert saved and saved[-1] == (_valid_token(), _NOW)   # advanced = now


def test_current_status_last_seen_futuro_come_stringa_numerica_blocca_rollback(license_gui):
    # GPT #144: la sanificazione NON deve diventare un bypass. Un `last_seen` FUTURO ma numerico
    # (qui una STRINGA numerica) è convertibile con int() → NON None → l'anti-rollback lo vede
    # ancora nel futuro → CLOCK_ROLLBACK, licenza non valida, nessun heartbeat scritto.
    fake, saved = _fake_panel(stored=(_valid_token(), str(_NOW + 30 * _DAY)), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is False
    assert st.reason == lic.CLOCK_ROLLBACK
    assert saved == []                                     # nessun bypass: niente scrittura


def test_current_status_orologio_retrocede_rollback(license_gui):
    # GLM #144: caso critico anti-rollback — last_seen nel futuro rispetto a now → CLOCK_ROLLBACK,
    # licenza NON valida e nessun heartbeat scritto.
    fake, saved = _fake_panel(stored=(_valid_token(), _NOW + 30 * _DAY), now=_NOW)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is False
    assert st.reason == lic.CLOCK_ROLLBACK
    assert saved == []


def test_current_status_senza_save_state_non_scrive(license_gui):
    # GLM #144: ramo _save_state=None → nessun heartbeat, nessun crash, stato valido.
    fake = types.SimpleNamespace(
        _hardware_id_provider=lambda: _HW, _now_provider=lambda: _NOW,
        _load_state=lambda: (_valid_token(), _NOW - _DAY), _save_state=None)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is True


def test_current_status_provider_difettoso_stato_neutro(license_gui):
    # Fable #144: un provider che solleva → current_status degrada a stato neutro (non propaga).
    def _boom():
        raise RuntimeError("WMI/registro giù (simulato)")
    fake = types.SimpleNamespace(
        _hardware_id_provider=_boom, _now_provider=lambda: _NOW,
        _load_state=lambda: (None, None), _save_state=lambda *a: None)
    st = license_gui.LicensePanel.current_status(fake)
    assert st.valid is False
    assert st.reason == license_status.NOT_PRESENT


def test_refresh_provider_difettoso_non_propaga(license_gui):
    # Fable #144: di conseguenza refresh_options (che chiama current_status) non si rompe.
    def _boom():
        raise RuntimeError("WMI/registro giù (simulato)")
    fake = types.SimpleNamespace(
        _hardware_id_provider=_boom, _now_provider=lambda: _NOW,
        _load_state=lambda: (None, None), _save_state=lambda *a: None,
        _on_status_change=None)
    fake.current_status = lambda: license_gui.LicensePanel.current_status(fake)
    license_gui.LicensePanel.refresh_options(fake)         # non deve sollevare


def test_refresh_non_inghiotte_errori_del_gate(license_gui):
    # Regressione (review Fable #144): in PR 4 `_on_status_change` sarà il GATE del lock. Un errore
    # nel gate NON deve essere inghiottito silenziosamente (sarebbe fail-OPEN): deve propagare.
    fake, _saved = _fake_panel(stored=(None, None))
    fake.current_status = lambda: license_gui.LicensePanel.current_status(fake)
    fake._on_status_change = lambda _st: (_ for _ in ()).throw(RuntimeError("gate boom"))
    with pytest.raises(RuntimeError):
        license_gui.LicensePanel.refresh_options(fake)


# ── REVOCA VISIBILE NEL PANNELLO (incidente del collaudo 2026-08-03/04 (notte)) ──────────────────────────────────────
#
# Collaudo reale del proprietario: licenza revocata dal fornitore, revoca RILEVATA (il log lo
# prova) e bridge effettivamente bloccato — ma la scheda «🔑 Licenza» continuava a mostrare in
# VERDE «✅ Licenza attiva — … · scade tra 2 giorni». Causa strutturale: `compute_status()` riceve
# solo (token, hardware_id, now, last_seen, public_key_hex) e NON sa nulla della revoca; la scheda
# Licenza è per giunta esclusa apposta dal lock, quindi resta viva e verde.
#
# Conseguenza: l'indicatore principale di un controllo di SICUREZZA diceva l'opposto della verità,
# e il proprietario ne ha ragionevolmente concluso che la revoca non funzionasse.


class _LblSpia:
    """Etichetta che registra l'ultimo `configure()` (testo + colore)."""

    def __init__(self):
        self.text = None
        self.color = None

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]
        if "text_color" in kw:
            self.color = kw["text_color"]


def _fake_panel_render(license_gui, *, revoked_provider=None, exp=_NOW + 15 * _DAY):
    """`self` finto con una LICENZA VALIDA e le etichette spiate, per esercitare `refresh_options`."""
    fake = types.SimpleNamespace(
        _hardware_id_provider=lambda: _HW, _now_provider=lambda: _NOW,
        _load_state=lambda: (_valid_token(exp=exp), None), _save_state=lambda *a: None,
        _on_status_change=None, _hw_value=_LblSpia(), _status_lbl=_LblSpia(),
        _revoked_provider=revoked_provider)
    fake.current_status = lambda: license_gui.LicensePanel.current_status(fake)
    # Il predicato REALE con il fake come `self` (stesso pattern di `current_status` qui sopra):
    # il test esercita il metodo del prodotto, non una sua imitazione.
    fake._revoca_nega = lambda st: license_gui.LicensePanel._revoca_nega(fake, st)
    return fake


def test_il_pannello_NON_dice_attiva_se_la_revoca_nega(license_gui):
    """FAIL-FIRST — il difetto del collaudo 2026-08-03/04 (notte).

    Licenza di per sé valida (firma buona, non scaduta) ma NEGATA dal gate revoca: la scheda non
    deve dire «Licenza attiva». Prima della patch diceva esattamente quello, in verde."""
    fake = _fake_panel_render(license_gui, revoked_provider=lambda: True)
    license_gui.LicensePanel.refresh_options(fake)

    assert "Licenza attiva" not in (fake._status_lbl.text or ""), (
        f"la scheda dice ancora attiva a un REVOCATO: {fake._status_lbl.text!r}")
    assert "REVOCATA" in (fake._status_lbl.text or "").upper(), fake._status_lbl.text
    assert fake._status_lbl.color == license_gui._SEVERITY_COLOR["error"], (
        "un revocato non deve vedere il colore di uno stato sano")


def test_il_pannello_dice_al_revocato_COSA_FARE(license_gui):
    """Uno scarto muto manderebbe l'utente a «riattivare» nella scheda sbagliata: la sua chiave È
    valida, è il fornitore ad averla bloccata. Il rimedio va nominato."""
    fake = _fake_panel_render(license_gui, revoked_provider=lambda: True)
    license_gui.LicensePanel.refresh_options(fake)
    assert "fornitore" in (fake._status_lbl.text or "").lower(), fake._status_lbl.text


def test_licenza_valida_e_NON_revocata_resta_verde(license_gui):
    """CONTRO-GUARDIA: il caso sano non deve cambiare. Un pannello che gridasse «revocata» a chi
    non lo è sarebbe peggio del difetto che sto correggendo."""
    fake = _fake_panel_render(license_gui, revoked_provider=lambda: False)
    license_gui.LicensePanel.refresh_options(fake)
    assert "Licenza attiva" in (fake._status_lbl.text or "")
    assert fake._status_lbl.color == license_gui._SEVERITY_COLOR["ok"]


def test_nessun_provider_revoca_si_comporta_come_prima(license_gui):
    """Retro-compatibilità: un `LicensePanel` costruito senza il seam (test esistenti, altri
    chiamanti) non deve cambiare comportamento."""
    fake = _fake_panel_render(license_gui, revoked_provider=None)
    license_gui.LicensePanel.refresh_options(fake)
    assert "Licenza attiva" in (fake._status_lbl.text or "")


def test_provider_revoca_difettoso_NON_accusa_di_revoca(license_gui):
    """FAIL-SAFE, stessa politica di `_license_bloccata_da_revoca`: in dubbio non si accusa.

    Un provider che solleva non deve né rompere il render né produrre un'accusa di revoca non
    dimostrata — l'unico blocco legittimo è quello provato da una lista firmata."""
    def _boom():
        raise RuntimeError("gate revoca in errore (simulato)")

    fake = _fake_panel_render(license_gui, revoked_provider=_boom)
    license_gui.LicensePanel.refresh_options(fake)          # non deve sollevare
    assert "REVOCATA" not in (fake._status_lbl.text or "").upper(), (
        f"accusa di revoca NON dimostrata: {fake._status_lbl.text!r}")


def test_licenza_gia_invalida_non_viene_mascherata_dalla_revoca(license_gui):
    """Se la licenza è scaduta di suo, il messaggio resta quello della scadenza: la revoca è una
    sovrapposizione su una licenza ALTRIMENTI valida, non un rimpiazzo di ogni diagnosi."""
    fake = _fake_panel_render(license_gui, revoked_provider=lambda: True, exp=_NOW - _DAY)
    license_gui.LicensePanel.refresh_options(fake)
    assert "REVOCATA" not in (fake._status_lbl.text or "").upper(), fake._status_lbl.text
    # …e si asserisce la diagnosi ATTESA, non solo l'assenza dell'altra (rilievo CodeRabbit
    # #235): col solo `not in` il test passerebbe anche se la scadenza fosse sostituita da un
    # testo qualunque — verificherebbe «non dice revocata» invece di «dice scaduta».
    atteso = license_status.status_message(
        license_status.LicenseStatus(valid=False, reason=license_status.EXPIRED, name=None,
                                     issued=None, expiry=None, days_left=0))
    assert fake._status_lbl.text == atteso, (fake._status_lbl.text, atteso)
    assert fake._status_lbl.color == license_gui._SEVERITY_COLOR["error"]


def test_init_REALE_memorizza_il_seam_e_refresh_lo_usa(license_gui, monkeypatch):
    """Chiude l'ultimo anello non coperto (rilievo CodeRabbit sulla PR #235).

    Le altre prove coprono le due metà separate: che l'App **passi** `revoked_provider`
    (`test_license_tab_wiring.py`) e che il pannello lo **consumi** (i test qui sopra, che però
    impostano `_revoked_provider` su un `self` finto). Restava scoperto l'anello in mezzo:
    **`__init__` che memorizza il kwarg**. Se quell'assegnazione sparisse, ogni altro test
    resterebbe VERDE e la revoca tornerebbe invisibile — il difetto originale, di nuovo.

    Qui si esegue il CORPO REALE di `__init__`, lasciando reali anche `_revoca_nega` e
    `refresh_options`. Si neutralizzano solo le due parti che richiedono un display:

    - `_build_ui` — pura costruzione di widget;
    - il `super().__init__` di `CTkFrame`.

    **Il secondo non era neutralizzato nella prima stesura e ha fatto ROSSA la CI** (`unit` e
    `merge-simulation` su `fae13a6`: `TclError: no display name and no $DISPLAY`). La fixture
    `license_gui` inietta il finto `customtkinter` **solo se quello vero manca**: in questo
    ambiente manca perfino `tkinter`, quindi il test girava sempre sul fake ed era verde; sulla
    CI, dove `customtkinter` è installato, `super().__init__` costruiva un `CTkFrame` VERO →
    `Tk()` → nessun display. Patchando la base il test è indipendente da quale dei due è
    presente, che è la proprietà che serve davvero."""
    monkeypatch.setattr(license_gui.LicensePanel, "_build_ui", lambda self: None)
    monkeypatch.setattr(license_gui.ctk.CTkFrame, "__init__",
                        lambda self, *a, **k: None, raising=False)
    chiamate = []

    panel = license_gui.LicensePanel(
        master=None,
        hardware_id_provider=lambda: _HW,
        now_provider=lambda: _NOW,
        load_state=lambda: (_valid_token(), None),
        save_state=lambda *_a: None,
        revoked_provider=lambda: chiamate.append(1) or True)

    assert panel._revoked_provider is not None, (
        "`__init__` non memorizza il seam: la scheda tornerebbe verde a un revocato")

    panel._hw_value, panel._status_lbl = _LblSpia(), _LblSpia()
    panel.refresh_options()

    assert chiamate, "il seam è memorizzato ma `refresh_options` non lo chiama mai"
    assert "REVOCATA" in (panel._status_lbl.text or "").upper(), panel._status_lbl.text
