"""#282 A2 — «frase ambigua» e «nessuna frase combacia» non sono la stessa cosa.

Il resolver le distingue già (`resolve_market` ritorna `"ambiguous"` oppure `"none"`), ma il
chiamante le appiattiva entrambe su `MARKET_MAPPING_MISSING`. Il motivo mostrato all'utente le
elencava con un «o»:

    «mercato non risolvibile: frasi ambigue, o nessuna frase combacia e nessun mercato dalle regole»

Due cause **opposte**, con rimedi opposti: togliere una frase in conflitto ≠ aggiungerne una. Chi
legge quella riga ha il 50% di probabilità di lavorare nella direzione sbagliata.

## Il rischio vero non è il messaggio

`_BASE_BLOCKING` elenca gli stati della base che **impediscono la generazione delle righe multi**.
`MARKET_MAPPING_MISSING` è lì dentro. Introdurre un codice nuovo per l'ambiguità senza metterlo
in quella tupla significherebbe che una base con mercato **ambiguo** non blocca più nulla: le
righe multi verrebbero generate da un mercato che il resolver si è **rifiutato di indovinare**,
moltiplicando per N selezioni una scommessa su un mercato non identificato.

È la ragione per cui il test più importante di questo file non guarda il testo del motivo ma
`_BASE_BLOCKING`, ed è provato per sabotaggio.

## Regola 2-bis — i consumatori

Il valore di ritorno di `build_validated_row` cambia su un ramo. I consumatori letti:

- `_BASE_BLOCKING` / `_MULTI_RESOLVABLE` (`custom_pipeline`) — vedi sopra;
- `parser_diagnostics.diagnose` — marca `MarketName`/`SelectionName`;
- `test_market_source_language_wiring_5c` — asseriva il codice vecchio sull'ambiguità.
"""

import tempfile

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_pipeline as pipe
from xtrader_bridge import parser_diagnostics as pdiag
from xtrader_bridge import signal_router


def _parser(*, multi=False):
    """Parser NAME_ONLY che porta un mercato valido dalle regole-colonna, così l'override del
    dizionario (o il suo fail-closed) è sempre distinguibile."""
    regole = [
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="MarketType", fixed_value="FIRST_HALF_GOALS_15", required=True),
        cp.FieldRule(target="MarketName", fixed_value="1º tempo - Totale goal 1,5"),
        cp.FieldRule(target="SelectionName", fixed_value="Over 1,5 goal", required=True),
        cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
        cp.FieldRule(target="BetType", fixed_value="BACK", required=True),
    ]
    return cp.CustomParserDef(name="MktAmb", mode="NAME_ONLY",
                              market_mapping_profiles=["M"], team_separator="v", rules=regole)


def _voce(lingua, mercato, selezione, frase="gg"):
    return {"start_after": "Mercato:", "end_before": "\n", "phrase": frase,
            "market_type": "", "market_name": mercato, "selection_name": selezione,
            "language": lingua}


#: Stessa frase «gg», due mercati DIVERSI → ambiguità (fail-closed D2).
_VOCI_AMBIGUE = [
    _voce("EN", "Entrambe le squadre a segno", "Sì"),
    _voce("IT", "1º tempo - Totale goal 0,5", "Over 0,5 goal"),
]

_MSG = "Match: Inter v Milan\nMercato: gg\nQuota: 1,85\n"


def _cfg(voci):
    return {"provider": "TG", "active_parser": "MktAmb", "chat_id": "42",
            "recognition_mode": "NAME_ONLY", "source_language": "",
            "market_mappings": {"M": list(voci)}}


def _esito(voci):
    """Percorso LIVE reale (`signal_router.resolve_row`), non una chiamata interna."""
    with tempfile.TemporaryDirectory() as d:
        cp.save_parser(_parser(), d)
        return signal_router.resolve_row(_MSG, _cfg(voci), chat_id="42", parsers_dir=d)


# ── ① il codice distingue le due cause ────────────────────────────────────────────────

def test_la_frase_ambigua_ha_un_codice_suo():
    """FAIL-FIRST: l'ambiguità arrivava come `MARKET_MAPPING_MISSING`, lo stesso codice del
    caso opposto. Misurato prima della patch: `status == 'MARKET_MAPPING_MISSING'`."""
    res = _esito(_VOCI_AMBIGUE)
    assert not res.placeable, "l'ambiguità deve restare fail-closed"
    assert res.status == pipe.MARKET_MAPPING_AMBIGUOUS, (
        f"l'ambiguità è ancora appiattita su un codice generico: {res.status}"
    )


def test_il_motivo_del_codice_dice_di_TOGLIERE_non_di_aggiungere():
    """FAIL-FIRST: il testo elencava le due cause con un «o», quindi metà era sempre falsa.

    `explain()` riceve **solo il codice**, quindi qui si pretende la parte generica: il verso
    del rimedio. È l'informazione che distingue le due cause, e quella che, sbagliata, manda a
    lavorare nella direzione opposta.
    """
    motivo = pdiag.explain(pdiag.MARKET_MAPPING_AMBIGUOUS)
    assert "togli" in motivo.lower(), motivo
    assert "nessuna frase combacia" not in motivo, (
        f"il motivo cita ancora la causa OPPOSTA, quella che qui è falsa: {motivo!r}"
    )


def test_il_verdetto_nomina_le_coppie_in_conflitto():
    """Le coppie **specifiche** viaggiano nel `detail` e arrivano via `status_reason`, non via
    `explain()` — che per contratto vede solo il codice e non potrebbe nominarle.

    Sono la cosa che l'utente deve andare a correggere: senza, resta un'indagine.
    """
    diag = pdiag.diagnose(_parser(), _MSG, provider="TG",
                          market_mapping_profiles=[list(_VOCI_AMBIGUE)])
    motivo = pdiag.motivo_stato(diag)

    assert "Entrambe le squadre a segno" in motivo and "1º tempo - Totale goal 0,5" in motivo, (
        f"il verdetto non nomina le coppie in conflitto: {motivo!r}"
    )
    assert "Sì" in motivo and "Over 0,5 goal" in motivo, (
        "il verdetto nomina i mercati ma non le selezioni: due voci sullo STESSO mercato con "
        f"selezioni opposte (Over/Under) sarebbero indistinguibili — {motivo!r}"
    )


def test_il_caso_opposto_non_e_stato_travolto():
    """La metà che impedisce di «correggere» spostando il difetto: «nessuna frase combacia»
    deve conservare il suo codice e il suo motivo. Se sparissero, avremmo scambiato una
    diagnosi generica con una diagnosi sbagliata."""
    motivo_none = pdiag.explain(pipe.MARKET_MAPPING_MISSING)
    assert "nessuna frase combacia" in motivo_none, motivo_none
    assert pipe.MARKET_MAPPING_AMBIGUOUS != pipe.MARKET_MAPPING_MISSING


# ── ② il test che conta: l'ambiguo NON deve sbloccare le righe multi ───────────────────

def test_il_codice_ambiguo_blocca_la_base_come_il_fratello():
    """**Il test più importante del file.**

    `_BASE_BLOCKING` è la tupla che impedisce di generare le righe multi da una base rotta.
    Un codice nuovo che non finisse lì dentro farebbe generare le righe da un mercato che il
    resolver ha rifiutato di risolvere — una scommessa su un mercato non identificato,
    moltiplicata per N selezioni.

    Verifica il **comportamento**, non l'appartenenza alla tupla: un parser con MultiSelection
    e un mercato ambiguo non deve produrre **nessuna riga piazzabile**. Asserire solo
    `codice in _BASE_BLOCKING` proverebbe che ho scritto ciò che ho scritto; questo prova che
    l'effetto c'è. L'appartenenza alla tupla è comunque controllata a valle, come diagnosi del
    perché in caso di rosso.
    """
    parser_multi = cp.CustomParserDef(
        name="MktAmbMulti", mode="NAME_ONLY", market_mapping_profiles=["M"], team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
            cp.FieldRule(target="MarketType", fixed_value="FIRST_HALF_GOALS_15", required=True),
            cp.FieldRule(target="MarketName", fixed_value="1º tempo - Totale goal 1,5"),
            cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
            cp.FieldRule(target="BetType", fixed_value="BACK", required=True),
        ],
        multi_selection_enabled=True,
        multi_selections=[cp.MultiRowRule(selection_name="Over 1,5 goal"),
                          cp.MultiRowRule(selection_name="Under 1,5 goal")])

    righe = pipe.build_validated_rows(parser_multi, _MSG,
                                      market_mapping_profiles=[list(_VOCI_AMBIGUE)])
    piazzabili = [r for r in righe if r.placeable]
    assert not piazzabili, (
        f"generate {len(piazzabili)} righe piazzabili da un mercato AMBIGUO: il resolver si è "
        f"rifiutato di indovinare il mercato e le righe multi lo hanno scavalcato — "
        f"{[r.row.get('SelectionName') for r in piazzabili]}"
    )

    # Diagnosi del perché, se il test sopra si rompe.
    assert pipe.MARKET_MAPPING_AMBIGUOUS in pipe._BASE_BLOCKING, (
        "l'ambiguità non blocca più la base: le righe multi verrebbero generate da un mercato "
        "che il resolver si è rifiutato di indovinare"
    )


def test_il_codice_ambiguo_non_e_colmabile_da_una_riga_multi():
    """`_MULTI_RESOLVABLE` esiste per gli stati che una riga multi PUÒ colmare fornendo una
    colonna — ed è documentato per il caso «mercato assente, nessuna frase combacia».

    L'ambiguità non è di quella famiglia: due frasi in conflitto non si risolvono perché una
    riga multi fornisce `SelectionName`. Finiva lì dentro solo perché condivideva il codice
    col caso opposto.
    """
    assert pipe.MARKET_MAPPING_AMBIGUOUS not in pipe._MULTI_RESOLVABLE
    assert pipe.MARKET_MAPPING_MISSING in pipe._MULTI_RESOLVABLE, (
        "il caso «nessuna frase combacia» ha perso la sua ri-valutazione multi"
    )


# ── ③ la diagnostica marca le colonne giuste ──────────────────────────────────────────

def test_la_diagnostica_marca_mercato_e_selezione():
    """Il gemello `MARKET_MAPPING_MISSING` marca `MarketName` e `SelectionName`, le due colonne
    che la mappatura avrebbe dovuto impostare. L'ambiguo deve marcarle allo stesso modo: sono
    le stesse due colonne, e la tabella diagnostica sotto il verdetto le mostra."""
    res = _esito(_VOCI_AMBIGUE)
    diag = pdiag.diagnose(_parser(), _MSG, provider="TG",
                          market_mapping_profiles=[list(_VOCI_AMBIGUE)])
    assert diag.status == res.status, "diagnose e percorso live divergono sullo stato"

    marcate = {f.target: f.error for f in diag.fields}
    assert marcate.get("MarketName") == pdiag.MARKET_MAPPING_AMBIGUOUS, marcate
    assert marcate.get("SelectionName") == pdiag.MARKET_MAPPING_AMBIGUOUS, marcate


def test_il_motivo_dello_stato_raggiunge_il_verdetto():
    """`status_reason` è il campo che GUI del «🧪 Prova messaggio» e assistente leggono. L'issue
    dice che l'infrastruttura c'è già: questo test lo pretende invece di fidarsene."""
    diag = pdiag.diagnose(_parser(), _MSG, provider="TG",
                          market_mapping_profiles=[list(_VOCI_AMBIGUE)])
    motivo = pdiag.motivo_stato(diag)
    assert motivo, "il verdetto arriverebbe come sigla nuda"
    assert "Entrambe le squadre a segno" in motivo, motivo


# ── ④ la fonte unica dei contendenti ───────────────────────────────────────────────────

def test_i_contendenti_li_calcola_una_fonte_unica():
    """Regola 3. La tecnica per sapere **quali** mercati si contendono una frase — ri-sondare
    una voce alla volta e tenere chi risolve `ok` — esisteva già dentro
    `ambiguous_phrase_warnings`, dove è stata corretta quattro volte in review (confronto `==`
    sulla frase, delimitatori ignorati, dedup per `market_name`).

    Riscriverla per il runtime avrebbe creato la seconda copia destinata a divergere. Qui si
    pretende che la funzione pubblica esista e risponda sul messaggio reale.
    """
    from xtrader_bridge import market_mapping_store as mms

    contesi = mms.mercati_in_conflitto(_MSG, [list(_VOCI_AMBIGUE)])
    assert len(contesi) == 2, contesi
    nomi = {mn for _mt, mn, _sn in contesi}
    assert nomi == {"Entrambe le squadre a segno", "1º tempo - Totale goal 0,5"}


def test_una_frase_non_contesa_non_ha_contendenti():
    """La metà opposta: senza conflitto la fonte unica non deve inventare contendenti — un
    elenco spurio manderebbe a correggere una riga sana, che è il difetto trovato in review
    sulla #255."""
    from xtrader_bridge import market_mapping_store as mms

    una_sola = [_voce("", "Entrambe le squadre a segno", "Sì")]
    contesi = mms.mercati_in_conflitto(_MSG, [una_sola])
    assert len(contesi) == 1, contesi

    nessuna = mms.mercati_in_conflitto(_MSG, [[_voce("", "X", "Y", frase="non-c-e")]])
    assert nessuna == [], nessuna


@pytest.mark.parametrize("testo", ["", "   ", "nessun mercato qui"])
def test_la_fonte_unica_e_fail_safe(testo):
    """Non deve sollevare su testo vuoto o senza match: è chiamata sul percorso di
    diagnostica, e una diagnostica che esplode è peggio di una generica."""
    from xtrader_bridge import market_mapping_store as mms

    assert mms.mercati_in_conflitto(testo, [list(_VOCI_AMBIGUE)]) == []
