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

    # URL-encoded: registrando il token GREZZO, anche la sua forma encoded (`:`→`%3A`) viene
    # mascherata, perché `redact_secrets` deriva le forme con `_secret_forms` (Codex #184 M7).
    from urllib.parse import quote
    raw = "123456789:AAtoken_urlencoded_value"   # canonico; ':' → '%3A' nell'URL
    enc = quote(raw, safe="")
    assert enc != raw                                            # la codifica cambia davvero
    el.register_secret(raw)                                      # si registra SOLO il grezzo
    assert enc not in el.redact_secrets(f"GET /set?token={enc}&x=1")   # encoded mascherato lo stesso


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


def test_register_grezzo_maschera_la_forma_url_encoded():
    """#184 M7 (Codex P1): `app` registra SOLO il token grezzo. Se nei log compare la sua forma
    URL-encoded (`:`→`%3A`, come in un path `…/bot<token>/…` dentro un'eccezione HTTP), né la
    regex né il match grezzo la riconoscono. `redact_secrets` deve mascherarla comunque derivando
    le forme dal literal registrato.

    Fail-first: senza la derivazione delle forme, registrare il solo grezzo lasciava la forma
    encoded in chiaro."""
    from urllib.parse import quote
    raw = "987654321:LiveBotTokenSecretValue_xyz"
    enc = quote(raw, safe="")
    assert enc != raw
    # baseline: senza registrare nulla, la forma encoded NON è canonica → la regex non la prende.
    assert enc in el.redact_secrets(f"HTTP GET https://api/bot{enc}/getMe")
    el.register_secret(raw)                       # come fa app._register_secret_token: solo grezzo
    out = el.redact_secrets(f"HTTP GET https://api/bot{enc}/getMe failed")
    assert enc not in out and "[REDACTED_TOKEN]" in out


def test_redact_secrets_token_spezzato_su_piu_righe():
    """#203 (Codex): un token registrato può finire WRAPPATO su più righe in un log/traceback
    (`123456789:\\nSecret…`). Un `str.replace` esatto non lo riconoscerebbe; `redact_secrets`
    deve tollerare i CR/LF tra i caratteri.

    Fail-first: prima del fix il match per-literal era `s.replace(sec, ...)` esatto → il token
    spezzato restava in chiaro."""
    raw = "123456789:LiveBotTokenSecretValue_xyz"
    el.register_secret(raw)
    # baseline: su singola riga continua a essere mascherato (retro-compatibile).
    assert raw not in el.redact_secrets(f"tok {raw} end")
    # spezzato da \n (wrapping a larghezza fissa): mascherato lo stesso, nessun frammento in chiaro.
    wrapped_lf = raw[:18] + "\n" + raw[18:]
    out_lf = el.redact_secrets(f"errore: {wrapped_lf} fine")
    assert "LiveBotTokenSecretValue" not in out_lf and "[REDACTED_TOKEN]" in out_lf
    # spezzato da \r\n (CRLF Windows): idem.
    wrapped_crlf = raw[:10] + "\r\n" + raw[10:]
    out_crlf = el.redact_secrets(f"errore: {wrapped_crlf} fine")
    assert "LiveBotTokenSecretValue" not in out_crlf and "[REDACTED_TOKEN]" in out_crlf


def test_redact_secrets_crlf_non_sovra_redige_testo_normale():
    """La tolleranza CR/LF non deve mascherare testo non correlato: senza il segreto in gioco,
    una riga normale resta intatta (zero newline → match identico all'occorrenza esatta)."""
    el.register_secret("123456789:LiveBotTokenSecretValue_xyz")
    testo = "Inter v Milan\nq. 1.85\nsegnale ok"
    assert el.redact_secrets(testo) == testo            # nessun segreto presente → invariato


def test_clear_secrets_non_trattiene_il_segreto_nella_cache_regex():
    """La cache CR/LF non deve trattenere il segreto oltre la sua registrazione: dopo
    `clear_secrets`/`unregister_secret` il valore non compare nelle chiavi della cache e non
    viene più mascherato."""
    # Segreto NON canonico (la regex del token non lo prende): isola il percorso per-literal/cache.
    tok = "AppKeySegretaNonCanonica123"
    el.register_secret(tok)
    el.redact_secrets(f"x {tok} y")                     # popola la cache regex per `tok`
    assert el._crlf_tolerant_re.cache_info().currsize >= 1
    el.clear_secrets()
    assert el._crlf_tolerant_re.cache_info().currsize == 0   # cache svuotata: segreto non trattenuto
    assert el.redact_secrets(f"x {tok} y") == f"x {tok} y"   # non più mascherato


def test_unregister_secret_non_trattiene_il_segreto_nella_cache_regex():
    """Anche `unregister_secret` (token cambiato) deve svuotare la cache CR/LF: il valore non
    resta nelle chiavi della cache e non viene più mascherato (CodeRabbit #251)."""
    tok = "AppKeySegretaNonCanonica123"
    el.register_secret(tok)
    el.redact_secrets(f"x {tok} y")
    assert el._crlf_tolerant_re.cache_info().currsize >= 1
    el.unregister_secret(tok)
    assert el._crlf_tolerant_re.cache_info().currsize == 0
    assert el.redact_secrets(f"x {tok} y") == f"x {tok} y"   # non più mascherato


def test_redact_preview_token_registrato_spezzato_da_crlf_sul_confine():
    """#203 (Codex P1): se un token registrato è wrappato da CR/LF e il budget cade dentro di
    esso, `redact_preview` deve estendere il taglio sull'INTERO token (span CR/LF-tolleranti),
    altrimenti taglierebbe a metà e il prefisso del token finirebbe nell'anteprima.

    Fail-first: con `_secret_spans` basato su `find` esatto, lo span del token wrappato non era
    rilevato → taglio a budget → frammento del token in chiaro nell'anteprima."""
    tok = "123456789:LiveBotTokenSecretValue_xyz"
    el.register_secret(tok)
    wrapped = tok[:20] + "\n" + tok[20:]            # spezzato da \n a metà
    out = el.redact_preview(f"p {wrapped}", 15)     # budget 15: cade DENTRO il token
    assert "123456789:LiveBotTok" not in out        # nessun frammento del token
    assert "LiveBot" not in out
    assert "[REDACTED_TOKEN]" in out


def test_redact_preview_budget_grezzo_e_segreto_sul_confine():
    """#184 M8 P2 (Codex): `redact_preview` rivela al più `budget` char GREZZI, ma maschera per
    intero un segreto che attraversa il confine senza trascinare contenuto oltre il budget."""
    # Segreto fully-in-window: redatto, resto entro budget mostrato.
    assert el.redact_preview("ciao mondo", 40) == "ciao mondo"        # nessun segreto, nessun taglio
    # Token (canonico) di 42 char a inizio + testo privato dopo il confine.
    token = "123456789:AAExampleSecretTokenValue_abcdef"
    out = el.redact_preview(f"{token} SEGRETO_DOPO", 40)
    assert token not in out and "SEGRETO_DOPO" not in out
    assert out == "[REDACTED_TOKEN]"             # solo il placeholder, niente oltre il confine


def test_redact_preview_taglia_a_budget_senza_segreti():
    """#184 M8 P2: senza segreti, `redact_preview` si comporta come un semplice taglio a `budget`
    (comportamento di troncamento originale preservato)."""
    assert el.redact_preview("A" * 60, 40) == "A" * 40
    assert el.redact_preview("breve", 40) == "breve"


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


# ── redazione interna (difesa in profondità, audit #259 D4) ───────────────────

def test_append_entry_redige_internamente_un_token(tmp_path):
    """Audit #259 D4: `append_entry` deve redigere il messaggio da sé (difesa in
    profondità), non fidarsi solo del chiamante — un caller diretto che passasse un
    token Telegram nel messaggio non deve scriverlo in chiaro nel log persistente.

    Fail-first: sul vecchio codice il token finiva in chiaro nel file."""
    # Stesso valore-fake già usato altrove in questo file (non triggera lo scanner).
    token = "123456789:LiveBotTokenSecretValue_xyz"
    when = datetime(2026, 6, 22, 12, 0, 0)
    line = el.append_entry(f"Errore bot: {token}", base=str(tmp_path), when=when)
    assert token not in line
    assert "[REDACTED_TOKEN]" in line
    # anche su disco (non solo nel valore ritornato)
    righe = el.read_entries(base=str(tmp_path), when=when)
    assert righe and token not in righe[0]


def test_append_entry_redige_segreto_registrato(tmp_path):
    """D4: anche un segreto registrato per-literal (non solo la regex token) viene
    mascherato da `append_entry`."""
    secret = "DelayedAppKeyABCDEF"
    assert el.register_secret(secret) is True
    try:
        when = datetime(2026, 6, 22, 12, 0, 0)
        line = el.append_entry(f"chiave {secret} usata", base=str(tmp_path), when=when)
        assert secret not in line and "[REDACTED" in line
    finally:
        el.unregister_secret(secret)


def test_append_entry_idempotente_su_messaggio_gia_redatto(tmp_path):
    """D4: la ri-redazione di un messaggio già pulito dal chiamante (`App._log`) non
    altera il testo normale — nessuna doppia sostituzione osservabile."""
    when = datetime(2026, 6, 22, 12, 0, 0)
    line = el.append_entry("Inter v Milan q.1.85", base=str(tmp_path), when=when)
    assert line == "[12:00:00] [INFO] Inter v Milan q.1.85"
