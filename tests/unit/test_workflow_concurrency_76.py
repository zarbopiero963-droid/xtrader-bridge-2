"""P2-10 + P3-33 audit #76 — niente run CI duplicate dagli eventi `labeled` della coppia
di label finali.

Bug: `final-fable-review` + `final-fugu-review` aggiunte insieme emettono DUE eventi
`labeled`; `windows-tests.yml` (runner Windows, minuti 2×) e `merge-simulation.yml`
partono su `labeled` con un `if` che controlla la PRESENZA di una label di collaudo —
non quale label ha scatenato l'evento — e senza `concurrency` giravano DUE run complete
identiche sullo stesso SHA.

Fix testato: blocco `concurrency` con gruppo per PR (fallback `github.sha` per push su
main/dispatch: run di commit diversi non si cancellano mai tra loro) e
`cancel-in-progress: true` (il doppione supera la prima run; un push nuovo cancella la
run stantia del head precedente).

I test leggono il TESTO reale dei workflow con regex — come `test_workflow_pins.py` —
perché PyYAML non è tra le dipendenze del progetto (la prima versione con `import yaml`
ha rotto la collection in CI: niente nuove dipendenze per un test)."""

import re
from pathlib import Path

_WF_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# I due workflow «label-triggered a suite intera» coperti dal fix (P2-10 / P3-33).
_DEDUPED = ("windows-tests", "merge-simulation")


def _text(prefix):
    return (_WF_DIR / f"{prefix}.yml").read_text(encoding="utf-8")


def _concurrency_block(prefix):
    """Il blocco `concurrency:` top-level (fino alla prossima chiave a colonna 0)."""
    m = re.search(r"^concurrency:\n((?:[ \t]+\S.*\n)+)", _text(prefix), re.MULTILINE)
    return m.group(1) if m else None


def test_concurrency_presente_con_cancel_in_progress():
    for prefix in _DEDUPED:
        block = _concurrency_block(prefix)
        assert block is not None, (
            f"{prefix}.yml: manca il blocco `concurrency` — i due eventi `labeled` della "
            f"coppia di label finali tornerebbero a duplicare la suite (P2-10/P3-33 #76)")
        assert re.search(r"^\s*cancel-in-progress:\s*true\s*$", block, re.MULTILINE), (
            f"{prefix}.yml: senza cancel-in-progress il doppione si accoda e gira comunque")


def test_gruppo_per_pr_con_fallback_sha():
    """Il gruppo deve dedupare per PR (i due `labeled` condividono il numero PR) e avere
    il fallback su `github.sha` per push/dispatch (gruppi distinti per commit: run di
    main di commit diversi non si cancellano a vicenda)."""
    for prefix in _DEDUPED:
        block = _concurrency_block(prefix)
        assert block is not None, f"{prefix}.yml: blocco concurrency assente"
        m = re.search(r"^\s*group:\s*(.+)$", block, re.MULTILINE)
        assert m, f"{prefix}.yml: `group:` assente nel blocco concurrency"
        group = m.group(1)
        assert "github.event.pull_request.number" in group, (
            f"{prefix}.yml: gruppo senza numero PR — i due eventi `labeled` non collassano")
        assert "github.sha" in group, (
            f"{prefix}.yml: gruppo senza fallback sha — push main/dispatch finirebbero "
            f"tutti nello stesso gruppo e si cancellerebbero tra loro")


def test_gruppi_distinti_tra_workflow():
    """I gruppi devono avere un prefisso univoco per workflow: senza, windows-tests e
    merge-simulation della stessa PR si cancellerebbero A VICENDA."""
    groups = {}
    for prefix in _DEDUPED:
        m = re.search(r"^\s*group:\s*(.+)$", _concurrency_block(prefix) or "",
                      re.MULTILINE)
        assert m, f"{prefix}.yml: group assente"
        groups[prefix] = m.group(1)
        assert m.group(1).startswith(prefix + "-"), (
            f"{prefix}.yml: il gruppo deve iniziare con «{prefix}-» per non collidere "
            f"con altri workflow della stessa PR")
    assert len(set(groups.values())) == len(groups), "gruppi identici tra workflow diversi"


def test_trigger_e_gate_label_invariati():
    """La patch tocca SOLO la concurrency: trigger `labeled/synchronize/reopened` e l'if
    sulla presenza delle label di collaudo devono restare invariati (il gate finale deve
    continuare a partire con le label)."""
    for prefix in _DEDUPED:
        text = _text(prefix)
        assert re.search(r"^\s*types:\s*\[labeled,\s*synchronize,\s*reopened\]\s*$",
                         text, re.MULTILINE), (
            f"{prefix}.yml: trigger pull_request `labeled/synchronize/reopened` cambiato")
        for label in ("ci-full", "final-fable-review", "final-fugu-review"):
            assert (f"'{label}'" in text) or (f'"{label}"' in text), (
                f"{prefix}.yml: gate label «{label}» sparito dall'if")
