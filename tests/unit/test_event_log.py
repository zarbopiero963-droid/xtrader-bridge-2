"""Test del log persistente e dei contatori di stato (PR-14/#11)."""

from datetime import datetime

from xtrader_bridge import event_log as el


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
