"""Integrazione PR-23: coda + lettore conferme end-to-end (senza GUI).

Riproduce la catena agganciata in `app._process_confirmation`: i segnali attivi
della coda diventano i `pending` per `confirmation_reader.interpret`; su CONFIRMED/
REJECTED il segnale viene rimosso dalla coda (e quindi dal CSV riscritto)."""

import csv

from xtrader_bridge import confirmation_reader as cr
from xtrader_bridge import csv_writer as cw
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


def _confirm_then_write(text, q, path, *, running=True, writer=None):
    """Replica la SEQUENZA di app._process_confirmation includendo la scrittura CSV:
    gate STOP → interpret → `confirm` (rimuove dalla coda PRIMA di scrivere) →
    `write_rows(active_rows())`. `writer` può sollevare per simulare un CSV lockato da
    XTrader (la write è atomica: se fallisce il CSV precedente resta intatto). Ritorna
    il result, o ``None`` se STOP (running=False) → nessuna riscrittura (Codex P2)."""
    writer = writer or cw.write_rows
    if not running:
        return None
    result = cr.interpret(text, q.pending())
    if result.status in (cr.CONFIRMED, cr.REJECTED):
        q.confirm(result.signal_id)
        try:
            writer(q.active_rows(), path)   # può sollevare (CSV lockato)
        except Exception:                   # noqa: BLE001 — come app: errore a log, retry schedulato
            pass
    return result


def _events_in_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [r["EventName"] for r in rows]


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


# ── audit #105 P2: conferma + fallimento scrittura CSV → retry converge ───────

def test_retry_dopo_write_fallita_converge_alle_righe_residue(tmp_path):
    # Replica il percorso critico di app._process_confirmation (audit #105 P2):
    # conferma ricevuta → segnale rimosso dalla coda → write_rows FALLISCE (CSV lockato) →
    # il segnale è già fuori dalla coda ma la riga è ancora nel CSV → il RETRY riscrive le
    # righe residue derivate dalla coda (già svuotata), facendo sparire il segnale confermato.
    p = str(tmp_path / "segnali.csv")
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Inter v Milan", "Esito finale", "Inter"), now=1000)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1001)
    cw.write_rows(q.active_rows(), p)                  # CSV iniziale: entrambi i segnali
    assert _events_in_csv(p) == ["Inter v Milan", "Roma v Lazio"]

    # Conferma "Inter" ma la scrittura CSV fallisce (lock simulato): la write atomica
    # non tocca il file, quindi il CSV resta com'era (entrambe le righe).
    def _boom(rows, path):
        raise OSError("CSV lockato da XTrader (simulato)")

    res = _confirm_then_write("Inter v Milan - Esito finale - Inter piazzata", q, p, writer=_boom)
    assert res.status == cr.CONFIRMED
    # La coda ha già rimosso "Inter" (mutata PRIMA della scrittura)...
    assert [r["EventName"] for r in q.active_rows()] == ["Roma v Lazio"]
    # ...ma il CSV (write fallita) contiene ancora entrambe: riga stantia da ripulire.
    assert _events_in_csv(p) == ["Inter v Milan", "Roma v Lazio"]

    # RETRY (scrittura ok): riscrive le righe residue della coda → resta solo "Roma".
    cw.write_rows(q.active_rows(), p)
    assert _events_in_csv(p) == ["Roma v Lazio"]


def test_nessuna_riscrittura_dopo_stop(tmp_path):
    # Codex P2 / audit #105: dopo lo STOP (running=False) una conferma NON deve riscrivere
    # il CSV (che lo STOP ha già svuotato) né mutare la coda.
    p = str(tmp_path / "segnali.csv")
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1000)
    cw.write_rows(q.active_rows(), p)
    snapshot = _events_in_csv(p)

    res = _confirm_then_write("Roma v Lazio - Both Teams To Score - Sì piazzata",
                              q, p, running=False)
    assert res is None                                 # STOP: niente elaborazione
    assert _events_in_csv(p) == snapshot               # CSV invariato
    assert len(q.active_rows()) == 1                    # coda invariata
