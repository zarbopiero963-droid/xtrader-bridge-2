"""Wave-3 mode-namespacing (#114) — LOCK dei quattro `normalize_mode` distinti.

Il repository ha **quattro** funzioni chiamate `normalize_mode`, una per modulo, con lo
STESSO nome ma **namespace e contratti DIVERSI**:

| Modulo             | Modi validi                                       | Default su ignoto | Case |
|--------------------|---------------------------------------------------|-------------------|------|
| `recognition`      | ID_ONLY / NAME_ONLY / BOTH                         | `NAME_ONLY`       | **SENSIBILE** |
| `signal_queue`     | OVERWRITE_LAST / APPEND_ACTIVE / QUEUE_UNTIL_CONFIRMED | `OVERWRITE_LAST` | insensibile |
| `source_manager`   | PRE / LIVE                                         | `PRE`             | insensibile |
| `bridge_mode`      | SIMULAZIONE / COLLAUDO / REALE                    | `""` (fail-closed) | insensibile |

Non è un bug vivo: **tutti** i call-site usano la forma QUALIFICATA (`modulo.normalize_mode`),
mai `from ... import normalize_mode`, quindi non c'è collisione. È però un **footgun latente**:
sono quattro gate safety-critical (riconoscimento CSV, coda segnali, filtro sorgenti, modalità
di esecuzione) che un futuro "refactor di pulizia" potrebbe **unificare**, cambiando in
SILENZIO il comportamento di un gate. Esempi di regressioni pericolose che questi test bloccano:

- rendere `recognition.normalize_mode` case-insensitive → un `"both"` scritto a mano in
  `config.json` passerebbe da `NAME_ONLY` (default sicuro, richiede i nomi) a `BOTH` (più
  permissivo: basta ID **oppure** nomi) — allargamento silenzioso del gate di riconoscimento;
- far tornare `bridge_mode.normalize_mode` un default valido (es. `SIMULAZIONE`) invece di
  `""` → romperebbe `mode_from_cfg`, che si basa proprio sul `""` per distinguere
  "etichetta assente/sporca" da "COLLAUDO esplicito" (fail-closed sulla scrittura del CSV).

Questi test esercitano le funzioni REALI e falliscono se uno qualsiasi dei quattro contratti
divergenti viene alterato o unificato. `test_nessun_import_non_qualificato_di_normalize_mode`
congela invece la convenzione "accesso solo qualificato" scandendo il sorgente del package
(i moduli GUI importano `customtkinter` e non sono testabili headless → source-scan, come i
guard di palette dei PR redesign).
"""

import ast
import pathlib

import pytest

from xtrader_bridge import bridge_mode, recognition, signal_queue, source_manager

_PKG_DIR = pathlib.Path(__file__).resolve().parents[2] / "xtrader_bridge"


# ── 1. Ogni namespace ha modi validi/default DISTINTI (nessuna sovrapposizione) ──────────
def test_i_quattro_namespace_sono_disgiunti():
    """I quattro insiemi di modi validi NON si sovrappongono: sono namespace distinti.
    Se un domani due namespace condividessero un valore, un `normalize_mode` sbagliato
    accetterebbe silenziosamente un modo di un altro dominio."""
    sets = {
        "recognition": set(recognition.VALID_MODES),
        "signal_queue": set(signal_queue.MODES),
        "source_manager": set(source_manager.MODES),
        "bridge_mode": set(bridge_mode.VALID_MODES),
    }
    seen = {}
    for name, modes in sets.items():
        for m in modes:
            assert m not in seen, f"modo {m!r} condiviso tra {seen.get(m)} e {name}"
            seen[m] = name
    # I default sono ciascuno un valore del proprio dominio (tranne bridge_mode, che
    # fail-closa a "" — vedi test dedicato).
    assert recognition.DEFAULT_MODE in recognition.VALID_MODES
    assert signal_queue.DEFAULT_MODE in signal_queue.MODES
    assert source_manager.DEFAULT_MODE in source_manager.MODES


# ── 2. Contratto di recognition: CASE-SENSITIVE, default NAME_ONLY ───────────────────────
def test_recognition_e_case_sensitive_e_default_name_only():
    """`recognition.normalize_mode` è l'UNICO case-SENSITIVE (nessun strip/upper): un
    valore valido ma in minuscolo/con spazi ricade sul default sicuro `NAME_ONLY`. Il
    chiamante (`settings_controller.current_values`) pre-uppercasa APPOSTA per questo. Se
    qualcuno aggiungesse strip().upper() qui, quel pre-uppercase diventerebbe una toppa
    silenziosa e il gate cambierebbe comportamento sugli input a mano."""
    assert recognition.normalize_mode("BOTH") == recognition.BOTH
    assert recognition.normalize_mode("ID_ONLY") == recognition.ID_ONLY
    # case-sensitive: minuscolo e con spazi NON matchano → default sicuro
    assert recognition.normalize_mode("both") == recognition.NAME_ONLY
    assert recognition.normalize_mode("  BOTH  ") == recognition.NAME_ONLY
    # ignoto/mancante → default sicuro (mai eccezione)
    assert recognition.normalize_mode("xxx") == recognition.NAME_ONLY
    assert recognition.normalize_mode(None) == recognition.NAME_ONLY
    assert recognition.DEFAULT_MODE == recognition.NAME_ONLY


# ── 3. Contratto di signal_queue: case-insensitive, default OVERWRITE_LAST ────────────────
def test_signal_queue_case_insensitive_default_overwrite_last():
    """`signal_queue.normalize_mode` coercizza (strip+upper); ignoto → `OVERWRITE_LAST`
    (il default conservativo: un solo segnale attivo, minor rischio doppia scommessa)."""
    assert signal_queue.normalize_mode("append_active") == signal_queue.APPEND_ACTIVE
    assert signal_queue.normalize_mode("  Queue_Until_Confirmed ") == signal_queue.QUEUE_UNTIL_CONFIRMED
    assert signal_queue.normalize_mode("xxx") == signal_queue.OVERWRITE_LAST
    assert signal_queue.normalize_mode(None) == signal_queue.OVERWRITE_LAST
    assert signal_queue.DEFAULT_MODE == signal_queue.OVERWRITE_LAST


# ── 4. Contratto di source_manager: case-insensitive, default PRE ────────────────────────
def test_source_manager_case_insensitive_default_pre():
    """`source_manager.normalize_mode` coercizza (strip+upper via `is_valid_mode`);
    ignoto → `PRE`. La validazione (`validate_sources`) invece RIFIUTA l'ignoto: la
    coercizione qui è solo il fail-safe di runtime, non un canale per modi inventati."""
    assert source_manager.normalize_mode("live") == "LIVE"
    assert source_manager.normalize_mode("  Pre ") == "PRE"
    assert source_manager.normalize_mode("xxx") == source_manager.DEFAULT_MODE
    assert source_manager.normalize_mode(None) == "PRE"
    assert source_manager.DEFAULT_MODE == "PRE"


# ── 5. Contratto di bridge_mode: FAIL-CLOSED a "" (non un default valido) ─────────────────
def test_bridge_mode_fail_closed_a_stringa_vuota():
    """`bridge_mode.normalize_mode` è l'UNICO che su ignoto ritorna `""` (NON un modo
    valido): `mode_from_cfg` distingue proprio col `""` fra "etichetta assente/sporca"
    (→ decide `dry_run`) e "COLLAUDO esplicito". Se qui tornasse un default valido, la
    catena fail-closed sulla scrittura del CSV si romperebbe."""
    assert bridge_mode.normalize_mode("REALE") == bridge_mode.REALE
    assert bridge_mode.normalize_mode("reale") == bridge_mode.REALE     # str → case-insensitive
    assert bridge_mode.normalize_mode("  Collaudo ") == bridge_mode.COLLAUDO
    assert bridge_mode.normalize_mode("xxx") == ""
    assert bridge_mode.normalize_mode(None) == ""                       # non-str → ""
    assert bridge_mode.normalize_mode(123) == ""                        # non-str → ""
    assert "" not in bridge_mode.VALID_MODES


# ── 6. Nessuna delle quattro solleva su input malformato (fail-safe totale) ──────────────
@pytest.mark.parametrize("fn", [
    recognition.normalize_mode,
    signal_queue.normalize_mode,
    source_manager.normalize_mode,
    bridge_mode.normalize_mode,
])
@pytest.mark.parametrize("bad", [None, "", "   ", 0, 123, 4.5, [], {}, object()])
def test_nessuna_normalize_mode_solleva_su_input_sporco(fn, bad):
    """Contratto trasversale: qualunque input malformato → un valore (mai eccezione).
    Il valore è sempre un modo valido del proprio dominio OPPURE `""` (solo bridge_mode)."""
    out = fn(bad)
    assert isinstance(out, str)


# ── 7. LOCK della convenzione: `normalize_mode` si importa SOLO qualificato ───────────────
def test_nessun_import_non_qualificato_di_normalize_mode():
    """Congela la convenzione anti-collisione: nessun modulo del package fa
    `from <qualcosa> import normalize_mode` (che creerebbe un nome `normalize_mode`
    ambiguo nel namespace del modulo, con quattro semantiche diverse in gioco). Tutti
    i call-site devono usare la forma qualificata `modulo.normalize_mode`.

    Source-scan via AST (non regex): i moduli GUI importano `customtkinter` e non sono
    importabili headless, quindi si analizza il sorgente, come i guard di palette."""
    offenders = []
    for path in sorted(_PKG_DIR.rglob("*.py")):  # ricorsivo: copre i sottopackage (es. betfair/) — nit Fable #132
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "normalize_mode":
                        offenders.append(f"{path.name}: from {node.module} import normalize_mode")
    assert not offenders, (
        "import non qualificato di normalize_mode (userebbe UNA delle quattro semantiche in "
        "modo ambiguo). Usare `modulo.normalize_mode`:\n  " + "\n  ".join(offenders))


def test_il_source_scan_e_efficace_non_passa_a_vuoto():
    """Meta-check: il source-scan del test 7 DEVE segnalare un import non qualificato
    sintetico (così non passa 'a vuoto' se un domani l'AST non trovasse più nulla)."""
    src = "from xtrader_bridge.recognition import normalize_mode\n"
    tree = ast.parse(src)
    found = [
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]
    assert "normalize_mode" in found
