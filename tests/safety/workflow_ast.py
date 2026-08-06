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
    """Estrae i blocchi ``python3 <<'PY' ... PY`` come li vede la shell.

    Il delimitatore di chiusura è riconosciuto **solo** con l'indentazione esatta di
    apertura, e un blocco che arriva a fine file senza chiusura **solleva** invece di essere
    restituito monco (rilievo CodeRabbit sulla #292). Prima bastava una riga il cui
    `.strip()` fosse `PY` — quindi una riga di codice Python indentata chiamata `PY` avrebbe
    troncato il blocco, e i test di sicurezza avrebbero validato un workflow tagliato
    credendolo intero. Un test che valida meno di ciò che gira è un falso verde.
    """
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)python3 <<'PY'\s*$", lines[i])
        if m:
            indent = m.group(1)
            chiusura = f"{indent}PY"
            body = []
            i += 1
            chiuso = False
            while i < len(lines):
                line = lines[i]
                if line == chiusura:
                    chiuso = True
                    break
                if line.startswith(indent):
                    line = line[len(indent):]
                body.append(line)
                i += 1
            if not chiuso:
                raise ValueError(
                    "heredoc Python non terminato: manca la riga di chiusura `PY` con "
                    f"l'indentazione di apertura ({len(indent)} spazi)"
                )
            blocks.append("\n".join(body))
        i += 1
    return blocks


def extract_func(src, fname, stubs):
    """Estrae UNA funzione dal sorgente heredoc dedentato ed esegue solo quel nodo,
    in un namespace con gli stub passati (safe_display/redact/is_critical), così può
    essere esercitata offline senza far girare il resto dello script (rete/API).

    Pretende **esattamente una** definizione a livello modulo (rilievo CodeRabbit sulla
    #292): Python lega il nome all'ULTIMA definizione, mentre questo helper restituiva la
    PRIMA. Con due definizioni omonime il test avrebbe esercitato un'implementazione diversa
    da quella che gira nel workflow — verde su codice che non è quello eseguito.
    """
    tree = ast.parse(src)
    trovate = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fname]
    if len(trovate) != 1:
        raise AssertionError(
            f"attesa UNA definizione di {fname} a livello modulo, trovate {len(trovate)}: "
            "con più definizioni il test eserciterebbe un'implementazione diversa da quella "
            "che Python lega al nome (l'ultima)"
        )
    mod = ast.Module(body=[trovate[0]], type_ignores=[])
    ns = dict(stubs)
    exec(compile(mod, "<heredoc>", "exec"), ns)  # noqa: S102 — sorgente del repo, test
    return ns[fname]
