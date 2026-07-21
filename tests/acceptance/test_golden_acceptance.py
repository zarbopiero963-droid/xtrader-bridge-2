"""Suite di ACCETTAZIONE «golden»: messaggio reale → riga CSV ESATTA, tutto in CI.

Perché esiste (risposta a «perché il collaudo non si fa in CI?»): questa suite fa girare un
messaggio attraverso il **vero** pipeline del bridge (`custom_pipeline.build_validated_rows`,
la stessa trasformazione usata da `signal_router.resolve_row`: estrazione → validazione →
mappatura mercati/nomi → riga CSV) e verifica **byte per byte** la riga che uscirebbe. Copre
tutta la NOSTRA metà della catena senza installare né XTrader né Telegram. Resta fuori solo ciò
che due scatole nere fanno col nostro output (XTrader che legge il CSV, Telegram live) — quello
lo verifica il collaudo sul PC reale, una volta.

────────────────────────────────────────────────────────────────────────────────────────────
COME AGGIUNGERE UN TUO MESSAGGIO REALE (il valore vero di questa suite):
1. Esporta il tuo Parser Personalizzato reale e adatta `GOLDEN_PARSER` qui sotto (o creane
   altri) alle sue regole vere; adatta `GOLDEN_MARKET_MAPPINGS` alle tue voci mercato reali.
2. Aggiungi una voce in `CASES`:
     {"id": "descrizione", "message": "<incolla qui il messaggio reale del canale>",
      "expect": {"MarketType": "...", "SelectionName": "...", "Price": "...", ...}}   # riga attesa
   oppure, per un messaggio che NON deve piazzare nulla (recap/chiacchiere/linea non mappata):
     {"id": "...", "message": "...", "expect_rejected": True}
3. Lancia `pytest tests/acceptance/ -q`. Da quel momento qualsiasi modifica al codice che
   cambierebbe quella riga CSV viene BECCATA in CI: il collaudo è «bakerizzato».
────────────────────────────────────────────────────────────────────────────────────────────

NB: `GOLDEN_PARSER`/`GOLDEN_MARKET_MAPPINGS` qui sono un setup **rappresentativo** (stile P.Bet
+ mappatura mercati) finché non arrivano il parser e i messaggi reali del proprietario; i casi
sono comunque veri e passano sul codice attuale. Due casi blindano i P1 chiusi in #135
(mercato sbagliato su linea decimale non mappata; bet spurio su non-segnale).
"""

import pytest

from xtrader_bridge import custom_parser_engine as cpe
from xtrader_bridge import custom_pipeline
from xtrader_bridge import market_mapping_store

FR = cpe.FieldRule

# Parser rappresentativo (SOSTITUISCILImax col tuo reale): NAME_ONLY, EventName+Price estratti,
# mercato dalla mappatura a frase, BetType/Provider fissi.
GOLDEN_PARSER = cpe.CustomParserDef(
    name="P.Bet.", mode="NAME_ONLY",
    rules=[
        FR(target="Provider", fixed_value="PBet"),
        FR(target="EventName", start_after="P.Bet. ", end_before="\n"),
        FR(target="Price", start_after="Quota "),      # end_before vuoto → fino a fine riga
        FR(target="BetType", fixed_value="PUNTA"),
    ],
    market_mapping_profiles=["Canale"])

# Voci mercato reali del Catalogo XTrader (nome/selezione canonici); il resolver le valida.
GOLDEN_MARKET_MAPPINGS = {"Canale": [
    {"start_after": "Mercato: ", "end_before": "\n", "phrase": "over 2,5",
     "market_type": "", "market_name": "Over/Under 2,5 gol", "selection_name": "Over 2,5 goal"},
    {"start_after": "Mercato: ", "end_before": "\n", "phrase": "gol gol",
     "market_type": "", "market_name": "Entrambe le squadre a segno", "selection_name": "Sì"},
]}


# Ogni caso: message → riga attesa (`expect`, sottoinsieme di colonne CSV) OPPURE `expect_rejected`.
CASES = [
    {
        "id": "over_2_5_valido → riga CSV esatta",
        "message": "P.Bet. Inter v Milan\nMercato: over 2,5\nQuota 1,85",
        "expect": {
            "Provider": "PBet", "EventName": "Inter v Milan",
            "MarketType": "OVER_UNDER_25", "MarketName": "Over/Under 2,5 gol",
            "SelectionName": "Over 2,5 goal", "Handicap": "0",
            "Price": "1.85", "BetType": "PUNTA",
        },
    },
    {
        "id": "gol_gol_valido → BTTS Sì",
        "message": "P.Bet. Roma v Lazio\nMercato: gol gol\nQuota 1,72",
        "expect": {
            "EventName": "Roma v Lazio", "MarketName": "Entrambe le squadre a segno",
            "SelectionName": "Sì", "Price": "1.72", "BetType": "PUNTA",
        },
    },
    {
        # Blinda P1 #1 (#135): una linea decimale NON mappata (2,75) non deve risolvere al
        # mercato di una voce più corta → nessuna riga (mai il mercato sbagliato).
        "id": "linea_2_75_non_mappata → nessuna scommessa (P1 #1)",
        "message": "P.Bet. Inter v Milan\nMercato: over 2,75\nQuota 1,90",
        "expect_rejected": True,
    },
    {
        # Blinda P1 #2 (#135): un messaggio non-segnale (recap) non deve piazzare nulla.
        "id": "recap_non_segnale → nessuna scommessa (P1 #2)",
        "message": "Riepilogo di ieri: buona giornata!\nQuota media 1,90 sui nostri tips.",
        "expect_rejected": True,
    },
    {
        # Fail-closed: quota mancante → riga non piazzabile (niente bet senza prezzo).
        "id": "quota_mancante → fail-closed",
        "message": "P.Bet. Inter v Milan\nMercato: over 2,5",
        "expect_rejected": True,
    },
]


def _run(message):
    """Fa girare il messaggio nel vero pipeline e ritorna le righe PIAZZABILI (0 o più)."""
    profiles = market_mapping_store.entries_for_profiles(
        {"market_mappings": GOLDEN_MARKET_MAPPINGS}, GOLDEN_PARSER.market_mapping_profiles)
    results = custom_pipeline.build_validated_rows(
        GOLDEN_PARSER, message, mode=GOLDEN_PARSER.mode,
        market_mapping_profiles=profiles, provider="PBet", require_price=True)
    return [r.row for r in results if r.placeable]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_message_to_csv(case):
    """Ogni messaggio golden → esattamente la riga CSV attesa (o nessuna riga se rifiutato)."""
    rows = _run(case["message"])
    if case.get("expect_rejected"):
        assert rows == [], f"il messaggio NON doveva piazzare nulla, invece: {rows}"
        return
    assert len(rows) == 1, f"atteso 1 riga piazzabile, ottenute {len(rows)}"
    row = rows[0]
    # header CSV integro (ordine colonne = contratto XTrader)
    assert list(row.keys()) == cpe.CSV_HEADER
    for col, atteso in case["expect"].items():
        assert row[col] == atteso, f"colonna {col}: atteso {atteso!r}, ottenuto {row[col]!r}"


def test_setup_golden_e_coerente():
    """Meta: il parser e le mappature golden sono ben formati (almeno un caso valido produce
    una riga) — così la suite non passa 'a vuoto' per un setup rotto."""
    assert any(not c.get("expect_rejected") for c in CASES)
    validi = [c for c in CASES if not c.get("expect_rejected")]
    assert _run(validi[0]["message"]), "il primo caso valido deve produrre una riga piazzabile"
