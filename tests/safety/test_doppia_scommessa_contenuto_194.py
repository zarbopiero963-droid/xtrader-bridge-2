"""B1 (#194 / #192 H1): due messaggi formulati DIVERSAMENTE per la stessa giocata non devono
produrre due righe CSV.

`signal_dedupe.row_dedup_key` antepone `message_hash(text)` ai campi identificativi della riga.
Ogni guardia anti-duplicato usa quella chiave, quindi cattura solo il rinvio del **medesimo
testo**. Un repost riformulato — un'intestazione promozionale, una correzione di quota, un
inoltro con firma diversa — produce una chiave diversa mentre la riga resta **identica**, e in
`APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED` vengono scritte entrambe: due righe byte-identiche nel
CSV che XTrader legge, cioe' la stessa scommessa piazzata due volte.

E' l'invariante che `CLAUDE.md` nomina per prima, e il commento della guardia stessa descrive
esattamente questo esito: *«accoderebbe una SECONDA riga uguale -> doppia scommessa»*.

La correzione aggiunge un'IDENTITA' DELLA SCOMMESSA indipendente dal messaggio
(`signal_dedupe.row_identity`), confrontata con le righe ancora attive in coda. Non sostituisce
`row_dedup_key`: lo affianca. Vale solo per le modalita' multi-riga — in `OVERWRITE_LAST` la
`add` SOSTITUISCE, quindi una seconda riga non puo' esistere e il reinvio deve poter riscrivere
l'ultima istruzione (comportamento storico, invariato).

Controprove obbligatorie, perche' bloccare tutto sarebbe facile quanto inutile:
giocate DIVERSE devono continuare a passare, l'espansione A->A+B deve restare possibile, e una
riga SCADUTA deve poter essere ripiazzata.
"""

import csv as _csv
import os
import tempfile

import pytest

from xtrader_bridge import (csv_writer, safety_guard, signal_dedupe, signal_queue,
                            write_path)

T0 = 1_800_000_000.0

# stessa giocata, due formulazioni diverse: e' il caso reale di un canale che ri-pubblica
MSG_A1 = "Match: Inter v Milan\nEsito: Inter\nQuota: 1.85\nLato: BACK"
MSG_A2 = "\U0001F525 VIP \U0001F525\nMatch: Inter v Milan\nEsito: Inter\nQuota: 1.85\nLato: BACK"


def _riga(selezione="Inter", evento="Inter v Milan"):
    r = {c: "" for c in csv_writer.CSV_HEADER}
    r.update({"Provider": "TG", "EventName": evento, "MarketType": "MATCH_ODDS",
              "SelectionName": selezione, "Price": "1,85", "BetType": "PUNTA"})
    return r


def _stack(mode, timeout=90):
    d = tempfile.mkdtemp()
    return {
        "tracker": signal_dedupe.SignalTracker(),
        "daily": safety_guard.DailyLimiter(),
        "queue": signal_queue.SignalQueue(mode=mode, default_timeout=timeout),
        "path": os.path.join(d, "segnali.csv"),
        "cfg": {"dry_run": False, "queue_mode": mode, "bridge_mode": "REALE"},
    }


def _commit(st, testo, riga, now):
    st["cfg"]["csv_path"] = st["path"]
    return write_path.commit_signal(st["tracker"], st["daily"], st["queue"], st["cfg"],
                                    testo, riga, st["path"], now, csv_writer.write_rows)


def _righe_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(_csv.DictReader(f))


# --------------------------------------------------------------------------------------
# Il difetto
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [signal_queue.APPEND_ACTIVE, signal_queue.QUEUE_UNTIL_CONFIRMED])
def test_due_messaggi_diversi_stessa_giocata_una_sola_riga(mode):
    """FAIL-FIRST. Il cuore di B1: due testi diversi, la stessa scommessa, una sola riga."""
    st = _stack(mode)
    _commit(st, MSG_A1, _riga(), T0)
    esito = _commit(st, MSG_A2, _riga(), T0 + 5)

    righe = _righe_csv(st["path"])
    assert len(righe) == 1, (
        f"{len(righe)} righe nel CSV: la stessa scommessa e' stata piazzata due volte "
        f"(esiti: {esito.decision})")


@pytest.mark.parametrize("mode", [signal_queue.APPEND_ACTIVE, signal_queue.QUEUE_UNTIL_CONFIRMED])
def test_il_secondo_messaggio_e_classificato_DUPLICATE(mode):
    """Non basta che il CSV abbia una riga sola: la decisione deve DIRE che e' un duplicato,
    altrimenti contatori, diario e limiti giornalieri raccontano una storia falsa."""
    st = _stack(mode)
    _commit(st, MSG_A1, _riga(), T0)
    esito = _commit(st, MSG_A2, _riga(), T0 + 5)
    assert esito.decision == "DUPLICATE", esito.decision


# --------------------------------------------------------------------------------------
# Controprove — la correzione non deve bloccare cio' che e' legittimo
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [signal_queue.APPEND_ACTIVE, signal_queue.QUEUE_UNTIL_CONFIRMED])
def test_giocate_DIVERSE_passano_entrambe(mode):
    """CONTROPROVA. Bloccare tutto sarebbe facile: due scommesse diverse devono restare due."""
    st = _stack(mode)
    _commit(st, MSG_A1, _riga(selezione="Inter"), T0)
    _commit(st, "Match: Roma v Lazio\nEsito: Roma", _riga(selezione="Roma", evento="Roma v Lazio"),
            T0 + 5)
    assert len(_righe_csv(st["path"])) == 2


@pytest.mark.parametrize("mode", [signal_queue.APPEND_ACTIVE, signal_queue.QUEUE_UNTIL_CONFIRMED])
def test_espansione_A_poi_A_piu_B(mode):
    """CONTROPROVA. Un messaggio piazza A; un SECONDO messaggio, formulato diversamente, porta
    A+B. Attese due righe: A resta quella gia' attiva, B si aggiunge.

    Oggi ne escono TRE (A duplicata), ed e' proprio B1 nel percorso multi-riga: l'identita' per
    contenuto qui non rompe l'espansione, la corregge.
    """
    st = _stack(mode)
    st["cfg"]["csv_path"] = st["path"]
    _commit(st, MSG_A1, _riga(selezione="Inter"), T0)

    write_path.commit_signals(st["tracker"], st["daily"], st["queue"], st["cfg"], MSG_A2,
                              [_riga(selezione="Inter"), _riga(selezione="Milan")],
                              st["path"], T0 + 5, csv_writer.write_rows)

    selezioni = sorted(r["SelectionName"] for r in _righe_csv(st["path"]))
    assert selezioni == ["Inter", "Milan"], f"attese A+B, trovate {selezioni}"


@pytest.mark.parametrize("mode", [signal_queue.APPEND_ACTIVE, signal_queue.QUEUE_UNTIL_CONFIRMED])
def test_dopo_la_scadenza_la_stessa_giocata_e_ripiazzabile(mode):
    """CONTROPROVA. L'identita' blocca solo finche' la riga e' ATTIVA: una giocata scaduta deve
    poter essere ripiazzata, altrimenti si perde un segnale valido invece di evitarne uno doppio.
    """
    st = _stack(mode, timeout=60)
    _commit(st, MSG_A1, _riga(), T0)
    # oltre la scadenza della riga E oltre la finestra di deduplica del tracker
    dopo = T0 + 60 + signal_dedupe.DEFAULT_DEDUPE_WINDOW + 10
    _commit(st, MSG_A2, _riga(), dopo)

    righe = _righe_csv(st["path"])
    assert len(righe) == 1, f"la giocata scaduta non e' stata ripiazzata: {len(righe)} righe"


def test_OVERWRITE_LAST_resta_invariato():
    """CONTROPROVA. In `OVERWRITE_LAST` la `add` SOSTITUISCE: una seconda riga non puo' esistere
    e il reinvio deve poter riscrivere l'ultima istruzione. Comportamento storico, non toccato."""
    st = _stack(signal_queue.OVERWRITE_LAST)
    _commit(st, MSG_A1, _riga(), T0)
    _commit(st, MSG_A2, _riga(), T0 + 5)
    assert len(_righe_csv(st["path"])) == 1


# --------------------------------------------------------------------------------------
# L'identita' come funzione pura
# --------------------------------------------------------------------------------------

def test_row_identity_ignora_il_messaggio_e_guarda_la_scommessa():
    """L'identita' e' della GIOCATA: due messaggi diversi con la stessa riga collidono, due
    righe diverse no. `row_dedup_key` resta message-dependent: sono due chiavi con due scopi."""
    r = _riga()
    assert signal_dedupe.row_identity(r) == signal_dedupe.row_identity(dict(r))
    assert signal_dedupe.row_dedup_key(MSG_A1, r) != signal_dedupe.row_dedup_key(MSG_A2, r), \
        "row_dedup_key deve restare dipendente dal messaggio (serve al multi-riga)"
    assert signal_dedupe.row_identity(r) != signal_dedupe.row_identity(_riga(selezione="Milan"))


def test_row_identity_distingue_il_LATO_della_scommessa():
    """PUNTA e BANCA sulla stessa selezione sono scommesse OPPOSTE: non devono mai collidere,
    o l'una verrebbe scambiata per un duplicato dell'altra e non piazzata."""
    punta = _riga()
    banca = dict(punta, BetType="BANCA")
    assert signal_dedupe.row_identity(punta) != signal_dedupe.row_identity(banca)
