"""Test hard del pannello Salute a semafori (#311 §3.3) — `health_check` puro.

Fail-safe onesto: dato assente = MAI verde per default; la sonda CSV non apre mai
il file (nessun lock che disturbi XTrader); la modalità usa la semantica di rischio
dei banner (#311 §3.1)."""

import os
import stat

import pytest

from xtrader_bridge import bridge_mode as bm
from xtrader_bridge import health_check as hc


def _by_key(items):
    return {i.key: i for i in items}


def test_evaluate_default_tutto_fermo_niente_verde_gratuito():
    d = _by_key(hc.evaluate())
    assert d["telegram"].state == hc.RED and "AVVIA" in d["telegram"].detail
    assert d["message"].state == hc.YELLOW
    assert d["parser"].state == hc.RED and "bloccato" in d["parser"].detail
    assert d["signal"].state == hc.YELLOW
    assert d["csv"].state == hc.RED
    assert d["confirmation"].state == hc.YELLOW and "non attive" in d["confirmation"].detail
    assert d["mode"].state == hc.GREEN            # fail-closed: default Simulazione
    assert [i.key for i in hc.evaluate()] == [
        "telegram", "message", "parser", "signal", "csv", "confirmation", "mode"]


def test_evaluate_operativo_tutto_verde():
    d = _by_key(hc.evaluate(
        listener_status="⬤  ATTIVO", last_message="P.Bet…", parser_active=True,
        last_signal="Inter v Milan @1.85", csv_state=hc.GREEN, csv_detail="ok",
        confirmations_enabled=True, last_confirmation="CONFERMATO @ 10:00:00",
        mode=bm.SIMULAZIONE))
    assert all(d[k].state == hc.GREEN for k in
               ("telegram", "message", "parser", "signal", "csv", "confirmation", "mode"))


def test_evaluate_riconnessione_gialla_e_motivo_errore_visibile():
    d = _by_key(hc.evaluate(listener_status="⬤  RICONNESSIONE…",
                            last_error="rete: timeout"))
    assert d["telegram"].state == hc.YELLOW
    # Nessun segnale ma errore recente: il MOTIVO è mostrato, mai nascosto.
    assert d["signal"].state == hc.YELLOW and "rete: timeout" in d["signal"].detail


def test_evaluate_conferme_attive_senza_esito_gialle():
    d = _by_key(hc.evaluate(confirmations_enabled=True))
    assert d["confirmation"].state == hc.YELLOW
    assert "nessuna conferma" in d["confirmation"].detail


def test_evaluate_modalita_semantica_di_rischio():
    assert _by_key(hc.evaluate(mode=bm.COLLAUDO))["mode"].state == hc.YELLOW
    assert _by_key(hc.evaluate(mode=bm.REALE))["mode"].state == hc.RED
    m = _by_key(hc.evaluate(mode="garbage"))["mode"]     # fail-closed → Simulazione
    assert m.state == hc.GREEN and m.detail == bm.label_for(bm.SIMULAZIONE)


# ── csv_writable: sonda non invasiva ─────────────────────────────────────────

def test_csv_writable_file_esistente_e_da_creare(tmp_path):
    # `platform="posix"` INIETTATO (API Fable #351): il ramo verde-verificabile è POSIX,
    # quindi lo esercitiamo in modo deterministico su QUALSIASI runner (su windows-latest,
    # senza iniezione, os.name=="nt" darebbe GIALLO onesto → esito dipendente dall'OS del
    # runner). Il ramo Windows YELLOW è coperto da `test_csv_writable_windows_giallo_onesto`.
    p = tmp_path / "segnali.csv"
    stato, motivo = hc.csv_writable(str(p), platform="posix")
    assert stato == hc.GREEN and "verrà creato" in motivo    # cartella scrivibile
    p.write_text("x", encoding="utf-8")
    stato, motivo = hc.csv_writable(str(p), platform="posix")
    assert stato == hc.GREEN and "scrivibile" in motivo      # POSIX: verificabile
    # NON invasiva: il contenuto non è stato toccato dalla sonda.
    assert p.read_text(encoding="utf-8") == "x"


def test_csv_writable_windows_giallo_onesto(tmp_path):
    # Fable #351: su NTFS os.access ignora ACL/lock (es. XTrader col file aperto) →
    # un verde sarebbe FALSO. Con file esistente su Windows la sonda si ferma a GIALLO.
    # `platform` INIETTABILE (GLM #351: monkeypatch del globale os.name rompeva
    # perfino la failure-repr di pytest): niente stato globale toccato.
    p = tmp_path / "segnali.csv"
    p.write_text("x", encoding="utf-8")
    stato, motivo = hc.csv_writable(str(p), platform="nt")
    assert stato == hc.YELLOW and "Windows" in motivo
    # Coerenza (Fugu #351): anche il ramo «file da creare» su Windows si ferma a
    # GIALLO — os.access sulla CARTELLA soffre delle stesse ACL NTFS non rilevabili.
    stato2, motivo2 = hc.csv_writable(str(tmp_path / "nuovo.csv"), platform="nt")
    assert stato2 == hc.YELLOW and "Windows" in motivo2
    # I casi rossi restano rossi anche su Windows.
    assert hc.csv_writable("", platform="nt")[0] == hc.RED
    assert hc.csv_writable(str(tmp_path), platform="nt")[0] == hc.RED
    # FAIL-CLOSED sul platform (Fable #353): un valore sconosciuto/sporco NON guadagna
    # il verde POSIX — resta al giallo onesto su entrambi i rami.
    assert hc.csv_writable(str(p), platform="java")[0] == hc.YELLOW
    assert hc.csv_writable(str(tmp_path / "nuovo.csv"), platform="")[0] == hc.YELLOW


def test_evaluate_csv_state_sporco_fail_closed():
    assert _by_key(hc.evaluate(csv_state="garbage"))["csv"].state == hc.RED


def test_csv_writable_casi_rossi(tmp_path):
    assert hc.csv_writable("") == (hc.RED, "csv_path non configurato")
    assert hc.csv_writable(None)[0] == hc.RED
    stato, motivo = hc.csv_writable(str(tmp_path))       # è una cartella
    assert stato == hc.RED and "cartella, non un file" in motivo
    stato, motivo = hc.csv_writable(str(tmp_path / "no" / "segnali.csv"))
    assert stato == hc.RED and "inesistente" in motivo


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="permessi POSIX non applicabili (Windows/root)")
def test_csv_writable_file_non_scrivibile(tmp_path):
    p = tmp_path / "segnali.csv"
    p.write_text("x", encoding="utf-8")
    p.chmod(stat.S_IRUSR)
    try:
        stato, motivo = hc.csv_writable(str(p))
        assert stato == hc.RED and "NON scrivibile" in motivo
    finally:
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
