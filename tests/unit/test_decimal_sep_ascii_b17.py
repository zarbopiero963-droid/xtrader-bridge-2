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

def test_nel_modulo_non_resta_nessuna_classe_di_cifre_unicode():
    """Il difetto non era «usare `\\d`»: era **riscrivere a mano** una classe di cifre che
    `numbers_re` definisce già. Riscritta ASCII resterebbe una seconda copia, divergente al
    primo cambio — la stessa Regola 3 che ha già morso tre volte in questo repo.

    **Guardia sul MODULO, non sulla funzione** (rilievo GPT-5.5 e Fable 5: la prima stesura era
    fragile). Tre differenze che contano:

    * legge il **file**, non `inspect.getsource` — un refactor che sposta la regex in una
      costante a livello modulo non la fa più fallire a torto, e la copre comunque;
    * cammina l'**AST** invece di `ast.unparse`, che è una resa testuale e può cambiare fra
      versioni di Python: qui si guardano nodi, non stringhe rigenerate;
    * **esclude docstring e commenti**: la prima stesura è diventata rossa sul docstring che
      *cita* `isdigit()` per spiegare il difetto storico, cioè puniva la documentazione del bug
      invece del bug. Si vieta la **chiamata**, non la parola.
    """
    import ast

    from xtrader_bridge import custom_pipeline

    albero = ast.parse(open(custom_pipeline.__file__, encoding="utf-8").read())

    docstring = {n.value for n in ast.walk(albero)
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}

    chiamate_isdigit = [n for n in ast.walk(albero)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "isdigit"]
    assert not chiamate_isdigit, (
        "`str.isdigit()` è Unicode-aware: accetta «٥», «५», «５» — è metà del difetto B17"
    )

    letterali_con_d = [n.value for n in ast.walk(albero)
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and n not in docstring and r"\d" in n.value]
    assert not letterali_con_d, (
        rf"`\d` in Python matcha TUTTE le cifre Unicode: è l'altra metà di B17. "
        rf"Letterali trovati: {letterali_con_d}"
    )

    assert "numbers_re" in {n.id for n in ast.walk(albero) if isinstance(n, ast.Name)} | {
        a.attr for a in ast.walk(albero) if isinstance(a, ast.Attribute)} | {
        al.name for imp in ast.walk(albero) if isinstance(imp, ast.ImportFrom)
        for al in imp.names}, (
        "la classe di cifre deve venire da `numbers_re`, non essere riscritta qui"
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


# ── Regola 2-bis, sul serio: il PERCORSO REALE, non la funzione isolata ────────────────────
#
# I test sopra chiamano `_decimal_sep_to_point` da sola. Il difetto della #202 era invisibile
# proprio così, e appariva solo passando per il chiamante. GPT-5.5 ha chiesto una prova
# end-to-end sui tre casi che contano: qui si costruisce una riga con la pipeline vera e si
# guarda cosa esce — status e valore — invece di fidarsi della funzione.

def _parser_con_handicap(valore):
    from xtrader_bridge.custom_parser import CustomParserDef, FieldRule

    return CustomParserDef(name="B17", mode="NAME_ONLY", rules=[
        FieldRule(target="Provider", fixed_value="TG"),
        FieldRule(target="EventName", fixed_value="Milan v Inter", required=True),
        FieldRule(target="MarketType", fixed_value="ASIAN_HANDICAP", required=True),
        FieldRule(target="SelectionName", fixed_value="Milan", required=True),
        FieldRule(target="BetType", fixed_value="PUNTA"),
        FieldRule(target="Handicap", fixed_value=valore),
    ])


def _riga(valore):
    from xtrader_bridge import custom_pipeline as pipe

    return pipe.build_validated_row(_parser_con_handicap(valore), "msg",
                                    provider="TG", require_price=False)


def test_end_to_end_le_cifre_non_ascii_non_producono_una_riga():
    """`"١,٥"` non deve diventare una riga piazzabile. Prima usciva `"١.٥"` dal normalizzatore
    e veniva fermato dal validatore; ora è fermato da entrambi — ma ciò che conta per l'utente
    è identico e va verificato QUI, alla fine del percorso: nessuna riga."""
    from xtrader_bridge import custom_pipeline as pipe

    res = _riga("١,٥")

    assert res.status == pipe.INVALID_HANDICAP
    assert not res.placeable, "un handicap non ASCII non deve produrre una scommessa"


def test_end_to_end_i_migliaia_ascii_arrivano_normalizzati():
    """Il controllo positivo, senza il quale il test sopra proverebbe solo che tutto è
    rifiutato: `"1.234,56"` deve continuare ad attraversare la pipeline e uscire canonico."""
    res = _riga("1.234,56")

    assert res.row["Handicap"] == "1234.56"


def test_end_to_end_handicap_negativo_con_virgola_resta_intatto():
    """Il caso che un fail-closed scritto male romperebbe per primo: il segno. `"-1,5"` è un
    Handicap legittimo e frequente — deve uscire `"-1.5"`, non invariato."""
    res = _riga("-1,5")

    assert res.row["Handicap"] == "-1.5"
