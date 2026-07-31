"""B46 (#194, trovato durante la review di PR-A #197): la stessa scommessa scritta con un
FORMATO diverso non deve diventare due righe CSV.

PR-A ha reso l'identità della scommessa indipendente dal MESSAGGIO. Ma il confronto dei campi
è rimasto **testuale puro** (`str(...).strip()`), quindi la stessa giocata scritta in un modo
leggermente diverso produce ancora due identità e, in `APPEND_ACTIVE`/`QUEUE_UNTIL_CONFIRMED`,
due righe nel CSV che XTrader legge:

- `Handicap` `"0"` vs `"0.0"` vs `"+0"` vs `"0.50"`/`"0.5"` — stesso numero, stringhe diverse;
- `SelectionName` `"Inter"` vs `"INTER"` — è **il modo più comune in cui un canale ri-pubblica**
  un pronostico, e senza regola di rimappatura né dizionario il CSV ricopia il messaggio
  verbatim (chiarimento del proprietario), quindi il case che finisce nel CSV è quello del
  messaggio.

Non è un buco nuovo: è una correzione **incompleta**. L'audit #76 (P2-2) aveva già normalizzato
virgola→punto su `Handicap`/`Points` con la motivazione scritta *«così la chiave dedup per-riga
è canonica e la stessa scommessa in stile «0,5»/«0.5» non genera due righe»*. Ha canonicalizzato
il **separatore**, non il **valore**, e non ha toccato le colonne testuali.

Due scelte di progetto che questi test fissano, perché sono la parte che può fare danno:

1. **La canonicalizzazione vive SOLO in `row_identity`.** `row_dedup_key` è **persistita** — in
   `dedupe_state.json` e su ogni segnale in coda come `dedup_key`. Cambiarne la normalizzazione
   invaliderebbe in silenzio tutte le chiavi già su disco: al primo avvio dopo l'aggiornamento
   una riga ancora attiva avrebbe la chiave vecchia mentre il codice calcola quella nuova, non
   combacerebbero, il duplicato non verrebbe riconosciuto → **doppia scommessa**. Una correzione
   che causa il bug che sta correggendo. `test_row_dedup_key_non_e_cambiata_di_un_byte` blinda
   questo con gli hash **letterali** misurati prima della patch.

2. **La normalizzazione testuale non è nuova: è `dizionario.normalize`**, già dichiarata nel
   codice «fonte unica della normalizzazione, riusata anche dalle value-map per evitare
   implementazioni divergenti». Scriverne una copia qui sarebbe stata la terza. Così l'identità
   della scommessa usa la **stessa** nozione di «stesso nome» che il dizionario usa per il
   lookup, invece di una privata.

Fuori scope deliberatamente: la **virgola dentro il nome della selezione** (`Over 5,5` vs
`Over 5.5`). È un buco reale e misurato, ma il contratto CSV dice esplicitamente che le colonne
testuali non vengono **mai** toccate: allargare lì è una decisione del proprietario, non una
conseguenza di questa correzione. Registrato a parte come B47.
"""

import csv as _csv
import os
import tempfile

import pytest

from xtrader_bridge import (csv_writer, dizionario, safety_guard, signal_dedupe,
                            signal_queue, write_path)

T0 = 1_800_000_000.0


def _riga(**kw):
    r = {c: "" for c in csv_writer.CSV_HEADER}
    r.update({"Provider": "TG", "EventName": "Inter v Milan", "MarketType": "MATCH_ODDS",
              "SelectionName": "Inter", "Price": "1,85", "BetType": "PUNTA", "Handicap": "0"})
    r.update(kw)
    return r


def _stessa_scommessa(a: dict, b: dict) -> bool:
    return signal_dedupe.row_identity(_riga(**a)) == signal_dedupe.row_identity(_riga(**b))


# --------------------------------------------------------------------------------------
# Il difetto — varianti di FORMATO che oggi sfuggono
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("uno,due", [
    ("0", "0.0"),        # il caso segnalato in review
    ("0", "+0"),
    ("1", "+1"),
    ("0.5", ".5"),
    ("0.5", "0.50"),
    ("-0.5", "-.50"),
])
def test_handicap_stesso_numero_stessa_scommessa(uno, due):
    """FAIL-FIRST. Lo stesso handicap scritto in due modi è lo stesso handicap."""
    assert _stessa_scommessa({"Handicap": uno}, {"Handicap": due}), (
        f"handicap {uno!r} e {due!r} sono lo stesso numero ma due scommesse diverse")


@pytest.mark.parametrize("uno,due", [
    ("Inter", "INTER"),
    ("Inter", "inter"),
    ("Inter Milan", "Inter  Milan"),      # spazio doppio: copia verbatim dal messaggio
    ("Inter", " Inter"),
])
def test_selection_stesso_nome_stessa_scommessa(uno, due):
    """FAIL-FIRST. Un repost in MAIUSCOLO è il modo più comune in cui un canale ri-pubblica:
    senza dizionario il CSV copia il messaggio, quindi il case cambia e la scommessa no."""
    assert _stessa_scommessa({"SelectionName": uno}, {"SelectionName": due}), (
        f"selezione {uno!r} e {due!r} sono la stessa ma due scommesse diverse")


@pytest.mark.parametrize("campo", ["EventName", "MarketType", "Provider"])
def test_anche_gli_altri_campi_testuali_sono_insensibili_al_case(campo):
    """La classe, non il sito: tutti i campi testuali dell'identità arrivano dalla stessa
    copiatura verbatim del messaggio, quindi hanno tutti la stessa esposizione."""
    assert _stessa_scommessa({campo: "Serie A"}, {campo: "SERIE A"})


def test_repost_in_maiuscolo_non_raddoppia_la_scommessa():
    """FAIL-FIRST end-to-end, il caso reale: stesso canale, stessa giocata, secondo post in
    maiuscolo con un'intestazione promozionale. Deve restare UNA riga nel CSV."""
    mode = signal_queue.APPEND_ACTIVE
    percorso = os.path.join(tempfile.mkdtemp(), "segnali.csv")
    cfg = {"dry_run": False, "queue_mode": mode, "bridge_mode": "REALE", "csv_path": percorso}
    tracker, daily = signal_dedupe.SignalTracker(), safety_guard.DailyLimiter()
    coda = signal_queue.SignalQueue(mode=mode, default_timeout=90)

    write_path.commit_signal(tracker, daily, coda, cfg, "Match: Inter v Milan\nEsito: Inter",
                             _riga(SelectionName="Inter"), percorso, T0, csv_writer.write_rows)
    write_path.commit_signal(tracker, daily, coda, cfg,
                             "\U0001F525 RILANCIO \U0001F525\nMatch: Inter v Milan\nEsito: INTER",
                             _riga(SelectionName="INTER"), percorso, T0 + 5,
                             csv_writer.write_rows)

    with open(percorso, encoding="utf-8-sig", newline="") as f:
        righe = list(_csv.DictReader(f))
    assert len(righe) == 1, (
        f"{len(righe)} righe: la stessa scommessa piazzata due volte "
        f"({[r['SelectionName'] for r in righe]})")


# --------------------------------------------------------------------------------------
# Controprove — l'identità non deve diventare CIECA
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("uno,due", [
    ("-1", "+1"),        # handicap opposti
    ("0.5", "1.5"),
    ("-0.5", "0.5"),
    ("0", "1"),
])
def test_handicap_DIVERSI_restano_scommesse_diverse(uno, due):
    """CONTROPROVA. Collassare tutto sarebbe facile quanto disastroso: un handicap diverso è
    una scommessa diversa, e scambiarla per un duplicato significa PERDERE un segnale valido."""
    assert not _stessa_scommessa({"Handicap": uno}, {"Handicap": due}), (
        f"handicap {uno!r} e {due!r} sono numeri diversi ma la stessa scommessa")


def test_selezioni_e_lati_diversi_restano_diversi():
    """CONTROPROVA. Il case cade, il significato no."""
    assert not _stessa_scommessa({"SelectionName": "Inter"}, {"SelectionName": "Milan"})
    assert not _stessa_scommessa({"BetType": "PUNTA"}, {"BetType": "BANCA"})
    assert not _stessa_scommessa({"EventName": "Inter v Milan"},
                                 {"EventName": "Roma v Lazio"})


def test_handicap_non_numerico_confronta_come_TESTO():
    """Fail-closed. Un handicap che non è un numero non viene «interpretato»: si confronta
    come testo, come prima. Mai indovinare un valore che finisce in una scommessa."""
    assert _stessa_scommessa({"Handicap": "asimmetrico"}, {"Handicap": "ASIMMETRICO"})
    assert not _stessa_scommessa({"Handicap": "asimmetrico"}, {"Handicap": "altro"})
    # e un non-numero non collide mai con uno zero solo perché entrambi «non valgono nulla»
    assert not _stessa_scommessa({"Handicap": "asimmetrico"}, {"Handicap": "0"})


def test_valori_non_finiti_non_collassano_su_un_numero():
    """`float("nan")`/`inf` sono parsabili da `float()` ma non sono handicap: devono restare
    testo, altrimenti `nan != nan` renderebbe una riga eternamente «nuova» (o `inf` collasserebbe
    handicap diversi). È lo stesso presidio anti-non-finiti già applicato altrove nel modulo."""
    assert not _stessa_scommessa({"Handicap": "nan"}, {"Handicap": "0"})
    assert not _stessa_scommessa({"Handicap": "inf"}, {"Handicap": "0"})
    assert _stessa_scommessa({"Handicap": "nan"}, {"Handicap": "NAN"})   # testo, non numero


# --------------------------------------------------------------------------------------
# Le due scelte di progetto, blindate
# --------------------------------------------------------------------------------------

def test_row_dedup_key_non_e_cambiata_di_un_byte():
    """La guardia che conta di più di tutte le altre.

    `row_dedup_key` è PERSISTITA (`dedupe_state.json`, e `dedup_key` su ogni segnale in coda).
    Se la canonicalizzazione finisse anche lì, al primo avvio dopo l'aggiornamento le righe
    ancora attive avrebbero la chiave VECCHIA mentre il codice calcola quella NUOVA: nessuna
    corrispondenza, duplicato non riconosciuto, **doppia scommessa** — causata proprio dalla
    patch che la doveva impedire.

    Gli hash qui sotto sono stati MISURATI sul codice pre-patch (`main` 799f51d) e sono
    incollati come letterali: se un refactor futuro tocca `row_dedup_key`, anche solo di un
    byte, questo test diventa rosso e costringe a ragionare sulla migrazione.
    """
    attesi = {
        "base":      "e5ec7bc2230acce9dceb42ac0808e7928e086b5981dac2335d9833aec7769153",
        "hcap_00":   "e709e76fba81454fe27364eed3a1c48d369fcec0230149af3263dfe1c4ca102b",
        "sel_caps":  "614a172c58aaa67e338e3aa95e49d081521d9564534733793063621421081592",
        "sel_spazi": "a6ea5087921c8fbbd7e360d4c77ece71272f63b68ceb05c41b62072a603f1d9b",
        "vuota":     "e6a18e53397f9b5d1ae4149707992bad75839195043e39b878dc5a5b9eb84fb8",
    }
    ottenuti = {
        "base":      signal_dedupe.row_dedup_key("MSG", _riga()),
        "hcap_00":   signal_dedupe.row_dedup_key("MSG", _riga(Handicap="0.0")),
        "sel_caps":  signal_dedupe.row_dedup_key("MSG", _riga(SelectionName="INTER")),
        "sel_spazi": signal_dedupe.row_dedup_key("MSG", _riga(SelectionName="Inter  Milan")),
        "vuota":     signal_dedupe.row_dedup_key("MSG", {}),
    }
    assert ottenuti == attesi, (
        "row_dedup_key è cambiata: è PERSISTITA su disco, quindi cambiarla invalida in "
        "silenzio le chiavi già scritte e riapre la doppia scommessa al primo riavvio.")


def test_row_dedup_key_resta_sensibile_al_formato():
    """Corollario esplicito del test sopra, perché la differenza fra le due chiavi sia una
    scelta leggibile e non un effetto collaterale: `row_identity` chiede «è la stessa
    SCOMMESSA?», `row_dedup_key` chiede «è la stessa RIGA di quel messaggio?» — provenienza
    esatta, e come tale resta sensibile al formato."""
    a, b = _riga(Handicap="0"), _riga(Handicap="0.0")
    assert signal_dedupe.row_dedup_key("MSG", a) != signal_dedupe.row_dedup_key("MSG", b)
    assert signal_dedupe.row_identity(a) == signal_dedupe.row_identity(b)


def test_la_normalizzazione_testuale_e_quella_del_dizionario():
    """La fonte unica, resa eseguibile. Se qualcuno domani cambiasse `dizionario.normalize`
    senza pensare all'identità delle scommesse — o viceversa ne scrivesse una copia locale —
    le due nozioni di «stesso nome» divergerebbero in silenzio: il dizionario risolverebbe
    due alias allo stesso nome e la deduplica li tratterebbe come scommesse diverse."""
    for uno, due in [("Inter", "INTER"), ("Over  0.5  HT", "over 0.5 ht"), ("A B", "a  b")]:
        stesso_nome = dizionario.normalize(uno) == dizionario.normalize(due)
        assert _stessa_scommessa({"SelectionName": uno}, {"SelectionName": due}) == stesso_nome
