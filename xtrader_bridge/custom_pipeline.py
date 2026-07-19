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

import logging
import re
import threading
from dataclasses import dataclass, field, replace

from . import (
    dizionario,
    market_mapping_store,
    name_mapping_store,
    numbers_re,
    recognition,
    validator,
    value_maps,
)
from .csv_writer import DEFAULT_HANDICAP, DEFAULT_POINTS
from .custom_parser import CustomParserDef
from .custom_parser_engine import apply_parser, extract_scores

# Separatore casa/trasferta di default quando il parser richiede la mappatura nomi
# ma non specifica `team_separator` (Betfair usa "Casa v Trasferta").
_DEFAULT_TEAM_SEPARATOR = "v"

# Avviso non-fatale (issue #38): nel percorso di riformattazione SENZA dizionario nomi,
# quando il separatore è impostato ma NON si trova tra le due squadre (nessuna forma
# spaziata), l'EventName resta VERBATIM (la riga non viene scartata: normalizzare un
# formato non può creare una scommessa errata) e si emette questo avviso in preview/log.
WARN_TEAM_SEPARATOR_NOT_FOUND = "separatore non trovato tra le squadre: nome lasciato invariato"

# Registro value-map di default del pipeline: include il dizionario (le mappe
# markettype/marketname/selectionname usate dallo skeleton e dai parser reali).
# Costruito una volta (legge il CSV una sola volta), poi riusato.
_DEFAULT_REGISTRY = None
# Lock per l'init lazy: senza, due thread al primo uso concorrente potrebbero
# costruire il registro due volte, leggendo il CSV due volte (A8). La build è
# idempotente, quindi era benigno; il lock garantisce una sola costruzione.
_REGISTRY_LOCK = threading.Lock()


_LOG = logging.getLogger(__name__)


def _default_registry() -> dict:
    """Registro value-map di default (lazy, in cache). Double-checked locking (A8):
    `value_maps.registry` ritorna un dict già completo, quindi l'assegnazione di
    `_DEFAULT_REGISTRY` pubblica direttamente il valore finito.

    P3-14 #76: la costruzione col dizionario può FALLIRE (CSV bundled corrotto/
    mancante/header invalido: `load_dizionario` solleva apposta). Senza guardia,
    l'eccezione esplodeva a OGNI messaggio dentro l'handler Telegram — outage
    silenzioso del bridge. Fallback: registro dei SOLI built-in (fail-closed a
    valle: le mappe-dizionario assenti risolvono a "" → campo «Non pronto» →
    nessuna riga sbagliata nel CSV), messo IN CACHE (niente retry-storm per
    messaggio) con un warning che dice come rimediare."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        with _REGISTRY_LOCK:
            if _DEFAULT_REGISTRY is None:
                try:
                    _DEFAULT_REGISTRY = value_maps.registry(include_dizionario=True)
                except Exception as exc:   # noqa: BLE001 — vedi allowlist blind-except (P3-14)
                    _LOG.warning(
                        "value-map: dizionario XTrader NON caricabile (%s: %s) -> "
                        "registro di FALLBACK coi soli built-in (le mappe-dizionario "
                        "risolveranno a vuoto: fail-closed). Ripristina il CSV del "
                        "dizionario e riavvia per riabilitarle (P3-14 #76).",
                        type(exc).__name__, exc)
                    # Ultimo-resort (nota Fable PR #108): se anche i built-in
                    # fallissero (teorico: nessun I/O), MAI un'eccezione
                    # per-messaggio — registro VUOTO cacheato: `resolve` ritorna
                    # "" per qualunque mappa → «Non pronto» (fail-closed).
                    try:
                        _DEFAULT_REGISTRY = value_maps.registry(include_dizionario=False)
                    except Exception as exc2:   # noqa: BLE001 — vedi allowlist blind-except
                        _LOG.error(
                            "value-map: anche il registro built-in NON e' costruibile "
                            "(%s: %s) -> registro VUOTO di ultimo-resort (ogni value-map "
                            "risolve a vuoto: fail-closed). Reinstalla/ripara l'app.",
                            type(exc2).__name__, exc2)
                        _DEFAULT_REGISTRY = {}
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
_HANDICAP_RE = re.compile(r"^" + numbers_re.SIGNED_DECIMAL + r"$")   # frammento condiviso (L4)

# Colonne quota: il contratto XTrader usa il punto decimale (es. "1.85").
_PRICE_COLS = ("Price", "MinPrice", "MaxPrice")
# Colonne decimali normalizzate virgola→punto al contratto (P2-2 audit #76): oltre alle quote,
# anche Handicap e Points. `_HANDICAP_RE` accetta la virgola («+1,5») e `Handicap` è parte della
# chiave di deduplica per-riga (`signal_dedupe._ROW_KEY_FIELDS`, confronto su stringa grezza):
# senza normalizzazione, la STESSA scommessa da due parser (stile «0.5» vs «0,5») avrebbe chiavi
# diverse → nessuna dedup → due righe identiche nel CSV localizzato (doppia scommessa). La riga
# interna deve restare canonica col punto (docstring `csv_writer.localize_row`); l'output CSV non
# cambia: `_localize_decimal` serializza già in modo uniforme per lingua.
_DECIMAL_NORM_COLS = _PRICE_COLS + ("Handicap", "Points")


def _decimal_sep_to_point(value) -> str:
    """Normalizza il separatore decimale a `.`, interpretando i formati con separatore delle
    migliaia (#184 low-pipeline-comma).

    Se sono presenti SIA `,` SIA `.`, l'ULTIMO che compare è il separatore **decimale** e l'altro è
    quello delle **migliaia** — ma SOLO se la parte intera è un raggruppamento migliaia VALIDO
    (`\\d{1,3}(<sep>\\d{3})+`) e i decimali sono sole cifre: `"1.234,56"` → `"1234.56"`,
    `"1,234.56"` → `"1234.56"`. Altrimenti (raggruppamento malformato, es. `"1.2,3"`) si lascia il
    valore **invariato**, così il validatore a valle lo scarta (fail-closed) invece di emettere un
    prezzo SBAGLIATO ma valido (Codex #184): `Price` finisce nella riga di scommessa CSV.

    Con il solo `,` è il decimale (`,`→`.`); con il solo `.` resta invariato (le quote tipiche
    `1.85` non cambiano); senza separatori, invariato. Un input non numerico resta tale (rifiutato
    a valle)."""
    s = str(value).strip()
    last_comma, last_dot = s.rfind(","), s.rfind(".")
    if last_comma != -1 and last_dot != -1:
        dec_sep, th_sep = (",", ".") if last_comma > last_dot else (".", ",")
        int_part, dec_part = s.rsplit(dec_sep, 1)
        grouped = re.fullmatch(r"\d{1,3}(?:" + re.escape(th_sep) + r"\d{3})+", int_part)
        if grouped and dec_part.isdigit():
            return int_part.replace(th_sep, "") + "." + dec_part
        return s                                   # raggruppamento non valido → invariato (fail-closed)
    if last_comma != -1:                          # solo virgola → decimale
        return s.replace(",", ".")
    return s                                       # solo punto, o nessun separatore


@dataclass
class PipelineResult:
    """Esito del passaggio messaggio → riga validata."""

    status: str                                   # NOT_READY | validator.* (VALID/INVALID_*)
    row: "dict[str, str]" = field(default_factory=dict)   # riga 14 colonne (diagnostica)
    missing_required: "list[str]" = field(default_factory=list)  # gate parser
    detail: object = None                         # dettaglio del validator (campi/valore)
    warnings: "list[str]" = field(default_factory=list)   # avvisi non-fatali (issue #38), per preview/log
    # P3-11 #76: True quando l'output multi era attivo ma la generazione NON è mai
    # partita perché la BASE è bloccata (`build_validated_rows` → `[base]`): il
    # risultato È la riga base, e l'anteprima deve etichettarla/valutarla come tale
    # (verdetto single-row con «mancanti:»), non come riga market/selection.
    base_fallback: bool = False

    @property
    def placeable(self) -> bool:
        """True solo se la riga ha passato entrambi i gate (status VALID)."""
        return self.status == validator.VALID


def _row_has_market(row: dict, mode: str, supplied=()) -> bool:
    """True se la riga ha già un mercato sufficiente per la **modalità di riconoscimento**:
    NAME → `MarketType`+`SelectionName`; ID → `MarketId`+`SelectionId`; BOTH → almeno una
    delle due coppie. Usato dal fallback della mappatura mercati per decidere, quando
    NESSUNA frase combacia, se le regole-colonna hanno comunque prodotto un mercato (così
    non si fa fail-closed su una riga che — secondo la sua modalità — il mercato ce l'ha già,
    evitando di scartare per errore una riga ID valida).

    `supplied` (#192 kyZ): colonne che OGNI riga multi generata riempirà — trattate come
    **presenti** anche se vuote sulla base, così un campo mercato fornito dalle righe multi
    (es. `SelectionName` di un MultiSelection) non provoca un falso `MARKET_MAPPING_MISSING`
    (Codex/CodeRabbit). La riga base non viene scritta; ogni riga derivata è validata a parte."""
    m = recognition.normalize_mode(mode)
    supplied = frozenset(supplied or ())

    def _present(*cols):
        return all(c in supplied or str(row.get(c, "")).strip() for c in cols)

    if m == recognition.ID_ONLY:
        return _present("MarketId", "SelectionId")
    if m == recognition.NAME_ONLY:
        return _present("MarketType", "SelectionName")
    return _present("MarketId", "SelectionId") or _present("MarketType", "SelectionName")


def _resolve_ids_into(row: dict, *, sport: str, id_resolver) -> dict:
    """Arricchisce la riga con `EventId`/`MarketId`/`SelectionId` dal dizionario Betfair locale
    (PR-P12), ristretto allo `sport` del parser. **Additivo, fail-open, NON distruttivo:**

    - se `id_resolver` è assente o lo sport è vuoto (parser agnostico) → riga invariata;
    - un errore del resolver non blocca il flusso (best-effort) → riga a nomi;
    - se il parser ha già fornito un ID esplicito (ID/BOTH) NON lo si sovrascrive; se un ID del
      parser è in **conflitto** con la tripla risolta si **scarta del tutto** l'arricchimento (un
      dizionario stantio non deve scrivere un mercato/selezione sbagliato); altrimenti si riempiono
      **solo** i campi ID vuoti con la tripla coerente del dizionario.

    Condivisa tra la riga BASE (`build_validated_row`) e OGNI riga multi derivata
    (`_validated_multi_row`, #192): una MultiSelection azzera gli ID al cambio selezione, quindi la
    riga derivata deve ri-risolvere gli ID per la PROPRIA selezione, altrimenti in ID_ONLY resterebbe
    senza ID e non piazzabile. Ritorna la riga (nuova se arricchita, altrimenti la stessa)."""
    if id_resolver is None or not sport:
        return row
    try:
        ids = id_resolver.resolve_ids(
            sport=sport,
            event_name=row.get("EventName", ""),
            market_type=row.get("MarketType", ""),
            market_name=row.get("MarketName", ""),
            selection_name=row.get("SelectionName", ""),
            handicap=row.get("Handicap", ""))
    except Exception:   # noqa: BLE001 — risoluzione best-effort: niente blocco del flusso
        ids = None
    # Fail-open robusto (CodeRabbit): un resolver pluggable potrebbe ritornare un valore truthy
    # NON dict (lista, oggetto…) → `ids.get`/`ids[_k]` solleverebbero FUORI dal try, violando la
    # garanzia best-effort. Si accetta solo un dict non vuoto; altrimenti riga invariata (a nomi).
    if not isinstance(ids, dict) or not ids:
        return row

    def _norm(v):   # normalizzazione condivisa dei valori di riga (Sourcery: no duplicazione)
        return str(v).strip()

    _keys = ("EventId", "MarketId", "SelectionId")
    _conflict = any(
        _norm(row.get(_k, ""))
        and ids.get(_k) and _norm(row.get(_k, "")) != str(ids[_k])
        for _k in _keys)
    if _conflict:
        return row
    out = dict(row)
    for _k in _keys:
        _v = ids.get(_k)
        if _v and not _norm(out.get(_k, "")):
            out[_k] = str(_v)   # valore ID invariato (base bit-identica): niente strip sull'ID risolto
    return out


def _normalize_to_contract(row: dict, provider: str) -> dict:
    """Porta la riga al formato del contratto XTrader, senza sovrascrivere i
    valori già impostati dalle regole:

    - `Provider`: dal runtime/config (`provider`) se la regola non lo imposta;
    - `Handicap` = "0" se vuoto/None; `Points` resta vuoto;
    - `Price`/`MinPrice`/`MaxPrice`/`Handicap`/`Points`: virgola → punto (es. "1,85" → "1.85";
      P2-2 audit #76: anche Handicap/Points, così la chiave dedup per-riga è canonica e la
      stessa scommessa in stile «0,5»/«0.5» non genera due righe);
    - `BetType`: canonicalizzato al lato ITALIANO del contratto (`BACK`→`PUNTA`, `LAY`→`BANCA`,
      `PUNTA`/`BANCA` invariati). Gli input inglesi sono accettati indifferentemente (conferma
      supporto BT/XT, issue #3), ma l'OUTPUT CSV resta canonico PUNTA/BANCA (universale su tutte
      le versioni). Un lato ignoto resta invariato e sarà respinto in validazione (fail-closed).
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
    for col in _DECIMAL_NORM_COLS:
        v = out.get(col)
        if v is not None and str(v).strip():
            out[col] = _decimal_sep_to_point(v)
    bt = out.get("BetType")
    if bt is not None and str(bt).strip():
        # Canonicalizza al lato ITALIANO del contratto: BACK/LAY (input inglese, valido su tutte
        # le versioni BT/XT — issue #3) → PUNTA/BANCA; PUNTA/BANCA invariati. Un lato ignoto resta
        # invariato (uppercase) e la validazione lo respinge (fail-closed, mai indovinare il lato).
        out["BetType"] = validator.canonical_bettype(bt)
    return out


def build_validated_row(defn: CustomParserDef, text: str, *,
                        value_maps_registry: dict = None,
                        provider: str = "",
                        mode: str = recognition.DEFAULT_MODE,
                        require_price: bool = True,
                        name_mapping_profiles=None,
                        market_mapping_profiles=None,
                        id_resolver=None,
                        source_language="",
                        multi_supplied=None) -> PipelineResult:
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
    il mercato letto da una **posizione delimitata** del messaggio (D3: `resolve_market`
    estrae tra `Inizia dopo`/`Finisce prima`) imposta `MarketType`/`MarketName`/
    `SelectionName` CANONICI dal Catalogo XTrader. Precedenza D1:
    il dizionario **vince** sulle regole-colonna quando una voce combacia in modo univoco;
    ambiguità → `MARKET_MAPPING_MISSING` (fail-closed, D2); nessun match → restano i valori
    delle regole-colonna, ma se nemmeno quelle hanno un mercato → `MARKET_MAPPING_MISSING`
    (mai un mercato inventato). Profili `None` (anteprima senza config) = lista vuota.

    Ritorna un `PipelineResult`: `placeable` True solo se supera il gate "Non
    pronto" del parser, ha un `Provider` E passa la validazione (modalità +
    prezzo + BetType). La riga è già in formato contratto (quota col punto,
    BetType maiuscolo).

    `multi_supplied` (#192 kyZ, uso INTERNO di `build_validated_rows`): insieme di **colonne
    CSV** che OGNI riga multi generata riempirà con un valore non vuoto (es. `SelectionName`
    per un MultiSelection). I gate STRUTTURALI trattano quelle colonne come **già presenti**,
    così un obbligatorio della base che le righe multi completeranno non blocca la generazione:
    - il gate "Non pronto" (`NOT_READY`) ignora SOLO gli obbligatori mancanti che sono in
      `multi_supplied` (Codex P1); se restano altri obbligatori scoperti → resta `NOT_READY`;
    - il fallback della mappatura mercati (`_row_has_market`) considera coperti i campi mercato
      forniti dalle righe multi (Codex/CodeRabbit), evitando un falso `MARKET_MAPPING_MISSING`.
    Gli altri gate (provider/handicap, mappatura nomi) restano invariati e fail-closed. La base
    non viene mai scritta: ogni riga derivata è comunque validata da `validator.validate`."""
    if value_maps_registry is None:
        value_maps_registry = _default_registry()
    res = apply_parser(defn, text, value_maps_registry)
    row = _normalize_to_contract(res.as_csv_row(), provider)

    supplied = frozenset(multi_supplied or ())
    if not res.ready:
        # kyZ (#192): un obbligatorio mancante che le righe multi riempiranno (`multi_supplied`)
        # NON blocca — ma quelli NON coperti restano bloccanti (Codex P1: mai un messaggio
        # dichiarato incompleto dal parser che finisce nel CSV su un campo che il validator non
        # ri-controlla). Se dopo aver scartato i coperti resta anche un solo obbligatorio → NOT_READY.
        still_missing = [t for t in res.missing_required if t not in supplied]
        if still_missing:
            return PipelineResult(NOT_READY, row, still_missing)
        # Tutti gli obbligatori mancanti sono forniti dalle righe multi: si prosegue per mappature
        # nomi/mercati (a valle di questo gate); `_apply_multi_rule` poi sovrascrive i campi della
        # singola riga e ogni riga derivata è validata da `validator.validate` (fail-closed per riga).

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
    warnings = []   # avvisi non-fatali (issue #38) da riportare in preview/log
    if defn.name_mapping_profiles:
        sep = (defn.team_separator or "").strip() or _DEFAULT_TEAM_SEPARATOR
        # Sport del parser (PR-P10): restringe la mappatura nomi alle righe di quello sport
        # o agnostiche, così un nome non viene tradotto con la voce di uno sport diverso.
        # entity_type (#178 §2, Codex P1): i partecipanti di un evento sono squadre/giocatori
        # → si usano SOLO le righe participant/team/player (più le agnostiche), escludendo le
        # righe competition/market/selection con alias che collide (no EventName sbagliato).
        original_event = str(row.get("EventName", "") or "")
        # `source_language` (epica #3 slice 5b wiring): lingua-fonte effettiva risolta dal
        # chiamante (`recognition.effective_source_language(cfg, defn)`), IDENTICA su live e
        # anteprima (invariante di parità). Restringe la mappatura nomi alle righe di quella
        # lingua o agnostiche; vuota = comportamento storico (nessun filtro-lingua).
        mapped = name_mapping_store.resolve_event_name(
            original_event, sep, name_mapping_profiles or [],
            sport=getattr(defn, "sport", ""),
            entity_type=name_mapping_store.PARTICIPANT_ENTITY_TYPES,
            language=source_language)
        if mapped is None:
            return PipelineResult(MAPPING_MISSING, row, list(res.missing_required))
        row = dict(row)
        row["EventName"] = mapped
        if mapped != original_event:
            # Stessa regola del ramo mercati sotto (audit #259 B1): quando il dizionario
            # VINCE sul nome, gli ID estratti dalle regole-colonna riferivano l'evento
            # col nome provider e possono contraddire il nome canonico appena scritto —
            # nel CSV finirebbero identificatori di un ALTRO oggetto e XTrader, se
            # prioritizza gli ID, punterebbe l'evento sbagliato. Si azzera la catena
            # (evento + figli): `_resolve_ids_into` a valle la ricostruisce dal nome
            # canonico via dizionario locale; se la modalità richiede gli ID e il
            # dizionario non li ha, la riga fa fail-closed in validazione.
            row["EventId"] = ""
            row["MarketId"] = ""
            row["SelectionId"] = ""
    elif (defn.team_separator or "").strip():
        # Issue #38 — riformattazione EventName SENZA dizionario nomi: se il parser NON ha
        # un dizionario ma ha un `team_separator` ESPLICITAMENTE non vuoto, si normalizza solo
        # il FORMATO del nome nel formato XTrader «Casa - Trasferta», usando le squadre
        # **verbatim** del messaggio (nessuna traduzione, nessun nome inventato).
        #
        # - `spaced_only=True` (guardia anti-split, commento owner sull'issue): per i separatori
        #   simbolici (`-`/`/`) si accetta SOLO la forma spaziata, niente fallback compatto, così
        #   un separatore sbagliato non taglia dentro un nome col trattino/slash interno
        #   (es. "Al-Kholood Club v Al-Hilal" con sep `-`).
        # - split OK → ricompone «Casa - Trasferta» (`compose_event_name`). NON si azzerano gli ID:
        #   è lo STESSO evento, solo col separatore normalizzato (a differenza del ramo dizionario,
        #   dove il nome può CAMBIARE per traduzione → lì gli ID stantii vanno azzerati).
        # - split FALLITO → EventName VERBATIM + avviso visibile (la riga NON viene scartata:
        #   normalizzare un formato non può creare una scommessa errata; un formato non
        #   normalizzato al massimo non è riconosciuto da XTrader).
        # - NESSUN default `v` qui (a differenza del ramo dizionario): la riformattazione scatta
        #   SOLO col separatore esplicito → parser esistenti col campo vuoto restano invariati.
        sep = defn.team_separator.strip()
        original_event = str(row.get("EventName", "") or "")
        split = name_mapping_store.split_event(original_event, sep, spaced_only=True)
        if split is not None and original_event:
            home, away = split
            recomposed = dizionario.compose_event_name(home, away)
            if recomposed != original_event:
                row = dict(row)
                row["EventName"] = recomposed
        elif original_event:
            # separatore impostato ma non trovato tra le squadre → verbatim + avviso
            warnings.append(WARN_TEAM_SEPARATOR_NOT_FOUND)

    # Mappatura mercati a frase (market_mapping_store, FASE 2). Solo se il parser seleziona
    # dei profili mercati. Regola di precedenza D1 (design §4): il DIZIONARIO VINCE sulle
    # regole-colonna quando una frase combacia in modo univoco; ambiguità → fail-closed (D2).
    # Profili None (anteprima senza config) = lista vuota → si valuta come "nessun match".
    if defn.market_mapping_profiles:
        # `language` (epica #3 slice 5c): la stessa lingua-fonte effettiva usata per i nomi
        # (identica su live e anteprima, 5b wiring) filtra anche il dizionario mercati, così
        # una voce mercato di lingua sbagliata non si applica. `""` = nessun filtro (legacy).
        resm = market_mapping_store.resolve_market(text, market_mapping_profiles or [],
                                                   language=source_language)
        if resm.status == "ambiguous":
            # Due frasi indicano mercati diversi: niente riga, mai tirare a indovinare.
            return PipelineResult(MARKET_MAPPING_MISSING, row, list(res.missing_required),
                                  warnings=warnings)
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
        elif not _row_has_market(row, mode, supplied=supplied):
            # status "none": nessuna frase combacia. Si tengono i valori della regola-colonna
            # SE costituiscono già un mercato per la modalità; altrimenti il mercato resterebbe
            # assente → fail-closed (niente mercato inventato), invece di lasciar passare una
            # riga senza mercato. Controllo mode-aware per non scartare per errore una riga ID.
            # kyZ (#192): i campi mercato forniti da OGNI riga multi (`supplied`) contano come
            # presenti — così un MultiSelection che riempie `SelectionName` non fa fail-closed qui.
            return PipelineResult(MARKET_MAPPING_MISSING, row, list(res.missing_required),
                                  warnings=warnings)

    # Identificazione precisa dal dizionario Betfair locale (PR-P12): dopo le mappature
    # a nomi, prova a riempire EventId/MarketId/SelectionId dalla catena evento→mercato→
    # selezione del dizionario, ristretta allo sport del parser. Additiva/fail-open/NON
    # distruttiva (vedi `_resolve_ids_into`): la logica è condivisa con le righe multi.
    row = _resolve_ids_into(row, sport=getattr(defn, "sport", ""), id_resolver=id_resolver)

    status, detail = validator.validate(row, mode, require_price)
    return PipelineResult(status, row, list(res.missing_required), detail, warnings=warnings)


# ── Output multi-riga (#192): un messaggio → più righe CSV ────────────────────

# Override colonna-CSV ← attributo della riga multi. Un valore vuoto eredita dalla riga base.
_MULTI_OVERRIDE = (
    ("MarketType", "market_type"), ("MarketName", "market_name"),
    ("SelectionName", "selection_name"), ("Price", "price"),
    ("MinPrice", "min_price"), ("MaxPrice", "max_price"),
    ("BetType", "bet_type"), ("Points", "points"), ("Handicap", "handicap"),
)

# Stati del gate base che impediscono di derivare righe multi: la riga base non è abbastanza
# completa/coerente da fornire i campi comuni (evento, provider, handicap, mappature) → si
# propaga la base (fail-closed: nessuna riga inventata).
_BASE_BLOCKING = (NOT_READY, INVALID_MISSING_PROVIDER, INVALID_HANDICAP,
                  MAPPING_MISSING, MARKET_MAPPING_MISSING)

# Stati bloccanti della base che le righe multi POSSONO risolvere completando un campo (kyZ #192):
# `NOT_READY` (obbligatorio della regola mancante) e `MARKET_MAPPING_MISSING` (mercato assente,
# nessuna frase combacia). Solo per questi si ri-valuta la base trattando come presenti i campi
# forniti da OGNI riga multi. Gli altri (`INVALID_MISSING_PROVIDER`/`INVALID_HANDICAP`/
# `MAPPING_MISSING`) restano fail-closed: un provider/handicap/evento mancante NON è colmabile
# da una riga multi.
_MULTI_RESOLVABLE = (NOT_READY, MARKET_MAPPING_MISSING)


# #325/#341: l'estrazione per-riga dinamica dei punteggi vale SOLO per i mercati Correct Score
# full-time e primo tempo — gli unici che elencano risultati «N - N» — perché `extract_scores`
# riconosce solo quella forma. Gating deliberato e fail-closed: i campi `start_after`/`end_before`
# su una `MultiRowRule` esistevano già prima di #325 (docstring base: «conservati per una futura
# estrazione per-riga»), quindi un JSON legacy POTREBBE avere una MultiSelection con `selection_name`
# vuoto + delimitatori residui su un mercato NON-punteggio: senza questo gate diventerebbe dinamica e
# moltiplicherebbe UNA riga fissa (che ereditava il SelectionName base) in N righe/scommesse estratte
# → possibili scommesse multiple non volute (Fable #341). Con il gate, quel caso resta una riga FISSA.
_DYNAMIC_SCORE_MARKETS = frozenset({"CORRECT_SCORE", "HALF_TIME_SCORE"})


def _effective_market(base_row: dict, rule) -> str:
    """MarketType effettivo di una riga selezione: l'override della regola se presente, altrimenti
    quello ereditato dalla riga base."""
    return (str(getattr(rule, "market_type", "") or "").strip()
            or str(base_row.get("MarketType", "") or "").strip())


def _is_dynamic_selection(rule, market_type: str) -> bool:
    """#325: una regola SELEZIONE è **dinamica** se NON ha un `selection_name` fisso ma ha un
    delimitatore di estrazione (`start_after`/`end_before`) **e** il mercato effettivo è un
    mercato-punteggio **canonico** (`_DYNAMIC_SCORE_MARKETS`, confronto esatto): il `SelectionName`
    di ogni riga viene estratto dal messaggio (lista di risultati esatti). Detection **stretta** —
    con un `selection_name` fisso, senza delimitatori, o su un mercato non-punteggio/non-canonico,
    resta il percorso #192 a riga fissa invariato (nessuna moltiplicazione di righe su config legacy).
    Il confronto è **esatto** (niente `.upper()`): un `MarketType` non canonico (es. «correct_score»
    minuscolo da JSON legacy) NON attiva l'estrazione, così le righe dinamiche emettono **solo**
    MarketType canonici che XTrader/Betfair riconoscono — evita di scrivere un mercato non canonico
    che verrebbe rifiutato o mappato male (Fugu #341). Fail-closed."""
    if str(market_type or "").strip() not in _DYNAMIC_SCORE_MARKETS:
        return False
    return (not str(getattr(rule, "selection_name", "") or "").strip()
            and bool(str(getattr(rule, "start_after", "") or "").strip()
                     or str(getattr(rule, "end_before", "") or "").strip()))


def _rule_supplies(rule, col: str, attr: str, *, from_selection: bool, market_type: str = "") -> bool:
    """`True` se `rule` garantisce la colonna `col` su OGNI riga che genera: attributo non vuoto,
    OPPURE — per `SelectionName` — è una regola SELEZIONE dinamica (#325), che fornisce il
    `SelectionName` via estrazione per-riga anche con l'attributo `selection_name` vuoto.

    `from_selection` deve essere `True` SOLO per le regole della lista SELEZIONI: il caso speciale
    `SelectionName` via estrazione dinamica vale unicamente per le selezioni. Una regola MERCATO
    ha `selection_name` vuoto per natura (è una riga-mercato) e — poiché `start_after`/`end_before`
    sono campi condivisi da `MultiRowRule` e non validati per i mercati — potrebbe averli valorizzati
    (JSON residuo/misconfig): senza questo vincolo verrebbe scambiata per selezione dinamica e
    «fornirebbe» falsamente `SelectionName`, rilassando a torto il gate base (CodeRabbit #341). I
    suoi row non riempiono mai `SelectionName` via estrazione, quindi non lo fornisce."""
    if str(getattr(rule, attr, "") or "").strip():
        return True
    return (col == "SelectionName" and from_selection
            and _is_dynamic_selection(rule, market_type))


def _multi_supplied_cols(markets, selections, base_market: str = "") -> "frozenset":
    """Colonne CSV che OGNI riga multi generata riempirà con un valore non vuoto (kyZ #192):
    una colonna è «fornita» solo se **tutte** le regole attive (mercati + selezioni) la
    garantiscono — così è assicurata su OGNI riga derivata, non solo su alcune. Una regola
    SELEZIONE dinamica (#325) garantisce `SelectionName` via estrazione anche con l'attributo
    vuoto (`_rule_supplies`), così la base non resta bloccata su un `SelectionName` obbligatorio
    che la lista estratta riempirà. Il credito `SelectionName` via estrazione dinamica è ristretto
    alle sole regole SELEZIONE (`from_selection=True`) e ai soli mercati-punteggio (il mercato
    effettivo della selezione = suo override o `base_market`): una regola MERCATO o una selezione su
    mercato non-punteggio non può rilassare il gate base su `SelectionName` (CodeRabbit/Fable #341).
    Con entrambe le liste vuote → insieme vuoto."""
    markets = list(markets or [])
    selections = list(selections or [])
    if not markets and not selections:
        return frozenset()
    return frozenset(
        col for col, attr in _MULTI_OVERRIDE
        if all(_rule_supplies(r, col, attr, from_selection=False) for r in markets)
        and all(_rule_supplies(r, col, attr, from_selection=True,
                               market_type=_effective_market({"MarketType": base_market}, r))
                for r in selections))


def _apply_multi_rule(base_row: dict, rule) -> dict:
    """Deriva una riga CSV dalla riga BASE applicando gli override NON VUOTI della regola
    multi (#192); i campi vuoti ereditano dalla base. La riga risultante è normalizzata al
    contratto (virgola→punto su quote/Handicap/Points, BetType maiuscolo, Handicap default)."""
    row = dict(base_row)
    clear_ids = False
    for col, attr in _MULTI_OVERRIDE:
        val = getattr(rule, attr, "")
        if str(val).strip():
            row[col] = val
            # Identità del mercato/selezione cambiata: gli ID risolti per la riga BASE (da regola
            # ID/BOTH o dal dizionario Betfair) non valgono più → vanno azzerati, altrimenti la riga
            # nominerebbe un mercato/selezione ma lo identificherebbe con l'ID di un altro (CSV
            # incoerente, bet sbagliato in ID/BOTH). Stessa regola del market-mapping (Codex/CodeRabbit).
            if col in ("MarketType", "MarketName", "SelectionName", "Handicap"):
                clear_ids = True
    if clear_ids:
        row["MarketId"] = ""
        row["SelectionId"] = ""
    return _normalize_to_contract(row, str(row.get("Provider", "") or ""))


def _validated_multi_row(base_row: dict, rule, mode: str, require_price: bool,
                         *, sport: str = "", id_resolver=None) -> PipelineResult:
    """Costruisce e VALIDA una singola riga multi derivata dalla base."""
    row = _apply_multi_rule(base_row, rule)
    # Handicap della riga DERIVATA (#192, Codex): l'override multi (`handicap`) NON passa dal gate
    # `INVALID_HANDICAP` della base (che vede l'Handicap base, non l'override) e `validator.validate`
    # non controlla l'Handicap → un override malformato (es. "abc") raggiungerebbe il CSV. Si applica
    # QUI lo stesso controllo di formato della base, così ogni riga derivata è fail-closed come il
    # single-row (vale sia col rilassamento kyZ sia nel percorso multi normale).
    hcap = str(row.get("Handicap", "")).strip()
    if hcap and not _HANDICAP_RE.match(hcap):
        return PipelineResult(INVALID_HANDICAP, row, [])
    # Arricchimento ID PER RIGA DERIVATA (#192, follow-up review #290): `_apply_multi_rule` azzera
    # gli ID quando la riga multi cambia mercato/selezione; senza ri-risolvere, un MultiSelection in
    # ID_ONLY resterebbe senza ID → non piazzabile. Si risolvono gli ID per la selezione/mercato di
    # QUESTA riga (additivo/fail-open/non-distruttivo, stessa logica della base).
    row = _resolve_ids_into(row, sport=sport, id_resolver=id_resolver)
    status, detail = validator.validate(row, mode, require_price)
    # P3-12 #76: SOLO il detail di INVALID_MISSING_FIELDS è un elenco di campi
    # mancanti. Le altre tuple/liste (es. le colonne offendenti di
    # INVALID_PRICE_BOUNDS: presenti ma incoerenti) NON vanno in `missing_required`,
    # o la GUI/l'assistente direbbero «mancanti: MinPrice» per un limite che c'è
    # (stessa regola già applicata dal ramo single-row di `test_verdict`).
    missing = (list(detail) if status == validator.INVALID_MISSING_FIELDS
               and isinstance(detail, (list, tuple)) else [])
    return PipelineResult(status, row, missing, detail)


def _selection_rows(base_row: dict, rule, text: str, mode: str, require_price: bool,
                    *, sport: str = "", id_resolver=None) -> "list[PipelineResult]":
    """Righe generate da UNA regola SELEZIONE (#192 + #325).

    - Regola **fissa** (`selection_name` impostato, o mercato non-punteggio) → UNA riga, come sempre.
    - Regola **dinamica** (#325: `selection_name` vuoto + delimitatori **su mercato-punteggio**) →
      estrae la lista dei risultati esatti dal messaggio (`extract_scores`, normalizzati a «N - N») e
      genera UNA riga per punteggio, ognuna con `selection_name` = quel punteggio. Ogni riga passa dal
      solito `_validated_multi_row` (azzeramento+ri-risoluzione ID per la selezione, validazione
      per-riga fail-closed): un punteggio malformato non arriva qui (non matcha il pattern), e una
      riga non valida non blocca le altre. Lista vuota → NESSUNA riga (fail-closed)."""
    if not _is_dynamic_selection(rule, _effective_market(base_row, rule)):
        return [_validated_multi_row(base_row, rule, mode, require_price,
                                     sport=sport, id_resolver=id_resolver)]
    rows = []
    for score in extract_scores(text, rule.start_after, rule.end_before):
        dyn = replace(rule, selection_name=score)   # copia con il SelectionName estratto
        rows.append(_validated_multi_row(base_row, dyn, mode, require_price,
                                         sport=sport, id_resolver=id_resolver))
    return rows


def build_validated_rows(defn: CustomParserDef, text: str, **kwargs) -> "list[PipelineResult]":
    """Variante multi-riga (#192) di `build_validated_row`: ritorna una LISTA di
    `PipelineResult`, una per riga generata. Accetta gli stessi keyword di
    `build_validated_row` (`provider`, `mode`, `require_price`, mappature, `id_resolver`).

    - MultiMarket/MultiSelection disattivati (o senza righe attive) → ``[base]`` — IDENTICO al
      single-row di sempre (retro-compatibile);
    - altrimenti la riga base (già arricchita da mappature nomi/mercati e dizionario) fornisce
      i campi comuni ed OGNI regola MultiMarket/MultiSelection genera UNA riga distinta, validata
      singolarmente (una riga non valida non blocca le altre);
    - **kyZ (#192):** un campo obbligatorio/mercato della BASE che sarà riempito dalle righe multi
      (es. `SelectionName` in un MultiSelection) NON deve bloccare la generazione: quando l'output
      multi è attivo e la base è bloccata per un motivo **colmabile** (`NOT_READY` o
      `MARKET_MAPPING_MISSING`), si RI-valuta la base passando `multi_supplied` = le colonne che
      OGNI riga multi riempie, trattate come presenti dai soli gate strutturali. La base passa così
      per mappature nomi/mercati ed enrichment ID e ogni riga derivata è validata singolarmente.
      Gli ALTRI gate (provider / handicap / mappatura nomi) e gli obbligatori NON coperti dal multi
      restano fail-closed (``[base]``);
    - MultiMarket e MultiSelection insieme → righe SEPARATE (prima i mercati, poi le selezioni
      sul mercato base), MAI il prodotto cartesiano (vedi `both_multi_active`).
    """
    # `multi_supplied` è un parametro INTERNO: si SCARTA qualsiasi valore passato dal chiamante
    # (CodeRabbit, safety) così NON può rilassare i gate della PRIMA valutazione con colonne
    # arbitrarie — sarà calcolato QUI sotto solo dalle regole multi realmente attive. Senza questo
    # strip, un chiamante potrebbe far passare un obbligatorio che il validator non ri-controlla.
    row_kwargs = dict(kwargs)
    row_kwargs.pop("multi_supplied", None)
    base = build_validated_row(defn, text, **row_kwargs)
    markets = defn.active_multi_markets()
    selections = defn.active_multi_selections()
    if not markets and not selections:
        return [base]
    # kyZ (#192): se la base è bloccata per un motivo che le righe multi possono colmare
    # (`NOT_READY`/`MARKET_MAPPING_MISSING`), si RI-valuta trattando come presenti SOLO le colonne
    # fornite da OGNI riga generata (`multi_supplied`) — così un obbligatorio NON coperto resta
    # bloccante (Codex P1) e la mappatura mercati non fa un falso fail-closed (Codex/CodeRabbit).
    if base.status in _MULTI_RESOLVABLE:
        supplied = set(_multi_supplied_cols(markets, selections,
                                            str(base.row.get("MarketType", "") or "")))
        # ID_ONLY con dizionario (Codex, follow-up #290): un parser creato dalla GUI marca
        # `MarketId`/`SelectionId` come obbligatori per la modalità; se sono lasciati vuoti perché
        # il resolver li riempie PER RIGA, la base sarebbe `NOT_READY` e la generazione non
        # partirebbe mai. Quando c'è un `id_resolver` + sport (cioè `_resolve_ids_into` girerà su
        # ogni riga derivata) si trattano gli ID come "forniti" per il solo gate della base: ogni
        # riga è comunque ri-validata dopo la risoluzione (senza ID risolti → INVALID in ID_ONLY),
        # quindi resta fail-closed PER RIGA come per kyZ.
        # SOLO in ID_ONLY (Codex): lì il validator ri-controlla MarketId/SelectionId → se il resolver
        # manca, la riga resta INVALID (fail-closed). In NAME_ONLY/BOTH il validator NON esige gli ID,
        # quindi rilassare un ID obbligatorio lascerebbe passare una riga senza ID che il parser aveva
        # dichiarato incompleta → NON si rilassa (resta bloccante).
        # Solo i campi che il validator ID_ONLY RI-CONTROLLA (`MarketId`/`SelectionId`) — NON
        # `EventId` (Codex): il validator ID_ONLY non esige `EventId`, quindi rilassarlo lascerebbe
        # passare una riga con `EventId` obbligatorio vuoto (dichiarato incompleto dal parser).
        _relax_mode = recognition.normalize_mode(kwargs.get("mode", recognition.DEFAULT_MODE))
        if (_relax_mode == recognition.ID_ONLY
                and kwargs.get("id_resolver") is not None and getattr(defn, "sport", "")):
            supplied |= {"MarketId", "SelectionId"}
        if supplied:
            retry_kwargs = dict(row_kwargs)     # `row_kwargs`: senza il `multi_supplied` del chiamante
            retry_kwargs["multi_supplied"] = frozenset(supplied)
            base = build_validated_row(defn, text, **retry_kwargs)
    if base.status in _BASE_BLOCKING:
        # P3-11 #76: la generazione multi non parte — si ritorna la BASE bloccata,
        # marcata come tale così l'anteprima non la etichetta «market»/«selection»
        # (che devierebbe il verdetto sul ramo multi, perdendo i campi «mancanti:»).
        base.base_fallback = True
        return [base]
    mode = kwargs.get("mode", recognition.DEFAULT_MODE)
    require_price = kwargs.get("require_price", True)
    # Provenienza per l'arricchimento ID per-riga (#192, follow-up #290): sport del parser +
    # resolver dai kwargs, così ogni riga derivata ri-risolve gli ID per la propria selezione.
    id_resolver = kwargs.get("id_resolver")
    sport = getattr(defn, "sport", "")
    out = [_validated_multi_row(base.row, r, mode, require_price, sport=sport,
                                id_resolver=id_resolver) for r in markets]
    # Selezioni: una regola fissa → una riga; una regola DINAMICA (#325) → una riga per risultato
    # esatto estratto dal messaggio. `_selection_rows` gestisce entrambi i casi.
    for r in selections:
        out += _selection_rows(base.row, r, text, mode, require_price,
                               sport=sport, id_resolver=id_resolver)
    if not out:
        # #325: una regola SELEZIONE dinamica che non estrae NESSUN risultato (lista vuota) e
        # nessun'altra riga → non si piazza la base (avrebbe SelectionName vuoto): un unico esito
        # NON piazzabile `NOT_READY` con un `detail` esplicito (per la diagnostica/GUI, review #341).
        # Evita anche un `[]` che romperebbe `resolve_row` (`results[0]`).
        return [PipelineResult(NOT_READY, base.row, [], "no_scores_extracted",
                               warnings=list(base.warnings))]
    # Issue #38: l'avviso di riformattazione EventName è a livello di MESSAGGIO (l'EventName base è
    # condiviso da tutte le righe derivate) → lo si riporta UNA sola volta, sulla prima riga, così
    # preview/log lo mostrano senza duplicarlo per ogni riga multi.
    if base.warnings and out:
        out[0].warnings = list(base.warnings)
    return out


def both_multi_active(defn: CustomParserDef) -> bool:
    """`True` se MultiMarket E MultiSelection hanno entrambi righe attive: la GUI/validazione
    deve avvisare che verranno generate righe SEPARATE, non combinazioni automatiche (#192)."""
    return bool(defn.active_multi_markets()) and bool(defn.active_multi_selections())


def is_placeable(defn: CustomParserDef, text: str, **kwargs) -> bool:
    """Scorciatoia: True se il messaggio produce una riga piazzabile."""
    return build_validated_row(defn, text, **kwargs).placeable
