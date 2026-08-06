"""Fugu Ultra: due difetti di costo misurati sulle PR reali del 05/08/2026.

**① `reasoning: {"effort": "low"}` non è mai stato applicato.** Interrogato l'endpoint
pubblico `openrouter.ai/api/v1/models`, `sakana/fugu-ultra` dichiara:

    {"mandatory": true, "default_enabled": true,
     "supported_efforts": ["max", "xhigh", "high"], "default_effort": "xhigh"}

`"low"` **non è fra gli effort supportati**: il valore viene scartato e il modello applica il
suo default, `xhigh`. Cioè si pagava ragionamento quasi al massimo credendo di averlo capato
al minimo. E `mandatory: true` significa che non si può spegnere: `"high"` è il minimo
possibile per questo modello.

Le conseguenze si vedono nei costi riportati dai job stessi sulla PR #281: **9.600 e 12.598
completion token** contro i ~200-1.300 che il prompt ultra-corto prevede — perché i token di
reasoning **sono fatturati come output** (documentazione OpenRouter). Due di quelle review
sono state pagate e poi **troncate**, quindi buttate: $0.62 + $0.52.

Il commento nel workflow diceva *«effort=low libera budget per il testo; OpenRouter lo ignora
per i modelli non-reasoning, quindi è sicuro comunque»*. La prima metà era vera per GPT-5.5
(serie GPT-5: `low` è supportato), la seconda nascondeva il caso peggiore — un modello
reasoning che **ignora il valore e usa il proprio default alto**.

**② Fugu spendeva su ogni push che toccasse file core.** Decisione del proprietario: resta il
**gate finale a head stabile**, che è il suo ruolo dichiarato nel `CLAUDE.md`. Sui push
intermedi bastano GPT-5.5 e Fable, che insieme costano ~12 centesimi contro i ~55 di Fugu.
"""

import os
import re

_RADICE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FUGU = os.path.join(_RADICE, ".github", "workflows", "pr-review-openrouter-fugu-ultra.yml")


def _fugu() -> str:
    with open(_FUGU, encoding="utf-8") as fh:
        return fh.read()


#: Ciò che il modello dichiara di accettare (endpoint pubblico, nessuna chiave necessaria).
EFFORT_SUPPORTATI = ("max", "xhigh", "high")


def test_fugu_non_usa_un_effort_che_il_modello_NON_supporta():
    """Il difetto ①, nella forma che conta: non «usa `high`» ma «non usa un valore rifiutato».

    Scritto così perché il danno non è il valore in sé — è che un effort **non supportato**
    viene scartato in silenzio e subentra `default_effort`, che qui è `xhigh`. Un test che
    pretendesse letteralmente `"high"` passerebbe anche se domani il modello cambiasse i
    valori ammessi; questo invece resta legato alla ragione.
    """
    src = _fugu()
    match = re.search(r'"reasoning":\s*\{"effort":\s*"([a-z]+)"\}', src)

    assert match, "il payload Fugu deve dichiarare esplicitamente un reasoning effort"
    assert match.group(1) in EFFORT_SUPPORTATI, (
        f"effort {match.group(1)!r} NON è fra quelli supportati da sakana/fugu-ultra "
        f"{EFFORT_SUPPORTATI}: viene scartato e il modello applica il suo default "
        "'xhigh' — si paga ragionamento quasi al massimo credendo di averlo ridotto."
    )


def test_fugu_usa_il_MINIMO_effort_possibile():
    """Fra i tre supportati va scelto il più basso: il reasoning è `mandatory`, quindi
    l'unica leva di costo è il livello. `high` è il pavimento, non una preferenza."""
    src = _fugu()
    match = re.search(r'"reasoning":\s*\{"effort":\s*"([a-z]+)"\}', src)

    assert match and match.group(1) == "high", (
        f"atteso l'effort MINIMO supportato ('high'), trovato {match and match.group(1)!r}: "
        "'max'/'xhigh' costano di più senza servire a una review di 150 parole."
    )


def test_fugu_spiega_nel_workflow_perche_non_e_low():
    """La ragione va nel file, non solo qui: chi in futuro vedesse `high` accanto al `low`
    di GPT-5.5 penserebbe a una svista e lo "correggerebbe", riaprendo il difetto."""
    src = _fugu()

    assert "supported_efforts" in src, (
        "il workflow deve dire PERCHÉ non usa 'low' (i valori ammessi dal modello), "
        "altrimenti la differenza con GPT-5.5 sembra un errore da correggere"
    )


def test_fugu_riporta_i_token_di_REASONING_separati():
    """I 9.600 token di reasoning erano invisibili nel report costi, che mostrava solo
    `completion_tokens`. Senza quella riga il difetto ① era indistinguibile da «il modello
    è verboso» — ed è per questo che è sopravvissuto. Il report deve separarli."""
    src = _fugu()

    assert "reasoning_tokens" in src, (
        "il report costi deve esporre i token di reasoning separati dal testo: senza, "
        "un ragionamento che esplode è indistinguibile da una review lunga"
    )


def test_fugu_chiama_il_modello_SOLO_sulla_label_finale():
    """Il difetto ②. Il modello si chiama solo quando l'agente arma il gate finale a head
    stabile — mai su un push intermedio, per quanto tocchi file core.

    NB: il workflow **parte** comunque sui push (serve a pubblicare lo stato del check);
    ciò che qui si pretende è che **esca senza spendere** se l'evento non è `labeled`.
    """
    src = _fugu()

    assert re.search(r'if\s+EVENT_ACTION\s*!=\s*"labeled"\s*:', src), (
        "manca lo skip incondizionato sui push: Fugu deve spendere SOLO sulla label finale"
    )


def test_fugu_non_ha_piu_il_gate_core_ormai_morto():
    """Contro-guardia: tolto lo skip condizionato, `CORE_TRIGGER_PATTERNS`/`touches_core`
    non decidono più nulla. Lasciarli sarebbe codice morto che *sembra* governare il costo —
    e la prossima persona che legge il file crederebbe che Fugu parta ancora sui file core."""
    src = _fugu()

    assert "CORE_TRIGGER_PATTERNS" not in src and "touches_core" not in src, (
        "il gate core di Fugu è ormai inerte (spende solo su label): va rimosso, non "
        "lasciato lì a suggerire un comportamento che non esiste più"
    )


def test_gli_ALTRI_reviewer_non_sono_stati_toccati():
    """Regola 5: si cambia il costo di UN reviewer, non la copertura della PR.

    GPT-5.5 resta automatico a ogni push (è l'unico sempre attivo, e costa due centesimi) e
    Fable resta sul suo gate core+label. Se questa PR li spegnesse, ridurrebbe la revisione
    invece del costo.
    """
    for nome, atteso in (("pr-review-gpt55.yml", "synchronize"),
                         ("pr-review-claude-fable5.yml", "touches_core")):
        p = os.path.join(_RADICE, ".github", "workflows", nome)
        with open(p, encoding="utf-8") as fh:
            testo = fh.read()
        assert atteso in testo, f"{nome}: copertura ridotta per sbaglio (manca {atteso!r})"


# ── la falla trovata da Fugu STESSO sulla PR #292 ──────────────────────────────────────────

def test_un_push_DOPO_la_label_non_lascia_un_verde_bugiardo():
    """Bloccante sollevato da Fugu Ultra sulla PR che lo correggeva — e fondato.

    Scenario: si arma il gate finale (label) → Fugu revisiona il head A → arriva un push →
    head B → evento `synchronize` → con lo skip incondizionato il job **esce 0** e il check
    resta **verde**. Ma quel verde si riferisce a una review del head A: sul head B nessuno
    ha guardato, e la label è ancora lì a dire che il gate è stato armato.

    Prima di questa PR il buco esisteva già ma era più stretto (su un push a file core Fugu
    revisionava davvero). Lo skip incondizionato lo ha **allargato**: quindi va chiuso qui,
    non lasciato com'era.

    Fail-closed: se la label finale è presente e il head si è mosso, il gate è **stantio** e
    il job lo dichiara invece di tacere. Un check verde che significa «non ho guardato» è
    esattamente il difetto della #274 («un reviewer che non ha interrogato il modello risulta
    success come uno che ha revisionato»).
    """
    src = _fugu()

    assert "LABELS_PRESENTI" in src or "gate_stantio" in src, (
        "il workflow deve accorgersi di un push arrivato DOPO la label finale: altrimenti "
        "lascia un check verde su un head che nessun reviewer forte ha letto"
    )
    assert "sys.exit(1)" in src, (
        "il gate stantio dev'essere fail-closed (job rosso), non un avviso che nessuno legge"
    )
