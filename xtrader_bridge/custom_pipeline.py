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
    numbers_re,
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
_HANDICAP_RE = re.compile(r"^" + numbers_re.SIGNED_DECIMAL + r"$")   # frammento condiviso (L4)

# Colonne quota: il contratto XTrader usa il punto decimale (es. "1.85").
_PRICE_COLS = ("Price", "MinPrice", "MaxPrice")


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
            out[col] = _decimal_sep_to_point(v)
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
                        market_mapping_profiles=None,
                        id_resolver=None,
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
    if defn.name_mapping_profiles:
        sep = (defn.team_separator or "").strip() or _DEFAULT_TEAM_SEPARATOR
        # Sport del parser (PR-P10): restringe la mappatura nomi alle righe di quello sport
        # o agnostiche, così un nome non viene tradotto con la voce di uno sport diverso.
        # entity_type (#178 §2, Codex P1): i partecipanti di un evento sono squadre/giocatori
        # → si usano SOLO le righe participant/team/player (più le agnostiche), escludendo le
        # righe competition/market/selection con alias che collide (no EventName sbagliato).
        mapped = name_mapping_store.resolve_event_name(
            row.get("EventName", ""), sep, name_mapping_profiles or [],
            sport=getattr(defn, "sport", ""),
            entity_type=name_mapping_store.PARTICIPANT_ENTITY_TYPES)
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
        elif not _row_has_market(row, mode, supplied=supplied):
            # status "none": nessuna frase combacia. Si tengono i valori della regola-colonna
            # SE costituiscono già un mercato per la modalità; altrimenti il mercato resterebbe
            # assente → fail-closed (niente mercato inventato), invece di lasciar passare una
            # riga senza mercato. Controllo mode-aware per non scartare per errore una riga ID.
            # kyZ (#192): i campi mercato forniti da OGNI riga multi (`supplied`) contano come
            # presenti — così un MultiSelection che riempie `SelectionName` non fa fail-closed qui.
            return PipelineResult(MARKET_MAPPING_MISSING, row, list(res.missing_required))

    # Identificazione precisa dal dizionario Betfair locale (PR-P12): dopo le mappature
    # a nomi, prova a riempire EventId/MarketId/SelectionId dalla catena evento→mercato→
    # selezione del dizionario, ristretta allo sport del parser. È **additiva e fail-open**:
    # se il dizionario non trova un match univoco la riga resta a nomi (fallback nomi), non
    # si blocca il segnale; un errore di lettura non deve mai interrompere il flusso.
    if id_resolver is not None and getattr(defn, "sport", ""):
        try:
            ids = id_resolver.resolve_ids(
                sport=defn.sport,
                event_name=row.get("EventName", ""),
                market_type=row.get("MarketType", ""),
                market_name=row.get("MarketName", ""),
                selection_name=row.get("SelectionName", ""),
                handicap=row.get("Handicap", ""))
        except Exception:   # noqa: BLE001 — risoluzione best-effort: niente blocco del flusso
            ids = None
        if ids:
            # Additivo e NON distruttivo (Codex P1): se il parser ha già fornito un ID
            # esplicito (ID/BOTH) NON lo si sovrascrive con quello del dizionario — un
            # dizionario stantio/diverso scriverebbe un mercato/selezione sbagliato. Se un
            # ID del parser è in CONFLITTO con la tripla risolta, si scarta del tutto
            # l'arricchimento (resta la riga del parser); altrimenti si riempiono SOLO i
            # campi ID vuoti con la tripla coerente del dizionario.
            _keys = ("EventId", "MarketId", "SelectionId")
            _conflict = any(
                str(row.get(_k, "")).strip()
                and ids.get(_k) and str(row.get(_k, "")).strip() != str(ids[_k])
                for _k in _keys)
            if not _conflict:
                row = dict(row)
                for _k in _keys:
                    _v = ids.get(_k)
                    if _v and not str(row.get(_k, "")).strip():
                        row[_k] = str(_v)

    status, detail = validator.validate(row, mode, require_price)
    return PipelineResult(status, row, list(res.missing_required), detail)


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


def _multi_supplied_cols(rules) -> "frozenset":
    """Colonne CSV che OGNI riga multi generata riempirà con un valore non vuoto (kyZ #192):
    una colonna è «fornita» solo se **tutte** le regole attive (mercati + selezioni) hanno il
    corrispondente attributo non vuoto — così è garantita su OGNI riga derivata, non solo su
    alcune. Serve ai gate strutturali della base per non bloccare un campo che il multi completerà.
    Con `rules` vuoto → insieme vuoto (nessuna garanzia)."""
    rules = list(rules or [])
    if not rules:
        return frozenset()
    return frozenset(
        col for col, attr in _MULTI_OVERRIDE
        if all(str(getattr(r, attr, "") or "").strip() for r in rules))


def _apply_multi_rule(base_row: dict, rule) -> dict:
    """Deriva una riga CSV dalla riga BASE applicando gli override NON VUOTI della regola
    multi (#192); i campi vuoti ereditano dalla base. La riga risultante è normalizzata al
    contratto (virgola→punto sulle quote, BetType maiuscolo, Handicap default)."""
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


def _validated_multi_row(base_row: dict, rule, mode: str, require_price: bool) -> PipelineResult:
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
    status, detail = validator.validate(row, mode, require_price)
    missing = list(detail) if isinstance(detail, (list, tuple)) else []
    return PipelineResult(status, row, missing, detail)


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
        supplied = _multi_supplied_cols(list(markets) + list(selections))
        if supplied:
            retry_kwargs = dict(row_kwargs)     # `row_kwargs`: senza il `multi_supplied` del chiamante
            retry_kwargs["multi_supplied"] = supplied
            base = build_validated_row(defn, text, **retry_kwargs)
    if base.status in _BASE_BLOCKING:
        return [base]
    mode = kwargs.get("mode", recognition.DEFAULT_MODE)
    require_price = kwargs.get("require_price", True)
    out = [_validated_multi_row(base.row, r, mode, require_price) for r in markets]
    out += [_validated_multi_row(base.row, r, mode, require_price) for r in selections]
    return out


def both_multi_active(defn: CustomParserDef) -> bool:
    """`True` se MultiMarket E MultiSelection hanno entrambi righe attive: la GUI/validazione
    deve avvisare che verranno generate righe SEPARATE, non combinazioni automatiche (#192)."""
    return bool(defn.active_multi_markets()) and bool(defn.active_multi_selections())


def is_placeable(defn: CustomParserDef, text: str, **kwargs) -> bool:
    """Scorciatoia: True se il messaggio produce una riga piazzabile."""
    return build_validated_row(defn, text, **kwargs).placeable
