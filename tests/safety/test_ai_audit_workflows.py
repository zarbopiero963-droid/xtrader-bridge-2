"""Gate di sicurezza dei workflow AI (PR review push-range + full-repo audit).

Sei workflow AI mandano diff/contenuti del repository a servizi esterni:

- **PR review push-range** (automatici su ogni push della PR, un commento per
  range `before...after` via GitHub Compare API):
  `pr-review-gpt55.yml` (OpenAI), `pr-review-claude-fable5.yml` (Anthropic),
  `pr-review-openrouter-glm52.yml` e `pr-review-openrouter-fugu-ultra.yml`
  (OpenRouter);
- **audit full-repo** (solo manuali, artifact scaricabile):
  `manual-full-repo-ai-audit.yml` (OpenAI) e `claude-fable-full-repo-audit.yml`
  (Anthropic).

Invarianti non negoziabili difese qui, in modo deterministico e offline:

- **read-only**: nessun checkout nei PR review, nessun permesso di scrittura
  sul contenuto (`contents: read`; solo `issues: write` per il commento PR);
- **niente `pull_request_target`**, fork esterni/draft esclusi via `if:`;
- **audit solo manuali**: trigger esclusivamente `workflow_dispatch`;
- **reviewer opzionali**: se manca l'API key il PR review esce con **successo**
  (skip), non fa fallire la PR con un check rosso;
- **redaction pre-invio**: possibili segreti — inclusi **nomi file/path** e il
  **ref** — vengono offuscati PRIMA dell'invio (con `github_pat_` fine-grained);
- **no training/persistenza lato OpenAI**: Responses API con `store: false`;
- **action pinnate a SHA** (solo gli audit usano `uses:`; i PR review no);
- **audit fail-closed**: se ogni chunk AI fallisce, l'audit non è "verde".

Il parsing dei workflow è dependency-free (regex; PyYAML non è una dipendenza
del progetto). Il Python embedded negli heredoc `python3 <<'PY'` viene estratto
esattamente come lo vedrebbe la shell (dedent al livello dell'heredoc),
compilato, e per i due script di audit anche ESEGUITO offline (solo definizioni:
`main()` resta dietro `if __name__ == "__main__"`, nessuna chiamata di rete) per
testare le funzioni pure. I quattro PR review girano a livello modulo (chiamano
GitHub appena importati), quindi sono coperti da compile + invarianti statiche;
il loro comportamento live si verifica solo su una PR reale.
"""

import os
import re

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WF_DIR = os.path.join(_REPO_ROOT, ".github", "workflows")

# kind: pr_review = automatico push-range (commenta) · audit = manuale read-only
_AI_WORKFLOWS = {
    "pr-review-gpt55.yml": {"kind": "pr_review", "provider": "openai", "trigger": "auto"},
    "pr-review-claude-fable5.yml": {"kind": "pr_review", "provider": "anthropic", "trigger": "label", "label": "final-fable-review"},
    "pr-review-openrouter-glm52.yml": {"kind": "pr_review", "provider": "openrouter", "trigger": "auto"},
    "pr-review-openrouter-fugu-ultra.yml": {"kind": "pr_review", "provider": "openrouter", "trigger": "label", "label": "final-fugu-review"},
    "manual-full-repo-ai-audit.yml": {"kind": "audit", "provider": "openai"},
    "claude-fable-full-repo-audit.yml": {"kind": "audit", "provider": "anthropic"},
}

_PROVIDER_SECRET = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

_AUDIT_WORKFLOWS = ("manual-full-repo-ai-audit.yml", "claude-fable-full-repo-audit.yml")

_UPLOAD_ARTIFACT_PINNED = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"


def _wf_path(name):
    return os.path.join(_WF_DIR, name)


def _read(name):
    with open(_wf_path(name), encoding="utf-8") as fh:
        return fh.read()


def _extract_heredocs(text):
    """Estrae i blocchi ``python3 <<'PY' ... PY`` come li vede la shell."""
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
# --- deve mai contenere pattern che assomiglino a un segreto reale.
def _fake_telegram_token():
    return "123456789" + ":" + "AB" * 18


def _fake_openai_key():
    return "sk-" + "a1B2" * 8


def _fake_github_pat():
    return "github_pat_" + "A1b2" * 10  # github_pat_ + 40 caratteri


def _fake_private_key_block():
    dash = "-" * 5
    return (
        dash + "BEGIN PRIVATE KEY" + dash + "\nMIIfintofintofinto\n" + dash + "END PRIVATE KEY" + dash
    )


def _exec_audit_script(name, tmp_path, monkeypatch, extra_env=None):
    """Esegue lo script di audit estratto, offline, e ritorna il namespace."""
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    report = tmp_path / "report"

    monkeypatch.setenv("AUDIT_ROOT", str(root))
    monkeypatch.setenv("AUDIT_REPORT_DIR", str(report))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test" + "-non-e-una-chiave-vera")
    monkeypatch.setenv("OPENAI_API_KEY", "test" + "-non-e-una-chiave-vera")
    for k, v in (extra_env or {}).items():
        monkeypatch.setenv(k, v)

    src = _compiled_heredoc(name)
    namespace = {"__name__": f"wf_audit_{name.replace('-', '_').replace('.', '_')}"}
    exec(compile(src, f"{name}#heredoc", "exec"), namespace)  # noqa: S102 - test del gate
    return namespace, root


# ---------------------------------------------------------------------------
# Invarianti statiche sui 6 workflow
# ---------------------------------------------------------------------------

def test_yaml_dei_workflow_ai_e_parsabile():
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
        assert "actions: write" not in text, f"{name}: actions: write vietato"
        assert not re.search(r"(?m)^\s*pull_request_target:", text), (
            f"{name}: trigger pull_request_target vietato"
        )

        if meta["kind"] == "audit":
            # Gli audit sono read-only puri: solo contents: read, nessuna write.
            assert "issues: write" not in text, f"{name}: audit deve restare senza issues: write"
            assert "pull-requests: write" not in text, (
                f"{name}: audit deve restare senza pull-requests: write"
            )
        else:
            # Per commentare SU una PR il GITHUB_TOKEN richiede pull-requests: write
            # (l'endpoint POST /issues/{n}/comments su un pull request è gated da
            # "Pull requests" write, non basta "Issues" write); issues: write serve
            # per l'add/remove della label manual-review-required.
            assert "issues: write" in text, f"{name}: manca issues: write per la label"
            assert "pull-requests: write" in text, (
                f"{name}: manca pull-requests: write per commentare la PR"
            )


def test_api_key_letta_con_strip():
    """La API key va letta con .strip().

    Regressione reale (PR #304, head 953d64c): un secret incollato con newline
    finale produceva ``Authorization: Bearer <key>\\n`` -> ``Invalid header
    value`` e la request al modello falliva prima ancora di partire. Lo strip
    neutralizza newline/spazi accidentali nel secret. Vale per tutti e sei i
    workflow AI (i quattro PR review + i due audit), ciascuno con la propria
    chiave provider.
    """
    for name, meta in _AI_WORKFLOWS.items():
        text = _read(name)
        secret = _PROVIDER_SECRET[meta["provider"]]
        # Accetta sia os.environ["KEY"].strip() (PR review + audit Anthropic)
        # sia os.environ.get("KEY", "").strip() (audit OpenAI): in entrambi i
        # casi il valore usato per l'header è .strip()-ato.
        pattern = rf'os\.environ(?:\.get)?[(\[]"{secret}"(?:,\s*"")?[)\]]\.strip\(\)'
        assert re.search(pattern, text), (
            f"{name}: la chiave {secret} va letta con .strip() "
            f"(un newline finale rompe l'header Authorization/x-api-key)"
        )


def test_before_sha_vuoto_ripiega_su_intera_pr():
    """BEFORE_SHA/AFTER_SHA (push-only) vuoti non rompono il range resolution.

    Finding del gate finale Claude Fable 5 (PR #304, head 92722ce): sul payload
    ``pull_request`` gli SHA ``before``/``after`` esistono SOLO per l'azione
    ``synchronize``, non per ``labeled`` — quindi sui due gate finali (solo
    ``labeled``) ``BEFORE_SHA``/``AFTER_SHA`` sono vuoti. È un falso allarme:
    ``resolve_range()`` legge ``BEFORE_SHA`` con default sicuro e lo usa SOLO
    dietro ``EVENT_ACTION == "synchronize"``, altrimenti ripiega su
    ``BASE_SHA...HEAD`` (l'intera PR). Questo test blocca la regressione in cui
    qualcuno usasse ``BEFORE_SHA`` senza guardia o senza default, facendo esplodere
    (o svuotare) il range sul gate finale.
    """
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        text = _read(name)
        # default sicuro: niente KeyError se before/after mancano dal payload
        assert 'os.environ.get("BEFORE_SHA", "")' in text, (
            f"{name}: BEFORE_SHA va letto con default sicuro (before assente su labeled)"
        )
        # BEFORE_SHA usato solo per synchronize; altrimenti base = BASE_SHA
        assert re.search(r'EVENT_ACTION == "synchronize" and good_sha\(BEFORE_SHA\)', text), (
            f"{name}: l'uso di BEFORE_SHA deve essere guardato da EVENT_ACTION == synchronize"
        )
        assert re.search(r'else:\s*\n\s*base = BASE_SHA', text), (
            f"{name}: senza synchronize il range deve ripiegare su BASE_SHA (intera PR)"
        )


def test_gate_finale_budget_output_ampio_e_troncamento_esplicito():
    """I due gate finali rivedono l'INTERA PR: budget output ampio + troncamento onesto.

    Regressione reale (PR #304, head c06708b): Claude Fable 5, sul range
    ``base...head`` (11 commit, ~12k token input), ha esaurito
    ``MAX_OUTPUT_TOKENS=1200`` producendo **0 testo**, e il commento diceva solo
    "Il modello non ha restituito testo" senza spiegare il troncamento. Ora i gate
    finali (label-gated, che rivedono tutta la PR) hanno un budget >= 4000 e,
    quando il modello si ferma per limite di token, il commento lo dichiara
    esplicitamente invece di sembrare "il modello non aveva nulla da dire".
    """
    finali = [n for n, m in _AI_WORKFLOWS.items() if m.get("trigger") == "label"]
    assert finali, "atteso almeno un gate finale label-gated"
    for name in finali:
        text = _read(name)
        match = re.search(r'MAX_OUTPUT_TOKENS:\s*"(\d+)"', text)
        assert match, f"{name}: MAX_OUTPUT_TOKENS non trovato nell'env"
        assert int(match.group(1)) >= 4000, (
            f"{name}: gate finale con budget output troppo piccolo "
            f"({match.group(1)}); rivede l'intera PR e va >= 4000"
        )
        assert "Output troncato" in text, (
            f"{name}: manca il ramo di troncamento onesto quando il modello "
            f"esaurisce il budget di output"
        )
        assert re.search(r'stop_reason.*max_tokens|finish_reason.*length', text), (
            f"{name}: manca il check su stop_reason/finish_reason per il troncamento"
        )


def test_tutti_i_pr_review_riportano_il_troncamento():
    """Ogni reviewer PR (anche gli automatici) deve dichiarare il troncamento.

    Regressione reale (PR #304, head fd22cff): il reviewer AUTOMATICO GPT-5.5 —
    modello reasoning, i cui token di reasoning contano nel budget di output — su
    un diff grande ha esaurito ``MAX_OUTPUT_TOKENS`` producendo 0 testo, e il
    commento diceva solo "Il modello non ha restituito testo". Il fix di
    troncamento onesto inizialmente copriva solo i due gate finali: ora vale per
    tutti e quattro i reviewer, ognuno col motivo giusto per il suo provider.
    """
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        text = _read(name)
        provider = meta["provider"]
        assert "Output troncato" in text, (
            f"{name}: manca il messaggio di troncamento onesto (budget esaurito)"
        )

        if provider == "openai":
            # Responses API: NON basta status=incomplete, serve DAVVERO anche il
            # motivo max_output_tokens (GPT-5.5 review: il vecchio regex passava
            # col solo status). Richiedi entrambi i marker.
            assert re.search(r'status.*==.*"incomplete"', text), (
                f"{name}: manca il check status=incomplete"
            )
            assert "max_output_tokens" in text, (
                f"{name}: manca il check reason=max_output_tokens per il troncamento"
            )
        elif provider == "anthropic":
            assert re.search(r'stop_reason.*max_tokens', text), (
                f"{name}: manca il check stop_reason=max_tokens"
            )
            # blocco con "text": null → None in "\n".join(parts) = TypeError.
            # La forma Anthropic è diversa dall'OpenRouter, va coperta a parte
            # (gap segnalato da GPT-5.5, PR #304).
            assert re.search(r'item\.get\("text"\)\s*or\s*""', text), (
                f"{name}: il testo dei blocchi Anthropic non è protetto da text=None"
            )
        else:  # openrouter (GLM, Fugu)
            assert re.search(r'finish_reason.*length', text), (
                f"{name}: manca il check finish_reason=length"
            )
            # content null (JSON null) va normalizzato a "" PRIMA di str(),
            # altrimenti str(None)="None" viene pubblicato come testo e bypassa
            # il ramo di troncamento (bloccante GPT-5.5, PR #304).
            assert 'msg.get("content") or ""' in text, (
                f"{name}: content=None non normalizzato → rischio di pubblicare 'None'"
            )
            # blocco con "text": null → None in "\n".join(...) = TypeError su una
            # risposta valida (edge case GPT-5.5): il join va reso None-safe.
            assert re.search(r'str\(part\.get\("text"\)\s*or\s*""\)', text), (
                f"{name}: il join dei blocchi non è protetto da text=None (TypeError)"
            )

        # Un reviewer reasoning (OpenAI gpt-5.5) con budget minuscolo produce 0
        # testo: il budget di output deve avere un minimo ragionevole.
        match = re.search(r'MAX_OUTPUT_TOKENS:\s*"(\d+)"', text)
        assert match and int(match.group(1)) >= 1500, (
            f"{name}: MAX_OUTPUT_TOKENS troppo piccolo per lasciare spazio al testo"
        )


def test_audit_solo_manuali_workflow_dispatch():
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "audit":
            continue
        text = _read(name)
        assert "workflow_dispatch:" in text, f"{name}: manca workflow_dispatch"
        assert not re.search(r"(?m)^  push:", text), f"{name}: trigger push vietato"
        assert not re.search(r"(?m)^  pull_request:", text), f"{name}: trigger pull_request vietato"
        assert not re.search(r"(?m)^  schedule:", text), f"{name}: trigger schedule vietato"
        # max_files/max_chunks = 0 → audit senza contenuto: va rifiutato
        # (Codex P2 su PR #304), altrimenti il job sembrerebbe verde con 0/0.
        assert "-lt 1" in text, f"{name}: budget 0 (max_files/max_chunks) non rifiutato"
        # CHUNK_MAX_CHARS troppo piccolo tronca ogni riga al solo marker: audit
        # vuoto ma verde (Codex P2 round 2). Deve avere un floor >= 500.
        assert re.search(r'CHUNK_MAX_CHARS"?\s*-lt 500', text), (
            f"{name}: CHUNK_MAX_CHARS senza floor (valori piccoli = audit vuoto ma verde)"
        )
        # MAX_FILE_KB = 0 scarterebbe ogni file → 0 scansionati, job verde.
        assert re.search(r'MAX_FILE_KB"?\s*-lt 1', text), (
            f"{name}: MAX_FILE_KB=0 non rifiutato (nessun file analizzato)"
        )


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


def test_pr_review_reviewer_opzionale_non_fa_fallire_la_pr():
    """Codex P2: senza API key il reviewer opzionale deve uscire con successo
    (skip), non trasformarsi in un check rosso su ogni PR interna."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        text = _read(name)
        # Word-boundary: `exit 1` esatto, non `exit 10`/`exit 127` legittimi.
        assert not re.search(r"\bexit 1\b", text), (
            f"{name}: il reviewer opzionale non deve mai uscire con exit 1"
        )
        assert re.search(r"non configurato.*\n\s*exit 0", text), (
            f"{name}: la key assente deve portare a 'exit 0' (skip), non a un fallimento"
        )
        # Anche un fallimento nella pubblicazione del commento (token read-only
        # / 403) deve degradare a warning, non far fallire la PR.
        src = _compiled_heredoc(name)
        assert "impossibile pubblicare il commento" in src, (
            f"{name}: upsert_comment deve essere fail-open (warning, non crash) su 403"
        )


def test_pr_review_trigger_split():
    """GPT-5.5 e GLM 5.2 automatici a ogni push (spendono sempre); Claude Fable 5
    e Fugu Ultra partono sui push ma spendono (chiamano il modello) SOLO se il
    push tocca file core del bridge oppure se è aggiunta la label finale."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        text = _read(name)
        if meta["trigger"] == "auto":
            assert "types: [opened, synchronize, reopened, ready_for_review]" in text, (
                f"{name}: reviewer automatico deve triggerare sui push della PR"
            )
            assert "github.event.label.name" not in text, (
                f"{name}: reviewer automatico non deve gatare su una label"
            )
            assert "CORE_TRIGGER_PATTERNS" not in text, (
                f"{name}: reviewer automatico non deve avere il gate costo core-file"
            )
        else:
            # Gate finale forte: parte sui push + label, ma il costo è gatato.
            assert "labeled" in text, f"{name}: gate finale deve triggerare anche su label"
            assert "synchronize" in text, (
                f"{name}: gate finale deve triggerare sui push (per il gate costo core-file)"
            )
            assert f"github.event.label.name == '{meta['label']}'" in text, (
                f"{name}: gate finale deve accettare la label {meta['label']}"
            )
            assert "CORE_TRIGGER_PATTERNS" in text and "touches_core" in text, (
                f"{name}: manca il gate costo (modello solo su file core o label)"
            )
            assert 'EVENT_ACTION != "labeled"' in text and "not touches_core(files)" in text, (
                f"{name}: manca la condizione di skip (nessun file core e nessuna label)"
            )
            # Il set core deve includere almeno il package del bridge.
            assert "xtrader_bridge/" in text, (
                f"{name}: il trigger core deve includere xtrader_bridge/"
            )
            # Fail-safe: su Compare API troncata (>=300 file) NON deve saltare la
            # review forte, perché un file core potrebbe essere oltre il limite
            # (GPT-5.5). Il gate deve considerare la truncation prima di skippare.
            assert "compare_maybe_truncated" in text, (
                f"{name}: il gate costo non è fail-safe su Compare API troncata (>=300 file)"
            )


def test_pr_review_redige_output_del_modello():
    """Codex P2: l'OUTPUT del modello va redatto prima della pubblicazione.

    Se il modello ripete un valore segreto (formato non coperto dalla redaction
    dell'input, o echo del prompt), non deve finire in chiaro nel commento PR.
    """
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        assert "review = redact(review)" in _read(name), (
            f"{name}: l'output del modello non passa da redact() prima della pubblicazione"
        )


def test_pr_review_dotenv_e_chiavi_sono_area_critica():
    """Codex P2: .env e file-chiave devono essere area critica (manual-review),
    anche se binari/oversized/senza patch."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        text = _read(name)
        assert r"(^|/)\.env($|\.)" in text, f"{name}: dotenv non marcato come area critica"
        assert "pem|pfx|p12|key|keystore" in text, (
            f"{name}: file-chiave privati non marcati come area critica"
        )


def test_pr_review_robustezza_infra():
    """Fix CodeRabbit/Codex su PR #304: il reviewer opzionale non deve morire su
    errori infra e non deve perdere il segnale di controllo manuale."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        src = _compiled_heredoc(name)
        # resolve_range fail-open (errore GitHub API non blocca la PR).
        assert "impossibile risolvere il range" in src, f"{name}: resolve_range non fail-open"
        # Retry budget ridotto (max 3 tentativi) per stare sotto il job timeout.
        assert "range(1, 4)" in src, f"{name}: retry budget non ridotto (max 3 tentativi)"
        assert "range(1, 5)" not in src, f"{name}: retry budget ancora a 4 tentativi"
        # Rinomina DA area sensibile: considerato anche previous_filename.
        assert "previous_filename" in src, (
            f"{name}: previous_filename non considerato per le aree sensibili"
        )
        # Diff Compare troncato a 300 file → forza controllo manuale.
        assert "compare_truncated" in src, (
            f"{name}: troncamento Compare (>=300 file) non gestito fail-closed"
        )
        # Force-push: fallback sull'intera PR, non sul solo parent di HEAD.
        assert "fallback intera PR" in src, (
            f"{name}: il fallback deve coprire l'intera PR (base...head), non il solo parent"
        )
        # Fence ``` nel patch neutralizzati (recinto anti-injection).
        assert re.search(r"patch = patch\.replace\(", src), (
            f"{name}: i fence del patch non sono neutralizzati (prompt-injection)"
        )
        # Un path che È un segreto (redatto in placeholder) è comunque sensibile.
        assert '"[REDACTED" in filename' in src, (
            f"{name}: un filename-segreto redatto deve restare marcato sensibile"
        )


def test_pr_review_push_range_via_compare_api():
    """L'architettura finale analizza il range del push (before...after) via
    Compare API, non il diff cumulativo della PR."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        src = _compiled_heredoc(name)
        assert "/compare/" in src and "resolve_range" in src, (
            f"{name}: deve usare il range del push via GitHub Compare API"
        )
        assert "BEFORE_SHA" in src, f"{name}: deve leggere github.event.before per il range del push"


def test_segreti_via_github_secrets_e_masking():
    for name, meta in _AI_WORKFLOWS.items():
        text = _read(name)
        key = _PROVIDER_SECRET[meta["provider"]]
        assert "${{ secrets." + key + " }}" in text, f"{name}: la API key deve venire dai secrets"
        assert "::add-mask::" in text, f"{name}: manca il masking della API key nei log"


def test_openai_responses_api_con_store_false():
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
        for m in re.finditer(r"(?m)^\s*uses:\s*(\S+)", text):
            ref = m.group(1)
            assert re.search(r"@[0-9a-f]{40}$", ref), f"{name}: action non pinnata a SHA: {ref}"


def test_pr_review_fix_incorporati():
    """Fix mantenuti nella riscrittura push-range (confermati dal proprietario):
    label/avviso prima di ogni uscita, redaction dei nomi file, pattern che
    copre tutti i requirements, paginazione dei commenti, PAT fine-grained."""
    for name, meta in _AI_WORKFLOWS.items():
        if meta["kind"] != "pr_review":
            continue
        src = _compiled_heredoc(name)
        # Label/avviso calcolati PRIMA dell'uscita per diff vuoto.
        assert src.index("if critical_files:") < src.index("if not diff_text.strip():"), (
            f"{name}: label/avviso vanno calcolati prima dell'early-exit per diff vuoto"
        )
        assert src.count("{manual_warning}") >= 2, (
            f"{name}: l'avviso manuale deve comparire anche nel commento per diff vuoto"
        )
        # Nome file redatto E ripulito dai control-char (safe_display).
        assert 'filename = safe_display(f.get("filename"' in src, (
            f"{name}: il nome file va redatto e sanitizzato (segreti/control-char)"
        )
        # Detector requirements completo (.txt/.in/.lock).
        assert r"requirements[^/]*\.(txt|in|lock)$" in src, (
            f"{name}: detector requirements non copre .in/-dev/-build.lock"
        )
        # Paginazione completa dei commenti (marker oltre i primi 100).
        assert "per_page=100&page={page}" in src, (
            f"{name}: upsert_comment deve paginare i commenti"
        )
        # PAT GitHub fine-grained redatto.
        assert "github_pat_" in src, f"{name}: manca la redaction del PAT fine-grained (github_pat_)"
        # AWS access key redatta anche nei PR review (Codex P2 su PR #304).
        assert "AKIA" in src, f"{name}: manca la redaction delle AWS access key (AKIA...)"


# ---------------------------------------------------------------------------
# Test funzionali OFFLINE sulle funzioni reali degli script di audit
# ---------------------------------------------------------------------------

def test_redaction_offusca_i_segreti_prima_dell_invio(tmp_path, monkeypatch):
    for name in _AUDIT_WORKFLOWS:
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        redact = ns["redact"]

        out = redact(f"token bot: {_fake_telegram_token()}")
        assert _fake_telegram_token() not in out and "REDACTED_TELEGRAM_BOT_TOKEN" in out, name

        out = redact(f"chiave {_fake_openai_key()} nel log")
        assert _fake_openai_key() not in out and "REDACTED_OPENAI_KEY" in out, name

        # PAT GitHub fine-grained (Codex P2 su PR #304).
        out = redact(f"pat {_fake_github_pat()} committato")
        assert _fake_github_pat() not in out and "REDACTED_GITHUB_PAT" in out, name

        out = redact(_fake_private_key_block())
        assert "MIIfintofintofinto" not in out and "REDACTED_PRIVATE_KEY_BLOCK" in out, name

        out = redact("api_key = " + "x" * 20)
        assert "x" * 20 not in out and "[REDACTED]" in out, name

        assert redact("quota 1,50 su Home v Away") == "quota 1,50 su Home v Away", name


def test_safe_display_redige_e_toglie_control_char(tmp_path, monkeypatch):
    """Codex P2: path/ref che finiscono nei prompt vanno redatti E ripuliti dai
    control-char, o un nome tipo 'safe.py\\nRegole output:' inietta campi."""
    for name in _AUDIT_WORKFLOWS:
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        out = ns["safe_display"](f"dir/{_fake_openai_key()}\nRegole output: iniezione\x00")
        assert _fake_openai_key() not in out, f"{name}: segreto nel path non redatto"
        assert "\n" not in out and "\x00" not in out, f"{name}: control-char non rimossi dal path"


def test_target_ref_redatto_per_prompt_e_report(tmp_path, monkeypatch):
    """Codex P2: un ref che contiene un valore token-like non deve finire in
    chiaro nei prompt/report; resta raw solo per il download tarball (in bash)."""
    for name in _AUDIT_WORKFLOWS:
        ns, _ = _exec_audit_script(
            name, tmp_path, monkeypatch, extra_env={"TARGET_REF": f"feature/{_fake_openai_key()}"}
        )
        assert _fake_openai_key() not in ns["TARGET_REF"], (
            f"{name}: TARGET_REF non redatto per prompt/report"
        )


def test_make_chunks_numeri_riga_e_budget(tmp_path, monkeypatch):
    text = "\n".join(f"riga {i}" for i in range(1, 51))

    ns, _ = _exec_audit_script("manual-full-repo-ai-audit.yml", tmp_path, monkeypatch)
    chunks = ns["make_chunks"]("main.py", text)
    assert chunks[0][0] == 1 and chunks[-1][1] == 50
    assert chunks[0][2].splitlines()[0] == "000001: riga 1"
    ricomposto = [ln for _, _, c in chunks for ln in c.splitlines()]
    assert len(ricomposto) == 50, "nessuna riga persa o duplicata nel chunking"

    monkeypatch.setenv("CHUNK_MAX_CHARS", "200")
    ns2, _ = _exec_audit_script("claude-fable-full-repo-audit.yml", tmp_path, monkeypatch)
    chunks2 = ns2["make_chunks"](text)
    assert len(chunks2) > 1, "con budget 200 chars il file da 50 righe deve spezzarsi"
    assert chunks2[0][0] == 1 and chunks2[-1][1] == 50
    for (s1, e1, _), (s2, _, _) in zip(chunks2, chunks2[1:]):
        assert s2 == e1 + 1
    assert ns2["make_chunks"]("") == [(1, 1, "000001: [EMPTY FILE]")]


def test_audit_scansiona_segreti_nei_path_dei_file_skippati(tmp_path, monkeypatch):
    """Codex P2: un segreto nel NOME di un file SKIPPATO (binario/oversized/
    MAX_FILES) deve comunque produrre un finding critico, altrimenti
    fail_on_critical lo mancherebbe (il path scan girava solo sui candidati)."""
    for name, iter_name in (
        ("manual-full-repo-ai-audit.yml", "iter_text_files"),
        ("claude-fable-full-repo-audit.yml", "iter_files"),
    ):
        ns, root = _exec_audit_script(name, tmp_path, monkeypatch)
        leaked = root / "leaked"
        leaked.mkdir(exist_ok=True)
        # file binario (→ skippato) con un PAT nel nome, a un boundary di path
        (leaked / f"{_fake_github_pat()}.exe").write_bytes(b"\x00\x01\x02")

        _files, _skipped, path_findings = ns[iter_name]()
        crit = [f for f in path_findings if f["severity"] == "critical"]
        assert crit, f"{name}: segreto nel nome di un file skippato non segnalato"
        # nessun valore in chiaro nel finding
        assert _fake_github_pat() not in crit[0]["evidence"], name
        assert _fake_github_pat() not in crit[0]["file"], name


def test_audit_scansiona_segreti_nei_nomi_dei_symlink(tmp_path, monkeypatch):
    """GPT-5.5: un segreto nel NOME di un symlink (anche rotto/verso dir) deve
    essere scansionato in ENTRAMBI gli audit — il manual audit prima scartava i
    non-file prima dello scan, disallineandosi dal Claude audit."""
    for name, iter_name in (
        ("manual-full-repo-ai-audit.yml", "iter_text_files"),
        ("claude-fable-full-repo-audit.yml", "iter_files"),
    ):
        ns, root = _exec_audit_script(name, tmp_path, monkeypatch)
        sub = root / "links"
        sub.mkdir(exist_ok=True)
        link = sub / f"{_fake_github_pat()}.txt"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(root / "target-inesistente")  # symlink rotto (non is_file)

        _files, _skipped, path_findings = ns[iter_name]()
        crit = [f for f in path_findings if f["severity"] == "critical"]
        assert crit, f"{name}: segreto nel nome di un symlink non segnalato"
        assert _fake_github_pat() not in crit[0]["file"], name


def test_normalize_finding_strip_severity(tmp_path, monkeypatch):
    """Codex P2: severity con spazio/newline incidentale ('critical ') non deve
    mancare l'allowed-set e degradare a info (fail_on_critical la mancherebbe)."""
    for name in _AUDIT_WORKFLOWS:
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        norm = ns["normalize_finding"]
        assert norm({"severity": "critical ", "title": "x"}, "main.py", 1, 10)["severity"] == "critical", name
        assert norm({"severity": " HIGH\n", "title": "x"}, "main.py", 1, 10)["severity"] == "high", name


def test_make_chunks_tronca_righe_singole_oltre_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("CHUNK_MAX_CHARS", "200")
    long_line = "x" * 1000

    ns, _ = _exec_audit_script("manual-full-repo-ai-audit.yml", tmp_path, monkeypatch)
    chunks = ns["make_chunks"]("minified.js", long_line)
    assert all(len(c) <= 260 for _, _, c in chunks), "audit GPT: chunk oltre il budget"

    ns2, _ = _exec_audit_script("claude-fable-full-repo-audit.yml", tmp_path, monkeypatch)
    chunks2 = ns2["make_chunks"](long_line)
    assert all(len(c) <= 260 for _, _, c in chunks2), "audit Claude: chunk oltre il budget"


def test_local_secret_scan_trova_token_finto_e_redige_l_evidenza(tmp_path, monkeypatch):
    for name, fn_name in (
        ("manual-full-repo-ai-audit.yml", "local_secret_findings"),
        ("claude-fable-full-repo-audit.yml", "local_secret_scan"),
    ):
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)

        text = "riga innocua\n" + f'TOKEN = "{_fake_telegram_token()}"\n'
        findings = ns[fn_name]("config_store.py", text)
        telegram = [f for f in findings if f["title"].endswith("telegram_bot_token")]
        assert telegram and telegram[0]["severity"] == "critical", name
        assert telegram[0]["line_start"] == 2, name
        assert _fake_telegram_token() not in telegram[0]["evidence"], name

        # PEM multi-riga.
        pem = [f for f in ns[fn_name]("secret.pem", _fake_private_key_block() + "\n")
               if f["title"].endswith("private_key_block")]
        assert pem and pem[0]["severity"] == "critical", f"{name}: PEM multi-riga non rilevata"

        # PAT fine-grained (Codex P2 su PR #304).
        pat = [f for f in ns[fn_name]("cfg.py", f'PAT = "{_fake_github_pat()}"\n')
               if f["title"].endswith("github_fine_grained_pat")]
        assert pat and pat[0]["severity"] == "critical", f"{name}: PAT fine-grained non rilevato"
        assert _fake_github_pat() not in pat[0]["evidence"], name

        assert ns[fn_name]("main.py", "print('ciao')\n") == [], f"{name}: falso positivo"


def test_path_secret_scan_segnala_segreto_nel_nome_file(tmp_path, monkeypatch):
    """Segreto nel NOME file/cartella → finding critico, path/evidence redatti.

    Codex P2 (round 2, PR #304): il path viene redatto (safe_display) PRIMA di
    ogni finding e lo scan sui contenuti non lo vede; senza uno scan sul path RAW
    un token path-embedded darebbe 0 finding critici e ``fail_on_critical`` non
    fallirebbe. Il valore in chiaro non deve mai finire nel finding.
    """
    for name, fn_name in (
        ("manual-full-repo-ai-audit.yml", "path_secret_findings"),
        ("claude-fable-full-repo-audit.yml", "path_secret_scan"),
    ):
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        fn = ns[fn_name]
        safe_display = ns["safe_display"]

        raw = f"leaked/{_fake_github_pat()}.bak"
        display = safe_display(raw)
        findings = fn(raw, display)
        assert findings, f"{name}: segreto nel path non segnalato"
        assert findings[0]["severity"] == "critical", name
        assert findings[0]["source"] == "local-secret-scan", name
        # niente segreto in chiaro nel finding (file + evidence redatti)
        assert _fake_github_pat() not in findings[0]["evidence"], name
        assert _fake_github_pat() not in findings[0]["file"], name

        # path pulito → nessun finding
        assert fn("src/main.py", "src/main.py") == [], f"{name}: falso positivo sul path"


def test_audit_delimitatore_con_nonce_anti_injection():
    """Il delimitatore del contenuto non attendibile usa un nonce casuale.

    Codex P2 (round 2, PR #304): un file che contiene il testo letterale del
    marker statico ``--- FILE CONTENT END ---`` potrebbe chiudere il blocco e
    iniettare istruzioni. Con un nonce per-chunk (``os.urandom``) il contenuto
    non può riprodurre il delimitatore.
    """
    for name in _AUDIT_WORKFLOWS:
        text = _read(name)
        assert "os.urandom(8).hex()" in text, f"{name}: manca il nonce del delimitatore"
        assert "start_marker" in text and "end_marker" in text, (
            f"{name}: manca il marker delimitatore basato sul nonce"
        )
        # niente più delimitatore statico riproducibile dal contenuto del file
        assert "--- FILE CONTENT END ---" not in text, (
            f"{name}: delimitatore statico ancora presente (injection possibile)"
        )
        assert "--- FILE CONTENT START ---" not in text, (
            f"{name}: delimitatore statico ancora presente (injection possibile)"
        )


def test_normalize_finding_fail_closed_su_dati_del_modello(tmp_path, monkeypatch):
    for name in _AUDIT_WORKFLOWS:
        ns, _ = _exec_audit_script(name, tmp_path, monkeypatch)
        norm = ns["normalize_finding"]

        f = norm({"severity": "apocalittica", "title": "x"}, "main.py", 10, 20)
        assert f["severity"] == "info", name

        f = norm({"severity": "high", "line_start": 999, "line_end": 999}, "main.py", 10, 20)
        assert f["line_start"] is None, name

        f = norm({"severity": "critical", "line_start": 12, "line_end": 15}, "main.py", 10, 20)
        assert f["severity"] == "critical" and f["line_start"] == 12 and f["line_end"] == 15, name

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

    files, skipped, _path_findings = ns["iter_files"]()
    scanned = [str(p.relative_to(root)) for p in files]
    skipped_names = {item["file"] for item in skipped}

    assert scanned == ["a_main.py", "b_doc.md"], "solo i primi MAX_FILES file testuali"
    assert "bridge.exe" in skipped_names, "binario non saltato"
    assert "__pycache__/x.py" in skipped_names, "directory generata non saltata"
    assert "c_extra.txt" in skipped_names, "file oltre MAX_FILES non tracciato come saltato"
    assert all(item["reason"] for item in skipped)


def test_iter_files_non_segue_symlink_fuori_dallo_snapshot(tmp_path, monkeypatch):
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

        files, skipped, _path_findings = ns[iter_name]()
        scanned = [str(p.relative_to(root)) for p in files]
        assert "evil_link.txt" not in scanned, f"{name}: symlink seguito fuori dallo snapshot"
        evil = [item for item in skipped if item["file"] == "evil_link.txt"]
        assert evil, f"{name}: symlink saltato ma non tracciato"
        assert any("symlink" in item["reason"] for item in evil), (
            f"{name}: motivo dello skip non menziona il symlink"
        )


def test_audit_fallisce_se_tutti_i_chunk_ai_falliscono():
    """Codex P2: se ogni chunk AI fallisce (key invalida/API giù) l'audit non
    deve sembrare verde. La logica gira a runtime con la rete; qui si verifica
    che il guard esista nel sorgente eseguito."""
    for name in _AUDIT_WORKFLOWS:
        src = _compiled_heredoc(name)
        assert "chunks_succeeded" in src, f"{name}: manca il conteggio dei chunk riusciti"
        # Guard forte: file da scansionare ma zero chunk riusciti (API giù,
        # tutti parse error, o max_chunks=0) → fallisci, non 0/0 verde.
        assert re.search(r"scanned\w* and chunks_succeeded == 0", src), (
            f"{name}: manca il guard 'file scansionati ma nessun chunk riuscito -> fallisci'"
        )
        # Un parse error NON conta come chunk riuscito (Codex/CodeRabbit P2):
        # l'incremento è nell'else del check errore.
        assert re.search(r"else:\s*\n\s*chunks_succeeded \+= 1", src), (
            f"{name}: chunks_succeeded incrementato anche sui parse error"
        )


def test_dedup_finding_stabile(tmp_path, monkeypatch):
    ns, _ = _exec_audit_script("manual-full-repo-ai-audit.yml", tmp_path, monkeypatch)
    key = ns["finding_key"]
    a = {"severity": "high", "category": "bug", "file": "main.py", "line_start": 3, "title": "Doppione"}
    assert key(a) == key(dict(a)), "stesso finding -> stessa chiave (dedupe deterministico)"
    b = dict(a, line_start=4)
    assert key(a) != key(b), "riga diversa -> finding distinto"
