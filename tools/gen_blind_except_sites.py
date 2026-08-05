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

# DUE radici, non una (#263). Fino alla #262 il gate guardava solo `xtrader_bridge`: era verde
# perché non guardava, non perché non ci fosse niente da vedere. `license_manager/` — 57
# blind-except — ne restava fuori, ed è il codice che **firma le licenze**. È la stessa
# posizione in cui erano Fable e Fugu prima della #247, con la stessa morale: un controllo che
# tace è indistinguibile da uno che approva.
#
# `tests/` è entrato con l'esame che la #263 aveva rimandato, e l'esito è che il sospetto era
# INFONDATO: i suoi 19 handler ciechi non mascherano nulla. Tutti raccolgono l'eccezione in una
# lista su cui il test poi asserisce (`assert errors == []`), oppure sono sonde d'ambiente
# deliberate. Verificato per sabotaggio, non per lettura: facendo sollevare `write_csv` nel 30%
# delle chiamate, `test_concorrenza_write_clear_non_corrompe` diventa ROSSO ed elenca ogni
# singola eccezione raccolta.
#
# La radice entra lo stesso, per il caso FUTURO: un `except Exception: pass` in un worker —
# che ingoia senza raccogliere — oggi non lo vedrebbe nessuno.
#
# `tools/`, `main.py` e `license_manager_main.py` entrano per un rilievo di CodeRabbit sulla
# #265, ed è quello giusto: il commento qui accanto diceva «da qui il gate copre tutto ciò che
# contiene codice Python» mentre `RADICI` ne elencava tre — cioè affermava una copertura che il
# codice non aveva. Esattamente il difetto che questo gate esiste per chiudere, scritto nel
# commento che lo descriveva. Che oggi quei file abbiano ZERO blind-except non rendeva
# l'affermazione vera: il gate non li avrebbe visti nemmeno domani.
#
# Con questo elenco l'affermazione è verificabile: `git ls-files '*.py'` non produce nulla al di
# fuori di queste voci. Le voci possono essere cartelle o FILE SINGOLI (vedi `scansiona_tutte`).
RADICI = ("xtrader_bridge", "license_manager", "tests", "tools",
          "main.py", "license_manager_main.py")

# NIENTE costante `PKG` che punti a una sola radice (riserva Fable 5 sulla #263). Ce n'era una,
# tenuta «per retrocompatibilità», e con essa un commento che diceva «il test la usa» — falso già
# nello stesso commit, perché il test era passato a `scansiona_tutte`. Una costante che nomina UNA
# radice, in un modulo che ne sorveglia DUE, è un invito a coprirne metà per sbaglio: esattamente
# il difetto che questa PR chiude, riprodotto nella patch che lo chiudeva. Chi vuole una radice
# sola passi il path a `scansiona()` esplicitamente.
OUT = os.path.join(_RADICE, "tests", "safety", "blind_except_sites.py")

def is_broad(node):
    return isinstance(node, ast.Name) and node.id in ("Exception", "BaseException")


def is_blind(h):
    t = h.type
    if t is None or is_broad(t):
        return True
    return isinstance(t, ast.Tuple) and any(is_broad(e) for e in t.elts)


def normalizza_motivo(riga):
    """Motivo normalizzato dall'`# noqa: BLE001 ...` sulla riga, o stringa vuota se assente.

    **Per intero, NON troncato** (rilievo Fugu Ultra sulla #260). Una prima stesura tagliava a
    60 caratteri per non far scattare il gate su una riformulazione di dettaglio, ma due motivi
    diversi con lo stesso prefisso sarebbero collassati nella stessa identità — e la
    sostituzione a saldo zero, cioè il difetto che questo gate esiste per chiudere, sarebbe
    ripassata proprio da lì.

    Misurato al momento della correzione: collisioni reali **0**, ma **5 motivi su 194**
    superano i 60 caratteri (il più lungo, 71). Il buco era latente, non ancora sfruttato:
    chiuderlo costa cinque righe di baseline più lunghe, che per un gate di sicurezza è il
    prezzo giusto.
    """
    m = re.search(r"#\s*noqa:\s*BLE001\s*(.*)$", riga)
    if not m:
        return ""
    testo = m.group(1).strip()
    testo = re.sub(r"^[\s\-—:·,]+", "", testo)          # separatori iniziali
    return re.sub(r"\s+", " ", testo).strip().lower()


def qualname_map(tree):
    """riga dell'except → nome qualificato della funzione che lo contiene."""
    fuori = {}

    def visita(nodo, prefisso):
        for figlio in ast.iter_child_nodes(nodo):
            if isinstance(figlio, ast.ClassDef):
                visita(figlio, f"{prefisso}{figlio.name}.")
            elif isinstance(figlio, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nome = f"{prefisso}{figlio.name}"
                # PRIMA le annidate, poi questa: con `setdefault` vince chi arriva per primo,
                # quindi la funzione PIÙ INTERNA si prende i suoi handler. All'inverso, un
                # `except` dentro una closure risultava attribuito alla funzione esterna — il
                # nome nel baseline avrebbe mentito, e uno spostamento fra interna ed esterna
                # non si sarebbe visto (rilievo Fable 5 sulla #260: 5 casi reali, fra cui
                # `_safe_shutdown_tg._shutdown` e `commit_signals._realign_dirty_disk`).
                visita(figlio, f"{nome}.")
                for x in ast.walk(figlio):
                    if isinstance(x, ast.ExceptHandler):
                        fuori.setdefault(x.lineno, nome)
            else:
                visita(figlio, prefisso)

    visita(tree, "")
    return fuori


def siti_del_file(path):
    """Blind-except di UN file: lista ordinata di `(funzione, motivo)`, vuota se non ce ne sono.

    Estratta da `scansiona` perché `RADICI` contiene anche **file singoli** (`main.py`,
    `license_manager_main.py`): `os.walk` su un file non produce nulla, quindi senza questo
    innesto sarebbero rimasti scoperti mentre il commento accanto prometteva copertura totale.
    """
    # `with`, non `open(...).read()`: quest'ultimo lascia il file alla mercé del GC e CPython
    # emette un ResourceWarning reale (verificato con `-W error::ResourceWarning` su tutti i
    # file). Su un ciclo che apre l'intero package non è teorico, ed è il tipo di dettaglio che
    # si liquida come «minore» finché non lo è (rilievo Fugu Ultra sulla #260).
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    righe = src.split("\n")
    tree = ast.parse(src)
    qmap = qualname_map(tree)
    return sorted((qmap.get(h.lineno, "<modulo>"), normalizza_motivo(righe[h.lineno - 1]))
                  for h in ast.walk(tree)
                  if isinstance(h, ast.ExceptHandler) and is_blind(h))


def scansiona(radice):
    """Blind-except di una CARTELLA, con chiavi relative alla cartella stessa.

    Contratto invariato (lo esercita il test del rilevatore su una cartella temporanea): per i
    file singoli e l'unione delle radici vedi `scansiona_tutte`.
    """
    siti = {}
    for dirpath, _d, files in os.walk(radice):
        if "__pycache__" in dirpath:
            continue
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            trovati = siti_del_file(path)
            if trovati:
                rel = os.path.relpath(path, radice).replace(os.sep, "/")
                siti[rel] = trovati
    return siti


def scansiona_tutte(base=None, radici=RADICI):
    """Siti di TUTTE le voci sorvegliate, con chiavi relative alla radice del REPOSITORY.

    Una voce di `RADICI` può essere una **cartella** (`xtrader_bridge`) o un **file singolo**
    (`main.py`): i due casi si distinguono qui, perché `os.walk` su un file non produce nulla e
    li avrebbe saltati in silenzio — che in un gate di copertura è il modo peggiore di sbagliare.

    `scansiona(radice)` resta invariata — chiavi relative alla cartella che riceve — perché è il
    contratto che il test del rilevatore esercita su una cartella temporanea. Qui ci si limita a
    unire le voci e a qualificare le chiavi.

    Le chiavi sono qualificate (`xtrader_bridge/app.py`, non `app.py`) **su tutte** le cartelle,
    non solo su quelle aggiunte dopo la prima. Prefissare solo le nuove avrebbe prodotto un
    baseline in cui una chiave nuda significa «xtrader_bridge» per convenzione implicita: in un
    gate l'asimmetria è precisamente il tipo di dettaglio che un lettore futuro legge male, e
    due file omonimi in cartelle diverse si sarebbero sovrascritti in silenzio.
    """
    base = base or _RADICE
    fuori = {}
    for voce in radici:
        percorso = os.path.join(base, voce)
        if os.path.isdir(percorso):
            for rel, trovati in scansiona(percorso).items():
                fuori[f"{voce}/{rel}"] = trovati
        else:
            trovati = siti_del_file(percorso)
            if trovati:
                fuori[voce.replace(os.sep, "/")] = trovati
    return fuori


def main():
    siti = scansiona_tutte()
    tot = sum(len(v) for v in siti.values())
    senza = sum(1 for v in siti.values() for _f, m in v if not m)
    righe = ['"""Baseline PER-SITO del gate blind-except (#224) — dati, non logica.',
             "",
             "Ogni voce è `(funzione, motivo)` dove il motivo viene dal `# noqa: BLE001` **sulla",
             "riga dell'except**, normalizzato (minuscolo, spazi collassati) e preso PER "
             "INTERO: troncarlo farebbe collidere due motivi con lo stesso prefisso, e la "
             "sostituzione a saldo zero ripasserebbe.",
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
