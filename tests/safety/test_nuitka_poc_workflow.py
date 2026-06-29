"""Gate di sicurezza del PoC Nuitka (workflow `nuitka-poc.yaml` + driver core).

Il PoC Nuitka è un esperimento, NON la build di rilascio. Questi test bloccano in modo
deterministico e offline gli invarianti di sicurezza del PoC, così non possono regredire:

- il workflow parte SOLO manualmente (`workflow_dispatch`): mai su push/PR/tag/schedule,
  così non interferisce con la CI/release esistente;
- non crea release, non fa merge, non abilita auto-merge;
- ha permessi minimi (`contents: read`, mai `write`);
- il driver `tools/nuitka_poc_core.py` esercita la logica REALE del bridge (parser →
  normalizzazione quota → value-map) e ne verifica gli invarianti: se la logica core si
  rompe, il PoC (e questo test) falliscono.
"""

import importlib.util
import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKFLOW = os.path.join(_REPO_ROOT, ".github", "workflows", "nuitka-poc.yaml")
_DRIVER = os.path.join(_REPO_ROOT, "tools", "nuitka_poc_core.py")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _yaml_directives(path: str) -> str:
    """Testo del workflow SENZA commenti: righe `#…` rimosse e commenti inline ` #…`
    troncati. Così i guard valutano le direttive reali, non la prosa esplicativa (un
    commento «non fa auto-merge» non deve far scattare un match a sottostringa)."""
    out = []
    for ln in _read(path).splitlines():
        if ln.lstrip().startswith("#"):
            continue
        out.append(re.sub(r"\s#.*$", "", ln))
    return "\n".join(out)


def _load_driver():
    """Carica il driver PoC come modulo dal path (tools/ non è un package)."""
    spec = importlib.util.spec_from_file_location("nuitka_poc_core", _DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_workflow_e_driver_esistono():
    assert os.path.isfile(_WORKFLOW), "manca .github/workflows/nuitka-poc.yaml"
    assert os.path.isfile(_DRIVER), "manca tools/nuitka_poc_core.py"


def test_trigger_solo_manuale():
    """`on:` deve contenere `workflow_dispatch` e NESSUN trigger automatico."""
    text = _read(_WORKFLOW)
    assert re.search(r"(?m)^\s*workflow_dispatch:\s*$", text), \
        "il PoC deve avere il trigger manuale workflow_dispatch"
    for forbidden in ("push", "pull_request", "schedule", "release"):
        assert not re.search(r"(?m)^\s*" + forbidden + r":\s*$", text), \
            f"il PoC NON deve attivarsi su '{forbidden}' (solo workflow_dispatch)"
    # nessun riferimento a tag/branch di trigger
    assert not re.search(r"(?m)^\s*tags:\s*", text), "il PoC non deve filtrare per tag"
    assert not re.search(r"(?m)^\s*branches:\s*", text), "il PoC non deve filtrare per branch"


def test_niente_release_ne_merge():
    """Il PoC non pubblica release né tocca il merge/auto-merge: nessuna di queste
    azioni/chiamate nelle DIRETTIVE (i commenti possono spiegarlo a parole)."""
    low = _yaml_directives(_WORKFLOW).casefold()
    for needle in ("action-gh-release", "softprops", "enable_pr_auto_merge",
                   "merge_pull_request"):
        assert needle not in low, f"il PoC non deve usare '{needle}'"


def test_permessi_minimi():
    """Permessi di sola lettura: il PoC non scrive sul repo."""
    text = _read(_WORKFLOW)
    assert re.search(r"(?m)^\s*contents:\s*read\s*$", text), \
        "il PoC deve dichiarare permissions: contents: read"
    assert not re.search(r"(?m)^\s*contents:\s*write\s*$", text), \
        "il PoC NON deve avere contents: write"


def test_driver_esercita_logica_reale():
    """Il driver chiama il parser REALE e verifica gli invarianti core (incl. quota
    virgola→punto). È la stessa logica compilata da Nuitka nel job core-smoke."""
    mod = _load_driver()
    parsed = mod.run_core_checks()   # solleva AssertionError se la logica diverge
    assert parsed["signal_type"] == "OVER 2.5"
    assert parsed["teams"] == "Inter v Milan"
    assert parsed["quota"] == "1.85"      # da "1,85": normalizzazione virgola→punto
    assert parsed["live"] is True


def test_driver_non_richiede_gui_telegram_token():
    """Il driver PoC deve restare puro: nessun IMPORT di GUI/Telegram (i commenti possono
    nominarli), e nessun token Telegram in chiaro."""
    src = _read(_DRIVER)
    for mod in ("tkinter", "customtkinter", "telegram"):
        assert not re.search(r"(?m)^\s*(?:import|from)\s+" + mod + r"\b", src), \
            f"il driver PoC non deve importare {mod}"
    # nessun pattern token Telegram in chiaro
    assert not re.search(r"[0-9]{8,10}:[A-Za-z0-9_-]{35}", src)
