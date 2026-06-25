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
    """Modella i **blocchi puri** su cui poggia `app._process_confirmation` (interpret →
    `confirm` che rimuove dalla coda PRIMA di scrivere → `write_rows(active_rows())`), con
    il gate `running`. NON è la GUI reale: `app._process_confirmation` è un metodo
    customtkinter NON importabile in CI (manca `tkinter`), quindi qui si verificano gli
    **invariant dei blocchi** (coda + csv_writer), mentre la programmazione del retry
    (`_schedule_expiry`) e lo svuotamento di `_stop` sono verificati a mano su Windows e
    coperti dall'estrazione `confirmation_executor` (voce NEEDS_MANUAL della roadmap #105).
    `writer` può sollevare `OSError` per simulare un CSV lockato (write atomica → file
    precedente intatto)."""
    writer = writer or cw.write_rows
    if not running:
        return None
    result = cr.interpret(text, q.pending())
    if result.status in (cr.CONFIRMED, cr.REJECTED):
        q.confirm(result.signal_id)
        try:
            writer(q.active_rows(), path)   # può sollevare (CSV lockato)
        except OSError:                     # come app: errore a log + retry schedulato (qui
            pass                            # ristretto a OSError per non nascondere altri bug)
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


# ── audit #105 P2: invariant coda+CSV su cui poggia il retry di app ───────────

def test_retry_dopo_write_fallita_converge_alle_righe_residue(tmp_path):
    # audit #105 P2 — invariant dei BLOCCHI usati da app._process_confirmation (non la GUI):
    # conferma → segnale rimosso dalla coda → write_rows FALLISCE (CSV lockato) → il segnale è
    # già fuori dalla coda ma la riga resta nel CSV → riscrivendo le righe RESIDUE della coda
    # (ciò che fa il retry di app via `_schedule_expiry`→`_expire_tick`) il segnale confermato
    # sparisce: convergenza. NB: che app PROGRAMMI davvero il retry è glue GUI (verifica
    # manuale Windows / estrazione confirmation_executor, roadmap #105), non testabile qui.
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


def test_gate_running_false_rende_la_conferma_un_no_op(tmp_path):
    # audit #105 P2 — il GATE `if not self._running: return` di app._process_confirmation:
    # un callback di conferma in RITARDO che arriva mentre il bridge è fermo NON deve
    # elaborare né mutare coda/CSV. (Lo SVUOTAMENTO di coda+CSV è responsabilità di `_stop`,
    # non di questo gate: qui si verifica solo che il callback tardivo sia un no-op.)
    p = str(tmp_path / "segnali.csv")
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=120)
    q.add(_row("Roma v Lazio", "Both Teams To Score", "Sì"), now=1000)
    cw.write_rows(q.active_rows(), p)
    snapshot = _events_in_csv(p)

    res = _confirm_then_write("Roma v Lazio - Both Teams To Score - Sì piazzata",
                              q, p, running=False)
    assert res is None                                 # gate: nessuna elaborazione
    assert _events_in_csv(p) == snapshot               # CSV non mutato dal callback tardivo
    assert len(q.active_rows()) == 1                    # coda non mutata dal callback tardivo
