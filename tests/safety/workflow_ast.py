"""Estrazione ed esecuzione delle funzioni pure che vivono negli heredoc dei workflow.

I gate di **costo** dei reviewer forti (chi spende, chi salta, chi è stantio) sono scritti in
Python dentro un blocco ``python3 <<'PY'`` nel YAML. Testarli guardando il *testo* del
workflow è stato bocciato tre volte sulla PR #292 — da CodeRabbit e due volte da GPT-5.5 — e
avevano ragione: una regex passa anche quando il comportamento è sbagliato, e si rompe al
primo refactor. Con questi helper la funzione viene **estratta e chiamata davvero**.

Il codice non è nuovo: viveva in `test_ai_audit_workflows.py` come `_extract_heredocs` /
`_extract_func`. È stato spostato qui quando è servito anche a `test_fugu_costo_reasoning.py`,
perché la regola 3 del `CLAUDE.md` vieta la stessa logica scritta in due posti — due copie
corrette oggi sono due copie divergenti domani. I due moduli di test lo importano da qui.
"""

import ast
import re


def extract_heredocs(text):
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


def extract_func(src, fname, stubs):
    """Estrae UNA funzione dal sorgente heredoc dedentato ed esegue solo quel nodo,
    in un namespace con gli stub passati (safe_display/redact/is_critical), così può
    essere esercitata offline senza far girare il resto dello script (rete/API)."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            mod = ast.Module(body=[node], type_ignores=[])
            ns = dict(stubs)
            exec(compile(mod, "<heredoc>", "exec"), ns)  # noqa: S102 — sorgente del repo, test
            return ns[fname]
    raise AssertionError(f"{fname} non trovata nel sorgente di {src[:40]!r}…")
