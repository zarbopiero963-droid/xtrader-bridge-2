"""B47 (#194): `Over 5,5` e `Over 5.5` sono la stessa linea, e oggi sono due scommesse.

Trovato durante la Phase 0 di PR-A2. Le colonne DECIMALI (`Handicap`, `Price`, `Points`) sono già
portate al punto a monte della scrittura, ma `SelectionName` è una colonna **testuale** e il
contratto CSV dichiara che le testuali «non vengono **mai** toccate». Quindi la linea `5,5` resta
`5,5`, la linea `5.5` resta `5.5`, e per il confronto sono due stringhe diverse.

Da dove nascono le due forme — misurato, non ipotizzato:

- **la virgola** la mette il bridge stesso: la trasformazione `score_to_over` (CP-05, l'unica del
  prodotto) dal punteggio `2-3` genera letteralmente `"Over 5,5"`, con la virgola scritta a mano
  in `transforms.py`. È opt-in: scatta solo se una regola imposta `transform="score_to_over"`;
- **il punto** arriva dal messaggio copiato verbatim — e questo percorso **non richiede la
  trasformazione**. Basta lo stesso canale italiano che scrive `Over 2,5` in un post e `Over 2.5`
  in un altro, con la copiatura verbatim e basta.

**Decisione del proprietario** (2026-07-31): normalizzare. La normalizzazione è **chirurgica** —
solo una virgola **fra due cifre** — e vive **solo** in `row_identity`, cioè nel confronto: nel
CSV continua a finire il valore prodotto dalla regola del parser.

Perché fra due cifre e non ovunque: le virgole della prosa (`"Inter, primo tempo"`) sono seguite
da uno **spazio**, non da una cifra, quindi non vengono toccate. È la stessa distinzione che il
contratto CSV fa già per le colonne decimali, applicata al solo confronto e non alla scrittura.
"""

import json
import os
import tempfile

import pytest

from xtrader_bridge import csv_writer, signal_dedupe, transforms

T0 = 1_800_000_000.0


def _riga(selezione, **kw):
    r = {c: "" for c in csv_writer.CSV_HEADER}
    r.update({"Provider": "TG", "EventName": "Inter v Milan", "MarketType": "OVER_UNDER",
              "SelectionName": selezione, "Price": "1,85", "BetType": "PUNTA", "Handicap": "0"})
    r.update(kw)
    return r


def _stessa(a, b, **kw):
    return signal_dedupe.row_identity(_riga(a, **kw)) == signal_dedupe.row_identity(_riga(b, **kw))


# --------------------------------------------------------------------------------------
# Il difetto
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("uno,due", [
    ("Over 5,5", "Over 5.5"),
    ("Under 2,5", "Under 2.5"),
    ("Over 0,5 HT", "Over 0.5 HT"),
    ("Handicap -1,5", "Handicap -1.5"),
])
def test_stessa_linea_scritta_coi_due_separatori(uno, due):
    """FAIL-FIRST. La stessa linea con virgola o punto è la stessa scommessa."""
    assert _stessa(uno, due), f"{uno!r} e {due!r} sono la stessa linea ma due scommesse diverse"


def test_la_trasformazione_del_prodotto_genera_la_virgola():
    """Fissa l'origine del difetto, così non si perde il perché: `score_to_over` scrive la
    virgola a mano. Se un giorno passasse al punto, questo test lo direbbe subito — e la
    normalizzazione resterebbe comunque necessaria per i messaggi copiati verbatim."""
    assert transforms._score_to_over("2-3") == "Over 5,5"
    assert _stessa(transforms._score_to_over("2-3"), "Over 5.5")


# --------------------------------------------------------------------------------------
# Controprove — la normalizzazione deve essere CHIRURGICA
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("uno,due", [
    ("Over 5,5", "Under 5,5"),          # lato opposto
    ("Over 5,5", "Over 6,5"),           # linea diversa
    ("Over 5,5", "Over 5,55"),          # decimale diverso
    ("Over 0,5", "Over 5"),             # non è lo stesso numero
])
def test_linee_DIVERSE_restano_scommesse_diverse(uno, due):
    """CONTROPROVA. Unire per il separatore non deve unire per il valore: collassare due linee
    diverse significa **perdere un segnale valido**, l'errore speculare alla doppia scommessa."""
    assert not _stessa(uno, due), f"{uno!r} e {due!r} sono linee diverse ma la stessa scommessa"


def test_le_virgole_della_PROSA_non_vengono_toccate():
    """CONTROPROVA, ed è la ragione per cui la regola è «fra due cifre» e non «ovunque».

    In un nome di selezione una virgola di prosa è seguita da uno **spazio**, non da una cifra.
    Normalizzare tutte le virgole confonderebbe nomi realmente diversi.
    """
    assert not _stessa("Inter, primo tempo", "Inter. primo tempo")
    assert not _stessa("Milan, Inter", "Milan. Inter")
    # e due nomi con la stessa virgola di prosa restano ovviamente lo stesso nome
    assert _stessa("Inter, primo tempo", "inter, primo tempo")


def test_la_normalizzazione_non_tocca_il_valore_SCRITTO():
    """L'invariante che il contratto CSV impone: le colonne testuali non vengono mai modificate.
    La forma canonica serve **solo** a decidere se è la stessa scommessa — la riga resta quella
    prodotta dal parser."""
    riga = _riga("Over 5,5")
    prima = dict(riga)
    signal_dedupe.row_identity(riga)
    assert riga == prima, "row_identity ha modificato la riga invece di limitarsi a leggerla"
    assert riga["SelectionName"] == "Over 5,5"


def test_row_dedup_key_resta_sensibile_alla_virgola():
    """`row_dedup_key` è **persistita** (`dedupe_state.json`, `dedup_key` sui segnali in coda):
    non deve cambiare, o le chiavi già su disco smetterebbero di combaciare al primo riavvio dopo
    l'aggiornamento — il buco di migrazione che PR-A2 ha evitato per progetto. Qui si fissa che la
    normalizzazione della virgola sia rimasta anch'essa confinata a `row_identity`."""
    a, b = _riga("Over 5,5"), _riga("Over 5.5")
    assert signal_dedupe.row_dedup_key("MSG", a) != signal_dedupe.row_dedup_key("MSG", b)
    assert signal_dedupe.row_identity(a) == signal_dedupe.row_identity(b)


def test_lo_stato_persistito_prima_dell_aggiornamento_continua_a_combaciare():
    """Corollario sul percorso reale: una chiave scritta su disco dalla versione precedente deve
    ancora essere riconosciuta dopo l'aggiornamento."""
    percorso = os.path.join(tempfile.mkdtemp(), "dedupe_state.json")
    chiave = signal_dedupe.row_dedup_key("MSG", _riga("Over 5,5"))

    import time as _time
    adesso = _time.time()
    prima = signal_dedupe.SignalTracker()
    prima.mark_seen(chiave, now=adesso)
    assert signal_dedupe.save_state(prima, percorso, now=adesso) is True

    dopo = signal_dedupe.SignalTracker()
    assert signal_dedupe.load_state(dopo, percorso, now=adesso) is True
    assert dopo.is_seen(signal_dedupe.row_dedup_key("MSG", _riga("Over 5,5")), now=adesso + 5)


# --------------------------------------------------------------------------------------
# Gli altri campi identificativi: stessa regola, stessa classe
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("campo", ["EventName", "MarketType"])
def test_la_regola_vale_per_tutti_i_campi_testuali(campo):
    """La classe, non il sito: tutti i campi testuali dell'identità arrivano dalla stessa
    copiatura verbatim del messaggio, quindi hanno tutti la stessa esposizione."""
    assert _stessa("X", "X", **{campo: "Linea 2,5"}) is True
    uno = signal_dedupe.row_identity(_riga("X", **{campo: "Linea 2,5"}))
    due = signal_dedupe.row_identity(_riga("X", **{campo: "Linea 2.5"}))
    assert uno == due, f"{campo}: la virgola fra cifre non è normalizzata"
