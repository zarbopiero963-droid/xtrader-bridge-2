"""Test della privacy mode dei log (`xtrader_bridge.log_privacy`).

Esercitano la funzione reale `redact_message`: di default il contenuto del
messaggio NON deve finire in chiaro (solo hash + lunghezza + prima riga troncata);
con `full=True` il payload completo torna su una sola riga.
"""

import hashlib

from xtrader_bridge import event_log
from xtrader_bridge import log_privacy as lp


def test_redatto_di_default_non_espone_il_contenuto():
    text = "Match: Inter v Milan\nEsito: GG\nQuota: 1,85\nNOTA SEGRETA: stake 500"
    out = lp.redact_message(text)               # full=False di default
    # Hash corretto (primi 12 hex dello sha256) e lunghezza esatta.
    expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    assert f"sha256:{expected_hash}" in out
    assert f"{len(text)} char" in out
    # La 2ª riga e oltre (contenuto sensibile) NON devono comparire.
    assert "Esito: GG" not in out
    assert "NOTA SEGRETA" not in out
    assert "stake 500" not in out
    # Una sola riga (nessun a-capo nel log).
    assert "\n" not in out


def test_prima_riga_troncata_con_ellissi():
    first = "A" * (lp.FIRSTLINE_CHARS + 20)
    out = lp.redact_message(first + "\nseconda riga")
    assert "A" * lp.FIRSTLINE_CHARS in out       # mostrati FIRSTLINE_CHARS caratteri
    assert "A" * (lp.FIRSTLINE_CHARS + 1) not in out   # non di più
    assert "…" in out                            # ellissi perché troncata
    assert "seconda riga" not in out


def test_prima_riga_corta_senza_ellissi():
    out = lp.redact_message("ciao")
    assert "ciao" in out
    assert "…" not in out


def test_full_true_ritorna_il_payload_completo_su_una_riga():
    text = "riga1\nriga2\nriga3"
    out = lp.redact_message(text, full=True)
    assert out == "riga1 riga2 riga3"            # a-capo compressi in spazi
    assert "[redatto" not in out


def test_hash_stabile_per_stesso_input():
    a = lp.redact_message("stesso messaggio")
    b = lp.redact_message("stesso messaggio")
    assert a == b


def test_none_e_vuoto():
    assert "0 char" in lp.redact_message(None)
    assert "0 char" in lp.redact_message("")
    assert lp.redact_message("", full=True) == ""
    assert lp.redact_message(None, full=True) == ""


def test_non_stringa_trattata_come_stringa():
    out = lp.redact_message(12345)
    assert "char" in out                         # non solleva, coerce a str


# ── #184 M8: il prefisso/payload passano da redact_secrets (no token in chiaro) ──────

def test_token_a_inizio_messaggio_non_in_chiaro_nel_prefisso():
    """#184 M8: un bot token nei primi caratteri della prima riga NON deve finire in chiaro nel
    prefisso "privacy on". Era il path di leak più concreto dell'audit.

    Fail-first: prima il prefisso era `first[:40]` grezzo → il token compariva in chiaro."""
    token = "123456789:AAExampleSecretTokenValue_abcdef"   # shape canonico → redact_secrets lo prende
    out = lp.redact_message(f"{token} resto del messaggio")
    assert token not in out
    assert "[REDACTED_TOKEN]" in out
    assert out.startswith("[redatto:")            # forma redatta preservata


def test_token_full_true_non_in_chiaro():
    """#184 M8: anche il payload completo di debug (`full=True`) passa da redact_secrets."""
    token = "987654321:AAanotherSecretTokenValue_xyz123"
    out = lp.redact_message(f"errore bot: {token}", full=True)
    assert token not in out and "[REDACTED_TOKEN]" in out
    assert "\n" not in out                        # resta una sola riga


def test_token_sul_confine_del_troncamento_non_trapela_a_meta():
    """#184 M8: un token che attraversa il confine dei FIRSTLINE_CHARS non deve trapelare tagliato
    a metà. Si redige PRIMA di troncare, quindi nessun frammento del token resta visibile.

    Fail-first: troncando prima di redarre, `first[:40]` conteneva una porzione grezza del token."""
    prefix = "X" * 30                              # spinge il token a cavallo del 40° char
    token = "123456789:AAExampleSecretTokenValue_abcdef"
    out = lp.redact_message(f"{prefix}{token} coda")
    # Nessuna porzione del segreto deve restare visibile (né la fetta a cavallo del confine).
    assert token not in out
    for start in range(0, len(token) - 7):         # nessun run contiguo di >= 8 char del token
        assert token[start:start + 8] not in out
    # La redazione è avvenuta sul confine: appare (anche solo l'inizio del) marker, mai il token.
    assert "[REDACT" in out


def test_registrato_literal_non_canonico_redatto_nel_prefisso():
    """#184 M8 + M7: un token registrato in forma NON canonica (che la regex non prende) è comunque
    mascherato nel prefisso, perché redact_secrets usa anche il registro per-literal."""
    short = "555:shortSecret"                       # porzione < 20 → la regex NON matcha
    event_log.clear_secrets()
    try:
        assert short in lp.redact_message(f"{short} testo")          # baseline: non registrato → resta
        event_log.register_secret(short)
        out = lp.redact_message(f"{short} testo")
        assert short not in out and "[REDACTED_TOKEN]" in out
    finally:
        event_log.clear_secrets()
