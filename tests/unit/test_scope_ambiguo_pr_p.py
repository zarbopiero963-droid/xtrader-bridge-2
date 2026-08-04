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

**Entrambi corretti.** B21 richiedeva una decisione che non era tecnica, perché il baratto era:

- **fail-closed** → eventi oggi tradotti smettono di esserlo (**segnali persi**);
- **ordine di salvataggio** → ogni tanto si traduce la squadra **sbagliata** (**scommessa
  sbagliata**).

Il proprietario ha scelto **fail-closed**: un segnale perso è visibile e si corregge, una squadra
sbagliata finisce nell'`EventName` — quindi nel mercato e nella selezione su cui si scommette — e
non si vede. Otto test esistenti codificavano il comportamento a ordine di salvataggio e sono
stati **riorientati**, non cancellati: ognuno continua a difendere la garanzia per cui era stato
scritto, misurata sul comportamento nuovo.

La guardia non è diventata «non risolvo mai». Quando c'è una risposta giusta viene data: chi
filtra ottiene la sua riga, e chi non filtra ottiene la riga **agnostica** — quella che l'utente
ha scritto come «vale per tutto» — se esiste. Fail-closed scatta solo quando due destinazioni
diverse sono davvero indistinguibili per quel chiamante.
"""

import pytest

from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import name_mapping_store as nms


def _riga_nome(provider, betfair, sport="", entity_type="", language=""):
    """Riga del Dizionario nomi, **pulita dal codice reale** (`_clean_entry`).

    Costruirla a mano sarebbe un test che mente: `normalize_sport("calcio")` produce
    `"Calcio"`, quindi una riga grezza con `sport="calcio"` non combacerebbe con nessun
    filtro e il test misurerebbe uno scarto invece del difetto."""
    return nms._clean_entry({"provider": provider, "betfair": betfair, "sport": sport,
                             "entity_type": entity_type, "language": language})


# ── B21 · lo scope distingue solo se il chiamante ha filtrato ────────────────

def test_b21_sport_diversi_ma_chiamante_agnostico_non_deve_indovinare():
    """Il cuore di B21: due squadre diverse dietro lo stesso alias, e nessun filtro.

    `Inter` è `Inter Milano` nel calcio e `Inter Miami` nel basket. Un parser
    sport-agnostico (`sport=None`) non ha modo di scegliere: la risoluzione deve
    **fail-closare**, non restituire la prima riga salvata."""
    righe = [_riga_nome("Inter", "Inter Milano", sport="Calcio"),
             _riga_nome("Inter", "Inter Miami", sport="Basket")]
    assert nms.resolve_team("Inter", [righe]) is None


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
    """Il controllo positivo, tenuto **separato** da quello di sopra: è la linea di base che la
    patch di B21 non doveva spostare, e non ha spostato. Chi filtra ottiene la sua riga — se
    questo diventasse rosso, la guardia sarebbe troppo stretta e perderemmo segnali validi."""
    righe = [_riga_nome("Inter", "Inter Milano", **{dimensione: valore_a}),
             _riga_nome("Inter", "Inter Miami", **{dimensione: valore_b})]
    assert nms.resolve_team("Inter", [righe], **filtro) == "Inter Milano", (
        f"{dimensione}: il filtro esplicito non risolve"
    )


def test_b21_e_vivo_sul_PERCORSO_DI_PRODUZIONE_non_solo_in_astratto():
    """La forma **esatta** della chiamata reale, non una agnostica di comodo.

    `custom_pipeline` chiama `resolve_event_name` → `resolve_team` passando sempre
    `entity_type=PARTICIPANT_ENTITY_TYPES`, ma `sport=getattr(defn, "sport", "")` e
    `language=source_language` possono essere **vuoti** (parser senza sport, nessuna
    lingua-fonte). Misurato con quella firma:

        ordine A -> 'Inter Milano'
        ordine B -> 'Inter Miami'

    Le dimensioni scoperte sul percorso vero erano `sport` e `language`. È il test che ha reso
    la decisione del proprietario una scelta su un rischio **vivo**, non su un caso di
    laboratorio — e ora è la sua regressione."""
    righe = [_riga_nome("Inter", "Inter Milano", sport="Calcio", entity_type="team"),
             _riga_nome("Inter", "Inter Miami", sport="Basket", entity_type="team")]
    et = nms.PARTICIPANT_ENTITY_TYPES
    diretto = nms.resolve_team("Inter", [righe], sport="", entity_type=et, language="")
    invertito = nms.resolve_team("Inter", [list(reversed(righe))], sport="",
                                 entity_type=et, language="")
    assert diretto is None, "con sport vuoto ha ancora scelto una squadra"
    assert diretto == invertito, "la squadra dipende dall'ordine di salvataggio"
    # E chi dichiara lo sport continua a essere servito, sulla stessa firma di produzione.
    assert nms.resolve_team("Inter", [righe], sport="Calcio", entity_type=et,
                            language="") == "Inter Milano"


def test_b21_entity_type_e_SEMPRE_filtrato_dal_chiamante_di_produzione():
    """Il rovescio, e non è un dettaglio: la dimensione `entity_type` **non** è fra quelle
    scoperte, perché `custom_pipeline` passa sempre `PARTICIPANT_ENTITY_TYPES`.

    Due righe distinte solo per `entity_type` si risolvono correttamente e in modo
    deterministico: la riga `competition` viene esclusa dal filtro, non «indovinata». Verde
    prima e dopo la patch di B21 — serve a non far sembrare il difetto più largo di quello che
    era."""
    righe = [_riga_nome("Inter", "Inter Milano", entity_type="team"),
             _riga_nome("Inter", "Inter Miami", entity_type="competition")]
    et = nms.PARTICIPANT_ENTITY_TYPES
    assert nms.resolve_team("Inter", [righe], sport="", entity_type=et, language="") == "Inter Milano"
    assert nms.resolve_team("Inter", [list(reversed(righe))], sport="",
                            entity_type=et, language="") == "Inter Milano"


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
    risolversi. È il controllo che dice se la patch è troppo stretta sul dato vero.

    La prima stesura diceva `esito is None or esito[...] == "Pareggio"` — un test che non
    poteva fallire, perché il ramo `None` è proprio la regressione da intercettare (rilievo
    CodeRabbit sulla #253, corretto). La coppia esiste nel catalogo spedito, quindi si
    pretende la tupla intera."""
    assert mms._canonical_market("Esito Finale", "Pareggio") == {
        "market_type": "MATCH_ODDS", "market_name": "Esito Finale",
        "selection_name": "Pareggio"}


def test_b20_una_riga_senza_MarketName_appartiene_a_un_ALTRO_mercato():
    """Rilievo di Fable 5 e GPT-5.5 sulla #253: e se una riga combaciata per `MarketType`
    avesse `MarketName` vuoto — il nuovo `continue` la scarterebbe per sbaglio?

    No, e il motivo è strutturale. `matches` pretende
    `normalize(MarketName) == nmn` con `nmn` **non vuoto** (guardia a inizio funzione),
    quindi una riga senza `MarketName` non può mai essere quella che fornisce il mercato
    canonico. Se le sue selezioni arrivano nel ciclo è **solo** perché il suo `MarketType`
    coincide col nome di un mercato **diverso** — cioè esattamente B20. Scartarla è la
    correzione, non un danno collaterale."""
    righe = [
        _riga_dizionario("MATCH_ODDS", "Vincente", "Pareggio"),
        _riga_dizionario("Vincente", "", "Selezione senza MarketName"),
    ]
    assert mms._canonical_market("Vincente", "Selezione senza MarketName", righe) is None
    # E la riga sana dello stesso catalogo continua a risolversi: la guardia non è un veto.
    assert mms._canonical_market("Vincente", "Pareggio", righe) == {
        "market_type": "MATCH_ODDS", "market_name": "Vincente", "selection_name": "Pareggio"}


def test_b20_il_catalogo_spedito_non_perde_NEMMENO_UNA_selezione():
    """La misura che risponde davvero al rilievo: quante selezioni il nuovo `continue`
    scarta sul catalogo **realmente spedito**?

    Zero. Il controllo gira sull'intero catalogo invece che su un mercato scelto a mano,
    così resta valido anche quando il catalogo verrà esteso: se un domani una riga arrivasse
    con `MarketName` vuoto o incoerente, questo test diventerebbe rosso **prima** che l'utente
    scopra un `MARKET_MAPPING_MISSING` inspiegabile."""
    from xtrader_bridge import dizionario

    assert [r for r in dizionario._rows(None)], "catalogo spedito vuoto: il test non misura nulla"
    scartate = []
    for m in dizionario.market_catalog(None):
        if m["dynamic"]:
            continue
        ncanon = dizionario.normalize(m["MarketName"])
        for s in dizionario.selections_for_market(m["MarketName"], None):
            if s.get("dynamic") or not s.get("SelectionName"):
                continue
            if dizionario.normalize(s.get("MarketName", "")) != ncanon:
                scartate.append((m["MarketName"], s.get("MarketName"), s["SelectionName"]))
    assert scartate == [], (
        f"il guard B20 scarta {len(scartate)} selezioni del catalogo spedito: {scartate[:5]}"
    )


# ── B21-bis · l'avviso deve valere per OGNI chiamante, non solo per l'agnostico ──

def _cfg_nomi(righe):
    return {"name_mappings": {"P": list(righe)}}


def test_b21bis_conflitto_dentro_uno_sport_con_ripiego_agnostico_va_AVVISATO():
    """Bloccante di Fable 5 sulla #253, misurato e confermato.

    Due righe in conflitto **dentro** `Calcio`, più una riga agnostica di ripiego. Il chiamante
    agnostico se la cava (vince l'agnostica), quindi la prima stesura dell'avviso — che sondava
    **solo** il chiamante agnostico — taceva. Ma un parser che dichiara `sport=Calcio` fail-closa
    a runtime, e allo START non vedeva **nessun ⚠️**: segnali persi e non diagnosticabili.

    Misurato prima della correzione:

        chiamante agnostico      -> 'Inter generico'
        chiamante sport=Calcio   -> None          (segnale perso)
        AVVISI                   -> NESSUNO       (l'utente non sa perché)
    """
    cfg = _cfg_nomi([
        {"betfair": "Inter Milano", "provider": "Inter", "sport": "Calcio"},
        {"betfair": "Inter Miami", "provider": "Inter", "sport": "Calcio"},
        {"betfair": "Inter generico", "provider": "Inter"},
    ])
    profs = nms.entries_for_profiles(cfg, ["P"])
    assert nms.resolve_team("Inter", profs) == "Inter generico"        # l'agnostico se la cava
    assert nms.resolve_team("Inter", profs, sport="Calcio") is None    # chi filtra NO
    assert nms.ambiguous_alias_warnings(cfg), (
        "un chiamante reale perde ogni segnale e allo START non c'è alcun avviso"
    )


def test_b21bis_avviso_e_runtime_coerenti_su_OGNI_scope_del_dizionario():
    """La generalizzazione del caso di sopra: l'equivalenza «avviso ⇔ fail-closed» non vale
    solo per il chiamante agnostico, ma per **ogni** scope che il dizionario stesso contiene.

    Se per un qualsiasi (sport, tipo, lingua) presente nelle righe il runtime fail-closa, allora
    l'avviso deve esserci; e se nessuno fail-closa, non deve esserci. È la stessa invariante di
    `test_avviso_e_runtime_dicono_la_STESSA_cosa`, estesa ai chiamanti che filtrano."""
    casi = [
        # conflitto dentro uno sport, con e senza ripiego agnostico
        ([{"betfair": "A", "provider": "X", "sport": "Calcio"},
          {"betfair": "B", "provider": "X", "sport": "Calcio"},
          {"betfair": "AGN", "provider": "X"}], True),
        ([{"betfair": "A", "provider": "X", "sport": "Calcio"},
          {"betfair": "B", "provider": "X", "sport": "Calcio"}], True),
        # conflitto dentro una lingua, con ripiego agnostico
        ([{"betfair": "A", "provider": "X", "language": "IT"},
          {"betfair": "B", "provider": "X", "language": "IT"},
          {"betfair": "AGN", "provider": "X"}], True),
        # scope diversi: ambiguo per l'agnostico, risolvibile per chi filtra → avviso
        ([{"betfair": "A", "provider": "X", "sport": "Calcio"},
          {"betfair": "B", "provider": "X", "sport": "Tennis"}], True),
        # nessun conflitto per nessuno
        ([{"betfair": "A", "provider": "X", "sport": "Calcio"},
          {"betfair": "A", "provider": "X", "sport": "Tennis"}], False),
        ([{"betfair": "A", "provider": "X"}], False),
        ([{"betfair": "A", "provider": "X", "sport": "Calcio"},
          {"betfair": "AGN", "provider": "X"}], False),
    ]
    for righe, atteso in casi:
        cfg = _cfg_nomi(righe)
        profs = nms.entries_for_profiles(cfg, ["P"])
        scope = {(e.get("sport", ""), e.get("entity_type", ""), e.get("language", ""))
                 for e in nms.entries_for_profiles(cfg, ["P"])[0]} | {("", "", "")}
        perso = any(nms.resolve_team("X", profs, sport=s or None,
                                     entity_type=t or None, language=l or None) is None
                    for s, t, l in scope)
        avvisato = bool(nms.ambiguous_alias_warnings(cfg))
        assert avvisato == atteso, f"avviso sbagliato per {righe}"
        assert perso == atteso, f"runtime sbagliato per {righe}"
