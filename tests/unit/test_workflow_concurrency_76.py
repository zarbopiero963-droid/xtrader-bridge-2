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


# ── P3-34 + P3-35 (PR successiva): suite doppia commit-gate/pr-checks ────────────────────────

def test_commit_gate_non_gira_sui_push_di_main():
    """P3-34 #76: i push su main/master eseguono già l'intero set di pr-checks (superset
    del gate): commit-gate deve ignorarli, o ogni merge paga la suite due volte."""
    text = _text("commit-gate")
    assert re.search(r"^\s*branches-ignore:\s*\[main,\s*master\]\s*$", text, re.MULTILINE), (
        "commit-gate.yml: manca branches-ignore [main, master] sul trigger push")


def test_commit_gate_salta_se_esiste_pr_aperta_fail_open():
    """P3-34 #76: su branch con PR aperta la suite gira già in pr-checks — il gate va
    saltato. La skip-logic deve essere FAIL-OPEN (errore API → suite eseguita comunque:
    può solo costare minuti, mai perdere copertura) e senza interpolazione `${{ }}`
    dentro lo script (script-injection: branch/repo dalle env del runner)."""
    text = _text("commit-gate")
    assert re.search(r"^\s*pull-requests:\s*read\s*$", text, re.MULTILINE), (
        "commit-gate.yml: serve pull-requests: read per interrogare le PR aperte")
    assert re.search(r"^\s*pr-open-check:\s*$", text, re.MULTILINE)
    assert re.search(r"^\s*needs:\s*pr-open-check\s*$", text, re.MULTILINE)
    assert "if: needs.pr-open-check.outputs.has_pr != 'true'" in text, (
        "commit-gate.yml: la suite deve saltare SOLO con has_pr == true (fail-open)")
    assert "|| echo 0" in text, (
        "commit-gate.yml: fallback fail-open assente — un errore API deve valere "
        "«nessuna PR» (suite eseguita), mai skip")
    # niente interpolazione GitHub-expression del ref dentro lo script (injection):
    script = text[text.index("pr-open-check"):]
    assert "${{ github.ref_name" not in script and "${{ github.head_ref" not in script, (
        "commit-gate.yml: il branch deve arrivare dalle env del runner, non da ${{ }}")
    assert "${GITHUB_REF_NAME}" in script


def test_concurrency_anche_su_commit_gate_e_pr_checks():
    """P3-35 #76: anche i due workflow di test su ubuntu cancellano le run stantie.
    commit-gate raggruppa per ref (gira solo su branch senza PR); pr-checks per PR con
    fallback sha (pattern PR #84: push su main mai cancellati tra loro)."""
    for prefix, key in (("commit-gate", "github.ref"),
                        ("pr-checks", "github.event.pull_request.number || github.sha")):
        block = _concurrency_block(prefix)
        assert block is not None, f"{prefix}.yml: blocco concurrency assente"
        assert re.search(r"^\s*cancel-in-progress:\s*true\s*$", block, re.MULTILINE), (
            f"{prefix}.yml: cancel-in-progress assente")
        m = re.search(r"^\s*group:\s*(.+)$", block, re.MULTILINE)
        assert m and m.group(1).startswith(prefix + "-"), (
            f"{prefix}.yml: prefisso di gruppo «{prefix}-» assente (collisione tra workflow)")
        assert key in m.group(1), f"{prefix}.yml: chiave di gruppo attesa «{key}»"


def test_pr_open_check_conta_solo_le_liste():
    """Review GPT PR #86 (bloccante reale): con 401/403/rate-limit l'API /pulls risponde
    con un OGGETTO JSON ({"message": ...}) e `len(dict)` conta le chiavi (>0) →
    `has_pr=true` → suite SALTATA proprio quando l'API è rotta: fail-open violato.
    Il one-liner REALE del workflow deve contare solo le liste (dict/errore → 0)."""
    import subprocess
    text = _text("commit-gate")
    m = re.search(r'python3 -c "([^"]+)"', text)
    assert m, "commit-gate.yml: one-liner python del pr-open-check non trovato"
    snippet = m.group(1)
    assert "isinstance" in snippet, (
        "commit-gate.yml: il conteggio deve distinguere lista (PR) da oggetto (errore API)")

    def run(payload):
        return subprocess.run(["python3", "-c", snippet], input=payload,
                              capture_output=True, text=True)

    assert run("[]").stdout.strip() == "0"                         # nessuna PR
    assert run('[{"number": 1}]').stdout.strip() == "1"            # PR aperta
    assert run('{"message": "Bad credentials"}').stdout.strip() == "0"   # errore API → 0
    assert run("non-json").returncode != 0                         # invalido → || echo 0
