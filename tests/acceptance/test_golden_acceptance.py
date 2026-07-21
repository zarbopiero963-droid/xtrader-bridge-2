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

Due livelli di verifica del contratto CSV:
1. `test_golden_message_to_csv` confronta il **dict-riga** prodotto dalla pipeline (valori
   canonici, `Price` col punto) — un caso ha l'`expect` su **tutte** le 14 colonne così anche
   `EventId`/`MarketId`/`Handicap`/`MinPrice`/… (non solo quelle "interessanti") sono blindate.
2. `test_golden_riga_serializza_csv_reale` rende la stessa riga attraverso il **vero writer**
   (`csv_writer.write_csv`) e confronta i **byte** del file (BOM utf-8-sig, `QUOTE_ALL`, `\\r\\n`,
   e la **localizzazione decimale**: `Price` diventa `1,85` in IT/ES e `1.85` in EN) — cioè
   esattamente ciò che XTrader legge, non solo il dict interno.
"""

import csv
import io
import re

import pytest

from xtrader_bridge import csv_writer
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
        # `expect` su TUTTE le 14 colonne (contratto XTrader completo): così una regressione su
        # QUALSIASI campo — anche EventId/MarketId/SelectionId/Handicap/MinPrice/MaxPrice/Points,
        # non solo quelli "interessanti" — viene beccata (review GLM 5.2 / Fugu Ultra #136).
        "id": "over_2_5_valido → riga CSV esatta (14 colonne)",
        "message": "P.Bet. Inter v Milan\nMercato: over 2,5\nQuota 1,85",
        "expect": {
            "Provider": "PBet", "EventId": "", "EventName": "Inter v Milan",
            "MarketId": "", "MarketName": "Over/Under 2,5 gol", "MarketType": "OVER_UNDER_25",
            "SelectionId": "", "SelectionName": "Over 2,5 goal", "Handicap": "0",
            "Price": "1.85", "MinPrice": "", "MaxPrice": "", "BetType": "PUNTA", "Points": "",
        },
    },
    {
        "id": "gol_gol_valido → BTTS Sì (14 colonne)",
        "message": "P.Bet. Roma v Lazio\nMercato: gol gol\nQuota 1,72",
        "expect": {
            "Provider": "PBet", "EventId": "", "EventName": "Roma v Lazio",
            "MarketId": "", "MarketName": "Entrambe le squadre a segno",
            "MarketType": "BOTH_TEAMS_TO_SCORE", "SelectionId": "", "SelectionName": "Sì",
            "Handicap": "0", "Price": "1.72", "MinPrice": "", "MaxPrice": "",
            "BetType": "PUNTA", "Points": "",
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
    # confronto RIGA COMPLETA su tutte le 14 colonne, non un sottoinsieme: una regressione su un
    # QUALSIASI campo (anche EventId/MarketId/…/Points vuoti) fallisce (coding guideline · CodeRabbit
    # #136). I casi validi dichiarano l'intero contratto atteso.
    assert set(case["expect"]) == set(cpe.CSV_HEADER), \
        "un caso golden valido deve dichiarare tutte le 14 colonne del contratto CSV"
    assert row == case["expect"], f"riga completa: attesa {case['expect']}, ottenuta {row}"


def test_setup_golden_e_coerente():
    """Meta: il parser e le mappature golden sono ben formati (almeno un caso valido produce
    una riga) — così la suite non passa 'a vuoto' per un setup rotto."""
    assert any(not c.get("expect_rejected") for c in CASES)
    validi = [c for c in CASES if not c.get("expect_rejected")]
    assert _run(validi[0]["message"]), "il primo caso valido deve produrre una riga piazzabile"


@pytest.fixture
def set_csv_lang():
    """Imposta la lingua CSV del writer e la **ripristina in teardown** — eseguito anche se il
    test solleva un'eccezione, così lo stato globale del modulo non sporca gli altri test (review
    GPT-5.5 + GLM 5.2 #136: niente flakiness da stato condiviso, più robusto di un try/finally
    locale)."""
    prev = csv_writer.get_csv_language()
    yield csv_writer.set_csv_language
    csv_writer.set_csv_language(prev)


# Ogni campo di una riga CSV valida è delimitato da virgolette (QUOTE_ALL), per l'intera riga.
_QUOTED_LINE = re.compile(r'^"[^"]*"(?:,"[^"]*")*$')


@pytest.mark.parametrize("lang,price_reso", [("IT", "1,85"), ("EN", "1.85"), ("ES", "1,85")])
def test_golden_riga_serializza_csv_reale(lang, price_reso, tmp_path, set_csv_lang):
    """La riga golden passata nel **vero writer** produce il file **byte per byte** che XTrader
    legge (review GPT-5.5 #136): non basta il dict-riga della pipeline, conta la serializzazione
    reale — BOM utf-8-sig, `QUOTE_ALL`, terminatore `\\r\\n` e la **localizzazione decimale**
    (`Price` = `1,85` in IT/ES, `1.85` in EN). Blinda il contratto CSV effettivo, non solo l'ordine
    delle chiavi del dict."""
    row = _run("P.Bet. Inter v Milan\nMercato: over 2,5\nQuota 1,85")[0]
    set_csv_lang(lang)
    path = tmp_path / "segnali.csv"
    csv_writer.write_csv(row, str(path))
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "manca il BOM utf-8-sig atteso da XTrader"
    text = raw.decode("utf-8-sig")
    assert text.endswith("\r\n") and text.count("\r\n") == 2, "attese esattamente header + 1 riga"
    header_line, data_line, _tail = text.split("\r\n")
    # QUOTE_ALL FORTE: OGNI campo di entrambe le righe è tra virgolette (non solo il primo)
    assert _QUOTED_LINE.match(header_line), f"header non interamente quotato: {header_line!r}"
    assert _QUOTED_LINE.match(data_line), f"riga dati non interamente quotata: {data_line!r}"
    righe = list(csv.reader(io.StringIO(text)))
    assert righe[0] == cpe.CSV_HEADER, "prima riga del file ≠ header contratto XTrader"
    campi = righe[1]
    assert len(campi) == len(cpe.CSV_HEADER), "numero colonne ≠ contratto XTrader"
    # localizzazione decimale reale: è il valore che XTrader parserà davvero
    assert campi[cpe.CSV_HEADER.index("Price")] == price_reso
    assert campi[cpe.CSV_HEADER.index("MarketType")] == "OVER_UNDER_25"
    assert campi[cpe.CSV_HEADER.index("SelectionName")] == "Over 2,5 goal"


def test_quote_all_preserva_colonne_con_virgola(tmp_path, set_csv_lang):
    """Un campo che contiene virgola/`;` (es. EventName `Inter, Milan; e altro`) NON deve spezzare
    le colonne: `QUOTE_ALL` lo protegge → sempre 14 campi, contenuto integro (review GLM 5.2 #136
    sul quoting reale)."""
    row = dict(_run("P.Bet. Inter v Milan\nMercato: over 2,5\nQuota 1,85")[0],
               EventName="Inter, Milan; e altro")
    set_csv_lang("IT")
    path = tmp_path / "s.csv"
    csv_writer.write_csv(row, str(path))
    righe = list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))
    assert righe[0] == cpe.CSV_HEADER
    assert len(righe[1]) == len(cpe.CSV_HEADER), "la virgola nel campo ha spezzato le colonne"
    assert righe[1][cpe.CSV_HEADER.index("EventName")] == "Inter, Milan; e altro"


@pytest.mark.parametrize("lang,atteso", [("IT", "12,50"), ("EN", "12.50")])
def test_localizzazione_prezzo_maggiore_di_dieci(lang, atteso, tmp_path, set_csv_lang):
    """Prezzo > 10 (review GLM 5.2 #136): la localizzazione è uno **swap di carattere**, non un
    reformat — `12.50` → `12,50` in IT, resta `12.50` in EN. Nessun separatore delle migliaia
    introdotto (XTrader non lo tollererebbe)."""
    row = dict(_run("P.Bet. Inter v Milan\nMercato: over 2,5\nQuota 1,85")[0], Price="12.50")
    set_csv_lang(lang)
    path = tmp_path / f"p_{lang}.csv"
    csv_writer.write_csv(row, str(path))
    righe = list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))
    assert righe[1][cpe.CSV_HEADER.index("Price")] == atteso


def test_mappature_vuote_fail_closed():
    """Fail-closed del resolver (review GLM 5.2 #136): se il profilo mercati è VUOTO, un messaggio
    che dipende dalla mappatura mercato (`over 2,5`) NON deve produrre alcuna riga piazzabile —
    mai tirare a indovinare un mercato quando non è mappato."""
    profiles = market_mapping_store.entries_for_profiles(
        {"market_mappings": {"Canale": []}}, GOLDEN_PARSER.market_mapping_profiles)
    results = custom_pipeline.build_validated_rows(
        GOLDEN_PARSER, "P.Bet. Inter v Milan\nMercato: over 2,5\nQuota 1,85",
        mode=GOLDEN_PARSER.mode, market_mapping_profiles=profiles,
        provider="PBet", require_price=True)
    assert [r.row for r in results if r.placeable] == [], \
        "con mappature vuote il resolver deve fail-closare (nessuna riga)"
