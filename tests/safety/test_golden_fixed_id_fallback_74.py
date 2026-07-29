"""GOLDEN TEST del fallback a ID FISSI quando la mappatura mercati non trova nulla (#74).

Perche' questo file esiste
--------------------------
L'audit #137 chiedeva di fissare questo ramo perche' oggi il suo comportamento **non e'
scritto da nessuna parte**: emerge dall'incastro di due decisioni in due file diversi
(`custom_parser_engine.matches_message` e `custom_pipeline.build_validated_row`), e nessun
test lo nominava. Un comportamento che tocca soldi e che nessuno ha dichiarato e' un
comportamento che il prossimo refactor puo' cambiare senza che nulla diventi rosso.

Il contratto fissato qui (decisione del proprietario, opzione B — si tiene la #74)
----------------------------------------------------------------------------------
Con un parser che ha `MarketId`/`SelectionId` **fissi** PIU' un profilo di mappatura
mercati, e un messaggio in cui **nessuna frase mercato combacia**:

    gli ID fissi RESTANO e la riga e' piazzabile,
    a condizione che un'estrazione OBBLIGATORIA fornisca contenuto reale.

**Il bordo tagliente, dichiarato.** Significa che se il mercato scritto nel messaggio non
e' a dizionario (o e' scritto in modo diverso — `over 2,75` invece di `over 2,5`), si
scommette sul mercato **FISSO** e quello nominato nel messaggio viene ignorato. E' corretto
per il caso d'uso «questo canale scommette sempre lo stesso mercato, il messaggio mi dice
solo quale evento»; e' sbagliato per «questo canale manda mercati diversi». La config non
distingue le due intenzioni, e la scelta del proprietario e' stata di tenere il
comportamento attuale invece di fail-closare (che perderebbe segnali in silenzio).

Cosa NON e' cambiato
--------------------
La difesa vera della #74 resta intatta ed e' verificata qui sotto: un'estrazione
**OPZIONALE** non basta a far passare un non-segnale. Senza quel contrasto questo golden
test rischierebbe di legittimare il bet spurio che la #74 aveva chiuso.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_parser_engine as cpe
from xtrader_bridge import dizionario
from xtrader_bridge import signal_router
from xtrader_bridge import validator

FR = cp.FieldRule

MARKET_ID_FISSO = "1.234567"
SELECTION_ID_FISSO = "55555"


def _sel_over25():
    return dizionario.selections_for_market("Over/Under 2,5 gol", None)[0]["SelectionName"]


def _defn(*, event_required):
    """Parser reale: coppia ID FISSA + profilo mercati + estrazione dell'evento.

    `event_required` e' il perno di tutto il contratto: OBBLIGATORIA = contenuto reale di
    segnale; OPZIONALE = non basta, ed e' cio' che blocca il non-segnale (#74 P1 #2)."""
    return cpe.CustomParserDef(
        name="FissoBoth", mode="BOTH",
        rules=[FR(target="MarketId", fixed_value=MARKET_ID_FISSO),
               FR(target="SelectionId", fixed_value=SELECTION_ID_FISSO),
               FR(target="Price", fixed_value="1.85"),
               FR(target="BetType", fixed_value="PUNTA"),
               FR(target="EventName", start_after="Match:", required=event_required)],
        market_mapping_profiles=["Canale"])


def _cfg():
    return {"recognition_mode": "BOTH", "market_mappings": {"Canale": [
        {"start_after": "Mercato:", "end_before": "\n", "phrase": "over 2,5",
         "market_type": "", "market_name": "Over/Under 2,5 gol",
         "selection_name": _sel_over25()}]}}


def _risolvi(defn, testo):
    return signal_router._resolve_one(defn, testo, cfg=_cfg(), chat="123",
                                      provider="Canale", id_resolver=None)


# ── IL GOLDEN ────────────────────────────────────────────────────────────────

def test_GOLDEN_mercato_non_mappato_la_riga_porta_gli_ID_FISSI():
    """Il ramo che l'audit #137 chiedeva di fissare, esercitato end-to-end.

    Messaggio con un mercato REALE (`over 2,75`) che NON e' a dizionario. La mappatura non
    trova nulla, gli ID fissi restano, e la riga e' piazzabile perche' `EventName` e'
    obbligatorio e ha estratto contenuto.

    Ogni assert qui e' una promessa: se un domani si decidesse il fail-closed, questo test
    diventa rosso e obbliga a dichiarare il cambio invece di scoprirlo dal CSV."""
    res = _risolvi(_defn(event_required=True), "Match: Inter v Milan\nMercato: over 2,75\n")

    assert res["fired"] is True, res
    assert res["status"] == validator.VALID, res["status"]
    assert len(res["rows"]) == 1, res["rows"]

    riga = res["rows"][0]
    assert riga["MarketId"] == MARKET_ID_FISSO
    assert riga["SelectionId"] == SELECTION_ID_FISSO
    assert riga["EventName"] == "Inter v Milan"
    # Il bordo tagliente, messo NERO SU BIANCO: il mercato del messaggio ("over 2,75") non
    # finisce da nessuna parte. Si scommette sulla coppia di ID FISSA.
    assert riga["MarketName"] == "", (
        "il mercato a nome deve restare VUOTO: la riga e' identificata dagli ID fissi, "
        "non dal mercato nominato nel messaggio")


def test_GOLDEN_quando_il_mercato_COMBACIA_vince_il_dizionario_e_gli_ID_si_azzerano():
    """La controprova che rende non vacuo il golden sopra: cambiando SOLO il mercato del
    messaggio (`2,75` → `2,5`, che e' a dizionario) l'esito e' l'opposto — il dizionario
    sovrascrive a nome e la coppia ID viene AZZERATA, cosi' la riga non porta identificatori
    incoerenti col mercato scelto.

    Senza questo caso, il golden potrebbe passare anche se gli ID fissi sopravvivessero
    SEMPRE, cioe' anche quando il dizionario dovrebbe vincere."""
    res = _risolvi(_defn(event_required=True), "Match: Inter v Milan\nMercato: over 2,5\n")

    assert res["fired"] is True and len(res["rows"]) == 1, res
    riga = res["rows"][0]
    assert riga["MarketId"] == "", riga["MarketId"]
    assert riga["SelectionId"] == "", riga["SelectionId"]
    assert riga["MarketName"] == "Over/Under 2,5 gol", riga["MarketName"]


def test_GOLDEN_senza_estrazione_OBBLIGATORIA_il_non_segnale_resta_bloccato():
    """La difesa della #74 (P1 #2) che questo golden NON deve indebolire.

    Stesso parser, ma `EventName` OPZIONALE: un messaggio non-segnale che contiene per caso
    il delimitatore `Match:` non deve produrre nulla. E' la differenza fra «il fallback a ID
    fissi vale per un segnale vero» e «vale per qualsiasi testo» — la seconda sarebbe una
    scommessa spuria con soldi veri."""
    non_segnale = "Riepilogo di ieri\nMatch: Inter v Milan finita 2-0, che partita!"
    res = _risolvi(_defn(event_required=False), non_segnale)

    assert res["fired"] is False, res
    assert res["rows"] == []
    assert res["status"] == signal_router.NO_CONTENT_MATCH, res["status"]


def test_GOLDEN_il_gate_del_motore_e_coerente_con_la_pipeline():
    """I due pezzi del contratto vivono in file diversi (`custom_parser_engine` decide se il
    messaggio e' un segnale, `custom_pipeline` decide se la riga ha un mercato) e possono
    divergere. Qui si fissa che il gate del motore dica la stessa cosa dell'esito end-to-end
    sopra, sui due valori di `market_matched` che contano."""
    obbligatorio = _defn(event_required=True)
    msg = "Match: Inter v Milan\nMercato: over 2,75\n"
    # nessun mercato combacia → gli ID fissi restano e l'estrazione obbligatoria basta
    assert cpe.matches_message(obbligatorio, msg, "BOTH", market_matched=False) is True

    opzionale = _defn(event_required=False)
    # stessa situazione ma con estrazione OPZIONALE → bloccato
    assert cpe.matches_message(opzionale, msg, "BOTH", market_matched=False) is False
