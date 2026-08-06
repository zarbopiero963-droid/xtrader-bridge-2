"""B17 — `_decimal_sep_to_point` normalizzava numeri scritti con cifre NON ASCII.

`custom_pipeline` era l'ultimo modulo estraneo alla disciplina che `numbers_re` enuncia nel
proprio docstring:

    «Le cifre sono ASCII [0-9] e NON \\d: \\d matcherebbe le cifre Unicode,
     aprendo il fail-open #318 L2-1.»

Due rami del normalizzatore la violavano, e **il piano ne aveva visto uno solo**:

* **ramo misto** (virgola *e* punto presenti) — `re.fullmatch(r"\\d{1,3}…")` e
  `dec_part.isdigit()`, entrambi Unicode-aware: `"1.234,٥٦"` → `"1234.٥٦"`;
* **ramo a sola virgola** — `s.replace(",", ".")` **senza alcun controllo sulle cifre**:
  `"١,٥"` → `"١.٥"`, `"1٢٣٤,56"` → `"1٢٣٤.56"`.

Il secondo non era citato in nessuna nota, eppure è il ramo che i due esempi usati come prova
del difetto attraversano davvero. È la stessa lezione di PR-H e PR-E al contrario: l'elenco dei
siti è un punto di partenza, non un inventario.

**Conseguenza raggiungibile: nessuna, oggi.** Tutte e cinque le colonne che il normalizzatore
tocca (`Price`, `MinPrice`, `MaxPrice`, `Handicap`, `Points`) sono gatate a valle da validatori
che compongono `numbers_re.SIGNED_DECIMAL`, quindi ASCII-stretti. Questo lavoro è
**consolidamento** — portare la normalizzazione sulla stessa fonte stretta della validazione —
non la chiusura di un buco aperto. Il pericolo che chiude è un domani in cui qualcuno consumi il
valore normalizzato **senza** passare dal validatore.
"""

import re

import pytest

from xtrader_bridge import numbers_re
from xtrader_bridge.custom_pipeline import _decimal_sep_to_point


# ── Il difetto: cifre non-ASCII non devono essere normalizzate ─────────────────────────────
#
# Fail-closed: se la stringa non è un decimale ASCII, il normalizzatore non la tocca. Non
# «aggiusta» un valore che non è un numero — lo lascia com'è, e il validatore lo rifiuta.

@pytest.mark.parametrize("grezzo", [
    "١,٥",              # tutte arabo-indiane, ramo a SOLA VIRGOLA
    "1٢٣٤,56",          # miste, ramo a SOLA VIRGOLA
    "1.234,٥٦",         # miste, ramo MISTO (regex + isdigit)
    "١.٢٣٤,٥٦",         # tutte arabo-indiane, ramo MISTO
    "１,５",             # fullwidth
    "१,५",              # devanagari
])
def test_le_cifre_non_ascii_non_vengono_normalizzate(grezzo):
    assert _decimal_sep_to_point(grezzo) == grezzo, (
        "una stringa con cifre non-ASCII non è un decimale: il normalizzatore deve lasciarla "
        "com'è, non convertirne il separatore facendola sembrare un numero"
    )


# ── Le invarianti: ciò che funzionava deve continuare a funzionare ─────────────────────────
#
# Verificate ROSSE-o-VERDI prima della patch: devono valere identiche prima e dopo. È la metà
# che impedisce di «correggere» rendendo il normalizzatore inutile.

@pytest.mark.parametrize("grezzo,atteso", [
    ("1.234,56", "1234.56"),      # migliaia punto, decimale virgola
    ("1,234.56", "1234.56"),      # migliaia virgola, decimale punto
    ("1.234.567,89", "1234567.89"),
    ("1,5", "1.5"),               # sola virgola = decimale
    ("-1,5", "-1.5"),             # Handicap negativo
    ("+1,5", "+1.5"),             # Handicap positivo esplicito
    ("1.85", "1.85"),             # solo punto → invariato
    ("1234", "1234"),             # nessun separatore → invariato
    ("", ""),
    ("abc", "abc"),
    ("1.2.3,45", "1.2.3,45"),     # raggruppamento non valido → invariato (fail-closed)
    ("1.234,56,7", "1.234,56,7"),
])
def test_gli_ascii_si_comportano_esattamente_come_prima(grezzo, atteso):
    assert _decimal_sep_to_point(grezzo) == atteso


# ── Regola 3: la fonte stretta è UNA, e resta quella ───────────────────────────────────────

def test_il_normalizzatore_usa_la_fonte_unica_e_non_una_copia():
    """Il difetto non era «usare `\\d`»: era **riscrivere a mano** una classe di cifre che
    `numbers_re` definisce già. Riscritta ASCII resterebbe una seconda copia, divergente al
    primo cambio — la stessa Regola 3 che ha già morso tre volte in questo repo.

    Il test guarda il sorgente perché ciò che si pretende è **da dove viene** la classe, non
    cosa fa: due implementazioni corrette oggi darebbero lo stesso risultato e il test sarebbe
    verde su entrambe, che è esattamente il falso verde da evitare.

    **Il docstring è escluso di proposito.** La prima stesura leggeva la funzione intera ed è
    diventata rossa sul docstring che *cita* `isdigit()` per spiegare il difetto storico —
    cioè puniva la documentazione del bug invece del bug. Una spiegazione scritta accanto al
    codice è valore: la guardia deve vietare la **chiamata**, non la parola.
    """
    import ast
    import inspect

    from xtrader_bridge import custom_pipeline

    albero = ast.parse(inspect.getsource(custom_pipeline._decimal_sep_to_point).lstrip())
    corpo = albero.body[0].body
    if (isinstance(corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant)
            and isinstance(corpo[0].value.value, str)):
        corpo = corpo[1:]                      # via il docstring: si giudica il codice
    sorgente = "\n".join(ast.unparse(n) for n in corpo)

    assert "numbers_re." in sorgente, (
        "la classe di cifre deve venire da `numbers_re`, non essere riscritta qui"
    )
    assert "isdigit()" not in sorgente, (
        "`str.isdigit()` è Unicode-aware: accetta «٥», «५», «５» — è metà del difetto B17"
    )
    assert r"\d" not in sorgente, (
        r"`\d` in Python matcha TUTTE le cifre Unicode: è l'altra metà di B17"
    )


def test_la_classe_di_cifre_e_composta_dentro_numbers_re():
    """Contro-guardia alla fonte unica: `DECIMAL` deve **comporsi** dalla classe di cifre, non
    ripeterla. Altrimenti l'anti-drift vale verso i consumer ma non dentro il modulo che lo
    predica — ed è già il motivo per cui `SIGNED_DECIMAL` è composto da `DECIMAL`."""
    assert hasattr(numbers_re, "DIGIT"), "manca la classe di cifre come costante condivisa"
    assert numbers_re.DIGIT == r"[0-9]"
    assert numbers_re.DECIMAL == r"(?:[0-9]+(?:[.,][0-9]+)?)", (
        "il VALORE di DECIMAL non deve cambiare: cinque consumer lo compongono con le ancore"
    )
    assert numbers_re.DIGIT in numbers_re.DECIMAL


# ── Regola 2-bis: il consumatore, non solo la funzione ─────────────────────────────────────

def test_il_confine_col_validatore_regge_ancora():
    """Ciò che rendeva innocuo il difetto era il validatore a valle. Deve continuare a valere
    **anche dopo** la patch: ora sono due strati fail-closed invece di uno, e questo test è la
    prova che il secondo non è stato indebolito mentre si aggiungeva il primo."""
    accetta = re.compile(r"^" + numbers_re.SIGNED_DECIMAL + r"$").fullmatch

    for grezzo in ("١.٢٣٤,٥٦", "1٢٣٤,56", "١,٥"):
        uscita = _decimal_sep_to_point(grezzo)
        assert accetta(uscita) is None, (
            f"{grezzo!r} → {uscita!r}: il validatore deve continuare a scartarlo"
        )
