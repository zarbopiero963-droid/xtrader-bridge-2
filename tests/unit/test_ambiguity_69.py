"""Guard delle ambiguità di naming risolte — issue #69.

Il report della #69 elenca funzioni con **nome uguale e contratto diverso**: il pericolo non è
un bug vivo, è che una modifica futura chiami quella sbagliata. Rinominare le risolve *oggi*;
questi test le tengono risolte *domani*, fallendo se qualcuno reintroduce il nome ambiguo.

Coperte qui:

- **A2** — `recognition.is_valid` → `fields_complete`. Aveva la **stessa firma posizionale**
  `(row, mode)` di `validator.is_valid`, ma controlla solo la **presenza** dei campi: usare il
  debole dove serve il forte fa passare verso il CSV una riga con `Price`/`BetType` malformato.
- **A3** — `health_check.evaluate` → `build_semaphores` e `live_guard.evaluate` → `decide_write`.
  Due `evaluate` di cui uno **governa la doppia scommessa** e l'altro è pura diagnostica UI.

I test esercitano le funzioni REALI: se un domani i due contratti convergessero (es. rendere
`fields_complete` una validazione completa) `test_debole_e_forte_restano_diversi` diventerebbe
rosso, perché la differenza fra i due è proprio ciò che rende necessari due nomi.
"""

import ast
import pathlib

import pytest

from xtrader_bridge import health_check, live_guard, recognition, validator

# Riga completa nei CAMPI richiesti da NAME_ONLY ma con **prezzo non numerico**: è esattamente
# il caso che distingue il controllo debole (presenza) da quello forte (validazione).
_ROW_PREZZO_ROTTO = {
    "EventName": "Inter v Milan",
    "MarketType": "OVER_UNDER_25",
    "MarketName": "Over/Under 2,5 gol",
    "SelectionName": "Over 2,5 goal",
    "BetType": "PUNTA",
    "Price": "non-un-numero",
}


# ── A2 — presenza dei campi ≠ validazione ────────────────────────────────────────────────────────
def test_nome_ambiguo_is_valid_non_esiste_piu_in_recognition():
    """`recognition.is_valid` non deve tornare: il nome collideva con `validator.is_valid`."""
    assert not hasattr(recognition, "is_valid"), (
        "reintrodotto `recognition.is_valid`: collide con `validator.is_valid`, stessa firma "
        "(row, mode) ma contratto molto più debole — usa `fields_complete`"
    )
    assert callable(recognition.fields_complete)


def test_debole_e_forte_restano_diversi():
    """La riga ha tutti i campi ma un prezzo non numerico: **completa** ma **non valida**.

    È la dimostrazione per cui servono due nomi. Se questo test diventa rosso, o il debole è
    stato irrobustito o il forte indebolito: in entrambi i casi va deciso a mano, non subito."""
    assert recognition.fields_complete(_ROW_PREZZO_ROTTO, "NAME_ONLY") is True
    assert validator.is_valid(_ROW_PREZZO_ROTTO, "NAME_ONLY") is False


def test_fields_complete_rileva_i_campi_mancanti():
    """Il controllo debole fa comunque il suo mestiere: manca un campo → `False`."""
    senza_evento = {k: v for k, v in _ROW_PREZZO_ROTTO.items() if k != "EventName"}
    assert recognition.fields_complete(senza_evento, "NAME_ONLY") is False


# ── A3 — diagnostica UI ≠ gate di scrittura ──────────────────────────────────────────────────────
def test_nome_ambiguo_evaluate_non_esiste_piu():
    """Nessuno dei due moduli deve riesporre `evaluate`: era il nome generico condiviso fra la
    diagnostica dei semafori e la decisione che governa la doppia scommessa."""
    assert not hasattr(health_check, "evaluate"), \
        "reintrodotto `health_check.evaluate`: usa `build_semaphores`"
    assert not hasattr(live_guard, "evaluate"), \
        "reintrodotto `live_guard.evaluate`: usa `decide_write`"
    assert callable(health_check.build_semaphores) and callable(live_guard.decide_write)


def test_build_semaphores_e_diagnostica_pura():
    """`build_semaphores` produce i sette semafori e **non decide nulla**: nessun esito di
    scrittura fra i valori possibili."""
    items = health_check.build_semaphores()
    assert len(items) == 7
    stati = {i.state for i in items}
    assert stati <= {health_check.GREEN, health_check.YELLOW, health_check.RED}
    esiti_di_scrittura = {live_guard.WRITE, live_guard.DUPLICATE, live_guard.RATE_LIMITED,
                          live_guard.DAILY_LIMITED, live_guard.DRY_RUN}
    assert not (stati & esiti_di_scrittura), "la diagnostica non deve produrre esiti di scrittura"


def test_decide_write_e_il_gate_di_scrittura():
    """`decide_write` ritorna un esito del percorso di scrittura — e in assenza di modalità reale
    esplicita ripiega su `DRY_RUN` (fail-closed), non su un semaforo."""
    from xtrader_bridge import signal_dedupe
    tracker = signal_dedupe.SignalTracker(dedupe_window=60, max_per_minute=10)
    esito = live_guard.decide_write({}, tracker, None, "Inter v Milan", now=1000)
    assert esito == live_guard.DRY_RUN
    assert esito not in (health_check.GREEN, health_check.YELLOW, health_check.RED)


@pytest.mark.parametrize("modulo, atteso", [(health_check, "build_semaphores"),
                                            (live_guard, "decide_write"),
                                            (recognition, "fields_complete")])
def test_i_nomi_nuovi_sono_esportati(modulo, atteso):
    """Rete anti-refuso: il nome nuovo esiste davvero (un typo nella rinomina non passa)."""
    assert hasattr(modulo, atteso), f"{modulo.__name__} deve esporre `{atteso}`"


# ── source-scan: nessun chiamante residuo, ovunque nel package ───────────────────────────────────
# Vecchi nomi qualificati che NON devono più comparire in un sorgente del package. Il `not hasattr`
# qui sopra dice che l'attributo non esiste; questo dice che **nessuno lo chiama** — che è la
# domanda vera (rilievo Fugu Ultra #160: un residuo in un ramo raro darebbe `AttributeError` solo
# a runtime, magari sul percorso di scrittura, dove costa di più).
_CHIAMATE_VIETATE = ("health_check.evaluate(", "live_guard.evaluate(", "recognition.is_valid(")
_PKG_DIR = pathlib.Path(__file__).resolve().parents[2] / "xtrader_bridge"


def test_nessun_chiamante_residuo_dei_nomi_vecchi():
    """Scandisce **tutti** i sorgenti del package (ricorsivo, sottopackage inclusi) e vieta le
    chiamate ai nomi rimossi.

    Perché serve oltre al `not hasattr`: quello prova che il nome non esiste più sul modulo, non
    che nessuno provi a usarlo. Un chiamante dimenticato in un ramo poco percorso passerebbe i
    test e romperebbe **a runtime**. Qui la CI fa a ogni push il grep che altrimenti resterebbe
    una verifica una-tantum fatta a mano."""
    offenders = []
    scanned = sorted(_PKG_DIR.rglob("*.py"))
    for path in scanned:
        testo = path.read_text(encoding="utf-8")
        for vietata in _CHIAMATE_VIETATE:
            if vietata in testo:
                offenders.append(f"{path.relative_to(_PKG_DIR.parent)}: {vietata}")
    assert not offenders, (
        "chiamate a nomi rimossi (#69) — darebbero AttributeError a runtime:\n  "
        + "\n  ".join(offenders))
    # Lo scan deve essere ricorsivo: senza questa asserzione un ritorno silenzioso a `glob("*.py")`
    # perderebbe i sottopackage (es. `licensing/`) e passerebbe INVISIBILE.
    assert [p for p in scanned if p.parent != _PKG_DIR and p.parent.name != "__pycache__"], \
        "lo scan deve raggiungere i sottopackage del package, non solo i moduli top-level"


def test_il_source_scan_non_passa_a_vuoto():
    """Meta-check: lo scan riconosce davvero una chiamata vietata sintetica (se un domani il
    confronto smettesse di funzionare, questo test lo direbbe invece di restare verde)."""
    finto = "x = health_check.evaluate(listener_status='ATTIVO')\n"
    assert any(v in finto for v in _CHIAMATE_VIETATE)


# Nomi vecchi per modulo di provenienza: un `from .health_check import evaluate` sfuggirebbe al
# confronto testuale qui sopra, che cerca la forma QUALIFICATA (rilievo GPT-5.5 #160). Il modulo
# conta: `from .validator import is_valid` è legittimo — è il controllo forte, quello che resta.
_IMPORT_VIETATI = {"health_check": {"evaluate"}, "live_guard": {"evaluate"},
                   "recognition": {"is_valid"}}


def test_nessun_import_diretto_dei_nomi_vecchi():
    """Chiude la strada indiretta: `from .health_check import evaluate` (o un alias) porterebbe
    il nome rimosso nel namespace di un modulo senza mai scrivere la forma qualificata.

    AST e non regex, come `test_mode_namespacing`: i moduli GUI importano `customtkinter` e non
    sono importabili headless, quindi si analizza il **sorgente**."""
    offenders = []
    for path in sorted(_PKG_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            sorgente = node.module.rsplit(".", 1)[-1]
            vietati = _IMPORT_VIETATI.get(sorgente, ())
            for alias in node.names:
                if alias.name in vietati:
                    offenders.append(
                        f"{path.relative_to(_PKG_DIR.parent)}: from {node.module} import {alias.name}")
    assert not offenders, (
        "import di nomi rimossi (#69) — ImportError all'avvio del modulo:\n  " + "\n  ".join(offenders))
