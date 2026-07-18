"""P3-29 audit #76 — chat_id senza validazione di formato.

Bug: le sorgenti multi-chat e la Chat notifiche XTrader accettavano qualsiasi testo
(`@canale`, nome, spazi interni): l'ID di `effective_chat` negli update Telegram è
sempre NUMERICO, quindi una voce col typo sembrava "configurata" ma non matchava mai —
sorgente silenziosamente morta; per la chat notifiche, conferme XTrader mai ricevute e
segnale attivo fino al timeout, in silenzio.

Fix testato (funzioni PURE, nessun mock):
- `source_manager.is_valid_chat_id`: intero con segno opzionale (regola del Wizard);
- `validate_sources`: chat_id non numerico = errore BLOCCANTE (stesso canale di
  mancante/duplicato/modalità invalida → blocca il Salva del pannello e il fail-fast
  di START);
- `settings_controller.apply_advanced`: Chat notifiche impostata ma non numerica =
  errore bloccante; vuota resta ammessa (= conferme disattivate)."""

import pytest

from xtrader_bridge import settings_controller, source_manager


# ── is_valid_chat_id: la regola pura ─────────────────────────────────────────────────

@pytest.mark.parametrize("valido", ["123", "-100", "-1001234567890", " 42 "])
def test_id_validi(valido):
    assert source_manager.is_valid_chat_id(valido) is True


@pytest.mark.parametrize("invalido", ["", None, "@canale", "Canale VIP", "-100 123",
                                      "--100", "12a3", "1.5", "+39123"])
def test_id_invalidi(invalido):
    assert source_manager.is_valid_chat_id(invalido) is False


# ── validate_sources: errore bloccante sul formato ───────────────────────────────────

def test_sorgente_con_typo_bloccata():
    """FAIL-FIRST: pre-patch `@canaletipster` passava la validazione e la sorgente
    restava "configurata" ma morta (mai un match sugli update numerici)."""
    errors = source_manager.validate_sources(
        [{"name": "Tipster", "chat_id": "@canaletipster", "enabled": True}])
    assert len(errors) == 1
    assert "non numerico" in errors[0] and "@canaletipster" in errors[0]
    assert "-1001234567890" in errors[0]           # l'errore INSEGNA il formato giusto


def test_sorgente_numerica_valida_passa():
    assert source_manager.validate_sources(
        [{"name": "OK", "chat_id": "-1001234567890", "enabled": True}]) == []


def test_formato_non_maschera_gli_altri_errori():
    """Il nuovo ramo si inserisce nella catena esistente senza romperla: mancante e
    duplicato restano rilevati come prima."""
    errors = source_manager.validate_sources([
        {"name": "vuota", "chat_id": "", "enabled": True},
        {"name": "a", "chat_id": "-100", "enabled": True},
        {"name": "b", "chat_id": "-100", "enabled": True},
    ])
    assert any("mancante" in e for e in errors)
    assert any("duplicato" in e for e in errors)


# ── apply_advanced: chat notifiche col typo bloccata, vuota ammessa ──────────────────

def _form(notif):
    """Form valido di base (stesso set di test_settings_controller._valid_form)."""
    return {"recognition_mode": "NAME_ONLY", "queue_mode": "QUEUE_UNTIL_CONFIRMED",
            "require_price": True, "dry_run": True, "max_per_day": "200",
            "confirmation_timeout": "90", "confirmation_keywords": "",
            "rejection_keywords": "", "xtrader_notification_chat_id": notif}


def test_notifiche_typo_errore_bloccante():
    """FAIL-FIRST: pre-patch il typo veniva salvato e le conferme XTrader non
    sarebbero MAI arrivate (segnale attivo fino al timeout, in silenzio)."""
    base, errors = settings_controller.apply_advanced({}, _form("@xtrader_bot"))
    assert any("non numerico" in e and "@xtrader_bot" in e for e in errors)
    assert base.get("xtrader_notification_chat_id") is None   # niente salvato


def test_notifiche_vuota_resta_ammessa():
    """Stringa vuota = conferme disattivate: comportamento storico invariato."""
    base, errors = settings_controller.apply_advanced({}, _form(""))
    assert errors == []
    assert base.get("xtrader_notification_chat_id") == ""


def test_notifiche_numerica_salvata():
    base, errors = settings_controller.apply_advanced({}, _form(" -1009876543210 "))
    assert errors == []
    assert base.get("xtrader_notification_chat_id") == "-1009876543210"
