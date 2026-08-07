"""CP-08b: diagnostica del Parser Personalizzato per "Prova messaggio".

Spiega, **campo per campo**, perché un messaggio produce (o no) una riga
piazzabile per XTrader, seguendo la stessa catena del runtime:

    estrazione (CP-02) → trasformazione (CP-05) → value-map (CP-03) → validazione (PR-10)

Quando il builder dice solo "Non pronto" non si capisce QUALE campo ha fallito né
PERCHÉ; questo modulo produce un esito strutturato (codici errore per colonna) di
cui la GUI (`custom_parser_gui`) è solo una vista. Logica pura, testabile in CI:
nessun widget, nessun I/O nascosto oltre al registro value-map condiviso del pipeline.
"""

from dataclasses import dataclass, field

import unicodedata

from . import custom_pipeline, recognition, transforms, validator, value_maps
from .custom_parser import CustomParserDef
from .custom_parser_engine import (
    EXTRACT_END_NOT_FOUND,
    EXTRACT_START_NOT_FOUND,
    extract_value_traced,
    failed_conditions,
    matches_message,
)

# ── Codici di stato per campo ───────────────────────────────────────────────
OK = "OK"                                # valore finale presente e valido
EMPTY_OPTIONAL = "EMPTY_OPTIONAL"        # vuoto ma non obbligatorio → non blocca
START_NOT_FOUND = "START_NOT_FOUND"      # "Inizia dopo" non trovato nel messaggio
END_NOT_FOUND = "END_NOT_FOUND"          # "Finisce prima" non trovato dopo l'inizio
REQUIRED_EMPTY = "REQUIRED_EMPTY"        # obbligatorio ma vuoto (nessuna estrazione)
TRANSFORM_FAILED = "TRANSFORM_FAILED"    # la trasformazione ha svuotato il valore
VALUE_MAP_MISS = "VALUE_MAP_MISS"        # la value-map non ha trovato il valore
INVALID_PRICE = "INVALID_PRICE"          # Price non numerico o ≤ 1.0
INVALID_BETTYPE = "INVALID_BETTYPE"      # BetType non è un lato valido (PUNTA/BANCA/BACK/LAY)
INVALID_HANDICAP = "INVALID_HANDICAP"    # Handicap valorizzato ma non numerico
INVALID_POINTS = "INVALID_POINTS"        # Points valorizzato ma non un numero > 0
INVALID_PRICE_BOUNDS = "INVALID_PRICE_BOUNDS"  # Min/Max incoerenti (invertiti o escludono Price)
MISSING_PROVIDER = "MISSING_PROVIDER"    # Provider assente (contratto)
MODE_REQUIRED_MISSING = "MODE_REQUIRED_MISSING"  # campo richiesto dalla Modalità mancante
MAPPING_MISSING = "MAPPING_MISSING"      # EventName non traducibile coi profili di mappatura nomi
MARKET_MAPPING_MISSING = "MARKET_MAPPING_MISSING"  # nessuna frase combacia e nessun mercato dalle regole
# #282 A2: causa OPPOSTA al fratello — frasi in conflitto, non frasi assenti. Codice distinto
# perché il rimedio è opposto: qui si TOGLIE una voce, lì se ne aggiunge una.
MARKET_MAPPING_AMBIGUOUS = "MARKET_MAPPING_AMBIGUOUS"
# Separatore squadre impostato ma non trovato nell'EventName (#182 PR S). DISTINTO da
# MAPPING_MISSING: lì manca la traduzione (dizionario), qui manca lo split (separatore sbagliato).
TEAM_SEPARATOR_NOT_FOUND = "TEAM_SEPARATOR_NOT_FOUND"

# ── Codici a livello messaggio ──────────────────────────────────────────────
NO_CONTENT_MATCH = "NO_CONTENT_MATCH"    # niente estratto: solo valori fissi / nessun match
# Condizioni di gate non soddisfatte (ordine proprietario 2026-08-04). DISTINTO da
# NO_CONTENT_MATCH: lì non è stato estratto nulla (delimitatori da correggere), qui
# l'estrazione è RIUSCITA ma il gate ha fermato il messaggio (condizione da correggere).
# Confonderli mandava a cercare l'errore nei delimitatori, cioè nel posto sbagliato.
# È un codice di sola DIAGNOSI: il runtime scarta gli stessi messaggi di prima.
CONDITIONS_NOT_MET = "CONDITIONS_NOT_MET"

_OK_CODES = (OK, EMPTY_OPTIONAL)

# Spiegazioni leggibili dei codici (per il report).
_EXPLAIN = {
    OK: "",
    EMPTY_OPTIONAL: "vuoto ma facoltativo",
    START_NOT_FOUND: "delimitatore «Inizia dopo» non trovato nel messaggio",
    END_NOT_FOUND: "delimitatore «Finisce prima» non trovato dopo l'inizio",
    REQUIRED_EMPTY: "obbligatorio ma vuoto (nessuna estrazione/valore)",
    TRANSFORM_FAILED: "la trasformazione non ha prodotto un valore",
    VALUE_MAP_MISS: "value-map: valore non presente nel dizionario",
    INVALID_PRICE: "quota non numerica o ≤ 1.0",
    INVALID_BETTYPE: "BetType non è un lato valido (PUNTA/BANCA/BACK/LAY)",
    INVALID_HANDICAP: "Handicap valorizzato ma non numerico",
    INVALID_POINTS: "Points valorizzato ma non un numero positivo",
    INVALID_PRICE_BOUNDS: "limiti di prezzo incoerenti (Min > Max o intervallo che esclude Price)",
    MISSING_PROVIDER: "Provider mancante (richiesto dal contratto)",
    MODE_REQUIRED_MISSING: "campo richiesto dalla Modalità di riconoscimento",
    # Tre cause, non due (B21 PR-P #194): oltre al separatore e alla squadra assente c'è ora
    # l'alias AMBIGUO — la squadra è nei profili, ma punta a ≥2 nomi Betfair diversi che il
    # parser non sa distinguere. Va nominata, altrimenti l'utente legge «non nei profili» e va
    # ad aggiungere una riga che c'è già, peggiorando il conflitto invece di risolverlo. Il
    # dettaglio su QUALE alias e su cosa fare è nell'avviso al load (`ambiguous_alias_warnings`).
    MAPPING_MISSING: ("EventName non traducibile: separatore non trovato, squadra non nei profili "
                      "di mappatura nomi, oppure alias ambiguo (stessa squadra su ≥2 nomi Betfair "
                      "diversi non distinguibili dal parser)"),
    # #282 A2 — due voci, non una: le cause erano opposte e i rimedi pure. Il testo del
    # fratello NON nomina più l'ambiguità, altrimenti resterebbe la metà falsa che manda a
    # cercare un conflitto che non c'è.
    MARKET_MAPPING_MISSING: ("mercato non risolvibile: nessuna frase combacia e nessun mercato "
                             "dalle regole-colonna"),
    # Dice cosa FARE, ed è l'azione opposta al fratello: qui non manca una voce, ce n'è una di
    # troppo. `_motivo_stato` accoda le coppie in conflitto, cioè le righe da correggere.
    MARKET_MAPPING_AMBIGUOUS: ("mercato ambiguo: più frasi del dizionario mercati combaciano "
                               "indicando coppie mercato/selezione diverse — togli o rendi "
                               "distinguibile una delle voci in conflitto"),
    # #182 PR S — il testo dice COSA FARE, non solo cosa è successo: il campo da correggere è
    # nominato per esteso, perché è l'unica azione che sblocca il messaggio. Senza questa voce
    # lo scarto sarebbe arrivato a schermo come sigla, cioè silenzioso nei fatti.
    TEAM_SEPARATOR_NOT_FOUND: ("separatore squadre impostato ma non trovato nel nome evento: "
                               "nessuna riga scritta — correggi il campo «Separatore squadre» "
                               "del parser (o svuotalo per lasciare il nome invariato)"),
    NO_CONTENT_MATCH: "nessun contenuto estratto dal messaggio (solo valori fissi / nessun match)",
    # Spiegazione generica: `diagnose` la sostituisce con quella che NOMINA le condizioni
    # fallite, che è l'unica azionabile. Questa resta per i chiamanti che hanno solo il codice.
    CONDITIONS_NOT_MET: ("le condizioni di gate non sono soddisfatte: il messaggio è stato "
                         "letto correttamente ma il parser non scatta"),
}


# Stati a livello di RIGA (`custom_pipeline`/`validator`): finora avevano una spiegazione
# solo nei loro gemelli per-campo qui sopra, quindi arrivavano al verdetto come sigle nude.
# Dove il gemello esiste si RIUSA la sua frase (regola 3: due copie corrette oggi sono due
# copie divergenti domani); dove non esiste la frase è scritta qui, e risponde alla domanda
# che si pone chi legge — «quale colonna, e dove la prendo».
_EXPLAIN.update({
    custom_pipeline.NOT_READY: ("manca almeno un campo obbligatorio del parser "
                                "(le colonne con «Obblig.» spuntato)"),
    custom_pipeline.INVALID_MISSING_PROVIDER: _EXPLAIN[MISSING_PROVIDER],
    custom_pipeline.MAPPING_MISSING: _EXPLAIN[MAPPING_MISSING],
    custom_pipeline.MARKET_MAPPING_MISSING: _EXPLAIN[MARKET_MAPPING_MISSING],
    custom_pipeline.MARKET_MAPPING_AMBIGUOUS: _EXPLAIN[MARKET_MAPPING_AMBIGUOUS],
    validator.INVALID_MISSING_PRICE: "quota richiesta dal parser ma assente nel messaggio",
    validator.INVALID_MISSING_FIELDS: (
        "mancano i campi di riconoscimento richiesti dalla Modalità: gli ID si prendono dal "
        "«Catalogo Betfair», i nomi si estraggono dal messaggio"),
})


def explain(code: str) -> str:
    """Spiegazione leggibile di un codice di stato/errore (stringa vuota se OK)."""
    return _EXPLAIN.get(code, code)


@dataclass
class FieldDiagnostic:
    """Esito della catena per UNA colonna."""

    target: str
    raw: str = ""                 # valore grezzo estratto (CP-02)
    after_transform: str = ""     # dopo la trasformazione (CP-05)
    final: str = ""               # dopo la value-map (CP-03) — valore XTrader
    required: bool = False
    error: str = OK               # uno dei codici sopra
    # Nomi degli stadi applicati alla colonna: servono al motivo azionabile
    # (`motivi_campi_mancanti`) per dire CHI ha svuotato il campo, non solo che è vuoto.
    transform: str = ""
    value_map: str = ""

    @property
    def ok(self) -> bool:
        return self.error in _OK_CODES


@dataclass
class Diagnosis:
    """Esito complessivo della diagnostica."""

    placeable: bool
    status: str                                  # status del pipeline (VALID/INVALID_*/NOT_READY)
    fields: "list[FieldDiagnostic]" = field(default_factory=list)
    message_error: str = ""                      # NO_CONTENT_MATCH, CONDITIONS_NOT_MET o ""
    # Motivo azionabile dello STATO (non dei singoli campi): la frase che nomina le
    # condizioni fallite, o la spiegazione del codice. Vuoto = nessun motivo specifico.
    # Calcolato in `diagnose`, dove `defn` e testo sono disponibili; letto da `motivo_stato`.
    status_reason: str = ""


def _classify_extraction(rule, raw, reason, after, final) -> str:
    """Codice per UN campo guardando SOLO estrazione→transform→value-map.
    Gli errori del validator (prezzo/bettype/modalità) sono sovrapposti dopo."""
    if final != "":
        return OK
    # final vuoto → individua lo stadio che l'ha svuotato (dal più "a monte").
    if reason == EXTRACT_START_NOT_FOUND:
        return START_NOT_FOUND
    if reason == EXTRACT_END_NOT_FOUND:
        return END_NOT_FOUND
    if rule.transform and raw != "" and after == "":
        return TRANSFORM_FAILED
    if rule.value_map and after != "" and final == "":
        return VALUE_MAP_MISS
    return REQUIRED_EMPTY if rule.required else EMPTY_OPTIONAL


def _field_diag(rule, text, registry) -> FieldDiagnostic:
    raw, reason = extract_value_traced(text, rule)
    after = transforms.apply(raw, rule.transform) if rule.transform else raw
    final = value_maps.map_value(after, rule.value_map, registry) if rule.value_map else after
    return FieldDiagnostic(
        target=rule.target, raw=raw, after_transform=after, final=final,
        required=bool(rule.required),
        error=_classify_extraction(rule, raw, reason, after, final),
        transform=rule.transform or "", value_map=rule.value_map or "",
    )


def _mark(by_target, fields, target, error, *, required=False) -> None:
    """Imposta/sovrascrive il codice errore su una colonna (la crea se assente:
    es. un campo richiesto dalla Modalità per cui non esiste alcuna regola)."""
    fd = by_target.get(target)
    if fd is None:
        fd = FieldDiagnostic(target=target, required=required, error=error)
        fields.append(fd)
        by_target[target] = fd
    else:
        fd.error = error
        if required:
            fd.required = True


def _mark_mode_required(by_target, fields, col) -> None:
    """Marca `col` come richiesta dalla MODALITÀ ma mancante. Se la colonna ha GIÀ un errore
    di ESTRAZIONE azionabile (START_NOT_FOUND/END_NOT_FOUND/TRANSFORM_FAILED/VALUE_MAP_MISS/
    REQUIRED_EMPTY) lo PRESERVA (solo `required=True`): sostituirlo col generico
    MODE_REQUIRED_MISSING nasconderebbe il motivo utile — es. il delimitatore sbagliato
    (Codex #70). Se la colonna è OK/vuota-facoltativa (o assente) usa MODE_REQUIRED_MISSING."""
    fd = by_target.get(col)
    if fd is not None and fd.error not in _OK_CODES:
        fd.required = True
        return
    _mark(by_target, fields, col, MODE_REQUIRED_MISSING, required=True)


def _overlay_validator(result, by_target, fields) -> None:
    """Sovrappone gli errori del validator/pipeline ai campi. Due parti:

    (A) i gate STRUTTURALI (dallo `status` del pipeline: modalità/prezzo mancante/provider/
        handicap/mappature), e
    (B) gli errori di VALORE per-colonna (BetType/prezzi/Points/limiti), controllati
        INDIPENDENTEMENTE così un messaggio con PIÙ colonne invalide le mostra TUTTE —
        `validator.validate` si ferma al primo errore (short-circuit), la diagnostica no
        (Codex #70): es. `BetType=FAVOR` (ES non ancora supportato) **e** `Price=abc` marca
        entrambe, non solo BetType.

    (B) non cambia il verdetto (`placeable`), solo l'attribuzione per-colonna."""
    status = result.status
    row = result.row

    # (A) Gate strutturali: la riga non è abbastanza completa/coerente per il contratto.
    if status == validator.INVALID_MISSING_FIELDS:
        for col in (result.detail or []):
            _mark_mode_required(by_target, fields, col)
    elif status == validator.INVALID_MISSING_PRICE:
        _mark(by_target, fields, "Price", REQUIRED_EMPTY, required=True)
    elif status == custom_pipeline.INVALID_MISSING_PROVIDER:
        _mark(by_target, fields, "Provider", MISSING_PROVIDER, required=True)
    elif status == custom_pipeline.INVALID_HANDICAP:
        _mark(by_target, fields, "Handicap", INVALID_HANDICAP)
    elif status == custom_pipeline.MAPPING_MISSING:
        _mark(by_target, fields, "EventName", MAPPING_MISSING, required=True)
    elif status == custom_pipeline.TEAM_SEPARATOR_NOT_FOUND:
        # #182 PR S: si marca EventName, la colonna che il separatore avrebbe dovuto
        # riformattare. Motivo dedicato e non MAPPING_MISSING, altrimenti l'utente andrebbe a
        # cercare il problema nel dizionario nomi invece che nel campo «Separatore squadre».
        _mark(by_target, fields, "EventName", TEAM_SEPARATOR_NOT_FOUND, required=True)
    elif status in (custom_pipeline.MARKET_MAPPING_MISSING,
                    custom_pipeline.MARKET_MAPPING_AMBIGUOUS):
        # Il mercato non è risolvibile: segnala su Mercato e Selezione (le due colonne
        # che la mappatura mercati avrebbe dovuto impostare). #282 A2: le due cause sono
        # opposte ma le colonne da marcare sono le stesse — cambia il codice, non il bersaglio.
        codice = (MARKET_MAPPING_AMBIGUOUS
                  if status == custom_pipeline.MARKET_MAPPING_AMBIGUOUS
                  else MARKET_MAPPING_MISSING)
        _mark(by_target, fields, "MarketName", codice, required=True)
        _mark(by_target, fields, "SelectionName", codice, required=True)

    # (B) Errori di VALORE per-colonna, indipendenti dallo short-circuit del validator.
    # Solo su valori NON vuoti (un campo vuoto è spiegato dall'estrazione, non "invalido").
    if (str(row.get("BetType", "")).strip()
            and validator.bettype_status(row.get("BetType", "")) != validator.VALID):
        _mark(by_target, fields, "BetType", INVALID_BETTYPE)
    for col in ("Price", "MinPrice", "MaxPrice"):
        v = str(row.get(col, "")).strip()
        if v and validator.price_status(v) != validator.VALID:
            _mark(by_target, fields, col, INVALID_PRICE)
    if (str(row.get("Points", "")).strip()
            and validator.points_status(row.get("Points", "")) != validator.VALID):
        _mark(by_target, fields, "Points", INVALID_POINTS)
    # Limiti incoerenti: solo se ogni prezzo/limite PRESENTE è già una quota valida (altrimenti
    # è già marcato INVALID_PRICE sopra, ed evita `float()` su valori malformati). Non sovrascrive
    # un errore più specifico già presente sulla colonna.
    if all(validator.price_status(str(row.get(c, "")).strip()) == validator.VALID
           for c in ("Price", "MinPrice", "MaxPrice") if str(row.get(c, "")).strip()):
        for col in validator.price_bounds_offenders(row):
            fd = by_target.get(col)
            if fd is None or fd.error in _OK_CODES:
                _mark(by_target, fields, col, INVALID_PRICE_BOUNDS)


def diagnose(defn: CustomParserDef, text: str, *, value_maps_registry: dict = None,
             provider: str = "", mode: str = recognition.DEFAULT_MODE,
             require_price: bool = True, name_mapping_profiles=None,
             market_mapping_profiles=None, id_resolver=None,
             source_language="") -> Diagnosis:
    """Diagnostica completa di `text` col parser `defn`.

    Per ogni regola traccia grezzo→transform→value-map→finale e ne classifica
    l'esito; poi esegue la stessa pipeline del runtime (`build_validated_row`) e
    sovrappone gli errori del validator alle colonne giuste. Il verdetto
    (`placeable`) coincide con quello del runtime, così "Prova messaggio" non mente
    mai rispetto a ciò che il bridge scriverebbe."""
    registry = (value_maps_registry if value_maps_registry is not None
                else custom_pipeline._default_registry())
    fields = [_field_diag(rule, text, registry) for rule in defn.rules]
    # Ultima regola vince per target (come `apply_parser`): allinea l'overlay.
    by_target = {}
    for fd in fields:
        by_target[fd.target] = fd

    result = custom_pipeline.build_validated_row(
        defn, text, value_maps_registry=registry, provider=provider,
        mode=mode, require_price=require_price,
        name_mapping_profiles=name_mapping_profiles,
        market_mapping_profiles=market_mapping_profiles, id_resolver=id_resolver,
        source_language=source_language)
    _overlay_validator(result, by_target, fields)

    # Il runtime (`signal_router.resolve_row`) scrive SOLO se la riga è piazzabile
    # **e** qualcosa è stato estratto dal messaggio (gate di contenuto
    # `matches_message`, altrimenti `NO_CONTENT_MATCH`). Riflettiamolo nel verdetto,
    # così un parser a soli valori fissi che "validerebbe" non risulta PRONTO quando
    # il bridge in realtà lo scarterebbe (Codex).
    # `matches_message` fonde due cause in un unico `False`: nulla di estratto, OPPURE
    # condizioni di gate non soddisfatte (che ritornano `False` per prime). Per il runtime
    # è la stessa cosa — scarta e basta — ma per chi prova un messaggio sono due correzioni
    # OPPOSTE: nel primo caso si sistemano i delimitatori, nel secondo le condizioni.
    # Qui le separiamo: SOLO diagnosi, il gate resta quello di prima.
    condizioni_fallite = failed_conditions(defn, text)
    if condizioni_fallite:
        message_error = CONDITIONS_NOT_MET
    else:
        message_error = "" if matches_message(defn, text, mode) else NO_CONTENT_MATCH
    placeable = result.placeable and not message_error
    status = message_error if (message_error and result.placeable) else result.status
    return Diagnosis(placeable=placeable, status=status, fields=fields,
                     message_error=message_error,
                     status_reason=_motivo_stato(status, condizioni_fallite,
                                                 getattr(result, "detail", None)))


@dataclass
class TableRow:
    """Una riga della tabella diagnostica (vista del builder, CP-08b).

    Pensata per essere disegnata 1:1 dalla GUI senza altra logica: la formattazione
    leggibile (delimitatori, valore estratto, motivo) è già risolta qui."""

    target: str
    status: str            # "✅ OK" / "⛔ ERR"
    reason: str            # spiegazione leggibile (vuota se OK)
    start_after: str       # "Inizia dopo" leggibile
    end_before: str        # "Finisce prima" leggibile
    extracted: str         # valore estratto ("grezzo" o "grezzo → finale" se mappato)
    ok: bool = True
    required: bool = True
    banner: bool = False    # True = riga d'avviso a livello messaggio (NO_CONTENT_MATCH)


def _fmt_delim(rule) -> "tuple[str, str]":
    """('Inizia dopo', 'Finisce prima') leggibili: un valore fisso non estrae →
    '(valore fisso)'; vuoto → semantica di default; i newline come «↵» (fine riga)."""
    if rule is not None and rule.is_fixed():
        return ("(valore fisso)", "(valore fisso)")

    def show(v, empty_label):
        v = (v or "").replace("\n", "↵")
        return v if v != "" else empty_label
    start = show(getattr(rule, "start_after", ""), "(dall'inizio)")
    end = show(getattr(rule, "end_before", ""), "(fine riga)")
    return (start, end)


def diagnostic_table(diag: Diagnosis, defn: CustomParserDef) -> "list[TableRow]":
    """Righe della tabella diagnostica per "Prova messaggio" (CP-08b).

    Una riga per colonna del parser, con stato/motivo/delimitatori/valore estratto
    già formattati. Se il gate di contenuto fallisce (`NO_CONTENT_MATCH`) la prima
    riga è un **banner** d'avviso. Logica pura: la GUI la disegna e basta."""
    rules_by_target = {r.target: r for r in defn.rules}
    rows: "list[TableRow]" = []
    if diag.message_error:
        # Il motivo calcolato in `diagnose` è più preciso della spiegazione del solo codice
        # (per le condizioni di gate NOMINA quelle fallite): la tabella mostra quello, così
        # non dice meno del verdetto qui sopra. Ripiego sul codice se manca.
        rows.append(TableRow(
            target=diag.message_error, status="⛔ ERR",
            reason=diag.status_reason or explain(diag.message_error),
            start_after="", end_before="", extracted="", ok=False, banner=True))
    for fd in diag.fields:
        start, end = _fmt_delim(rules_by_target.get(fd.target))
        extracted = fd.raw if (fd.final == fd.raw or not fd.final) else f"{fd.raw} → {fd.final}"
        rows.append(TableRow(
            target=fd.target, status="✅ OK" if fd.ok else "⛔ ERR",
            reason="" if fd.ok else explain(fd.error),
            start_after=start, end_before=end, extracted=extracted,
            ok=fd.ok, required=fd.required))
    return rows


def format_report(diag: Diagnosis) -> str:
    """Report testuale leggibile della diagnostica (per la GUI / copia negli appunti)."""
    head = "PRONTO ✅" if diag.placeable else f"NON PRONTO ⛔  (status: {diag.status})"
    lines = [head]
    if diag.message_error:
        lines.append(f"• {diag.message_error} — "
                     f"{diag.status_reason or explain(diag.message_error)}")
    elif diag.status_reason:
        # Stati di riga (MAPPING_MISSING, INVALID_MISSING_PROVIDER…): l'intestazione
        # riporta la sigla, il motivo la rende azionabile anche negli appunti.
        lines.append(f"• {diag.status} — {diag.status_reason}")
    for fd in diag.fields:
        flag = "OK " if fd.ok else "ERR"
        kind = "obbl" if fd.required else "opz "
        chain = f"grezzo={fd.raw!r}"
        if fd.after_transform != fd.raw:
            chain += f" →tr={fd.after_transform!r}"
        if fd.final != fd.after_transform:
            chain += f" →map={fd.final!r}"
        why = explain(fd.error)
        reason = f" — {why}" if (why and not fd.ok) else ""
        lines.append(f"[{flag}] {fd.target} ({kind}): {fd.error}{reason}  |  {chain}")
    return "\n".join(lines)


# Codici che significano «la colonna è VUOTA e si può fare qualcosa» — gli unici per cui
# ha senso un motivo accanto al verdetto (gli errori di VALORE, es. quota non numerica,
# hanno già il loro testo e non compaiono fra i «mancanti»).
_CODICI_VUOTO = (START_NOT_FOUND, END_NOT_FOUND, TRANSFORM_FAILED,
                 VALUE_MAP_MISS, REQUIRED_EMPTY)

# Il valore mostrato viene dal messaggio Telegram: testo NON attendibile (rilievo
# convergente Fable 5 + GPT-5.5 sulla #245). Grezzo renderebbe illeggibile la riga
# sintetica del verdetto, e un valore multilinea potrebbe far sembrare «righe del
# verdetto» del testo scelto dall'utente — stessa classe di rischio dei control-char
# nel CSV (`csv_writer._sanitize_cell`). Qui: una riga sola, cappata, taglio VISIBILE.
_MAX_VALORE = 60


def _leggibile(valore) -> str:
    """Valore utente reso sicuro per UNA riga di verdetto.

    Tre passaggi, in quest'ordine (rilievi Fable 5 + GPT-5.5 sulla #245 — la prima
    versione prometteva nel docstring più di quanto facesse, e `str.split()` da solo
    appiattisce SOLO lo whitespace):

    1. **control-char e format-char via categoria Unicode** (`Cc`/`Cf`) → spazio: copre
       `\x00`, gli escape ANSI `\x1b[…` e soprattutto i **bidi override** (U+202E),
       che ribaltano visivamente tutto il testo a valle;
    2. **delimitatori del motivo neutralizzati**: un valore contenente `«`/`»` chiuderebbe
       la citazione e potrebbe far sembrare «testo del bridge» quello scelto da chi manda
       il messaggio — si sostituiscono con le virgolette singole angolari;
    3. whitespace compattato e taglio a `_MAX_VALORE` con «…» **esplicito** (un
       troncamento invisibile ingannerebbe chi legge).

    `None` → "" ; qualsiasi altro valore (anche `0`/`False`, che `or` avrebbe
    schiacciato a vuoto) viene reso con `str()` e conservato."""
    grezzo = "" if valore is None else str(valore)
    pulito = "".join(" " if unicodedata.category(ch) in ("Cc", "Cf") else ch
                     for ch in grezzo)
    pulito = pulito.replace("«", "‹").replace("»", "›")
    testo = " ".join(pulito.split())                 # \n \r \t e spazi ripetuti → uno
    if len(testo) > _MAX_VALORE:
        testo = testo[:_MAX_VALORE] + "…"            # lunghezza max = _MAX_VALORE + 1
    return testo


def motivi_campi_mancanti(diag: "Diagnosis") -> dict:
    """`{colonna: motivo azionabile}` per le colonne rimaste VUOTE.

    Nasce dall'ordine del proprietario (2026-08-04): «Prova messaggio» diceva solo
    «mancanti: SelectionName», lasciando indovinare fra delimitatori sbagliati,
    trasformazione che non sa leggere il testo, o value-map che non trova l'alias —
    tre correzioni completamente diverse. Il motivo include **il valore davvero
    letto**, che è ciò che chiude il caso a colpo d'occhio.

    Pura e testabile in CI: non tocca il motore, solo il testo mostrato."""
    motivi = {}
    for fd in diag.fields:
        if fd.error not in _CODICI_VUOTO:
            continue
        if fd.error == START_NOT_FOUND:
            motivi[fd.target] = "«Inizia dopo» non trovato nel messaggio"
        elif fd.error == END_NOT_FOUND:
            motivi[fd.target] = "«Finisce prima» non trovato dopo l'inizio"
        elif fd.error == TRANSFORM_FAILED:
            motivi[fd.target] = (f"la trasformazione «{fd.transform}» non ha saputo "
                                 f"leggere «{_leggibile(fd.raw)}»")
        elif fd.error == VALUE_MAP_MISS:
            motivi[fd.target] = (f"la value-map «{fd.value_map}» non ha trovato "
                                 f"«{_leggibile(fd.after_transform)}» nel dizionario")
        else:   # REQUIRED_EMPTY
            motivi[fd.target] = "nessun valore estratto"
    return motivi


# Etichette delle condizioni di gate, IDENTICHE a quelle della tendina nella GUI
# (`CustomParserPanel._COND_CONTAINS`/`_COND_NOT_CONTAINS`): chi legge il motivo deve
# ritrovare la stessa parola che ha scelto, non un sinonimo.
_COND_LABEL = {False: "contiene", True: "NON contiene"}


def _motivo_condizioni(condizioni) -> str:
    """Frase che NOMINA le condizioni di gate non soddisfatte.

    Il testo delle condizioni lo scrive l'utente, ma finisce accanto a testo del
    bridge: passa dalla stessa sanificazione del valore letto (`_leggibile`) —
    control-char, bidi override e delimitatori neutralizzati, lunghezza capata."""
    voci = [f"«{_COND_LABEL[bool(c.negate)]}: {_leggibile(c.text)}»" for c in condizioni]
    quali = ", ".join(voci)
    return (f"il messaggio è stato letto correttamente, ma non soddisfa "
            f"{'la condizione' if len(voci) == 1 else 'le condizioni'} di gate {quali}")


def _motivo_conflitto_mercati(detail) -> str:
    """Le coppie mercato/selezione che si contendono la frase, accodate al motivo generico.

    #282 A2. Il codice da solo dice *che tipo* di problema è; questo dice **quale**, ed è la
    differenza fra un'indagine e una correzione: l'utente ha davanti l'elenco delle righe del
    dizionario da disambiguare.

    I nomi arrivano dal `config.json`, che è editabile a mano: passano da `_leggibile` come il
    testo delle condizioni di gate: control-char, bidi override e delimitatori del motivo
    neutralizzati. Un mercato chiamato `«…»` non deve poter far sembrare «testo del bridge»
    quello che ha scritto l'utente.

    La resa la fa `market_mapping_store.descrivi_conflitto`, la stessa dell'avviso di
    configurazione: la coppia in conflitto si legge identica nei due posti.
    """
    from .market_mapping_store import descrivi_conflitto

    pulite = [(mt, _leggibile(mn), _leggibile(sn)) for mt, mn, sn in detail]
    return descrivi_conflitto(pulite)


def _motivo_stato(status: str, condizioni_fallite, detail=None) -> str:
    """Motivo azionabile dello STATO (non dei campi), calcolato in `diagnose`.

    Usa `_EXPLAIN` DIRETTAMENTE e non `explain()`: quello, per contratto, ripiega sul
    codice stesso quando non conosce la voce — utile in tabella, dannoso qui, dove
    produrrebbe «⛔ Non pronto (X) · X». Stato senza voce → nessun motivo, e il verdetto
    resta quello di prima invece di guadagnare rumore.

    `detail` (#282 A2) è il dettaglio specifico del `PipelineResult`, quando il codice ne porta
    uno: è lo schema di `INVALID_PRICE_BOUNDS`, che accompagna il codice con i soli limiti che
    offendono invece di nominarli tutti."""
    if condizioni_fallite:
        return _motivo_condizioni(condizioni_fallite)
    if status in _OK_CODES or status == validator.VALID:
        return ""
    motivo = _EXPLAIN.get(status, "")
    if status == custom_pipeline.MARKET_MAPPING_AMBIGUOUS and detail:
        # Fail-safe: se il dettaglio manca o arriva in una forma inattesa (config manomessa,
        # chiamante che non lo passa) resta il motivo generico — mai un verdetto che esplode.
        try:
            quali = _motivo_conflitto_mercati(detail)
        except (TypeError, ValueError):
            return motivo
        if quali:
            return f"{motivo}: {quali}"
    return motivo


def motivo_stato(diag: "Diagnosis") -> str:
    """Motivo azionabile dello stato complessivo, per la riga del verdetto.

    Ordine del proprietario (2026-08-04): stati come `MAPPING_MISSING`,
    `MARKET_MAPPING_MISSING` o `INVALID_MISSING_PROVIDER` arrivavano al verdetto come
    SIGLE NUDE — la spiegazione esisteva già in `_EXPLAIN` e si vedeva nella tabella
    diagnostica sotto, ma non nella riga che si legge per prima. Qui la si porta lì,
    senza letterali nuovi (regola 3: la fonte resta `_EXPLAIN`).

    Stringa vuota quando non c'è nulla da spiegare (stato OK, o codice senza voce):
    il verdetto non guadagna rumore quando il parser va bene."""
    return diag.status_reason
