"""Dizionario di mappatura mercati: frase del provider → Mercato/Selezione XTrader.

Alcuni provider (canali Telegram) scrivono il mercato **a parole** ("0,5 HT") dentro il
messaggio. Questo modulo tiene **profili** di regole che leggono il mercato **da una
posizione precisa** del messaggio — tra i delimitatori ``Inizia dopo``/``Finisce prima``,
come una regola del Parser Personalizzato — e lo traducono nel Mercato/Selezione canonici
del **Catalogo XTrader**. I valori di mercato/selezione **non** sono testo libero: vanno
scelti dal Catalogo (vedi GUI), così ciò che finisce nel CSV è sempre canonico.

Perché a delimitatori e non "frase su tutto il messaggio": molti provider mettono in testa
un **banner/menu** con più mercati (es. ``P.Bet. 30/0,5HT/1,5HT/1 ASIATICO``); cercare la
frase nell'intero testo darebbe falsi match/ambiguità. Leggendo SOLO il campo delimitato
(es. fra «Quota» e «Prematch») si prende il mercato vero del segnale e si ignora il banner.

Modello dati (config, chiave ``market_mappings``)::

    cfg["market_mappings"] = {
        "<nome profilo>": [
            {"start_after": "Quota",      # "Inizia dopo": delimitatore sinistro
             "end_before": "Prematch",    # "Finisce prima": delimitatore destro ("" = fine riga)
             "phrase": "0,5 HT",          # testo mercato da riconoscere nel campo estratto
             "market_type": "FIRST_HALF_GOALS_05",
             "market_name": "1º tempo - Totale goal 0,5",
             "selection_name": "Over 0,5 goal"},
            ...
        ],
        ...
    }

Logica PURA su un ``dict`` di config: nessuna GUI, nessun I/O — la persistenza è del
chiamante (``config_store.save_config``), come ``name_mapping_store``/``provider_store``.
Le funzioni di modifica ritornano una COPIA della config, non mutano l'originale.

Sicurezza (safety-critical: un mercato sbagliato = scommessa sbagliata). Decisioni
del proprietario, vedi ``docs/audit/mercati_mapping_design.md``:
- **D2 fail-closed sull'ambiguità**: se più frasi combaciano e indicano mercati
  **diversi**, ``resolve_market`` ritorna stato ``"ambiguous"`` → il chiamante NON
  scrive nulla (niente mercato "a caso");
- **D3 match sul campo estratto**: il mercato si legge SOLO tra i delimitatori
  ``Inizia dopo``/``Finisce prima`` (non su tutto il messaggio), poi il testo mercato si
  confronta case-insensitive e su **confini di token** (no falsi positivi tipo "over" dentro
  "overflow"). Una voce **senza delimitatori** è **preservata** in config ma **non
  applicata** (``resolve_market`` la salta, fail-closed): la modalità "frase su tutto il
  messaggio" è rimossa, ma le voci vecchie non vengono cancellate (no perdita dati);
- nessun match → stato ``"none"`` (il chiamante decide il fallback, vedi precedenza D1
  nel runtime). ``resolve_market`` non inventa mai un mercato.

NB: la **precedenza D1** ("il dizionario vince" sulla regola-colonna) è una scelta del
**runtime** (``custom_pipeline``), non di questo store: qui si risolve solo la frase.
"""

import logging
import re
from collections import namedtuple

from . import dizionario, mapping_store_base, recognition
from .custom_parser_engine import extract_between

_LOG = logging.getLogger(__name__)

# Chiave di config che ospita i profili di mappatura mercati.
_STORE_KEY = "market_mappings"

# Esito della risoluzione di un mercato da una frase.
#   status: "ok"        → match univoco; `market` = {market_type, market_name, selection_name}
#           "ambiguous" → più frasi combaciano con mercati DIVERSI (fail-closed, D2); market=None
#           "none"      → nessuna frase combacia; market=None
MarketResolution = namedtuple("MarketResolution", ["status", "market"])


def _normalize_text(s) -> str:
    """Testo normalizzato per il confronto: spazi collassati + casefold (case-insensitive)."""
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _malformed_fields(entry: dict) -> list:
    """Coppie ``(campo, valore_grezzo)`` NON riconosciute di una voce mercato: per ora la
    sola ``language`` (epica #3 slice 5c) non-vuota e non ``IT``/``EN``/``ES``. Vuoto =
    agnostico intenzionale (vale per tutte le lingue), NON malformato. Predicato unico
    condiviso tra ``_clean_entry`` (scarto fail-closed) e ``malformed_entry_warnings``
    (avvisi GUI), così i due non possono divergere — stesso pattern di
    ``name_mapping_store._malformed_fields``."""
    out = []
    # language (epica #3 slice 5c): non-vuoto ma non IT/EN/ES → FAIL-CLOSED come nel
    # dizionario nomi. Un typo di lingua non deve allargare in silenzio la voce a "tutte le
    # lingue" (un mercato applicato a una lingua sbagliata = scommessa sbagliata).
    raw_language = str(entry.get("language", "") or "").strip()
    if raw_language and not recognition.normalize_source_language(raw_language):
        out.append(("language", raw_language))
    return out


def _clean_entry(entry) -> dict:
    """Normalizza una voce in ``{start_after, end_before, phrase, market_type, market_name,
    selection_name, language}`` (stringhe ripulite), o ``None`` se inutile.

    Una voce è valida se ha **testo mercato** (``phrase``), **market_name** e
    **selection_name**: senza, non può formare un mercato. I delimitatori ``start_after``/
    ``end_before`` sono **facoltativi a livello dati**: così una config vecchia senza
    delimitatori NON viene cancellata al load/save (niente perdita dati, CodeRabbit). È
    ``resolve_market`` a **non applicare** una voce senza delimitatori — la **salta**
    (fail-closed) — invece di eliminarla. Dei delimitatori si tolgono **solo spazi/tab** ai
    bordi (come ``_delim_pattern`` del Parser), **preservando i newline** (es. ``"\\nMercato:"``
    resta ancorato a inizio riga, Codex). ``market_type`` può essere vuoto (lo ricava
    ``_canonical_market`` dal catalogo).

    ``language`` (epica #3 slice 5c): lingua della fonte (``IT``/``EN``/``ES``); **vuoto** →
    ``""`` = agnostico (retro-compatibile con le voci salvate prima). Un valore non-vuoto ma
    **non riconosciuto** (typo) è FAIL-CLOSED come nel dizionario nomi: la voce viene
    **scartata** (mai allargata a tutte le lingue), con avviso in ``malformed_entry_warnings``."""
    if not isinstance(entry, dict):
        return None
    start_after = str(entry.get("start_after", "") or "").strip(" \t")
    end_before = str(entry.get("end_before", "") or "").strip(" \t")
    phrase = str(entry.get("phrase", "") or "").strip()
    market_type = str(entry.get("market_type", "") or "").strip()
    market_name = str(entry.get("market_name", "") or "").strip()
    selection_name = str(entry.get("selection_name", "") or "").strip()
    # `raw_language` ripulito UNA volta e condiviso con la validazione: `_malformed_fields`
    # valida `str(...).strip()`, quindi persistere lo STESSO valore ripulito evita ogni
    # divergenza tra ciò che si valida e ciò che si salva (Sourcery bug_risk #26).
    raw_language = str(entry.get("language", "") or "").strip()
    if not phrase or not market_name or not selection_name:
        return None
    if _malformed_fields(entry):                 # language typo → voce scartata (fail-closed)
        return None
    return {"start_after": start_after, "end_before": end_before, "phrase": phrase,
            "market_type": market_type, "market_name": market_name,
            "selection_name": selection_name,
            "language": recognition.normalize_source_language(raw_language)}


# CRUD condiviso (store refactor #114): le dieci funzioni identiche fra i due store vivono in
# `mapping_store_base`; qui si iniettano le TRE differenze dello store mercati — la chiave di
# config, il proprio `_clean_entry` (schema mercati) e il prefisso di log dei profili duplicati —
# e si legano le funzioni al modulo con le firme storiche. `_store`/`_norm_profile_name`/
# `_find_store_key` restano accessibili (li usano i resolver e i test) sull'implementazione condivisa.
_crud = mapping_store_base.make_profile_crud(
    store_key=_STORE_KEY, clean_entry=_clean_entry, dup_warn_prefix="market_mappings", logger=_LOG)
_store = _crud._store
_norm_profile_name = _crud._norm_profile_name
_find_store_key = _crud._find_store_key
profile_names = _crud.profile_names
get_entries = _crud.get_entries
entries_for_profiles = _crud.entries_for_profiles
set_entries = _crud.set_entries
add_profile = _crud.add_profile
delete_profile = _crud.delete_profile
rename_profile = _crud.rename_profile


def malformed_entry_warnings(cfg: dict) -> list:
    """Avvisi **non bloccanti** per la GUI/event log (epica #3 slice 5c): voci mercato con
    ``language`` non riconosciuta, che il resolver SCARTA (fail-closed). Il warning del
    logger Python non è visibile nell'app windowed: ``_start`` mostra QUESTI messaggi nel log
    eventi, così l'operatore scopre subito la voce disattivata invece che dal mercato non
    riconosciuto — stesso principio di ``name_mapping_store.malformed_entry_warnings``."""
    warnings = []
    for profile, rows in _store(cfg).items():
        if not isinstance(rows, (list, tuple)):
            continue
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            phrase = str(entry.get("phrase", "") or "").strip()
            market_name = str(entry.get("market_name", "") or "").strip()
            selection_name = str(entry.get("selection_name", "") or "").strip()
            if not phrase or not market_name or not selection_name:
                continue                      # voce incompleta: scartata comunque, senza avviso
            bad = _malformed_fields(entry)
            if bad:
                dove = ", ".join(f"{f}={v!r}" for f, v in bad)
                warnings.append(
                    f"Mappatura mercati «{_norm_profile_name(profile)}», voce «{phrase}»: "
                    f"{dove} non riconosciuto -> voce IGNORATA (fail-closed). "
                    f"Correggi il valore per riattivarla.")
    return warnings


def _canonical_market(market_name: str, selection_name: str, rows=None):
    """Risolve ``(market_name, selection_name)`` del config nella tupla **canonica** del
    Catalogo XTrader ``{market_type, market_name, selection_name}``, o ``None`` se la
    coppia non è valida.

    Validazione + canonicalizzazione safety-critical (design §5.3): il match col catalogo è
    case/spazio-insensitive (``dizionario.normalize``), ma ciò che si ritorna — e che il
    runtime scriverà nel CSV — sono **sempre i valori canonici del catalogo** (MarketType,
    MarketName, SelectionName), non quelli grezzi del config: così una config editata a
    mano con case/spazi diversi (o un ``market_type`` stantio) non produce mai una tupla che
    XTrader non riconosce. Mercato **fisso** + selezione **non dinamica** (Codex). ``rows``
    inietta un catalogo nei test; di default usa quello reale."""
    mn = str(market_name or "").strip()
    sn = str(selection_name or "").strip()
    if not mn or not sn:
        return None
    nmn = dizionario.normalize(mn)
    nsn = dizionario.normalize(sn)
    # P3-20 #76: guardia anti-ambiguità, leggendo i TIPI direttamente dalle voci del
    # catalogo (NON via `market_type_for_name`, che è first-match sui nomi normalizzati
    # e per due duplicati ritornerebbe lo stesso tipo, mascherando l'ambiguità). Oggi il
    # catalogo non ha MarketName duplicati; se in futuro due nomi normalizzati-uguali
    # finissero sotto MarketType DIVERSI, il primo-match sceglierebbe in silenzio un
    # mercato — e il CSV punterebbe un mercato potenzialmente sbagliato. Fail-closed:
    # con tipi divergenti nessuna risoluzione (meglio nessuna riga che quella sbagliata).
    matches = [m for m in dizionario.market_catalog(rows)
               if not m["dynamic"] and dizionario.normalize(m["MarketName"]) == nmn]
    if not matches:
        return None
    tipi = {m["MarketType"] for m in matches}
    if len(tipi) > 1:
        _LOG.warning(
            "market_mappings: MarketName %r AMBIGUO nel catalogo (%d voci, MarketType "
            "divergenti %s) -> risoluzione RIFIUTATA (fail-closed, P3-20 #76).",
            mn, len(matches), sorted(tipi))
        return None
    canon_market = matches[0]["MarketName"]
    for s in dizionario.selections_for_market(canon_market, rows):
        if s.get("dynamic") or not s.get("SelectionName"):
            continue
        if dizionario.normalize(s["SelectionName"]) == nsn:
            mtype = dizionario.market_type_for_name(canon_market, rows) or ""
            return {"market_type": mtype, "market_name": canon_market,
                    "selection_name": s["SelectionName"]}
    return None


def _phrase_in_text(phrase: str, text_norm: str) -> bool:
    """``True`` se ``phrase`` compare in ``text_norm`` (già normalizzato) come
    sottostringa su **confini di token**. I lookaround escludono dai confini sia i
    caratteri di parola (``\\w``) sia ``/`` e ``-``: così "over" non combacia dentro
    "overflow" **e** una frase corta come "x" non combacia dentro codici tipo "1/x" o
    "1-x" (HT/FT), evitando falsi positivi che imposterebbero il mercato sbagliato
    (Codex). Funziona comunque con frasi che finiscono con cifre/punteggiatura
    (es. "over 2.5" seguito da spazio o "!")."""
    p = _normalize_text(phrase)
    if not p:
        return False
    return re.search(r"(?<![\w/-])" + re.escape(p) + r"(?![\w/-])", text_norm) is not None


def resolve_market(text: str, profiles, rows=None, language=None) -> MarketResolution:
    """Risolve il mercato canonico XTrader dal mercato scritto dal provider nel ``text``.

    Per ogni voce il mercato si legge **da una posizione precisa** del messaggio: si estrae
    il testo tra i delimitatori ``start_after``/``end_before`` (stesso motore del Parser,
    ``extract_between``) e si verifica che il **testo mercato** (``phrase``) compaia in
    quel campo estratto (case-insensitive, a confini di token). Così un banner/menu altrove
    nel messaggio non crea falsi match (es. ``30/0,5HT/1,5HT/1`` non viene letto se il
    mercato vero sta tra «Quota» e «Prematch»). La coppia Mercato/Selezione dev'essere
    **coerente col Catalogo XTrader** (``_canonical_market``, §5.3): una voce incoerente
    (config a mano/bug) è ignorata, mai scritta. ``rows`` inietta un catalogo nei test.

    ``language`` (epica #3 slice 5c): lingua-fonte effettiva (``IT``/``EN``/``ES`` o
    ``None``/``""`` = nessun filtro = comportamento storico). Se valorizzata: le voci di
    un'ALTRA lingua vengono **scartate** (le agnostiche restano) e la voce della lingua
    ESATTA ha **priorità** sull'agnostica (tier), come il dizionario nomi (5b). Un dizionario
    tutto-agnostico continua a risolvere anche con la lingua-fonte impostata (retro-compat).
    Poi (D2):

    - 0 match → ``MarketResolution("none", None)``;
    - match che indicano **lo stesso** ``(market_type, market_name, selection_name)``
      → ``MarketResolution("ok", {...})``;
    - match che indicano mercati **diversi** → ``MarketResolution("ambiguous", None)``
      (fail-closed: il chiamante non scrive nulla, niente mercato a caso).
    """
    if not str(text or "").strip():
        return MarketResolution("none", None)
    wl = recognition.normalize_source_language(language)   # "" = nessun filtro-lingua (legacy)
    found = []                                             # (canon_tuple, entry_language)
    for entries in (profiles or []):
        for e in entries:
            sa = str(e.get("start_after", "") or "")
            eb = str(e.get("end_before", "") or "")
            ph = str(e.get("phrase", "") or "").strip()
            # Difesa ANCHE sul percorso runtime (i profili possono arrivare grezzi, non solo
            # ripuliti da _clean_entry): una voce senza testo mercato o senza alcun
            # delimitatore è ignorata qui (non applicata, fail-closed), così non può MAI
            # combaciare su tutto il messaggio (Sourcery/CodeRabbit). "Vuoto" = solo spazi/tab
            # ai bordi, come `_delim_pattern`: un delimitatore di soli newline conta.
            if not ph or (not sa.strip(" \t") and not eb.strip(" \t")):
                continue
            # Filtro-lingua (epica #3 slice 5c): con una lingua-fonte richiesta, una voce di
            # un'ALTRA lingua esatta è scartata (mai applicare un mercato di lingua sbagliata).
            # Le agnostiche (`""`) restano eleggibili. Senza filtro (`wl` vuoto) nessuno scarto
            # → comportamento storico invariato.
            el = str(e.get("language", "") or "")
            if wl and el and el != wl:
                continue
            # Leggi il mercato SOLO dalla posizione delimitata (niente scansione dell'intero
            # messaggio): i delimitatori RAW vanno a extract_between, che preserva i newline
            # (ancoraggio a inizio riga, Codex); poi il testo mercato si confronta sul campo
            # normalizzato. I delimitatori sono case-sensitive come nel Parser.
            region = extract_between(text, sa, eb)
            if not region:
                continue
            if not _phrase_in_text(e.get("phrase", ""), _normalize_text(region)):
                continue
            # Risolvi nella tupla CANONICA del catalogo (type+nomi esatti, ignorando i
            # valori grezzi del config): una coppia incoerente → None → IGNORATA, mai
            # scritta; una coppia valida ma non-canonica (case/spazi) → valori canonici,
            # così XTrader riconosce sempre la tupla (design §5.3, Codex).
            canon = _canonical_market(e.get("market_name", ""), e.get("selection_name", ""), rows)
            if canon is None:
                continue
            found.append(((canon["market_type"], canon["market_name"],
                           canon["selection_name"]), el))
    if not found:
        return MarketResolution("none", None)
    # Tier lingua (epica #3 slice 5c): se è richiesta una lingua-fonte e c'è almeno un match
    # della lingua ESATTA, si usano SOLO quelli — un match agnostico non deve creare una falsa
    # ambiguità contro la voce della lingua giusta (mirror del tier del dizionario nomi). Senza
    # filtro (`wl` vuoto) il set resta invariato → ambiguità/risultato identici al legacy.
    if wl and any(el == wl for _, el in found):
        found = [(canon, el) for canon, el in found if el == wl]
    canon_set = {canon for canon, _ in found}
    if len(canon_set) > 1:
        return MarketResolution("ambiguous", None)
    mt, mn, sn = next(iter(canon_set))
    return MarketResolution("ok", {"market_type": mt, "market_name": mn,
                                   "selection_name": sn})
