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
run stantia del head precedente). I test leggono lo YAML REALE dei workflow: se il
blocco sparisce o il gruppo perde la chiave-PR, falliscono.
"""

from pathlib import Path

import yaml

_WF_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# I due workflow «label-triggered a suite intera» coperti dal fix (P2-10 / P3-33).
_DEDUPED = {
    "windows-tests.yml": "windows-tests",
    "merge-simulation.yml": "merge-simulation",
}


def _load(name):
    return yaml.safe_load((_WF_DIR / name).read_text(encoding="utf-8"))


def test_yaml_valido():
    for name in _DEDUPED:
        assert isinstance(_load(name), dict), f"{name}: YAML non parsabile"


def test_concurrency_presente_con_cancel_in_progress():
    for name in _DEDUPED:
        wf = _load(name)
        conc = wf.get("concurrency")
        assert isinstance(conc, dict), (
            f"{name}: manca il blocco `concurrency` — i due eventi `labeled` della coppia "
            f"di label finali tornerebbero a duplicare la suite (P2-10/P3-33 #76)")
        assert conc.get("cancel-in-progress") is True, (
            f"{name}: senza cancel-in-progress il doppione si accoda e gira comunque")


def test_gruppo_per_pr_con_fallback_sha():
    """Il gruppo deve dedupare per PR (i due `labeled` condividono il numero PR) e avere
    il fallback su `github.sha` per push/dispatch (gruppi distinti per commit: run di
    main di commit diversi non si cancellano a vicenda)."""
    for name in _DEDUPED:
        group = _load(name)["concurrency"]["group"]
        assert "github.event.pull_request.number" in group, (
            f"{name}: gruppo senza numero PR — i due eventi `labeled` non collassano")
        assert "github.sha" in group, (
            f"{name}: gruppo senza fallback sha — push main/dispatch finirebbero tutti "
            f"nello stesso gruppo e si cancellerebbero tra loro")


def test_gruppi_distinti_tra_workflow():
    """I gruppi devono avere un prefisso univoco per workflow: senza, windows-tests e
    merge-simulation della stessa PR si cancellerebbero A VICENDA."""
    groups = {name: _load(name)["concurrency"]["group"] for name in _DEDUPED}
    for name, prefix in _DEDUPED.items():
        assert groups[name].startswith(prefix + "-"), (
            f"{name}: il gruppo deve iniziare con «{prefix}-» per non collidere con "
            f"altri workflow della stessa PR")
    assert len(set(groups.values())) == len(groups), "gruppi identici tra workflow diversi"


def test_trigger_e_gate_label_invariati():
    """La patch tocca SOLO la concurrency: trigger `labeled/synchronize/reopened` e l'if
    sulla presenza delle label di collaudo devono restare invariati (il gate finale deve
    continuare a partire con le label)."""
    for name in _DEDUPED:
        wf = _load(name)
        # PyYAML parsa la chiave `on:` come booleano True (yaml 1.1).
        triggers = wf.get("on", wf.get(True))
        assert "labeled" in triggers["pull_request"]["types"]
        assert "synchronize" in triggers["pull_request"]["types"]
        job = next(iter(wf["jobs"].values()))
        for label in ("ci-full", "final-fable-review", "final-fugu-review"):
            assert label in job.get("if", ""), f"{name}: gate label «{label}» sparito"
