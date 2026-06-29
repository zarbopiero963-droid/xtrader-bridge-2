"""Test del log persistente e dei contatori di stato (PR-14/#11)."""

import os
from datetime import datetime, timedelta

from xtrader_bridge import event_log as el


# ── retention: pulizia log vecchi (PR-3) ─────────────────────────────────────

def _write_day(base, when):
    el.append_entry("riga", base=str(base), when=when)


def test_retention_days_normalizza():
    assert el.retention_days({}) == 0                          # assente → conserva tutto
    assert el.retention_days({"log_retention_days": 5}) == 5
    assert el.retention_days({"log_retention_days": "15"}) == 15
    assert el.retention_days({"log_retention_days": 30}) == 30
    assert el.retention_days({"log_retention_days": 0}) == 0
    assert el.retention_days({"log_retention_days": -3}) == 0  # negativo → 0
    assert el.retention_days({"log_retention_days": 7}) == 0   # fuori menu → 0 (coerente con "Mai")
    assert el.retention_days({"log_retention_days": "boh"}) == 0


def test_purge_old_logs_rimuove_solo_i_vecchi(tmp_path):
    now = datetime(2026, 6, 22, 12, 0, 0)
    for delta in (0, 3, 6, 20):                # 06-22, 06-19, 06-16, 06-02
        _write_day(tmp_path, now - timedelta(days=delta))
    removed = el.purge_old_logs(5, base=str(tmp_path), when=now)   # cutoff 06-17
    assert removed == ["bridge-2026-06-02.log", "bridge-2026-06-16.log"]
    # i recenti restano leggibili
    assert el.read_entries(base=str(tmp_path), when=now) == ["[12:00:00] [INFO] riga"]
    for name in removed:
        assert not os.path.exists(os.path.join(el.log_dir(str(tmp_path)), name))


def test_purge_zero_o_negativo_no_op(tmp_path):
    now = datetime(2026, 6, 22)
    _write_day(tmp_path, now - timedelta(days=100))
    assert el.purge_old_logs(0, base=str(tmp_path), when=now) == []
    assert el.purge_old_logs(-5, base=str(tmp_path), when=now) == []


def test_purge_non_tocca_file_non_log(tmp_path):
    folder = el.log_dir(str(tmp_path))
    os.makedirs(folder, exist_ok=True)
    keep = os.path.join(folder, "appunti.txt")
    with open(keep, "w") as f:
        f.write("non un log")
    _write_day(tmp_path, datetime(2020, 1, 1))
    el.purge_old_logs(5, base=str(tmp_path), when=datetime(2026, 6, 22))
    assert os.path.exists(keep)                # mai cancellati file non-log


def test_clear_all_logs(tmp_path):
    for d in (datetime(2026, 6, 22), datetime(2026, 6, 1)):
        _write_day(tmp_path, d)
    removed = el.clear_all_logs(str(tmp_path))
    assert removed == ["bridge-2026-06-01.log", "bridge-2026-06-22.log"]
    assert el.read_entries(base=str(tmp_path), when=datetime(2026, 6, 22)) == []


WHEN = datetime(2026, 6, 17, 9, 5, 3)


# ── formato e livelli ────────────────────────────────────────────────────────

def test_format_entry():
    assert el.format_entry("ciao", "INFO", WHEN) == "[09:05:03] [INFO] ciao"


def test_normalize_level():
    assert el.normalize_level("error") == "ERROR"
    assert el.normalize_level("  signal ") == "SIGNAL"
    assert el.normalize_level("boh") == "INFO"      # ignoto → default
    assert el.normalize_level(None) == "INFO"


def test_redact_secrets_maschera_token():
    # Un bot token incorporato nel messaggio (es. eccezione) non resta in chiaro.
    token = "123456789:AAExampleSecretTokenValue_abcdef"
    out = el.redact_secrets(f"❌ Errore bot: {token} - fine")
    assert token not in out
    assert "[REDACTED_TOKEN]" in out
    assert out.startswith("❌ Errore bot:")     # resto del messaggio preservato


def test_redact_secrets_lascia_testo_normale():
    assert el.redact_secrets("Inter v Milan q.1.85") == "Inter v Milan q.1.85"
    assert el.redact_secrets("") == ""


# ── #184 M7: redazione per-literal del token registrato (forme non canoniche) ──────

import pytest


@pytest.fixture(autouse=True)
def _clear_secret_registry():
    """Isola il registro dei segreti tra i test (additivo e di modulo)."""
    el.clear_secrets()
    yield
    el.clear_secrets()


def test_register_secret_maschera_token_in_forma_non_canonica():
    """#184 M7: la regex copre solo lo shape canonico `<id>:<20+ char>`. Un token in forma
    NON standard (porzione segreta corta, URL-encoded, spezzata su righe) le sfugge. Registrando
    il token vivo da config con `register_secret`, viene mascherato per-literal in QUALSIASI
    forma compaia.

    Fail-first: senza il registro questi token restavano in chiaro."""
    short = "999:abcDEF12"                         # porzione < 20 char → regex NON matcha
    assert el.redact_secrets(f"err {short} x") == f"err {short} x"   # baseline: la regex non lo prende
    assert el.register_secret(short) is True
    out = el.redact_secrets(f"❌ Errore: {short} - fine")
    assert short not in out and "[REDACTED_TOKEN]" in out
    assert out.startswith("❌ Errore:")

    # URL-encoded: i ':' diventano %3A → la regex non matcha, ma il literal registrato sì.
    enc = "123456789%3AAAtoken_urlencoded_value"
    el.register_secret(enc)
    assert enc not in el.redact_secrets(f"GET /set?token={enc}&x=1")


def test_register_secret_rifiuta_frammenti_banali_e_vuoti():
    """#184 M7: valori vuoti/non-stringa o troppo corti (< 8 char) NON vengono registrati,
    per non mascherare frammenti banali che inquinerebbero i log."""
    for trivial in ("", None, "abc", "1234567"):
        assert el.register_secret(trivial) is False
    # un valore >= 8 char è registrato.
    assert el.register_secret("12345678") is True
    assert "[REDACTED_TOKEN]" in el.redact_secrets("x 12345678 y")


def test_unregister_e_clear_secrets():
    """#184 M7: un segreto rimosso (token cambiato) non viene più mascherato; clear svuota tutto."""
    tok = "SECRETtoken_value_123"
    el.register_secret(tok)
    assert tok not in el.redact_secrets(f"a {tok} b")
    el.unregister_secret(tok)
    assert el.redact_secrets(f"a {tok} b") == f"a {tok} b"   # non più mascherato
    el.register_secret(tok)
    el.clear_secrets()
    assert el.redact_secrets(f"a {tok} b") == f"a {tok} b"


def test_redact_secrets_literal_piu_lungo_prima():
    """#184 M7: i literal più LUNGHI vengono sostituiti prima, così un segreto contenuto in un
    altro non lascia frammenti dell'altro in chiaro."""
    el.register_secret("ABCDEFGH")            # contenuto in quello sotto
    el.register_secret("ABCDEFGHIJKLMNOP")    # più lungo
    out = el.redact_secrets("tok ABCDEFGHIJKLMNOP end")
    assert "ABCDEF" not in out and "[REDACTED_TOKEN]" in out


def test_classify_dal_marker():
    # Lo storico distingue errori/segnali derivando il livello dal marker (#11).
    assert el.classify("❌ CSV non scrivibile") == "ERROR"
    assert el.classify("⚠️ Segnale scartato (custom/NOT_READY)") == "WARNING"
    assert el.classify("📱 Segnale (custom): Inter v Milan") == "SIGNAL"
    assert el.classify("🚀 Bridge avviato!") == "INFO"     # nessun marker noto
    assert el.classify("") == "INFO"
    assert el.classify("   ❌ con spazi iniziali") == "ERROR"   # lstrip


# ── persistenza: append + rilettura (storico dopo restart) ───────────────────

def test_append_e_read_round_trip(tmp_path):
    base = str(tmp_path)
    el.append_entry("avvio", "INFO", base=base, when=WHEN)
    el.append_entry("errore X", "ERROR", base=base, when=WHEN)
    righe = el.read_entries(base=base, when=WHEN)
    assert righe == ["[09:05:03] [INFO] avvio", "[09:05:03] [ERROR] errore X"]


def test_read_entries_file_assente_vuoto(tmp_path):
    assert el.read_entries(base=str(tmp_path), when=WHEN) == []


def test_storico_sopravvive_a_nuova_lettura(tmp_path):
    # Simula il restart: scrivo, poi una "nuova sessione" rilegge lo storico.
    base = str(tmp_path)
    el.append_entry("segnale 1", "SIGNAL", base=base, when=WHEN)
    assert el.read_entries(base=base, when=WHEN) == ["[09:05:03] [SIGNAL] segnale 1"]


def test_log_path_datato(tmp_path):
    p = el.log_path(base=str(tmp_path), when=WHEN)
    assert p.endswith("bridge-2026-06-17.log")
    assert "logs" in p


def test_append_best_effort_non_solleva(tmp_path):
    # base che punta a un file (non una cartella) → makedirs fallisce, ma niente
    # eccezione: la riga è comunque ritornata (best-effort).
    fake = tmp_path / "nondir"
    fake.write_text("x", encoding="utf-8")
    line = el.append_entry("msg", "INFO", base=str(fake / "sub"), when=WHEN)
    assert line == "[09:05:03] [INFO] msg"


# ── filtro per livello ───────────────────────────────────────────────────────

def test_filter_by_level():
    lines = [
        "[09:05:03] [INFO] avvio",
        "[09:05:04] [ERROR] parser fallito",
        "[09:05:05] [SIGNAL] Inter v Milan",
    ]
    assert el.filter_by_level(lines, "ERROR") == ["[09:05:04] [ERROR] parser fallito"]
    assert el.filter_by_level(lines, "INFO") == ["[09:05:03] [INFO] avvio"]
    # il livello passato viene normalizzato (case-insensitive)
    assert el.filter_by_level(lines, "error") == ["[09:05:04] [ERROR] parser fallito"]


def test_filter_non_confonde_messaggio_con_livello():
    # Un messaggio che contiene la parola "ERROR" non deve essere preso come ERROR.
    lines = ["[09:05:03] [INFO] nessun ERROR qui"]
    assert el.filter_by_level(lines, "ERROR") == []


def test_filter_legge_solo_campo_header_non_il_testo():
    # Un tag di livello LETTERALE nel testo non deve far classificare la entry:
    # conta solo il campo header (secondo gruppo tra parentesi dopo il timestamp).
    lines = ["[09:05:03] [INFO] dettaglio: [ERROR] dentro al messaggio"]
    assert el.filter_by_level(lines, "ERROR") == []
    assert el.filter_by_level(lines, "INFO") == lines


def test_entry_level():
    assert el.entry_level("[09:05:03] [SIGNAL] x") == "SIGNAL"
    assert el.entry_level("riga non formattata") is None


def test_format_entry_neutralizza_newline():
    # Un messaggio multiriga deve restare UNA riga fisica (niente entry spezzate
    # né header forgiati).
    line = el.format_entry("Inter v Milan\n[00:00:00] [ERROR] forgiato", "INFO", WHEN)
    assert "\n" not in line
    assert line == "[09:05:03] [INFO] Inter v Milan [00:00:00] [ERROR] forgiato"


def test_append_messaggio_multiriga_resta_una_entry(tmp_path):
    base = str(tmp_path)
    el.append_entry("riga1\nriga2", "INFO", base=base, when=WHEN)
    righe = el.read_entries(base=base, when=WHEN)
    assert len(righe) == 1
    assert righe[0] == "[09:05:03] [INFO] riga1 riga2"


# ── contatori ────────────────────────────────────────────────────────────────

def test_counters():
    c = el.Counters()
    c.record_message("msg1")
    c.record_message("msg2")
    c.record_signal("Inter v Milan")
    c.record_error("CSV non scrivibile")
    assert (c.messages, c.signals, c.errors) == (2, 1, 1)
    assert c.last_message == "msg2"
    assert c.last_signal == "Inter v Milan"
    assert c.last_error == "CSV non scrivibile"


def test_counters_record_senza_testo_non_cambia_ultimo():
    c = el.Counters()
    c.record_signal("primo")
    c.record_signal()                 # incrementa ma non sovrascrive l'ultimo
    assert c.signals == 2
    assert c.last_signal == "primo"
