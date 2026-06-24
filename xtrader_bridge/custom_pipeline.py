"""CP-04: dal Parser Personalizzato a una riga CSV validata.

Collega l'output del Parser Personalizzato (estrazione CP-02 + value-map CP-03)
al `validator` (PR-10) e al contratto CSV, producendo una riga **pronta per la
scrittura** — o uno stato chiaro di scarto. NON scrive il CSV e NON tocca `app`
(l'aggancio al runtime è CP-09); NON applica trasformazioni (CP-05); NON tocca
la GUI (CP-06).

Due gate, entrambi devono passare perché la riga sia "piazzabile":
1. **parser "Non pronto"** (CP-02): se un campo obbligatorio della regola è vuoto
   → `NOT_READY` (nessuna riga).
2. **validator** (PR-10): campi della modalità di riconoscimento + `Price` > 1.0
   + `BetType` ∈ {PUNTA, BANCA}.

La riga viene comunque costruita (a 14 colonne) per diagnostica, ma va scritta
SOLO se `result.placeable` è True (status VALID).
"""

import re
import threading
from dataclasses import dataclass, field

from . import (
    market_mapping_store,
    name_mapping_store,
    recognition,
    validator,
    value_maps,
)
from .csv_writer import DEFAULT_HANDICAP, DEFAULT_POINTS
from .custom_parser import CustomParserDef
from .custom_parser_engine import apply_parser

# Separatore casa/trasferta di default quando il parser richiede la mappatura nomi
# ma non specifica `team_separator` (Betfair usa "Casa v Trasferta").
_DEFAULT_TEAM_SEPARATOR = "v"

# Registro value-map di default del pipeline: include il dizionario (le mappe
# markettype/marketname/selectionname usate dallo skeleton e dai parser reali).
# Costruito una volta (legge il CSV una sola volta), poi riusato.
_DEFAULT_REGISTRY = None
# Lock per l'init lazy: senza, due thread al primo uso concorrente potrebbero
# costruire il registro due volte, leggendo il CSV due volte (A8). La build è
# idempotente, quindi era benigno; il lock garantisce una sola costruzione.
_REGISTRY_LOCK = threading.Lock()


def _default_registry() -> dict:
    """Registro value-map di default (lazy, in cache). Double-checked locking (A8):
    `value_maps.registry` ritorna un dict già completo, quindi l'assegnazione di
    `_DEFAULT_REGISTRY` pubblica direttamente il valore finito."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        with _REGISTRY_LOCK:
            if _DEFAULT_REGISTRY is None:
                _DEFAULT_REGISTRY = value_maps.registry(include_dizionario=True)
    return _DEFAULT_REGISTRY

NOT_READY = "NOT_READY"   # gate parser: manca un campo obbligatorio della regola
INVALID_MISSING_PROVIDER = "INVALID_MISSING_PROVIDER"  # Provider assente (contratto)
INVALID_HANDICAP = "INVALID_HANDICAP"  # Handicap valorizzato ma non numerico
# Mappatura nomi richiesta ma EventName non traducibile (separatore non trovato o una
# squadra non nei profili): fail-closed, nessuna riga (un evento sbagliato = bet sbagliato).
MAPPING_MISSING = "MAPPING_MISSING"
# Mappatura mercati richiesta ma il mercato non è risolvibile: o due frasi indicano mercati
# DIVERSI (ambiguo, D2 fail-closed), oppure nessuna frase combacia e nemmeno le regole-colonna
# hanno estratto un mercato. Fail-closed: nessuna riga (un mercato sbagliato/inventato = bet
# sbagliato). Vedi docs/audit/mercati_mapping_design.md §4-§5.
MARKET_MAPPING_MISSING = "MARKET_MAPPING_MISSING"

# Handicap: numero con segno opzionale (es. "0", "-1", "0.5", "+1,5").
_HANDICAP_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")

# Colonne quota: il contratto XTrader usa il punto decimale (es. "1.85").
_PRICE_COLS = ("Price", "MinPrice", "MaxPrice")


@dataclass
class PipelineResult:
    """Esito del passaggio messaggio → riga validata."""

    status: str                                   # NOT_READY | validator.* (VALID/INVALID_*)
    row: "dict[str, str]" = field(default_factory=dict)   # riga 14 colonne (diagnostica)
    missing_required: "list[str]" = field(default_factory=list)  # gate parser
    detail: object = None                         # dettaglio del validator (campi/valore)

    @property
    def placeable(self) -> bool:
        """True solo se la riga ha passato entrambi i gate (status VALID)."""
        return self.status == validator.VALID


def _row_has_market(row: dict, mode: str) -> bool:
    """True se la riga ha già un mercato sufficiente per la **modalità di riconoscimento**:
    NAME → `MarketType`+`SelectionName`; ID → `MarketId`+`SelectionId`; BOTH → almeno una
    delle due coppie. Usato dal fallback della mappatura mercati per decidere, quando
    NESSUNA frase combacia, se le regole-colonna hanno comunque prodotto un mercato (così
    non si fa fail-closed su una riga che — secondo la sua modalità — il mercato ce l'ha già,
    evitando di scartare per errore una riga ID valida)."""
    m = recognition.normalize_mode(mode)

    def _present(*cols):
        return all(str(row.get(c, "")).strip() for c in cols)

    if m == recognition.ID_ONLY:
        return _present("MarketId", "SelectionId")
    if m == recognition.NAME_ONLY:
        return _present("MarketType", "SelectionName")
    return _present("MarketId", "SelectionId") or _present("MarketType", "SelectionName")


def _normalize_to_contract(row: dict, provider: str) -> dict:
    """Porta la riga al formato del contratto XTrader, senza sovrascrivere i
    valori già impostati dalle regole:

    - `Provider`: dal runtime/config (`provider`) se la regola non lo imposta;
    - `Handicap` = "0" se vuoto/None; `Points` resta vuoto;
    - `Price`/`MinPrice`/`MaxPrice`: virgola → punto (es. "1,85" → "1.85");
    - `BetType`: maiuscolo (il contratto emette esattamente PUNTA/BANCA).
    """
    out = dict(row)
    if provider and not str(out.get("Provider", "")).strip():
        out["Provider"] = provider
    hcap = out.get("Handicap")
    # None o stringa vuota → default; evita str(None)=="None" (truthy).
    if hcap is None or not str(hcap).strip():
        out["Handicap"] = DEFAULT_HANDICAP
    if out.get("Points") is None:
        out["Points"] = DEFAULT_POINTS
    for col in _PRICE_COLS:
        v = out.get(col)
        if v is not None and str(v).strip():
            out[col] = str(v).replace(",", ".")
    bt = out.get("BetType")
    if bt is not None and str(bt).strip():
        out["BetType"] = str(bt).strip().upper()
    return out


def build_validated_row(defn: CustomParserDef, text: str, *,
                        value_maps_registry: dict = None,
                        provider: str = "",
                        mode: str = recognition.DEFAULT_MODE,
                        require_price: bool = True,
                        name_mapping_profiles=None,
                        market_mapping_profiles=None) -> PipelineResult:
    """Applica il parser al messaggio e valida la riga risultante.

    `provider` è fornito dal runtime/config (come per il parser hardcoded) e
    riempie la colonna `Provider` se la regola non la imposta.

    `value_maps_registry` di default include il dizionario (built-in + mappe
    markettype/marketname/selectionname), così i parser/skeleton che usano quelle
    value-map risolvono senza che il chiamante debba passare un registro.

    `name_mapping_profiles` (lista di liste-di-righe, vedi `name_mapping_store`):
    se il parser richiede la mappatura nomi (`defn.name_mapping_profiles` non vuoto)
    l'`EventName` provider viene tradotto nel nome Betfair/XTrader PRIMA della
    validazione; se non è traducibile lo stato è `MAPPING_MISSING` (fail-closed,
    nessuna riga). La mappatura è **obbligatoria** quando richiesta: profili assenti
    (`None`) sono trattati come lista vuota → `MAPPING_MISSING` (l'anteprima senza
    config non deve mostrare "Pronto" per un evento che il runtime scarterebbe).

    `market_mapping_profiles` (lista di liste-di-voci, vedi `market_mapping_store`):
    se il parser seleziona dei profili mercati (`defn.market_mapping_profiles` non vuoto),
    una frase-mercato del provider nel **messaggio grezzo** (D3) imposta
    `MarketType`/`MarketName`/`SelectionName` CANONICI dal Catalogo XTrader. Precedenza D1:
    il dizionario **vince** sulle regole-colonna quando una frase combacia in modo univoco;
    ambiguità → `MARKET_MAPPING_MISSING` (fail-closed, D2); nessun match → restano i valori
    delle regole-colonna, ma se nemmeno quelle hanno un mercato → `MARKET_MAPPING_MISSING`
    (mai un mercato inventato). Profili `None` (anteprima senza config) = lista vuota.

    Ritorna un `PipelineResult`: `placeable` True solo se supera il gate "Non
    pronto" del parser, ha un `Provider` E passa la validazione (modalità +
    prezzo + BetType). La riga è già in formato contratto (quota col punto,
    BetType maiuscolo)."""
    if value_maps_registry is None:
        value_maps_registry = _default_registry()
    res = apply_parser(defn, text, value_maps_registry)
    row = _normalize_to_contract(res.as_csv_row(), provider)

    if not res.ready:
        # Manca un obbligatorio della regola: non si costruisce un segnale.
        return PipelineResult(NOT_READY, row, list(res.missing_required))

    if not str(row.get("Provider", "")).strip():
        # Provider è obbligatorio per il contratto; il runtime lo passa da config.
        return PipelineResult(INVALID_MISSING_PROVIDER, row, list(res.missing_required))

    # Handicap valorizzato dal parser ma non numerico: scartato (il default "0"
    # e i valori del dizionario sono sempre numerici).
    hcap = str(row.get("Handicap", "")).strip()
    if hcap and not _HANDICAP_RE.match(hcap):
        return PipelineResult(INVALID_HANDICAP, row, list(res.missing_required))

    # Mappatura nomi squadra: traduce l'EventName provider nel nome Betfair/XTrader.
    # Se il parser la richiede è **obbligatoria** e fail-closed: profili assenti
    # (`None`, es. anteprima senza config) sono trattati come "nessun profilo" →
    # MAPPING_MISSING, così l'anteprima NON mostra "Pronto" per un evento che il
    # runtime scarterebbe (Codex). Senza profili richiesti l'EventName resta invariato.
    if defn.name_mapping_profiles:
        sep = (defn.team_separator or "").strip() or _DEFAULT_TEAM_SEPARATOR
        mapped = name_mapping_store.resolve_event_name(
            row.get("EventName", ""), sep, name_mapping_profiles or [])
        if mapped is None:
            return PipelineResult(MAPPING_MISSING, row, list(res.missing_required))
        row = dict(row)
        row["EventName"] = mapped

    # Mappatura mercati a frase (market_mapping_store, FASE 2). Solo se il parser seleziona
    # dei profili mercati. Regola di precedenza D1 (design §4): il DIZIONARIO VINCE sulle
    # regole-colonna quando una frase combacia in modo univoco; ambiguità → fail-closed (D2).
    # Profili None (anteprima senza config) = lista vuota → si valuta come "nessun match".
    if defn.market_mapping_profiles:
        resm = market_mapping_store.resolve_market(text, market_mapping_profiles or [])
        if resm.status == "ambiguous":
            # Due frasi indicano mercati diversi: niente riga, mai tirare a indovinare.
            return PipelineResult(MARKET_MAPPING_MISSING, row, list(res.missing_required))
        if resm.status == "ok":
            # Il dizionario vince: sovrascrive Type/Mercato/Selezione con i valori CANONICI
            # del catalogo (resolve_market li ha già canonicalizzati).
            row = dict(row)
            row["MarketType"] = resm.market["market_type"]
            row["MarketName"] = resm.market["market_name"]
            row["SelectionName"] = resm.market["selection_name"]
            # La mappatura mercati è NAME-based (resolve_market non risolve gli ID, non sono
            # nel catalogo): azzera la coppia ID quando il dizionario vince, così la riga non
            # porta un MarketId/SelectionId STANTIO (estratto dalle regole-colonna) che
            # contraddirebbe il mercato a nome — nel CSV identificatori incoerenti, o in
            # validazione ID/BOTH gli ID vecchi "vincerebbero" ignorando la frase. Così il
            # mercato della riga è univocamente la tupla a nome del dizionario; se la modalità
            # richiedeva gli ID (ID_ONLY), la riga fa fail-closed in validazione — niente
            # scommessa su un mercato ambiguo (CodeRabbit).
            row["MarketId"] = ""
            row["SelectionId"] = ""
        elif not _row_has_market(row, mode):
            # status "none": nessuna frase combacia. Si tengono i valori della regola-colonna
            # SE costituiscono già un mercato per la modalità; altrimenti il mercato resterebbe
            # assente → fail-closed (niente mercato inventato), invece di lasciar passare una
            # riga senza mercato. Controllo mode-aware per non scartare per errore una riga ID.
            return PipelineResult(MARKET_MAPPING_MISSING, row, list(res.missing_required))

    status, detail = validator.validate(row, mode, require_price)
    return PipelineResult(status, row, list(res.missing_required), detail)


def is_placeable(defn: CustomParserDef, text: str, **kwargs) -> bool:
    """Scorciatoia: True se il messaggio produce una riga piazzabile."""
    return build_validated_row(defn, text, **kwargs).placeable
