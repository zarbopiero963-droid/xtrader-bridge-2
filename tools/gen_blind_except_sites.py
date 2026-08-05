"""Generatore del baseline per-sito del gate blind-except (#224).

Produce `tests/safety/blind_except_sites.py`. Non fa parte della suite: si lancia a mano
quando il baseline va rigenerato, e il diff si legge riga per riga.
"""
import ast
import os
import re
import sys

# Path ancorati alla posizione DI QUESTO FILE, non alla cartella da cui si lancia: uno script
# che scrive un baseline in un posto che dipende dalla CWD è un modo silenzioso di sbagliare.
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(_RADICE, "xtrader_bridge")
OUT = os.path.join(_RADICE, "tests", "safety", "blind_except_sites.py")

MAX_MOTIVO = 60


def is_broad(node):
    return isinstance(node, ast.Name) and node.id in ("Exception", "BaseException")


def is_blind(h):
    t = h.type
    if t is None or is_broad(t):
        return True
    return isinstance(t, ast.Tuple) and any(is_broad(e) for e in t.elts)


def normalizza_motivo(riga):
    """Motivo normalizzato dall'`# noqa: BLE001 ...` sulla riga, o '' se assente."""
    m = re.search(r"#\s*noqa:\s*BLE001\s*(.*)$", riga)
    if not m:
        return ""
    testo = m.group(1).strip()
    testo = re.sub(r"^[\s\-—:·,]+", "", testo)          # separatori iniziali
    testo = re.sub(r"\s+", " ", testo).strip().lower()
    return testo[:MAX_MOTIVO]


def qualname_map(tree):
    """riga dell'except → nome qualificato della funzione che lo contiene."""
    fuori = {}

    def visita(nodo, prefisso):
        for figlio in ast.iter_child_nodes(nodo):
            if isinstance(figlio, ast.ClassDef):
                visita(figlio, f"{prefisso}{figlio.name}.")
            elif isinstance(figlio, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nome = f"{prefisso}{figlio.name}"
                for x in ast.walk(figlio):
                    if isinstance(x, ast.ExceptHandler):
                        fuori.setdefault(x.lineno, nome)
                visita(figlio, f"{nome}.")
            else:
                visita(figlio, prefisso)

    visita(tree, "")
    return fuori


def scansiona(radice):
    siti = {}
    for dirpath, _d, files in os.walk(radice):
        if "__pycache__" in dirpath:
            continue
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            src = open(path, encoding="utf-8").read()
            righe = src.split("\n")
            tree = ast.parse(src)
            qmap = qualname_map(tree)
            trovati = []
            for h in ast.walk(tree):
                if isinstance(h, ast.ExceptHandler) and is_blind(h):
                    trovati.append((qmap.get(h.lineno, "<modulo>"),
                                    normalizza_motivo(righe[h.lineno - 1])))
            if trovati:
                rel = os.path.relpath(path, radice).replace(os.sep, "/")
                siti[rel] = sorted(trovati)
    return siti


def main():
    siti = scansiona(PKG)
    tot = sum(len(v) for v in siti.values())
    senza = sum(1 for v in siti.values() for _f, m in v if not m)
    righe = ['"""Baseline PER-SITO del gate blind-except (#224) — dati, non logica.',
             "",
             "Ogni voce è `(funzione, motivo)` dove il motivo viene dal `# noqa: BLE001` **sulla",
             "riga dell'except**, normalizzato (minuscolo, spazi collassati, troncato a "
             f"{MAX_MOTIVO} caratteri).",
             "",
             "Prima della #224 il gate confrontava solo il NUMERO di blind-except per file, quindi",
             "rimuoverne uno motivato e aggiungerne uno nudo altrove nello stesso file lasciava il",
             "totale invariato e passava. Con le identità qui sotto quella sostituzione a saldo zero",
             "non passa più.",
             "",
             "**Come si aggiorna:** `python tools/gen_blind_except_sites.py` e si LEGGE il diff.",
             "Un baseline aggiornato a occhi chiusi è peggio di nessun baseline — vedi il commento",
             "in testa a `test_blind_except_allowlist.py`.",
             '"""',
             "",
             "# file → tuple ordinate di (funzione, motivo normalizzato)",
             "SITI = {"]
    for f in sorted(siti):
        righe.append(f"    {f!r}: (")
        for fn, mot in siti[f]:
            righe.append(f"        ({fn!r}, {mot!r}),")
        righe.append("    ),")
    righe.append("}")
    righe.append("")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(righe))
    print(f"scritto {OUT}: {len(siti)} file, {tot} siti, {senza} senza motivo")


if __name__ == "__main__":
    sys.exit(main())
