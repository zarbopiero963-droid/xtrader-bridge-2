"""#256 punto 1 — `_phrase_in_text` ricompilava un regex per frase a OGNI chiamata.

Il pattern dipende **solo** dalla frase normalizzata:

    r"(?<![\\w/-])(?<!\\d[.,])" + re.escape(frase) + r"(?![\\w/-])(?![.,]\\d)"

ma veniva ricostruito e ricompilato a ogni invocazione. Il modulo `re` tiene una cache
interna di ~512 pattern compilati: finché il dizionario mercati sta sotto quella soglia la
cache assorbe tutto e il costo non si vede, ma appena la supera **ogni messaggio ricompila
l'intero dizionario**. Misurato sul percorso live (`resolve_market`, media su 20 messaggi):

     100 frasi ->   0,73 ms/messaggio
     400 frasi ->   2,98 ms/messaggio
     600 frasi ->  54,04 ms/messaggio     <- 18x, il dirupo cade dove ci si aspetta
    1200 frasi -> 108,42 ms/messaggio

Il tetto `_MAX_VOCI_CONTROLLO_AMBIGUITA` introdotto dalla #255 protegge **solo** la
diagnostica allo START. Il runtime non ha tetto e non può averne uno: non si può rifiutare
di risolvere un mercato perché il dizionario è grande. Non è perdita di segnali — è latenza
sul percorso che scrive il CSV.

**Perché i test contano le compilazioni e non i millisecondi.** Un'asserzione a cronometro
è flaky su un runner condiviso e misura la cosa sbagliata: il punto non è «è veloce», è «non
ricompila». Si conta quindi il compilatore REALE (`re._compiler.compile`, invocato solo su
cache miss), che è deterministico e dice esattamente ciò che la patch cambia.

**Il rischio della patch non è la prestazione, è il matching.** `_phrase_in_text` sta sul
percorso soldi: un confine di token sbagliato = mercato sbagliato = scommessa sbagliata (P1
in `tests/safety/test_money_path_p1_bughunt.py`). Perciò qui non si verifica solo che la
cache esista, ma che **attraverso la cache il matching sia identico** — inclusi i casi
decimali che avevano già prodotto un bug reale.
"""

import re

import pytest

from xtrader_bridge import market_mapping_store as mms


def _modulo_compilatore():
    """Il modulo che contiene il compilatore regex reale, o ``None`` se non individuabile.

    È un dettaglio interno di CPython e ha cambiato nome: `sre_compile` fino a 3.10,
    `re._compiler` da 3.11 (il repo gira su 3.11 ovunque, CI inclusa). Sondarli entrambi, e
    tollerare che nessuno dei due esista, evita che un upgrade di Python faccia fallire questi
    test **all'import** — il modo più confuso di rompersi, perché nasconde l'unica cosa che
    stanno misurando (rilievo Fable 5 e GPT-5.5 sulla #257).
    """
    for nome in ("re._compiler", "sre_compile"):
        try:
            modulo = __import__(nome, fromlist=["compile"])
        except ImportError:
            continue
        if hasattr(modulo, "compile"):
            return modulo
    return None


def _conta_compilazioni(fn):
    """Esegue `fn()` contando le compilazioni regex REALI (i cache miss di `re`).

    Si conta il compilatore interno, che `re._compile` invoca **solo** quando il pattern non
    è già nella sua cache. Contare `re.search` direbbe solo quante volte è stata chiamata la
    funzione, non quante volte ha davvero ricompilato — che è l'unica cosa che questa patch
    cambia.

    Lo stato che si tocca è globale (`re.purge()` e la sostituzione del compilatore), quindi
    va ripristinato **sempre**: il `finally` lo garantisce anche se `fn()` solleva. Non è un
    problema di parallelismo — `pytest-xdist` isola per **processo**, e dentro un processo i
    test girano in sequenza — e `_phrase_pattern` è una cache **pura**: svuotarla cambia i
    tempi, mai le risposte.
    """
    modulo = _modulo_compilatore()
    if modulo is None:                  # pragma: no cover - solo su interpreti non-CPython
        pytest.skip("compilatore regex interno non individuabile su questo interprete")
    vero = modulo.compile
    n = [0]

    def contato(*a, **k):
        n[0] += 1
        return vero(*a, **k)

    modulo.compile = contato
    try:
        re.purge()                      # parte da cache fredda, altrimenti il conteggio mente
        mms._phrase_pattern.cache_clear()
        fn()
    finally:
        modulo.compile = vero
        re.purge()
    return n[0]


def _voce(frase):
    return {"start_after": "Mercato:", "end_before": "\n", "phrase": frase,
            "market_type": "", "market_name": "Entrambe le squadre a segno",
            "selection_name": "Sì", "language": ""}


# Sopra la cache interna di `re` (~512): è il regime in cui il difetto morde.
_N_FRASI = 600
_MSG = "Match: A v B\nMercato: frase000000\nQuota: 1,85\n"


def test_256_frasi_oltre_la_cache_di_re_non_si_ricompilano_a_ogni_messaggio():
    """Il cuore della issue, con la misura che l'ha aperta.

    Con 600 frasi mappate, processare 5 messaggi ricompilava ~600 pattern **ogni volta**.
    Sul codice pre-patch questo test è rosso con un conteggio nell'ordine delle migliaia;
    con la cache le frasi si compilano una volta sola e i messaggi successivi costano zero
    compilazioni.
    """
    cfg = {"market_mappings": {"M": [_voce(f"frase{i:06d}") for i in range(_N_FRASI)]}}
    profili = mms.entries_for_profiles(cfg, ["M"])

    def cinque_messaggi():
        for _ in range(5):
            mms.resolve_market(_MSG, profili)

    compilazioni = _conta_compilazioni(cinque_messaggi)
    # Con la cache: ~una compilazione per frase distinta, non per frase PER messaggio.
    # Si lascia margine (il resto del modulo compila qualche pattern suo), ma la soglia
    # esclude nettamente il comportamento «ricompila tutto ogni volta» (~3000).
    assert compilazioni <= _N_FRASI + 50, (
        f"{compilazioni} compilazioni per 5 messaggi con {_N_FRASI} frasi: "
        f"il dizionario viene ricompilato a ogni messaggio")


def test_256_lo_stesso_messaggio_ripetuto_non_compila_piu_nulla():
    """La garanzia più forte, e quella che descrive il regime reale: un bridge acceso riceve
    molti messaggi sullo stesso dizionario. Dopo il primo, le compilazioni devono essere
    **zero** — non «poche»."""
    cfg = {"market_mappings": {"M": [_voce(f"frase{i:06d}") for i in range(_N_FRASI)]}}
    profili = mms.entries_for_profiles(cfg, ["M"])

    _conta_compilazioni(lambda: mms.resolve_market(_MSG, profili))    # scalda (e azzera dopo)
    # NB: `_conta_compilazioni` ripulisce le cache in uscita, quindi qui si riscalda dentro
    # la stessa misura e si conta solo il secondo giro.
    def scalda_poi_dieci():
        mms.resolve_market(_MSG, profili)          # primo giro: compila
        base = mms._phrase_pattern.cache_info().misses
        for _ in range(10):
            mms.resolve_market(_MSG, profili)      # nove giri successivi: deve bastare la cache
        assert mms._phrase_pattern.cache_info().misses == base, "ha ricompilato dopo il warm-up"

    _conta_compilazioni(scalda_poi_dieci)


def test_256_la_cache_e_indicizzata_sulla_frase_NORMALIZZATA():
    """«GG», «gg» e «  gg  » sono la stessa frase per il matching (case-insensitive, spazi
    collassati), quindi devono essere la stessa voce di cache — non tre.

    Non è un dettaglio di efficienza: se la chiave fosse la frase grezza, un dizionario che
    scrive la stessa frase con case diversi moltiplicherebbe le voci di cache e riaprirebbe
    il thrashing che questa patch chiude."""
    mms._phrase_pattern.cache_clear()
    for variante in ("gg", "GG", "  gg  ", "Gg"):
        assert mms._phrase_in_text(variante, "mercato: gg") is True, variante
    assert mms._phrase_pattern.cache_info().misses == 1, mms._phrase_pattern.cache_info()


# ── Il matching NON deve cambiare: `_phrase_in_text` sta sul percorso soldi ──────────
#
# Un confine di token sbagliato qui = mercato sbagliato = scommessa sbagliata. Questi casi
# sono i P1 già tracciati in `tests/safety/test_money_path_p1_bughunt.py`: ripetuti qui
# perché la patch tocca proprio la costruzione del pattern, ed è l'unico modo per accorgersi
# subito se la cache avesse introdotto una divergenza.

@pytest.mark.parametrize("frase,testo,atteso", [
    # separatore decimale: una frase che finisce con un intero NON entra in una linea diversa
    ("over 2", "over 2,75", False),
    ("over 2", "over 2.5", False),
    ("5 ht", "1,5 ht", False),
    ("5", "2,5", False),
    ("2,5", "1,25 over", False),
    # ...ma il decimale giusto combacia
    ("over 2", "over 2", True),
    ("over 0,5", "over 0,5 goal", True),
    ("2,5", "over/under 2,5", True),
    # confini di parola: "over" non entra in "overflow"
    ("over", "overflow", False),
    ("over 0,5", "over 0,55", False),
    # punteggiatura finale resta un confine valido
    ("over 2", "over 2.", True),
    ("over 2", "over 2, quota 1,85", True),
    ("gol gol", "gol gol.", True),
    # separatori / e - non sono confini
    ("x", "1/x", False),
    ("x", "1-x", False),
])
def test_256_il_matching_attraverso_la_cache_e_identico(frase, testo, atteso):
    """Ogni caso passa per la cache. Se la patch avesse alterato la stringa del pattern, o
    avesse indicizzato su una chiave che perde informazione, qui si vedrebbe subito."""
    assert mms._phrase_in_text(frase, mms._normalize_text(testo)) is atteso


def test_256_la_cache_e_limitata_e_non_cresce_senza_fine():
    """Una cache non limitata su dati che arrivano dal config dell'utente è una perdita di
    memoria lenta. `lru_cache` con `maxsize` la tiene sotto controllo: oltre il tetto le voci
    più vecchie escono, e il comportamento resta corretto (si ricompila, come prima della
    patch — solo per le frasi meno usate)."""
    info = mms._phrase_pattern.cache_info()
    assert info.maxsize is not None, "cache illimitata su input dell'utente"
    assert info.maxsize >= 1024, info          # sopra qualunque dizionario realistico
    # e continua a rispondere correttamente anche riempiendola oltre il tetto
    for i in range(info.maxsize + 100):
        mms._phrase_in_text(f"frase{i}", "mercato: frase42")
    assert mms._phrase_in_text("frase42", "mercato: frase42") is True
    assert mms._phrase_in_text("frase43", "mercato: frase42") is False
