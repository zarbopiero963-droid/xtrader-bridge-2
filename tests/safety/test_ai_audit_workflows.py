"""Gate di sicurezza dei workflow AI (PR review + full-repo audit).

I 4 workflow AI (`openai-gpt-pr-review.yml`, `claude-fable-pr-review.yml`,
`manual-full-repo-ai-audit.yml`, `claude-fable-full-repo-audit.yml`) inviano
diff/contenuti del repository a servizi esterni (OpenAI/Anthropic). Le regole
non negoziabili che questo gate difende, in modo deterministico e offline:

- **read-only**: nessun checkout nei PR review, nessun permesso di scrittura
  sul contenuto (`contents: read`; solo `issues: write` per il commento PR);
- **niente `pull_request_target`** (il pattern pericoloso con secrets + codice
  del fork) e fork esterni/draft esclusi via guard `if:`;
- **audit solo manuali**: trigger esclusivamente `workflow_dispatch`;
- **redaction**: i possibili segreti vengono offuscati PRIMA dell'invio al
  modello — qui si esercitano le funzioni REALI estratte dagli heredoc;
- **no training/persistenza lato OpenAI**: Responses API con `store: False`;
- **action pinnate a SHA** (convenzione hardening del repo).

Come per `test_build_exe_safety.py` il parsing dei workflow è dependency-free
(regex, nessun parser YAML esterno: PyYAML non è una dipendenza del progetto).
Il Python embedded negli heredoc `python3 <<'PY'` viene estratto esattamente
come lo vedrebbe la shell (dedent al livello dell'heredoc), compilato, e per i
due script di audit anche ESEGUITO offline (solo definizioni: `main()` resta
dietro `if __name__ == "__main__"`, nessuna chiamata di rete) per testare le
funzioni pure: redaction, chunking con numeri riga, secret-scan locale,
normalizzazione dei finding.

Limite onesto: i due script di PR review girano a livello modulo (chiamano le
API GitHub/AI appena importati), quindi qui sono coperti da compile + invarianti
statiche; il loro comportamento live si verifica solo su una PR reale.
"""

import os
import re

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WF_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")

# kind: pr_review = automatico sulle PR (commenta) · audit = manuale read-only (artifact)
_AI_WORKFLOWS = {
    "openai-gpt-pr-review.yml": {"kind": "pr_review", "provider": "openai"},
    "claude-fable-pr-review.yml": {"kind": "pr_review", "provider": "anthropic"},
    "manual-full-repo-ai-audit.yml": {"kind": "audit", "provider": "openai"},
    "claude-fable-full-repo-audit.yml": {"kind": "audit", "provider": "anthropic"},
}

_UPLOAD_ARTIFACT_PINNED = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"


def _wf_path(name):
    return os.path.join(_WF_DIR, name)


def _read(name):
    with open(_wf_path(name), encoding="utf-8") as fh:
        return fh.read()


def _extract_heredocs(text):
    """Estrae i blocchi ``python3 <<'PY' ... PY`` come li vede la shell.

    YAML rimuove l'indentazione del block scalar fino al livello base del
    ``run: |``; qui si replica il risultato togliendo a ogni riga del corpo
    l'indentazione della riga ``python3 <<'PY'`` (le righe vuote restano vuote).
    """
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)python3 <<'PY'\s*$", lines[i])
        if m:
            indent = m.group(1)
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != "PY":
                line = lines[i]
                if line.startswith(indent):
                    line = line[len(indent):]
                body.append(line)
                i += 1
            blocks.append("\n".join(body))
        i += 1
    return blocks


def _compiled_heredoc(name):
    text = _read(name)
    blocks = _extract_heredocs(text)
    assert len(blocks) == 1, f"{name}: atteso esattamente 1 heredoc python, trovati {len(blocks)}"
    src = blocks[0]
    compile(src, f"{name}#heredoc", "exec")  # SyntaxError = gate rosso
    return src


# --- Segreti FINTI costruiti a runtime: il testo grezzo di questo file non
# --- deve mai contenere pattern che assomiglino a un segreto reale (gate
# --- forbidden-files / secret-scan del repo).
def _fake_telegram_token():
    return "123456789" + ":" + "AB" * 18  # 9 cifre + ':' + 36 caratteri


def _fake_openai_key():
    return "sk-" + "a1B2" * 8  # 'sk-' + 32 caratteri


def _fake_private_key_block():
    dash = "-" * 5
    return (
        dash + "BEGIN PRIVATE KEY" + dash + "\nMIIfintofintofinto\n" + dash + "END PRIVATE KEY" + dash
    )


def _exec_audit_script(name, tmp_path, monkeypatch):
    """Esegue lo script di audit estratto, offline, e ritorna il namespace.

    Prepara un finto repo (AUDIT_ROOT) e una report-dir temporanea; imposta le
    env richieste a livello modulo. Nessuna rete: viene eseguito solo il corpo
    di definizione (main() è guardato da __name__).
    """
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    report = tmp_path / "report"

    monkeypatch.setenv("AUDIT_ROOT", str(root))
    monkeypatch.setenv("AUDIT_REPORT_DIR", str(report))
    # Chiave FINTA: serve solo perché lo script Claude la legge a livello modulo.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test" + "-non-e-una-chiave-vera")
    monkeypatch.setenv("OPENAI_API_KEY", "test" + "-non-e-una-chiave-vera")

    src = _compiled_heredoc(name)
    namespace = {"__name__": f"wf_audit_{name.replace('-', '_').replace('.', '_')}"}
    exec(compile(src, f"{name}#heredoc", "exec"), namespace)  # noqa: S102 - test del gate
    return namespace, root


# ---------------------------------------------------------------------------
# Invarianti statiche sui 4 workflow
# ---------------------------------------------------------------------------

def test_yaml_dei_workflow_ai_e_parsabile():
    """Validazione YAML piena, solo dove PyYAML è disponibile.

    PyYAML non è una dipendenza del progetto: in CI questo test viene SKIPPATO
    (motivo scritto qui) e la validità YAML resta garantita da GitHub Actions
    stesso, che rifiuta i workflow malformati. In locale (dove PyYAML è
    installato) il parse gira davvero.
    """
    yaml = pytest.importorskip(
        "yaml", reason="PyYAML non è una dipendenza del progetto; validazione YAML solo locale"
    )
    for name in _AI_WORKFLOWS:
        data = yaml.safe_load(_read(name))
        assert isinstance(data, dict) and "jobs" in data, f"{name}: YAML senza jobs"


def test_python_embedded_compila():
    for name in _AI_WORKFLOWS:
        _compiled_heredoc(name)


def test_permessi_minimi_e_niente_scritture():
    for name, meta in _AI_WORKFLOWS.items():
        text = _read(name)
        assert "permissions:\n  contents: read" in text, f"{name}: manca contents: read"
        assert "contents: write" not in text, f"{name}: contents: write vietato"
        assert "pull-requests: write" not in text, f"{name}: pull-requests: write vietato"
        assert "actions: write" not in text, f"{name}: actions: write vietato"
        # Come chiave trigger YAML, non come substring: i commenti di sicurezza
        # («niente pull_request_target») sono legittimi.
        assert not re.search(r"(?m)^\s*pull_request_target:", text), (
            f"{name}: trigger pull_request_target vietato"
        )

        if meta["kind"] == "audit":
            # Gli audit non devono poter scrivere nulla, nemmeno commenti.
            assert "issues: write" not in text, f"{name}: audit deve restare senza issues: write"
        else:
            # Il PR review scrive SOLO il commento (issues: write) e legge la PR.
            assert "issues: write" in text, f"{name}: manca issues: write per il commento"
            assert "pull-requests: read" in text, f"{name}: manca pull-requests: read"


def test_audit_solo_manuali_workflow_dispatch():
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "audit":
            continue
        text = _read(name)
        assert "workflow_dispatch:" in text, f"{name}: manca workflow_dispatch"
        # Nessun trigger automatico: niente push/pull_request/schedule.
        assert not re.search(r"(?m)^  push:", text), f"{name}: trigger push vietato"
        assert not re.search(r"(?m)^  pull_request:", text), f"{name}: trigger pull_request vietato"
        assert not re.search(r"(?m)^  schedule:", text), f"{name}: trigger schedule vietato"


def test_pr_review_diff_only_niente_checkout_niente_fork():
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        text = _read(name)
        assert "actions/checkout" not in text, f"{name}: il PR review non deve fare checkout"
        assert "github.event.pull_request.head.repo.full_name == github.repository" in text, (
            f"{name}: manca il guard anti-fork"
        )
        assert "github.event.pull_request.draft == false" in text, f"{name}: manca il guard draft"


def test_segreti_via_github_secrets_e_masking():
    for name, meta in _AI_WORKFLOWS.items():
        text = _read(name)
        key = "OPENAI_API_KEY" if meta["provider"] == "openai" else "ANTHROPIC_API_KEY"
        assert "${{ secrets." + key + " }}" in text, f"{name}: la API key deve venire dai secrets"
        assert "::add-mask::" in text, f"{name}: manca il masking della API key nei log"


def test_openai_responses_api_con_store_false():
    """I dati inviati a OpenAI non devono essere memorizzati (store: False)."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["provider"] != "openai":
            continue
        src = _compiled_heredoc(name)
        assert '"store": False' in src, f"{name}: manca store: False nella payload OpenAI"
        assert "https://api.openai.com/v1/responses" in src, f"{name}: endpoint Responses atteso"


def test_upload_artifact_pinnato_a_sha():
    for name, meta in _AI_WORKFLOWS.items():
        text = _read(name)
        if meta["kind"] == "audit":
            assert _UPLOAD_ARTIFACT_PINNED in text, (
                f"{name}: upload-artifact deve essere pinnato allo SHA v4.6.2 come build.yaml"
            )
        # Nessuna action non pinnata: ogni `uses:` deve referenziare uno SHA di 40 hex.
        for m in re.finditer(r"(?m)^\s*uses:\s*(\S+)", text):
            ref = m.group(1)
            assert re.search(r"@[0-9a-f]{40}$", ref), f"{name}: action non pinnata a SHA: {ref}"


# ---------------------------------------------------------------------------
# Test funzionali OFFLINE sulle funzioni reali degli script di audit
# ---------------------------------------------------------------------------

def test_redaction_offusca_i_segreti_prima_dell_invio(tmp_path, monkeypatch):
    for name in ("manual-full-repo-ai-audit.yml", "claude-fable-full-repo-audit.yml"):
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        redact = ns["redact"]

        out = redact(f"token bot: {_fake_telegram_token()}")
        assert _fake_telegram_token() not in out and "REDACTED_TELEGRAM_BOT_TOKEN" in out, name

        out = redact(f"chiave {_fake_openai_key()} nel log")
        assert _fake_openai_key() not in out and "REDACTED_OPENAI_KEY" in out, name

        out = redact(_fake_private_key_block())
        assert "MIIfintofintofinto" not in out and "REDACTED_PRIVATE_KEY_BLOCK" in out, name

        out = redact("api_key = " + "x" * 20)
        assert "x" * 20 not in out and "[REDACTED]" in out, name

        # Testo innocuo: nessuna alterazione.
        assert redact("quota 1,50 su Home v Away") == "quota 1,50 su Home v Away", name


def test_make_chunks_numeri_riga_e_budget(tmp_path, monkeypatch):
    text = "\n".join(f"riga {i}" for i in range(1, 51))

    # Script GPT: firma make_chunks(path_str, text).
    ns, _ = _exec_audit_script("manual-full-repo-ai-audit.yml", tmp_path, monkeypatch)
    chunks = ns["make_chunks"]("main.py", text)
    assert chunks[0][0] == 1 and chunks[-1][1] == 50
    assert chunks[0][2].splitlines()[0] == "000001: riga 1"
    ricomposto = [ln for _, _, c in chunks for ln in c.splitlines()]
    assert len(ricomposto) == 50, "nessuna riga persa o duplicata nel chunking"

    # Script Claude: firma make_chunks(text) + budget da CHUNK_MAX_CHARS env.
    monkeypatch.setenv("CHUNK_MAX_CHARS", "200")
    ns2, _ = _exec_audit_script("claude-fable-full-repo-audit.yml", tmp_path, monkeypatch)
    chunks2 = ns2["make_chunks"](text)
    assert len(chunks2) > 1, "con budget 200 chars il file da 50 righe deve spezzarsi"
    assert chunks2[0][0] == 1 and chunks2[-1][1] == 50
    assert all(len(c) <= 200 + 60 for _, _, c in chunks2), "chunk oltre il budget configurato"
    # Continuità: ogni chunk riparte dalla riga successiva al precedente.
    for (s1, e1, _), (s2, _, _) in zip(chunks2, chunks2[1:]):
        assert s2 == e1 + 1

    # File vuoto: chunk sintetico, nessun crash.
    assert ns2["make_chunks"]("") == [(1, 1, "000001: [EMPTY FILE]")]


def test_local_secret_scan_trova_token_finto_e_redige_l_evidenza(tmp_path, monkeypatch):
    for name, fn_name in (
        ("manual-full-repo-ai-audit.yml", "local_secret_findings"),
        ("claude-fable-full-repo-audit.yml", "local_secret_scan"),
    ):
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        text = "riga innocua\n" + f'TOKEN = "{_fake_telegram_token()}"\n'
        findings = ns[fn_name]("config_store.py", text)
        assert findings, f"{name}: token finto non rilevato"
        telegram = [f for f in findings if f["title"].endswith("telegram_bot_token")]
        assert telegram and telegram[0]["severity"] == "critical", name
        assert telegram[0]["line_start"] == 2, name
        # L'evidenza NON deve contenere il valore del segreto.
        assert _fake_telegram_token() not in telegram[0]["evidence"], name

        # PEM multi-riga (com'è nella realtà): il marker BEGIN deve produrre un
        # finding critical anche se BEGIN/END stanno su righe diverse
        # (regressione Codex P2 / CodeRabbit su PR #304: pattern multiline
        # usato in un loop per-riga non matchava mai).
        pem_findings = ns[fn_name]("secret.pem", _fake_private_key_block() + "\n")
        pem = [f for f in pem_findings if f["title"].endswith("private_key_block")]
        assert pem and pem[0]["severity"] == "critical", (
            f"{name}: private key PEM multi-riga non rilevata dallo scan locale"
        )

        assert ns[fn_name]("main.py", "print('ciao')\n") == [], f"{name}: falso positivo"


def test_normalize_finding_fail_closed_su_dati_del_modello(tmp_path, monkeypatch):
    for name in ("manual-full-repo-ai-audit.yml", "claude-fable-full-repo-audit.yml"):
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        norm = ns["normalize_finding"]

        # Severity inventata dal modello → clampata a info.
        f = norm({"severity": "apocalittica", "title": "x"}, "main.py", 10, 20)
        assert f["severity"] == "info", name

        # Riga fuori dal range del chunk → scartata (nessuna riga inventata).
        f = norm({"severity": "high", "line_start": 999, "line_end": 999}, "main.py", 10, 20)
        assert f["line_start"] is None, name

        # Riga valida nel range → preservata.
        f = norm({"severity": "critical", "line_start": 12, "line_end": 15}, "main.py", 10, 20)
        assert f["severity"] == "critical" and f["line_start"] == 12 and f["line_end"] == 15, name

        # Il modello non può attribuire il finding a un file MAI analizzato:
        # il campo file è clampato al file del chunk (Codex P2 su PR #304).
        f = norm({"severity": "high", "file": "altro/file_inventato.py"}, "main.py", 10, 20)
        assert f["file"] == "main.py", f"{name}: file del finding non clampato al chunk"


def test_iter_files_salta_binari_directory_generate_e_max_files(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_FILES", "2")
    ns, root = _exec_audit_script("claude-fable-full-repo-audit.yml", tmp_path, monkeypatch)

    (root / "a_main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "b_doc.md").write_text("# doc\n", encoding="utf-8")
    (root / "c_extra.txt").write_text("oltre il limite\n", encoding="utf-8")
    (root / "bridge.exe").write_bytes(b"\x00\x01\x02")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.py").write_text("cache\n", encoding="utf-8")

    files, skipped = ns["iter_files"]()
    scanned = [str(p.relative_to(root)) for p in files]
    skipped_names = {item["file"] for item in skipped}

    assert scanned == ["a_main.py", "b_doc.md"], "solo i primi MAX_FILES file testuali"
    assert "bridge.exe" in skipped_names, "binario non saltato"
    assert "__pycache__/x.py" in skipped_names, "directory generata non saltata"
    assert "c_extra.txt" in skipped_names, "file oltre MAX_FILES non tracciato come saltato"
    # Ogni file saltato ha il motivo scritto (trasparenza: niente troncamenti silenziosi).
    assert all(item["reason"] for item in skipped)


def test_iter_files_non_segue_symlink_fuori_dallo_snapshot(tmp_path, monkeypatch):
    """Un symlink committato nel ref scansionato non deve far leggere file del
    runner fuori da AUDIT_ROOT (Codex P2 su PR #304): va saltato, con motivo."""
    fuori = tmp_path / "fuori-dallo-snapshot.txt"
    fuori.write_text("contenuto del runner FUORI dal repo\n", encoding="utf-8")

    for name, iter_name in (
        ("manual-full-repo-ai-audit.yml", "iter_text_files"),
        ("claude-fable-full-repo-audit.yml", "iter_files"),
    ):
        ns, root = _exec_audit_script(name, tmp_path, monkeypatch)
        (root / "ok.py").write_text("print('ok')\n", encoding="utf-8")
        link = root / "evil_link.txt"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(fuori)

        files, skipped = ns[iter_name]()
        scanned = [str(p.relative_to(root)) for p in files]
        assert "evil_link.txt" not in scanned, f"{name}: symlink seguito fuori dallo snapshot"
        assert any(item["file"] == "evil_link.txt" for item in skipped), (
            f"{name}: symlink saltato ma non tracciato"
        )


def test_pr_review_upsert_paginato_e_ref_tarball_encodato():
    """Invarianti statiche dei fix Codex/CodeRabbit su PR #304."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] == "pr_review":
            src = _compiled_heredoc(name)
            assert "per_page=100&page={page}" in src, (
                f"{name}: upsert_comment deve paginare i commenti (marker oltre i primi 100)"
            )
        else:
            text = _read(name)
            assert "urllib.parse.quote" in text, (
                f"{name}: TARGET_REF va URL-encodato prima dell'URL tarball (branch con '/')"
            )


def test_dedup_finding_stabile(tmp_path, monkeypatch):
    ns, _ = _exec_audit_script("manual-full-repo-ai-audit.yml", tmp_path, monkeypatch)
    key = ns["finding_key"]
    a = {"severity": "high", "category": "bug", "file": "main.py", "line_start": 3, "title": "Doppione"}
    assert key(a) == key(dict(a)), "stesso finding → stessa chiave (dedupe deterministico)"
    b = dict(a, line_start=4)
    assert key(a) != key(b), "riga diversa → finding distinto"
