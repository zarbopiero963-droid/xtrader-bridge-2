"""P1 percorso soldi — caccia adversariale pre-live (2 bug confermati con repro eseguita).

Due bug che con soldi VERI producevano una scommessa sbagliata/spuria. Test FAIL-FIRST:
falliscono sul codice pre-fix (riproducono il bug), passano dopo la correzione.

- **P1 #1 — mercato SBAGLIATO** (`market_mapping_store._phrase_in_text`): il confine di token
  escludeva le cifre ma NON il separatore decimale `,`/`.`. Una frase mappata che finisce con un
  intero combaciava dentro una linea decimale diversa (`over 2` dentro `over 2,75`) → `resolve_market`
  ritornava `ok` col mercato della voce più corta invece del `none` fail-closed → riga CSV
  piazzabile sul mercato SBAGLIATO.
- **P1 #2 — scommessa SPURIA** (`custom_parser_engine.matches_message` + `signal_router`): con un
  profilo mercati selezionato, il gate anti-non-segnale (#74/A10) azzerava sempre gli `MarketId`/
  `SelectionId` fissi, anche quando NESSUNA frase mercato combaciava col messaggio. Un messaggio
  non-segnale che conteneva solo il delimitatore di un'estrazione OPZIONALE passava il gate e
  scriveva il bet FISSO. Il fix azzera gli ID solo se una frase mercato combacia DAVVERO.
"""

from xtrader_bridge import custom_parser_engine as cpe
from xtrader_bridge import dizionario
from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import signal_router

FR = cpe.FieldRule


# ══════════════════════════ P1 #1 — resolver mercati ══════════════════════════

def _market_profile(phrase, market_name):
    sel = dizionario.selections_for_market(market_name, None)[0]["SelectionName"]
    return [[{"start_after": "Mercato:", "end_before": "\n", "phrase": phrase,
             "market_type": "", "market_name": market_name, "selection_name": sel}]]


def test_frase_intera_non_matcha_linea_decimale_diversa():
    """FAIL-FIRST: `over 2` (mappata a Over/Under 2,5) NON deve combaciare in una linea `over 2,75`
    MAI mappata → `none` (fail-closed), mai il mercato 2,5 (scommessa sbagliata)."""
    prof = _market_profile("over 2", "Over/Under 2,5 gol")
    assert mms.resolve_market("Mercato: over 2,75 gol\n", prof).status == "none"
    assert mms.resolve_market("Mercato: over 2.75 gol\n", prof).status == "none"   # anche punto EN


def test_phrase_in_text_esclude_separatore_decimale():
    """Il confine di token esclude ora anche `,`/`.`: una frase che finisce con un intero non
    combacia dentro un decimale diverso, in nessuna delle due direzioni."""
    n = mms._normalize_text
    assert mms._phrase_in_text("over 2", n("over 2,75")) is False
    assert mms._phrase_in_text("over 2", n("over 2.5")) is False
    assert mms._phrase_in_text("5 ht", n("1,5 ht")) is False      # collisione leading
    # regressione: i match legittimi restano (spazio/!/fine come confine, cifra dopo già esclusa)
    assert mms._phrase_in_text("over 2", n("over 2")) is True
    assert mms._phrase_in_text("over 0,5", n("over 0,5 goal")) is True
    assert mms._phrase_in_text("over 0,5", n("vai di over 0,5!")) is True
    assert mms._phrase_in_text("over 0,5", n("over 0,55")) is False   # cifra dopo (già ok)


def test_separatore_come_punteggiatura_finale_resta_confine():
    """Review GPT-5.5: il `,`/`.` come PUNTEGGIATURA (non decimale, cioè non seguìto da cifra) NON
    deve rompere il match — un provider che scrive `over 2.` o `gol gol.` deve ancora combaciare.
    Solo il separatore DECIMALE (seguìto/preceduto da cifra) è un non-confine."""
    n = mms._normalize_text
    assert mms._phrase_in_text("over 2", n("over 2.")) is True        # punto finale = confine
    assert mms._phrase_in_text("over 2", n("over 2,")) is True        # virgola finale = confine
    assert mms._phrase_in_text("gol gol", n("gol gol.")) is True      # frase + punto
    assert mms._phrase_in_text("over 2", n("over 2, quota 1,85")) is True  # virgola+spazio
    # ma il decimale vero resta escluso
    assert mms._phrase_in_text("over 2", n("over 2,75")) is False


def test_match_legittimo_preservato():
    """Regressione: una frase che identifica il proprio mercato continua a risolvere `ok`."""
    prof = _market_profile("over/under 2,5", "Over/Under 2,5 gol")
    assert mms.resolve_market("Mercato: over/under 2,5 gol\n", prof).status == "ok"


# ══════════════════════════ P1 #2 — gate anti-non-segnale ══════════════════════════

def _fixed_both_defn():
    return cpe.CustomParserDef(
        name="FissoBoth", mode="BOTH",
        rules=[FR(target="MarketId", fixed_value="1.234567"),
               FR(target="SelectionId", fixed_value="55555"),
               FR(target="Price", fixed_value="1.85"),
               FR(target="BetType", fixed_value="PUNTA"),
               FR(target="EventName", start_after="Match:")],  # estrazione OPZIONALE
        market_mapping_profiles=["Canale"])


def test_matches_message_blocca_non_segnale_senza_mercato():
    """FAIL-FIRST: con profilo mercati ma NESSUN mercato nel messaggio (`market_matched=False`), una
    estrazione OPZIONALE (EventName dopo `Match:`) NON deve far passare un messaggio non-segnale."""
    defn = _fixed_both_defn()
    msg = "Riepilogo di ieri\nMatch: Inter v Milan finita 2-0, che partita!"
    assert cpe.matches_message(defn, msg, "BOTH", market_matched=False) is False


def test_matches_message_passa_se_mercato_combacia_davvero():
    """Regressione: quando una frase mercato combacia (`market_matched=True`), il path supportato
    «ID fissi + mappatura mercati + EventName» resta valido."""
    defn = _fixed_both_defn()
    msg = "Segnale\nMatch: Inter v Milan\nMercato: over 2,5\n"
    assert cpe.matches_message(defn, msg, "BOTH", market_matched=True) is True


def test_end_to_end_non_segnale_non_produce_riga_piazzabile():
    """FAIL-FIRST end-to-end via `signal_router`: un parser reale con ID fissi + profilo mercati +
    EventName opzionale, su un messaggio non-segnale (contiene `Match:` ma nessun mercato mappato),
    NON deve produrre una riga piazzabile (nessun bet spurio con soldi veri)."""
    defn = _fixed_both_defn()
    sel = dizionario.selections_for_market("Over/Under 2,5 gol", None)[0]["SelectionName"]
    cfg = {
        "recognition_mode": "BOTH",
        "market_mappings": {"Canale": [
            {"start_after": "Mercato:", "end_before": "\n", "phrase": "over 2,5",
             "market_type": "", "market_name": "Over/Under 2,5 gol", "selection_name": sel}]},
    }
    non_segnale = "Riepilogo di ieri\nMatch: Inter v Milan finita 2-0, che partita!"
    res = signal_router._resolve_one(defn, non_segnale, cfg=cfg, chat="123",
                                     provider="Canale", id_resolver=None)
    assert res["fired"] is False
    assert res["rows"] == []
    assert res["status"] == signal_router.NO_CONTENT_MATCH

    # controprova: un VERO segnale con la frase mercato → scatta e produce la riga
    segnale = "Match: Inter v Milan\nMercato: over 2,5\n"
    res2 = signal_router._resolve_one(defn, segnale, cfg=cfg, chat="123",
                                      provider="Canale", id_resolver=None)
    assert res2["fired"] is True and res2["rows"], "un vero segnale mappato deve ancora scattare"


def test_mercato_ambiguo_e_fail_closed_end_to_end():
    """Review Fable #135: sul ramo `ambiguous` (`market_matched=False` col mio gate) la pipeline
    fail-closa comunque (`MARKET_MAPPING_MISSING`, mai il bet fisso). Anche con un EventName
    OBBLIGATORIO (che farebbe passare il gate), due frasi che indicano mercati DIVERSI nello stesso
    messaggio NON devono produrre alcuna riga piazzabile — mai tirare a indovinare il mercato."""
    from xtrader_bridge import dizionario as dz
    sel25 = dz.selections_for_market("Over/Under 2,5 gol", None)[0]["SelectionName"]
    sel15 = dz.selections_for_market("Over/Under 1,5 gol", None)[0]["SelectionName"]
    defn = cpe.CustomParserDef(
        name="FissoAmb", mode="BOTH",
        rules=[FR(target="MarketId", fixed_value="1.234567"),
               FR(target="SelectionId", fixed_value="55555"),
               FR(target="Price", fixed_value="1.85"),
               FR(target="BetType", fixed_value="PUNTA"),
               FR(target="EventName", start_after="Match:", required=True)],  # OBBLIGATORIO
        market_mapping_profiles=["Canale"])
    cfg = {"recognition_mode": "BOTH", "market_mappings": {"Canale": [
        {"start_after": "Mercato:", "end_before": "\n", "phrase": "gol",
         "market_type": "", "market_name": "Over/Under 2,5 gol", "selection_name": sel25},
        {"start_after": "Mercato:", "end_before": "\n", "phrase": "over",
         "market_type": "", "market_name": "Over/Under 1,5 gol", "selection_name": sel15}]}}
    ambiguo = "Match: Inter v Milan\nMercato: over gol\n"   # contiene sia 'over' sia 'gol'
    res = signal_router._resolve_one(defn, ambiguo, cfg=cfg, chat="123",
                                     provider="Canale", id_resolver=None)
    assert res["fired"] is False and res["rows"] == [], \
        "un mercato AMBIGUO non deve mai produrre una riga piazzabile (mai il bet fisso)"
