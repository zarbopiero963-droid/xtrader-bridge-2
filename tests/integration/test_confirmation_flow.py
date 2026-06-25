"""Integrazione PR-23: coda + lettore conferme end-to-end (senza GUI).

Riproduce la catena agganciata in `app._process_confirmation`: i segnali attivi
della coda diventano i `pending` per `confirmation_reader.interpret`; su CONFIRMED/
REJECTED il segnale viene rimosso dalla coda (e quindi dal CSV riscritto)."""

from xtrader_bridge import confirmation_reader as cr
from xtrader_bridge import signal_queue as sq


def _row(event, market, selection):
    return {"EventName": event, "MarketName": market, "SelectionName": selection,
            "Price": "1.85", "BetType": "PUNTA"}


def _confirm_against_queue(text, q):
    """Replica la logica pura di app._process_confirmation (senza GUI)."""
    result = cr.interpret(text, q.pending())
    if result.status in (cr.CONFIRMED, cr.REJECTED):
        q.confirm(result.signal_id)
    return result


def test_conferma_rimuove_il_segnale_associato():
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Inter v Milan", "Esito finale", "Inter"), now=1000)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1001)

    res = _confirm_against_queue("Roma v Lazio - Both Teams To Score - Sì piazzata", q)
    assert res.status == cr.CONFIRMED
    # rimosso solo quello confermato; l'altro resta attivo
    assert [r["EventName"] for r in q.active_rows()] == ["Inter v Milan"]


def test_rifiutata_rimuove_il_segnale():
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1000)
    res = _confirm_against_queue("Roma v Lazio - Both Teams To Score - Sì: errore", q)
    assert res.status == cr.REJECTED
    assert q.is_empty()


def test_notifica_di_altra_scommessa_non_tocca_la_coda():
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1000)
    res = _confirm_against_queue("Napoli v Juve - Esito finale - Napoli piazzata", q)
    assert res.status == cr.UNMATCHED
    assert len(q.active_rows()) == 1               # nessuna rimozione a caso


def test_esito_non_chiaro_non_rimuove():
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1000)
    # nomina il segnale ma senza parola d'esito → UNKNOWN, niente rimozione
    res = _confirm_against_queue("Roma v Lazio Both Teams To Score Sì", q)
    assert res.status == cr.UNKNOWN
    assert len(q.active_rows()) == 1


def test_keyword_conferma_dalla_config_viva_live_reload():
    # audit C8: le keyword conferma/rifiuto sono lette dalla config VIVA (in app:
    # `_process_confirmation(..., route_cfg=route)`). Una parola d'esito PERSONALIZZATA
    # classifica come CONFIRMED solo se la config la fornisce: cambiandola a runtime
    # l'effetto è immediato, senza Stop/Start.
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1000)
    text = "Roma v Lazio Both Teams To Score Sì swishato"

    # Config "vecchia" senza la parola custom → esito non chiaro (UNKNOWN), niente rimozione.
    kw_old = cr.normalize_keywords(None)
    res_old = cr.interpret(text, q.pending(), confirm_keywords=kw_old)
    assert res_old.status == cr.UNKNOWN
    assert len(q.active_rows()) == 1

    # Config "viva": l'utente aggiunge "swishato" alle keyword di conferma → CONFIRMED subito.
    kw_live = cr.normalize_keywords(["swishato"])
    res_live = cr.interpret(text, q.pending(), confirm_keywords=kw_live)
    assert res_live.status == cr.CONFIRMED
    q.confirm(res_live.signal_id)
    assert q.is_empty()
