"""Test della privacy mode dei log (`xtrader_bridge.log_privacy`).

Esercitano la funzione reale `redact_message`: di default il contenuto del
messaggio NON deve finire in chiaro (solo hash + lunghezza + prima riga troncata);
con `full=True` il payload completo torna su una sola riga.
"""

import hashlib

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
