"""La fonte unica dell'input annidato deve essere corretta *lei*, o sposta il difetto.

`tests/unit/json_patologico.py` nasce nella PR #296 per R5 della #211: tre file costruivano
l'input patologico con la stessa costante scritta a mano. Un helper condiviso però concentra
il rischio — se sbaglia, sbagliano insieme i tre file che lo usano. Quindi va esercitato come
codice vero, non dato per buono perché «è solo un test».

Copre le tre cose che possono andare storte:

1. **la forma** — i documenti devono essere JSON *validi* a profondità piccola, altrimenti i
   test a valle fallirebbero per «JSON malformato» credendo di aver misurato la ricorsione;
2. **la validazione** — `livelli=0` o negativo produceva JSON rotto travestito da input
   ostile (rilievo CodeRabbit sulla #296);
3. **il predicato** — `premessa_regge` deve dire `True` solo dove il documento è davvero
   patologico, e non deve mai sollevare.
"""

import json
import sys

import pytest

from tests.unit import json_patologico as jp

# ── ① la forma: a profondità piccola devono essere JSON validi ─────────────────────────

def test_liste_a_profondita_piccola_e_json_valido_della_forma_attesa():
    """Se il generatore producesse JSON malformato, i test a valle andrebbero rossi con
    «Expecting value» e sembrerebbe un bug del codice sotto esame, non del generatore."""
    assert json.loads(jp.json_annidato_liste("entries", 3)) == {"entries": [[[]]]}


def test_oggetti_a_profondita_piccola_e_json_valido_della_forma_attesa():
    assert json.loads(jp.json_annidato_oggetti("a", 3)) == {"a": {"a": {"a": 1}}}


@pytest.mark.parametrize("n", [1, 2, 5, 40])
def test_le_parentesi_sono_bilanciate_a_ogni_profondita(n):
    """La classe di bug più probabile in un generatore così: un `n - 1` di troppo o di meno.
    Si verifica decodificando davvero, non contando i caratteri."""
    assert json.loads(jp.json_annidato_liste("k", n)) is not None
    assert json.loads(jp.json_annidato_oggetti("k", n)) is not None


def test_la_profondita_degli_oggetti_e_esattamente_quella_richiesta():
    """`json_annidato_oggetti` ha un `n - 1` nella costruzione: se fosse sbagliato di uno,
    tutti i test a valle userebbero una profondità diversa da quella dichiarata."""
    doc = json.loads(jp.json_annidato_oggetti("a", 7))
    livelli = 0
    while isinstance(doc, dict):
        doc = doc["a"]
        livelli += 1
    assert livelli == 7
    assert doc == 1


# ── ② la validazione: profondità non positive respinte (CodeRabbit #296) ───────────────

@pytest.mark.parametrize("n", [0, -1, -3000])
@pytest.mark.parametrize("generatore", [jp.json_annidato_liste, jp.json_annidato_oggetti])
def test_profondita_non_positiva_respinta(generatore, n):
    """FAIL-FIRST: prima della validazione, `livelli=0` restituiva `'{"k": }'` — JSON rotto —
    e `livelli=-1` un oggetto troncato. Un input rotto travestito da input ostile fa fallire
    il test a valle per la ragione sbagliata, che è il modo peggiore di fallire."""
    with pytest.raises(ValueError, match="profondità"):
        generatore("k", n)


def test_il_default_resta_valido_e_non_passa_dalla_validazione_per_caso():
    """La metà che impedisce di «validare» rompendo il caso normale."""
    assert jp.profondita_patologica() == jp.PROFONDITA
    assert jp.PROFONDITA >= 1
    json.loads(jp.json_annidato_liste("k", 2))          # non solleva


# ── ③ il predicato: risponde, non esplode ─────────────────────────────────────────────

def test_premessa_regge_riconosce_il_documento_patologico():
    """Sul documento di default e col limite di default, la premessa DEVE reggere: se un
    domani non reggesse più, i tre file a valle smetterebbero di esercitare il recovery e
    questo test lo dice invece di lasciarli verdi in silenzio."""
    if jp.PROFONDITA <= jp.limite_ricorsione():
        pytest.skip(f"profondità {jp.PROFONDITA} <= limite {jp.limite_ricorsione()}")
    assert jp.premessa_regge(jp.json_annidato_liste("entries")) is True
    assert jp.premessa_regge(jp.json_annidato_oggetti("a")) is True


@pytest.mark.parametrize("documento, perche", [
    ('{"a": 1}', "JSON valido e banale"),
    ("{non json", "JSON malformato"),
    ("", "stringa vuota"),
    ("[]", "array vuoto"),
])
def test_premessa_non_regge_su_cio_che_patologico_non_e(documento, perche):
    """`premessa_regge` non deve confondere «illeggibile» con «patologico»: un JSON
    malformato non è un annidamento profondo, e trattarli allo stesso modo rimetterebbe
    insieme proprio i due casi che R5 chiedeva di separare."""
    assert jp.premessa_regge(documento) is False, perche


def test_premessa_regge_non_solleva_su_input_non_stringa():
    """La promessa del docstring — «risponde a una domanda» — vale anche sugli input che
    `json.loads` rifiuta per tipo: `TypeError` è nella tupla, quindi diventa `False`."""
    assert jp.premessa_regge(None) is False          # type: ignore[arg-type]
    assert jp.premessa_regge(123) is False           # type: ignore[arg-type]


@pytest.mark.parametrize("limite_finto", [1000, 6000, 30000, 100000])
def test_il_consumo_di_stack_non_dipende_dal_recursion_limit(monkeypatch, limite_finto):
    """Il cuore del rilievo GPT-5.5 sulla #296, pinnato come invariante.

    I frame C consumati dallo scanner sono `min(profondità, limite)`. Con profondità FISSA
    sono al più `PROFONDITA` qualunque sia il limite; con una profondità legata al limite
    crescerebbero senza tetto — su Windows (stack ~1 MB) un segfault del runner, non un
    `RecursionError` gestito.

    **Il limite viene FINTO, non alzato davvero** (secondo rilievo GPT-5.5, e aveva ragione
    due volte di fila sullo stesso tema). La prima stesura chiamava
    `sys.setrecursionlimit(limite * 4)` con un `finally` a ripristinare: funziona, ma è un
    test contro la fragilità di CI che, per dimostrarla, muta lo stato globale
    dell'interprete — proprio la cosa che questa PR ha appena smesso di fare. Con
    `monkeypatch` sulla *lettura* si verifica lo stesso invariante senza che il limite reale
    cambi mai di un'unità, quindi nessun altro test può risentirne e nessuno stack può
    saltare, nemmeno a 100000.
    """
    monkeypatch.setattr(sys, "getrecursionlimit", lambda: limite_finto)

    assert jp.limite_ricorsione() == limite_finto, "il finto limite non è arrivato al modulo"
    assert jp.profondita_patologica() == jp.PROFONDITA, (
        f"con limite {limite_finto} la profondità è {jp.profondita_patologica()} invece di "
        f"{jp.PROFONDITA}: è tornata a essere funzione del recursion limit, e con essa il "
        f"consumo di stack C senza tetto"
    )
