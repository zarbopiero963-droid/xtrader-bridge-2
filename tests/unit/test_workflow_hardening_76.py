"""P3-36 + P3-37 audit #76 — hardening dei workflow build/notturni.

- **P3-36** (`merge-simulation-hard.yml`): il cron notturno girava OGNI notte su
  windows-latest (minuti 2×) anche con zero commit dal giorno prima (~600+ min/mese
  potenzialmente a vuoto). Fix: job-guard `fresh-commits-check` su ubuntu — nella run
  schedulata, ultimo commit più vecchio di 25h → hard-run saltata. FAIL-OPEN verso
  l'esecuzione: dispatch sempre eseguito; output vuoto/errore → run eseguita.
- **P3-37** (`build.yaml`): `contents: write` era a livello WORKFLOW (lo ereditavano
  tutti i job) e i checkout non disattivavano `persist-credentials`. Fix: workflow a
  sola lettura, write solo sul job `build` (release su tag v*), credenziali git non
  persistite su entrambi i checkout.

Regex su testo reale (pattern `test_workflow_pins`: PyYAML non è una dipendenza)."""

import re
from pathlib import Path

_WF_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _text(name):
    return (_WF_DIR / name).read_text(encoding="utf-8")


# ── P3-36: guard notturna su merge-simulation-hard ───────────────────────────────────────────

def test_hard_run_notturna_ha_la_guard_sui_commit_freschi():
    text = _text("merge-simulation-hard.yml")
    assert re.search(r"^\s*fresh-commits-check:\s*$", text, re.MULTILINE), (
        "merge-simulation-hard.yml: manca il job-guard fresh-commits-check — il cron "
        "notturno tornerebbe a bruciare minuti Windows 2× anche senza commit (P3-36 #76)")
    assert re.search(r"^\s*needs:\s*fresh-commits-check\s*$", text, re.MULTILINE)
    assert ("if: ${{ !cancelled() && "
            "needs.fresh-commits-check.outputs.has_new != 'false' }}") in text, (
        "merge-simulation-hard.yml: il gate deve essere `!cancelled() && ... != 'false'` "
        "— senza !cancelled() un job-guard FALLITO skippa `hard` per dipendenza fallita "
        "(review GPT #87); senza != 'false' l'output vuoto a guard verde farebbe skip")


def test_guard_notturna_fail_open_e_solo_su_schedule():
    """Il dispatch manuale è SEMPRE eseguito (il proprietario che lancia a mano non deve
    trovarsi la run saltata); la finestra è 25h (margine sul cron delle 03:00); e la
    guard usa la data del PUSH (`pushed_at`), non del commit (final review Fable #87:
    un rebase/cherry-pick pushato oggi con committer-date vecchie DEVE contare come
    lavoro nuovo — con `git log --since` la notturna lo salterebbe in silenzio)."""
    text = _text("merge-simulation-hard.yml")
    guard = text[text.index("fresh-commits-check"):text.index("  hard:")]
    assert '"${GITHUB_EVENT_NAME}" != "schedule"' in guard, (
        "merge-simulation-hard.yml: la guard deve valere SOLO per il cron (schedule)")
    assert "has_new=true" in guard.split("schedule")[1].split("fi")[0], (
        "merge-simulation-hard.yml: fuori dal cron l'output deve essere true (run sempre)")
    assert "pushed_at" in guard, (
        "merge-simulation-hard.yml: la guard deve confrontare la data del PUSH "
        "(pushed_at), non la data del commit")
    assert "--since" not in guard, (
        "merge-simulation-hard.yml: niente git log --since (commit-date: salterebbe "
        "rebase/cherry-pick retrodatati)")
    assert "25 * 3600" in guard
    # doppio fail-open: eccezione python → 'true', e crash dell'interprete → || echo true
    assert re.search(r"except Exception:\s*\n\s*print\('true'\)", guard), (
        "merge-simulation-hard.yml: l'except della guard deve stampare 'true' (fail-open)")
    assert '|| echo true' in guard, (
        "merge-simulation-hard.yml: fallback shell fail-open assente")


# ── P3-37: permessi minimi e credenziali non persistite su build.yaml ───────────────────────

def test_build_workflow_di_default_in_sola_lettura():
    text = _text("build.yaml")
    m = re.search(r"^permissions:\n\s+contents:\s*(\w+)", text, re.MULTILINE)
    assert m and m.group(1) == "read", (
        "build.yaml: il default del workflow deve essere contents: read — il write "
        "lo eredita SOLO il job della release (P3-37 #76)")


def test_build_write_solo_sul_job_release():
    text = _text("build.yaml")
    build_job = text[text.index("  build:"):text.index("  build-linux:")]
    assert re.search(r"^\s*permissions:\s*\n\s*contents:\s*write(\s+#.*)?$", build_job,
                     re.MULTILINE), (
        "build.yaml: il job build deve avere contents: write a livello JOB "
        "(serve alla release su tag v*)")
    linux_job = text[text.index("  build-linux:"):]
    assert "contents: write" not in linux_job, (
        "build.yaml: build-linux non deve avere write (eredita il read del workflow)")


def test_build_checkout_senza_credenziali_persistite():
    text = _text("build.yaml")
    assert text.count("persist-credentials: false") >= 2, (
        "build.yaml: ENTRAMBI i checkout (build e build-linux) devono disattivare "
        "persist-credentials — nessuno step git usa il token dopo il checkout")
