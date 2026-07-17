"""P3-5 audit #76 — START bloccato se il salvataggio della config è FALLITO.

Bug: `_start` chiamava `_save_config()` senza mai controllare `_save_ok`. Con un save
fallito (permessi/spazio/disco) la sessione partiva su una config solo IN-MEMORY: al
riavvio (o dopo un crash) la recovery del CSV stantio legge la config VECCHIA dal
disco e pulisce il path SBAGLIATO — lasciando potenzialmente una riga stantia viva
sul path davvero usato dalla sessione (rischio doppia scommessa alla riapertura).

Fix: fail-fast subito dopo `cfg = self._save_config()` — `if not self._save_ok:` →
log ❌ e `return`, PRIMA di ogni altro gate e del thread del bot. Vale anche per
l'auto-start (stesso `_start`).

`app.py` non è importabile headless (customtkinter): vincoli STRUTTURALI sul sorgente
pinnato, pattern consolidato del repo (#311)."""

import re
from pathlib import Path

_APP = (Path(__file__).resolve().parents[2] / "xtrader_bridge" / "app.py")


def _start_body():
    src = _APP.read_text(encoding="utf-8")
    start = src.index("def _start(self, auto: bool = False):")
    end = src.index("def _stop", start)
    return src[start:end]


def test_start_verifica_save_ok_subito_dopo_il_save():
    body = _start_body()
    save_idx = body.index("cfg = self._save_config()")
    guard_idx = body.find("if not self._save_ok:", save_idx)
    assert guard_idx != -1, (
        "app.py/_start: manca il fail-fast su _save_ok — con un save fallito la "
        "sessione partirebbe su config solo in-memory (P3-5 #76)")
    # il guard è il PRIMO gate dopo il save: prima di adv_errors/chat-filter/parser.
    for other in ("self._adv_errors", "has_chat_filter", "has_active_parser_config"):
        idx = body.find(other, save_idx)
        assert idx == -1 or idx > guard_idx, (
            f"app.py/_start: il fail-fast su _save_ok deve precedere il gate «{other}»")


def test_guard_save_ok_logga_e_ritorna():
    body = _start_body()
    guard_idx = body.index("if not self._save_ok:")
    ramo = body[guard_idx:guard_idx + 600]
    assert "Salvataggio config FALLITO" in ramo, "manca il log ❌ esplicativo"
    assert re.search(r"^\s*return\s*$", ramo, re.MULTILINE), (
        "app.py/_start: il guard su _save_ok deve fare return (avvio annullato)")
    assert "_bot_thread" not in ramo, "il thread del bot non deve partire nel ramo di errore"


def test_stringa_localizzata_en_es():
    """La stringa del fail-fast deve avere le traduzioni EN/ES (anti-drift i18n)."""
    from xtrader_bridge import i18n
    key = ("❌ Salvataggio config FALLITO: avvio annullato (al riavvio la pulizia del "
           "CSV userebbe la config vecchia su disco). Controlla permessi/spazio del "
           "file config e riprova.")
    body = _start_body()
    assert "Salvataggio config FALLITO: avvio annullato" in body
    for lang in ("EN", "ES"):
        assert key in i18n._CATALOG[lang], f"traduzione {lang} assente per il fail-fast P3-5"
