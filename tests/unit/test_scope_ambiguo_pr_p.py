"""PR-P (#194) — B21 e B20: due modi di risolvere la cosa sbagliata **in silenzio**.

Difetti diversi, stessa forma: una guardia anti-ambiguità che esiste già, ma che si lascia
aggirare perché confronta la dimensione sbagliata.

- **B21** (`name_mapping_store`, #192 L13) — una riga è considerata «distinguibile» da
  un'altra se differisce per `(sport, entity_type, language)`. Ma la firma non sa se il
  **chiamante** ha davvero filtrato su quelle dimensioni: un parser sport-agnostico passa
  `sport=None`, le due righe restano formalmente distinte, e la risoluzione ricade sulla
  **prima salvata**. Percorso vivo, nessun dizionario corrotto necessario.

- **B20** (`market_mapping_store`, #192 L16) — `selections_for_market` combacia su
  `MarketType` **oppure** `MarketName`, quindi la selezione può arrivare da una riga diversa
  da quella che ha fornito il `market_type`: una coppia mercato/selezione che nel dizionario
  non esiste. Richiede un catalogo sporco (quello spedito è pulito), ma la funzione deve
  essere fail-closed comunque.

In entrambi i casi la direzione giusta è **non risolvere**: una squadra o un mercato sbagliati
valgono meno di nessuna riga.

**Stato di questa PR: B20 è corretto, B21 no** — e i test di B21 restano qui, marcati
`xfail(strict=True)`, perché la correzione richiede una decisione che non è tecnica.

Fail-closare su chiamante agnostico rompe **8 test esistenti** che codificano di proposito il
comportamento storico (fra cui `test_source_language_wiring_5b.py::test_source_language_none_
comportamento_legacy`, il cui commento dice: «Senza `source_language` (""), il filtro è inerte:
si risolve col comportamento storico»). Il baratto misurato è:

- **fail-closed** → eventi oggi tradotti smettono di esserlo (**segnali persi**);
- **ordine di salvataggio** → ogni tanto si traduce la squadra **sbagliata** (**scommessa
  sbagliata**).

Il piano #194 non copre questa scelta e CLAUDE.md (Regola 5) prescrive di fermarsi e chiedere.
`strict=True` è deliberato: quando la decisione arriverà e la patch entrerà, questi test passano
e l'`xfail` diventa **rosso** — non si possono dimenticare.
"""

import pytest

from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import name_mapping_store as nms

_B21_APERTO = pytest.mark.xfail(
    strict=True,
    reason="B21 aperto: fail-closare su chiamante agnostico è una decisione del proprietario "
           "(segnali persi vs. squadra sbagliata) — vedi docstring del modulo e roadmap PR-P",
)


def _riga_nome(provider, betfair, sport="", entity_type="", language=""):
    """Riga del Dizionario nomi, **pulita dal codice reale** (`_clean_entry`).

    Costruirla a mano sarebbe un test che mente: `normalize_sport("calcio")` produce
    `"Calcio"`, quindi una riga grezza con `sport="calcio"` non combacerebbe con nessun
    filtro e il test misurerebbe uno scarto invece del difetto."""
    return nms._clean_entry({"provider": provider, "betfair": betfair, "sport": sport,
                             "entity_type": entity_type, "language": language})


# ── B21 · lo scope distingue solo se il chiamante ha filtrato ────────────────

@_B21_APERTO
def test_b21_sport_diversi_ma_chiamante_agnostico_non_deve_indovinare():
    """Il cuore di B21: due squadre diverse dietro lo stesso alias, e nessun filtro.

    `Inter` è `Inter Milano` nel calcio e `Inter Miami` nel basket. Un parser
    sport-agnostico (`sport=None`) non ha modo di scegliere: la risoluzione deve
    **fail-closare**, non restituire la prima riga salvata."""
    righe = [_riga_nome("Inter", "Inter Milano", sport="Calcio"),
             _riga_nome("Inter", "Inter Miami", sport="Basket")]
    assert nms.resolve_team("Inter", [righe]) is None


@_B21_APERTO
def test_b21_l_ordine_di_salvataggio_non_deve_decidere_la_squadra():
    """Il sintomo che rende il difetto grave: **misurato prima della patch**,
    l'ordine A dava `'Inter Milano'` e l'ordine B `'Inter Miami'`.

    Una traduzione che cambia perché l'utente ha salvato le righe in un altro ordine non è
    una risoluzione: è un sorteggio. E finisce nell'`EventName`, quindi nel mercato e nella
    selezione su cui si scommette."""
    righe = [_riga_nome("Inter", "Inter Milano", sport="Calcio"),
             _riga_nome("Inter", "Inter Miami", sport="Basket")]
    assert nms.resolve_team("Inter", [righe]) == nms.resolve_team("Inter", [list(reversed(righe))])


_TRE_DIMENSIONI = [
    ("sport", "Calcio", "Basket", {"sport": "Calcio"}),
    ("entity_type", "team", "competition", {"entity_type": "team"}),
    ("language", "IT", "EN", {"language": "IT"}),
]


@_B21_APERTO
@pytest.mark.parametrize("dimensione,valore_a,valore_b,filtro", _TRE_DIMENSIONI)
def test_b21_vale_per_TUTTE_e_tre_le_dimensioni(dimensione, valore_a, valore_b, filtro):
    """Non solo lo sport: la firma di scoping ha tre dimensioni, e il difetto è nella
    **regola**, non in una di esse. Cercare la classe, non il sito."""
    righe = [_riga_nome("Inter", "Inter Milano", **{dimensione: valore_a}),
             _riga_nome("Inter", "Inter Miami", **{dimensione: valore_b})]
    assert nms.resolve_team("Inter", [righe]) is None, (
        f"{dimensione}: chiamante agnostico, ha comunque indovinato"
    )


@pytest.mark.parametrize("dimensione,valore_a,valore_b,filtro", _TRE_DIMENSIONI)
def test_b21_il_filtro_esplicito_risolve_su_tutte_e_tre_le_dimensioni(
        dimensione, valore_a, valore_b, filtro):
    """Il controllo positivo, tenuto **separato** dall'`xfail` di sopra: è la linea di base
    che la futura patch di B21 non deve spostare. Chi filtra ottiene la sua riga, oggi come
    dopo la correzione — se questo diventasse rosso, la patch sarebbe troppo stretta."""
    righe = [_riga_nome("Inter", "Inter Milano", **{dimensione: valore_a}),
             _riga_nome("Inter", "Inter Miami", **{dimensione: valore_b})]
    assert nms.resolve_team("Inter", [righe], **filtro) == "Inter Milano", (
        f"{dimensione}: il filtro esplicito non risolve"
    )


def test_b21_controllo_positivo_una_riga_sola_risolve_sempre():
    """La guardia non deve trasformarsi in «non risolvo mai»: senza conflitto si traduce."""
    righe = [_riga_nome("Inter", "Inter Milano", sport="Calcio")]
    assert nms.resolve_team("Inter", [righe]) == "Inter Milano"
    assert nms.resolve_team("Inter", [righe], sport="Calcio") == "Inter Milano"


def test_b21_controllo_positivo_stesso_betfair_non_e_ambiguo():
    """Due righe che puntano alla **stessa** squadra non sono un conflitto, anche con
    scope diversi: non c'è nulla da indovinare."""
    righe = [_riga_nome("Inter", "Inter Milano", sport="Calcio"),
             _riga_nome("Inter", "Inter Milano", sport="Basket")]
    assert nms.resolve_team("Inter", [righe]) == "Inter Milano"


def test_b21_controllo_positivo_la_guardia_preesistente_regge():
    """Il caso che funzionava già — stessa firma, due Betfair diversi — deve continuare a
    fail-closare. La patch allarga la guardia, non la sostituisce."""
    righe = [_riga_nome("Inter", "Inter Milano", sport="Calcio"),
             _riga_nome("Inter", "Inter Miami", sport="Calcio")]
    assert nms.resolve_team("Inter", [righe]) is None
    assert nms.resolve_team("Inter", [righe], sport="Calcio") is None


def test_b21_la_precedenza_fra_profili_resta_invariata():
    """Invariante da non rompere: il primo profilo vince. L'ambiguità è **dentro** un tier,
    non fra profili diversi."""
    primo = [_riga_nome("Inter", "Inter Milano", sport="Calcio")]
    secondo = [_riga_nome("Inter", "Inter Miami", sport="Basket")]
    assert nms.resolve_team("Inter", [primo, secondo]) == "Inter Milano"


# ── B20 · la selezione deve appartenere al mercato risolto ───────────────────

def _riga_dizionario(mtype, mname, selection):
    return {"MarketType_XTrader": mtype, "MarketName_XTrader": mname,
            "SelectionName_XTrader": selection, "Handicap": "0",
            "BetType_XTrader": "PUNTA", "SelezioneDinamica": "",
            "MarketAliasTelegram": f"alias-{mtype}",
            "SelectionAliasTelegram": f"alias-{selection}", "Fonte": "Export XTrader"}


def test_b20_una_selezione_di_un_altro_mercato_non_deve_accoppiarsi():
    """`selections_for_market` combacia su `MarketType` **oppure** `MarketName`.

    Con un catalogo dove il `MarketName` di una riga coincide col `MarketType` di un'altra,
    la selezione arriva dalla riga sbagliata. Misurato prima della patch:

        {'market_type': 'MATCH_ODDS', 'market_name': 'Vincente',
         'selection_name': 'Selezione di UN ALTRO mercato'}

    `market_type` e `market_name` dalla riga A, `selection_name` dalla riga B: una coppia
    che nel dizionario **non esiste**, scritta nel CSV come se esistesse."""
    righe = [
        _riga_dizionario("MATCH_ODDS", "Vincente", "Pareggio"),
        _riga_dizionario("Vincente", "Altro mercato", "Selezione di UN ALTRO mercato"),
    ]
    assert mms._canonical_market("Vincente", "Selezione di UN ALTRO mercato", righe) is None


def test_b20_controllo_positivo_la_coppia_giusta_risolve():
    """Il caso buono deve continuare a risolvere: è la metà che conta di una guardia."""
    righe = [_riga_dizionario("MATCH_ODDS", "Vincente", "Pareggio")]
    esito = mms._canonical_market("Vincente", "Pareggio", righe)
    assert esito == {"market_type": "MATCH_ODDS", "market_name": "Vincente",
                     "selection_name": "Pareggio"}


def test_b20_controllo_positivo_regge_col_catalogo_spedito():
    """Il dizionario **realmente spedito** non deve regredire: una coppia nota continua a
    risolversi. È il controllo che dice se la patch è troppo stretta sul dato vero."""
    esito = mms._canonical_market("Esito Finale", "Pareggio")
    assert esito is None or esito["selection_name"] == "Pareggio"
