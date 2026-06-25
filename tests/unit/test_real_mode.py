"""Test della logica UX della modalità REALE (`xtrader_bridge.real_mode`).

Logica pura, headless: conferma alla transizione sim→reale, frase di conferma,
testo del banner persistente, evento di audit ed estrazione per l'export.
"""

from xtrader_bridge import real_mode as rm

SIM = {"dry_run": True}
REAL = {"dry_run": False}


def test_requires_confirmation_solo_su_transizione_sim_to_real():
    assert rm.requires_confirmation(SIM, REAL) is True       # sim → reale: conferma
    assert rm.requires_confirmation(REAL, REAL) is False     # già reale: niente conferma
    assert rm.requires_confirmation(SIM, SIM) is False       # resta sim
    assert rm.requires_confirmation(REAL, SIM) is False      # reale → sim: niente conferma


def test_requires_confirmation_default_sim_quando_campo_assente():
    # Config senza `dry_run` = simulazione (default sicuro). Passare a reale chiede conferma.
    assert rm.requires_confirmation({}, REAL) is True
    assert rm.requires_confirmation({}, {}) is False


def test_confirmation_ok():
    assert rm.confirmation_ok("REALE") is True
    assert rm.confirmation_ok("reale") is True               # case-insensitive
    assert rm.confirmation_ok("  Reale  ") is True           # trim
    assert rm.confirmation_ok("REAL") is False               # parola sbagliata
    assert rm.confirmation_ok("") is False
    assert rm.confirmation_ok(None) is False                 # dialog annullato


def test_banner_text_solo_in_reale():
    assert rm.banner_text(SIM) is None                       # simulazione → niente banner
    assert rm.banner_text({}) is None                        # default sim
    txt = rm.banner_text(REAL)
    assert txt is not None and "REALE" in txt.upper()


def test_banner_active_segue_config_viva_e_sessione():
    # Config viva in reale → banner attivo (a prescindere dalla sessione).
    assert rm.banner_active(REAL) is True
    assert rm.banner_active(REAL, session_active=False, session_real=False) is True
    # Config viva in simulazione e nessuna sessione reale → niente banner.
    assert rm.banner_active(SIM) is False
    assert rm.banner_active(SIM, session_active=True, session_real=False) is False
    # Codex P1: config viva tornata in simulazione MA sessione partita in reale e ancora
    # attiva → il banner DEVE restare (il betting reale è ancora in corso fino a STOP).
    assert rm.banner_active(SIM, session_active=True, session_real=True) is True
    # Sessione reale ma non più attiva (STOP) → segue la config viva (sim) → niente banner.
    assert rm.banner_active(SIM, session_active=False, session_real=True) is False


def test_audit_lines_with_date_antepone_la_data_dal_nome_file():
    log = (f"[10:00:01] {rm.AUDIT_MARKER}: attivata ...\n"
           "[10:01:00] altro\n"
           f"[11:00:00] {rm.AUDIT_MARKER}: attivata ...\n")
    out = rm.audit_lines_with_date("bridge-2026-06-25.log", log)
    assert len(out) == 2
    assert all(ln.startswith("[2026-06-25] ") for ln in out)   # data dal nome file
    assert all(rm.AUDIT_MARKER in ln for ln in out)
    # Nome senza data riconoscibile → usa il nome file come prefisso (non crasha).
    out2 = rm.audit_lines_with_date("strano.log", log)
    assert out2 and out2[0].startswith("[strano.log] ")


def test_enabled_message_contiene_marker():
    msg = rm.enabled_message()
    assert rm.AUDIT_MARKER in msg
    assert "reali" in msg.lower()


def test_extract_audit_lines():
    log = (
        "[10:00:00] 🚀 Bridge avviato!\n"
        f"[10:00:01] ⚠️ {rm.AUDIT_MARKER}: modalità REALE attivata (confermata) — ...\n"
        "[10:01:00] 📱 Segnale: ...\n"
        f"[11:00:00] {rm.AUDIT_MARKER}: modalità REALE attivata (confermata) — ...\n"
    )
    out = rm.extract_audit_lines(log)
    assert len(out) == 2
    assert all(rm.AUDIT_MARKER in ln for ln in out)
    assert "🚀 Bridge avviato" not in "\n".join(out)         # solo le righe di audit
    assert rm.extract_audit_lines("") == []
    assert rm.extract_audit_lines(None) == []
