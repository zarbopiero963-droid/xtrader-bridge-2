"""B47 (#194): `Over 5,5` e `Over 5.5` sono la stessa linea, e oggi sono due scommesse.

Trovato durante la Phase 0 di PR-A2. Le colonne DECIMALI (`Handicap`, `Price`, `Points`) sono già
portate al punto a monte della scrittura, ma `SelectionName` è una colonna **testuale** e il
contratto CSV dichiara che le testuali «non vengono **mai** toccate». Quindi la linea `5,5` resta
`5,5`, la linea `5.5` resta `5.5`, e per il confronto sono due stringhe diverse.

Da dove nascono le due forme — misurato, non ipotizzato:

- **la virgola** la mette il bridge stesso: la trasformazione `score_to_over` (CP-05) dal
  punteggio `2-3` genera letteralmente `"Over 5,5"`, con la virgola scritta a mano
  in `transforms.py`. È opt-in: scatta solo se una regola imposta `transform="score_to_over"`;
- **il punto** arriva dal messaggio copiato verbatim — e questo percorso **non richiede la
  trasformazione**. Basta lo stesso canale italiano che scrive `Over 2,5` in un post e `Over 2.5`
  in un altro, con la copiatura verbatim e basta.

**Decisione del proprietario** (2026-07-31): normalizzare. La normalizzazione è **chirurgica** —
solo una virgola **decimale** — e vive **solo** in `row_identity`, cioè nel confronto: nel CSV
continua a finire il valore prodotto dalla regola del parser.

Due esclusioni, entrambe per non unire nomi realmente diversi (che costerebbe un segnale valido,
l'errore speculare alla doppia scommessa): le virgole della **prosa** (`"Inter, primo tempo"`)
sono seguite da uno spazio, non da una cifra; quelle delle **migliaia** (`"Over 1,000"`) sono
seguite da tre cifre, mentre un decimale in una linea ne ha una o due.
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
    assert transforms.apply("2-3", "score_to_over") == "Over 5,5"
    assert _stessa(transforms.apply("2-3", "score_to_over"), "Over 5.5")


# --------------------------------------------------------------------------------------
# Controprove — la normalizzazione deve essere CHIRURGICA
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("uno,due", [
    ("Over 5,5", "Under 5,5"),          # lato opposto
    ("Over 5,5", "Over 6,5"),           # linea diversa
    ("Over 5,5", "Over 5,55"),          # decimale diverso
    ("Over 0,5", "Over 5"),             # non è lo stesso numero
    ("Over 1,000", "Over 1.000"),       # MIGLIAIA vs decimale: 1000 e 1.0 (rilievo Fable 5 #200)
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


def test_la_virgola_delle_MIGLIAIA_non_e_un_decimale():
    """Rilievo Fable 5 su #200. La prima stesura normalizzava qualunque virgola fra due cifre,
    quindi «Over 1,000» (mille) e «Over 1.000» (uno) — numeri **diversi** — venivano uniti, e
    una delle due linee sarebbe stata scartata come duplicato dell'altra: **segnale perso**.

    Fable lo classificava irrilevante per le linee Over/Under reali, ed è vero; ma la direzione
    è quella che questa PR esiste per non prendere, e distinguerli costa una parentesi: un
    decimale in una linea ha **una o due** cifre dopo la virgola, le migliaia ne hanno **tre**.
    """
    assert not _stessa("Over 1,000", "Over 1.000")
    assert not _stessa("Over 12,500", "Over 12.500")
    # e il decimale continua a funzionare, con una o due cifre
    assert _stessa("Over 5,5", "Over 5.5")
    assert _stessa("Over 5,25", "Over 5.25")


@pytest.mark.parametrize("uno,due", [
    ("Multigol 1,2", "Multigol 2,3"),
    ("Multigol 1,2", "Multigol 1,3"),
    ("Multigol 1,2", "Multigol 3,4"),
    ("Multigol 2,3", "Multigol 4,6"),
])
def test_mercati_a_LISTA_restano_distinti_fra_loro(uno, due):
    """Rilievo Fugu Ultra su #200: nei mercati italiani a **lista** — `Multigol 1,2` = «1 o 2
    gol» — la virgola è un separatore, non un decimale. La normalizzazione la tratta comunque
    come decimale, quindi va dimostrato che non unisce mercati **realmente diversi**.

    Non li unisce: due liste diverse differiscono nelle CIFRE, e le cifre non sono toccate. La
    sola fusione possibile è fra `Multigol 1,2` e `Multigol 1.2`, che sono la stessa lista
    scritta in due modi — non due mercati distinti. Il residuo onesto è nell'altro verso:
    `Multigol 1,2` e `Multigol 1-2` restano distinti (mancata fusione, cioè il comportamento
    di prima), che è un rischio di duplicato e non di segnale perso.
    """
    assert not _stessa(uno, due), f"{uno!r} e {due!r} sono mercati diversi ma la stessa scommessa"


def test_il_trattino_resta_una_forma_a_se():
    """Delimita il residuo dichiarato sopra, invece di lasciarlo implicito: la regola tocca la
    virgola, non il trattino. `Multigol 1-2` non viene unito a `Multigol 1,2` — comportamento
    invariato rispetto a prima di questa PR."""
    assert not _stessa("Multigol 1,2", "Multigol 1-2")


@pytest.mark.parametrize("nome,atteso", [
    ("over 1,5 gol", "over 1.5 gol"),        # decimale seguito da parola
    ("over 1,00 gol", "over 1.00 gol"),      # due cifre: ancora decimale
    ("over 1,00a", "over 1.00a"),            # il confine è la CIFRA, non lo spazio
    ("over 1,000 gol", "over 1,000 gol"),    # tre cifre: migliaia, invariato
    ("over 12,50", "over 12.50"),
    ("inter, primo tempo", "inter, primo tempo"),
])
def test_il_confine_della_lookahead(nome, atteso):
    """Chiesto da GPT-5.5 su #200: fissare esplicitamente dove la lookahead si ferma, invece di
    lasciarlo dedurre dalla regex. Il confine è la **cifra successiva**, non lo spazio: `1,00a` è
    un decimale seguito da una lettera, `1,000` sono migliaia. Un ritocco futuro alla regex che
    spostasse questo confine diventerebbe rosso qui."""
    assert signal_dedupe._VIRGOLA_DECIMALE.sub(".", nome) == atteso


def test_row_identity_non_e_persistita_da_nessuna_parte():
    """Rilievo Fable 5 su #200: «l'identità di `Over 1,000` cambia → un segnale salvato prima
    dell'upgrade non combacia più → doppia scommessa al primo riavvio».

    Il presupposto non regge: `row_identity` **non è persistita**. È calcolata a runtime nei due
    soli siti che la usano (`write_path.commit_signal` e `commit_signals`), confrontata con
    `queue.active_rows()` e buttata. Ciò che va su disco è `row_dedup_key` — che questa PR non
    tocca, come fissa `test_row_dedup_key_resta_sensibile_alla_virgola`.

    Questo test rende la proprietà eseguibile invece che argomentata: lo stato salvato non
    contiene alcuna identità, quindi non esiste un formato da migrare.
    """
    percorso = os.path.join(tempfile.mkdtemp(), "dedupe_state.json")
    riga = _riga("Over 1,000")
    identita = signal_dedupe.row_identity(riga)

    import time as _time
    adesso = _time.time()
    tracker = signal_dedupe.SignalTracker()
    tracker.mark_seen(signal_dedupe.row_dedup_key("MSG", riga), now=adesso)
    assert signal_dedupe.save_state(tracker, percorso, now=adesso) is True

    with open(percorso, encoding="utf-8") as f:
        salvato = f.read()
    assert identita not in salvato, "l'identità è finita nello stato persistito"

    # e nemmeno dopo un giro completo su disco: ciò che torna in memoria è la CHIAVE, non
    # l'identità — quindi non esiste un formato di identità da migrare fra versioni.
    dopo = signal_dedupe.SignalTracker()
    assert signal_dedupe.load_state(dopo, percorso, now=adesso) is True
    assert identita not in {h for (h, _t, _r) in dopo.state()}


# --------------------------------------------------------------------------------------
# Primo tempo vs tempo pieno — la deduplica DEVE saperli distinguere (2026-08-03)
# --------------------------------------------------------------------------------------

def test_primo_tempo_e_tempo_pieno_non_sono_la_stessa_scommessa():
    """Guardia nata con `score_to_over_ht`. Prima di quella trasformazione il primo tempo era
    IRRAGGIUNGIBILE dal parser personalizzato, quindi due righe non potevano differire solo per
    il periodo. Ora possono — e il `SelectionName` risolto è **identico** nei due casi
    (`"Over 1,5 goal"`): a distinguerle resta il solo `MarketType`.

    Se un domani `MarketType` uscisse da `_ROW_KEY_FIELDS`, un segnale di primo tempo e uno di
    tempo pieno sulla stessa partita diventerebbero «la stessa scommessa» e il secondo verrebbe
    silenziosamente scartato come duplicato. Questo test lo impedisce."""
    testo = "Match: Inter v Milan\nRisultato: 0-1\n"   # STESSO messaggio per entrambe le righe
    base = {"Provider": "TG", "EventName": "Inter v Milan",
            "SelectionName": "Over 1,5 goal", "BetType": "PUNTA", "Handicap": "0"}
    primo_tempo = dict(base, MarketType="FIRST_HALF_GOALS_15")
    tempo_pieno = dict(base, MarketType="OVER_UNDER_15")
    # Stesso testo di proposito: se le chiavi differissero per l'hash del messaggio il test
    # passerebbe senza dire nulla sul MarketType, cioè proprio sulla cosa che deve sorvegliare.
    assert (signal_dedupe.row_dedup_key(testo, primo_tempo)
            != signal_dedupe.row_dedup_key(testo, tempo_pieno)), (
        "primo tempo e tempo pieno hanno la STESSA chiave di deduplica: uno dei due segnali "
        "verrebbe scartato come duplicato")


def test_le_due_trasformazioni_over_scrivono_entrambe_la_virgola():
    """Contro-parte di `test_la_trasformazione_del_prodotto_genera_la_virgola` per la variante
    primo tempo: anche lei scrive la virgola a mano, quindi anche il suo output deve risultare
    identico alla forma col punto."""
    assert transforms.apply("0-1", "score_to_over_ht") == "over 1,5 ht"
    assert _stessa(transforms.apply("0-1", "score_to_over_ht"), "over 1.5 ht")
