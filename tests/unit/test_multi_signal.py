"""Test della logica UX multi-segnale (`xtrader_bridge.multi_signal`) — pura, headless."""

from xtrader_bridge import multi_signal as ms

OVERWRITE = {"queue_mode": "OVERWRITE_LAST"}
APPEND = {"queue_mode": "APPEND_ACTIVE"}
QUEUE = {"queue_mode": "QUEUE_UNTIL_CONFIRMED"}


def test_is_multi_mode():
    assert ms.is_multi_mode("OVERWRITE_LAST") is False
    assert ms.is_multi_mode("APPEND_ACTIVE") is True
    assert ms.is_multi_mode("QUEUE_UNTIL_CONFIRMED") is True
    assert ms.is_multi_mode(None) is False         # ignoto → default (overwrite)
    assert ms.is_multi_mode("boh") is False


def test_requires_warning_solo_su_transizione_a_multi():
    assert ms.requires_warning(OVERWRITE, APPEND) is True       # 1-riga → multi: warning
    assert ms.requires_warning(OVERWRITE, QUEUE) is True
    assert ms.requires_warning(APPEND, QUEUE) is False          # multi → multi: no warning
    assert ms.requires_warning(APPEND, OVERWRITE) is False      # multi → 1-riga: no warning
    assert ms.requires_warning(OVERWRITE, OVERWRITE) is False
    assert ms.requires_warning({}, APPEND) is True              # default (overwrite) → multi


def test_warning_text_contiene_il_tetto():
    txt = ms.warning_text(2)
    assert "2" in txt and "MULTI" in txt.upper()


def test_active_count_text():
    assert ms.active_count_text(0, 2) == "Righe attive: 0/2"
    assert ms.active_count_text(3, 2) == "Righe attive: 3/2"   # mostra anche se oltre (diagnostica)
    assert ms.active_count_text(1, 0) == "Righe attive: 1"     # tetto 0 → senza /M
    assert ms.active_count_text(1, "x") == "Righe attive: 1"   # tetto non numerico → senza /M


def test_blocked_message_contiene_il_tetto():
    msg = ms.blocked_message(2)
    assert "2" in msg and "bloccato" in msg.lower()
