"""Validazione del segnale prima della scrittura CSV (PR-10).

Gate esplicito sopra il riconoscimento (PR-06). Oltre ai campi nome/ID richiesti
dalla modalità, verifica due cose safety-critical:

- il **prezzo** (`Price`) è una quota valida, cioè un numero **> 1.0 e ≤ 1000.0**
  (una quota a 1.00 non dà guadagno e non è piazzabile; sotto 1 è una linea di
  mercato, non una quota; sopra 1000 non è una quota reale — è il tetto delle quote
  decimali Betfair — e con ogni probabilità è un misparse del separatore migliaia,
  es. «1.000.000», B1 audit #114). Il parametro `require_price` rende il controllo
  disattivabile: a runtime è guidato dalla riga Price del parser
  (`CustomParserDef.price_required`), non più da una chiave di config globale;
- il **BetType** è uno dei quattro lati validi `PUNTA`/`BANCA`/`BACK`/`LAY` (indifferenti su
  tutte le versioni BT/XT, issue #3); un lato sconosciuto — inclusi i termini ES `FAVOR`/`CONTRA`
  non ancora supportati — pizzerebbe la scommessa sbagliata, quindi è rifiutato (fail-closed).

Un segnale senza prezzo, con prezzo non valido o con lato sconosciuto NON deve
raggiungere XTrader. Il validatore non modifica la riga: la accetta o la scarta.
`Points` (moltiplicatore stake) NON va normalizzato a "1" e resta vuoto di default,
ma se un parser custom lo valorizza deve essere un numero **finito** in `0 < p ≤ 100`;
`Handicap`, se valorizzato, deve essere **finito** con `|h| ≤ 1000` (B5 #194: il vecchio
controllo «> 0» diceva VALID all'infinito, perché `float("9"*400)` è `inf` e `inf > 0`);
e i limiti `MinPrice`/`MaxPrice`, oltre a essere quote valide, non devono essere
**incoerenti** (intervallo invertito o che esclude `Price`).
"""

import re

from . import numbers_re, recognition

VALID = "VALID"

# Quota = decimale "semplice": cifre con al più un separatore (punto o virgola).
# Esclude esponenti ("1e2"), inf/nan, segni, separatori multipli: il contratto
# XTrader documenta quote decimali punto-normalizzate, non notazioni arbitrarie.
# Frammento decimale condiviso (anti-drift, audit L4).
_DECIMAL_PRICE = re.compile(r"^" + numbers_re.DECIMAL + r"$")
# Come sopra ma col segno: l'Handicap è l'unico campo del contratto che può essere negativo
# («-1,5» asiatico). Unico gate del formato Handicap dal B5 (#194) — prima erano due copie in
# `custom_pipeline`, ora entrambe delegano a `handicap_status`. Composto dallo stesso
# frammento condiviso — non una seconda scrittura a mano (B5, #194).
_SIGNED_DECIMAL_RE = re.compile(r"^" + numbers_re.SIGNED_DECIMAL + r"$")

# Tetto superiore della quota (B1 audit #114): 1000.0 è il massimo delle quote
# decimali Betfair. `_decimal_sep_to_point` (custom_pipeline) interpreta i separatori
# migliaia senza tetto di grandezza e il validatore controllava solo `> 1.0`: una
# quota assurda ma «valida» (es. «1.000.000» → 1000000.0, tipico misparse del
# separatore migliaia) sarebbe finita nella riga di scommessa CSV. Sopra questo tetto
# → INVALID_PRICE (fail-closed): mai una quota irreale verso XTrader.
_MAX_PRICE = 1000.0

# Tetti di `Points` e `Handicap` (B5, #194) — decisione del proprietario del 2026-07-31.
#
# Il buco chiuso qui NON era «manca un tetto», ma «il tetto che c'era non ferma l'infinito».
# La regex accetta solo cifre, quindi «inf» non passa per via testuale — ma `float("9"*400)`
# È `inf`, e `inf <= 0.0` è `False`: il controllo «rifiuta se ≤ 0» diceva VALID all'infinito.
# Perciò ogni soglia qui sotto è preceduta da `numbers_re.valore_finito`, che è il controllo
# di FINITEZZA, non un confronto in più.
#
# `Points` è il moltiplicatore dello stake quando la strategia XTrader ha spuntato «Modula lo
# Stake con dato Points del segnale se disponibile» (docs/xtrader_csv_contract.md → «Lato
# XTrader»): un Points fuori scala è uno STAKE fuori scala. 100 sta ampiamente sopra l'uso
# reale (i provider usano 1-10) e limita il danno di un valore errato a 100× invece che 1000×.
_MAX_POINTS = 100.0
# `Handicap` è la LINEA. 1000 copre ogni linea Betfair reale, comprese quelle grandi dei
# mercati a punti/run, senza rischiare falsi rifiuti su sport oggi non usati. Il tetto è sul
# VALORE ASSOLUTO: le linee negative sono legittime quanto le positive («-1,5» asiatico).
_MAX_HANDICAP = 1000.0

INVALID_MISSING_FIELDS = "INVALID_MISSING_FIELDS"   # campi nome/ID per la modalità
INVALID_MISSING_PRICE = "INVALID_MISSING_PRICE"
INVALID_PRICE = "INVALID_PRICE"
INVALID_BETTYPE = "INVALID_BETTYPE"
INVALID_POINTS = "INVALID_POINTS"           # Points valorizzato ma non un numero > 0 e ≤ _MAX_POINTS
# Stesso LETTERALE del gemello in `custom_pipeline` (che resta il codice emesso dal pipeline):
# qui serve perché `validate` gatea l'Handicap anche fuori dal pipeline. I due non divergono
# perché condividono `handicap_status` — la costante è l'etichetta, il predicato è uno solo.
INVALID_HANDICAP = "INVALID_HANDICAP"       # Handicap non numerico, o |h| oltre _MAX_HANDICAP
INVALID_PRICE_BOUNDS = "INVALID_PRICE_BOUNDS"  # Min/Max incoerenti (invertiti o escludono Price)

# Le due forme CANONICHE del contratto CSV (output, in italiano): universali su tutte le versioni
# Betting Toolkit / XTrader.
_CANONICAL_BETTYPES = ("PUNTA", "BANCA")
# I QUATTRO lati validi in INGRESSO → forma canonica. Indifferenti su TUTTE le versioni (conferma
# del supporto, issue #3): italiano PUNTA/BANCA e inglese BACK/LAY. Il mapping è NON ambiguo
# (BACK=back→PUNTA, LAY=lay→BANCA): un lato ignoto non viene MAI indovinato (invertire il lato della
# scommessa sarebbe catastrofico). I termini spagnoli (FAVOR/CONTRA) NON sono ancora supportati
# (arriveranno nei prossimi aggiornamenti del supporto): non sono in mappa → INVALID (fail-closed).
_BETTYPE_CANON = {"PUNTA": "PUNTA", "BANCA": "BANCA", "BACK": "PUNTA", "LAY": "BANCA"}

# Alias PUBBLICO di `_CANONICAL_BETTYPES` per i consumatori fuori da questo modulo (#182 PR A ⑧:
# la tendina BetType del pannello Parser offre esattamente questi valori). Alias e non copia:
# FONTE UNICA — se un domani il contratto ammettesse un terzo lato, la tendina lo eredita senza
# che nessuno debba ricordarsi di allinearla. Il nome privato resta per i chiamanti interni.
CANONICAL_BETTYPES = _CANONICAL_BETTYPES


def canonical_bettype(value) -> str:
    """Canonicalizza un BetType al lato ITALIANO del contratto CSV: `BACK`→`PUNTA`, `LAY`→`BANCA`,
    `PUNTA`/`BANCA` invariati (case-insensitive, spazi ignorati). `None`/vuoto → `""` (nessun
    lato); un valore ignoto resta invariato (solo uppercase). In entrambi i casi `bettype_status`
    lo respinge (fail-closed: mai un lato inventato). Usato al confine del contratto CSV così
    l'output resta canonico PUNTA/BANCA."""
    if value is None:
        return ""
    up = str(value).strip().upper()
    return _BETTYPE_CANON.get(up, up)


def _price_status(value) -> str:
    """VALID se `value` è una quota valida (`1.0 < price ≤ 1000.0`); altrimenti il
    codice di errore.

    `None` e stringa vuota contano come **prezzo mancante** (non malformato). Il tetto
    `_MAX_PRICE` (B1 audit #114) rifiuta le quote irreali da misparse del separatore
    migliaia (es. «1.000.000»), che superavano il solo controllo `> 1.0`.
    """
    if value is None:
        return INVALID_MISSING_PRICE
    s = str(value).strip()
    if not s:
        return INVALID_MISSING_PRICE
    # Forma decimale stretta: niente esponenti/inf/nan/testo (il parser custom
    # può estrarre testo arbitrario, es. "1e2"/"inf"/"abc").
    if not _DECIMAL_PRICE.match(s):
        return INVALID_PRICE
    # `valore_finito` invece di `float()` diretto: il prezzo era GIÀ al sicuro (`inf <=
    # _MAX_PRICE` è False → INVALID_PRICE), ma tenerlo sulla stessa fonte degli altri due
    # campi impedisce che un domani i tre confronti divergano di nuovo. L'equivalenza col
    # comportamento precedente è fissata da un test dedicato (B5, #194).
    price = numbers_re.valore_finito(s)
    if price is None:
        return INVALID_PRICE
    return VALID if 1.0 < price <= _MAX_PRICE else INVALID_PRICE


def price_status(value) -> str:
    """Pubblico: `VALID` se `value` è una quota valida (`1.0 < price ≤ 1000.0`),
    altrimenti il codice di errore (`INVALID_MISSING_PRICE`/`INVALID_PRICE`). Usato
    dalla diagnostica per attribuire un errore prezzo alla colonna giusta (Price vs
    Min/MaxPrice)."""
    return _price_status(value)


def bettype_status(value) -> str:
    """Pubblico: `VALID` se `value` è un BetType valido (`PUNTA`/`BANCA`/`BACK`/`LAY`,
    case-insensitive — indifferenti su tutte le versioni BT/XT, issue #3), altrimenti
    `INVALID_BETTYPE`. Vuoto/sconosciuto (inclusi i termini ES `FAVOR`/`CONTRA` non ancora
    supportati) = non valido: il lato è obbligatorio e non si indovina mai. Usato dalla
    diagnostica per segnalare la colonna BetType indipendentemente dagli altri."""
    # Delega la normalizzazione a `canonical_bettype` (fonte unica): un lato è valido sse
    # canonicalizza a una delle due forme del contratto → niente strip/upper duplicato qui.
    return VALID if canonical_bettype(value) in _CANONICAL_BETTYPES else INVALID_BETTYPE


def points_status(value) -> str:
    """Pubblico: `VALID` se `value` è un Points valido — vuoto (facoltativo) oppure un numero
    **finito** con `0 < points ≤ _MAX_POINTS` — altrimenti `INVALID_POINTS`. Usato dalla
    diagnostica per segnalare la colonna Points indipendentemente dagli altri errori.

    Il tetto e la finitezza sono B5 (#194): prima bastava `> 0`, e `float("9"*400)` è `inf`,
    che `> 0` è. Un Points infinito arrivava VALID fino al CSV, dove XTrader lo usa come
    moltiplicatore dello stake.
    """
    s = str(value).strip()
    if not s:
        return VALID
    if not _DECIMAL_PRICE.match(s):
        return INVALID_POINTS
    points = numbers_re.valore_finito(s)
    if points is None or not (0.0 < points <= _MAX_POINTS):
        return INVALID_POINTS
    return VALID


def handicap_status(value) -> str:
    """Pubblico: `VALID` se `value` è un Handicap valido — vuoto (facoltativo: il default del
    contratto è `"0"`) oppure un numero **finito** con `|handicap| ≤ _MAX_HANDICAP` —
    altrimenti `INVALID_HANDICAP`.

    Fonte unica del gate Handicap (B5, #194). Prima il controllo era la sola regex, scritta
    **due volte** in `custom_pipeline` (riga base e riga multi-riga derivata): correggere il
    tetto in un solo punto avrebbe lasciato il percorso multi-riga aperto — precisamente il
    modo in cui sono nati B6, B10 e B17. Entrambi i gate e `validate` chiamano questa.

    Il segno è ammesso e il tetto è sul valore ASSOLUTO: «-1,5» è un handicap asiatico
    legittimo quanto «+1,5».
    """
    s = str(value).strip()
    if not s:
        return VALID
    if not _SIGNED_DECIMAL_RE.match(s):
        return INVALID_HANDICAP
    handicap = numbers_re.valore_finito(s)
    if handicap is None or abs(handicap) > _MAX_HANDICAP:
        return INVALID_HANDICAP
    return VALID


def price_bounds_offenders(row: dict) -> tuple:
    """Colonne dei limiti che rendono l'intervallo Min/Max INCOERENTE (tupla vuota = coerente).

    Presuppone che i valori presenti siano già quote valide (validati a monte), quindi
    `float(...)` è sicuro. Restituisce SOLO i limiti che offendono, così la diagnostica non
    segnala un limite opzionale ASSENTE (Codex):
    - `MinPrice > MaxPrice` → `("MinPrice", "MaxPrice")` (entrambi: la relazione è fra loro);
    - `MinPrice > Price`     → `("MinPrice",)`;
    - `MaxPrice < Price`     → `("MaxPrice",)`.
    """
    def _num(col):
        v = str(row.get(col, "")).strip()
        return float(v.replace(",", ".")) if v else None

    price_v, min_v, max_v = _num("Price"), _num("MinPrice"), _num("MaxPrice")
    if min_v is not None and max_v is not None and min_v > max_v:
        return ("MinPrice", "MaxPrice")
    if price_v is not None:
        if min_v is not None and min_v > price_v:
            return ("MinPrice",)
        if max_v is not None and max_v < price_v:
            return ("MaxPrice",)
    return ()


def validate(row: dict, mode: str, require_price: bool = True):
    """Valuta una riga CSV già costruita.

    Ritorna una tupla `(status, detail)`:
    - status == VALID  → la riga può essere scritta;
    - INVALID_MISSING_FIELDS → `detail` è la lista dei campi nome/ID mancanti;
    - INVALID_BETTYPE        → `detail` è il BetType trovato;
    - INVALID_MISSING_PRICE / INVALID_PRICE → `detail` è il valore Price trovato.
    """
    missing = recognition.missing_fields(row, mode)
    if missing:
        return (INVALID_MISSING_FIELDS, missing)

    bet_type = str(row.get("BetType", "")).strip().upper()
    if bettype_status(bet_type) != VALID:
        return (INVALID_BETTYPE, bet_type)

    # Un `Price` valorizzato va SEMPRE validato; `require_price` governa solo se
    # un `Price` VUOTO è ammesso (flag = "prezzo opzionale", non "non validato").
    price_raw = str(row.get("Price", "")).strip()
    if price_raw:
        status = _price_status(price_raw)
        if status != VALID:
            return (status, price_raw)
    elif require_price:
        return (INVALID_MISSING_PRICE, "")

    # MinPrice/MaxPrice sono opzionali (possono restare vuoti), ma se valorizzati
    # devono essere quote valide: un limite malformato ("abc") o sotto/uguale a
    # 1.0 non deve raggiungere XTrader. (Il percorso hardcoded li lascia vuoti.)
    for col in ("MinPrice", "MaxPrice"):
        v = str(row.get(col, "")).strip()
        if v:
            status = _price_status(v)
            if status != VALID:
                return (status, v)

    # Points (moltiplicatore stake): il percorso hardcoded lo lascia vuoto, ma un
    # parser custom può estrarre testo arbitrario. Se valorizzato deve essere un
    # numero POSITIVO (> 0): "abc"/"-5"/"0"/"inf"/"1e2" non devono raggiungere XTrader.
    points_raw = str(row.get("Points", "")).strip()
    if points_status(points_raw) != VALID:
        return (INVALID_POINTS, points_raw)

    # Handicap (B5, #194): finora `validate` NON lo controllava affatto — il gate viveva solo
    # in `custom_pipeline`, in due copie. Metterlo anche qui lo rende il punto di strozzatura
    # che OGNI riga attraversa, qualunque percorso l'abbia costruita, invece di dipendere dal
    # fatto che ogni futuro chiamante si ricordi del gate. Il percorso hardcoded scrive sempre
    # "0" e i valori del dizionario sono numerici: nessuna riga legittima cambia esito.
    handicap_raw = str(row.get("Handicap", "")).strip()
    if handicap_status(handicap_raw) != VALID:
        return (INVALID_HANDICAP, handicap_raw)

    # Coerenza dei limiti di prezzo: oltre a essere singolarmente validi (sopra),
    # Min/Max non devono CONTRADDIRE loro stessi o `Price`. Un intervallo invertito
    # (Min > Max) o che ESCLUDE la quota selezionata (Min > Price, Max < Price) non
    # è usabile da XTrader → fail-closed. Bordi inclusivi ok. `detail` è la tupla dei
    # SOLI limiti che offendono, così la diagnostica non segnala un limite assente.
    offenders = price_bounds_offenders(row)
    if offenders:
        return (INVALID_PRICE_BOUNDS, offenders)

    return (VALID, None)


def is_valid(row: dict, mode: str, require_price: bool = True) -> bool:
    """True se la riga supera la validazione completa."""
    return validate(row, mode, require_price)[0] == VALID
