"""B45 (#194): il residuo dichiarato in PR-B, chiuso rendendolo DECIDIBILE invece che indovinato.

PR-B ha corretto B4 portando l'orizzonte anti-corruzione a 24 h, e ha dichiarato onestamente un
residuo: **un ripristino di snapshot VM di oltre 24 ore ricade ancora nel comportamento
originario**. Il motivo è che l'orizzonte è calcolato a partire da `now` — e dopo un ripristino
`now` è proprio la cosa che non è attendibile. Con il solo contenuto del file, «orologio
arretrato di molto» e «file corrotto» sono indistinguibili: entrambi si presentano come voci nel
futuro. Non era un limite inerente al problema, era un limite del **formato**: mancava il dato
che rende la domanda decidibile.

`saved_at` — l'istante in cui lo stato è stato salvato — la rende decidibile:

- una voce con `t > saved_at` è **impossibile** (registrata dopo il salvataggio) → è corruzione,
  a prescindere da quanto disti da `now`. È un criterio più stretto e più fondato dell'orizzonte
  a 24 h, che su un `now` arretrato di 30 giorni non poteva funzionare;
- `now < saved_at` significa che **l'orologio è arretrato** di `saved_at - now`: le voci vanno
  traslate della stessa quantità, così la loro ETÀ resta quella vera e la finestra di deduplica
  continua a funzionare com'è stata configurata.

Due scelte deliberate che questi test fissano:

1. **Con l'orologio in avanti (riavvio normale) i timestamp restano VERBATIM.** La tentazione è
   ribasare sempre l'età sul momento del caricamento, ma sarebbe un peggioramento: dopo un
   fermo di due ore una voce salvata 10 s prima dello spegnimento tornerebbe «vecchia di 10 s» e
   bloccherebbe come duplicato un segnale legittimo arrivato due ore dopo. Si perde un segnale
   valido — l'errore speculare alla doppia scommessa. La traslazione si applica **solo** quando
   l'orologio è andato indietro.

2. **Uno stato senza `saved_at` si comporta esattamente come prima.** I file scritti dalle
   versioni precedenti non hanno il campo: devono continuare a funzionare con l'orizzonte a 24 h,
   senza che l'aggiornamento cambi il comportamento sotto i piedi.
"""

import json
import os
import tempfile

import pytest

from xtrader_bridge import signal_dedupe

MSG = "Match: Inter v Milan\nEsito: Inter\nQuota: 1.85"
T0 = 1_800_000_000.0
GIORNO = 86_400.0


def _percorso():
    return os.path.join(tempfile.mkdtemp(), "dedupe_state.json")


def _tracker_con_voce(now=T0):
    t = signal_dedupe.SignalTracker()
    assert t.register(MSG, now=now).status == signal_dedupe.NEW
    return t


# --------------------------------------------------------------------------------------
# Il residuo — un orologio arretrato OLTRE l'orizzonte a 24 h
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("giorni_indietro", [2, 30, 365])
def test_snapshot_VM_vecchio_non_perde_la_deduplica(giorni_indietro):
    """FAIL-FIRST. È il residuo dichiarato in PR-B: l'orologio torna indietro di giorni, le voci
    superano l'orizzonte a 24 h e vengono clampate a `now`. Corretto poi l'orologio in avanti,
    risultano vecchissime, escono dalla finestra, e lo stesso messaggio si ri-registra come
    NEW — **scritto due volte**.

    Con `saved_at` la traslazione conserva l'ETÀ delle voci, quindi la deduplica regge.
    """
    percorso = _percorso()
    signal_dedupe.save_state(_tracker_con_voce(now=T0), percorso, now=T0)

    indietro = T0 - giorni_indietro * GIORNO
    ripristinato = signal_dedupe.SignalTracker()
    assert signal_dedupe.load_state(ripristinato, percorso, now=indietro) is True

    assert ripristinato.register(MSG, now=indietro + 60).status == signal_dedupe.DUPLICATE, (
        f"deduplica persa dopo un salto indietro di {giorni_indietro} giorni: lo stesso "
        "segnale verrebbe scritto una seconda volta")


def test_l_eta_della_voce_e_conservata_non_azzerata():
    """La traslazione deve conservare l'ETÀ, non riportare la voce a `now`.

    Se la riportasse a `now`, la voce durerebbe una finestra INTERA in più: un segnale
    legittimo ripubblicato poco dopo verrebbe scartato come duplicato. Qui la voce ha 200 s al
    salvataggio: dopo il ripristino deve averne ancora 200, quindi scadere dopo altri 100
    (finestra 300) e non dopo altri 300.
    """
    percorso = _percorso()
    tracker = signal_dedupe.SignalTracker()
    tracker.register(MSG, now=T0)
    signal_dedupe.save_state(tracker, percorso, now=T0 + 200)          # voce vecchia di 200 s

    indietro = T0 - 30 * GIORNO
    ripristinato = signal_dedupe.SignalTracker()
    signal_dedupe.load_state(ripristinato, percorso, now=indietro)

    # a +99 s è ancora entro i 300 della finestra (200 + 99)
    assert ripristinato.register(MSG, now=indietro + 99).status == signal_dedupe.DUPLICATE
    # a +101 s l'età supera la finestra: la voce è scaduta, come sarebbe successo senza il salto
    fresco = signal_dedupe.SignalTracker()
    signal_dedupe.load_state(fresco, percorso, now=indietro)
    assert fresco.register(MSG, now=indietro + 101).status == signal_dedupe.NEW


# --------------------------------------------------------------------------------------
# Controprove — la correzione non deve peggiorare i casi normali
# --------------------------------------------------------------------------------------

def test_riavvio_normale_lascia_i_timestamp_VERBATIM():
    """CONTROPROVA, ed è la scelta di progetto più importante di questa PR.

    Con l'orologio in AVANTI (riavvio normale) i timestamp NON vengono ribasati: dopo un fermo
    di due ore una voce salvata 10 s prima dello spegnimento deve risultare vecchia di due ore
    e dieci secondi — quindi SCADUTA — e non «vecchia di 10 s». Ribasare sempre bloccherebbe
    come duplicato un segnale legittimo arrivato due ore dopo: si perderebbe un segnale valido.
    """
    percorso = _percorso()
    tracker = signal_dedupe.SignalTracker()
    tracker.register(MSG, now=T0)
    signal_dedupe.save_state(tracker, percorso, now=T0 + 10)

    dopo_due_ore = T0 + 2 * 3600
    ripristinato = signal_dedupe.SignalTracker()
    signal_dedupe.load_state(ripristinato, percorso, now=dopo_due_ore)

    assert ripristinato.register(MSG, now=dopo_due_ore).status == signal_dedupe.NEW, (
        "una voce di due ore fa è stata trattata come recente: un segnale legittimo "
        "verrebbe scartato come duplicato")


def test_riavvio_immediato_riconosce_ancora_il_duplicato():
    """CONTROPROVA della precedente: il caso normale — riavvio pochi secondi dopo — deve
    continuare a bloccare i duplicati, altrimenti avremmo «corretto» disattivando la protezione."""
    percorso = _percorso()
    signal_dedupe.save_state(_tracker_con_voce(now=T0), percorso, now=T0 + 2)

    ripristinato = signal_dedupe.SignalTracker()
    signal_dedupe.load_state(ripristinato, percorso, now=T0 + 5)
    assert ripristinato.register(MSG, now=T0 + 5).status == signal_dedupe.DUPLICATE


def test_una_voce_successiva_al_salvataggio_e_CORRUZIONE():
    """`saved_at` dà un criterio di corruzione più stretto e più fondato dell'orizzonte a 24 h:
    una voce registrata DOPO il salvataggio è impossibile, a prescindere da quanto disti da
    `now`. Va riportata a `saved_at`, altrimenti `_prune` non la potrebbe mai e quell'hash
    resterebbe DUPLICATE per sempre (#184 H4)."""
    percorso = _percorso()
    assurdo = T0 + 365 * GIORNO * 1000
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump({"saved_at": T0, "entries": [["deadbeef", assurdo, True]]}, f)

    ripristinato = signal_dedupe.SignalTracker()
    assert signal_dedupe.load_state(ripristinato, percorso, now=T0) is True
    (_h, ts, _r) = ripristinato.state()[0]
    assert ts <= T0, f"timestamp impossibile non clampato: {ts}"


# --------------------------------------------------------------------------------------
# Compatibilità — i file delle versioni precedenti
# --------------------------------------------------------------------------------------

def test_stato_LEGACY_senza_saved_at_si_comporta_come_prima():
    """Un `dedupe_state.json` scritto da una versione precedente è una LISTA nuda, senza
    `saved_at`. Deve continuare a caricarsi e a comportarsi esattamente come prima —
    orizzonte a 24 h — senza che l'aggiornamento cambi il comportamento sotto i piedi."""
    percorso = _percorso()
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump([["deadbeef", T0, True]], f)                 # formato vecchio: lista nuda

    ripristinato = signal_dedupe.SignalTracker()
    assert signal_dedupe.load_state(ripristinato, percorso, now=T0) is True
    assert [h for (h, _t, _r) in ripristinato.state()] == ["deadbeef"]

    # e il clamp a 24 h resta quello di PR-B su un file legacy
    legacy = _percorso()
    with open(legacy, "w", encoding="utf-8") as f:
        json.dump([["deadbeef", T0 + 365 * GIORNO * 1000, True]], f)
    t = signal_dedupe.SignalTracker()
    signal_dedupe.load_state(t, legacy, now=T0)
    assert t.state()[0][1] == T0, "su stato legacy il clamp a 24 h deve restare attivo"


def test_il_file_nuovo_e_rileggibile_e_contiene_saved_at():
    """Contratto del formato: `save_state` scrive un oggetto con `saved_at` ed `entries`, e
    `load_state` lo rilegge. Se qualcuno cambiasse il formato senza aggiornare il lettore, il
    riavvio perderebbe in silenzio tutta la protezione anti-duplicato."""
    percorso = _percorso()
    assert signal_dedupe.save_state(_tracker_con_voce(now=T0), percorso, now=T0) is True

    with open(percorso, encoding="utf-8") as f:
        salvato = json.load(f)
    assert isinstance(salvato, dict), f"formato inatteso: {type(salvato).__name__}"
    assert salvato["saved_at"] == T0
    assert len(salvato["entries"]) == 1


@pytest.mark.parametrize("rotto", [
    {"saved_at": "non-un-numero", "entries": [["a" * 8, T0, True]]},
    {"saved_at": float("nan"), "entries": [["a" * 8, T0, True]]},
    {"saved_at": float("inf"), "entries": [["a" * 8, T0, True]]},
    {"entries": [["a" * 8, T0, True]]},                    # saved_at assente
    {"saved_at": T0},                                      # entries assenti
    {"saved_at": T0, "entries": "non-una-lista"},
])
def test_saved_at_malformato_non_fa_crashare_lo_START(rotto):
    """Fail-safe. `dedupe_state.json` è un file su disco: corrotto, troncato o manomesso non
    deve MAI far crashare l'avvio — al massimo si perde la protezione anti-duplicato di quel
    riavvio, mai l'app. Un `saved_at` non finito o non numerico ricade sul comportamento
    prudente (l'orizzonte a 24 h), non sulla fiducia."""
    percorso = _percorso()
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(rotto, f)

    ripristinato = signal_dedupe.SignalTracker()
    signal_dedupe.load_state(ripristinato, percorso, now=T0)   # non deve sollevare
    for (_h, ts, _r) in ripristinato.state():
        assert ts == ts and abs(ts) != float("inf"), "timestamp non finito sopravvissuto"
