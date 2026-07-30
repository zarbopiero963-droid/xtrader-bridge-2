"""B4 (#194 / #192 M1): un salto INDIETRO dell'orologio non deve azzerare la deduplica.

Il clamp anti-corruzione di `restore_state` nasce per una ragione giusta — una voce con
timestamp assurdo (anno 3000, da file corrotto/manomesso) non verrebbe mai potata da `_prune`
e bloccherebbe quell'hash **per sempre**. Ma l'orizzonte era calcolato **a partire da `now`**
(`now + max(dedupe_window, 60)`), e questo presuppone che `now` sia attendibile: se l'orologio
arretra di piu' di una finestra, voci del tutto legittime — registrate contro l'orologio
*vecchio* — finiscono oltre l'orizzonte e vengono riportate al `now` arretrato. Quando poi
l'orologio viene corretto in avanti, quelle voci risultano troppo vecchie, escono dalla
finestra, e **lo stesso messaggio si ri-registra come NEW**: scritto due volte.

Due chiamanti, due livelli di fiducia (per questo la correzione e' in due parti):

- `write_path` (**7** siti di rollback del tracker): lo snapshot e' preso dallo stesso processo
  pochi secondi prima via `tracker.state()`. Non e' un file, nessuno puo' manometterlo ->
  `trusted=True`, restauro verbatim, nessun clamp.
  Sette, non sedici: dei 16 `restore_state` di `write_path` gli altri 9 sono `daily` (2) e
  `queue` (6), classi diverse le cui firme non accettano nemmeno `now` — passare loro `trusted`
  sarebbe un `TypeError` all'avvio. Il test `test_tutti_i_rollback_del_tracker_sono_fidati`
  qui sotto fissa il conteggio, cosi' un ottavo sito aggiunto in futuro e dimenticato
  diventa rosso invece di riaprire B4 in silenzio.
- `load_state` (allo START): legge `dedupe_state.json` dal disco -> il clamp RESTA, ma con
  orizzonte a 24 h (decisione proprietario D1 in #194): uno step NTP o un ripristino di
  snapshot VM valgono secondi/ore, un file corrotto sbaglia di anni.

Ogni test ha il suo **controllo positivo**: non basta che la deduplica sopravviva al salto
d'orologio, deve anche continuare a bloccare i duplicati e a clampare la corruzione vera —
altrimenti avremmo "corretto" il bug disattivando la protezione.
"""

import ast
import pathlib

import pytest

from xtrader_bridge import signal_dedupe

_WRITE_PATH = pathlib.Path(signal_dedupe.__file__).with_name("write_path.py")

MSG = "Match: Inter v Milan\nEsito: Inter\nQuota: 1.85\nLato: BACK"
T0 = 1_800_000_000.0
GIORNO = 86_400.0


def _tracker_con_voce(now=T0):
    """Tracker con `MSG` gia' registrato a `now` (stato pronto per uno snapshot)."""
    t = signal_dedupe.SignalTracker()
    assert t.register(MSG, now=now).status == signal_dedupe.NEW
    return t


# --------------------------------------------------------------------------------------
# Parte 1 — rollback in-process (write_path): lo snapshot e' NOSTRO, va restaurato verbatim
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("salto", [-301.0, -600.0, -3600.0, -2 * GIORNO])
def test_rollback_fidato_non_perde_la_deduplica(salto):
    """FAIL-FIRST. Un rollback di `write_path` con l'orologio arretrato oltre la finestra
    deve lasciare i timestamp INVARIATI: e' il nostro stesso snapshot, non un file."""
    snapshot = _tracker_con_voce().state()

    ripristinato = signal_dedupe.SignalTracker()
    ripristinato.restore_state([list(v) for v in snapshot], now=T0 + salto, trusted=True)

    assert ripristinato.state()[0][1] == snapshot[0][1], (
        "il rollback ha alterato un timestamp che aveva preso lui stesso pochi secondi prima")
    # e la conseguenza che conta: a orologio corretto il messaggio resta un duplicato
    assert ripristinato.register(MSG, now=T0 + 120).status == signal_dedupe.DUPLICATE, (
        "deduplica persa: lo stesso segnale verrebbe scritto una seconda volta")


def test_controllo_positivo_rollback_senza_salto_orologio():
    """Senza salto d'orologio il comportamento non cambia: prova che la correzione non ha
    semplicemente disattivato la guardia."""
    snapshot = _tracker_con_voce().state()
    t = signal_dedupe.SignalTracker()
    t.restore_state([list(v) for v in snapshot], now=T0, trusted=True)
    assert t.register(MSG, now=T0 + 120).status == signal_dedupe.DUPLICATE


def test_il_restauro_fidato_non_disattiva_gli_altri_presidi():
    """`trusted=True` salta SOLO il clamp: NaN/inf e voci malformate restano scartati.
    Un `inf` conservato bloccherebbe quell'hash per sempre (issue #184 H4)."""
    t = signal_dedupe.SignalTracker()
    t.restore_state(
        [["a" * 8, float("inf"), True], ["b" * 8, float("nan"), True],
         ["c" * 8, "non-un-numero", True], [], {}, ["d" * 8, T0, True]],
        now=T0, trusted=True)
    rimaste = [h for (h, _t, _r) in t.state()]
    assert rimaste == ["d" * 8], f"voci non finite o malformate sopravvissute: {rimaste}"


# --------------------------------------------------------------------------------------
# Parte 2 — load_state (START): il clamp RESTA, ma l'orizzonte e' 24 h (decisione D1)
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("salto", [-301.0, -3600.0, -6 * 3600.0])
def test_load_state_tollera_uno_skew_realistico(salto):
    """FAIL-FIRST. Uno step NTP all'indietro o un ripristino di snapshot VM (secondi/ore)
    non e' corruzione: i timestamp non vanno clampati e la deduplica deve reggere."""
    snapshot = _tracker_con_voce().state()
    t = signal_dedupe.SignalTracker()
    t.restore_state([list(v) for v in snapshot], now=T0 + salto)

    assert t.state()[0][1] == snapshot[0][1], "skew d'orologio realistico scambiato per corruzione"
    assert t.register(MSG, now=T0 + 120).status == signal_dedupe.DUPLICATE


def test_load_state_clampa_ancora_la_corruzione_vera():
    """CONTROPROVA della precedente: una voce nell'anno 3000 e' corruzione, non skew, e va
    ancora riportata a `now` — altrimenti `_prune` non la potrebbe mai e quell'hash
    resterebbe DUPLICATE per sempre."""
    assurdo = T0 + 365 * GIORNO * 1000
    t = signal_dedupe.SignalTracker()
    t.restore_state([["deadbeef", assurdo, True]], now=T0)

    (_h, ts, _r) = t.state()[0]
    assert ts == T0, f"timestamp assurdo non clampato: {ts}"


def test_la_soglia_di_corruzione_e_24h_non_la_finestra_di_deduplica():
    """Fissa la decisione D1 come numero, non come intenzione: appena oltre le 24 h si
    clampa, appena sotto no. Senza questo, un futuro ritocco alla finestra di deduplica
    sposterebbe in silenzio anche la soglia di corruzione."""
    t = signal_dedupe.SignalTracker()

    t.restore_state([["sotto", T0 + GIORNO - 60, True]], now=T0)
    assert t.state()[0][1] == T0 + GIORNO - 60, "clampato un valore entro le 24 h"

    t.restore_state([["oltre", T0 + GIORNO + 60, True]], now=T0)
    assert t.state()[0][1] == T0, "non clampato un valore oltre le 24 h"


def test_un_valore_corrotto_non_sopravvive_al_giro_load_state_poi_rollback_fidato():
    """Il limite di `trusted=True`, reso esplicito invece che lasciato al ragionamento.

    In modalita' fidata un timestamp assurdo NON viene clampato — ed e' voluto, altrimenti il
    rollback rifarebbe il danno che deve evitare. La domanda giusta e' quindi: puo' un valore
    corrotto FINIRE in uno snapshot fidato? No, e questo test lo fissa. Uno snapshot fidato e'
    sempre `tracker.state()` di un tracker vivo, i cui valori vengono o da `register()` (che usa
    l'orologio) o da `load_state` (che clampa, perche' non e' fidato). Il giro completo
    disco -> memoria -> rollback non puo' quindi resuscitare la corruzione.
    """
    assurdo = T0 + 365 * GIORNO * 1000

    vivo = signal_dedupe.SignalTracker()
    vivo.restore_state([["deadbeef", assurdo, True]], now=T0)      # da disco: NON fidato -> clampa
    assert vivo.state()[0][1] == T0

    snapshot = vivo.state()                                        # cio' che write_path salverebbe
    dopo_rollback = signal_dedupe.SignalTracker()
    dopo_rollback.restore_state([list(v) for v in snapshot], now=T0, trusted=True)

    assert dopo_rollback.state()[0][1] == T0, (
        "un valore corrotto e' rientrato attraverso il rollback fidato")


def test_tutti_i_rollback_del_tracker_sono_fidati():
    """La regola «cerca la classe, non il sito» resa eseguibile.

    B4 e' stato corretto passando `trusted=True` ai rollback del tracker in `write_path`. Se
    domani qualcuno aggiunge un ramo di rollback e dimentica il parametro, quel percorso torna a
    clampare e B4 si riapre **solo li'** — mentre tutti i test qui sopra restano verdi, perche'
    esercitano `restore_state` direttamente e non il nuovo sito.

    Questo test guarda il sorgente: ogni chiamata `tracker.restore_state(...)` in `write_path`
    deve passare `trusted=True`. Volutamente NON fissa un numero: un sito in piu' e' legittimo,
    un sito senza `trusted` no.

    `daily`/`queue` sono esclusi apposta: sono classi diverse, le loro firme non accettano
    `trusted` e passarglielo sarebbe un `TypeError`.
    """
    albero = ast.parse(_WRITE_PATH.read_text(encoding="utf-8"))
    infedeli = []
    totale = 0
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
            continue
        if nodo.func.attr != "restore_state":
            continue
        oggetto = getattr(nodo.func.value, "id", None)
        if oggetto != "tracker":          # daily/queue: altre classi, altre firme
            continue
        totale += 1
        fidato = any(kw.arg == "trusted" and getattr(kw.value, "value", None) is True
                     for kw in nodo.keywords)
        if not fidato:
            infedeli.append(nodo.lineno)

    assert totale > 0, "nessuna chiamata tracker.restore_state trovata: test da aggiornare"
    assert not infedeli, (
        f"in write_path.py ci sono rollback del tracker SENZA trusted=True alle righe {infedeli}: "
        "su quei percorsi un rollback con l'orologio arretrato riazzera la deduplica (B4)")


def test_il_default_resta_non_fidato():
    """Chi non passa `trusted` deve ottenere il comportamento prudente (clamp attivo):
    un chiamante nuovo che dimentica il parametro non deve ereditare la fiducia."""
    assurdo = T0 + 365 * GIORNO * 1000
    t = signal_dedupe.SignalTracker()
    t.restore_state([["deadbeef", assurdo, True]], now=T0)   # nessun trusted=
    assert t.state()[0][1] == T0
