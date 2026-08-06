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

import pytest

from tests.safety.workflow_ast import extract_func, extract_heredocs

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


def _usage_note_reale():
    """La `usage_note` VERA del workflow, estratta dall'heredoc via AST ed eseguita isolata.

    Stessa tecnica di `_touches_core_reale` in `test_ai_audit_workflows.py`, e per la stessa
    ragione (rilievo CodeRabbit su questa PR, fondato): la prima stesura di questo test
    cercava la stringa `reasoning_tokens` nel sorgente — sarebbe passata anche se comparisse
    solo in un **commento**, o in un'assegnazione mai usata. Cioè proprio il falso-verde che
    il `CLAUDE.md` vieta: «i test devono esercitare funzioni reali del progetto».

    Qui si misura il **comportamento**: dato un `usage`, cosa scrive nel report.
    """
    import ast
    import re as _re

    blocchi = extract_heredocs(_fugu())
    assert len(blocchi) == 1, f"atteso 1 heredoc Python nel workflow, trovati {len(blocchi)}"
    albero = ast.parse(blocchi[0])
    # Servono anche le costanti di prezzo che `usage_note` usa: si estraggono dallo stesso
    # sorgente invece di ricopiarne i valori qui, altrimenti il test resterebbe verde con
    # un listino stantio (e il costo riportato dal workflow sarebbe sbagliato senza che
    # nessuno se ne accorga).
    NECESSARIE = ("PRICE_INPUT_PER_MILLION", "PRICE_OUTPUT_PER_MILLION")
    voluti = [n for n in albero.body
              if (isinstance(n, ast.FunctionDef) and n.name == "usage_note")
              or (isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id in NECESSARIE for t in n.targets))]
    funzioni = [n for n in voluti if isinstance(n, ast.FunctionDef)]
    assert len(funzioni) == 1, (
        f"attesa una sola `usage_note` a livello modulo, trovate {len(funzioni)} — "
        "il report costi è stato ristrutturato, aggiorna questo test"
    )
    assert len(voluti) == len(funzioni) + len(NECESSARIE), (
        "le costanti di prezzo non sono più assegnate a livello modulo: "
        f"attese {NECESSARIE}, il costo nel report non sarebbe calcolabile"
    )
    # Le costanti leggono l'ambiente: si forniscono gli STESSI valori dichiarati nell'`env:`
    # del workflow, così il prezzo esercitato è quello vero e non un default a zero.
    import os as _os
    prezzi = dict(_re.findall(r'^      (PRICE_\w+): "([\d.]+)"$', _fugu(), _re.M))
    assert len(prezzi) >= 2, f"listino non leggibile dall'env del workflow: {prezzi}"
    vecchio_env = {k: _os.environ.get(k) for k in prezzi}
    _os.environ.update(prezzi)
    try:
        ns = {"os": _os}
        exec(compile(ast.Module(body=voluti, type_ignores=[]), "fugu#usage_note", "exec"), ns)  # noqa: S102
    finally:
        for k, v in vecchio_env.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
    return ns["usage_note"]


def test_usage_note_RENDE_i_token_di_reasoning():
    """I 9.600 token di reasoning erano invisibili nel report, che mostrava solo
    `completion_tokens`: un ragionamento esploso era indistinguibile da una review lunga, ed
    è per questo che il difetto ① è sopravvissuto a lungo.

    Si esercita la funzione vera con un `usage` realistico — quello della PR #292, dove Fugu
    ha riportato 1.702 completion di cui 1.496 di reasoning.
    """
    usage_note = _usage_note_reale()

    testo = usage_note(
        {"prompt_tokens": 7899, "completion_tokens": 1702,
         "completion_tokens_details": {"reasoning_tokens": 1496}},
        "system", "user", "review",
    )

    assert "1496" in testo, f"il conteggio del reasoning non compare nel report: {testo!r}"
    assert "87%" in testo, f"la percentuale non è calcolata correttamente: {testo!r}"
    assert "1702" in testo, "il totale completion deve restare visibile"


def test_usage_note_TACE_se_il_modello_non_riporta_reasoning():
    """Contro-guardia: la riga in più non deve comparire quando il dato non c'è.

    Serve perché `usage_note` è condivisa con le risposte che NON hanno il dettaglio (errori,
    fallback, provider che non lo espongono): una riga «di cui reasoning: 0 (0%)» sarebbe una
    misura inventata, non un'assenza dichiarata.
    """
    usage_note = _usage_note_reale()

    testo = usage_note({"prompt_tokens": 100, "completion_tokens": 200}, "s", "u", "r")

    assert "reasoning" not in testo.lower(), (
        f"senza il dato il report non deve inventare una riga: {testo!r}"
    )
    assert "200" in testo, "il resto del report deve funzionare comunque"


def test_fugu_non_spende_su_un_push_senza_label():
    """Il difetto ②, verificato sul COMPORTAMENTO e non sul testo.

    La prima stesura cercava `if EVENT_ACTION != "labeled":` nel sorgente — è morta al primo
    refactor legittimo (l'estrazione della decisione in funzione pura), che è esattamente la
    fragilità segnalata da GPT-5.5. Qui si esegue la decisione vera.
    """
    decisione_gate = _funzione_dal_workflow("decisione_gate")

    assert decisione_gate("synchronize", ["manual-review-required"], "final-fugu-review") == "salta"


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


def _funzione_dal_workflow(nome):
    """La funzione `nome` dell'heredoc Fugu, estratta ed **eseguibile**.

    L'estrazione non è scritta qui: gli helper stanno in `tests/safety/workflow_ast.py`,
    che è la fonte unica condivisa con `test_ai_audit_workflows.py` (regola 3 — la prima
    stesura di questo modulo ne aveva una seconda copia, ed è stata rimossa).
    """
    blocchi = extract_heredocs(_fugu())
    assert len(blocchi) == 1, (
        f"atteso 1 heredoc Python nel workflow Fugu, trovati {len(blocchi)}: l'estrazione "
        "per posizione non è più affidabile, va ancorata al blocco giusto"
    )
    return extract_func(blocchi[0], nome, {"os": os})


@pytest.mark.parametrize("evento,armato,atteso", [
    # Il gate è armato dalla label: si revisiona a prescindere dall'evento…
    ("labeled",          True,  "revisiona"),
    ("opened",           True,  "revisiona"),   # ← il buco trovato da Fugu
    ("reopened",         True,  "revisiona"),
    ("ready_for_review", True,  "revisiona"),
    # …tranne quando il head si è mosso DOPO l'armamento: lì è stantio, non verde.
    ("synchronize",      True,  "stantio"),
    # Senza label non si spende mai, qualunque sia l'evento.
    ("synchronize",      False, "salta"),
    ("opened",           False, "salta"),
    ("reopened",         False, "salta"),
])
def test_decisione_gate_su_ogni_evento(evento, armato, atteso):
    """Il test che GPT-5.5 e CodeRabbit hanno chiesto **due volte** su questa PR, e avevano
    ragione entrambe le volte: le prime stesure asserivano pattern testuali nel workflow —
    fragili ai refactor e, soprattutto, incapaci di dimostrare il comportamento.

    Ora la decisione è una funzione pura nello script, estratta ed **eseguita** qui su tutti
    gli eventi che GitHub può emettere su una PR. Il caso `opened + armato` è il buco che
    Fugu aveva trovato: una PR aperta con la label già applicata non riceve `labeled`, e con
    lo skip silenzioso il check restava verde senza che nessuno avesse guardato.
    """
    decisione_gate = _funzione_dal_workflow("decisione_gate")

    etichette = ["manual-review-required"] + (["final-fugu-review"] if armato else [])

    assert decisione_gate(evento, etichette, "final-fugu-review") == atteso


def test_decisione_gate_e_pura():
    """Contro-guardia: la decisione non deve dipendere dall'ambiente o da stato globale,
    altrimenti il test sopra proverebbe qualcosa di diverso da ciò che gira in CI."""
    decisione_gate = _funzione_dal_workflow("decisione_gate")

    prima = decisione_gate("synchronize", ["final-fugu-review"], "final-fugu-review")
    os.environ["LABELS_PRESENTI"] = "niente"
    os.environ["EVENT_ACTION"] = "labeled"
    dopo = decisione_gate("synchronize", ["final-fugu-review"], "final-fugu-review")

    assert prima == dopo == "stantio", "la decisione legge l'ambiente invece dei suoi argomenti"


def test_una_label_QUALSIASI_non_fa_spendere():
    """Rilievo GPT-5.5: `decisione_gate("labeled", …)` rispondeva «revisiona» a prescindere
    dalla label, appoggiandosi al filtro YAML del job (`github.event.label.name ==
    'final-fugu-review'`).

    Il filtro c'è ed è corretto, ma far dipendere una decisione di **costo** da un altro
    strato è fragile: basta che qualcuno allarghi la condizione del job — per esempio per
    reagire a `manual-review-required` — e la funzione comincia a spendere senza che nulla
    la fermi. Difesa in profondità: la decisione richiede il gate ARMATO in ogni caso.
    """
    decisione_gate = _funzione_dal_workflow("decisione_gate")

    # `labeled` di un'altra label, senza quella finale fra le presenti
    assert decisione_gate("labeled", ["manual-review-required"], "final-fugu-review") == "salta"
    # …e con quella finale presente si revisiona, come deve
    assert decisione_gate("labeled", ["final-fugu-review"], "final-fugu-review") == "revisiona"


def test_estrazione_heredoc_non_prende_il_blocco_sbagliato():
    """Rilievo GPT-5.5: `_funzione_dal_workflow` prendeva il PRIMO blocco `python3 <<'PY'`.
    Oggi ce n'è uno solo, ma se un domani ne comparisse un altro prima, i test validerebbero
    lo script sbagliato restando verdi — un falso verde silenzioso."""
    blocchi = extract_heredocs(_fugu())

    assert len(blocchi) == 1, (
        f"atteso 1 heredoc Python nel workflow, trovati {len(blocchi)}: l'estrazione per "
        "posizione non è più affidabile, va ancorata al blocco giusto"
    )


# ── Regola 2: la CLASSE, non il sito ───────────────────────────────────────────────────────
#
# Il rilievo di GPT-5.5 qui sopra non riguarda Fugu: riguarda «un gate di SPESA che si fida
# del filtro YAML del job». Cercato il pattern su tutti i workflow, **Fable ha lo stesso
# difetto**: il suo salto per assenza di file core è condizionato a `EVENT_ACTION != "labeled"`,
# quindi un evento `labeled` — di qualunque label — bypassa il controllo core e fa spendere.
# Oggi non succede perché la condizione YAML filtra le altre label; ma è esattamente la stessa
# dipendenza da un altro strato, sullo stesso tipo di decisione (soldi).

_FABLE = os.path.join(_RADICE, ".github", "workflows", "pr-review-claude-fable5.yml")


def _fable() -> str:
    with open(_FABLE, encoding="utf-8") as fh:
        return fh.read()


def _funzione_da_fable(nome):
    blocchi = extract_heredocs(_fable())
    assert len(blocchi) == 1, (
        f"atteso 1 heredoc Python nel workflow Fable, trovati {len(blocchi)}"
    )
    return extract_func(blocchi[0], nome, {"os": os})


@pytest.mark.parametrize("evento,etichette,atteso", [
    # La label finale, e solo quella, arma il gate…
    ("labeled", ["final-fable-review"], True),
    ("labeled", ["manual-review-required", "final-fable-review"], True),
    # …una label qualsiasi no: si torna al controllo sui file core, che è ciò che decide
    # se spendere su un push.
    ("labeled", ["manual-review-required"], False),
    ("labeled", [], False),
    # E nessun altro evento arma il gate: su `synchronize`/`opened` la spesa dipende dai
    # file core, non dalla label già presente da un giro precedente.
    ("synchronize", ["final-fable-review"], False),
    ("opened", ["final-fable-review"], False),
])
def test_fable_arma_il_gate_solo_con_la_SUA_label(evento, etichette, atteso):
    """Stesso rilievo di `test_una_label_QUALSIASI_non_fa_spendere`, applicato al sibling.

    Fable è il reviewer forte che resta anche sui push core: se una label qualsiasi gli
    facesse saltare il controllo core, spenderebbe su PR di soli docs/test — il costo che
    questa PR sta cercando di togliere.
    """
    gate_finale_armato = _funzione_da_fable("gate_finale_armato")

    assert gate_finale_armato(evento, etichette, "final-fable-review") is atteso


@pytest.mark.parametrize("workflow,leggi", [
    ("fugu", _fugu),
    ("fable", _fable),
])
def test_le_etichette_arrivano_DAVVERO_dall_env_del_job(workflow, leggi):
    """`decisione_gate`/`gate_finale_armato` ricevono le label come argomento, quindi i test
    di comportamento qui sopra restano verdi anche se l'`env:` che le fornisce sparisce — e
    il gate, in CI, non si armerebbe più (Fugu non spenderebbe MAI, Fable salterebbe il gate
    finale in silenzio). Serve un'ancora sulla DICHIARAZIONE.

    Non basta `"LABELS_PRESENTI" in testo`: la stringa compare comunque nello script che la
    legge. Verificato per sabotaggio — cancellando l'env, la versione con `in` restava verde.
    """
    testo = leggi()

    assert re.search(
        r"^      LABELS_PRESENTI: \$\{\{ join\(github\.event\.pull_request\.labels\.\*\.name,"
        r" ','\) \}\}$", testo, re.M), (
        f"{workflow}: manca l'env LABELS_PRESENTI — il gate non vede le label della PR"
    )
    assert re.search(rf"^      FINAL_LABEL: final-{workflow}-review$", testo, re.M), (
        f"{workflow}: manca l'env FINAL_LABEL — il gate userebbe il default hardcoded"
    )
