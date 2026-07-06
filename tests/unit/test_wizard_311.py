"""Test hard del Wizard di prima configurazione (#311 §3.4) — `wizard` puro.

Sonde Telegram SEMPRE iniettate (mai live in CI); invariante chiave: il token non
compare MAI negli esiti, nemmeno quando la sonda esplode con l'URL nel messaggio."""

import urllib.error

import pytest

from xtrader_bridge import bridge_mode as bm
from xtrader_bridge import health_check as hc
from xtrader_bridge import parser_builder as pb
from xtrader_bridge import wizard

TOK = "123456:SEGRETISSIMO-abcDEF"


# ── step 1: token ─────────────────────────────────────────────────────────────

def test_check_token_ok_e_username():
    res = wizard.check_token(TOK, probe=lambda t: {"ok": True,
                                                   "result": {"username": "mio_bot"}})
    assert res.ok and "@mio_bot" in res.message


def test_check_token_fail_closed_vuoto_rifiutato_malformato():
    assert wizard.check_token("").ok is False
    assert wizard.check_token(TOK, probe=lambda t: {"ok": False}).ok is False
    assert wizard.check_token(TOK, probe=lambda t: "garbage").ok is False


def test_check_token_errore_sonda_sanificato_senza_token():
    def boom(_t):
        raise urllib.error.URLError(f"https://api.telegram.org/bot{TOK}/getMe")
    res = wizard.check_token(TOK, probe=boom)
    assert res.ok is False
    assert TOK not in res.message and "SEGRETISSIMO" not in res.message
    assert "rete" in res.message


def test_check_token_http_401_suggerisce_token_errato():
    def unauthorized(_t):
        raise urllib.error.HTTPError(f"url/{TOK}", 401, "Unauthorized", {}, None)
    res = wizard.check_token(TOK, probe=unauthorized)
    assert res.ok is False and "401" in res.message and TOK not in res.message


def test_call_telegram_token_percent_encoded_nel_path(monkeypatch):
    """CodeRabbit #354: caratteri spuri da incolla malformato (#, ?, /, spazi) non
    troncano/deviano l'URL; `:` resta letterale (un token VALIDO non cambia URL)."""
    visto = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return b'{"ok": true, "result": {}}'

    monkeypatch.setattr(
        wizard.urllib.request, "urlopen",
        lambda url, timeout=None: visto.update(url=url, timeout=timeout) or _Resp())
    assert wizard._call_telegram("123:AB#C?D/e f", "getMe") == {"ok": True, "result": {}}
    assert "/bot123:AB%23C%3FD%2Fe%20f/getMe" in visto["url"]   # spuri encodati, ':' intatto
    assert visto["timeout"] == wizard._TIMEOUT
    wizard._call_telegram(TOK, "getMe")
    assert f"/bot{TOK}/getMe" in visto["url"]                   # token valido: URL identico


# ── step 2: chat + messaggio di prova ────────────────────────────────────────

def _updates(chat_id, text="P.Bet segnale\nriga2"):
    return {"ok": True, "result": [
        {"message": {"chat": {"id": 999}, "text": "altro"}},
        {"channel_post": {"chat": {"id": chat_id}, "text": text}},
    ]}


def test_check_chat_trova_il_messaggio_della_chat_giusta():
    res = wizard.check_chat(TOK, "-100123", probe=lambda t: _updates(-100123))
    assert res.ok and "-100123" in res.message and "P.Bet segnale" in res.message
    assert res.data["text"].startswith("P.Bet")


def test_check_chat_fail_closed():
    assert wizard.check_chat(TOK, "").ok is False
    assert wizard.check_chat(TOK, "abc").ok is False                    # non numerico
    res = wizard.check_chat(TOK, "-100123", probe=lambda t: _updates(42))
    assert res.ok is False and "Nessun messaggio" in res.message        # chat diversa
    assert wizard.check_chat(TOK, "-100123",
                             probe=lambda t: {"ok": False}).ok is False


def test_check_chat_errore_sonda_sanificato():
    def boom(_t):
        raise RuntimeError(f"token={TOK}")
    res = wizard.check_chat(TOK, "-100123", probe=boom)
    assert res.ok is False and TOK not in res.message


# ── step 3: parser su messaggio reale (riusa il tester #350) ─────────────────

def _builder():
    b = pb.ParserBuilder()
    b.name = "Wiz"
    b.mode = "NAME_ONLY"
    b.add_rule(target="Provider", fixed_value="PBet")
    b.add_rule(target="EventName", start_after="🆚", end_before="\n", required=True)
    b.add_rule(target="Price", fixed_value="1.50", required=True)
    b.add_rule(target="BetType", fixed_value="PUNTA", required=True)
    b.add_rule(target="MarketType", fixed_value="MATCH_ODDS", required=True)
    b.add_rule(target="SelectionName", fixed_value="Casa", required=True)
    return b


def test_check_parser_valido_e_scartato():
    ok = wizard.check_parser(_builder(), "x\n🆚Inter v Milan\n⌚ 1m")
    assert ok.ok and ok.message.startswith("✅") and ok.data["rows"]
    ko = wizard.check_parser(_builder(), "ciao come va")
    assert ko.ok is False and "⛔" in ko.message      # motivo esatto nel verdetto
    assert wizard.check_parser(_builder(), "  ").ok is False


# ── step 4: csv_path + scrittura di prova ────────────────────────────────────

def test_check_csv_percorso_e_scrittura_di_prova(tmp_path):
    p = tmp_path / "segnali.csv"
    pre = wizard.check_csv(str(p))
    assert pre.ok and "Scrivi CSV di prova" in pre.message
    done = wizard.check_csv(str(p), do_write=True)
    assert done.ok and p.exists()
    header = p.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.replace('"', "").startswith("Provider,")


def test_check_csv_file_estraneo_rifiutato_e_intatto(tmp_path):
    # File ESTRANEO (header diverso dal contratto): rifiuto + contenuto INTATTO.
    p = tmp_path / "segnali.csv"
    p.write_text("FILE UTENTE - NON TOCCARE", encoding="utf-8")
    res = wizard.check_csv(str(p), do_write=True)
    assert res.ok is False and "NON è un CSV del bridge" in res.message
    assert p.read_text(encoding="utf-8") == "FILE UTENTE - NON TOCCARE"


def test_check_csv_riga_attiva_protetta(tmp_path):
    # CSV del bridge CON riga attiva: non toccato (anti doppia scommessa), esito ok.
    from xtrader_bridge.csv_writer import CSV_HEADER, write_rows
    p = tmp_path / "segnali.csv"
    row = dict.fromkeys(CSV_HEADER, "")
    row.update({"Provider": "PBet", "EventName": "Inter v Milan", "Price": "1.85",
                "BetType": "PUNTA", "MarketType": "MATCH_ODDS",
                "SelectionName": "Inter", "Handicap": "0"})
    write_rows([row], str(p))
    prima = p.read_bytes()
    res = wizard.check_csv(str(p), do_write=True)
    assert res.ok and "riga ATTIVA" in res.message and "NON lo tocco" in res.message
    assert p.read_bytes() == prima


def test_check_csv_fail_closed_su_percorso_rosso(tmp_path):
    assert wizard.check_csv("").ok is False
    assert wizard.check_csv(str(tmp_path)).ok is False            # è una cartella
    assert wizard.check_csv(str(tmp_path / "no" / "x.csv")).ok is False


# ── step 5: checklist finale ─────────────────────────────────────────────────

def test_final_checklist_stati(tmp_path):
    csv = tmp_path / "segnali.csv"
    cfg = {"bot_token": TOK, "chat_id": "-100123", "csv_path": str(csv),
           "dry_run": True, "bridge_mode": "SIMULAZIONE"}
    items = dict((label, ok) for ok, label in wizard.final_checklist(
        cfg, parser_active=True))
    assert all(items.values())
    # reale attivo → l'ultima voce va a False (il wizard NON tocca la modalità)
    cfg2 = dict(cfg, dry_run=False, bridge_mode="REALE")
    voci = wizard.final_checklist(cfg2, parser_active=False)
    stato = {label: ok for ok, label in voci}
    assert stato["Parser Personalizzato attivo (richiesto dallo START)"] is False
    assert any(("Simulazione" in label and not ok) for ok, label in voci)
    # cfg vuota → tutto False tranne nulla
    assert not any(ok for ok, _ in wizard.final_checklist({}, parser_active=False)[:4])
