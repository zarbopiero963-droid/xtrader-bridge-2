"""B6 + B22 (#194 PR-E-overflow · #192 M3 · #191 A1 · #193) — un numero enorme in
`config.json` o in uno stato persistito non deve far crashare il bridge.

Il difetto. `float(intero_enorme)` solleva **`OverflowError`**, che NON è sottoclasse di
`ValueError`. Ogni sito che scrive::

    try:
        f = float(value)
    except (TypeError, ValueError):
        ...

lascia quindi passare l'eccezione. E l'input è raggiungibile: `json.loads` accetta senza
protestare un intero di 400 cifre, quindi basta un `config.json` editato a mano (o un file
di stato manomesso) perché quel valore arrivi fin lì.

    >>> float(int("9" * 400))
    OverflowError: int too large to convert to float

Perché conta più di un crash. Due dei siti sono sul percorso **START**, e uno è il **tetto
anti-overbetting** (`max_active_signals`): un valore malformato lo instradava a `0`, che in
questo modulo significa **illimitato**. Il presidio si spegneva da solo, in silenzio — la
stessa forma del bug della revoca (#235), dove il controllo di sicurezza mostrava verde
mentre era già scattato.

La fonte unica esiste già e fa la cosa giusta: `validators.require_finite_now` e
`require_positive_int` catturano `OverflowError` dalla #318 L1-1, con la motivazione
scritta. Gli otto siti non la usavano — avevano ognuno la propria `float()` con la tupla
stretta. La correzione è farli delegare, non aggiungere `OverflowError` in otto posti (che
sarebbero otto copie destinate a divergere: è la Regola 3).

I due `load_state` sono la stessa famiglia vista da un altro ingresso: non un numero
enorme ma un file **annidato** migliaia di livelli, che fa sollevare `RecursionError` a
`json` — anch'esso fuori dalla tupla, e anch'esso allo START senza `try`.
"""

import json
import math
import os

import pytest

from xtrader_bridge import (confirmation_reader, journal_view, safety_guard,
                            settings_controller, signal_dedupe, signal_queue)

# Un intero che `json.loads` accetta e che `float()` non può rappresentare.
# 400 cifre: ben oltre ~1.8e308, il massimo di un float a doppia precisione.
ENORME = int("9" * 400)

# Le classi che un input ostile può sollevare e che NON sono `ValueError`.
FUORI_TUPLA = (OverflowError, RecursionError)


def _json_annidato(livelli: int = 3000) -> str:
    """Un JSON valido ma annidato: `json` decodifica ricorsivamente → `RecursionError`."""
    return '{"entries": ' + "[" * livelli + "]" * livelli + "}"


# ── ① la coda segnali: timeout letto dal config allo START ───────────────────

def test_timeout_from_config_regge_un_intero_enorme():
    """`clear_delay` enorme in `config.json` non deve far esplodere lo START.

    `timeout_from_config` è chiamata all'avvio della sessione: se solleva, il bridge non
    parte — e l'utente non ha modo di capire che è colpa di un numero scritto male.
    """
    cfg = {"clear_delay": ENORME}

    valore = signal_queue.timeout_from_config(cfg)

    assert valore == signal_queue.DEFAULT_TIMEOUT, (
        "un timeout illeggibile deve ricadere sul default, non propagare")


# ── ② il TETTO ANTI-OVERBETTING ──────────────────────────────────────────────

def test_max_active_malformato_non_disattiva_il_tetto():
    """Il punto più importante del file.

    In questo modulo `0` significa **illimitato**. Instradare un valore malformato a `0`
    non è «fail-safe»: è disattivare il presidio anti-overbetting proprio quando la
    configurazione è sospetta. Un `max_active_signals` scritto male deve ricadere sul
    **default 2** (`config_store.DEFAULTS`), non su «nessun limite».
    """
    ottenuto = signal_queue.SignalQueue._validate_max_active(ENORME)

    assert ottenuto != 0, "un valore malformato ha DISATTIVATO il tetto (0 = illimitato)"
    assert ottenuto == 2, f"atteso il default 2, ottenuto {ottenuto!r}"


@pytest.mark.parametrize("malformato", [float("nan"), float("inf"), -1, 1.5, "x", None, True])
def test_ogni_valore_malformato_ricade_sul_default_non_su_illimitato(malformato):
    """La stessa regola per TUTTA la classe dei malformati, non solo per l'intero enorme.

    Senza questo, la correzione chiuderebbe un solo ingresso lasciando aperti gli altri —
    esattamente il difetto che le cinque regole anti-regressione esistono per impedire.
    """
    assert signal_queue.SignalQueue._validate_max_active(malformato) == 2


def test_default_max_active_allineato_al_config_store():
    """`DEFAULT_MAX_ACTIVE` è una copia deliberata di `config_store.DEFAULTS`, tenuta in
    lockstep — stesso presidio dell'AC-B43 su `DEFAULT_TIMEOUT`/`MAX_TIMEOUT`.

    Rilievo di Fable 5 sulla PR #243, giusto e per la ragione precisa che indicava: senza
    questo test la copia diverge alla prima modifica del default, e la divergenza
    sposterebbe **il tetto anti-overbetting** senza che nessuno se ne accorga. Il valore è
    duplicato per non legare un modulo puro al layer di configurazione; duplicare è
    accettabile solo se qualcosa fallisce quando le due copie si separano.
    """
    from xtrader_bridge import config_store

    assert signal_queue.DEFAULT_MAX_ACTIVE == config_store.DEFAULTS["max_active_signals"], (
        "DEFAULT_MAX_ACTIVE e config_store.DEFAULTS['max_active_signals'] sono divergenti: "
        "un valore malformato ricadrebbe su un tetto diverso da quello di default")


def test_lo_zero_ESPLICITO_resta_illimitato():
    """Contro-guardia: la correzione NON deve cambiare il significato di `0`.

    `0` scritto apposta dall'utente vuol dire «nessun tetto» ed è documentato. Se questo
    test diventasse rosso, avrei cambiato un comportamento voluto invece di chiudere un
    crash — che è fuori dallo scope di questa PR.
    """
    assert signal_queue.SignalQueue._validate_max_active(0) == 0
    assert signal_queue.SignalQueue._validate_max_active(5) == 5


# ── ③ timeout e now della coda: fail-fast, ma con l'eccezione GIUSTA ─────────

def test_validate_timeout_solleva_ValueError_non_OverflowError():
    """Il docstring promette «si fallisce subito» con `ValueError`. Un `OverflowError`
    rompe quel contratto: i chiamanti che catturano `ValueError` non lo vedono passare."""
    with pytest.raises(ValueError):
        signal_queue.SignalQueue._validate_timeout(ENORME)


def test_resolve_now_solleva_ValueError_non_OverflowError():
    with pytest.raises(ValueError):
        signal_queue.SignalQueue._resolve_now(ENORME)


# ── ④ deduplica: il percorso di recovery non deve mai crashare ───────────────

def test_restore_state_con_now_enorme_non_crasha_il_recovery():
    """`restore_state` è sul percorso di ripristino dopo un riavvio.

    Il suo stesso commento dice che la persistenza «NON deve MAI crashare lo START» e per
    questo sceglie il fallback invece di `require_finite_now` che solleva. Ma la tupla
    stretta lasciava passare `OverflowError`, quindi la promessa non era mantenuta.
    """
    tracker = signal_dedupe.SignalTracker(60)

    tracker.restore_state({"entries": {}}, now=ENORME)   # non deve sollevare


# ── ⑤ i due load_state chiamati allo START senza try ────────────────────────

def test_load_state_dedupe_su_file_annidato_non_crasha_lo_start(tmp_path):
    """`app._start` chiama `signal_dedupe.load_state` **senza `try`** (app.py:3121).

    Il commento sopra quella riga promette: «Avvisa solo se lo stato ESISTE ma non è
    caricabile». Con un file ostile l'avviso non veniva mai raggiunto — l'eccezione
    risaliva e lo START falliva. Il contratto è un `bool`, non un'eccezione.
    """
    percorso = tmp_path / "dedupe_state.json"
    percorso.write_text(_json_annidato(), encoding="utf-8")
    tracker = signal_dedupe.SignalTracker(60)

    esito = signal_dedupe.load_state(tracker, str(percorso))

    assert esito is False, "un file illeggibile deve dare False, non sollevare"


def test_load_state_daily_su_file_annidato_non_crasha_lo_start(tmp_path):
    """Gemello del precedente su `safety_guard.load_state` (app.py:3141).

    Trovato dal grep della CLASSE, non dal rapporto: correggere solo il sito segnalato
    avrebbe lasciato vivo questo, che sta sullo stesso percorso di avvio.
    """
    percorso = tmp_path / "daily_state.json"
    percorso.write_text(_json_annidato(), encoding="utf-8")
    daily = safety_guard.DailyLimiter(10)

    safety_guard.load_state(daily, str(percorso))   # best-effort: non deve sollevare


# ── ⑥ gli altri tre siti misurati ───────────────────────────────────────────

def test_coerce_int_display_regge_un_intero_enorme():
    """GUI impostazioni: un valore illeggibile mostra il default, non chiude la finestra."""
    assert settings_controller._coerce_int_display(ENORME, 2) == 2


def test_require_finite_solleva_ValueError_non_OverflowError():
    """`confirmation_reader._require_finite` promette «altrimenti ValueError»."""
    with pytest.raises(ValueError):
        confirmation_reader._require_finite(ENORME, "timestamp")


def test_ts_value_del_diario_regge_un_intero_enorme():
    """Il visualizzatore del diario non deve morire su un evento con un `ts` assurdo:
    è uno strumento di diagnosi, e serve proprio quando qualcosa è andato storto."""
    journal_view._ts_value({"ts": ENORME})   # non deve sollevare


# ── ⑦ guardie sul corpus: il veleno è ancora veleno? ────────────────────────

def test_il_veleno_solleva_ancora_le_classi_attese():
    """Se un domani CPython smettesse di sollevare queste classi, TUTTI i test sopra
    diventerebbero verdi **senza esercitare nulla**. Questo test lo dice invece di tacere.
    """
    with pytest.raises(OverflowError):
        float(ENORME)

    with pytest.raises(RecursionError):
        json.loads(_json_annidato())

    # …e che nessuna delle due sia catturabile con la tupla stretta di partenza:
    for classe in FUORI_TUPLA:
        assert not issubclass(classe, (TypeError, ValueError)), (
            f"{classe.__name__} è diventata sottoclasse di ValueError: "
            "la premessa di questa PR non vale più")


def test_json_accetta_davvero_un_intero_di_400_cifre():
    """La raggiungibilità è metà del difetto: senza questa, i test sopra proverebbero
    solo che una funzione regge un input che nessuno può fornirle."""
    assert json.loads("9" * 400) == ENORME
